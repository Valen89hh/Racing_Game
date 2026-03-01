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
    PKT_TRACK_LIST, PKT_RETURN_LOBBY,
    PKT_ROOM_LIST, PKT_ROOM_CREATE_OK, PKT_ROOM_ACCEPT, PKT_ROOM_REJECT,
    unpack_join_accept, unpack_join_reject, unpack_state_snapshot,
    unpack_lobby_state, unpack_race_start, unpack_track_chunk,
    unpack_powerup_event, unpack_ping, unpack_track_list,
    unpack_room_list, unpack_room_create_ok, unpack_room_accept, unpack_room_reject,
    pack_join_request, pack_input, pack_input_redundant,
    pack_track_ack,
    pack_ping, pack_disconnect,
    pack_server_config_track, pack_server_config_bots, pack_server_config_start,
    pack_room_list_req, pack_room_create, pack_room_join_by_id,
    pack_room_join_by_code, pack_room_leave,
    INPUT_REDUNDANCY,
)
from networking.net_state import StateSnapshot, InputState

from settings import (
    NET_DEFAULT_PORT, NET_TIMEOUT, NET_HEARTBEAT_INTERVAL,
    NET_MAX_SNAPSHOT_BUFFER, NET_INTERPOLATION_DELAY,
    NET_INTERP_MIN_DELAY, NET_INTERP_MAX_DELAY,
)


class GameClient:
    """Cliente UDP para conectarse a un host."""

    def __init__(self, host_ip, port=None):
        self.host_ip = host_ip
        self.port = port or NET_DEFAULT_PORT
        self.host_addr = (host_ip, self.port)
        self.socket = None
        self._running = False
        self._thread = None

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

        # Admin (dedicated server)
        self.is_admin = False
        self._track_list = []
        self._track_list_lock = threading.Lock()
        self._return_to_lobby = False

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

        # Input redundancy: ring buffer of last N sent inputs (newest first)
        self._recent_inputs = []  # [(accel, turn, brake, use_pw, seq), ...]

        # Clock offset estimation (server_race_time ↔ client wall-clock)
        self._clock_offsets = []       # list of (recv_time - race_time) samples
        self._clock_offset = 0.0       # current estimated offset
        self._clock_synced = False

        # Multi-room support
        self.multi_room = False      # servidor soporta multi-room
        self.room_id = -1            # sala actual (-1 = ninguna)
        self.room_code = ""          # código de la sala
        self._room_list = []
        self._room_list_lock = threading.Lock()
        self._room_joined = False    # flag: unido a sala
        self._room_slot = -1         # slot en la sala
        self._room_is_admin = False  # admin en la sala
        self._room_reject_reason = 0

        # Adaptive interpolation delay (jitter measurement)
        self._last_snap_recv_time = 0.0          # recv_time del último snapshot
        self._snap_intervals = []                 # últimos N inter-arrival times
        self._adaptive_delay = NET_INTERPOLATION_DELAY  # valor actual adaptativo

    def connect_async(self, player_name):
        """Inicia conexión en un hilo separado (no bloquea game loop)."""
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
                self.player_id, self.max_players, self.is_admin, self.multi_room = unpack_join_accept(resp)
                self.connected = True
                self._connect_ok = True
                self._connect_done = True
                admin_tag = " (Admin)" if self.is_admin else ""
                mr_tag = " [multi-room]" if self.multi_room else ""
                print(f"[CLIENT] Connected as Player {self.player_id + 1}{admin_tag}{mr_tag}")
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
                elif pkt_type == PKT_TRACK_LIST:
                    self._handle_track_list(data)
                elif pkt_type == PKT_RETURN_LOBBY:
                    self._handle_return_lobby()
                elif pkt_type == PKT_DISCONNECT:
                    self._handle_disconnect()
                elif pkt_type == PKT_ROOM_LIST:
                    self._handle_room_list_response(data)
                elif pkt_type == PKT_ROOM_CREATE_OK:
                    self._handle_room_create_ok(data)
                elif pkt_type == PKT_ROOM_ACCEPT:
                    self._handle_room_accept(data)
                elif pkt_type == PKT_ROOM_REJECT:
                    self._handle_room_reject(data)
                elif pkt_type == PKT_JOIN_ACCEPT:
                    # Re-accept (admin reassignment)
                    self.player_id, self.max_players, self.is_admin, _ = unpack_join_accept(data)
                    if self.is_admin:
                        print(f"[CLIENT] You are now admin")
            except Exception as e:
                print(f"[CLIENT] Error handling pkt 0x{pkt_type:02x}: {e}")

    def _handle_snapshot(self, data):
        raw = unpack_state_snapshot(data)
        snapshot = StateSnapshot(raw)
        with self._snapshot_lock:
            self._snapshots.append(snapshot)
            while len(self._snapshots) > NET_MAX_SNAPSHOT_BUFFER:
                self._snapshots.pop(0)

        # Clock offset estimation (median filter for jitter resistance)
        if snapshot.race_time > 0:
            offset = snapshot.recv_time - snapshot.race_time
            self._clock_offsets.append(offset)
            if len(self._clock_offsets) > 20:
                self._clock_offsets.pop(0)
            sorted_offsets = sorted(self._clock_offsets)
            self._clock_offset = sorted_offsets[len(sorted_offsets) // 2]
            self._clock_synced = True

        # Adaptive interpolation delay (jitter measurement)
        now = snapshot.recv_time
        if self._last_snap_recv_time > 0:
            interval = now - self._last_snap_recv_time
            if 0.001 < interval < 0.500:  # ignore outliers (>500ms = reconnect/pause)
                self._snap_intervals.append(interval)
                if len(self._snap_intervals) > 30:
                    self._snap_intervals.pop(0)
                self._update_adaptive_delay()
        self._last_snap_recv_time = now

    def _update_adaptive_delay(self):
        """Recalcula el delay de interpolación basado en jitter de snapshots."""
        n = len(self._snap_intervals)
        if n < 5:
            return  # No hay suficientes muestras
        avg = sum(self._snap_intervals) / n
        variance = sum((x - avg) ** 2 for x in self._snap_intervals) / n
        stddev = variance ** 0.5
        # delay = intervalo promedio + 2 * desviación estándar
        delay = avg + 2.0 * stddev
        self._adaptive_delay = max(NET_INTERP_MIN_DELAY,
                                   min(delay, NET_INTERP_MAX_DELAY))

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

    def _handle_track_list(self, data):
        tracks = unpack_track_list(data)
        with self._track_list_lock:
            self._track_list = tracks
        print(f"[CLIENT] Received track list: {len(tracks)} tracks")

    def _handle_return_lobby(self):
        print(f"[CLIENT] Server requested return to lobby")
        self._return_to_lobby = True
        self.race_started = False
        # Reset track data for next race
        with self._track_lock:
            self._track_chunks.clear()
            self._track_total_chunks = 0
            self._track_json = None

    def _handle_disconnect(self):
        print(f"[CLIENT] Host disconnected")
        self.connected = False
        self._running = False

    # ── API pública ──

    def send_input(self, accel, turn, brake, use_powerup):
        """Envía input del frame al servidor con redundancia (últimos 3 inputs)."""
        if not self.connected or not self.socket:
            return
        self._input_seq = (self._input_seq + 1) % 65536

        # Add to recent inputs buffer (newest first)
        self._recent_inputs.insert(0, (accel, turn, brake, use_powerup, self._input_seq))
        if len(self._recent_inputs) > INPUT_REDUNDANCY:
            self._recent_inputs.pop()

        data = pack_input_redundant(self.player_id, self._recent_inputs)
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

    def clear_snapshots(self):
        """Limpia el buffer de snapshots. Llamar al iniciar countdown para
        evitar que snapshots acumulados causen saltos al entrar en racing."""
        with self._snapshot_lock:
            self._snapshots.clear()
        self._clock_offsets.clear()
        self._clock_synced = False
        self._last_snap_recv_time = 0.0
        self._snap_intervals.clear()
        self._adaptive_delay = NET_INTERPOLATION_DELAY

    def get_interpolation_states(self):
        """Retorna (prev, curr) snapshots para interpolación."""
        with self._snapshot_lock:
            if len(self._snapshots) >= 2:
                return self._snapshots[-2], self._snapshots[-1]
            elif self._snapshots:
                return None, self._snapshots[-1]
        return None, None

    def get_server_time_now(self):
        """Estima el race_time actual del servidor basándose en clock offset."""
        if not self._clock_synced:
            return 0.0
        return time.time() - self._clock_offset

    def get_adaptive_delay(self):
        """Retorna el delay de interpolación adaptativo actual (en segundos)."""
        return self._adaptive_delay

    def get_snapshots_for_time(self, render_time):
        """Busca (prev, next, t) snapshots que encuadran render_time por race_time.

        Returns (prev_snap, next_snap, t) donde t es la fracción de interpolación [0..1].
        Returns (None, latest, 1.0) si render_time está más allá de todos los snapshots.
        Returns (None, None, 0.0) si no hay snapshots disponibles.
        """
        with self._snapshot_lock:
            if not self._snapshots:
                return None, None, 0.0

            # Buscar el par donde a.race_time <= render_time <= b.race_time
            for i in range(len(self._snapshots) - 1):
                a = self._snapshots[i]
                b = self._snapshots[i + 1]
                if a.race_time <= render_time <= b.race_time:
                    dt = b.race_time - a.race_time
                    if dt < 0.001:
                        return a, b, 1.0
                    t = (render_time - a.race_time) / dt
                    return a, b, max(0.0, min(1.0, t))

            # render_time más allá del snapshot más reciente → usar el último
            latest = self._snapshots[-1]
            return None, latest, 1.0

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

    # ── Admin API ──

    def get_track_list(self):
        """Retorna lista de tracks disponibles del servidor."""
        with self._track_list_lock:
            return list(self._track_list)

    def should_return_to_lobby(self):
        """Retorna True si el servidor pidió volver al lobby (consume flag)."""
        if self._return_to_lobby:
            self._return_to_lobby = False
            return True
        return False

    def send_config_change_track(self, filename):
        """Admin: solicita cambio de track al servidor."""
        if not self.connected or not self.socket:
            return
        data = pack_server_config_track(filename)
        try:
            self.socket.sendto(data, self.host_addr)
        except OSError:
            pass

    def send_config_change_bots(self, count):
        """Admin: solicita cambio de bots al servidor."""
        if not self.connected or not self.socket:
            return
        data = pack_server_config_bots(count)
        try:
            self.socket.sendto(data, self.host_addr)
        except OSError:
            pass

    def send_config_start_race(self):
        """Admin: solicita inicio de carrera al servidor."""
        if not self.connected or not self.socket:
            return
        data = pack_server_config_start()
        try:
            self.socket.sendto(data, self.host_addr)
        except OSError:
            pass

    # ── Room management (multi-room) ──

    def _handle_room_list_response(self, data):
        rooms = unpack_room_list(data)
        with self._room_list_lock:
            self._room_list = rooms

    def _handle_room_create_ok(self, data):
        info = unpack_room_create_ok(data)
        self.room_id = info["room_id"]
        self.room_code = info["code"]
        self._room_slot = info["slot"]
        self._room_is_admin = True
        self._room_joined = True
        self.player_id = info["slot"]  # Use slot as player_id in room
        self.is_admin = True
        print(f"[CLIENT] Room created: {self.room_code} (slot={self._room_slot})")

    def _handle_room_accept(self, data):
        info = unpack_room_accept(data)
        self.room_id = info["room_id"]
        self._room_slot = info["slot"]
        self._room_is_admin = info["is_admin"]
        self._room_joined = True
        self.player_id = info["slot"]  # Use slot as player_id in room
        self.is_admin = info["is_admin"]
        print(f"[CLIENT] Joined room {self.room_id} (slot={self._room_slot}, "
              f"admin={self._room_is_admin})")

    def _handle_room_reject(self, data):
        self._room_reject_reason = unpack_room_reject(data)
        print(f"[CLIENT] Room join rejected (reason={self._room_reject_reason})")

    def request_room_list(self):
        """Enviar PKT_ROOM_LIST_REQ al servidor."""
        if not self.connected or not self.socket:
            return
        try:
            self.socket.sendto(pack_room_list_req(), self.host_addr)
        except OSError:
            pass

    def send_create_room(self, name, is_private=False):
        """PKT_ROOM_CREATE: crear sala."""
        if not self.connected or not self.socket:
            return
        try:
            self.socket.sendto(pack_room_create(name, is_private), self.host_addr)
        except OSError:
            pass

    def send_join_room(self, room_id):
        """PKT_ROOM_JOIN by id."""
        if not self.connected or not self.socket:
            return
        try:
            self.socket.sendto(pack_room_join_by_id(room_id), self.host_addr)
        except OSError:
            pass

    def send_join_room_by_code(self, code):
        """PKT_ROOM_JOIN by code."""
        if not self.connected or not self.socket:
            return
        try:
            self.socket.sendto(pack_room_join_by_code(code), self.host_addr)
        except OSError:
            pass

    def send_leave_room(self):
        """PKT_ROOM_LEAVE: salir de sala."""
        if not self.connected or not self.socket:
            return
        try:
            self.socket.sendto(pack_room_leave(), self.host_addr)
        except OSError:
            pass
        self.room_id = -1
        self.room_code = ""
        self._room_slot = -1
        self._room_is_admin = False
        self._room_joined = False

    def get_room_list(self):
        """Retorna lista de salas del servidor."""
        with self._room_list_lock:
            return list(self._room_list)

    def has_joined_room(self):
        """Retorna True si se unió a una sala (consume flag)."""
        if self._room_joined:
            self._room_joined = False
            return True
        return False

    def get_room_reject_reason(self):
        """Retorna y consume el motivo de rechazo (0 = sin rechazo)."""
        r = self._room_reject_reason
        self._room_reject_reason = 0
        return r
