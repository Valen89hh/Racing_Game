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

from networking.protocol import (
    get_packet_type,
    PKT_JOIN_REQUEST, PKT_PLAYER_INPUT, PKT_TRACK_ACK,
    PKT_PING, PKT_PONG, PKT_DISCONNECT,
    unpack_join_request, unpack_input, unpack_track_ack, unpack_ping,
    pack_join_accept, pack_join_reject, pack_pong,
    pack_lobby_state, pack_race_start, pack_track_chunks,
    pack_state_snapshot, pack_powerup_event,
    pack_disconnect,
    REJECT_FULL, REJECT_RACING,
)
from networking.net_state import InputState

from settings import (
    NET_DEFAULT_PORT, NET_TIMEOUT, NET_HEARTBEAT_INTERVAL, MAX_PLAYERS,
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

    def __init__(self, port=None, relay_socket=None):
        self.port = port or NET_DEFAULT_PORT
        self.socket = None
        self._running = False
        self._thread = None
        self._relay_socket = relay_socket  # RelaySocket pre-creado o None
        self._use_relay = relay_socket is not None

        # Clientes conectados: addr → ClientInfo
        self._clients = {}
        self._clients_lock = threading.Lock()

        # Inputs recibidos: player_id → InputState
        self._inputs = {}
        self._inputs_lock = threading.Lock()

        # Asignación de player IDs (0 = host, 1-3 = clientes)
        self._next_player_id = 1

        # Estado del lobby
        self.host_name = "Host"
        self.bot_count = 1
        self.track_name = ""
        self.racing = False

        # Track transfer (non-blocking)
        self._track_send_thread = None
        self._track_send_done = False
        self._track_send_ok = False

        # Callbacks
        self.on_player_join = None    # (player_id, name) → None
        self.on_player_leave = None   # (player_id) → None

    def start(self):
        """Inicia el servidor en un hilo daemon."""
        if self._use_relay:
            self.socket = self._relay_socket
            self.socket.start()
            print(f"[SERVER] Started via relay room={self.socket.room_code}")
        else:
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
            if self._use_relay:
                # En relay, broadcast disconnect y luego cerrar
                try:
                    self.socket.sendto_broadcast(pack_disconnect())
                except (OSError, AttributeError):
                    pass
            else:
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
                elif pkt_type == PKT_PING:
                    self._handle_ping(data, addr)
                elif pkt_type == PKT_DISCONNECT:
                    self._handle_disconnect(addr)
            except Exception as e:
                print(f"[SERVER] Error handling pkt 0x{pkt_type:02x}: {e}")

    def _handle_join(self, data, addr):
        """Procesa solicitud de unión."""
        name = unpack_join_request(data)

        with self._clients_lock:
            # Ya conectado? Re-enviar accept
            if addr in self._clients:
                client = self._clients[addr]
                pid = client.player_id
                # sendto fuera del lock abajo
            else:
                # Lobby lleno?
                if self._next_player_id >= MAX_PLAYERS:
                    try:
                        self.socket.sendto(pack_join_reject(REJECT_FULL), addr)
                    except OSError:
                        pass
                    return

                # Ya en carrera?
                if self.racing:
                    try:
                        self.socket.sendto(pack_join_reject(REJECT_RACING), addr)
                    except OSError:
                        pass
                    return

                # Asignar player ID
                pid = self._next_player_id
                self._next_player_id += 1
                client = ClientInfo(addr, pid, name)
                self._clients[addr] = client
                print(f"[SERVER] Player '{name}' joined as P{pid + 1} from {addr}")

        # Enviar accept FUERA del lock
        try:
            self.socket.sendto(pack_join_accept(pid), addr)
        except OSError:
            pass

        if self.on_player_join:
            self.on_player_join(pid, name)

    def _handle_input(self, data, addr):
        """Procesa input de un cliente."""
        with self._clients_lock:
            client = self._clients.get(addr)
            if not client:
                return
            client.last_heartbeat = time.time()

        inp = unpack_input(data)
        input_state = InputState(
            accel=inp["accel"],
            turn=inp["turn"],
            brake=inp["brake"],
            use_powerup=inp["use_powerup"],
            seq=inp["seq"],
        )

        with self._inputs_lock:
            self._inputs[inp["player_id"]] = input_state

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

    def _handle_disconnect(self, addr):
        """Procesa desconexión de un cliente."""
        with self._clients_lock:
            client = self._clients.pop(addr, None)
        if client:
            print(f"[SERVER] Player P{client.player_id + 1} disconnected")
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
            if self.on_player_leave:
                self.on_player_leave(client.player_id)

    # ── API pública ──

    def get_client_inputs(self):
        """Retorna dict de {player_id: InputState}."""
        with self._inputs_lock:
            return dict(self._inputs)

    def clear_input(self, player_id):
        """Limpia input de un jugador específico."""
        with self._inputs_lock:
            self._inputs.pop(player_id, None)

    def broadcast(self, data):
        """Envía datos a todos los clientes conectados."""
        if self._use_relay:
            # Relay broadcast: un solo paquete con target=0xFF
            with self._clients_lock:
                if not self._clients:
                    return
            try:
                self.socket.sendto_broadcast(data)
            except OSError:
                pass
        else:
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
        data = pack_lobby_state(players, self.bot_count, self.track_name)
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
        """Retorna lista de (player_id, name) incluyendo host."""
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
