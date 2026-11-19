"""Synchronous ETOP cloud client for a single ThermoTouch thermostat.

Blocking sockets; Home Assistant calls these from an executor. Each call is a short, fresh
cloud session: register with a unique app id, authenticate with the device token, then read
state or send a command. See PROTOCOL.md in the thermotouch-bridge repo.
"""
from __future__ import annotations

import socket
import time

try:
    from . import decode, protocol
except ImportError:  # standalone (tests)
    import decode, protocol

CLOUD_HOST = "18.197.22.220"          # etop3.etopcontrols.com
CLOUD_PORT = 2026

MODE_CODES = {v: k for k, v in decode.MODE_NAMES.items()}
RAIL_CODES = {v: k for k, v in decode.RAIL_NAMES.items() if not v.startswith("0x")}


class SlotBusy(Exception):
    """The device is serving another app session (the vendor app) and refused our read."""


class ThermoTouchError(Exception):
    pass


def _frames(sock, fr, seconds):
    """Yield decoded-ready frames arriving within `seconds`."""
    sock.settimeout(1)
    end = time.time() + seconds
    while time.time() < end:
        try:
            data = sock.recv(4096)
        except socket.timeout:
            continue
        except OSError:
            break            # peer closed / reset: end of stream
        if not data:
            break
        for f in fr.feed(data):
            yield f


class Framer:
    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf.extend(data)
        while len(self.buf) >= 2:
            n = (self.buf[0] << 8) | self.buf[1]
            if n < 8 or n > 4096:
                self.buf.pop(0)
                continue
            if len(self.buf) < n:
                break
            msg = bytes(self.buf[:n])
            del self.buf[:n]
            yield msg


class ThermoTouchClient:
    def __init__(self, mac, token, command_template=None,
                 host=CLOUD_HOST, port=CLOUD_PORT):
        self.host = host
        self.port = int(port)
        self.device = bytes.fromhex(mac.replace(":", ""))
        self.token = bytes.fromhex(token.replace(":", "").replace(" ", ""))
        self.template = bytes.fromhex(command_template) if command_template else None
        if len(self.device) != 6:
            raise ThermoTouchError("MAC must be 6 bytes")
        if len(self.token) != 6:
            raise ThermoTouchError("token must be 6 bytes (12 hex chars)")

    # -- session ---------------------------------------------------------
    def _open(self, app):
        sock = socket.create_connection((self.host, self.port), timeout=10)
        fr = Framer()
        sock.sendall(protocol.app_register(app))
        reply = None
        end = time.time() + 10
        while reply is None and time.time() < end:
            data = sock.recv(4096)
            if not data:
                sock.close()
                raise ThermoTouchError("cloud closed the connection after register")
            for f in fr.feed(data):
                if not decode.is_session0(f) and reply is None:
                    reply = f
        if reply is None:
            sock.close()
            raise ThermoTouchError("no register reply")
        sess, key, _ = protocol.key_from_reply(reply, app)
        ks = decode.KeyStore()
        ks.keys[sess.hex()] = key
        return sock, fr, app, sess, key, ks

    # -- reads -----------------------------------------------------------
    def poll(self, attempts=3):
        """Read the full state. Returns a dict, or raises SlotBusy if the vendor app holds
        the session. Retries the cloud's occasional register drop."""
        last = None
        for _ in range(attempts):
            app = protocol.unique_app_id()
            auth = protocol.auth_payload(self.device, app, self.token)
            try:
                sock, fr, app, sess, key, ks = self._open(app)
            except ThermoTouchError as e:
                last = e
                time.sleep(1.5)
                continue
            try:
                for p in (auth, protocol.get_payload(self.device, app, protocol.GET_STATE)):
                    sock.sendall(protocol.app_upstream(sess, key, app, p))
                    time.sleep(0.2)
                state, authed = {}, False
                for f in _frames(sock, fr, 8.0):
                    r = decode.decode_frame(f, ks)
                    if not r or r.get("origin") != "device":
                        continue
                    if len(f) >= 122:
                        authed = True
                    if r.get("setpoint_c") is not None:
                        state = _state_from(r)
                if state:
                    return state
                if not authed:
                    raise SlotBusy("no state; the vendor app may be holding the session")
                last = ThermoTouchError("authenticated but no state frame")
            finally:
                sock.close()
            time.sleep(1.0)
        raise last or SlotBusy("no state returned")

    # -- writes ----------------------------------------------------------
    def set(self, setpoint=None, mode=None, rail=None):
        if self.template is None:
            raise ThermoTouchError("writing needs a command_template (capture one via the bridge)")
        app = protocol.unique_app_id()
        auth = protocol.auth_payload(self.device, app, self.token)
        payload = protocol.readdress(
            protocol.patch_command(self.template, setpoint=setpoint, mode=mode, rail=rail),
            self.device, app)
        sock, fr, app, sess, key, ks = self._open(app)
        try:
            for p in (auth, payload):
                sock.sendall(protocol.app_upstream(sess, key, app, p))
                time.sleep(0.2)
            accepted = False
            for f in _frames(sock, fr, 4.0):
                r = decode.decode_frame(f, ks)
                if r and r.get("origin") == "device" and len(f) >= 122:
                    accepted = True        # the device took the session (auth ok)
            if not accepted:
                # the thermostat refused the session (status 0x13): the vendor app is
                # holding its single slot. The command did not apply.
                raise SlotBusy("thermostat busy; close the vendor app and retry")
        finally:
            sock.close()
        return True


def _state_from(r):
    """Map a decoded device report to a clean state dict."""
    out = {
        "setpoint_c": r.get("setpoint_c"),
        "mode": r.get("mode"),
        "presets": r.get("presets"),
        "rail": r.get("rail"),
        "rail_running": r.get("rail_running"),
        "heating": r.get("heating"),
        "room_c": r.get("room_c"),
    }
    return {k: v for k, v in out.items() if v is not None}
