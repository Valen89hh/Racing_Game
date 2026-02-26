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
    COLOR_PROGRESS_BAR, COLOR_PROGRESS_BG,
    PLAYER_COLORS, TOTAL_LAPS, DEBUG_CHECKPOINTS,
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


class Game:
    """Clase principal que orquesta todo el juego."""

    def __init__(self):
        pygame.init()
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
                    elif self.state == STATE_TRACK_SELECT:
                        self.state = STATE_MENU
                    elif self.state == STATE_TRAINING:
                        self._cancel_training()
                        self.state = STATE_TRACK_SELECT
                    else:
                        self.running = False

                elif event.key == pygame.K_e:
                    if self.state == STATE_MENU:
                        self._open_editor()
                    elif self.state == STATE_TRACK_SELECT:
                        self._edit_selected_track()

                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER,
                                   pygame.K_SPACE):
                    if self.state == STATE_MENU:
                        self._open_track_select()
                    elif self.state == STATE_TRACK_SELECT:
                        self._start_selected_track()
                    elif self.state == STATE_VICTORY:
                        if self.return_to_editor:
                            self._open_editor_with_points()
                        else:
                            self.state = STATE_MENU
                    elif self.state == STATE_TRAINING:
                        if self._train_status == "idle":
                            self._launch_training()
                        elif self._train_status in ("done", "error"):
                            self.state = STATE_TRACK_SELECT

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

            # Click izquierdo del mouse para activar power-up
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.state == STATE_RACING:
                    if (self.player_car and self.player_car.held_powerup is not None
                            and self._use_cooldown <= 0):
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

            old_x, old_y = car.x, car.y

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

            # Física (con per-tile friction si el track lo soporta)
            self.physics.update(car, car_dt, self.track)
            car.update_sprite()

            # Colisiones con bordes
            if self.collision_system.check_track_collision(car):
                if car.is_shielded:
                    car.break_shield()
                    normal = self.collision_system.resolve_track_collision(car)
                    car.speed *= 0.7
                    car.update_sprite()
                elif car.has_bounce:
                    # Rebote mejorado: conserva más velocidad
                    normal = self.collision_system.resolve_track_collision(car)
                    self.physics.apply_collision_response(car, normal)
                    car.speed *= 1.3  # recuperar velocidad tras el rebote
                    car.update_sprite()
                else:
                    normal = self.collision_system.resolve_track_collision(car)
                    self.physics.apply_collision_response(car, normal)
                    car.update_sprite()
            else:
                self.physics.clear_wall_contact(car)

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
        self.camera.update_shake(
            self.player_car.get_lateral_speed(),
            self.player_car.is_drifting, dt
        )

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
            if cam.is_visible(car.x, car.y, 60):
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
            mx, my = self.track.get_minimap_pos(car.x, car.y)
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

    def _render_victory(self):
        """Renderiza la pantalla de victoria."""
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        if self.winner and self.winner.player_id == 0:
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

        draw_text_centered(self.screen, "UP/DOWN select | ENTER race | E edit | T train AI | ESC back",
                           self.font, COLOR_GRAY, SCREEN_HEIGHT - 50)

    # ──────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────

    def _get_player_position(self) -> int:
        """Calcula la posición actual del jugador en la carrera."""
        if self.race_progress:
            return self.race_progress.get_position(self.player_car.player_id)
        return 1
