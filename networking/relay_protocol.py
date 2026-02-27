"""
relay_protocol.py - Protocolo binario para comunicación con el relay server.

Define pack/unpack para los comandos del relay.
Los paquetes de juego se envuelven transparentemente con un header de 6 bytes.
"""

import struct

# ── Comandos del relay ──
RELAY_CREATE_ROOM  = 0xA0
RELAY_ROOM_CREATED = 0xA1
RELAY_JOIN_ROOM    = 0xA2
RELAY_JOIN_OK      = 0xA3
RELAY_JOIN_FAIL    = 0xA4
RELAY_LEAVE_ROOM   = 0xA5
RELAY_PEER_LEFT    = 0xA6
RELAY_HEARTBEAT    = 0xA7
RELAY_FORWARD      = 0xA8

# Target especiales para FORWARD
TARGET_HOST      = 0x00
TARGET_BROADCAST = 0xFF


def get_relay_cmd(data):
    """Retorna el comando relay del primer byte, o None."""
    if len(data) < 1:
        return None
    return data[0]


# ── CREATE_ROOM: Player → Relay ──
# [0xA0]
def pack_create_room():
    return struct.pack("!B", RELAY_CREATE_ROOM)


# ── ROOM_CREATED: Relay → Player ──
# [0xA1][room_code:4s]
def pack_room_created(room_code):
    return struct.pack("!B4s", RELAY_ROOM_CREATED, room_code.encode("ascii"))


def unpack_room_created(data):
    """Retorna room_code (str)."""
    _, code_bytes = struct.unpack_from("!B4s", data, 0)
    return code_bytes.decode("ascii")


# ── JOIN_ROOM: Player → Relay ──
# [0xA2][room_code:4s]
def pack_join_room(room_code):
    return struct.pack("!B4s", RELAY_JOIN_ROOM, room_code.encode("ascii"))


def unpack_join_room(data):
    """Retorna room_code (str)."""
    _, code_bytes = struct.unpack_from("!B4s", data, 0)
    return code_bytes.decode("ascii")


# ── JOIN_OK: Relay → Player ──
# [0xA3][slot:1B]
def pack_join_ok(slot):
    return struct.pack("!BB", RELAY_JOIN_OK, slot)


def unpack_join_ok(data):
    """Retorna slot (int)."""
    _, slot = struct.unpack_from("!BB", data, 0)
    return slot


# ── JOIN_FAIL: Relay → Player ──
# [0xA4][reason:1B]
RELAY_FAIL_NOT_FOUND = 1
RELAY_FAIL_FULL = 2

def pack_join_fail(reason):
    return struct.pack("!BB", RELAY_JOIN_FAIL, reason)


def unpack_join_fail(data):
    """Retorna reason (int)."""
    _, reason = struct.unpack_from("!BB", data, 0)
    return reason


# ── LEAVE_ROOM: Player → Relay ──
# [0xA5][room_code:4s]
def pack_leave_room(room_code):
    return struct.pack("!B4s", RELAY_LEAVE_ROOM, room_code.encode("ascii"))


# ── PEER_LEFT: Relay → Players ──
# [0xA6][slot:1B]
def pack_peer_left(slot):
    return struct.pack("!BB", RELAY_PEER_LEFT, slot)


def unpack_peer_left(data):
    """Retorna slot (int) del peer que se fue."""
    _, slot = struct.unpack_from("!BB", data, 0)
    return slot


# ── HEARTBEAT: Bidireccional ──
# [0xA7][room_code:4s]
def pack_heartbeat(room_code):
    return struct.pack("!B4s", RELAY_HEARTBEAT, room_code.encode("ascii"))


# ── FORWARD: Bidireccional (envolver/desenvolver paquetes de juego) ──
# [0xA8][room_code:4s][target:1B][payload...]
def pack_forward(room_code, target, payload):
    """Envuelve un paquete de juego con header relay."""
    header = struct.pack("!B4sB", RELAY_FORWARD, room_code.encode("ascii"), target)
    return header + payload


def unpack_forward(data):
    """Desenvuelve paquete relay. Retorna (room_code, sender_slot, payload).

    Nota: sender_slot es inyectado por el relay server (reemplaza target).
    """
    _, code_bytes, sender_slot = struct.unpack_from("!B4sB", data, 0)
    payload = data[6:]
    return code_bytes.decode("ascii"), sender_slot, payload
