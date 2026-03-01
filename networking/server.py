"""
server.py - Servidor UDP para el host del juego multijugador.

El host crea un GameServer que escucha en un puerto UDP.
Los clientes envían JOIN_REQUEST y luego inputs cada frame.
El host broadcast snapshots de estado a todos los clientes.
"""

import socket
import threading
import time
import json
from collections import deque

from networking.protocol import (
    get_packet_type,
    PKT_JOIN_REQUEST, PKT_PLAYER_INPUT, PKT_TRACK_ACK,
    PKT_PING, PKT_PONG, PKT_DISCONNECT,
    PKT_SERVER_CONFIG, PKT_RETURN_LOBBY,
    PKT_ROOM_LIST_REQ, PKT_ROOM_CREATE, PKT_ROOM_JOIN, PKT_ROOM_LEAVE,
    unpack_join_request, unpack_input, unpack_track_ack, unpack_ping,
    unpack_server_config,
    unpack_room_create, unpack_room_join,
    pack_join_accept, pack_join_reject, pack_pong,
    pack_lobby_state, pack_race_start, pack_track_chunks,
    pack_state_snapshot, pack_powerup_event,
    pack_disconnect, pack_return_lobby,
    pack_room_list, pack_room_create_ok, pack_room_accept, pack_room_reject,
    REJECT_FULL, REJECT_RACING,
    ROOM_JOIN_BY_ID, ROOM_JOIN_BY_CODE,
    ROOM_FULL, ROOM_RACING, ROOM_NOT_FOUND, MAX_ROOMS_REACHED,
)
from networking.net_state import InputState

from settings import (
    NET_DEFAULT_PORT, NET_TIMEOUT, NET_HEARTBEAT_INTERVAL, MAX_PLAYERS,
    SERVER_INPUT_QUEUE_SIZE,
)


class ClientInfo:
    """Información de un cliente conectado."""
    __slots__ = ('addr', 'player_id', 'name', 'last_heartbeat',
                 'track_acks', 'connected')

    def __init__(self, addr, player_id, name):
        self.addr = addr
        self.player_id = player_id
        self.name = name
        self.last_heartbeat = time.time()
        self.track_acks = set()
        self.connected = True


class GameServer:
    """Servidor UDP para partida multijugador."""

    def __init__(self, port=None, dedicated=False):
        self.port = port or NET_DEFAULT_PORT
        self.socket = None
        self._running = False
        self._thread = None
        self._dedicated = dedicated

        # Clientes conectados: addr → ClientInfo
        self._clients = {}
        self._clients_lock = threading.Lock()

        # Input queues: player_id → deque of InputState (ordered by seq)
        self._input_queues = {}
        self._last_processed_seq = {}
        self._inputs_lock = threading.Lock()

        # Asignación de player IDs
        # Dedicated: IDs desde 0 (no hay host local)
        # Host mode: IDs desde 1 (host = 0)
        self._next_player_id = 0 if dedicated else 1

        # Estado del lobby
        self.host_name = "Host"
        self.bot_count = 1
        self.track_name = ""
        self.racing = False

        # Track transfer (non-blocking)
        self._track_send_thread = None
        self._track_send_done = False
        self._track_send_ok = False

        # Admin (dedicated server only)
        self._admin_player_id = None  # player_id del admin, None = no admin

        # Multi-room support
        self._room_manager = None       # set by DedicatedServer if multi-room
        self._client_room = {}          # addr -> room_id (None = en room select)
        self._client_slot = {}          # addr -> slot dentro de la sala

        # Callbacks
        self.on_player_join = None    # (player_id, name) → None
        self.on_player_leave = None   # (player_id) → None
        self.on_config_change = None  # (config_dict) → None

    def start(self):
        """Inicia el servidor en un hilo daemon."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(("0.0.0.0", self.port))
        self.socket.settimeout(0.1)
        print(f"[SERVER] Started on port {self.port}")

        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Para el servidor y cierra el socket."""
        self._running = False
        # Notificar a todos los clientes
        if self.socket:
            with self._clients_lock:
                for client in self._clients.values():
                    try:
                        self.socket.sendto(pack_disconnect(), client.addr)
                    except OSError:
                        pass
        with self._clients_lock:
            self._clients.clear()
        if self._thread:
            self._thread.join(timeout=2)
        if self.socket:
            try:
                self.socket.close()
            except OSError:
                pass
            self.socket = None
        print("[SERVER] Stopped")

    def _recv_loop(self):
        """Hilo de recepción continua."""
        while self._running:
            try:
                data, addr = self.socket.recvfrom(4096)
            except socket.timeout:
                self._check_timeouts()
                continue
            except OSError:
                break

            if len(data) < 1:
                continue

            pkt_type = get_packet_type(data)
            try:
                if pkt_type == PKT_JOIN_REQUEST:
                    self._handle_join(data, addr)
                elif pkt_type == PKT_PLAYER_INPUT:
                    self._handle_input(data, addr)
                elif pkt_type == PKT_TRACK_ACK:
                    self._handle_track_ack(data, addr)
                elif pkt_type == PKT_SERVER_CONFIG:
                    self._handle_server_config(data, addr)
                elif pkt_type == PKT_PING:
                    self._handle_ping(data, addr)
                elif pkt_type == PKT_DISCONNECT:
                    self._handle_disconnect(addr)
                elif pkt_type == PKT_ROOM_LIST_REQ:
                    self._handle_room_list_req(addr)
                elif pkt_type == PKT_ROOM_CREATE:
                    self._handle_room_create(data, addr)
                elif pkt_type == PKT_ROOM_JOIN:
                    self._handle_room_join(data, addr)
                elif pkt_type == PKT_ROOM_LEAVE:
                    self._handle_room_leave(addr)
            except Exception as e:
                print(f"[SERVER] Error handling pkt 0x{pkt_type:02x}: {e}")

    def _handle_join(self, data, addr):
        """Procesa solicitud de unión."""
        name = unpack_join_request(data)

        is_new = False
        is_admin = False
        multi_room = self._room_manager is not None

        with self._clients_lock:
            # Ya conectado? Re-enviar accept
            if addr in self._clients:
                client = self._clients[addr]
                pid = client.player_id
                if not multi_room:
                    is_admin = (self._admin_player_id == pid)
            else:
                if multi_room:
                    # Multi-room: asignar un ID global (solo para tracking)
                    pid = self._next_player_id
                    self._next_player_id += 1
                    client = ClientInfo(addr, pid, name)
                    self._clients[addr] = client
                    is_new = True
                    # No asignar a ninguna sala todavía
                    self._client_room[addr] = None
                    print(f"[SERVER] Player '{name}' connected (multi-room, "
                          f"global_id={pid}) from {addr}")
                else:
                    # Legacy single-room mode
                    if self._next_player_id >= MAX_PLAYERS:
                        try:
                            self.socket.sendto(pack_join_reject(REJECT_FULL), addr)
                        except OSError:
                            pass
                        return

                    if self.racing:
                        try:
                            self.socket.sendto(pack_join_reject(REJECT_RACING), addr)
                        except OSError:
                            pass
                        return

                    pid = self._next_player_id
                    self._next_player_id += 1
                    client = ClientInfo(addr, pid, name)
                    self._clients[addr] = client
                    is_new = True
                    print(f"[SERVER] Player '{name}' joined as P{pid + 1} from {addr}")

                    if self._dedicated and self._admin_player_id is None:
                        self._admin_player_id = pid
                        is_admin = True
                        print(f"[SERVER] Player P{pid + 1} is now admin")

        # Enviar accept FUERA del lock
        try:
            self.socket.sendto(
                pack_join_accept(pid, is_admin=is_admin, multi_room=multi_room),
                addr)
        except OSError:
            pass

        if is_new and not multi_room and self.on_player_join:
            self.on_player_join(pid, name)

    def _handle_input(self, data, addr):
        """Procesa input de un cliente. Soporta paquetes con redundancia (1-3 inputs)."""
        with self._clients_lock:
            client = self._clients.get(addr)
            if not client:
                return
            client.last_heartbeat = time.time()

        input_list = unpack_input(data)

        # Multi-room: route to the room's adapter
        if self._room_manager:
            room_id = self._client_room.get(addr)
            if room_id is None:
                return  # Not in a room, ignore inputs
            adapter = self._room_manager.adapters.get(room_id)
            if not adapter:
                return
            slot = self._client_slot.get(addr, 0)
            for inp in input_list:
                input_state = InputState(
                    accel=inp["accel"],
                    turn=inp["turn"],
                    brake=inp["brake"],
                    use_powerup=inp["use_powerup"],
                    seq=inp["seq"],
                )
                adapter.enqueue_input(slot, input_state)
            return

        # Legacy single-room mode
        for inp in input_list:
            input_state = InputState(
                accel=inp["accel"],
                turn=inp["turn"],
                brake=inp["brake"],
                use_powerup=inp["use_powerup"],
                seq=inp["seq"],
            )
            pid = inp["player_id"]

            with self._inputs_lock:
                if pid not in self._input_queues:
                    self._input_queues[pid] = deque(maxlen=SERVER_INPUT_QUEUE_SIZE)

                last_proc = self._last_processed_seq.get(pid, 0)
                diff = (input_state.seq - last_proc) & 0xFFFF
                if diff == 0 or diff >= 32768:
                    continue  # Duplicado o antiguo

                queue = self._input_queues[pid]
                if not queue or self._seq_after(input_state.seq, queue[-1].seq):
                    queue.append(input_state)  # Caso común: llega en orden
                else:
                    # Out-of-order: insertar en posición correcta (raro)
                    inserted = False
                    for i in range(len(queue)):
                        if input_state.seq == queue[i].seq:
                            inserted = True
                            break  # duplicado
                        if not self._seq_after(input_state.seq, queue[i].seq):
                            queue.insert(i, input_state)
                            inserted = True
                            break
                    if not inserted:
                        queue.append(input_state)

    @staticmethod
    def _seq_after(a, b):
        """True si seq a es posterior a seq b (uint16 wrapping)."""
        return 0 < ((a - b) & 0xFFFF) < 32768

    def _handle_track_ack(self, data, addr):
        """Registra ACK de chunk de track recibido."""
        chunk_idx = unpack_track_ack(data)
        with self._clients_lock:
            client = self._clients.get(addr)
            if client:
                client.track_acks.add(chunk_idx)

    def _handle_ping(self, data, addr):
        """Responde PONG con el mismo timestamp."""
        ts = unpack_ping(data)
        try:
            self.socket.sendto(pack_pong(ts), addr)
        except OSError:
            pass
        with self._clients_lock:
            client = self._clients.get(addr)
            if client:
                client.last_heartbeat = time.time()

    def _handle_server_config(self, data, addr):
        """Procesa paquete de configuración del admin."""
        with self._clients_lock:
            client = self._clients.get(addr)
            if not client:
                return
            client.last_heartbeat = time.time()

        if self._room_manager:
            # Multi-room: route to the room's adapter
            room_id = self._client_room.get(addr)
            if room_id is None:
                return
            adapter = self._room_manager.adapters.get(room_id)
            if not adapter:
                return
            slot = self._client_slot.get(addr, 0)
            if slot != adapter.get_admin_player_id():
                return  # Solo el admin puede cambiar config
            config = unpack_server_config(data)
            if adapter.on_config_change:
                adapter.on_config_change(config)
        else:
            # Legacy single-room
            with self._clients_lock:
                if client.player_id != self._admin_player_id:
                    return
            config = unpack_server_config(data)
            if self.on_config_change:
                self.on_config_change(config)

    def _handle_disconnect(self, addr):
        """Procesa desconexión de un cliente."""
        # Multi-room: leave room first
        if self._room_manager:
            self._room_manager.leave_room(addr)

        with self._clients_lock:
            client = self._clients.pop(addr, None)
        if client:
            print(f"[SERVER] Player P{client.player_id + 1} disconnected")
            # Clean up room tracking
            self._client_room.pop(addr, None)
            self._client_slot.pop(addr, None)

            if not self._room_manager:
                if client.player_id == self._admin_player_id:
                    self._reassign_admin()
                if self.on_player_leave:
                    self.on_player_leave(client.player_id)

    def _check_timeouts(self):
        """Desconecta clientes sin heartbeat."""
        now = time.time()
        timed_out = []
        with self._clients_lock:
            for addr, client in list(self._clients.items()):
                if now - client.last_heartbeat > NET_TIMEOUT:
                    timed_out.append((addr, client))
                    del self._clients[addr]

        for addr, client in timed_out:
            print(f"[SERVER] Player P{client.player_id + 1} timed out")
            if self._room_manager:
                self._room_manager.leave_room(addr)
                self._client_room.pop(addr, None)
                self._client_slot.pop(addr, None)
            else:
                if client.player_id == self._admin_player_id:
                    self._reassign_admin()
                if self.on_player_leave:
                    self.on_player_leave(client.player_id)

    def _reassign_admin(self):
        """Reasigna admin al jugador con menor player_id."""
        with self._clients_lock:
            if not self._clients:
                self._admin_player_id = None
                print("[SERVER] No players left, no admin")
                return
            # Encontrar el cliente con menor player_id
            min_client = min(self._clients.values(), key=lambda c: c.player_id)
            self._admin_player_id = min_client.player_id
            new_admin_addr = min_client.addr
            print(f"[SERVER] Admin reassigned to P{self._admin_player_id + 1}")

        # Notificar al nuevo admin con un re-accept
        try:
            self.socket.sendto(
                pack_join_accept(self._admin_player_id, is_admin=True),
                new_admin_addr)
        except OSError:
            pass

    # ── Room management handlers (multi-room mode) ──

    def _handle_room_list_req(self, addr):
        """Envía la lista de salas públicas al cliente."""
        if not self._room_manager:
            return
        with self._clients_lock:
            client = self._clients.get(addr)
            if not client:
                return
            client.last_heartbeat = time.time()
        rooms = self._room_manager.get_room_list()
        try:
            self.socket.sendto(pack_room_list(rooms), addr)
        except OSError:
            pass

    def _handle_room_create(self, data, addr):
        """Crea una nueva sala."""
        if not self._room_manager:
            return
        with self._clients_lock:
            client = self._clients.get(addr)
            if not client:
                return
            client.last_heartbeat = time.time()

        info = unpack_room_create(data)
        result = self._room_manager.create_room(
            info["name"], info["is_private"], addr)
        if result is None:
            try:
                self.socket.sendto(pack_room_reject(MAX_ROOMS_REACHED), addr)
            except OSError:
                pass
            return

        room_id, code, slot = result
        try:
            self.socket.sendto(pack_room_create_ok(room_id, code, slot), addr)
        except OSError:
            pass

    def _handle_room_join(self, data, addr):
        """Une un cliente a una sala existente."""
        if not self._room_manager:
            return
        with self._clients_lock:
            client = self._clients.get(addr)
            if not client:
                return
            client.last_heartbeat = time.time()

        info = unpack_room_join(data)

        if info["mode"] == ROOM_JOIN_BY_ID:
            room_id = info["room_id"]
            slot = self._room_manager.join_room(room_id, addr)
            if slot is None:
                reason = self._room_manager.get_room_state_for_reject(room_id)
                try:
                    self.socket.sendto(pack_room_reject(reason), addr)
                except OSError:
                    pass
                return
            is_admin = (self._room_manager.adapters[room_id].get_admin_player_id() == slot)
            try:
                self.socket.sendto(pack_room_accept(room_id, slot, is_admin), addr)
            except OSError:
                pass
        else:
            code = info["code"]
            result = self._room_manager.join_room_by_code(code, addr)
            if result is None:
                try:
                    self.socket.sendto(pack_room_reject(ROOM_NOT_FOUND), addr)
                except OSError:
                    pass
                return
            room_id, slot = result
            is_admin = (self._room_manager.adapters[room_id].get_admin_player_id() == slot)
            try:
                self.socket.sendto(pack_room_accept(room_id, slot, is_admin), addr)
            except OSError:
                pass

    def _handle_room_leave(self, addr):
        """Saca un cliente de su sala actual."""
        if not self._room_manager:
            return
        with self._clients_lock:
            client = self._clients.get(addr)
            if not client:
                return
            client.last_heartbeat = time.time()

        self._room_manager.leave_room(addr)
        # Client stays connected to the server, just not in any room

    # ── API pública ──

    def pop_one_input_per_player(self):
        """Pop 1 input por jugador. Retorna (inputs_dict, last_seqs_dict)."""
        result = {}
        with self._inputs_lock:
            for pid, queue in self._input_queues.items():
                if queue:
                    inp = queue.popleft()
                    result[pid] = inp
                    self._last_processed_seq[pid] = inp.seq
        return result, dict(self._last_processed_seq)

    def pop_all_inputs_per_player(self):
        """Pop ALL queued inputs per player. Returns {pid: [InputState, ...]}."""
        result = {}
        with self._inputs_lock:
            for pid, queue in self._input_queues.items():
                if queue:
                    result[pid] = list(queue)
                    self._last_processed_seq[pid] = queue[-1].seq
                    queue.clear()
        return result

    def get_last_processed_seqs(self):
        """Retorna dict de {player_id: last_processed_seq}."""
        with self._inputs_lock:
            return dict(self._last_processed_seq)

    def broadcast(self, data):
        """Envía datos a todos los clientes conectados."""
        with self._clients_lock:
            addrs = [c.addr for c in self._clients.values() if c.connected]
        for addr in addrs:
            try:
                self.socket.sendto(data, addr)
            except OSError:
                pass

    def broadcast_lobby_state(self):
        """Broadcast estado actual del lobby."""
        players = self.get_player_list()
        admin_pid = self._admin_player_id if self._admin_player_id is not None else 255
        data = pack_lobby_state(players, self.bot_count, self.track_name,
                                admin_player_id=admin_pid)
        self.broadcast(data)

    def broadcast_race_start(self, countdown=3):
        """Envía señal de inicio de carrera (3x para reliability)."""
        data = pack_race_start(countdown)
        for _ in range(3):
            self.broadcast(data)
            time.sleep(0.01)  # pequeña pausa para que el cliente los procese

    def send_track_data_async(self, track_json_str, timeout=10.0):
        """Envía track data en un hilo separado (no bloquea game loop)."""
        self._track_send_done = False
        self._track_send_ok = False
        self._track_send_thread = threading.Thread(
            target=self._send_track_worker,
            args=(track_json_str, timeout),
            daemon=True,
        )
        self._track_send_thread.start()

    def _send_track_worker(self, track_json_str, timeout):
        """Worker thread para enviar track chunks con ACK."""
        chunks = pack_track_chunks(track_json_str)
        total = len(chunks)
        print(f"[SERVER] Sending track data: {len(track_json_str)} bytes in {total} chunks")

        with self._clients_lock:
            for c in self._clients.values():
                c.track_acks.clear()

        start = time.time()
        while time.time() - start < timeout:
            with self._clients_lock:
                clients = list(self._clients.values())

            if not clients:
                # Sin clientes, nada que enviar
                self._track_send_ok = True
                self._track_send_done = True
                return

            all_done = True
            for chunk_idx, chunk_pkt in enumerate(chunks):
                for client in clients:
                    if chunk_idx not in client.track_acks:
                        try:
                            self.socket.sendto(chunk_pkt, client.addr)
                        except OSError:
                            pass
                        all_done = False

            if all_done:
                print(f"[SERVER] Track data sent successfully")
                self._track_send_ok = True
                self._track_send_done = True
                return
            time.sleep(0.05)

        print(f"[SERVER] Track data send timeout")
        self._track_send_ok = False
        self._track_send_done = True

    def send_track_data_blocking(self, track_json_str, timeout=10.0):
        """Envía track data de forma bloqueante (para servidor dedicado)."""
        self.send_track_data_async(track_json_str, timeout)
        while not self.is_track_send_done():
            time.sleep(0.05)
        return self.is_track_send_ok()

    def is_track_send_done(self):
        """Verifica si el envío async de track terminó."""
        return self._track_send_done

    def is_track_send_ok(self):
        """Verifica si el envío async de track fue exitoso."""
        return self._track_send_ok

    def get_connected_count(self):
        """Retorna número de clientes conectados."""
        with self._clients_lock:
            return len(self._clients)

    def get_player_list(self):
        """Retorna lista de (player_id, name).
        En modo dedicado: solo clientes (no hay host local).
        En modo host: incluye host como player 0."""
        if self._dedicated:
            with self._clients_lock:
                players = [(c.player_id, c.name)
                           for c in self._clients.values()]
            return sorted(players, key=lambda p: p[0])
        else:
            players = [(0, self.host_name)]
            with self._clients_lock:
                for client in self._clients.values():
                    players.append((client.player_id, client.name))
            return sorted(players, key=lambda p: p[0])

    def set_bot_count(self, count):
        """Ajusta el número de bots."""
        max_bots = MAX_PLAYERS - 1 - self.get_connected_count()
        self.bot_count = max(0, min(count, max_bots))

    def kick_client(self, player_id):
        """Desconecta un cliente por player_id."""
        with self._clients_lock:
            to_remove = None
            for addr, client in self._clients.items():
                if client.player_id == player_id:
                    to_remove = addr
                    break
            if to_remove:
                del self._clients[to_remove]
        if to_remove:
            try:
                self.socket.sendto(pack_disconnect(), to_remove)
            except OSError:
                pass

    def send_to_player(self, player_id, data):
        """Envía datos a un jugador específico por player_id."""
        with self._clients_lock:
            for client in self._clients.values():
                if client.player_id == player_id:
                    try:
                        self.socket.sendto(data, client.addr)
                    except OSError:
                        pass
                    return

    def get_admin_player_id(self):
        """Retorna el player_id del admin o None."""
        return self._admin_player_id

    def reset_for_new_lobby(self):
        """Reset estado para nueva ronda de lobby. Broadcast PKT_RETURN_LOBBY."""
        self.racing = False
        # Limpiar input queues
        with self._inputs_lock:
            self._input_queues.clear()
            self._last_processed_seq.clear()
        # Broadcast return to lobby (3x para reliability)
        data = pack_return_lobby()
        for _ in range(3):
            self.broadcast(data)
            time.sleep(0.01)
        # Reset track transfer state
        self._track_send_done = False
        self._track_send_ok = False

    def get_local_ip(self):
        """Intenta obtener la IP local de la máquina."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
