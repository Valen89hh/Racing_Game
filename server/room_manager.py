"""
room_manager.py - Gestiona múltiples Room instances en el servidor dedicado.

Cada sala tiene su propio RoomNetAdapter, Room y WorldSimulation.
"""

from networking.protocol import generate_room_code
from server.room import Room, ROOM_LOBBY
from server.room_net_adapter import RoomNetAdapter
from settings import MAX_ROOMS, MAX_PLAYERS


class RoomManager:
    """Gestiona hasta MAX_ROOMS salas simultáneas."""

    def __init__(self, net_server, default_track, default_bots, max_players_per_room):
        self.net_server = net_server
        self.rooms = {}           # room_id -> Room
        self.adapters = {}        # room_id -> RoomNetAdapter
        self._codes = {}          # code -> room_id
        self._next_room_id = 0
        self.default_track = default_track
        self.default_bots = default_bots
        self.max_players_per_room = max_players_per_room

    def create_room(self, name, is_private, creator_addr):
        """Crea una nueva sala. Retorna (room_id, code, slot) o None si max reached."""
        if len(self.rooms) >= MAX_ROOMS:
            return None

        room_id = self._next_room_id
        self._next_room_id += 1

        code = generate_room_code()
        # Evitar colisiones de código
        attempts = 0
        while code in self._codes and attempts < 100:
            code = generate_room_code()
            attempts += 1

        # Crear adapter
        adapter = RoomNetAdapter(self.net_server, room_id)
        adapter.track_name = self.default_track
        adapter.bot_count = self.default_bots
        self.adapters[room_id] = adapter

        # Crear room
        room = Room(
            adapter, self.default_track, self.default_bots,
            self.max_players_per_room,
            room_code=code, room_name=name, is_private=is_private,
        )
        self.rooms[room_id] = room
        self._codes[code] = room_id

        # Asignar al creador
        slot = 0
        self.net_server._client_room[creator_addr] = room_id
        self.net_server._client_slot[creator_addr] = slot

        # Creador es admin
        adapter.set_admin(slot)

        # Notificar al room
        with self.net_server._clients_lock:
            client = self.net_server._clients.get(creator_addr)
            creator_name = client.name if client else "Player"

        if adapter.on_player_join:
            adapter.on_player_join(slot, creator_name)

        print(f"[ROOM_MGR] Room '{name}' created (id={room_id}, code={code}, "
              f"private={is_private}) by {creator_name}")

        return room_id, code, slot

    def join_room(self, room_id, addr):
        """Une un cliente a una sala por room_id.
        Retorna slot o None si falla."""
        if room_id not in self.rooms:
            return None

        room = self.rooms[room_id]
        adapter = self.adapters[room_id]

        # No unirse si está en carrera
        if room.state != ROOM_LOBBY:
            return None

        # Verificar capacidad
        current = adapter.get_connected_count()
        if current >= self.max_players_per_room:
            return None

        # Asignar slot (buscar el primer slot libre 0-3)
        used_slots = set()
        with self.net_server._clients_lock:
            for a, c in self.net_server._clients.items():
                if self.net_server._client_room.get(a) == room_id:
                    used_slots.add(self.net_server._client_slot.get(a, -1))

        slot = None
        for s in range(MAX_PLAYERS):
            if s not in used_slots:
                slot = s
                break
        if slot is None:
            return None

        self.net_server._client_room[addr] = room_id
        self.net_server._client_slot[addr] = slot

        # Si no hay admin, asignar este jugador
        if adapter.get_admin_player_id() is None:
            adapter.set_admin(slot)

        with self.net_server._clients_lock:
            client = self.net_server._clients.get(addr)
            name = client.name if client else "Player"

        if adapter.on_player_join:
            adapter.on_player_join(slot, name)

        print(f"[ROOM_MGR] Player '{name}' joined room {room_id} (slot={slot})")
        return slot

    def join_room_by_code(self, code, addr):
        """Une un cliente a una sala por código.
        Retorna (room_id, slot) o None."""
        room_id = self._codes.get(code)
        if room_id is None:
            return None
        slot = self.join_room(room_id, addr)
        if slot is None:
            return None
        return room_id, slot

    def leave_room(self, addr):
        """Saca un cliente de su sala actual. Retorna room_id o None."""
        room_id = self.net_server._client_room.pop(addr, None)
        slot = self.net_server._client_slot.pop(addr, None)
        if room_id is None:
            return None

        adapter = self.adapters.get(room_id)
        if adapter and adapter.on_player_leave:
            adapter.on_player_leave(slot)

        # Si era admin, reasignar
        if adapter and adapter.get_admin_player_id() == slot:
            adapter.reassign_admin()

        with self.net_server._clients_lock:
            client = self.net_server._clients.get(addr)
            name = client.name if client else "?"
        print(f"[ROOM_MGR] Player '{name}' left room {room_id}")

        return room_id

    def get_room_list(self):
        """Retorna lista de info de salas públicas para el browser."""
        result = []
        for room_id, room in self.rooms.items():
            if room.is_private:
                continue
            adapter = self.adapters[room_id]
            state_map = {
                "lobby": 0, "countdown": 1, "racing": 2, "done": 3,
            }
            result.append({
                "room_id": room_id,
                "code": room.room_code,
                "name": room.room_name,
                "track": room.track_file,
                "players": adapter.get_connected_count(),
                "max_players": room.max_players,
                "state": state_map.get(room.state, 0),
                "is_private": room.is_private,
            })
        return result

    def get_room_for_client(self, addr):
        """Retorna room_id del cliente o None."""
        return self.net_server._client_room.get(addr)

    def tick_all(self, dt):
        """Tick cada Room + cleanup de salas vacías."""
        for room_id in list(self.rooms.keys()):
            room = self.rooms.get(room_id)
            if room:
                room.tick(dt)

        self._cleanup_empty_rooms()

    def _cleanup_empty_rooms(self):
        """Destruye salas sin jugadores (solo en estado lobby o done)."""
        to_remove = []
        for room_id, room in self.rooms.items():
            adapter = self.adapters.get(room_id)
            if not adapter:
                continue
            if adapter.get_connected_count() == 0 and room.state in ("lobby", "done"):
                to_remove.append(room_id)

        for room_id in to_remove:
            room = self.rooms.pop(room_id, None)
            adapter = self.adapters.pop(room_id, None)
            if room:
                code = room.room_code
                self._codes.pop(code, None)
                print(f"[ROOM_MGR] Room '{room.room_name}' (id={room_id}) "
                      f"destroyed (empty)")

    def get_room_state_for_reject(self, room_id):
        """Retorna el motivo de rechazo apropiado para una sala."""
        from networking.protocol import ROOM_NOT_FOUND, ROOM_FULL, ROOM_RACING
        if room_id not in self.rooms:
            return ROOM_NOT_FOUND
        room = self.rooms[room_id]
        adapter = self.adapters[room_id]
        if room.state != "lobby":
            return ROOM_RACING
        if adapter.get_connected_count() >= room.max_players:
            return ROOM_FULL
        return ROOM_NOT_FOUND
