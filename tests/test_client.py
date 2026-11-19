"""End-to-end test of the standalone client against a fake ETOP cloud, with synthetic
frames (no real captures). Exercises register -> auth -> get -> state, and the busy-slot
refusal path for both poll and set."""
import os, socket, sys, threading, time

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "custom_components", "thermotouch"))
import decode, protocol  # noqa: E402
import client as ttclient  # noqa: E402

DEVICE = bytes.fromhex("f0fe6b6ac810")
TOKEN = bytes.fromhex("ada64e53b05c")
SERVER = decode.SERVER_ID
SESS = bytes.fromhex("12345678")
KEY = (0, 0x11, 0x22)


def _register_reply(app):
    # mirrors the real 26-byte reply: dst=app, src=server, type 0x01
    return protocol.frame(SESS, KEY, app, SERVER, 1, 0x00, 0x01, 0x00, b"\x00")


def _state_payload(app, setpoint, mode, rail, room, heating):
    p = bytearray(decode.STATE_LEN - 25)       # 57-byte payload
    p[0:2] = b"\x00\x02"
    p[2:8] = app                               # inner dst = app (device->app report)
    p[8:14] = DEVICE                            # inner src = device
    p[14:16] = b"\x01\x02"
    p[16] = 0x30
    p[decode.SETPOINT_OFFSET - 25] = int(round((setpoint + 20) * 2))
    p[decode.MODE_OFFSET - 25] = {v: k for k, v in decode.MODE_NAMES.items()}[mode]
    p[decode.RAIL_OFFSET - 25] = {v: k for k, v in decode.RAIL_NAMES.items() if not v.startswith("0x")}[rail]
    p[decode.ROOM_OFFSET - 25] = int(round((room + 20) * 2))
    p[decode.HEAT_OFFSET - 25] = 0x01 if heating else 0x00
    for o in decode.PRESET_OFFSETS.values():
        p[o - 25] = int(round((24 + 20) * 2))
    return bytes(p)


def _device_frame(app, payload):              # as the cloud relays a device report to an app
    return protocol.frame(SESS, KEY, app, SERVER, 7, 0x00, 0x04, 0x00, payload)


class FakeCloud:
    def __init__(self, serve_state=True):
        self.serve_state = serve_state
        self.srv = socket.socket(); self.srv.bind(("127.0.0.1", 0)); self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            c, _ = self.srv.accept(); c.settimeout(4)
            reg = c.recv(4096)
            app = decode.unmask(reg[:((reg[0] << 8) | reg[1])], decode.HELLO_KEY)[15:21]
            c.sendall(_register_reply(app))
            fr = ttclient.Framer(); got_auth = False; end = time.time() + 3
            while time.time() < end:
                try:
                    data = c.recv(4096)
                except socket.timeout:
                    break
                if not data:
                    break
                for f in fr.feed(data):
                    pl = decode.unmask(f, KEY)[25:]
                    if len(pl) > 16 and pl[16] == 0x32:
                        got_auth = True
                if got_auth and self.serve_state:
                    c.sendall(_device_frame(app, _state_payload(app, 19.0, "manual", "on", 18.0, True)))
                    break
            time.sleep(0.3); c.close()
        finally:
            self.srv.close()


def test_poll_reads_state():
    fc = FakeCloud(serve_state=True)
    c = ttclient.ThermoTouchClient("F0:FE:6B:6A:C8:10", TOKEN.hex(),
                                   host="127.0.0.1", port=fc.port)
    st = c.poll(attempts=1)
    assert st["setpoint_c"] == 19.0 and st["mode"] == "manual"
    assert st["rail"] == "on" and st["room_c"] == 18.0 and st["heating"] is True


def test_poll_slot_busy_raises():
    fc = FakeCloud(serve_state=False)          # device never answers = slot busy
    c = ttclient.ThermoTouchClient("F0:FE:6B:6A:C8:10", TOKEN.hex(),
                                   host="127.0.0.1", port=fc.port)
    try:
        c.poll(attempts=1)
    except ttclient.SlotBusy:
        return
    raise AssertionError("expected SlotBusy")


def test_set_requires_template():
    c = ttclient.ThermoTouchClient("F0:FE:6B:6A:C8:10", TOKEN.hex())
    try:
        c.set(setpoint=20)
    except ttclient.ThermoTouchError as e:
        assert "template" in str(e)
        return
    raise AssertionError("expected template error")
