"""
game.py - Clase principal del juego.

Controla el game loop, la máquina de estados (menú, countdown, carrera, victoria),
la inicialización de todos los sistemas y entidades, y el renderizado.

Ahora incluye:
- Cámara con seguimiento suave del jugador.
- Mapa grande (mayor que la pantalla).
- Sistema de power-ups con 4 tipos.
- Minimapa.
"""

import os
import sys
import random
import math
import pygame

import json
import subprocess
import tempfile

from settings import (
    SCREEN_WIDTH, SCREEN_HEIGHT, FPS, TITLE,
    WORLD_WIDTH, WORLD_HEIGHT,
    COLOR_BLACK, COLOR_WHITE, COLOR_YELLOW, COLOR_GREEN,
    COLOR_RED, COLOR_GRAY, COLOR_DARK_GRAY, COLOR_ORANGE, COLOR_BLUE,
    STATE_MENU, STATE_COUNTDOWN, STATE_RACING, STATE_VICTORY,
    STATE_EDITOR, STATE_TRACK_SELECT, STATE_TRAINING,
    STATE_JOIN_LOBBY, STATE_CONNECTING, STATE_ROOM_SELECT,
    STATE_ONLINE_RACING, STATE_ONLINE_COUNTDOWN,
    ROOM_LIST_REFRESH_INTERVAL,
    COLOR_PROGRESS_BAR, COLOR_PROGRESS_BG,
    PLAYER_COLORS, MAX_PLAYERS, TOTAL_LAPS, DEBUG_CHECKPOINTS,
    HUD_FONT_SIZE, HUD_TITLE_FONT_SIZE,
    HUD_SUBTITLE_FONT_SIZE, HUD_MARGIN, MINIMAP_MARGIN, MINIMAP_CAR_DOT,
    BOT_ACCELERATION, BOT_MAX_SPEED, BOT_TURN_SPEED,
    POWERUP_BOOST, POWERUP_SHIELD, POWERUP_MISSILE, POWERUP_OIL,
    POWERUP_MINE, POWERUP_EMP, POWERUP_MAGNET, POWERUP_SLOWMO,
    POWERUP_BOUNCE, POWERUP_AUTOPILOT, POWERUP_TELEPORT,
    POWERUP_SMART_MISSILE,
    POWERUP_COLORS, POWERUP_MYSTERY_COLOR,
    BOOST_DURATION, SHIELD_DURATION,
    MISSILE_SLOW_DURATION, OIL_EFFECT_DURATION,
    MINE_SPIN_DURATION, EMP_RANGE, EMP_SLOW_DURATION,
    MAGNET_DURATION, SLOWMO_DURATION, BOUNCE_DURATION,
    AUTOPILOT_DURATION, TELEPORT_DISTANCE,
    SMART_MISSILE_LIFETIME,
    NET_DEFAULT_PORT, NET_TICK_RATE, NET_INTERPOLATION_DELAY, DEDICATED_SERVER_IP,
    NET_TELEPORT_THRESHOLD, NET_EXTRAPOLATION_MAX,
    FIXED_DT, VISUAL_SMOOTH_RATE,
    SLOWMO_FACTOR,
    CAR_VS_CAR_SPEED_PENALTY,
)
from entities.car import Car
from entities.track import Track
from entities.powerup import PowerUpItem, Missile, OilSlick, Mine, SmartMissile
from entities.particles import DustParticleSystem, SkidMarkSystem
from systems.physics import PhysicsSystem
from systems.collision import CollisionSystem
from systems.input_handler import InputHandler
from systems.ai import AISystem, RLSystem
from systems.camera import Camera
from utils.timer import RaceTimer
from utils.helpers import draw_text_centered
from editor import TileEditor
from tile_track import TileTrack
from race_progress import RaceProgressTracker
import track_manager


class InputRecord:
    """Record de un input enviado al servidor, para replay en reconciliación."""
    __slots__ = ('seq', 'accel', 'turn', 'brake', 'use_powerup')

    def __init__(self, seq, accel, turn, brake, use_powerup=False):
        self.seq = seq
        self.accel = accel
        self.turn = turn
        self.brake = brake
        self.use_powerup = use_powerup


class Game:
    """Clase principal que orquesta todo el juego."""

    def __init__(self):
        # Inicializar subsistemas por separado para permitir múltiples instancias.
        # pygame.init() puede bloquear si otra instancia tiene el driver de audio.
        pygame.display.init()
        pygame.font.init()
        try:
            pygame.mixer.init()
        except pygame.error:
            pass  # Audio no disponible (otra instancia lo usa)
        pygame.display.set_caption(TITLE)

        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()

        # Fuentes
        self.font = pygame.font.SysFont("consolas", HUD_FONT_SIZE)
        self.font_title = pygame.font.SysFont("consolas", HUD_TITLE_FONT_SIZE, bold=True)
        self.font_subtitle = pygame.font.SysFont("consolas", HUD_SUBTITLE_FONT_SIZE)
        self.font_small = pygame.font.SysFont("consolas", 16)

        # Estado
        self.state = STATE_MENU
        self.running = True
        self.total_time = 0.0      # tiempo total del juego (para animaciones)

        # Countdown
        self.countdown_timer = 0.0
        self.countdown_value = 3

        # Entidades y sistemas
        self.track = None
        self.cars = []
        self.player_car = None
        self.physics = PhysicsSystem()
        self.collision_system = None
        self.input_handler = InputHandler()
        self.ai_system = None
        self.rl_system = None
        self.camera = Camera()
        self.race_timer = RaceTimer()

        # Power-ups
        self.powerup_items = []    # pickups en la pista
        self.missiles = []         # misiles activos
        self.oil_slicks = []       # manchas de aceite activas
        self.mines = []            # minas activas
        self.smart_missiles = []   # misiles inteligentes activos
        self._use_cooldown = 0.0   # cooldown para evitar doble uso
        self.dust_particles = None # sistema de partículas de polvo

        # Resultado
        self.winner = None
        self.final_times = {}
        self.race_progress = None

        # Editor y selección de pista
        self.editor = None
        self.track_list = []
        self.track_selected = 0
        self.return_to_editor = False  # para volver al editor tras test race

        # Training state
        self._train_process = None
        self._train_progress_file = None
        self._train_progress = {}
        self._train_track_name = ""
        self._train_track_file = ""
        self._train_timesteps = 200000
        self._train_status = "idle"  # idle | training | done | error
        self._train_error_log = ""  # ruta al archivo de log de error

        # Multiplayer online (client-only, server is separate process)
        self.net_client = None       # GameClient
        self.is_online = False
        self.my_player_id = 0
        self._lobby_ip_input = ""
        self._lobby_name_input = "Player"
        self._online_countdown_timer = 0.0
        self._online_countdown_value = 3
        self._net_error_msg = ""
        self._ip_cursor_blink = 0.0
        self._join_mode = "choose"  # "choose" | "connecting"

        # Local server (started in-process when user selects "Local")
        self._local_server = None        # GameServer instance
        self._local_room_manager = None  # RoomManager instance
        self._local_server_thread = None # tick loop thread

        # Admin lobby (dedicated server)
        self._is_lobby_admin = False
        self._admin_track_list = []
        self._admin_track_selected = 0
        self._admin_bot_count = 1

        # Room select (multi-room dedicated server)
        self._room_list = []
        self._room_selected = 0
        self._room_create_mode = False
        self._room_code_mode = False
        self._room_name_input = ""
        self._room_code_input = ""
        self._room_private = False
        self._room_refresh_timer = 0.0
        self._room_error_msg = ""
        self._room_cursor_blink = 0.0

        # Fixed timestep accumulator
        self._physics_accumulator = 0.0
        self._client_slowmo_on_me = False
        self._last_reconcile_seq = -1

        # Input replay buffer (client-side prediction + reconciliation)
        self._input_buffer = [None] * 128  # circular buffer of InputRecord
        self._input_buffer_head = 0
        self._input_buffer_count = 0

        # Net debug overlay (toggle con F3)
        self._show_net_stats = False
        self._net_stats = {
            'ping': 0.0,
            'unacked': 0,
            'reconcile_error': 0.0,
            'snap_rate': 0.0,
            'server_tick': 0,
            'input_seq': 0,
            'last_server_seq': 0,
        }
        self._snap_count = 0
        self._snap_rate_timer = 0.0
        self._snap_rate_value = 0.0

        # Exportar circuito por defecto si no existe
        track_manager.export_default_track()

    # ──────────────────────────────────────────────
    # GAME LOOP
    # ──────────────────────────────────────────────

    def run(self):
        """Loop principal del juego."""
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            dt = min(dt, 0.05)
            self.total_time += dt

            self._handle_events()
            self._update(dt)
            self._render()

        # Limpiar networking al salir
        self._stop_online()
        pygame.quit()
        sys.exit()

    # ──────────────────────────────────────────────
    # EVENTOS
    # ──────────────────────────────────────────────

    def _handle_events(self):
        """Procesa eventos de Pygame."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                continue

            # Editor captura sus propios eventos
            if self.state == STATE_EDITOR and self.editor:
                self.editor.handle_event(event)
                if self.editor.result == "menu":
                    self.state = STATE_MENU
                    self.editor = None
                elif self.editor.result == "test":
                    tile_data = self.editor._build_tile_data()
                    self.return_to_editor = True
                    self._start_race(tile_data=tile_data)
                    self.editor.result = None
                continue

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self.state in (STATE_RACING, STATE_COUNTDOWN):
                        if self.return_to_editor:
                            self._open_editor_with_points()
                        else:
                            self.state = STATE_MENU
                    elif self.state in (STATE_ONLINE_RACING, STATE_ONLINE_COUNTDOWN):
                        self._stop_online()
                        self.state = STATE_MENU
                    elif self.state == STATE_TRACK_SELECT:
                        self.state = STATE_MENU
                    elif self.state == STATE_TRAINING:
                        self._cancel_training()
                        self.state = STATE_TRACK_SELECT
                    elif self.state == STATE_ROOM_SELECT:
                        if self._room_create_mode:
                            self._room_create_mode = False
                        elif self._room_code_mode:
                            self._room_code_mode = False
                        else:
                            self._stop_online()
                            self.state = STATE_MENU
                    elif self.state == STATE_JOIN_LOBBY:
                        if self.net_client and self.net_client.multi_room:
                            self.net_client.send_leave_room()
                            self.state = STATE_ROOM_SELECT
                            self._room_error_msg = ""
                            self._room_refresh_timer = 0.0
                            self.net_client.request_room_list()
                        else:
                            self._stop_online()
                            self.state = STATE_MENU
                    elif self.state == STATE_CONNECTING:
                        if self._join_mode == "connecting":
                            self._stop_online()
                            self._join_mode = "choose"
                            self.state = STATE_CONNECTING
                        else:
                            self.state = STATE_MENU
                    elif self.state == STATE_VICTORY:
                        if self.is_online:
                            self._stop_online()
                        self.state = STATE_MENU
                    else:
                        self.running = False

                elif event.key == pygame.K_e:
                    if self.state == STATE_MENU:
                        self._open_editor()
                    elif self.state == STATE_TRACK_SELECT:
                        self._edit_selected_track()

                elif event.key == pygame.K_j:
                    if self.state == STATE_MENU:
                        self._start_join_screen()

                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER,
                                   pygame.K_SPACE):
                    if self.state == STATE_MENU:
                        self._open_track_select()
                    elif self.state == STATE_TRACK_SELECT:
                        self._start_selected_track()
                    elif self.state == STATE_VICTORY:
                        if self.is_online:
                            pass  # Online: wait for server return-to-lobby
                        elif self.return_to_editor:
                            self._open_editor_with_points()
                        else:
                            self.state = STATE_MENU
                    elif self.state == STATE_TRAINING:
                        if self._train_status == "idle":
                            self._launch_training()
                        elif self._train_status in ("done", "error"):
                            self.state = STATE_TRACK_SELECT
                    elif self.state == STATE_CONNECTING:
                        if self._join_mode == "choose":
                            if self._join_choice == 0:
                                # Online
                                self._lobby_ip_input = DEDICATED_SERVER_IP
                                self._join_mode = "connecting"
                                self._net_error_msg = "Connecting..."
                                self._attempt_connect()
                            else:
                                # Local — start a local server and auto-connect
                                self._start_local_server()
                    elif self.state == STATE_JOIN_LOBBY:
                        if self._is_lobby_admin:
                            self.net_client.send_config_start_race()
                    elif self.state == STATE_ROOM_SELECT:
                        if self._room_create_mode:
                            if self._room_name_input.strip():
                                self.net_client.send_create_room(
                                    self._room_name_input.strip(),
                                    self._room_private)
                                self._room_create_mode = False
                        elif self._room_code_mode:
                            if len(self._room_code_input) == 4:
                                self.net_client.send_join_room_by_code(
                                    self._room_code_input.upper())
                                self._room_code_mode = False
                        else:
                            # Join selected room
                            if self._room_list and self._room_selected < len(self._room_list):
                                room = self._room_list[self._room_selected]
                                if room["state"] == 0:  # lobby
                                    self.net_client.send_join_room(room["room_id"])

                elif self.state == STATE_ROOM_SELECT:
                    if self._room_create_mode:
                        if event.key == pygame.K_BACKSPACE:
                            self._room_name_input = self._room_name_input[:-1]
                        elif event.key == pygame.K_TAB:
                            self._room_private = not self._room_private
                    elif self._room_code_mode:
                        if event.key == pygame.K_BACKSPACE:
                            self._room_code_input = self._room_code_input[:-1]
                    else:
                        if event.key == pygame.K_UP:
                            self._room_selected = max(0, self._room_selected - 1)
                        elif event.key == pygame.K_DOWN:
                            if self._room_list:
                                self._room_selected = min(
                                    len(self._room_list) - 1,
                                    self._room_selected + 1)
                        elif event.key == pygame.K_c:
                            self._room_create_mode = True
                            self._room_name_input = ""
                            self._room_private = False
                            self._room_cursor_blink = 0.0
                        elif event.key == pygame.K_p:
                            self._room_code_mode = True
                            self._room_code_input = ""
                            self._room_cursor_blink = 0.0

                elif self.state == STATE_CONNECTING:
                    if self._join_mode == "choose":
                        if event.key in (pygame.K_UP, pygame.K_DOWN):
                            self._join_choice = 1 - self._join_choice

                elif self.state == STATE_JOIN_LOBBY:
                    if self._is_lobby_admin and self._admin_track_list:
                        if event.key == pygame.K_UP:
                            self._admin_track_selected = max(
                                0, self._admin_track_selected - 1)
                            t = self._admin_track_list[self._admin_track_selected]
                            self.net_client.send_config_change_track(t["filename"])
                        elif event.key == pygame.K_DOWN:
                            self._admin_track_selected = min(
                                len(self._admin_track_list) - 1,
                                self._admin_track_selected + 1)
                            t = self._admin_track_list[self._admin_track_selected]
                            self.net_client.send_config_change_track(t["filename"])
                        elif event.key == pygame.K_LEFT:
                            self._admin_bot_count = max(0, self._admin_bot_count - 1)
                            self.net_client.send_config_change_bots(self._admin_bot_count)
                        elif event.key == pygame.K_RIGHT:
                            self._admin_bot_count = min(
                                MAX_PLAYERS - 1, self._admin_bot_count + 1)
                            self.net_client.send_config_change_bots(self._admin_bot_count)

                elif self.state == STATE_TRACK_SELECT:
                    if event.key == pygame.K_UP:
                        self.track_selected = max(0, self.track_selected - 1)
                    elif event.key == pygame.K_DOWN:
                        self.track_selected = min(
                            len(self.track_list) - 1, self.track_selected + 1)
                    elif event.key == pygame.K_t:
                        if self.track_list:
                            entry = self.track_list[self.track_selected]
                            if entry.get("type") == "tiles":
                                self._start_training_screen()

                elif self.state == STATE_TRAINING:
                    if event.key == pygame.K_UP and self._train_status == "idle":
                        self._train_timesteps = min(self._train_timesteps + 50000, 1000000)
                    elif event.key == pygame.K_DOWN and self._train_status == "idle":
                        self._train_timesteps = max(self._train_timesteps - 50000, 50000)

                # F3: Toggle net stats overlay (cualquier estado online)
                if event.key == pygame.K_F3:
                    self._show_net_stats = not self._show_net_stats

            # Text input for room select (create name / join code)
            if event.type == pygame.TEXTINPUT and self.state == STATE_ROOM_SELECT:
                if self._room_create_mode:
                    if len(self._room_name_input) < 20:
                        self._room_name_input += event.text
                elif self._room_code_mode:
                    char = event.text.upper()
                    if len(self._room_code_input) < 4 and char.isalnum():
                        self._room_code_input += char

            # Click izquierdo del mouse para activar power-up
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.state in (STATE_RACING, STATE_ONLINE_RACING):
                    if (self.player_car and self.player_car.held_powerup is not None
                            and self._use_cooldown <= 0):
                        if self.is_online:
                            # Online: señalar al servidor, no activar localmente
                            self.player_car.input_use_powerup = True
                        else:
                            self._activate_powerup(self.player_car)
                        self._use_cooldown = 0.3

    # ──────────────────────────────────────────────
    # INICIALIZACIÓN DE CARRERA
    # ──────────────────────────────────────────────

    def _start_race(self, control_points=None, tile_data=None):
        """Inicializa una nueva carrera."""
        # Circuito
        if tile_data:
            self.track = TileTrack(tile_data)
        else:
            self.track = Track(control_points=control_points)

        # Autos
        self.cars = []
        sp = self.track.start_positions[0]
        self.player_car = Car(sp[0], sp[1], sp[2], PLAYER_COLORS[0], 0)
        self.cars.append(self.player_car)

        sp = self.track.start_positions[1]
        bot_car = Car(sp[0], sp[1], sp[2], PLAYER_COLORS[1], 1)
        bot_car.name = "Bot"
        bot_car.acceleration = BOT_ACCELERATION
        bot_car.max_speed = BOT_MAX_SPEED
        bot_car.turn_speed = BOT_TURN_SPEED
        self.cars.append(bot_car)

        # Sistemas
        self.collision_system = CollisionSystem(self.track)

        # Asegurar que ningún auto spawneó dentro de un muro
        for car in self.cars:
            self.collision_system.ensure_valid_spawn(car)

        # Intentar cargar modelo RL para esta pista
        self.rl_system = None
        if hasattr(self, 'track_list') and self.track_list and self.track_selected < len(self.track_list):
            from utils.base_path import get_writable_dir
            track_name = os.path.splitext(self.track_list[self.track_selected]["filename"])[0]
            model_path = os.path.join(get_writable_dir(), "models", f"{track_name}_model.zip")
            if os.path.exists(model_path):
                rl = RLSystem(self.track, model_path)
                if rl.is_loaded:
                    self.rl_system = rl

        self.ai_system = AISystem(self.track)
        self.ai_system.register_bot(bot_car)

        # Race progress tracker
        fl = self.track.finish_line
        fl_center = ((fl[0][0] + fl[1][0]) / 2, (fl[0][1] + fl[1][1]) / 2)
        self.race_progress = RaceProgressTracker(
            self.track.checkpoints, fl_center
        )
        for car in self.cars:
            self.race_progress.register_car(car.player_id)

        # Cámara: snap instantáneo al jugador (con ángulo inicial)
        self.camera.snap_to(self.player_car.x, self.player_car.y,
                            self.player_car.angle)

        # Power-ups: crear pickups en los puntos de spawn
        self.powerup_items = [
            PowerUpItem(p[0], p[1]) for p in self.track.powerup_spawn_points
        ]
        self.missiles = []
        self.oil_slicks = []
        self.mines = []
        self.smart_missiles = []
        self._use_cooldown = 0.0

        # Partículas de polvo y marcas de derrape
        self.dust_particles = DustParticleSystem()
        self.skid_marks = SkidMarkSystem()

        # Timer
        self.race_timer.reset()
        self.winner = None
        self.final_times = {}

        # Countdown
        self.state = STATE_COUNTDOWN
        self.countdown_timer = 0.0
        self.countdown_value = 3

    # ──────────────────────────────────────────────
    # UPDATE
    # ──────────────────────────────────────────────

    def _update(self, dt: float):
        """Actualiza la lógica según el estado actual."""
        if self.state == STATE_COUNTDOWN:
            self._update_countdown(dt)
        elif self.state == STATE_RACING:
            self._update_racing(dt)
        elif self.state == STATE_EDITOR and self.editor:
            self.editor.update(dt)
        elif self.state == STATE_TRAINING:
            self._update_training(dt)
        elif self.state == STATE_JOIN_LOBBY:
            self._update_join_lobby(dt)
        elif self.state == STATE_ONLINE_COUNTDOWN:
            self._update_online_countdown(dt)
        elif self.state == STATE_ONLINE_RACING:
            self._update_online_racing_client(dt)
        elif self.state == STATE_CONNECTING:
            self._ip_cursor_blink += dt
            self._update_connecting(dt)
        elif self.state == STATE_ROOM_SELECT:
            self._room_cursor_blink += dt
            self._update_room_select(dt)
        elif self.state == STATE_VICTORY:
            self._update_victory(dt)

    def _update_countdown(self, dt: float):
        """Actualiza la cuenta regresiva."""
        self.countdown_timer += dt
        # Actualizar cámara durante el countdown
        if self.player_car:
            self.camera.update(self.player_car.x, self.player_car.y,
                               self.player_car.angle, 0, dt)

        if self.countdown_timer >= 1.0:
            self.countdown_timer -= 1.0
            self.countdown_value -= 1
            if self.countdown_value < 0:
                self.state = STATE_RACING
                self.race_timer.start()

    def _update_racing(self, dt: float):
        """
        Actualiza todos los sistemas durante la carrera.
        Orden: input → IA → física → colisiones → power-ups → cámara → timer
        """
        keys = pygame.key.get_pressed()
        self._use_cooldown = max(0, self._use_cooldown - dt)

        # Detectar si algún auto tiene slowmo activo
        slowmo_owner = None
        for car in self.cars:
            if car.has_slowmo:
                slowmo_owner = car
                break

        # ── Actualizar autos ──
        for car in self.cars:
            if car.finished:
                continue

            # Input
            if car.player_id == 0:
                self.input_handler.update(car, keys)
            else:
                if self.rl_system is not None:
                    self.rl_system.update(car, dt, self.cars)
                else:
                    self.ai_system.update(car, dt, self.cars)

            # Autopilot sobreescribe el input del jugador
            if car.has_autopilot:
                self._autopilot_steer(car)

            # Efectos de power-ups activos
            car.update_effects(dt)

            # SlowMo: rivales se mueven más lento
            car_dt = dt
            if (slowmo_owner is not None and
                    car.player_id != slowmo_owner.player_id):
                from settings import SLOWMO_FACTOR
                car_dt = dt * SLOWMO_FACTOR

            # Física: velocidad (sin movimiento)
            self.physics.update(car, car_dt, self.track)

            # Movimiento sub-stepped con colisión integrada (anti-tunneling)
            hit, normal, remaining = self.collision_system.move_with_substeps(car, car_dt)
            if hit:
                if car.is_shielded:
                    car.break_shield()
                    car.speed *= 0.7
                elif car.has_bounce:
                    self.physics.apply_collision_response(car, normal)
                    car.speed *= 1.3
                else:
                    self.physics.apply_collision_response(car, normal)
                # Slide con tiempo restante (también sub-stepped)
                if remaining > 0:
                    self.collision_system.move_with_substeps(car, remaining)

            car.update_sprite()

            # Checkpoints y vueltas
            old_laps = car.laps
            self.collision_system.update_checkpoints(car)
            if car.laps > old_laps:
                if car == self.player_car:
                    self.race_timer.complete_lap()
                if car.laps >= TOTAL_LAPS:
                    car.finished = True
                    car.finish_time = self.race_timer.total_time
                    self.final_times[car.name] = car.finish_time
                    if self.winner is None:
                        self.winner = car

            # Actualizar progreso de carrera
            self.race_progress.update(car)

            # Usar power-up
            if car.input_use_powerup and car.held_powerup is not None:
                if car.player_id != 0 or self._use_cooldown <= 0:
                    self._activate_powerup(car)
                    if car.player_id == 0:
                        self._use_cooldown = 0.3

        # ── Colisiones entre autos ──
        for i in range(len(self.cars)):
            for j in range(i + 1, len(self.cars)):
                if self.collision_system.check_car_vs_car(
                        self.cars[i], self.cars[j]):
                    # Si uno tiene escudo, el otro rebota más
                    a, b = self.cars[i], self.cars[j]
                    if a.is_shielded:
                        a.break_shield()
                    elif b.is_shielded:
                        b.break_shield()
                    self.collision_system.resolve_car_vs_car(a, b)
                    a.update_sprite()
                    b.update_sprite()

        # ── Recoger power-ups (solo si no tiene uno ya) ──
        for car in self.cars:
            if car.held_powerup is not None:
                continue
            for item in self.powerup_items:
                if self.collision_system.check_car_vs_powerup(car, item):
                    car.held_powerup = item.collect()
                    break

        # ── Actualizar power-up items (respawn) ──
        for item in self.powerup_items:
            item.update(dt)

        # ── Actualizar misiles ──
        for missile in self.missiles:
            missile.update(dt)
            # Colisión misil vs muro
            if self.collision_system.check_missile_vs_wall(missile):
                missile.alive = False
            # Colisión misil vs autos
            for car in self.cars:
                if self.collision_system.check_car_vs_missile(car, missile):
                    missile.alive = False
                    if car.is_shielded:
                        car.break_shield()
                    else:
                        car.apply_effect("missile_slow", MISSILE_SLOW_DURATION)
                        car.speed *= 0.3
        self.missiles = [m for m in self.missiles if m.alive]

        # ── Actualizar manchas de aceite ──
        for oil in self.oil_slicks:
            oil.update(dt)
            for car in self.cars:
                if car.player_id == oil.owner_id:
                    continue
                if self.collision_system.check_car_vs_oil(car, oil):
                    if "oil_slow" not in car.active_effects:
                        car.apply_effect("oil_slow", OIL_EFFECT_DURATION)
        self.oil_slicks = [o for o in self.oil_slicks if o.alive]

        # ── Actualizar minas ──
        for mine in self.mines:
            mine.update(dt)
            for car in self.cars:
                if self.collision_system.check_car_vs_mine(car, mine):
                    mine.alive = False
                    if car.is_shielded:
                        car.break_shield()
                    else:
                        car.apply_effect("mine_spin", MINE_SPIN_DURATION)
                        car.speed *= 0.3
        self.mines = [m for m in self.mines if m.alive]

        # ── Actualizar misiles inteligentes ──
        for sm in self.smart_missiles:
            sm.update(dt)
            if self.collision_system.check_missile_vs_wall(sm):
                sm.alive = False
            for car in self.cars:
                if self.collision_system.check_car_vs_smart_missile(car, sm):
                    sm.alive = False
                    if car.is_shielded:
                        car.break_shield()
                    else:
                        car.apply_effect("missile_slow", MISSILE_SLOW_DURATION)
                        car.speed *= 0.3
        self.smart_missiles = [m for m in self.smart_missiles if m.alive]

        # ── Partículas de polvo, sparks y skid marks ──
        if self.dust_particles:
            for car in self.cars:
                if not car.finished:
                    self.dust_particles.emit_from_car(car)
                    self.dust_particles.emit_drift_smoke(car)
                    self.dust_particles.emit_drift_sparks(car)
                    self.skid_marks.record_from_car(car)
            self.dust_particles.update(dt)
            self.skid_marks.update(dt)

        # ── Cámara ──
        self.camera.update(self.player_car.x, self.player_car.y,
                           self.player_car.angle, self.player_car.speed, dt)

        # ── Timer ──
        self.race_timer.update(dt)

        # ── Victoria ──
        all_finished = all(car.finished for car in self.cars)
        if all_finished or (self.winner and
                            self.race_timer.total_time > self.winner.finish_time + 15):
            self.state = STATE_VICTORY

    # ──────────────────────────────────────────────
    # POWER-UP ACTIVATION
    # ──────────────────────────────────────────────

    def _activate_powerup(self, car: Car):
        """Activa el power-up que lleva el auto."""
        ptype = car.held_powerup
        car.held_powerup = None

        if ptype == POWERUP_BOOST:
            car.apply_effect("boost", BOOST_DURATION)

        elif ptype == POWERUP_SHIELD:
            car.apply_effect("shield", SHIELD_DURATION)

        elif ptype == POWERUP_MISSILE:
            fx, fy = car.get_forward_vector()
            mx = car.x + fx * 30
            my = car.y + fy * 30
            self.missiles.append(Missile(mx, my, car.angle, car.player_id))

        elif ptype == POWERUP_OIL:
            fx, fy = car.get_forward_vector()
            ox = car.x - fx * 30
            oy = car.y - fy * 30
            self.oil_slicks.append(OilSlick(ox, oy, car.player_id))

        elif ptype == POWERUP_MINE:
            fx, fy = car.get_forward_vector()
            mx = car.x - fx * 35
            my = car.y - fy * 35
            self.mines.append(Mine(mx, my, car.player_id))

        elif ptype == POWERUP_EMP:
            # Efecto instantáneo: ralentizar rivales cercanos + quitar boost
            for other in self.cars:
                if other.player_id == car.player_id:
                    continue
                dist = math.hypot(other.x - car.x, other.y - car.y)
                if dist < EMP_RANGE:
                    other.apply_effect("emp_slow", EMP_SLOW_DURATION)
                    # Desactivar boost si lo tienen
                    if "boost" in other.active_effects:
                        del other.active_effects["boost"]

        elif ptype == POWERUP_MAGNET:
            car.apply_effect("magnet", MAGNET_DURATION)

        elif ptype == POWERUP_SLOWMO:
            car.apply_effect("slowmo", SLOWMO_DURATION)

        elif ptype == POWERUP_BOUNCE:
            car.apply_effect("bounce", BOUNCE_DURATION)

        elif ptype == POWERUP_AUTOPILOT:
            car.apply_effect("autopilot", AUTOPILOT_DURATION)

        elif ptype == POWERUP_TELEPORT:
            # Mover auto hacia adelante si el destino está en pista
            fx, fy = car.get_forward_vector()
            new_x = car.x + fx * TELEPORT_DISTANCE
            new_y = car.y + fy * TELEPORT_DISTANCE
            if self.track.is_on_track(new_x, new_y):
                car.x = new_x
                car.y = new_y
                car.update_sprite()

        elif ptype == POWERUP_SMART_MISSILE:
            # Buscar el auto rival más avanzado como objetivo
            target = self._find_leader_rival(car)
            if target:
                fx, fy = car.get_forward_vector()
                mx = car.x + fx * 30
                my = car.y + fy * 30
                self.smart_missiles.append(
                    SmartMissile(mx, my, car.angle, car.player_id, target))

    def _find_leader_rival(self, car: Car):
        """Encuentra el auto rival más avanzado en la carrera."""
        best = None
        best_score = -1
        for other in self.cars:
            if other.player_id == car.player_id or other.finished:
                continue
            # Score: laps * 1000 + checkpoints
            score = other.laps * 1000 + other.next_checkpoint_index
            if score > best_score:
                best_score = score
                best = other
        return best

    def _autopilot_steer(self, car: Car):
        """Piloto automático: dirige el auto hacia los waypoints."""
        wps = self.track.waypoints
        if not wps:
            return
        # Encontrar waypoint más cercano
        min_dist = float('inf')
        best_idx = 0
        for i, (wx, wy) in enumerate(wps):
            d = math.hypot(car.x - wx, car.y - wy)
            if d < min_dist:
                min_dist = d
                best_idx = i
        # Apuntar algunos waypoints adelante
        target_idx = (best_idx + 3) % len(wps)
        tx, ty = wps[target_idx]
        dx = tx - car.x
        dy = ty - car.y
        target_angle = math.degrees(math.atan2(dx, -dy)) % 360
        current = car.angle % 360
        diff = (target_angle - current + 180) % 360 - 180
        car.input_accelerate = 1.0
        if diff > 5:
            car.input_turn = 1.0
        elif diff < -5:
            car.input_turn = -1.0

    # ──────────────────────────────────────────────
    # RENDER
    # ──────────────────────────────────────────────

    def _render(self):
        """Renderiza el frame actual."""
        self.screen.fill(COLOR_BLACK)

        if self.state == STATE_MENU:
            self._render_menu()
        elif self.state == STATE_COUNTDOWN:
            self._render_race()
            self._render_hud()
            self._render_countdown()
        elif self.state == STATE_RACING:
            self._render_race()
            self._render_hud()
        elif self.state == STATE_VICTORY:
            self._render_race()
            self._render_victory()
        elif self.state == STATE_EDITOR and self.editor:
            self.editor.render()
        elif self.state == STATE_TRACK_SELECT:
            self._render_track_select()
        elif self.state == STATE_TRAINING:
            self._render_training()
        elif self.state == STATE_CONNECTING:
            self._render_connecting()
        elif self.state == STATE_ROOM_SELECT:
            self._render_room_select()
        elif self.state == STATE_JOIN_LOBBY:
            self._render_join_lobby()
        elif self.state == STATE_ONLINE_COUNTDOWN:
            self._render_race()
            self._render_hud()
            self._render_countdown()
        elif self.state == STATE_ONLINE_RACING:
            self._render_race()
            self._render_hud()
            self._render_net_stats()

        pygame.display.flip()

    def _render_menu(self):
        """Renderiza la pantalla de inicio."""
        for y in range(SCREEN_HEIGHT):
            ratio = y / SCREEN_HEIGHT
            r = int(10 + 20 * ratio)
            g = int(10 + 15 * ratio)
            b = int(30 + 40 * ratio)
            pygame.draw.line(self.screen, (r, g, b), (0, y), (SCREEN_WIDTH, y))

        draw_text_centered(self.screen, "ARCADE RACING 2D",
                           self.font_title, COLOR_YELLOW, 140)
        draw_text_centered(self.screen, f"Complete {TOTAL_LAPS} laps to win!",
                           self.font_subtitle, COLOR_WHITE, 230)

        instructions = [
            "W / S   -  Accelerate / Reverse",
            "A / D   -  Turn Left / Right",
            "SPACE   -  Handbrake",
            "L-CLICK -  Use Power-Up",
            "E       -  Track Editor",
            "J       -  Join Online Game",
            "ESC     -  Back to Menu",
        ]
        for i, text in enumerate(instructions):
            draw_text_centered(self.screen, text, self.font, COLOR_GRAY,
                               310 + i * 32)

        # Leyenda de power-ups
        y_pw = 490
        draw_text_centered(self.screen, "Power-Ups:", self.font,
                           COLOR_WHITE, y_pw)
        powerup_info = [
            (POWERUP_BOOST,          "Boost    - Speed increase"),
            (POWERUP_SHIELD,         "Shield   - Absorbs one hit (5s)"),
            (POWERUP_MISSILE,        "Missile  - Slows enemy"),
            (POWERUP_OIL,            "Oil      - Slippery hazard"),
            (POWERUP_MINE,           "Mine     - Spin + slow on contact"),
            (POWERUP_EMP,            "EMP      - Slows nearby rivals"),
            (POWERUP_MAGNET,         "Magnet   - Wider checkpoints"),
            (POWERUP_SLOWMO,         "SlowMo   - Rivals move slower"),
            (POWERUP_BOUNCE,         "Bounce   - Better wall bounce"),
            (POWERUP_AUTOPILOT,      "Autopilot - Auto-steer 1s"),
            (POWERUP_TELEPORT,       "Teleport  - Jump 100px forward"),
            (POWERUP_SMART_MISSILE,  "SmartMsl - Homing missile"),
        ]
        for i, (ptype, desc) in enumerate(powerup_info):
            color = POWERUP_COLORS[ptype]
            py = y_pw + 30 + i * 20
            cx = SCREEN_WIDTH // 2 - 160
            pygame.draw.circle(self.screen, color, (cx, py + 8), 6)
            rendered = self.font_small.render(desc, True, COLOR_GRAY)
            self.screen.blit(rendered, (cx + 16, py))

        # Parpadeo
        alpha = abs(pygame.time.get_ticks() % 2000 - 1000) / 1000.0
        blink_color = (int(255 * alpha), int(215 * alpha), int(50))
        draw_text_centered(self.screen, "Press ENTER to Start",
                           self.font_subtitle, blink_color, 640)

    def _render_race(self):
        """Renderiza la pista, power-ups y autos con cámara rotativa."""
        cam = self.camera

        # Pista (porción visible, rotada según la cámara)
        self.track.draw(self.screen, cam)

        # Marcas de derrape (sobre la pista, bajo todo lo demás)
        if self.skid_marks:
            self.skid_marks.draw(self.screen, cam)

        # Manchas de aceite (se dibujan sobre la pista, bajo los autos)
        for oil in self.oil_slicks:
            if cam.is_visible(oil.x, oil.y, 50):
                oil.draw(self.screen, cam)

        # Minas (sobre la pista, bajo los autos)
        for mine in self.mines:
            if cam.is_visible(mine.x, mine.y, 40):
                mine.draw(self.screen, cam)

        # Power-up pickups
        for item in self.powerup_items:
            if item.active and cam.is_visible(item.x, item.y, 30):
                item.draw(self.screen, cam, self.total_time)

        # Partículas de polvo (debajo de los autos)
        if self.dust_particles:
            self.dust_particles.draw(self.screen, cam)

        # Autos
        for car in self.cars:
            if cam.is_visible(car.render_x, car.render_y, 60):
                car.draw(self.screen, cam)
                car.draw_powerup_indicator(self.screen, cam)

        # Misiles
        for missile in self.missiles:
            if cam.is_visible(missile.x, missile.y, 20):
                missile.draw(self.screen, cam)

        # Misiles inteligentes
        for sm in self.smart_missiles:
            if cam.is_visible(sm.x, sm.y, 20):
                sm.draw(self.screen, cam)

        # Debug: dibujar checkpoint zones y next_checkpoint_index
        if DEBUG_CHECKPOINTS and hasattr(self.track, 'checkpoint_zones'):
            self._render_debug_checkpoints(cam)

    def _render_debug_checkpoints(self, cam):
        """Dibuja zonas de checkpoint y next_cp sobre autos (debug)."""
        zones = self.track.checkpoint_zones

        # Dibujar cada zona como rectángulo semi-transparente
        for i, zone in enumerate(zones):
            # Transformar las 4 esquinas del rect a coordenadas de pantalla
            corners_world = [
                (zone.left, zone.top),
                (zone.right, zone.top),
                (zone.right, zone.bottom),
                (zone.left, zone.bottom),
            ]
            corners_screen = [cam.world_to_screen(wx, wy) for wx, wy in corners_world]

            # Determinar color según estado del jugador
            player_next = self.player_car.next_checkpoint_index
            if i < player_next or (self.player_car.laps > 0 and i < player_next):
                color = (0, 200, 0, 60)  # verde = ya pasado
            elif i == player_next:
                color = (255, 50, 50, 80)  # rojo = siguiente
            else:
                color = (150, 150, 150, 40)  # gris = pendiente

            # Dibujar polígono semi-transparente
            int_corners = [(int(cx), int(cy)) for cx, cy in corners_screen]
            # Calcular bounding box del polígono en pantalla
            min_x = min(c[0] for c in int_corners)
            min_y = min(c[1] for c in int_corners)
            max_x = max(c[0] for c in int_corners)
            max_y = max(c[1] for c in int_corners)
            w = max_x - min_x
            h = max_y - min_y
            if w > 0 and h > 0 and max_x > 0 and max_y > 0:
                overlay = pygame.Surface((w, h), pygame.SRCALPHA)
                shifted = [(cx - min_x, cy - min_y) for cx, cy in int_corners]
                pygame.draw.polygon(overlay, color, shifted)
                pygame.draw.polygon(overlay, (255, 255, 255, 120), shifted, 2)
                self.screen.blit(overlay, (min_x, min_y))

                # Número del checkpoint
                label = self.font_small.render(str(i), True, COLOR_WHITE)
                center_sx = sum(c[0] for c in int_corners) // 4
                center_sy = sum(c[1] for c in int_corners) // 4
                self.screen.blit(label, (center_sx - 4, center_sy - 8))

        # Dibujar next_checkpoint_index sobre cada auto
        for car in self.cars:
            sx, sy = cam.world_to_screen(car.x, car.y)
            label = self.font_small.render(
                f"cp{car.next_checkpoint_index}", True, COLOR_WHITE
            )
            self.screen.blit(label, (int(sx) - 12, int(sy) - 35))

    def _render_countdown(self):
        """Renderiza la cuenta regresiva superpuesta."""
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 100))
        self.screen.blit(overlay, (0, 0))

        if self.countdown_value > 0:
            text = str(self.countdown_value)
            color = COLOR_YELLOW
        else:
            text = "GO!"
            color = COLOR_GREEN

        draw_text_centered(self.screen, text, self.font_title, color,
                           SCREEN_HEIGHT // 2 - 50)

    def _render_hud(self):
        """Renderiza HUD: tiempo, vuelta, velocidad, posición, power-up, minimapa."""
        margin = HUD_MARGIN

        # ── Panel superior izquierdo: Tiempo y vuelta ──
        hud_texts = [
            f"Time: {self.race_timer.formatted_total}",
            f"Lap:  {self.race_timer.current_lap_number}/{TOTAL_LAPS}",
            f"Lap T: {self.race_timer.formatted_lap}",
        ]
        if self.race_timer.best_lap is not None:
            hud_texts.append(
                f"Best:  {RaceTimer.format_time(self.race_timer.best_lap)}"
            )

        hud_h = len(hud_texts) * 26 + 14
        hud_bg = pygame.Surface((240, hud_h), pygame.SRCALPHA)
        hud_bg.fill((20, 20, 20, 180))
        self.screen.blit(hud_bg, (margin, margin))
        for i, text in enumerate(hud_texts):
            rendered = self.font.render(text, True, COLOR_WHITE)
            self.screen.blit(rendered, (margin + 8, margin + 7 + i * 26))

        # ── Panel superior derecho: Velocidad + Posición ──
        speed_kmh = int(abs(self.player_car.speed) * 0.8)
        speed_text = f"{speed_kmh} km/h"
        position = self._get_player_position()
        pos_suffix = {1: "st", 2: "nd", 3: "rd"}.get(position, "th")

        right_bg = pygame.Surface((160, 65), pygame.SRCALPHA)
        right_bg.fill((20, 20, 20, 180))
        self.screen.blit(right_bg, (SCREEN_WIDTH - 160 - margin, margin))

        speed_rendered = self.font.render(speed_text, True, COLOR_YELLOW)
        self.screen.blit(speed_rendered,
                         (SCREEN_WIDTH - 160 - margin + 8, margin + 7))

        pos_color = COLOR_YELLOW if position == 1 else COLOR_WHITE
        pos_rendered = self.font_subtitle.render(
            f"{position}{pos_suffix}", True, pos_color
        )
        self.screen.blit(pos_rendered,
                         (SCREEN_WIDTH - 160 - margin + 8, margin + 33))

        # ── Power-up del jugador (centro inferior) ──
        self._render_powerup_hud()

        # ── Minimapa (esquina inferior izquierda) ──
        self._render_minimap()

    def _render_net_stats(self):
        """Renderiza overlay de estadísticas de red (toggle con F3)."""
        if not self._show_net_stats or not self.net_client:
            return

        s = self._net_stats
        lines = [
            f"-- NET DEBUG (F3) --",
            f"Ping:      {s['ping']:.0f} ms",
            f"Snap rate: {s['snap_rate']:.0f} Hz",
            f"Unacked:   {s['unacked']}",
            f"Recon err: {s['reconcile_error']:.1f} px",
            f"Srv tick:  {s['server_tick']}",
            f"Input seq: {s['input_seq']}",
            f"Srv ack:   {s['last_server_seq']}",
            f"Interp dl: {s.get('interp_delay', 0):.0f} ms",
        ]

        line_h = 18
        panel_w = 220
        panel_h = len(lines) * line_h + 10
        panel_x = SCREEN_WIDTH - panel_w - HUD_MARGIN
        panel_y = SCREEN_HEIGHT - panel_h - HUD_MARGIN - 80

        bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 180))
        self.screen.blit(bg, (panel_x, panel_y))

        for i, line in enumerate(lines):
            # Color coding
            if i == 0:
                color = COLOR_YELLOW
            elif "Ping" in line:
                ping_val = s['ping']
                if ping_val < 50:
                    color = COLOR_GREEN
                elif ping_val < 100:
                    color = COLOR_YELLOW
                else:
                    color = COLOR_RED
            elif "Recon err" in line:
                err = s['reconcile_error']
                if err < 5:
                    color = COLOR_GREEN
                elif err < 20:
                    color = COLOR_YELLOW
                else:
                    color = COLOR_RED
            elif "Snap rate" in line:
                rate = s['snap_rate']
                if rate >= 27:
                    color = COLOR_GREEN
                elif rate >= 20:
                    color = COLOR_YELLOW
                else:
                    color = COLOR_RED
            else:
                color = COLOR_WHITE

            rendered = self.font_small.render(line, True, color)
            self.screen.blit(rendered, (panel_x + 6, panel_y + 5 + i * line_h))

    def _render_powerup_hud(self):
        """Dibuja el indicador de power-up del jugador en la parte inferior."""
        pw_size = 50
        px = SCREEN_WIDTH // 2 - pw_size // 2
        py = SCREEN_HEIGHT - pw_size - 20

        # Fondo
        bg = pygame.Surface((pw_size + 8, pw_size + 22), pygame.SRCALPHA)
        bg.fill((20, 20, 20, 160))
        self.screen.blit(bg, (px - 4, py - 4))

        if self.player_car.held_powerup is not None:
            ptype = self.player_car.held_powerup
            color = POWERUP_COLORS.get(ptype, (200, 200, 200))

            # Cuadro coloreado
            pygame.draw.rect(self.screen, color,
                             (px, py, pw_size, pw_size), border_radius=6)
            pygame.draw.rect(self.screen, COLOR_WHITE,
                             (px, py, pw_size, pw_size), 2, border_radius=6)

            # Nombre
            name = ptype.upper()
            name_surf = self.font_small.render(name, True, COLOR_WHITE)
            name_rect = name_surf.get_rect(
                centerx=px + pw_size // 2, top=py + pw_size + 3
            )
            self.screen.blit(name_surf, name_rect)
        else:
            # Sin power-up
            pygame.draw.rect(self.screen, (60, 60, 60),
                             (px, py, pw_size, pw_size), 2, border_radius=6)
            lbl = self.font_small.render("[CLICK]", True, (80, 80, 80))
            lbl_rect = lbl.get_rect(
                centerx=px + pw_size // 2, top=py + pw_size + 3
            )
            self.screen.blit(lbl, lbl_rect)

        # Efectos activos (mostrar debajo como íconos con timer)
        effects = self.player_car.active_effects
        if effects:
            ey = py - 22
            for name, remaining in effects.items():
                color = {
                    "boost": POWERUP_COLORS[POWERUP_BOOST],
                    "shield": POWERUP_COLORS[POWERUP_SHIELD],
                    "oil_slow": POWERUP_COLORS[POWERUP_OIL],
                    "missile_slow": POWERUP_COLORS[POWERUP_MISSILE],
                    "mine_spin": POWERUP_COLORS[POWERUP_MINE],
                    "emp_slow": POWERUP_COLORS[POWERUP_EMP],
                    "magnet": POWERUP_COLORS[POWERUP_MAGNET],
                    "slowmo": POWERUP_COLORS[POWERUP_SLOWMO],
                    "bounce": POWERUP_COLORS[POWERUP_BOUNCE],
                    "autopilot": POWERUP_COLORS[POWERUP_AUTOPILOT],
                }.get(name, COLOR_WHITE)
                txt = f"{name}: {remaining:.1f}s"
                surf = self.font_small.render(txt, True, color)
                rect = surf.get_rect(centerx=SCREEN_WIDTH // 2, top=ey)
                self.screen.blit(surf, rect)
                ey -= 20

    def _render_minimap(self):
        """Dibuja el minimapa con posiciones de los autos."""
        mm = self.track.minimap_surface.copy()

        # Dibujar puntos de los autos
        for car in self.cars:
            mx, my = self.track.get_minimap_pos(car.render_x, car.render_y)
            pygame.draw.circle(mm, car.color, (mx, my), MINIMAP_CAR_DOT)
            pygame.draw.circle(mm, COLOR_WHITE, (mx, my), MINIMAP_CAR_DOT, 1)

        # Dibujar power-ups activos (caja misteriosa dorada)
        for item in self.powerup_items:
            if item.active:
                mx, my = self.track.get_minimap_pos(item.x, item.y)
                pygame.draw.circle(mm, POWERUP_MYSTERY_COLOR, (mx, my), 2)

        # Posicionar en esquina inferior izquierda
        x = MINIMAP_MARGIN
        y = SCREEN_HEIGHT - mm.get_height() - MINIMAP_MARGIN
        self.screen.blit(mm, (x, y))

    def _update_victory(self, dt):
        """Actualiza estado de victoria. Online: espera return-to-lobby del servidor."""
        if not self.is_online or not self.net_client:
            return

        if not self.net_client.connected:
            self._net_error_msg = "Server disconnected"
            self._stop_online()
            self.state = STATE_MENU
            return

        if self.net_client.should_return_to_lobby():
            # Volver al lobby sin desconectar
            self._is_lobby_admin = self.net_client.is_admin
            self.state = STATE_JOIN_LOBBY

    def _render_victory(self):
        """Renderiza la pantalla de victoria."""
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        if self.winner and self.winner.player_id == self.my_player_id:
            title = "YOU WIN!"
            title_color = COLOR_YELLOW
        else:
            title = "RACE OVER"
            title_color = COLOR_RED

        draw_text_centered(self.screen, title, self.font_title,
                           title_color, 160)

        y_pos = 280
        draw_text_centered(self.screen, "Results:", self.font_subtitle,
                           COLOR_WHITE, y_pos)
        y_pos += 50

        if self.race_progress:
            rankings = self.race_progress.get_all_rankings()
            car_by_id = {c.player_id: c for c in self.cars}
            for pos, pid, _score in rankings:
                car = car_by_id.get(pid)
                if car is None:
                    continue
                if car.finished:
                    time_str = RaceTimer.format_time(car.finish_time)
                    text = f"{pos}. {car.name} - {time_str}"
                else:
                    text = f"{pos}. {car.name} - DNF"
                color = COLOR_YELLOW if car == self.winner else COLOR_WHITE
                draw_text_centered(self.screen, text, self.font_subtitle,
                                   color, y_pos)
                y_pos += 40
        else:
            for i, car in enumerate(self.cars):
                text = f"{i + 1}. {car.name} - DNF"
                draw_text_centered(self.screen, text, self.font_subtitle,
                                   COLOR_WHITE, y_pos)
                y_pos += 40

        if self.race_timer.best_lap is not None:
            y_pos += 20
            best = RaceTimer.format_time(self.race_timer.best_lap)
            draw_text_centered(self.screen, f"Your Best Lap: {best}",
                               self.font, COLOR_GREEN, y_pos)

        if self.is_online:
            draw_text_centered(self.screen, "Returning to lobby...",
                               self.font, COLOR_YELLOW, SCREEN_HEIGHT - 110)
            draw_text_centered(self.screen, "ESC: Leave server",
                               self.font, COLOR_GRAY, SCREEN_HEIGHT - 80)
        else:
            draw_text_centered(self.screen, "Press ENTER to return to menu",
                               self.font, COLOR_GRAY, SCREEN_HEIGHT - 80)

    # ──────────────────────────────────────────────
    # EDITOR & TRACK SELECT
    # ──────────────────────────────────────────────

    def _open_editor(self):
        """Abre el editor de pistas."""
        self.editor = TileEditor(self.screen)
        self.state = STATE_EDITOR
        self.return_to_editor = False

    def _open_editor_with_points(self):
        """Vuelve al editor conservando los tiles de la carrera de prueba."""
        if self.editor is None:
            self.editor = TileEditor(self.screen)
        self.state = STATE_EDITOR
        self.return_to_editor = False
        self.editor.result = None

    def _open_track_select(self):
        """Abre la pantalla de selección de pista."""
        self.track_list = track_manager.list_tracks()
        self.track_selected = 0
        self.state = STATE_TRACK_SELECT
        self.return_to_editor = False

    def _start_selected_track(self):
        """Inicia carrera con la pista seleccionada."""
        if not self.track_list:
            return
        entry = self.track_list[self.track_selected]
        try:
            data = track_manager.load_track(entry["filename"])
            if data.get("format") == "tiles":
                self._start_race(tile_data=data)
            else:
                self._start_race(control_points=data["control_points"])
        except (OSError, KeyError):
            pass

    def _edit_selected_track(self):
        """Abre la pista seleccionada en el editor para editarla."""
        if not self.track_list:
            return
        entry = self.track_list[self.track_selected]
        if entry.get("type") != "tiles":
            return
        self.editor = TileEditor(self.screen)
        if self.editor.load_from_file(entry["filename"]):
            self.state = STATE_EDITOR
            self.return_to_editor = False
        else:
            self.editor = None

    # ──────────────────────────────────────────────
    # TRAINING
    # ──────────────────────────────────────────────

    def _start_training_screen(self):
        """Abre la pantalla de entrenamiento RL para la pista seleccionada."""
        entry = self.track_list[self.track_selected]
        self._train_track_name = entry["name"]
        self._train_track_file = entry["filename"]
        self._train_status = "idle"
        self._train_progress = {}
        self._train_timesteps = 200000
        self.state = STATE_TRAINING

    def _launch_training(self):
        """Lanza el subproceso de entrenamiento RL."""
        from utils.base_path import TRACKS_DIR, get_writable_dir

        track_path = os.path.join(TRACKS_DIR, self._train_track_file)
        writable_dir = get_writable_dir()

        self._train_progress_file = os.path.join(
            tempfile.gettempdir(), f"rl_progress_{os.getpid()}.json"
        )
        # Limpiar archivo de progreso previo
        if os.path.exists(self._train_progress_file):
            os.remove(self._train_progress_file)

        # Construir comando: frozen exe no necesita script, source sí
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--train-subprocess"]
        else:
            project_root = os.path.dirname(os.path.abspath(__file__))
            main_script = os.path.join(project_root, "main.py")
            cmd = [sys.executable, main_script, "--train-subprocess"]
        cmd += [track_path,
                "--timesteps", str(self._train_timesteps),
                "--json-progress", self._train_progress_file]

        self._train_process = subprocess.Popen(
            cmd, cwd=writable_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._train_status = "training"
        self._train_progress = {}

    def _update_training(self, dt):
        """Lee el progreso del subproceso de entrenamiento."""
        if self._train_status != "training":
            return

        # Leer progreso del JSON
        if self._train_progress_file and os.path.exists(self._train_progress_file):
            try:
                with open(self._train_progress_file, "r") as f:
                    self._train_progress = json.load(f)
                status = self._train_progress.get("status", "training")
                if status in ("done", "error"):
                    self._train_status = status
            except (json.JSONDecodeError, IOError):
                pass  # archivo en escritura parcial, reintentar next frame

        # Verificar si el proceso murió inesperadamente
        if self._train_process and self._train_process.poll() is not None:
            if self._train_status == "training":
                self._train_status = "error"
                # Leer stderr completo para diagnóstico
                err_msg = ""
                self._train_error_log = ""
                try:
                    _, stderr = self._train_process.communicate(timeout=2)
                    if stderr:
                        full_err = stderr.decode(errors="replace").strip()
                        # Guardar error completo a archivo log
                        self._train_error_log = os.path.join(
                            os.path.dirname(os.path.abspath(__file__)),
                            "training_error.log"
                        )
                        with open(self._train_error_log, "w") as f:
                            f.write(full_err)
                        # Extraer líneas útiles del traceback
                        lines = full_err.splitlines()
                        # Tomar las últimas líneas relevantes
                        err_lines = []
                        for line in reversed(lines):
                            err_lines.insert(0, line.strip())
                            if len(err_lines) >= 3:
                                break
                        err_msg = "\n".join(err_lines)
                except Exception:
                    pass
                self._train_progress["message"] = (
                    err_msg or "Training process exited unexpectedly"
                )

    def _cancel_training(self):
        """Cancela el entrenamiento en curso y limpia recursos."""
        if self._train_process and self._train_process.poll() is None:
            self._train_process.terminate()
            try:
                self._train_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._train_process.kill()
        self._train_process = None
        self._train_status = "idle"
        if self._train_progress_file and os.path.exists(self._train_progress_file):
            try:
                os.remove(self._train_progress_file)
            except OSError:
                pass

    def _render_training(self):
        """Renderiza la pantalla de entrenamiento RL."""
        # Gradient background (same as menu/track_select)
        for y in range(SCREEN_HEIGHT):
            ratio = y / SCREEN_HEIGHT
            r = int(10 + 20 * ratio)
            g = int(10 + 15 * ratio)
            b = int(30 + 40 * ratio)
            pygame.draw.line(self.screen, (r, g, b), (0, y), (SCREEN_WIDTH, y))

        # Title
        draw_text_centered(self.screen, "TRAIN AI MODEL",
                           self.font_title, COLOR_YELLOW, 80)

        # Track name
        draw_text_centered(self.screen, f"Track: {self._train_track_name}",
                           self.font_subtitle, COLOR_WHITE, 160)

        # Timesteps selector
        ts_text = f"{self._train_timesteps:,}"
        if self._train_status == "idle":
            draw_text_centered(
                self.screen,
                f"Timesteps:  < {ts_text} >",
                self.font_subtitle, COLOR_WHITE, 230,
            )
            draw_text_centered(
                self.screen, "UP/DOWN to adjust",
                self.font_small, COLOR_GRAY, 265,
            )
        else:
            draw_text_centered(
                self.screen, f"Timesteps: {ts_text}",
                self.font_subtitle, COLOR_GRAY, 230,
            )

        # Progress bar area
        bar_x = SCREEN_WIDTH // 2 - 250
        bar_y = 320
        bar_w = 500
        bar_h = 30

        progress = self._train_progress
        done = progress.get("timesteps_done", 0)
        total = progress.get("timesteps_total", self._train_timesteps)
        fraction = min(done / total, 1.0) if total > 0 else 0.0

        if self._train_status in ("training", "done", "error"):
            # Background
            pygame.draw.rect(self.screen, COLOR_PROGRESS_BG,
                             (bar_x, bar_y, bar_w, bar_h), border_radius=4)
            # Fill
            fill_w = int(bar_w * fraction)
            if fill_w > 0:
                fill_color = COLOR_PROGRESS_BAR if self._train_status != "error" else COLOR_RED
                pygame.draw.rect(self.screen, fill_color,
                                 (bar_x, bar_y, fill_w, bar_h), border_radius=4)
            # Border
            pygame.draw.rect(self.screen, COLOR_WHITE,
                             (bar_x, bar_y, bar_w, bar_h), 2, border_radius=4)
            # Percentage
            pct_text = f"{int(fraction * 100)}%"
            draw_text_centered(self.screen, pct_text, self.font,
                               COLOR_WHITE, bar_y + 4)

            # Stats below bar
            stats_y = bar_y + 45
            draw_text_centered(
                self.screen,
                f"{done:,} / {total:,} timesteps",
                self.font, COLOR_WHITE, stats_y,
            )

            elapsed = progress.get("elapsed_seconds", 0)
            mins = int(elapsed) // 60
            secs = int(elapsed) % 60
            stats_parts = [f"Elapsed: {mins}:{secs:02d}"]
            if "mean_reward" in progress:
                stats_parts.append(f"Mean reward: {progress['mean_reward']:.1f}")
            if "episodes_done" in progress:
                stats_parts.append(f"Episodes: {progress['episodes_done']}")
            draw_text_centered(
                self.screen,
                "  |  ".join(stats_parts),
                self.font, COLOR_GRAY, stats_y + 30,
            )

        # Status line
        status_y = 450
        if self._train_status == "idle":
            draw_text_centered(self.screen, "Ready to train",
                               self.font_subtitle, COLOR_WHITE, status_y)
        elif self._train_status == "training":
            dots = "." * ((pygame.time.get_ticks() // 500) % 4)
            draw_text_centered(self.screen, f"Training{dots}",
                               self.font_subtitle, COLOR_YELLOW, status_y)
        elif self._train_status == "done":
            draw_text_centered(self.screen, "Training Complete!",
                               self.font_subtitle, COLOR_GREEN, status_y)
            model_path = progress.get("model_path", "")
            if model_path:
                draw_text_centered(self.screen, f"Model saved: {os.path.basename(model_path)}",
                                   self.font, COLOR_GRAY, status_y + 35)
        elif self._train_status == "error":
            draw_text_centered(self.screen, "Training Error",
                               self.font_subtitle, COLOR_RED, status_y)
            msg = progress.get("message", "Unknown error")
            # Mostrar cada línea del error
            err_y = status_y + 35
            for line in msg.splitlines():
                if err_y > SCREEN_HEIGHT - 100:
                    break
                draw_text_centered(self.screen, line,
                                   self.font_small, COLOR_RED, err_y)
                err_y += 20
            # Mostrar ruta del log si existe
            log_path = getattr(self, "_train_error_log", "")
            if log_path:
                draw_text_centered(self.screen, f"Full log: {log_path}",
                                   self.font_small, COLOR_GRAY, err_y + 5)

        # Footer
        sep_y = SCREEN_HEIGHT - 80
        pygame.draw.line(self.screen, COLOR_GRAY,
                         (100, sep_y), (SCREEN_WIDTH - 100, sep_y))

        if self._train_status == "idle":
            footer = "ENTER: Start Training  |  ESC: Back"
        elif self._train_status == "training":
            footer = "ESC: Cancel Training"
        else:
            footer = "ENTER: Back to Track Select  |  ESC: Back"
        draw_text_centered(self.screen, footer,
                           self.font, COLOR_GRAY, SCREEN_HEIGHT - 55)

    def _render_track_select(self):
        """Renderiza la pantalla de selección de pista."""
        # Gradient background
        for y in range(SCREEN_HEIGHT):
            ratio = y / SCREEN_HEIGHT
            r = int(10 + 20 * ratio)
            g = int(10 + 15 * ratio)
            b = int(30 + 40 * ratio)
            pygame.draw.line(self.screen, (r, g, b), (0, y), (SCREEN_WIDTH, y))

        draw_text_centered(self.screen, "SELECT TRACK",
                           self.font_title, COLOR_YELLOW, 80)

        if not self.track_list:
            draw_text_centered(self.screen, "No tracks found",
                               self.font_subtitle, COLOR_GRAY, 200)
            draw_text_centered(self.screen, "Press E in menu to create one",
                               self.font, COLOR_GRAY, 250)
        else:
            start_y = 180
            visible = 12
            start_idx = max(0, self.track_selected - visible + 1)
            end_idx = min(len(self.track_list), start_idx + visible)

            for i_draw, i in enumerate(range(start_idx, end_idx)):
                entry = self.track_list[i]
                yy = start_y + i_draw * 38
                name = entry["name"]
                fname = entry["filename"]
                track_type = entry.get("type", "classic")

                if i == self.track_selected:
                    sel_rect = pygame.Rect(
                        SCREEN_WIDTH // 2 - 250, yy - 2, 500, 34)
                    pygame.draw.rect(self.screen, (40, 50, 90), sel_rect,
                                     border_radius=4)
                    pygame.draw.rect(self.screen, COLOR_YELLOW, sel_rect, 1,
                                     border_radius=4)
                    color = COLOR_YELLOW
                else:
                    color = COLOR_WHITE

                type_tag = f" [{track_type}]" if track_type == "tiles" else ""
                draw_text_centered(self.screen, name + type_tag,
                                   self.font_subtitle, color, yy)
                draw_text_centered(self.screen, f"({fname})",
                                   self.font_small, COLOR_GRAY, yy + 22)

        draw_text_centered(self.screen, "UP/DOWN select | ENTER race | E edit | T train | ESC",
                           self.font_small, COLOR_GRAY, SCREEN_HEIGHT - 50)

    # ──────────────────────────────────────────────
    # MULTIPLAYER ONLINE
    # ──────────────────────────────────────────────

    def _render_gradient_bg(self):
        """Renderiza fondo degradado reutilizable."""
        for y in range(SCREEN_HEIGHT):
            ratio = y / SCREEN_HEIGHT
            r = int(10 + 20 * ratio)
            g = int(10 + 15 * ratio)
            b = int(30 + 40 * ratio)
            pygame.draw.line(self.screen, (r, g, b), (0, y), (SCREEN_WIDTH, y))

    def _stop_online(self):
        """Limpia toda la infraestructura de red."""
        if self.net_client:
            self.net_client.disconnect()
            self.net_client = None
        self._stop_local_server()
        self.is_online = False
        self.my_player_id = 0
        self._net_error_msg = ""
        self._is_lobby_admin = False
        self._admin_track_list = []
        self._admin_track_selected = 0
        self._admin_bot_count = 1
        # Room select cleanup
        self._room_list = []
        self._room_selected = 0
        self._room_create_mode = False
        self._room_code_mode = False
        self._room_error_msg = ""

    def _update_online_countdown(self, dt):
        """Cuenta regresiva para carrera online."""
        self._online_countdown_timer += dt
        if self.player_car:
            self.camera.update(self.player_car.x, self.player_car.y,
                               self.player_car.angle, 0, dt)
        if self._online_countdown_timer >= 1.0:
            self._online_countdown_timer -= 1.0
            self._online_countdown_value -= 1
            self.countdown_value = self._online_countdown_value
            if self._online_countdown_value < 0:
                if self.player_car:
                    print(f"[DEBUG-GO] countdown→racing: "
                          f"x={self.player_car.x:.1f} y={self.player_car.y:.1f} "
                          f"rx={self.player_car.render_x:.1f} ry={self.player_car.render_y:.1f} "
                          f"spd={self.player_car.speed:.1f}")
                # Limpiar snapshots acumulados durante countdown para evitar
                # salto de posición al reconciliar con datos pre-racing
                if self.net_client:
                    self.net_client.clear_snapshots()
                self.state = STATE_ONLINE_RACING
                self.race_timer.start()

    def _simulate_car_step(self, car, dt):
        """Un paso determinista de simulación de auto.
        Usada por: predicción del cliente, replay.
        Incluye: effects, física, drift, colisión con muros."""
        car.update_effects(dt)
        self.physics.update(car, dt, self.track)
        hit, normal, remaining = self.collision_system.move_with_substeps(car, dt)
        if hit:
            if car.is_shielded:
                car.break_shield()
                car.speed *= 0.7
            elif car.has_bounce:
                self.physics.apply_collision_response(car, normal)
                car.speed *= 1.3
            else:
                self.physics.apply_collision_response(car, normal)
            if remaining > 0:
                self.collision_system.move_with_substeps(car, remaining)
        car.update_sprite()

    def _simulate_car_step_headless(self, car, dt):
        """Simulation step sin modificar render state.
        Usado para: predicción local online, replay de reconciliación."""
        car.update_effects(dt)
        self.physics.update(car, dt, self.track)
        hit, normal, remaining = self.collision_system.move_with_substeps(car, dt)
        if hit:
            if car.is_shielded:
                car.break_shield()
                car.speed *= 0.7
            elif car.has_bounce:
                self.physics.apply_collision_response(car, normal)
                car.speed *= 1.3
            else:
                self.physics.apply_collision_response(car, normal)
            if remaining > 0:
                self.collision_system.move_with_substeps(car, remaining)

    def _predict_car_vs_car_local(self, local_car, remote_car):
        """Predicción local de colisión car-vs-car (solo empuja auto local)."""
        dx = remote_car.x - local_car.x
        dy = remote_car.y - local_car.y
        dist = math.hypot(dx, dy)
        if dist < 1.0:
            dx, dy, dist = 1.0, 0.0, 1.0
        nx, ny = dx / dist, dy / dist
        min_dist = local_car.collision_radius + remote_car.collision_radius
        overlap = min_dist - dist
        if overlap > 0:
            half = (overlap + 1.0) * 0.5
            local_car.x -= nx * half
            local_car.y -= ny * half
        dot_a = local_car.velocity.x * nx + local_car.velocity.y * ny
        dot_b = remote_car.velocity.x * nx + remote_car.velocity.y * ny
        if dot_a - dot_b > 0:
            local_car.velocity.x += (dot_b - dot_a) * nx
            local_car.velocity.y += (dot_b - dot_a) * ny
        local_car.speed *= CAR_VS_CAR_SPEED_PENALTY

    def _smooth_player_render(self, dt):
        """Suavizado visual del auto local. Solo cosmético, no afecta simulación."""
        if not self.player_car:
            return
        car = self.player_car
        factor = 1.0 - math.exp(-VISUAL_SMOOTH_RATE * dt)
        car.render_x += (car.x - car.render_x) * factor
        car.render_y += (car.y - car.render_y) * factor
        angle_diff = (car.angle - car.render_angle + 180) % 360 - 180
        car.render_angle += angle_diff * factor

    def _start_join_screen(self):
        """Muestra pantalla de selección: servidor online o local."""
        self._lobby_ip_input = ""
        self._lobby_name_input = "Player"
        self._net_error_msg = ""
        self._ip_cursor_blink = 0.0
        self._join_mode = "choose"  # "choose" | "connecting"
        self._join_choice = 0       # 0 = Online, 1 = Local
        self.state = STATE_CONNECTING

    def _update_connecting(self, dt):
        """Poll resultado de connect_async."""
        if not self.net_client:
            return
        if not self.net_client._connect_done:
            return  # Todavía conectando...

        if self.net_client._connect_ok:
            self.my_player_id = self.net_client.player_id
            self._is_lobby_admin = self.net_client.is_admin
            self.is_online = True
            self._net_error_msg = ""
            if self.net_client.multi_room:
                self.state = STATE_ROOM_SELECT
                self._room_list = []
                self._room_selected = 0
                self._room_error_msg = ""
                self._room_refresh_timer = 0.0
                self.net_client.request_room_list()
                print(f"[GAME] Connected to multi-room server")
            else:
                self.state = STATE_JOIN_LOBBY
                admin_tag = " (Admin)" if self._is_lobby_admin else ""
                print(f"[GAME] Connected to host as Player {self.my_player_id + 1}{admin_tag}")
        else:
            reason = self.net_client.reject_reason
            if reason == 1:
                self._net_error_msg = "Lobby is full"
            elif reason == 2:
                self._net_error_msg = "Race already in progress"
            else:
                self._net_error_msg = "Could not connect to host"
            self.net_client.disconnect()
            self.net_client = None
            self._stop_local_server()
            self._join_mode = "choose"

    def _attempt_connect(self):
        """Inicia conexión async al host con la IP configurada."""
        ip = self._lobby_ip_input.strip()
        if not ip:
            self._net_error_msg = "Enter host IP address"
            return

        # Si ya hay una conexión en progreso, ignorar
        if self.net_client:
            return

        self._join_mode = "connecting"

        from networking.client import GameClient
        self.net_client = GameClient(ip)
        self._net_error_msg = "Connecting..."

        name = self._lobby_name_input or "Player"
        self.net_client.connect_async(name)

    def _start_local_server(self):
        """Inicia un servidor local multi-room en un hilo y auto-conecta."""
        import threading
        from networking.server import GameServer
        from server.room_manager import RoomManager
        from track_manager import list_tracks

        # Elegir track por defecto (el primero disponible)
        tracks = list_tracks()
        default_track = tracks[0]["filename"] if tracks else "default_circuit.json"

        # Crear GameServer local
        try:
            srv = GameServer(port=NET_DEFAULT_PORT, dedicated=True)
            srv.track_name = default_track
            srv.host_name = "Local Server"
            srv.start()
        except OSError as e:
            self._net_error_msg = f"Cannot start local server: {e}"
            return

        # Crear RoomManager (multi-room)
        rm = RoomManager(srv, default_track, 1, 4)
        srv._room_manager = rm

        self._local_server = srv
        self._local_room_manager = rm

        # Tick loop en hilo daemon
        from settings import FIXED_DT
        import time

        def _tick_loop():
            next_tick = time.perf_counter()
            while srv._running:
                now = time.perf_counter()
                ticks = 0
                while now >= next_tick and ticks < 2:
                    try:
                        rm.tick_all(FIXED_DT)
                    except Exception as e:
                        print(f"[LOCAL-SERVER] Error in tick: {e}")
                    next_tick += FIXED_DT
                    ticks += 1
                if now >= next_tick:
                    next_tick = now
                remaining = next_tick - time.perf_counter()
                if remaining > 0.002:
                    time.sleep(0.001)

        t = threading.Thread(target=_tick_loop, daemon=True)
        t.start()
        self._local_server_thread = t

        print(f"[GAME] Local multi-room server started on port {NET_DEFAULT_PORT}")

        # Auto-conectar al servidor local
        self._lobby_ip_input = "127.0.0.1"
        self._join_mode = "connecting"
        self._net_error_msg = "Connecting..."
        self._attempt_connect()

    def _stop_local_server(self):
        """Detiene el servidor local si existe."""
        if self._local_server:
            print("[GAME] Stopping local server...")
            self._local_server.stop()
            self._local_server = None
            self._local_room_manager = None
            self._local_server_thread = None

    def _render_connecting(self):
        """Renderiza pantalla de conexión según el sub-modo."""
        self._render_gradient_bg()

        if self._join_mode == "choose":
            self._render_join_choose()
        else:
            self._render_connecting_status()

    def _render_join_choose(self):
        """Pantalla de selección: Online o LAN."""
        draw_text_centered(self.screen, "JOIN GAME",
                           self.font_title, COLOR_YELLOW, 120)

        box_w = 400
        box_h = 80
        box_x = SCREEN_WIDTH // 2 - box_w // 2

        # Online box
        y1 = 260
        sel0 = self._join_choice == 0
        bg0 = (40, 60, 40) if sel0 else (25, 25, 35)
        border0 = COLOR_GREEN if sel0 else (60, 60, 80)
        pygame.draw.rect(self.screen, bg0,
                         (box_x, y1, box_w, box_h), border_radius=8)
        pygame.draw.rect(self.screen, border0,
                         (box_x, y1, box_w, box_h), 2, border_radius=8)
        prefix0 = "> " if sel0 else "  "
        draw_text_centered(self.screen, f"{prefix0}Online Server",
                           self.font_subtitle,
                           COLOR_GREEN if sel0 else COLOR_GRAY, y1 + 15)
        draw_text_centered(self.screen, f"({DEDICATED_SERVER_IP})",
                           self.font_small, COLOR_GRAY, y1 + 48)

        # Local box
        y2 = 370
        sel1 = self._join_choice == 1
        bg1 = (30, 40, 60) if sel1 else (25, 25, 35)
        border1 = COLOR_BLUE if sel1 else (60, 60, 80)
        pygame.draw.rect(self.screen, bg1,
                         (box_x, y2, box_w, box_h), border_radius=8)
        pygame.draw.rect(self.screen, border1,
                         (box_x, y2, box_w, box_h), 2, border_radius=8)
        prefix1 = "> " if sel1 else "  "
        draw_text_centered(self.screen, f"{prefix1}Local",
                           self.font_subtitle,
                           COLOR_BLUE if sel1 else COLOR_GRAY, y2 + 15)
        draw_text_centered(self.screen, "Play on this computer (LAN)",
                           self.font_small, COLOR_GRAY, y2 + 48)

        # Error (si volvió de un intento fallido)
        if self._net_error_msg:
            draw_text_centered(self.screen, self._net_error_msg,
                               self.font, COLOR_RED, 490)

        draw_text_centered(self.screen,
                           "UP/DOWN: Select  |  ENTER: Confirm  |  ESC: Back",
                           self.font, COLOR_GRAY, SCREEN_HEIGHT - 50)

    def _render_connecting_status(self):
        """Pantalla de 'conectando...'"""
        if self._local_server:
            target = "Local Server"
        else:
            target = self._lobby_ip_input or DEDICATED_SERVER_IP
        draw_text_centered(self.screen, "CONNECTING",
                           self.font_title, COLOR_YELLOW, 200)

        draw_text_centered(self.screen, f"Server: {target}",
                           self.font, COLOR_GRAY, 280)

        dots = "." * (int(self._ip_cursor_blink * 2) % 4)
        draw_text_centered(self.screen, f"Please wait{dots}",
                           self.font_subtitle, COLOR_WHITE, 330)

        if self._net_error_msg and "Connecting" not in self._net_error_msg:
            draw_text_centered(self.screen, self._net_error_msg,
                               self.font, COLOR_RED, 400)

        draw_text_centered(self.screen, "ESC: Cancel",
                           self.font, COLOR_GRAY, SCREEN_HEIGHT - 50)

    # ── ROOM SELECT (multi-room) ──

    def _update_room_select(self, dt):
        """Actualiza pantalla de selección de salas."""
        if not self.net_client or not self.net_client.connected:
            self._stop_online()
            self.state = STATE_MENU
            return

        # Refresh room list periódicamente
        self._room_refresh_timer += dt
        if self._room_refresh_timer >= ROOM_LIST_REFRESH_INTERVAL:
            self._room_refresh_timer = 0.0
            self.net_client.request_room_list()

        # Actualizar lista desde el cliente
        new_list = self.net_client.get_room_list()
        if new_list is not None:
            self._room_list = new_list
            if self._room_selected >= len(self._room_list):
                self._room_selected = max(0, len(self._room_list) - 1)

        # Verificar si se unió a una sala
        if self.net_client.has_joined_room():
            self.my_player_id = self.net_client.player_id
            self._is_lobby_admin = self.net_client.is_admin
            self.state = STATE_JOIN_LOBBY
            self._room_error_msg = ""
            admin_tag = " (Admin)" if self._is_lobby_admin else ""
            print(f"[GAME] Joined room as Player {self.my_player_id + 1}{admin_tag}")
            return

        # Verificar rechazo
        reason = self.net_client.get_room_reject_reason()
        if reason > 0:
            from networking.protocol import ROOM_FULL, ROOM_RACING, ROOM_NOT_FOUND, MAX_ROOMS_REACHED
            msg_map = {
                ROOM_FULL: "Room is full",
                ROOM_RACING: "Race in progress",
                ROOM_NOT_FOUND: "Room not found",
                MAX_ROOMS_REACHED: "Max rooms reached",
            }
            self._room_error_msg = msg_map.get(reason, f"Rejected (code {reason})")

    def _render_room_select(self):
        """Renderiza pantalla de selección de salas."""
        self._render_gradient_bg()

        draw_text_centered(self.screen, "ROOM SELECT",
                           self.font_title, COLOR_YELLOW, 50)

        if self._room_create_mode:
            self._render_room_create_dialog()
            return
        if self._room_code_mode:
            self._render_room_code_dialog()
            return

        # Room list
        list_y = 120
        list_h = 380
        list_x = 80
        list_w = SCREEN_WIDTH - 160

        # Header
        pygame.draw.rect(self.screen, (30, 30, 50),
                         (list_x, list_y, list_w, 30), border_radius=4)
        hdr_font = self.font_small
        hdr_surf = hdr_font.render(
            f"{'Room':<22} {'Players':<10} {'Track':<20} {'Status':<10}",
            True, COLOR_GRAY)
        self.screen.blit(hdr_surf, (list_x + 10, list_y + 6))

        # Rooms
        row_y = list_y + 35
        if not self._room_list:
            draw_text_centered(self.screen, "No rooms available",
                               self.font, COLOR_GRAY, row_y + 40)
            draw_text_centered(self.screen, "Press C to create one",
                               self.font_small, COLOR_GRAY, row_y + 70)
        else:
            for i, room in enumerate(self._room_list):
                is_sel = (i == self._room_selected)
                bg_color = (50, 50, 80) if is_sel else (25, 25, 40)
                pygame.draw.rect(self.screen, bg_color,
                                 (list_x, row_y, list_w, 32), border_radius=3)
                if is_sel:
                    pygame.draw.rect(self.screen, COLOR_YELLOW,
                                     (list_x, row_y, list_w, 32), 2,
                                     border_radius=3)

                state_names = {0: "Lobby", 1: "Starting", 2: "Racing", 3: "Done"}
                state_colors = {0: COLOR_GREEN, 1: COLOR_YELLOW,
                                2: COLOR_ORANGE, 3: COLOR_GRAY}
                state = room.get("state", 0)
                name = room.get("name", "?")[:20]
                players = f"{room.get('players', 0)}/{room.get('max_players', 4)}"
                track = room.get("track", "?")[:18]
                status = state_names.get(state, "?")

                txt = f"  {name:<20} {players:<10} {track:<20}"
                txt_surf = self.font_small.render(txt, True, COLOR_WHITE)
                self.screen.blit(txt_surf, (list_x + 5, row_y + 7))

                status_surf = self.font_small.render(
                    status, True, state_colors.get(state, COLOR_WHITE))
                self.screen.blit(status_surf, (list_x + list_w - 80, row_y + 7))

                row_y += 36
                if row_y > list_y + list_h:
                    break

        # Error message
        if self._room_error_msg:
            draw_text_centered(self.screen, self._room_error_msg,
                               self.font, COLOR_RED, SCREEN_HEIGHT - 130)

        # Footer controls
        draw_text_centered(self.screen,
                           "ENTER: Join  |  C: Create Room  |  P: Join by Code",
                           self.font, COLOR_GREEN, SCREEN_HEIGHT - 80)
        draw_text_centered(self.screen,
                           "UP/DOWN: Navigate  |  ESC: Disconnect",
                           self.font, COLOR_GRAY, SCREEN_HEIGHT - 50)

    def _render_room_create_dialog(self):
        """Renderiza diálogo de creación de sala."""
        # Overlay box
        box_w = 450
        box_h = 220
        box_x = SCREEN_WIDTH // 2 - box_w // 2
        box_y = SCREEN_HEIGHT // 2 - box_h // 2
        pygame.draw.rect(self.screen, (20, 20, 35),
                         (box_x, box_y, box_w, box_h), border_radius=8)
        pygame.draw.rect(self.screen, COLOR_YELLOW,
                         (box_x, box_y, box_w, box_h), 2, border_radius=8)

        draw_text_centered(self.screen, "CREATE ROOM",
                           self.font_subtitle, COLOR_YELLOW, box_y + 20)

        # Name input
        draw_text_centered(self.screen, "Room Name:",
                           self.font, COLOR_WHITE, box_y + 60)

        inp_w = 300
        inp_h = 35
        inp_x = SCREEN_WIDTH // 2 - inp_w // 2
        inp_y = box_y + 85
        pygame.draw.rect(self.screen, (40, 40, 60),
                         (inp_x, inp_y, inp_w, inp_h), border_radius=4)
        pygame.draw.rect(self.screen, COLOR_WHITE,
                         (inp_x, inp_y, inp_w, inp_h), 2, border_radius=4)

        cursor = "|" if int(self._room_cursor_blink * 2) % 2 == 0 else ""
        name_text = self._room_name_input + cursor
        name_surf = self.font.render(name_text, True, COLOR_WHITE)
        self.screen.blit(name_surf, (inp_x + 8, inp_y + 7))

        # Private toggle
        priv_text = f"Private: {'YES' if self._room_private else 'NO'} (TAB to toggle)"
        priv_color = COLOR_YELLOW if self._room_private else COLOR_GRAY
        draw_text_centered(self.screen, priv_text,
                           self.font, priv_color, box_y + 140)

        # Footer
        draw_text_centered(self.screen, "ENTER: Create  |  ESC: Cancel",
                           self.font_small, COLOR_GRAY, box_y + 180)

    def _render_room_code_dialog(self):
        """Renderiza diálogo de ingreso de código de sala."""
        box_w = 400
        box_h = 180
        box_x = SCREEN_WIDTH // 2 - box_w // 2
        box_y = SCREEN_HEIGHT // 2 - box_h // 2
        pygame.draw.rect(self.screen, (20, 20, 35),
                         (box_x, box_y, box_w, box_h), border_radius=8)
        pygame.draw.rect(self.screen, COLOR_YELLOW,
                         (box_x, box_y, box_w, box_h), 2, border_radius=8)

        draw_text_centered(self.screen, "JOIN BY CODE",
                           self.font_subtitle, COLOR_YELLOW, box_y + 20)

        draw_text_centered(self.screen, "Enter 4-character room code:",
                           self.font, COLOR_WHITE, box_y + 60)

        # Code input (big, centered)
        inp_w = 160
        inp_h = 45
        inp_x = SCREEN_WIDTH // 2 - inp_w // 2
        inp_y = box_y + 90
        pygame.draw.rect(self.screen, (40, 40, 60),
                         (inp_x, inp_y, inp_w, inp_h), border_radius=4)
        pygame.draw.rect(self.screen, COLOR_WHITE,
                         (inp_x, inp_y, inp_w, inp_h), 2, border_radius=4)

        cursor = "|" if int(self._room_cursor_blink * 2) % 2 == 0 else ""
        code_text = self._room_code_input.upper() + cursor
        code_surf = self.font_subtitle.render(code_text, True, COLOR_YELLOW)
        code_rect = code_surf.get_rect(center=(SCREEN_WIDTH // 2, inp_y + inp_h // 2))
        self.screen.blit(code_surf, code_rect)

        # Footer
        draw_text_centered(self.screen, "ENTER: Join  |  ESC: Cancel",
                           self.font_small, COLOR_GRAY, box_y + 150)

    # ── CLIENT LOBBY ──

    def _update_join_lobby(self, dt):
        """Actualiza lobby del cliente: recibe estado y espera RACE_START."""
        if not self.net_client:
            return

        if not self.net_client.connected:
            self._net_error_msg = "Server disconnected"
            self._stop_online()
            self.state = STATE_MENU
            return

        # Actualizar admin state
        self._is_lobby_admin = self.net_client.is_admin
        track_list = self.net_client.get_track_list()
        if track_list:
            self._admin_track_list = track_list
            # Sincronizar selección con track actual del lobby
            lobby = self.net_client.get_lobby_state()
            if lobby:
                current_track = lobby.get("track_name", "")
                for i, t in enumerate(self._admin_track_list):
                    if t["filename"] == current_track:
                        self._admin_track_selected = i
                        break
                self._admin_bot_count = lobby.get("bot_count", 1)

        # Verificar si la carrera ha comenzado
        if self.net_client.race_started:
            self._start_online_race_as_client()

    def _render_join_lobby(self):
        """Renderiza lobby del cliente."""
        self._render_gradient_bg()

        draw_text_centered(self.screen, "LOBBY",
                           self.font_title, COLOR_YELLOW, 80)

        admin_tag = " (Admin)" if self._is_lobby_admin else ""
        draw_text_centered(self.screen,
                           f"Connected as Player {self.my_player_id + 1}{admin_tag}",
                           self.font_subtitle, COLOR_WHITE, 150)

        # Mostrar estado del lobby
        lobby = self.net_client.get_lobby_state() if self.net_client else None
        admin_pid = lobby.get("admin_player_id", 255) if lobby else 255

        if lobby:
            # Track display
            track_name = lobby['track_name']
            if self._is_lobby_admin and self._admin_track_list:
                sel = self._admin_track_selected
                display_name = self._admin_track_list[sel]["name"] if sel < len(self._admin_track_list) else track_name
                draw_text_centered(self.screen,
                                   f"< {display_name} >",
                                   self.font_subtitle, COLOR_YELLOW, 205)
                draw_text_centered(self.screen,
                                   f"({self._admin_track_list[sel]['filename']})",
                                   self.font_small, COLOR_GRAY, 235)
            else:
                draw_text_centered(self.screen, f"Track: {track_name}",
                                   self.font, COLOR_GRAY, 210)

            # Bots display
            bot_count = lobby["bot_count"]
            if self._is_lobby_admin:
                draw_text_centered(self.screen,
                                   f"Bots: < {bot_count} >",
                                   self.font, COLOR_YELLOW, 260)
            else:
                if bot_count > 0:
                    draw_text_centered(self.screen, f"Bots: {bot_count}",
                                       self.font, COLOR_GRAY, 260)

            # Player list
            y = 300
            draw_text_centered(self.screen, "Players:", self.font_subtitle,
                               COLOR_WHITE, y)
            y += 35
            for pid, name in lobby["players"]:
                tag = ""
                if pid == self.my_player_id:
                    tag += " (You)"
                if pid == admin_pid:
                    tag += " [Admin]"
                color = PLAYER_COLORS[pid] if pid < len(PLAYER_COLORS) else COLOR_WHITE
                draw_text_centered(self.screen, f"P{pid + 1}: {name}{tag}",
                                   self.font, color, y)
                y += 28

        # Track transfer progress
        progress = self.net_client.get_track_progress() if self.net_client else 0.0
        if progress > 0 and progress < 1.0:
            draw_text_centered(self.screen,
                               f"Receiving track... {int(progress * 100)}%",
                               self.font, COLOR_YELLOW, 520)

        # Footer controls
        if self._is_lobby_admin:
            draw_text_centered(self.screen,
                               "UP/DOWN: Track  |  LEFT/RIGHT: Bots  |  ENTER: Start",
                               self.font, COLOR_GREEN, SCREEN_HEIGHT - 90)
        else:
            draw_text_centered(self.screen, "Waiting for admin to start...",
                               self.font, COLOR_GRAY, SCREEN_HEIGHT - 90)
        draw_text_centered(self.screen, "ESC: Leave",
                           self.font, COLOR_GRAY, SCREEN_HEIGHT - 50)

    def _start_online_race_as_client(self):
        """Cliente: construye track local, crea Cars, entra en countdown."""
        if not self.net_client:
            return

        # Esperar a que el track data esté completo
        track_data = self.net_client.get_track_data()
        if not track_data:
            # Reintentar en el siguiente frame (no resetear race_started)
            return

        # Crear track local
        if track_data.get("format") == "tiles":
            self.track = TileTrack(track_data)
        else:
            self.track = Track(control_points=track_data["control_points"])

        # Crear autos basándose en lobby state
        self.cars = []
        lobby = self.net_client.get_lobby_state()
        sp = self.track.start_positions

        if lobby:
            for i, (pid, name) in enumerate(lobby["players"]):
                pos_idx = min(i, len(sp) - 1)
                car = Car(sp[pos_idx][0], sp[pos_idx][1], sp[pos_idx][2],
                          PLAYER_COLORS[pid % len(PLAYER_COLORS)], pid)
                car.name = name
                if pid == self.my_player_id:
                    self.player_car = car
                else:
                    car.is_remote = True
                self.cars.append(car)

            # Bots
            bot_start = len(lobby["players"])
            for b in range(lobby.get("bot_count", 0)):
                bot_idx = bot_start + b
                pos_idx = min(bot_idx, len(sp) - 1)
                bot = Car(sp[pos_idx][0], sp[pos_idx][1], sp[pos_idx][2],
                          PLAYER_COLORS[bot_idx % len(PLAYER_COLORS)],
                          100 + b)
                bot.name = f"Bot {b + 1}"
                bot.is_bot_car = True
                bot.is_remote = True  # el cliente no corre IA para bots
                self.cars.append(bot)

        if not self.player_car and self.cars:
            self.player_car = self.cars[0]

        # Sistemas
        self.collision_system = CollisionSystem(self.track)

        # Asegurar que ningún auto spawneó dentro de un muro
        for car in self.cars:
            self.collision_system.ensure_valid_spawn(car)

        # Race progress
        fl = self.track.finish_line
        fl_center = ((fl[0][0] + fl[1][0]) / 2, (fl[0][1] + fl[1][1]) / 2)
        self.race_progress = RaceProgressTracker(
            self.track.checkpoints, fl_center)
        for car in self.cars:
            self.race_progress.register_car(car.player_id)

        # Cámara
        self.camera.snap_to(self.player_car.x, self.player_car.y,
                            self.player_car.angle)

        # Power-ups
        self.powerup_items = [
            PowerUpItem(p[0], p[1]) for p in self.track.powerup_spawn_points
        ]
        self.missiles = []
        self.oil_slicks = []
        self.mines = []
        self.smart_missiles = []
        self._use_cooldown = 0.0

        # Partículas
        self.dust_particles = DustParticleSystem()
        self.skid_marks = SkidMarkSystem()

        # Timer
        self.race_timer = RaceTimer()
        self.race_timer.reset()
        self.winner = None
        self.final_times = {}

        # Countdown — resetear ambos timers (display + lógica online)
        self.countdown_timer = 0.0
        self.countdown_value = self.net_client.countdown
        self._online_countdown_timer = 0.0
        self._online_countdown_value = self.net_client.countdown

        # Resetear input replay buffer
        self._input_buffer = [None] * 128
        self._input_buffer_head = 0
        self._input_buffer_count = 0

        # Reset fixed timestep accumulator
        self._physics_accumulator = 0.0
        self._client_slowmo_on_me = False
        self._last_reconcile_seq = -1

        # Limpiar snapshots acumulados durante lobby/connecting
        # para que el primer reconcile use datos frescos de la fase RACING
        self.net_client.clear_snapshots()
        self.net_client._input_seq = 0  # Reset input sequence

        self.state = STATE_ONLINE_COUNTDOWN
        self._debug_first_reconcile = True  # DEBUG: flag para primer reconcile
        if self.player_car:
            print(f"[DEBUG-SPAWN] player_car created: "
                  f"x={self.player_car.x:.1f} y={self.player_car.y:.1f} "
                  f"rx={self.player_car.render_x:.1f} ry={self.player_car.render_y:.1f}")

    def _update_online_racing_client(self, dt):
        """Update del cliente: fixed timestep + predicción + render smoothing."""
        if not self.net_client:
            return

        # Verificar conexión
        if not self.net_client.connected:
            self._net_error_msg = "Server disconnected"
            self._stop_online()
            self.state = STATE_MENU
            return

        keys = pygame.key.get_pressed()
        self._use_cooldown = max(0, self._use_cooldown - dt)

        # ── Fixed timestep loop para predicción local ──
        # Cap: máximo 2 ticks por frame para evitar ráfagas de física acumulada
        self._physics_accumulator += dt
        ticks_this_frame = 0

        while self._physics_accumulator >= FIXED_DT and ticks_this_frame < 2:
            # 1. Input local
            if self.player_car and not self.player_car.finished:
                pending_use_pw = self.player_car.input_use_powerup
                self.player_car.reset_inputs()
                self.player_car.input_use_powerup = pending_use_pw
                if keys[pygame.K_w]:
                    self.player_car.input_accelerate = 1.0
                elif keys[pygame.K_s]:
                    self.player_car.input_accelerate = -1.0
                if keys[pygame.K_a]:
                    self.player_car.input_turn -= 1.0
                if keys[pygame.K_d]:
                    self.player_car.input_turn += 1.0
                if keys[pygame.K_SPACE]:
                    self.player_car.input_brake = True

                # Enviar input al servidor
                self.net_client.send_input(
                    self.player_car.input_accelerate,
                    self.player_car.input_turn,
                    self.player_car.input_brake,
                    self.player_car.input_use_powerup,
                )
                # Guardar input en buffer para replay en reconciliación
                self._save_input_to_buffer(
                    self.net_client._input_seq,
                    self.player_car.input_accelerate,
                    self.player_car.input_turn,
                    self.player_car.input_brake,
                    self.player_car.input_use_powerup,
                )
                # Limpiar flag de uso después de enviar (one-shot)
                self.player_car.input_use_powerup = False

                # 2. Predicción local con simulación headless (no toca render state)
                predict_dt = FIXED_DT
                if self._client_slowmo_on_me:
                    predict_dt = FIXED_DT * SLOWMO_FACTOR
                self._simulate_car_step_headless(self.player_car, predict_dt)

                # Colisión car-vs-car predictiva (evita traspaso visual)
                for other_car in self.cars:
                    if other_car is self.player_car:
                        continue
                    if self.collision_system.check_car_vs_car(self.player_car, other_car):
                        self._predict_car_vs_car_local(self.player_car, other_car)

            self._physics_accumulator -= FIXED_DT
            ticks_this_frame += 1

        # Si quedó deuda acumulada, descartar en vez de acumular
        if self._physics_accumulator >= FIXED_DT:
            self._physics_accumulator = 0.0

        # ── Fuera del fixed loop ──

        # 3A. LOCAL CAR: Reconciliar con snapshot más reciente (sin delay)
        latest = self.net_client.get_latest_snapshot()
        if latest:
            # Solo reconciliar auto local con snapshots NUEVOS (evita jitter por snapshot stale)
            if latest.seq != self._last_reconcile_seq:
                self._last_reconcile_seq = latest.seq
                self._snap_count += 1
                for car_state in latest.cars:
                    if car_state.player_id == self.my_player_id:
                        self._reconcile_local_car(car_state, latest_snapshot=latest)
                # Actualizar flag SlowMo para predicción local
                self._client_slowmo_on_me = False
                for cs in latest.cars:
                    if cs.player_id != self.my_player_id and "slowmo" in (cs.effects or []):
                        self._client_slowmo_on_me = True
                        break
            # Sincronizar objetos del mundo cada frame (no causan jitter)
            self._sync_projectiles(latest)
            self._sync_hazards(latest)
            self._sync_powerup_items(latest)
            self.race_timer.total_time = latest.race_time

        # 3B. REMOTE CARS: Interpolar con delay buffer adaptativo (server time)
        interp_delay = self.net_client.get_adaptive_delay()
        render_time = self.net_client.get_server_time_now() - interp_delay
        prev_snap, next_snap, t = self.net_client.get_snapshots_for_time(render_time)

        if prev_snap and next_snap:
            for car_state in next_snap.cars:
                if car_state.player_id == self.my_player_id:
                    continue  # skip local car
                target_car = self._find_car_by_pid(car_state.player_id)
                if target_car:
                    prev_state = self._find_car_state_in_snapshot(
                        prev_snap, car_state.player_id)
                    if prev_state:
                        self._interpolate_car_smooth(target_car, prev_state,
                                                     car_state, t)
                    else:
                        target_car.apply_net_state(car_state)
        elif next_snap:
            # No hay par → extrapolación dead-reckoning con velocidad del último snapshot
            dt_extra = render_time - next_snap.race_time
            dt_extra = max(0.0, min(dt_extra, NET_EXTRAPOLATION_MAX))
            for car_state in next_snap.cars:
                if car_state.player_id != self.my_player_id:
                    target_car = self._find_car_by_pid(car_state.player_id)
                    if target_car:
                        target_car.apply_net_state(car_state)
                        if dt_extra > 0.001:
                            target_car.x += car_state.vx * dt_extra
                            target_car.y += car_state.vy * dt_extra

        # Procesar eventos de power-up
        for event in self.net_client.pop_powerup_events():
            self._handle_remote_powerup_event(event)

        # Visual smoothing del auto local (cosmético, render → sim gradualmente)
        self._smooth_player_render(dt)

        # Net stats tracking
        if self._show_net_stats:
            self._snap_rate_timer += dt
            if self._snap_rate_timer >= 1.0:
                self._snap_rate_value = self._snap_count / self._snap_rate_timer
                self._snap_count = 0
                self._snap_rate_timer = 0.0
            self._net_stats['ping'] = self.net_client.get_ping()
            self._net_stats['snap_rate'] = self._snap_rate_value
            self._net_stats['input_seq'] = self.net_client._input_seq
            self._net_stats['interp_delay'] = self.net_client.get_adaptive_delay() * 1000

        # Partículas
        if self.dust_particles:
            for car in self.cars:
                if not car.finished:
                    self.dust_particles.emit_from_car(car)
                    self.dust_particles.emit_drift_smoke(car)
                    self.dust_particles.emit_drift_sparks(car)
                    self.skid_marks.record_from_car(car)
            self.dust_particles.update(dt)
            self.skid_marks.update(dt)

        # Cámara (sigue render position para suavidad visual)
        if self.player_car:
            self.camera.update(self.player_car.render_x, self.player_car.render_y,
                               self.player_car.render_angle, self.player_car.speed, dt)

        # Timer
        self.race_timer.update(dt)

        # Update progress
        for car in self.cars:
            self.race_progress.update(car)

        # Victoria
        all_finished = all(car.finished for car in self.cars)
        if all_finished or (self.winner and
                            self.race_timer.total_time > self.winner.finish_time + 15):
            self.state = STATE_VICTORY

    def _save_input_to_buffer(self, seq, accel, turn, brake, use_powerup=False):
        """Guarda un input enviado en el buffer circular para replay."""
        buf = self._input_buffer
        idx = self._input_buffer_head
        buf[idx] = InputRecord(seq, accel, turn, brake, use_powerup)
        self._input_buffer_head = (idx + 1) % len(buf)
        if self._input_buffer_count < len(buf):
            self._input_buffer_count += 1

    def _get_unacked_inputs(self, server_seq):
        """Retorna inputs no confirmados (seq > server_seq) en orden cronológico.

        Usa half-space technique para uint16 wrapping:
        diff = (record.seq - server_seq) & 0xFFFF; si 0 < diff < 32768 → posterior.
        """
        result = []
        buf = self._input_buffer
        buf_len = len(buf)
        count = self._input_buffer_count
        # Start from oldest entry in the circular buffer
        start = (self._input_buffer_head - count) % buf_len
        for i in range(count):
            record = buf[(start + i) % buf_len]
            if record is None:
                continue
            diff = (record.seq - server_seq) & 0xFFFF
            if 0 < diff < 32768:
                result.append(record)
        return result

    def _reconcile_local_car(self, server_state, latest_snapshot=None):
        """Reconciliación autoritativa: overwrite + replay determinístico.

        1. Guarda render state
        2. Overwrite completo de sim state desde servidor
        3. Teleport check (error extremo → snap render también)
        4. Replay inputs no confirmados
        5. Restaura render state (visual smoothing lo moverá gradualmente)
        """
        if not self.player_car:
            return
        car = self.player_car

        # ── DEBUG: primer reconcile ──
        if getattr(self, '_debug_first_reconcile', False):
            self._debug_first_reconcile = False
            print(f"[DEBUG-RECONCILE-1st] ANTES: "
                  f"local x={car.x:.1f} y={car.y:.1f} "
                  f"rx={car.render_x:.1f} ry={car.render_y:.1f} "
                  f"spd={car.speed:.1f}")
            print(f"[DEBUG-RECONCILE-1st] SERVER: "
                  f"x={server_state.x:.1f} y={server_state.y:.1f} "
                  f"vx={server_state.vx:.1f} vy={server_state.vy:.1f} "
                  f"angle={server_state.angle:.1f} "
                  f"last_input_seq={server_state.last_input_seq}")

        # ── 1. GUARDAR render state ──
        saved_rx = car.render_x
        saved_ry = car.render_y
        saved_ra = car.render_angle

        # ── 2. OVERWRITE COMPLETO de estado sim desde servidor ──
        car.x = server_state.x
        car.y = server_state.y
        car.velocity.x = server_state.vx
        car.velocity.y = server_state.vy
        car.angle = server_state.angle

        # Drift completo
        car.is_drifting = server_state.is_drifting
        car.is_countersteer = server_state.is_countersteer
        car.drift_charge = server_state.drift_charge
        car.drift_level = server_state.drift_level
        car.drift_time = server_state.drift_time
        car.drift_direction = server_state.drift_direction
        car.drift_mt_boost_timer = server_state.drift_mt_boost_timer

        # Effects con duraciones exactas del servidor
        if hasattr(server_state, 'effect_durations') and server_state.effect_durations:
            car.active_effects = {}
            for ename in server_state.effects:
                car.active_effects[ename] = server_state.effect_durations.get(ename, 1.0)
        else:
            car.active_effects = {}
            for ename in server_state.effects:
                car.active_effects[ename] = 1.0
        car.update_effects(0)  # recalc multipliers sin tickear

        # Discretos
        car.laps = server_state.laps
        car.next_checkpoint_index = server_state.next_checkpoint_index
        car.held_powerup = server_state.held_powerup
        car.finished = server_state.finished
        car.finish_time = server_state.finish_time

        if car.finished and self.winner is None:
            self.winner = car
            self.final_times[car.name] = car.finish_time

        # ── 3. TELEPORT check (error extremo, skip replay) ──
        dx = saved_rx - car.x
        dy = saved_ry - car.y
        pos_error = math.sqrt(dx * dx + dy * dy)
        if pos_error > NET_TELEPORT_THRESHOLD:
            car.render_x = car.x
            car.render_y = car.y
            car.render_angle = car.angle
            car.update_collision_mask()
            return

        # ── 4. REPLAY inputs no confirmados ──
        unacked = self._get_unacked_inputs(server_state.last_input_seq)

        # Determinar dt de replay (SlowMo correction)
        replay_dt = FIXED_DT
        if latest_snapshot:
            for cs in latest_snapshot.cars:
                if cs.player_id != self.my_player_id and "slowmo" in (cs.effects or []):
                    replay_dt = FIXED_DT * SLOWMO_FACTOR
                    break

        for inp in unacked:
            car.reset_inputs()
            car.input_accelerate = inp.accel
            car.input_turn = inp.turn
            car.input_brake = inp.brake
            car.input_use_powerup = False  # NUNCA replay powerup activation
            self._simulate_car_step_headless(car, replay_dt)

            # Car-vs-car durante replay para que predicción coincida con servidor
            for other_car in self.cars:
                if other_car is car:
                    continue
                if self.collision_system.check_car_vs_car(car, other_car):
                    self._predict_car_vs_car_local(car, other_car)

        # ── 5. RESTAURAR render state ──
        car.render_x = saved_rx
        car.render_y = saved_ry
        car.render_angle = saved_ra
        # Visual smoothing moverá render → sim gradualmente

        # ── Stats para debug overlay ──
        if self._show_net_stats:
            post_error = math.sqrt(
                (car.x - saved_rx) ** 2 + (car.y - saved_ry) ** 2)
            self._net_stats['unacked'] = len(unacked)
            self._net_stats['reconcile_error'] = post_error
            self._net_stats['last_server_seq'] = server_state.last_input_seq
            if latest_snapshot:
                self._net_stats['server_tick'] = latest_snapshot.server_tick

    def _interpolate_car_smooth(self, car, prev_state, curr_state, t):
        """Interpola un auto remoto entre dos estados usando t pre-computado.

        t es la fracción de interpolación [0..1] calculada desde server race_time,
        haciéndola inmune al jitter de recv_time.
        """
        # Smoothstep para ease-in/ease-out
        t_smooth = t * t * (3.0 - 2.0 * t)

        # Lerp posición
        car.x = prev_state.x + (curr_state.x - prev_state.x) * t_smooth
        car.y = prev_state.y + (curr_state.y - prev_state.y) * t_smooth
        car.velocity.x = curr_state.vx
        car.velocity.y = curr_state.vy

        # Angle lerp (camino corto)
        a1 = prev_state.angle % 360
        a2 = curr_state.angle % 360
        diff = (a2 - a1 + 180) % 360 - 180
        car.angle = (a1 + diff * t_smooth) % 360

        # Datos discretos: snap al más reciente
        car.laps = curr_state.laps
        car.next_checkpoint_index = curr_state.next_checkpoint_index
        car.held_powerup = curr_state.held_powerup
        car.is_drifting = curr_state.is_drifting
        car.drift_charge = curr_state.drift_charge
        car.drift_level = curr_state.drift_level
        car.finished = curr_state.finished
        car.finish_time = curr_state.finish_time

        # Effects
        for ename in curr_state.effects:
            if ename not in car.active_effects:
                car.active_effects[ename] = 1.0
        to_remove = [k for k in car.active_effects if k not in curr_state.effects]
        for k in to_remove:
            del car.active_effects[k]

        if car.finished and car.finish_time > 0:
            self.final_times[car.name] = car.finish_time
            if self.winner is None:
                self.winner = car

        car.update_sprite()

    def _find_car_by_pid(self, player_id):
        """Busca un auto por player_id."""
        for car in self.cars:
            if car.player_id == player_id:
                return car
        return None

    def _find_car_state_in_snapshot(self, snapshot, player_id):
        """Busca estado de un auto en un snapshot."""
        for cs in snapshot.cars:
            if cs.player_id == player_id:
                return cs
        return None

    def _sync_projectiles(self, snapshot):
        """Sincroniza misiles y smart_missiles desde snapshot."""
        from networking.protocol import PROJ_MISSILE, PROJ_SMART_MISSILE

        # Recrear listas desde snapshot
        new_missiles = []
        new_smart = []
        for proj in snapshot.projectiles:
            if proj.proj_type == PROJ_MISSILE:
                m = Missile(proj.x, proj.y, proj.angle, proj.owner_id)
                new_missiles.append(m)
            elif proj.proj_type == PROJ_SMART_MISSILE:
                target = self._find_car_by_pid(proj.target_pid)
                sm = SmartMissile(proj.x, proj.y, proj.angle,
                                  proj.owner_id, target)
                new_smart.append(sm)

        self.missiles = new_missiles
        self.smart_missiles = new_smart

    def _sync_hazards(self, snapshot):
        """Sincroniza oil slicks y mines desde snapshot."""
        from networking.protocol import HAZARD_OIL, HAZARD_MINE

        new_oils = []
        new_mines = []
        for h in snapshot.hazards:
            if h.hazard_type == HAZARD_OIL:
                o = OilSlick(h.x, h.y, h.owner_id)
                o.lifetime = h.lifetime
                new_oils.append(o)
            elif h.hazard_type == HAZARD_MINE:
                m = Mine(h.x, h.y, h.owner_id)
                m.lifetime = h.lifetime
                new_mines.append(m)

        self.oil_slicks = new_oils
        self.mines = new_mines

    def _sync_powerup_items(self, snapshot):
        """Sincroniza estado de los pickups de power-up."""
        for item_state in snapshot.items:
            idx = item_state.index
            if idx < len(self.powerup_items):
                item = self.powerup_items[idx]
                if item_state.active and not item.active:
                    item.active = True
                    item.power_type = None
                elif not item_state.active and item.active:
                    item.active = False
                    item.respawn_timer = item_state.respawn_timer

    def _handle_remote_powerup_event(self, event):
        """Procesa evento de power-up recibido del servidor."""
        from networking.protocol import PW_EVENT_COLLECT
        if event["event_type"] == PW_EVENT_COLLECT:
            pid = event["player_id"]
            ptype = event["powerup_type"]
            idx = event["item_index"]
            car = self._find_car_by_pid(pid)
            if car and ptype:
                car.held_powerup = ptype
                if idx < len(self.powerup_items):
                    self.powerup_items[idx].collect_with_type(ptype)

    # ──────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────

    def _get_player_position(self) -> int:
        """Calcula la posición actual del jugador en la carrera."""
        if self.race_progress:
            return self.race_progress.get_position(self.player_car.player_id)
        return 1
