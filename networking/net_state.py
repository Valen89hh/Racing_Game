"""
net_state.py - Data classes ligeras para estado de red.

Clases con __slots__ para almacenar snapshots recibidos del servidor
y estados de input para envío al servidor.
"""

import time


class NetCarState:
    """Estado mínimo de un auto recibido del servidor."""
    __slots__ = (
        'player_id', 'x', 'y', 'vx', 'vy', 'angle',
        'laps', 'next_checkpoint_index', 'held_powerup',
        'effects', 'is_drifting', 'is_countersteer',
        'drift_charge', 'drift_level',
        'finished', 'finish_time',
        'last_input_seq',
        'effect_durations', 'drift_time', 'drift_direction', 'drift_mt_boost_timer',
    )

    def __init__(self, data=None):
        if data:
            self.player_id = data["player_id"]
            self.x = data["x"]
            self.y = data["y"]
            self.vx = data["vx"]
            self.vy = data["vy"]
            self.angle = data["angle"]
            self.laps = data["laps"]
            self.next_checkpoint_index = data["next_checkpoint_index"]
            self.held_powerup = data["held_powerup"]
            self.effects = data["effects"]
            self.is_drifting = data["is_drifting"]
            self.is_countersteer = data["is_countersteer"]
            self.drift_charge = data["drift_charge"]
            self.drift_level = data["drift_level"]
            self.finished = data["finished"]
            self.finish_time = data["finish_time"]
            self.last_input_seq = data.get("last_input_seq", 0)
            self.effect_durations = data.get("effect_durations", {})
            self.drift_time = data.get("drift_time", 0.0)
            self.drift_direction = data.get("drift_direction", 0)
            self.drift_mt_boost_timer = data.get("drift_mt_boost_timer", 0.0)
        else:
            self.player_id = 0
            self.x = self.y = self.vx = self.vy = self.angle = 0.0
            self.laps = self.next_checkpoint_index = 0
            self.held_powerup = None
            self.effects = []
            self.is_drifting = self.is_countersteer = False
            self.drift_charge = 0.0
            self.drift_level = 0
            self.finished = False
            self.finish_time = 0.0
            self.last_input_seq = 0
            self.effect_durations = {}
            self.drift_time = 0.0
            self.drift_direction = 0
            self.drift_mt_boost_timer = 0.0


class NetProjectileState:
    """Estado de un proyectil (misil o smart_missile)."""
    __slots__ = ('proj_type', 'owner_id', 'x', 'y', 'angle', 'target_pid')

    def __init__(self, data=None):
        if data:
            self.proj_type = data["type"]
            self.owner_id = data["owner_id"]
            self.x = data["x"]
            self.y = data["y"]
            self.angle = data["angle"]
            self.target_pid = data["target_pid"]
        else:
            self.proj_type = 0
            self.owner_id = 0
            self.x = self.y = self.angle = 0.0
            self.target_pid = 255


class NetHazardState:
    """Estado de un hazard (oil, mine)."""
    __slots__ = ('hazard_type', 'owner_id', 'x', 'y', 'lifetime')

    def __init__(self, data=None):
        if data:
            self.hazard_type = data["type"]
            self.owner_id = data["owner_id"]
            self.x = data["x"]
            self.y = data["y"]
            self.lifetime = data["lifetime"]
        else:
            self.hazard_type = 0
            self.owner_id = 0
            self.x = self.y = self.lifetime = 0.0


class NetPowerUpItemState:
    """Estado de un pickup de power-up."""
    __slots__ = ('index', 'active', 'respawn_timer')

    def __init__(self, data=None):
        if data:
            self.index = data["index"]
            self.active = data["active"]
            self.respawn_timer = data["respawn_timer"]
        else:
            self.index = 0
            self.active = True
            self.respawn_timer = 0.0


class StateSnapshot:
    """Estado completo del juego en un instante."""
    __slots__ = ('seq', 'race_time', 'server_tick', 'cars', 'projectiles',
                 'hazards', 'items', 'recv_time')

    def __init__(self, data=None):
        if data:
            self.seq = data["seq"]
            self.race_time = data["race_time"]
            self.server_tick = data.get("server_tick", 0)
            self.cars = [NetCarState(c) for c in data["cars"]]
            self.projectiles = [NetProjectileState(p) for p in data["projectiles"]]
            self.hazards = [NetHazardState(h) for h in data["hazards"]]
            self.items = [NetPowerUpItemState(it) for it in data["items"]]
        else:
            self.seq = 0
            self.race_time = 0.0
            self.server_tick = 0
            self.cars = []
            self.projectiles = []
            self.hazards = []
            self.items = []
        self.recv_time = time.time()


class InputState:
    """Un frame de input del jugador."""
    __slots__ = ('accel', 'turn', 'brake', 'use_powerup', 'seq')

    def __init__(self, accel=0.0, turn=0.0, brake=False, use_powerup=False, seq=0):
        self.accel = accel
        self.turn = turn
        self.brake = brake
        self.use_powerup = use_powerup
        self.seq = seq
