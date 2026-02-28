"""
room.py - State machine para una sala de juego en el servidor dedicado.

Estados: LOBBY -> COUNTDOWN -> RACING -> DONE
"""

import time
import json

import track_manager
from networking.protocol import pack_state_snapshot
from settings import (
    FIXED_DT,
    DEDICATED_AUTO_START_DELAY, DEDICATED_MIN_PLAYERS,
)
from server.world_simulation import WorldSimulation


ROOM_LOBBY = "lobby"
ROOM_COUNTDOWN = "countdown"
ROOM_RACING = "racing"
ROOM_DONE = "done"


class Room:
    """Sala de juego con state machine para el servidor dedicado."""

    def __init__(self, net_server, track_file, bot_count, max_players):
        self.net_server = net_server
        self.track_file = track_file
        self.bot_count = bot_count
        self.max_players = max_players

        self.state = ROOM_LOBBY
        self.world = None

        # Lobby
        self._lobby_broadcast_timer = 0.0
        self._auto_start_timer = 0.0
        self._auto_start_triggered = False

        # Countdown (4 segundos: "3" 1s + "2" 1s + "1" 1s + "GO!" 1s)
        # Debe coincidir con el countdown del cliente para evitar gap
        self._countdown_timer = 0.0
        self._countdown_secs = 4

        # Racing
        self._snapshot_seq = 0
        self._snapshot_tick_counter = 0

        # Track data cargada
        self._track_data = None

    def tick(self, dt):
        """Ejecuta un tick segun el estado actual."""
        if self.state == ROOM_LOBBY:
            self._tick_lobby(dt)
        elif self.state == ROOM_COUNTDOWN:
            self._tick_countdown(dt)
        elif self.state == ROOM_RACING:
            self._tick_racing(dt)
        elif self.state == ROOM_DONE:
            self._tick_done(dt)

    def _tick_lobby(self, dt):
        """Lobby: broadcast estado y auto-start cuando hay suficientes jugadores."""
        # Broadcast lobby state periodicamente
        self._lobby_broadcast_timer += dt
        if self._lobby_broadcast_timer >= 0.25:
            self._lobby_broadcast_timer = 0.0
            self.net_server.bot_count = self.bot_count
            self.net_server.broadcast_lobby_state()

        # Auto-start
        connected = self.net_server.get_connected_count()
        if connected >= DEDICATED_MIN_PLAYERS:
            if not self._auto_start_triggered:
                self._auto_start_triggered = True
                self._auto_start_timer = 0.0
                print(f"[ROOM] {connected} player(s) connected, "
                      f"auto-starting in {DEDICATED_AUTO_START_DELAY}s...")

            self._auto_start_timer += dt
            if self._auto_start_timer >= DEDICATED_AUTO_START_DELAY:
                self._begin_race()
        else:
            # Reset auto-start si se desconectan
            if self._auto_start_triggered:
                self._auto_start_triggered = False
                print("[ROOM] Not enough players, auto-start cancelled")

    def _begin_race(self):
        """Carga track, lo envia a clientes, crea WorldSimulation."""
        print("[ROOM] Loading track and starting race...")

        # Cargar track data
        try:
            self._track_data = track_manager.load_track(self.track_file)
        except (OSError, KeyError) as e:
            print(f"[ROOM] ERROR loading track: {e}")
            return

        self.net_server.racing = True

        # Enviar track data a clientes (bloqueante en servidor dedicado)
        track_json_str = json.dumps(self._track_data)
        if self.net_server.get_connected_count() > 0:
            ok = self.net_server.send_track_data_blocking(
                track_json_str, timeout=10.0)
            if not ok:
                print("[ROOM] WARNING: Track data send timed out for some clients")

        # Obtener lista de jugadores
        player_list = self.net_server.get_player_list()
        print(f"[ROOM] Players: {player_list}, Bots: {self.bot_count}")

        # Crear simulacion
        self.world = WorldSimulation(
            self._track_data, player_list, self.bot_count)

        # Broadcast race start con countdown (enviar valor de display, no timer total)
        display_countdown = self._countdown_secs - 1  # 4-1=3 → "3, 2, 1, GO!"
        self.net_server.broadcast_race_start(display_countdown)
        print(f"[ROOM] Race starting! Countdown: {display_countdown}s + GO!")

        self._countdown_timer = 0.0
        self.state = ROOM_COUNTDOWN

    def _tick_countdown(self, dt):
        """Countdown antes de la carrera."""
        self._countdown_timer += dt
        if self._countdown_timer >= self._countdown_secs:
            print("[ROOM] GO!")
            self.state = ROOM_RACING
            self._snapshot_seq = 0
            self._snapshot_tick_counter = 0

    def _tick_racing(self, dt):
        """Tick principal: 1 input por tick, snapshot a 30Hz.
        El accumulator del dedicated_server corre ticks rápidos para catch-up."""
        # Pop 1 input por jugador (el accumulator corre múltiples ticks si atrasa)
        inputs, _ = self.net_server.pop_one_input_per_player()

        # 1 sim step por tick (siempre exactamente 1)
        self.world.step(FIXED_DT, inputs)

        # Broadcast eventos de powerup
        for evt_data in self.world.flush_events():
            for _ in range(3):
                self.net_server.broadcast(evt_data)

        # Broadcast snapshot a 30Hz (cada 2do tick del accumulator)
        self._snapshot_tick_counter += 1
        if self._snapshot_tick_counter >= 2:
            self._snapshot_tick_counter = 0
            last_seqs = self.net_server.get_last_processed_seqs()
            self._broadcast_snapshot(last_seqs)

        # Verificar fin de carrera
        if self.world.is_race_over():
            winner = self.world.winner
            if winner:
                print(f"[ROOM] Race over! Winner: {winner.name} "
                      f"({winner.finish_time:.2f}s)")
            else:
                print("[ROOM] Race over! (all finished)")
            self.state = ROOM_DONE

    def _broadcast_snapshot(self, last_seqs=None):
        """Empaqueta y envia snapshot de estado a todos los clientes."""
        self._snapshot_seq = (self._snapshot_seq + 1) % 65536
        w = self.world

        # DEBUG: primeros 3 snapshots
        if self._snapshot_seq <= 3:
            for car in w.cars:
                lis = last_seqs.get(car.player_id, 0) if last_seqs else 0
                print(f"[DEBUG-SNAP] seq={self._snapshot_seq} "
                      f"car={car.name}(pid={car.player_id}) "
                      f"x={car.x:.1f} y={car.y:.1f} "
                      f"last_input_seq={lis}")
        data = pack_state_snapshot(
            w.cars, w.missiles, w.smart_missiles,
            w.oil_slicks, w.mines, w.powerup_items,
            w.race_timer.total_time, self._snapshot_seq,
            last_input_seqs=last_seqs,
            server_tick=w.server_tick,
        )
        self.net_server.broadcast(data)

    def _tick_done(self, dt):
        """Carrera terminada. Por ahora no hace nada (futuro: restart)."""
        pass
