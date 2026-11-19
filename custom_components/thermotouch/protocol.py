"""Build ETOP cloud-protocol frames (the write side of decode.py).

Every frame is   [len 2][session 4][crc 2][0x02][dst 6][src 6][seq][b22][type][b24][payload]
with the CRC-16/ARC of the UNMASKED bytes 8.. in bytes 6-7, then the session mask applied.

App -> thermostat messages are type 04. Their payload is
    [00 02][inner dst 6][inner src 6][00 01][class][...]
class 0x32 = auth (carries the device's pairing token), 0x30 = get/set.
The cloud forwards the payload unchanged and only rewrites the outer header, so the
same payload works whether we hand it to the cloud (as an app) or straight to the
thermostat (inside a relayed connection).

We never invent a payload. Commands are made by patching the setpoint/mode bytes of a
real app command captured from this thermostat, so every other byte is one the device
has already accepted.
"""
from decode import (SERVER_ID, HELLO_KEY, crc16_arc, unmask, candidate_keys,
                    SETPOINT_OFFSET, MODE_OFFSET, MODE_NAMES, RAIL_OFFSET, RAIL_NAMES)

TYPE_REGISTER = 0x01
TYPE_APPDATA = 0x04
HEADER_LEN = 25
ZERO_ID = b"\x00" * 6
MODE_CODES = {v: k for k, v in MODE_NAMES.items()}
RAIL_CODES = {v: k for k, v in RAIL_NAMES.items() if not v.startswith("0x")}
MIN_C, MAX_C = 5.0, 35.0

# Session-0 register sent by the vendor app (payload only; identical every time we saw it).
APP_REGISTER_PAYLOAD = bytes.fromhex(
    "00c00000064f24" + "00" * 33 + "02")


def mask(plain: bytes, key) -> bytes:
    """Inverse of decode.unmask: c = ((p + A) & 0xFF) ^ B on the masked byte positions."""
    parity, a, b = key
    out = bytearray(plain)
    for i in range(8 if parity == 0 else 9, len(out), 2):
        out[i] = ((plain[i] + a) & 0xFF) ^ b
    return bytes(out)


def seal(plain: bytes, key) -> bytes:
    """Set length and CRC on an unmasked frame, then mask it."""
    p = bytearray(plain)
    p[0], p[1] = len(p) >> 8, len(p) & 0xFF
    c = crc16_arc(bytes(p[8:]))
    p[6], p[7] = c >> 8, c & 0xFF
    return mask(bytes(p), key)


def frame(session: bytes, key, dst: bytes, src: bytes, seq: int, b22: int,
          ftype: int, b24: int, payload: bytes) -> bytes:
    hdr = bytes(2) + session + bytes(2) + b"\x02" + dst + src + bytes([seq & 0xFF, b22, ftype, b24])
    return seal(hdr + payload, key)


def temp_byte(c: float) -> int:
    c = max(MIN_C, min(MAX_C, round(float(c) * 2) / 2))
    return int(round((c + 20) * 2))


def patch_command(template: bytes, setpoint=None, mode=None, presets=None, rail=None) -> bytes:
    """Patch a captured 82-byte app command payload (frame offset 25..).

    setpoint: degrees C (0.5 steps). mode: name. If only the mode changes and we know that
    mode's preset, the setpoint follows it, as the app does (comfort -> 24, eco -> 16 ...).
    """
    p = bytearray(template)
    sp_i, md_i = SETPOINT_OFFSET - HEADER_LEN, MODE_OFFSET - HEADER_LEN
    if len(p) <= md_i:
        raise ValueError("template too short")
    if mode is not None:
        if mode not in MODE_CODES:
            raise ValueError("unknown mode %r" % mode)
        p[md_i] = MODE_CODES[mode]
        if setpoint is None and presets and presets.get(mode) is not None:
            setpoint = presets[mode]
    if setpoint is not None:
        p[sp_i] = temp_byte(setpoint)
    if rail is not None:
        if rail not in RAIL_CODES:
            raise ValueError("unknown towel-rail setting %r (use %s)" % (rail, ", ".join(RAIL_CODES)))
        p[RAIL_OFFSET - HEADER_LEN] = RAIL_CODES[rail]
    return bytes(p)


def readdress(payload: bytes, device: bytes, app: bytes) -> bytes:
    """Force the inner header to app -> device (templates are always that shape)."""
    p = bytearray(payload)
    p[2:8], p[8:14] = device, app
    return bytes(p)


# ---------------------------------------------------------------- relay mode
def downstream(session: bytes, key, device: bytes, payload: bytes) -> bytes:
    """A frame as the cloud forwards an app message to the thermostat (seq 1, b22 00, b24 FF)."""
    return frame(session, key, device, SERVER_ID, 1, 0x00, TYPE_APPDATA, 0xFF, payload)


# ---------------------------------------------------------------- cloud (app) mode
def app_register(app: bytes) -> bytes:
    return frame(bytes(4), HELLO_KEY, ZERO_ID, app, 0, 0x01, TYPE_REGISTER, 0xFF, APP_REGISTER_PAYLOAD)


def app_upstream(session: bytes, key, app: bytes, payload: bytes) -> bytes:
    """A frame as the app sends it to the cloud (seq 0, b22 01, b24 FF)."""
    return frame(session, key, SERVER_ID, app, 0, 0x01, TYPE_APPDATA, 0xFF, payload)


def key_from_reply(reply: bytes, app: bytes):
    """Recover the session key from the cloud's register reply (known plaintext + CRC)."""
    c = candidate_keys(reply, {app})
    if len(c) != 1:
        raise ValueError("register reply did not pin a unique key (%d candidates)" % len(c))
    k = next(iter(c))
    return reply[2:6], k, unmask(reply, k)


# What the app polls the device with. Counter 1 returns the 82-byte state (setpoint,
# mode, rail, room, heating); 2 = limits, 3/4 = schedule. The whole payload is
# determined by the two ids and the counter, so no capture is needed to build it.
GET_STATE, GET_LIMITS, GET_SCHED_1, GET_SCHED_2 = 1, 2, 3, 4


def get_payload(device: bytes, app: bytes, counter: int = GET_STATE) -> bytes:
    """App -> device read request (class 0x30)."""
    return b"\x00\x02" + device + app + b"\x00\x01\x30\xff" + (counter & 0xFFFFFFFF).to_bytes(4, "big")


# ---------------------------------------------------------------- standalone client helpers
import os as _os


def unique_app_id() -> bytes:
    """A fresh app identity per cloud session. The vendor app's id must NOT be reused: the
    cloud dedups by app id and refuses a duplicate while the vendor app holds the session."""
    return b"\x00\x01" + _os.urandom(4)


def auth_payload(device: bytes, app: bytes, token: bytes) -> bytes:
    """The app->device auth (class 0x32) built from just the 6-byte device token."""
    return b"\x00\x02" + device + app + b"\x00\x01\x32" + bytes.fromhex("ff0000010001") + token
