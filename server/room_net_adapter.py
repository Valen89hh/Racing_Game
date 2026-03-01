"""
room_net_adapter.py - Wrapper que da a Room networking scoped per-room.

Expone la misma API que Room usa de GameServer, pero filtrada a los
clientes de una sala específica. Room no cambia su lógica interna.
"""

import threading
import time
from collections import deque

from networking.protocol import (
    pack_lobby_state, pack_race_start, pack_track_chunks,
    pack_return_lobby, pack_track_list,
)
from networking.net_state import InputState
from settings import SERVER_INPUT_QUEUE_SIZE, MAX_PLAYERS


class RoomNetAdapter:
    """Adapter que expone la misma API de networking que Room espera,
    pero scoped a los clientes de una sala específica."""

    def __init__(self, net_server, room_id):
        self.net_server = net_server  # GameServer ref
        self.room_id = room_id

        # Per-room input state
        self._input_queues = {}         # slot -> deque(InputState)
        self._last_processed_seq = {}   # slot -> int
        self._inputs_lock = threading.Lock()

        # Per-room config (Room writes these)
        self._admin_slot = None
        self.bot_count = 1
        self.track_name = ""
        self.racing = False
        self.host_name = "Server"

        # Track transfer
        self._track_send_done = False
        self._track_send_ok = False

        # Callbacks (set by Room)
        self.on_player_join = None
        self.on_player_leave = None
        self.on_config_change = None

    # ── Helpers para filtrar clientes de esta sala ──

    def _get_room_addrs(self):
        """Retorna lista de addrs de clientes en esta sala."""
        addrs = []
        with self.net_server._clients_lock:
            for addr, client in self.net_server._clients.items():
                if self.net_server._client_room.get(addr) == self.room_id:
                    addrs.append(addr)
        return addrs

    def _get_room_clients(self):
        """Retorna lista de (addr, ClientInfo) en esta sala."""
        clients = []
        with self.net_server._clients_lock:
            for addr, client in self.net_server._clients.items():
                if self.net_server._client_room.get(addr) == self.room_id:
                    clients.append((addr, client))
        return clients

    def _get_slot_for_addr(self, addr):
        """Retorna el slot de un addr en esta sala."""
        return self.net_server._client_slot.get(addr, 0)

    # ── Métodos que Room ya llama ──

    def broadcast(self, data):
        """Envía datos solo a clientes de esta sala."""
        for addr in self._get_room_addrs():
            try:
                self.net_server.socket.sendto(data, addr)
            except OSError:
                pass

    def broadcast_lobby_state(self):
        """Construye y envía lobby state con players de esta sala."""
        players = self.get_player_list()
        admin_pid = self._admin_slot if self._admin_slot is not None else 255
        data = pack_lobby_state(players, self.bot_count, self.track_name,
                                admin_player_id=admin_pid)
        self.broadcast(data)

    def broadcast_race_start(self, countdown=3):
        """Envía señal de inicio de carrera (3x para reliability)."""
        data = pack_race_start(countdown)
        for _ in range(3):
            self.broadcast(data)
            time.sleep(0.01)

    def send_track_data_blocking(self, track_json_str, timeout=10.0):
        """Envía track data de forma bloqueante a clientes de esta sala."""
        chunks = pack_track_chunks(track_json_str)
        total = len(chunks)

        room_clients = self._get_room_clients()
        if not room_clients:
            self._track_send_ok = True
            self._track_send_done = True
            return True

        # Clear track acks for room clients
        with self.net_server._clients_lock:
            for addr, client in room_clients:
                client.track_acks.clear()

        start = time.time()
        while time.time() - start < timeout:
            room_clients = self._get_room_clients()
            if not room_clients:
                self._track_send_ok = True
                self._track_send_done = True
                return True

            all_done = True
            for chunk_idx, chunk_pkt in enumerate(chunks):
                for addr, client in room_clients:
                    if chunk_idx not in client.track_acks:
                        try:
                            self.net_server.socket.sendto(chunk_pkt, addr)
                        except OSError:
                            pass
                        all_done = False

            if all_done:
                self._track_send_ok = True
                self._track_send_done = True
                return True
            time.sleep(0.05)

        self._track_send_ok = False
        self._track_send_done = True
        return False

    def send_track_data_async(self, track_json_str, timeout=10.0):
        """Envía track data en un hilo separado."""
        self._track_send_done = False
        self._track_send_ok = False
        t = threading.Thread(
            target=self.send_track_data_blocking,
            args=(track_json_str, timeout),
            daemon=True,
        )
        t.start()

    def is_track_send_done(self):
        return self._track_send_done

    def is_track_send_ok(self):
        return self._track_send_ok

    def pop_one_input_per_player(self):
        """Pop 1 input por jugador de las colas de esta sala."""
        result = {}
        with self._inputs_lock:
            for slot, queue in self._input_queues.items():
                if queue:
                    inp = queue.popleft()
                    result[slot] = inp
                    self._last_processed_seq[slot] = inp.seq
        return result, dict(self._last_processed_seq)

    def get_last_processed_seqs(self):
        with self._inputs_lock:
            return dict(self._last_processed_seq)

    def get_connected_count(self):
        """Clientes en esta sala."""
        count = 0
        with self.net_server._clients_lock:
            for addr in self.net_server._clients:
                if self.net_server._client_room.get(addr) == self.room_id:
                    count += 1
        return count

    def get_player_list(self):
        """Retorna [(slot, name)] de clientes en esta sala."""
        players = []
        with self.net_server._clients_lock:
            for addr, client in self.net_server._clients.items():
                if self.net_server._client_room.get(addr) == self.room_id:
                    slot = self.net_server._client_slot.get(addr, 0)
                    players.append((slot, client.name))
        return sorted(players, key=lambda p: p[0])

    def send_to_player(self, slot, data):
        """Unicast por slot dentro de esta sala."""
        with self.net_server._clients_lock:
            for addr, client in self.net_server._clients.items():
                if (self.net_server._client_room.get(addr) == self.room_id and
                        self.net_server._client_slot.get(addr) == slot):
                    try:
                        self.net_server.socket.sendto(data, addr)
                    except OSError:
                        pass
                    return

    def get_admin_player_id(self):
        """Admin slot de esta sala."""
        return self._admin_slot

    def reset_for_new_lobby(self):
        """Limpiar inputs y broadcast RETURN_LOBBY a esta sala."""
        self.racing = False
        with self._inputs_lock:
            self._input_queues.clear()
            self._last_processed_seq.clear()
        data = pack_return_lobby()
        for _ in range(3):
            self.broadcast(data)
            time.sleep(0.01)
        self._track_send_done = False
        self._track_send_ok = False

    def set_bot_count(self, count):
        connected = self.get_connected_count()
        max_bots = MAX_PLAYERS - connected
        self.bot_count = max(0, min(count, max_bots))

    def enqueue_input(self, slot, input_state):
        """Llamado por GameServer para enrutar input a esta sala."""
        with self._inputs_lock:
            if slot not in self._input_queues:
                self._input_queues[slot] = deque(maxlen=SERVER_INPUT_QUEUE_SIZE)

            last_proc = self._last_processed_seq.get(slot, 0)
            diff = (input_state.seq - last_proc) & 0xFFFF
            if diff == 0 or diff >= 32768:
                return  # Duplicado o antiguo

            queue = self._input_queues[slot]
            if not queue or self._seq_after(input_state.seq, queue[-1].seq):
                queue.append(input_state)
            else:
                for i in range(len(queue)):
                    if input_state.seq == queue[i].seq:
                        break
                    if not self._seq_after(input_state.seq, queue[i].seq):
                        queue.insert(i, input_state)
                        break
                else:
                    queue.append(input_state)

    @staticmethod
    def _seq_after(a, b):
        return 0 < ((a - b) & 0xFFFF) < 32768

    def set_admin(self, slot):
        """Establece el admin de esta sala."""
        self._admin_slot = slot

    def reassign_admin(self):
        """Reasigna admin al jugador con menor slot en la sala."""
        players = self.get_player_list()
        if not players:
            self._admin_slot = None
            return
        new_admin_slot = players[0][0]
        self._admin_slot = new_admin_slot
        # Notificar al nuevo admin
        from networking.protocol import pack_join_accept
        self.send_to_player(new_admin_slot,
                            pack_join_accept(new_admin_slot, is_admin=True, multi_room=True))
