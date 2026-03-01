"""
protocol.py - Protocolo binario UDP para multijugador.

Define pack/unpack para todos los tipos de paquetes de red.
Usa struct para serialización eficiente con tamaño fijo.
"""

import struct
import json
import time
import random

# ── Tipos de paquete ──
PKT_JOIN_REQUEST   = 0x01
PKT_JOIN_ACCEPT    = 0x02
PKT_JOIN_REJECT    = 0x03
PKT_PLAYER_INPUT   = 0x10
PKT_STATE_SNAPSHOT = 0x20
PKT_LOBBY_STATE    = 0x30
PKT_RACE_START     = 0x31
PKT_SERVER_CONFIG  = 0x32   # Admin→Server: cambiar config
PKT_TRACK_LIST     = 0x33   # Server→Admin: tracks disponibles
PKT_RETURN_LOBBY   = 0x34   # Server→All: volver al lobby
PKT_TRACK_DATA     = 0x35
PKT_TRACK_ACK      = 0x36
PKT_POWERUP_EVENT  = 0x40
PKT_ROOM_LIST_REQ  = 0x50  # C→S: pedir lista de salas
PKT_ROOM_LIST      = 0x51  # S→C: lista de salas
PKT_ROOM_CREATE    = 0x52  # C→S: crear sala
PKT_ROOM_CREATE_OK = 0x53  # S→C: sala creada + código + slot
PKT_ROOM_JOIN      = 0x54  # C→S: unirse a sala
PKT_ROOM_ACCEPT    = 0x55  # S→C: aceptado en sala
PKT_ROOM_REJECT    = 0x56  # S→C: rechazado
PKT_ROOM_LEAVE     = 0x57  # C→S: salir de sala

PKT_PING           = 0xF0
PKT_PONG           = 0xF1
PKT_DISCONNECT     = 0xFF

# Tamaño máximo de chunk para transferencia de track
TRACK_CHUNK_SIZE = 1024

# Header: [pkt_type:1B][seq:2B]
HEADER_FMT = "!BH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)


def _pack_header(pkt_type, seq=0):
    return struct.pack(HEADER_FMT, pkt_type, seq)


def _unpack_header(data):
    pkt_type, seq = struct.unpack_from(HEADER_FMT, data, 0)
    return pkt_type, seq, data[HEADER_SIZE:]


def get_packet_type(data):
    """Retorna el tipo de paquete sin desempaquetar todo."""
    if len(data) < 1:
        return None
    return data[0]


# ── JOIN_REQUEST: C→H ──
# [header][name_len:1B][name:varB]
def pack_join_request(player_name):
    name_bytes = player_name.encode("utf-8")[:20]
    return _pack_header(PKT_JOIN_REQUEST) + struct.pack("!B", len(name_bytes)) + name_bytes


def unpack_join_request(data):
    _, _, payload = _unpack_header(data)
    name_len = payload[0]
    name = payload[1:1 + name_len].decode("utf-8", errors="replace")
    return name


# ── JOIN_ACCEPT: H→C ──
# [header][player_id:1B][max_players:1B][is_admin:1B][multi_room:1B]
JOIN_ACCEPT_FMT = "!BBBB"

def pack_join_accept(player_id, max_players=4, is_admin=False, multi_room=False):
    return _pack_header(PKT_JOIN_ACCEPT) + struct.pack(
        JOIN_ACCEPT_FMT, player_id, max_players,
        1 if is_admin else 0, 1 if multi_room else 0)


def unpack_join_accept(data):
    _, _, payload = _unpack_header(data)
    if len(payload) >= 4:
        player_id, max_players, is_admin_byte, multi_room_byte = struct.unpack_from(
            JOIN_ACCEPT_FMT, payload, 0)
        return player_id, max_players, bool(is_admin_byte), bool(multi_room_byte)
    if len(payload) >= 3:
        player_id, max_players, is_admin_byte = struct.unpack_from("!BBB", payload, 0)
        return player_id, max_players, bool(is_admin_byte), False
    # Backward compat: old format without is_admin
    player_id, max_players = struct.unpack_from("!BB", payload, 0)
    return player_id, max_players, False, False


# ── JOIN_REJECT: H→C ──
# [header][reason:1B]
REJECT_FULL = 1
REJECT_RACING = 2

# Room reject reasons
ROOM_FULL = 1
ROOM_RACING = 2
ROOM_NOT_FOUND = 3
MAX_ROOMS_REACHED = 4

def pack_join_reject(reason=REJECT_FULL):
    return _pack_header(PKT_JOIN_REJECT) + struct.pack("!B", reason)


def unpack_join_reject(data):
    _, _, payload = _unpack_header(data)
    return payload[0]


# ── PLAYER_INPUT: C→H ──
# Single input: [player_id:1B][accel:b][turn:b][brake:B][use_powerup:B][seq:H]
INPUT_FMT = "!BbbBBH"
INPUT_SIZE = struct.calcsize(INPUT_FMT)

# Redundant input packet: [header][count:1B][input1][input2][input3]
# count = number of inputs (1-3), newest first
INPUT_REDUNDANCY = 3


def pack_input(player_id, accel, turn, brake, use_powerup, seq=0):
    """Pack a single input (legacy, still used by server for compatibility)."""
    accel_i = max(-127, min(127, int(accel * 127)))
    turn_i = max(-127, min(127, int(turn * 127)))
    return _pack_header(PKT_PLAYER_INPUT, seq) + struct.pack(
        INPUT_FMT, player_id, accel_i, turn_i,
        1 if brake else 0, 1 if use_powerup else 0, seq
    )


def pack_input_redundant(player_id, inputs):
    """Pack multiple inputs for redundancy. inputs = [(accel, turn, brake, use_pw, seq), ...] newest first."""
    count = min(len(inputs), INPUT_REDUNDANCY)
    newest_seq = inputs[0][4] if inputs else 0
    body = struct.pack("!B", count)
    for i in range(count):
        accel, turn, brake, use_pw, seq = inputs[i]
        accel_i = max(-127, min(127, int(accel * 127)))
        turn_i = max(-127, min(127, int(turn * 127)))
        body += struct.pack(INPUT_FMT, player_id, accel_i, turn_i,
                            1 if brake else 0, 1 if use_pw else 0, seq)
    return _pack_header(PKT_PLAYER_INPUT, newest_seq) + body


def unpack_input(data):
    """Unpack input packet. Returns list of input dicts (newest first).
    Backward compatible: old single-input packets return a 1-element list."""
    _, seq_h, payload = _unpack_header(data)
    # Detect redundant format: if payload starts with count byte and
    # total size matches count * INPUT_SIZE + 1
    if len(payload) >= 1 + INPUT_SIZE:
        count = payload[0]
        expected = 1 + count * INPUT_SIZE
        if 1 <= count <= INPUT_REDUNDANCY and len(payload) >= expected:
            results = []
            offset = 1
            for _ in range(count):
                pid, accel_i, turn_i, brake, use_pw, seq = struct.unpack_from(
                    INPUT_FMT, payload, offset)
                results.append({
                    "player_id": pid,
                    "accel": accel_i / 127.0,
                    "turn": turn_i / 127.0,
                    "brake": bool(brake),
                    "use_powerup": bool(use_pw),
                    "seq": seq,
                })
                offset += INPUT_SIZE
            return results

    # Legacy single-input format
    pid, accel_i, turn_i, brake, use_pw, seq = struct.unpack_from(INPUT_FMT, payload, 0)
    return [{
        "player_id": pid,
        "accel": accel_i / 127.0,
        "turn": turn_i / 127.0,
        "brake": bool(brake),
        "use_powerup": bool(use_pw),
        "seq": seq,
    }]


# ── STATE_SNAPSHOT: H→C ──
# Cada auto: 41 bytes
# [pid:1B][x:f][y:f][vx:f][vy:f][angle:f][laps:B][ncp:B]
# [held_pw:b][effects_mask:H][drift_flags:B][drift_charge:B]
# [drift_level:B][finished:B][finish_time:f][last_input_seq:H]
# [drift_time:B][drift_dir:b][drift_mt_boost:B]
# [10 x effect_duration:B]
CAR_STATE_FMT = "!BfffffBBbHBBBBfHBbBBBBBBBBBBB"
CAR_STATE_SIZE = struct.calcsize(CAR_STATE_FMT)

# Effect mask bits
EFFECT_BOOST        = 1 << 0
EFFECT_SHIELD       = 1 << 1
EFFECT_OIL_SLOW     = 1 << 2
EFFECT_MISSILE_SLOW = 1 << 3
EFFECT_MINE_SPIN    = 1 << 4
EFFECT_EMP_SLOW     = 1 << 5
EFFECT_MAGNET       = 1 << 6
EFFECT_SLOWMO       = 1 << 7
EFFECT_BOUNCE       = 1 << 8
EFFECT_AUTOPILOT    = 1 << 9

EFFECT_NAMES = {
    EFFECT_BOOST: "boost",
    EFFECT_SHIELD: "shield",
    EFFECT_OIL_SLOW: "oil_slow",
    EFFECT_MISSILE_SLOW: "missile_slow",
    EFFECT_MINE_SPIN: "mine_spin",
    EFFECT_EMP_SLOW: "emp_slow",
    EFFECT_MAGNET: "magnet",
    EFFECT_SLOWMO: "slowmo",
    EFFECT_BOUNCE: "bounce",
    EFFECT_AUTOPILOT: "autopilot",
}

EFFECT_TO_BIT = {v: k for k, v in EFFECT_NAMES.items()}

# Orden fijo de efectos para serializar duraciones (10 efectos)
EFFECT_BIT_ORDER = [
    "boost", "shield", "oil_slow", "missile_slow", "mine_spin",
    "emp_slow", "magnet", "slowmo", "bounce", "autopilot",
]

# Powerup type → byte ID
POWERUP_TYPE_MAP = {
    None: 0,
    "boost": 1, "shield": 2, "missile": 3, "oil": 4,
    "mine": 5, "emp": 6, "magnet": 7, "slowmo": 8,
    "bounce": 9, "autopilot": 10, "teleport": 11, "smart_missile": 12,
}
POWERUP_ID_MAP = {v: k for k, v in POWERUP_TYPE_MAP.items()}


def _encode_effects_mask(active_effects):
    mask = 0
    for name in active_effects:
        bit = EFFECT_TO_BIT.get(name, 0)
        mask |= bit
    return mask


def _decode_effects_mask(mask):
    effects = []
    for bit, name in EFFECT_NAMES.items():
        if mask & bit:
            effects.append(name)
    return effects


def pack_car_state(car, last_input_seq=0):
    """Empaqueta estado de un Car para snapshot."""
    held_pw_id = POWERUP_TYPE_MAP.get(car.held_powerup, 0)
    if held_pw_id == 0 and car.held_powerup is not None:
        held_pw_id = 0  # unknown → none
    effects_mask = _encode_effects_mask(car.active_effects)
    drift_flags = (1 if car.is_drifting else 0) | (2 if car.is_countersteer else 0)
    drift_charge_byte = max(0, min(255, int(car.drift_charge * 255)))

    # Drift state sync (resolución 0.01s, max 2.55s)
    drift_time_byte = max(0, min(255, int(car.drift_time * 100)))
    drift_dir = max(-1, min(1, car.drift_direction))
    drift_mt_byte = max(0, min(255, int(car.drift_mt_boost_timer * 100)))

    # Effect durations (resolución 0.1s, max 25.5s)
    effect_dur_bytes = []
    for ename in EFFECT_BIT_ORDER:
        dur = car.active_effects.get(ename, 0.0)
        effect_dur_bytes.append(max(0, min(255, int(dur * 10))))

    return struct.pack(
        CAR_STATE_FMT,
        car.player_id,
        car.x, car.y,
        car.velocity.x, car.velocity.y,
        car.angle,
        min(car.laps, 255),
        min(car.next_checkpoint_index, 255),
        held_pw_id,
        effects_mask,
        drift_flags,
        drift_charge_byte,
        min(car.drift_level, 255),
        1 if car.finished else 0,
        car.finish_time,
        last_input_seq & 0xFFFF,
        drift_time_byte,
        drift_dir,
        drift_mt_byte,
        *effect_dur_bytes,
    )


def unpack_car_state(data, offset=0):
    """Desempaqueta estado de un auto desde bytes."""
    vals = struct.unpack_from(CAR_STATE_FMT, data, offset)
    (pid, x, y, vx, vy, angle, laps, ncp,
     held_pw_id, effects_mask, drift_flags, drift_charge_byte,
     drift_level, finished_byte, finish_time, last_input_seq,
     drift_time_byte, drift_dir, drift_mt_byte,
     *effect_dur_raw) = vals

    # Decodificar duraciones de efectos
    effect_durations = {}
    for i, ename in enumerate(EFFECT_BIT_ORDER):
        if i < len(effect_dur_raw) and effect_dur_raw[i] > 0:
            effect_durations[ename] = effect_dur_raw[i] / 10.0

    return {
        "player_id": pid,
        "x": x, "y": y,
        "vx": vx, "vy": vy,
        "angle": angle,
        "laps": laps,
        "next_checkpoint_index": ncp,
        "held_powerup": POWERUP_ID_MAP.get(held_pw_id),
        "effects": _decode_effects_mask(effects_mask),
        "is_drifting": bool(drift_flags & 1),
        "is_countersteer": bool(drift_flags & 2),
        "drift_charge": drift_charge_byte / 255.0,
        "drift_level": drift_level,
        "finished": bool(finished_byte),
        "finish_time": finish_time,
        "last_input_seq": last_input_seq,
        "drift_time": drift_time_byte / 100.0,
        "drift_direction": drift_dir,
        "drift_mt_boost_timer": drift_mt_byte / 100.0,
        "effect_durations": effect_durations,
    }


# Projectile state: [type:1B][owner:1B][x:f][y:f][angle:f][target_pid:B]
PROJ_FMT = "!BBfffB"
PROJ_SIZE = struct.calcsize(PROJ_FMT)
PROJ_MISSILE = 1
PROJ_SMART_MISSILE = 2

# Hazard state: [type:1B][owner:1B][x:f][y:f][lifetime:f]
HAZARD_FMT = "!BBfff"
HAZARD_SIZE = struct.calcsize(HAZARD_FMT)
HAZARD_OIL = 1
HAZARD_MINE = 2

# PowerUp item state: [index:B][active:B][respawn_timer:f]
ITEM_FMT = "!BBf"
ITEM_SIZE = struct.calcsize(ITEM_FMT)


def pack_state_snapshot(cars, missiles, smart_missiles, oil_slicks, mines, powerup_items, race_time, seq=0, last_input_seqs=None, server_tick=0):
    """Empaqueta snapshot completo del estado del juego."""
    header = _pack_header(PKT_STATE_SNAPSHOT, seq)

    # Race time + server_tick + counts
    meta = struct.pack("!fIBBBBB",
                       race_time,
                       server_tick & 0xFFFFFFFF,
                       len(cars),
                       len(missiles) + len(smart_missiles),
                       len(oil_slicks) + len(mines),
                       min(len(powerup_items), 255),
                       0)  # reserved

    # Cars
    car_data = b""
    for car in cars:
        lis = 0
        if last_input_seqs:
            lis = last_input_seqs.get(car.player_id, 0)
        car_data += pack_car_state(car, last_input_seq=lis)

    # Projectiles
    proj_data = b""
    for m in missiles:
        if m.alive:
            proj_data += struct.pack(PROJ_FMT, PROJ_MISSILE, m.owner_id,
                                     m.x, m.y, m.angle, 255)
    for sm in smart_missiles:
        if sm.alive:
            target_pid = sm.target.player_id if sm.target else 255
            proj_data += struct.pack(PROJ_FMT, PROJ_SMART_MISSILE, sm.owner_id,
                                     sm.x, sm.y, sm.angle, target_pid)

    # Hazards
    hazard_data = b""
    for o in oil_slicks:
        if o.alive:
            hazard_data += struct.pack(HAZARD_FMT, HAZARD_OIL, o.owner_id,
                                       o.x, o.y, o.lifetime)
    for m in mines:
        if m.alive:
            hazard_data += struct.pack(HAZARD_FMT, HAZARD_MINE, m.owner_id,
                                       m.x, m.y, m.lifetime)

    # PowerUp items (active/inactive state)
    item_data = b""
    for i, item in enumerate(powerup_items):
        if i > 254:
            break
        item_data += struct.pack(ITEM_FMT, i, 1 if item.active else 0,
                                 item.respawn_timer)

    return header + meta + car_data + proj_data + hazard_data + item_data


def unpack_state_snapshot(data):
    """Desempaqueta snapshot completo."""
    _, seq, payload = _unpack_header(data)

    meta_fmt = "!fIBBBBB"
    meta_size = struct.calcsize(meta_fmt)
    race_time, server_tick, n_cars, n_proj, n_hazard, n_items, _ = struct.unpack_from(meta_fmt, payload, 0)
    offset = meta_size

    cars = []
    for _ in range(n_cars):
        cs = unpack_car_state(payload, offset)
        cars.append(cs)
        offset += CAR_STATE_SIZE

    projectiles = []
    for _ in range(n_proj):
        vals = struct.unpack_from(PROJ_FMT, payload, offset)
        projectiles.append({
            "type": vals[0], "owner_id": vals[1],
            "x": vals[2], "y": vals[3], "angle": vals[4],
            "target_pid": vals[5],
        })
        offset += PROJ_SIZE

    hazards = []
    for _ in range(n_hazard):
        vals = struct.unpack_from(HAZARD_FMT, payload, offset)
        hazards.append({
            "type": vals[0], "owner_id": vals[1],
            "x": vals[2], "y": vals[3], "lifetime": vals[4],
        })
        offset += HAZARD_SIZE

    items = []
    for _ in range(n_items):
        if offset + ITEM_SIZE > len(payload):
            break
        vals = struct.unpack_from(ITEM_FMT, payload, offset)
        items.append({
            "index": vals[0], "active": bool(vals[1]),
            "respawn_timer": vals[2],
        })
        offset += ITEM_SIZE

    return {
        "seq": seq,
        "race_time": race_time,
        "server_tick": server_tick,
        "cars": cars,
        "projectiles": projectiles,
        "hazards": hazards,
        "items": items,
    }


# ── LOBBY_STATE: H→C ──
# [header][n_players:B][bot_count:B][track_name_len:B][admin_pid:B][track_name:varB]
# followed by: for each player [pid:B][name_len:B][name:varB]
# admin_pid: 255 = no admin
def pack_lobby_state(players, bot_count, track_name, admin_player_id=255):
    """players: list of (player_id, name)"""
    header = _pack_header(PKT_LOBBY_STATE)
    track_bytes = track_name.encode("utf-8")[:40]
    meta = struct.pack("!BBBB", len(players), bot_count, len(track_bytes), admin_player_id)
    payload = meta + track_bytes
    for pid, name in players:
        name_bytes = name.encode("utf-8")[:20]
        payload += struct.pack("!BB", pid, len(name_bytes)) + name_bytes
    return header + payload


def unpack_lobby_state(data):
    _, _, payload = _unpack_header(data)
    # New format: 4-byte meta with admin_pid
    if len(payload) >= 4:
        n_players, bot_count, track_name_len, admin_pid = struct.unpack_from("!BBBB", payload, 0)
        offset = 4
    else:
        n_players, bot_count, track_name_len = struct.unpack_from("!BBB", payload, 0)
        admin_pid = 255
        offset = 3
    track_name = payload[offset:offset + track_name_len].decode("utf-8", errors="replace")
    offset += track_name_len
    players = []
    for _ in range(n_players):
        if offset + 2 > len(payload):
            break
        pid, name_len = struct.unpack_from("!BB", payload, offset)
        offset += 2
        name = payload[offset:offset + name_len].decode("utf-8", errors="replace")
        offset += name_len
        players.append((pid, name))
    return {"players": players, "bot_count": bot_count, "track_name": track_name,
            "admin_player_id": admin_pid}


# ── RACE_START: H→C ──
# [header][countdown:B]
def pack_race_start(countdown=3):
    return _pack_header(PKT_RACE_START) + struct.pack("!B", countdown)


def unpack_race_start(data):
    _, _, payload = _unpack_header(data)
    return payload[0]


# ── TRACK_DATA: H→C (chunked) ──
# [header(seq=chunk_idx)][total_chunks:H][chunk_data:varB]
def pack_track_chunks(track_json_str):
    """Divide track JSON en chunks y retorna lista de paquetes."""
    raw = track_json_str.encode("utf-8")
    chunks = []
    total = (len(raw) + TRACK_CHUNK_SIZE - 1) // TRACK_CHUNK_SIZE
    for i in range(total):
        chunk = raw[i * TRACK_CHUNK_SIZE:(i + 1) * TRACK_CHUNK_SIZE]
        pkt = _pack_header(PKT_TRACK_DATA, i) + struct.pack("!H", total) + chunk
        chunks.append(pkt)
    return chunks


def unpack_track_chunk(data):
    _, chunk_idx, payload = _unpack_header(data)
    total_chunks = struct.unpack_from("!H", payload, 0)[0]
    chunk_data = payload[2:]
    return chunk_idx, total_chunks, chunk_data


# ── TRACK_ACK: C→H ──
def pack_track_ack(chunk_idx):
    return _pack_header(PKT_TRACK_ACK, chunk_idx)


def unpack_track_ack(data):
    _, chunk_idx, _ = _unpack_header(data)
    return chunk_idx


# ── POWERUP_EVENT: H→C ──
# [header][event_type:B][player_id:B][powerup_type:B][item_index:B][x:f][y:f]
PW_EVENT_FMT = "!BBBBff"
PW_EVENT_SIZE = struct.calcsize(PW_EVENT_FMT)
PW_EVENT_COLLECT = 1
PW_EVENT_ACTIVATE = 2

def pack_powerup_event(event_type, player_id, powerup_type, item_index=255, x=0.0, y=0.0):
    pw_id = POWERUP_TYPE_MAP.get(powerup_type, 0)
    return _pack_header(PKT_POWERUP_EVENT) + struct.pack(
        PW_EVENT_FMT, event_type, player_id, pw_id, item_index, x, y)


def unpack_powerup_event(data):
    _, _, payload = _unpack_header(data)
    vals = struct.unpack_from(PW_EVENT_FMT, payload, 0)
    return {
        "event_type": vals[0],
        "player_id": vals[1],
        "powerup_type": POWERUP_ID_MAP.get(vals[2]),
        "item_index": vals[3],
        "x": vals[4], "y": vals[5],
    }


# ── PING / PONG ──
# [header][timestamp:d]
PING_FMT = "!d"

def pack_ping():
    return _pack_header(PKT_PING) + struct.pack(PING_FMT, time.time())


def pack_pong(timestamp):
    return _pack_header(PKT_PONG) + struct.pack(PING_FMT, timestamp)


def unpack_ping(data):
    _, _, payload = _unpack_header(data)
    return struct.unpack_from(PING_FMT, payload, 0)[0]


# ── SERVER_CONFIG: Admin→Server ──
# [header][subtype:1B][payload...]
CONFIG_CHANGE_TRACK = 0x01
CONFIG_CHANGE_BOTS  = 0x02
CONFIG_START_RACE   = 0x03

def pack_server_config_track(filename):
    """Admin requests track change."""
    name_bytes = filename.encode("utf-8")[:60]
    return _pack_header(PKT_SERVER_CONFIG) + struct.pack("!BB", CONFIG_CHANGE_TRACK,
                                                          len(name_bytes)) + name_bytes

def pack_server_config_bots(count):
    """Admin requests bot count change."""
    return _pack_header(PKT_SERVER_CONFIG) + struct.pack("!BB", CONFIG_CHANGE_BOTS, count)

def pack_server_config_start():
    """Admin requests race start."""
    return _pack_header(PKT_SERVER_CONFIG) + struct.pack("!B", CONFIG_START_RACE)

def unpack_server_config(data):
    """Unpack server config packet. Returns dict with 'subtype' and payload fields."""
    _, _, payload = _unpack_header(data)
    subtype = payload[0]
    if subtype == CONFIG_CHANGE_TRACK:
        name_len = payload[1]
        filename = payload[2:2 + name_len].decode("utf-8", errors="replace")
        return {"subtype": subtype, "filename": filename}
    elif subtype == CONFIG_CHANGE_BOTS:
        return {"subtype": subtype, "count": payload[1]}
    elif subtype == CONFIG_START_RACE:
        return {"subtype": subtype}
    return {"subtype": subtype}


# ── TRACK_LIST: Server→Admin ──
# [header][count:1B][ [name_len:1B][name][fname_len:1B][fname][type:1B] ...]
def pack_track_list(tracks):
    """Pack list of available tracks. tracks: list of dicts with name, filename, type."""
    header = _pack_header(PKT_TRACK_LIST)
    count = min(len(tracks), 255)
    body = struct.pack("!B", count)
    for i in range(count):
        t = tracks[i]
        name_bytes = t["name"].encode("utf-8")[:40]
        fname_bytes = t["filename"].encode("utf-8")[:60]
        ttype = 1 if t.get("type") == "tiles" else 0
        body += struct.pack("!B", len(name_bytes)) + name_bytes
        body += struct.pack("!B", len(fname_bytes)) + fname_bytes
        body += struct.pack("!B", ttype)
    return header + body

def unpack_track_list(data):
    """Unpack track list. Returns list of dicts with name, filename, type."""
    _, _, payload = _unpack_header(data)
    count = payload[0]
    offset = 1
    tracks = []
    for _ in range(count):
        name_len = payload[offset]; offset += 1
        name = payload[offset:offset + name_len].decode("utf-8", errors="replace"); offset += name_len
        fname_len = payload[offset]; offset += 1
        fname = payload[offset:offset + fname_len].decode("utf-8", errors="replace"); offset += fname_len
        ttype = payload[offset]; offset += 1
        tracks.append({"name": name, "filename": fname, "type": "tiles" if ttype == 1 else "classic"})
    return tracks


# ── RETURN_LOBBY: Server→All ──
def pack_return_lobby():
    """Signal all clients to return to lobby."""
    return _pack_header(PKT_RETURN_LOBBY)


# ── DISCONNECT ──
def pack_disconnect():
    return _pack_header(PKT_DISCONNECT)


# ══════════════════════════════════════════════
# ROOM MANAGEMENT (multi-room dedicated server)
# ══════════════════════════════════════════════

_ROOM_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sin 0/O/1/I/L


def generate_room_code():
    """Genera un código de sala de 4 caracteres."""
    return "".join(random.choices(_ROOM_CHARS, k=4))


# ── ROOM_LIST_REQ: C→S ──
def pack_room_list_req():
    return _pack_header(PKT_ROOM_LIST_REQ)


# ── ROOM_LIST: S→C ──
# [header][count:1B] per room: [room_id:1B][code_len:1B][code:varB]
#   [name_len:1B][name:varB][track_len:1B][track:varB]
#   [players:1B][max_players:1B][state:1B][is_private:1B]
ROOM_STATE_LOBBY = 0
ROOM_STATE_COUNTDOWN = 1
ROOM_STATE_RACING = 2
ROOM_STATE_DONE = 3


def pack_room_list(rooms):
    """Pack list of room info dicts.
    rooms: [{room_id, code, name, track, players, max_players, state, is_private}, ...]
    """
    header = _pack_header(PKT_ROOM_LIST)
    count = min(len(rooms), 255)
    body = struct.pack("!B", count)
    for r in rooms[:count]:
        code_bytes = r["code"].encode("utf-8")[:8]
        name_bytes = r["name"].encode("utf-8")[:30]
        track_bytes = r["track"].encode("utf-8")[:40]
        body += struct.pack("!BB", r["room_id"], len(code_bytes)) + code_bytes
        body += struct.pack("!B", len(name_bytes)) + name_bytes
        body += struct.pack("!B", len(track_bytes)) + track_bytes
        body += struct.pack("!BBBB", r["players"], r["max_players"],
                            r["state"], 1 if r["is_private"] else 0)
    return header + body


def unpack_room_list(data):
    _, _, payload = _unpack_header(data)
    count = payload[0]
    offset = 1
    rooms = []
    for _ in range(count):
        room_id = payload[offset]; offset += 1
        code_len = payload[offset]; offset += 1
        code = payload[offset:offset + code_len].decode("utf-8", errors="replace"); offset += code_len
        name_len = payload[offset]; offset += 1
        name = payload[offset:offset + name_len].decode("utf-8", errors="replace"); offset += name_len
        track_len = payload[offset]; offset += 1
        track = payload[offset:offset + track_len].decode("utf-8", errors="replace"); offset += track_len
        players, max_p, state, is_priv = struct.unpack_from("!BBBB", payload, offset); offset += 4
        rooms.append({
            "room_id": room_id, "code": code, "name": name,
            "track": track, "players": players, "max_players": max_p,
            "state": state, "is_private": bool(is_priv),
        })
    return rooms


# ── ROOM_CREATE: C→S ──
# [header][is_private:1B][name_len:1B][name:varB]
def pack_room_create(name, is_private=False):
    name_bytes = name.encode("utf-8")[:30]
    return _pack_header(PKT_ROOM_CREATE) + struct.pack(
        "!BB", 1 if is_private else 0, len(name_bytes)) + name_bytes


def unpack_room_create(data):
    _, _, payload = _unpack_header(data)
    is_private = bool(payload[0])
    name_len = payload[1]
    name = payload[2:2 + name_len].decode("utf-8", errors="replace")
    return {"is_private": is_private, "name": name}


# ── ROOM_CREATE_OK: S→C ──
# [header][room_id:1B][code_len:1B][code:varB][slot:1B]
def pack_room_create_ok(room_id, code, slot):
    code_bytes = code.encode("utf-8")[:8]
    return _pack_header(PKT_ROOM_CREATE_OK) + struct.pack(
        "!BB", room_id, len(code_bytes)) + code_bytes + struct.pack("!B", slot)


def unpack_room_create_ok(data):
    _, _, payload = _unpack_header(data)
    room_id = payload[0]
    code_len = payload[1]
    code = payload[2:2 + code_len].decode("utf-8", errors="replace")
    slot = payload[2 + code_len]
    return {"room_id": room_id, "code": code, "slot": slot}


# ── ROOM_JOIN: C→S ──
# [header][join_mode:1B][id_or_code_len:1B][id_or_code:varB]
# join_mode: 0=by room_id (1 byte), 1=by code (4 bytes)
ROOM_JOIN_BY_ID = 0
ROOM_JOIN_BY_CODE = 1


def pack_room_join_by_id(room_id):
    return _pack_header(PKT_ROOM_JOIN) + struct.pack("!BBB", ROOM_JOIN_BY_ID, 1, room_id)


def pack_room_join_by_code(code):
    code_bytes = code.encode("utf-8")[:8]
    return _pack_header(PKT_ROOM_JOIN) + struct.pack(
        "!BB", ROOM_JOIN_BY_CODE, len(code_bytes)) + code_bytes


def unpack_room_join(data):
    _, _, payload = _unpack_header(data)
    join_mode = payload[0]
    val_len = payload[1]
    if join_mode == ROOM_JOIN_BY_ID:
        return {"mode": ROOM_JOIN_BY_ID, "room_id": payload[2]}
    else:
        code = payload[2:2 + val_len].decode("utf-8", errors="replace")
        return {"mode": ROOM_JOIN_BY_CODE, "code": code}


# ── ROOM_ACCEPT: S→C ──
# [header][room_id:1B][slot:1B][is_admin:1B]
def pack_room_accept(room_id, slot, is_admin=False):
    return _pack_header(PKT_ROOM_ACCEPT) + struct.pack(
        "!BBB", room_id, slot, 1 if is_admin else 0)


def unpack_room_accept(data):
    _, _, payload = _unpack_header(data)
    room_id, slot, is_admin = struct.unpack_from("!BBB", payload, 0)
    return {"room_id": room_id, "slot": slot, "is_admin": bool(is_admin)}


# ── ROOM_REJECT: S→C ──
# [header][reason:1B]
def pack_room_reject(reason):
    return _pack_header(PKT_ROOM_REJECT) + struct.pack("!B", reason)


def unpack_room_reject(data):
    _, _, payload = _unpack_header(data)
    return payload[0]


# ── ROOM_LEAVE: C→S ──
def pack_room_leave():
    return _pack_header(PKT_ROOM_LEAVE)
