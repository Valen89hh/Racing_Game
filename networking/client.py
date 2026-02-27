"""
client.py - Cliente UDP para conectarse al host.

Envía inputs al servidor y recibe snapshots de estado.
Mantiene un buffer circular de snapshots para interpolación.
"""

import socket
import threading
import time
import json

from networking.protocol import (
    get_packet_type,
    PKT_JOIN_ACCEPT, PKT_JOIN_REJECT, PKT_STATE_SNAPSHOT,
    PKT_LOBBY_STATE, PKT_RACE_START, PKT_TRACK_DATA,
    PKT_POWERUP_EVENT, PKT_PONG, PKT_DISCONNECT,
    unpack_join_accept, unpack_join_reject, unpack_state_snapshot,
    unpack_lobby_state, unpack_race_start, unpack_track_chunk,
    unpack_powerup_event, unpack_ping,
    pack_join_request, pack_input, pack_track_ack,
    pack_ping, pack_disconnect,
)
from networking.net_state import StateSnapshot, InputState

from settings import (
    NET_DEFAULT_PORT, NET_TIMEOUT, NET_HEARTBEAT_INTERVAL,
    NET_MAX_SNAPSHOT_BUFFER,
)


class GameClient:
    """Cliente UDP para conectarse a un host."""

    def __init__(self, host_ip, port=None, relay_socket=None):
        self.host_ip = host_ip
        self.port = port or NET_DEFAULT_PORT
        self.host_addr = (host_ip, self.port)
        self.socket = None
        self._running = False
        self._thread = None
        self._relay_socket = relay_socket  # RelaySocket pre-creado o None
        self._use_relay = relay_socket is not None

        # Estado de conexión (thread-safe)
        self.connected = False
        self.player_id = -1
        self.max_players = 4
        self.reject_reason = 0
        self._connect_done = False  # True cuando connect termina
        self._connect_ok = False    # True si fue aceptado

        # Lobby
        self.lobby_state = None
        self._lobby_lock = threading.Lock()

        # Race
        self.race_started = False
        self.countdown = 3

        # Track data
        self._track_chunks = {}
        self._track_total_chunks = 0
        self._track_json = None
        self._track_lock = threading.Lock()

        # Snapshots (buffer circular)
        self._snapshots = []
        self._snapshot_lock = threading.Lock()

        # Power-up events
        self._powerup_events = []
        self._pw_events_lock = threading.Lock()

        # Ping
        self._ping_ms = 0.0
        self._last_ping_sent = 0.0
        self._ping_lock = threading.Lock()

        # Input sequence
        self._input_seq = 0

    def connect_async(self, player_name):
        """Inicia conexión en un hilo separado (no bloquea game loop)."""
        if self._use_relay:
            self.socket = self._relay_socket
            self.socket.start()
            self.host_addr = ("relay_peer", 0)  # fake addr del host
        else:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.settimeout(0.1)
        self._connect_done = False
        self._connect_ok = False
        self._connect_thread = threading.Thread(
            target=self._connect_worker,
            args=(player_name,),
            daemon=True,
        )
        self._connect_thread.start()

    def _connect_worker(self, player_name):
        """Worker thread que maneja el handshake de conexión."""
        data = pack_join_request(player_name)
        timeout = 5.0
        start = time.time()
        retry_interval = 0.3
        last_send = 0.0

        print(f"[CLIENT] Connecting to {self.host_addr}...")

        while time.time() - start < timeout:
            # Enviar/reenviar request periódicamente
            now = time.time()
            if now - last_send > retry_interval:
                try:
                    self.socket.sendto(data, self.host_addr)
                except OSError as e:
                    print(f"[CLIENT] Send error: {e}")
                    break
                last_send = now

            # Leer respuesta
            try:
                resp, addr = self.socket.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            pkt_type = get_packet_type(resp)
            if pkt_type == PKT_JOIN_ACCEPT:
                self.player_id, self.max_players = unpack_join_accept(resp)
                self.connected = True
                self._connect_ok = True
                self._connect_done = True
                print(f"[CLIENT] Connected as Player {self.player_id + 1}")
                # Iniciar recv loop
                self._running = True
                self._thread = threading.Thread(target=self._recv_loop, daemon=True)
                self._thread.start()
                return
            elif pkt_type == PKT_JOIN_REJECT:
                self.reject_reason = unpack_join_reject(resp)
                self._connect_ok = False
                self._connect_done = True
                print(f"[CLIENT] Rejected (reason={self.reject_reason})")
                return
            # Ignorar otros paquetes (LOBBY_STATE, etc.) durante handshake

        print(f"[CLIENT] Connection timeout")
        self._connect_ok = False
        self._connect_done = True

    def disconnect(self):
        """Desconecta del servidor."""
        self._running = False
        self.connected = False
        if self.socket:
            try:
                self.socket.sendto(pack_disconnect(), self.host_addr)
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=2)
        if self.socket:
            try:
                self.socket.close()
            except (OSError, Exception):
                pass
            self.socket = None

    def _recv_loop(self):
        """Hilo de recepción continua."""
        last_ping = time.time()

        while self._running:
            try:
                data, addr = self.socket.recvfrom(8192)
            except socket.timeout:
                # Enviar ping periódico
                now = time.time()
                if now - last_ping > NET_HEARTBEAT_INTERVAL:
                    try:
                        self.socket.sendto(pack_ping(), self.host_addr)
                    except OSError:
                        pass
                    last_ping = now
                continue
            except OSError:
                break

            pkt_type = get_packet_type(data)
            try:
                if pkt_type == PKT_STATE_SNAPSHOT:
                    self._handle_snapshot(data)
                elif pkt_type == PKT_LOBBY_STATE:
                    self._handle_lobby_state(data)
                elif pkt_type == PKT_RACE_START:
                    self._handle_race_start(data)
                elif pkt_type == PKT_TRACK_DATA:
                    self._handle_track_data(data)
                elif pkt_type == PKT_POWERUP_EVENT:
                    self._handle_powerup_event(data)
                elif pkt_type == PKT_PONG:
                    self._handle_pong(data)
                elif pkt_type == PKT_DISCONNECT:
                    self._handle_disconnect()
                elif pkt_type == PKT_JOIN_ACCEPT:
                    # Re-accept (idempotent)
                    self.player_id, self.max_players = unpack_join_accept(data)
            except Exception as e:
                print(f"[CLIENT] Error handling pkt 0x{pkt_type:02x}: {e}")

    def _handle_snapshot(self, data):
        raw = unpack_state_snapshot(data)
        snapshot = StateSnapshot(raw)
        with self._snapshot_lock:
            self._snapshots.append(snapshot)
            if len(self._snapshots) > NET_MAX_SNAPSHOT_BUFFER:
                self._snapshots.pop(0)

    def _handle_lobby_state(self, data):
        lobby = unpack_lobby_state(data)
        with self._lobby_lock:
            self.lobby_state = lobby

    def _handle_race_start(self, data):
        self.countdown = unpack_race_start(data)
        self.race_started = True
        print(f"[CLIENT] Race starting! countdown={self.countdown}")

    def _handle_track_data(self, data):
        chunk_idx, total, chunk_bytes = unpack_track_chunk(data)
        with self._track_lock:
            self._track_total_chunks = total
            self._track_chunks[chunk_idx] = chunk_bytes

            # Enviar ACK
            try:
                self.socket.sendto(pack_track_ack(chunk_idx), self.host_addr)
            except OSError:
                pass

            # Reconstruir si tenemos todos los chunks
            if len(self._track_chunks) >= total:
                raw = b""
                for i in range(total):
                    raw += self._track_chunks.get(i, b"")
                try:
                    self._track_json = json.loads(raw.decode("utf-8"))
                    print(f"[CLIENT] Track data received ({total} chunks)")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    print(f"[CLIENT] Track data decode error")
                    self._track_json = None

    def _handle_powerup_event(self, data):
        event = unpack_powerup_event(data)
        with self._pw_events_lock:
            self._powerup_events.append(event)

    def _handle_pong(self, data):
        ts = unpack_ping(data)
        rtt = time.time() - ts
        with self._ping_lock:
            self._ping_ms = rtt * 1000.0

    def _handle_disconnect(self):
        print(f"[CLIENT] Host disconnected")
        self.connected = False
        self._running = False

    # ── API pública ──

    def send_input(self, accel, turn, brake, use_powerup):
        """Envía input del frame al servidor."""
        if not self.connected or not self.socket:
            return
        self._input_seq = (self._input_seq + 1) % 65536
        data = pack_input(self.player_id, accel, turn, brake,
                          use_powerup, self._input_seq)
        try:
            self.socket.sendto(data, self.host_addr)
        except OSError:
            pass

    def get_latest_snapshot(self):
        """Retorna el snapshot más reciente o None."""
        with self._snapshot_lock:
            if self._snapshots:
                return self._snapshots[-1]
        return None

    def get_interpolation_states(self):
        """Retorna (prev, curr) snapshots para interpolación."""
        with self._snapshot_lock:
            if len(self._snapshots) >= 2:
                return self._snapshots[-2], self._snapshots[-1]
            elif self._snapshots:
                return None, self._snapshots[-1]
        return None, None

    def get_ping(self):
        """Retorna ping en ms."""
        with self._ping_lock:
            return self._ping_ms

    def get_lobby_state(self):
        """Retorna último estado del lobby."""
        with self._lobby_lock:
            return self.lobby_state

    def get_track_data(self):
        """Retorna track JSON si está completo, o None."""
        with self._track_lock:
            return self._track_json

    def get_track_progress(self):
        """Retorna fracción de chunks recibidos (0.0 a 1.0)."""
        with self._track_lock:
            if self._track_total_chunks == 0:
                return 0.0
            return len(self._track_chunks) / self._track_total_chunks

    def pop_powerup_events(self):
        """Retorna y limpia lista de eventos de power-up pendientes."""
        with self._pw_events_lock:
            events = list(self._powerup_events)
            self._powerup_events.clear()
        return events

    def is_host_alive(self):
        """Verifica si el host sigue vivo basándose en snapshots recientes."""
        with self._snapshot_lock:
            if not self._snapshots:
                return self.connected
            last = self._snapshots[-1]
            return (time.time() - last.recv_time) < NET_TIMEOUT
