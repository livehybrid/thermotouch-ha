"""
ThermoTouch / ETOP cloud-protocol decoder.

Transport: TCP to etop3.etopcontrols.com:2026. Every message is a length-prefixed frame.
Both the thermostat and the vendor phone app speak this protocol to the cloud.

Mask (credit: external analysis, see etop_decode.py):
    one byte of each 2-byte pair is masked, the other is clear:
        plain = ((cipher ^ B) - A) & 0xFF
    * session-0 frames (registration, before a session id is assigned): odd offsets,
      fixed key A=0x09 B=0xD5
    * in-session frames: a per-session key (A, B) AND a per-session parity (odd or even)

Unmasked layout:
    0-1   length (big-endian, whole frame)
    2-5   session id (00000000 before a session is assigned)
    6-7   per-message check (not understood)
    8     0x02
    9-14  destination id   } a client id (thermostat Wi-Fi MAC, or the app's id) and the
    15-20 source id        } server id 00:26:C7:30:E9:EA
    21    sequence number
    23    message type: 01 register, 02 heartbeat, 03 ack, 04 app data (app <-> thermostat,
          relayed by the cloud), 10 time sync, 11 status
    25..  payload
Type-04 payload starts with an inner header: [2 bytes][inner dst 6][inner src 6], naming the
thermostat and the app at either end, whichever connection the frame travels on.

Key recovery: the server id is constant and the client ids are learned from the fixed-key
register frames that open each connection, so each session's (parity, A, B) is recovered
from known plaintext with no need to know how it is derived.

Temperatures everywhere: plain = 2 * (T + 20)  ->  T = byte / 2 - 20.
Decoded fields of the 82-byte type-04 frame (sent by the app as a command and by the
thermostat as a report; verified against labelled changes in the app):
    62  setpoint                                   verified (9 changes)
    63  mode: 00 comfort 01 eco 02 manual 03 holiday 04 schedule      verified (5 modes)
    64-67  comfort / eco / manual / holiday preset  verified (24/16/20/10 as configured)
    49  heating relay, device reports only          strongly indicated (closes ~11s after a
                                                    setpoint above room temperature)
    47-48  room/floor temperature?                  unverified (constant 20.0 in capture)
    68-70  further presets (18 / 5 frost / 27 max?) unverified
Other device-originated type-04 frames: 61 B heat-state report, 64 B limits, 103 B weekly
schedule (6 periods x 3 day groups), 122 B device info incl. firmware build stamp.
"""

SERVER_ID = bytes.fromhex("0026C730E9EA")
HELLO_KEY = (1, 0x09, 0xD5)          # (parity, A, B) for session-0 frames
DEVICE_OUI = b"\xf0\xfe\x6b"          # Shanghai High-Flying (the thermostat's Wi-Fi module)
ZERO_ID = b"\x00" * 6

TYPE_NAMES = {0x01: "register", 0x02: "heartbeat", 0x03: "ack", 0x04: "app-data",
              0x10: "time-sync", 0x11: "status"}

STATE_LEN = 0x52
SETPOINT_OFFSET = 62
MODE_OFFSET = 63
PRESET_OFFSETS = {"comfort": 64, "eco": 65, "manual": 66, "holiday": 67}   # verified vs labels
PRESET_UNVERIFIED = {"preset_68": 68, "frost": 69, "max": 70}
SENSOR_OFFSETS = (47, 48)          # room temperature (probable): tracked 17.5 -> 19.0 as the room warmed
ROOM_OFFSET = 47
HEAT_OFFSET = 49                   # bitfield in device reports: bit0 floor heating, bit1 towel rail running
RAIL_OFFSET = 72                   # towel-rail / radiator setting (verified 2026-11-19 18:48)
RAIL_NAMES = {0x00: "off", 0x01: "on", 0x02: "timer", 0x03: "1h", 0x04: "2h", 0x05: "4h"}   # 02 = app's Rail Timer (schedule) icon
MODE_NAMES = {0x00: "comfort", 0x01: "eco", 0x02: "manual", 0x03: "holiday", 0x04: "schedule"}


def temp_c(byte: int):
    """Temperature encoding used throughout: plain = 2 * (T + 20)."""
    return byte / 2.0 - 20


def fmt_id(b: bytes) -> str:
    return ":".join("%02X" % v for v in b)


def is_device_id(b: bytes) -> bool:
    return len(b) == 6 and b[:3] == DEVICE_OUI


def split_frames(blob: bytes):
    """Cut a TCP read into whole frames using each 2-byte length prefix."""
    i = 0
    while i + 2 <= len(blob):
        n = (blob[i] << 8) | blob[i + 1]
        if n < 8 or i + n > len(blob):
            break
        yield blob[i:i + n]
        i += n


def unmask(frame: bytes, key) -> bytes:
    parity, a, b = key
    out = bytearray(frame)
    start = 8 if parity == 0 else 9
    for i in range(start, len(frame), 2):
        out[i] = ((frame[i] ^ b) - a) & 0xFF
    return bytes(out)


def session_id(frame: bytes) -> str:
    return frame[2:6].hex() if len(frame) >= 6 else ""


def is_session0(frame: bytes) -> bool:
    return len(frame) >= 6 and frame[2:6] == b"\x00\x00\x00\x00"


def crc16_arc(data: bytes) -> int:
    """CRC-16/ARC (poly 0x8005 reflected, init 0). Frame bytes 6-7 hold this over the
    UNMASKED frame from byte 8 to the end, big-endian."""
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c


def crc_ok(p: bytes) -> bool:
    return len(p) > 8 and crc16_arc(p[8:]) == ((p[6] << 8) | p[7])


def _check(p: bytes, known_ids):
    """0 = reject; otherwise a score: server id (+1), known client id (+2), header constants (+1).
    A plaintext whose CRC does not verify is rejected outright: that alone pins the key."""
    if len(p) < 24 or p[8] != 0x02 or not crc_ok(p):
        return 0
    dst, src = p[9:15], p[15:21]
    if SERVER_ID not in (dst, src):
        return 0
    upstream = dst == SERVER_ID
    other = src if upstream else dst
    score = 1
    if other in known_ids:
        score += 2
    # header constants: byte 22 is 0x02 upstream / 0x00 downstream,
    # byte 24 is 0xFF upstream / 0x00 or 0x30 downstream
    if upstream and p[22] == 0x02 and p[24] == 0xFF:
        score += 1
    if not upstream and p[22] == 0x00 and p[24] in (0x00, 0x30):
        score += 1
    return score


def candidate_keys(frame: bytes, known_ids=()):
    """The best-scoring (parity, A, B) consistent with known plaintext.

    B is derived from one known byte for each A, so this is a few hundred checks:
      parity 0 (even offsets masked): byte 8 is 0x02
      parity 1 (odd offsets masked):  byte 9 is the first byte of dst (server 0x00, or a known id)
    """
    if len(frame) < 24:
        return set()
    anchors1 = {0x00, DEVICE_OUI[0]} | {i[0] for i in known_ids}
    scored = {}
    for parity, off, anchors in ((0, 8, (0x02,)), (1, 9, tuple(anchors1))):
        for anchor in anchors:
            for a in range(0x80):
                b = ((anchor + a) & 0xFF) ^ frame[off]
                key = (parity, a, b)
                sc = _check(unmask(frame, key), known_ids)
                if sc:
                    scored[key] = max(sc, scored.get(key, 0))
    if not scored:
        return set()
    best = max(scored.values())
    return {k for k, v in scored.items() if v == best}


class KeyStore:
    """Learns client ids from session-0 frames and per-session keys from known plaintext."""

    def __init__(self):
        self.device_ids = set()     # thermostats (High-Flying MACs)
        self.app_ids = set()        # app clients
        self.keys = {}              # session id -> (parity, A, B), confirmed unique
        self._cands = {}            # session id -> remaining candidate set

    @property
    def known_ids(self):
        return self.device_ids | self.app_ids

    def learn_session0(self, frame: bytes):
        p = unmask(frame, HELLO_KEY)
        if len(p) >= 21 and p[8] == 0x02:
            for ident in (p[9:15], p[15:21]):
                if ident in (SERVER_ID, ZERO_ID):
                    continue
                (self.device_ids if is_device_id(ident) else self.app_ids).add(ident)
        return p

    def key_for(self, frame: bytes):
        sid = session_id(frame)
        if sid in self.keys:
            return self.keys[sid]
        c = candidate_keys(frame, self.known_ids)
        if not c:
            return None
        prev = self._cands.get(sid)
        c = (prev & c) if prev and (prev & c) else c
        self._cands[sid] = c
        if len(c) == 1:
            self.keys[sid] = next(iter(c))
            return self.keys[sid]
        return sorted(c)[0]     # best guess until another frame disambiguates


def decode_frame(frame: bytes, ks: KeyStore):
    """Return a dict describing the frame, or None if it cannot be unmasked."""
    if len(frame) < 24:
        return None
    if is_session0(frame):
        p = ks.learn_session0(frame)
        key, confident = HELLO_KEY, True
    else:
        key = ks.key_for(frame)
        if key is None:
            return None
        p = unmask(frame, key)
        confident = session_id(frame) in ks.keys

    dst, src = p[9:15], p[15:21]
    if dst == SERVER_ID:
        client, upstream = src, True
    elif src == SERVER_ID:
        client, upstream = dst, False
    else:                               # session-0 register: destination all zeros
        client, upstream = (src if dst == ZERO_ID else dst), True

    out = {
        "session": session_id(frame),
        "len": len(frame),
        "type": p[23],
        "type_name": TYPE_NAMES.get(p[23], "0x%02x" % p[23]),
        "seq": p[21],
        "client": fmt_id(client),
        "client_kind": "device" if is_device_id(client) else "app",
        "upstream": upstream,
        "key": "%s/%02X/%02X" % ("even" if key[0] == 0 else "odd", key[1], key[2]),
        "key_confident": confident,
        "payload": p[25:].hex(),
    }
    device = client if is_device_id(client) else None
    origin = out["client_kind"] if upstream else "cloud"

    if p[23] == 0x04 and len(p) >= 39:
        idst, isrc = p[27:33], p[33:39]
        out["inner_dst"], out["inner_src"] = fmt_id(idst), fmt_id(isrc)
        for ident in (idst, isrc):
            if is_device_id(ident):
                device = device or ident
        origin = "device" if is_device_id(isrc) else "app"

    out["device"] = fmt_id(device) if device else None
    out["device_known"] = device in ks.device_ids if device else False
    out["origin"] = origin
    out["from_device"] = upstream and out["client_kind"] == "device"

    if p[23] == 0x01 and is_session0(frame) and len(p) >= 42:
        out["ip"] = ".".join(str(v) for v in p[26:30])
        out["port"] = int.from_bytes(p[30:32], "big")
    if p[23] == 0x10 and len(p) >= 33:
        yy, mo, dd, dow, hh, mi, ss = p[26:33]
        out["time"] = "20%02d-%02d-%02d %02d:%02d:%02d" % (yy, mo, dd, hh, mi, ss)
    if p[23] == 0x04 and len(p) == STATE_LEN:
        sp = temp_c(p[SETPOINT_OFFSET])
        if 0 <= sp <= 40:
            out["setpoint_c"] = sp
            out["setpoint_source"] = "app command" if origin == "app" else "device report"
            out["mode"] = MODE_NAMES.get(p[MODE_OFFSET], "0x%02x" % p[MODE_OFFSET])
            out["presets"] = {k: temp_c(p[o]) for k, o in PRESET_OFFSETS.items()}
            out["presets_unverified"] = {k: temp_c(p[o]) for k, o in PRESET_UNVERIFIED.items()}
            out["sensors_unverified"] = [temp_c(p[o]) for o in SENSOR_OFFSETS]
            out["rail"] = RAIL_NAMES.get(p[RAIL_OFFSET], "0x%02x" % p[RAIL_OFFSET])
            if origin == "device":
                out["heating"] = bool(p[HEAT_OFFSET] & 0x01)
                out["rail_running"] = bool(p[HEAT_OFFSET] & 0x02)
                out["room_c"] = temp_c(p[ROOM_OFFSET])
    elif p[23] == 0x04 and len(p) == 61 and origin == "device":
        out["heating"] = bool(p[HEAT_OFFSET] & 0x01)              # periodic heat-state report
        out["rail_running"] = bool(p[HEAT_OFFSET] & 0x02)
        out["sensors_unverified"] = [temp_c(p[o]) for o in SENSOR_OFFSETS]
        out["room_c"] = temp_c(p[ROOM_OFFSET])
    elif p[23] == 0x04 and len(p) == 122 and origin == "device":
        txt = bytes(c for c in p[80:96] if 32 <= c < 127).decode("ascii", "replace").strip()
        if txt:
            out["firmware"] = txt                                  # e.g. "20170915 192654"
    elif p[23] == 0x04 and len(p) == 103 and origin == "device" and p[46] == 0x05:
        # weekly schedule: 3 day-groups x 6 periods; times as (hour, minute) pairs, temps x 2+40
        body = p[47:85]
        out["schedule_raw"] = body.hex()
        temps = p[85:103]
        out["schedule_temps"] = [temp_c(b) for b in temps]
    return out


# --- backwards-compatible helper (single-frame, used by older callers/tests) ---
def parse_state(pkt: bytes, ks: KeyStore = None):
    ks = ks or KeyStore()
    d = decode_frame(pkt, ks)
    if d and "setpoint_c" in d:
        return {"session": d["session"], "target_c": d["setpoint_c"],
                "heating_flag": d.get("heating"), "mode": d.get("mode"), "device": d["device"]}
    return None
