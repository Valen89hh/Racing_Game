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

import sys
import random
import math
import pygame

from settings import (
    SCREEN_WIDTH, SCREEN_HEIGHT, FPS, TITLE,
    WORLD_WIDTH, WORLD_HEIGHT,
    COLOR_BLACK, COLOR_WHITE, COLOR_YELLOW, COLOR_GREEN,
    COLOR_RED, COLOR_GRAY, COLOR_DARK_GRAY, COLOR_ORANGE, COLOR_BLUE,
    STATE_MENU, STATE_COUNTDOWN, STATE_RACING, STATE_VICTORY,
    STATE_EDITOR, STATE_TRACK_SELECT,
    PLAYER_COLORS, TOTAL_LAPS, HUD_FONT_SIZE, HUD_TITLE_FONT_SIZE,
    HUD_SUBTITLE_FONT_SIZE, HUD_MARGIN, MINIMAP_MARGIN, MINIMAP_CAR_DOT,
    BOT_ACCELERATION, BOT_MAX_SPEED, BOT_TURN_SPEED,
    POWERUP_BOOST, POWERUP_SHIELD, POWERUP_MISSILE, POWERUP_OIL,
    POWERUP_COLORS,
    BOOST_DURATION, SHIELD_DURATION,
    MISSILE_SLOW_DURATION, OIL_EFFECT_DURATION,
)
from entities.car import Car
from entities.track import Track
from entities.powerup import PowerUpItem, Missile, OilSlick
from entities.particles import DustParticleSystem
from systems.physics import PhysicsSystem
from systems.collision import CollisionSystem
from systems.input_handler import InputHandler
from systems.ai import AISystem
from systems.camera import Camera
from utils.timer import RaceTimer
from utils.helpers import draw_text_centered
from editor import TileEditor
from tile_track import TileTrack
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
        self.camera = Camera()
        self.race_timer = RaceTimer()

        # Power-ups
        self.powerup_items = []    # pickups en la pista
        self.missiles = []         # misiles activos
        self.oil_slicks = []       # manchas de aceite activas
        self._use_cooldown = 0.0   # cooldown para evitar doble uso
        self.dust_particles = None # sistema de partículas de polvo

        # Resultado
        self.winner = None
        self.final_times = {}

        # Editor y selección de pista
        self.editor = None
        self.track_list = []
        self.track_selected = 0
        self.return_to_editor = False  # para volver al editor tras test race

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

                elif self.state == STATE_TRACK_SELECT:
                    if event.key == pygame.K_UP:
                        self.track_selected = max(0, self.track_selected - 1)
                    elif event.key == pygame.K_DOWN:
                        self.track_selected = min(
                            len(self.track_list) - 1, self.track_selected + 1)

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
        self.ai_system = AISystem(self.track)
        self.ai_system.register_bot(bot_car)

        # Cámara: snap instantáneo al jugador (con ángulo inicial)
        self.camera.snap_to(self.player_car.x, self.player_car.y,
                            self.player_car.angle)

        # Power-ups: crear pickups en los puntos de spawn
        self.powerup_items = [
            PowerUpItem(p[0], p[1]) for p in self.track.powerup_spawn_points
        ]
        self.missiles = []
        self.oil_slicks = []
        self._use_cooldown = 0.0

        # Partículas de polvo
        self.dust_particles = DustParticleSystem()

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

        # ── Actualizar autos ──
        for car in self.cars:
            if car.finished:
                continue

            old_x, old_y = car.x, car.y

            # Input
            if car.player_id == 0:
                self.input_handler.update(car, keys)
            else:
                self.ai_system.update(car, dt, self.cars)

            # Efectos de power-ups activos
            car.update_effects(dt)

            # Física (con per-tile friction si el track lo soporta)
            self.physics.update(car, dt, self.track)
            car.update_sprite()

            # Colisiones con bordes
            if self.collision_system.check_track_collision(car):
                if car.is_shielded:
                    # El escudo absorbe el impacto
                    car.break_shield()
                    normal = self.collision_system.resolve_track_collision(car)
                    car.speed *= 0.7
                    car.update_sprite()
                else:
                    normal = self.collision_system.resolve_track_collision(car)
                    self.physics.apply_collision_response(car, normal)
                    car.update_sprite()
            else:
                self.physics.clear_wall_contact(car)

            # Checkpoints y vueltas
            self.collision_system.update_checkpoints(car)
            if self.collision_system.check_lap_completion(car, old_x, old_y):
                if car == self.player_car:
                    self.race_timer.complete_lap()
                if car.laps >= TOTAL_LAPS:
                    car.finished = True
                    car.finish_time = self.race_timer.total_time
                    self.final_times[car.name] = car.finish_time
                    if self.winner is None:
                        self.winner = car

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

        # ── Recoger power-ups ──
        for car in self.cars:
            for item in self.powerup_items:
                if self.collision_system.check_car_vs_powerup(car, item):
                    car.held_powerup = item.collect()

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

        # ── Partículas de polvo ──
        if self.dust_particles:
            for car in self.cars:
                if not car.finished:
                    self.dust_particles.emit_from_car(car)
            self.dust_particles.update(dt)

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
            # Disparar misil desde la posición frontal del auto
            fx, fy = car.get_forward_vector()
            mx = car.x + fx * 30
            my = car.y + fy * 30
            self.missiles.append(Missile(mx, my, car.angle, car.player_id))

        elif ptype == POWERUP_OIL:
            # Dejar mancha detrás del auto
            fx, fy = car.get_forward_vector()
            ox = car.x - fx * 30
            oy = car.y - fy * 30
            self.oil_slicks.append(OilSlick(ox, oy, car.player_id))

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
            "L-SHIFT -  Use Power-Up",
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
            (POWERUP_BOOST,   "Boost   - Speed increase"),
            (POWERUP_SHIELD,  "Shield  - Absorbs one hit"),
            (POWERUP_MISSILE, "Missile - Slows enemy"),
            (POWERUP_OIL,     "Oil     - Creates slippery hazard"),
        ]
        for i, (ptype, desc) in enumerate(powerup_info):
            color = POWERUP_COLORS[ptype]
            py = y_pw + 30 + i * 26
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

        # Manchas de aceite (se dibujan sobre la pista, bajo los autos)
        for oil in self.oil_slicks:
            if cam.is_visible(oil.x, oil.y, 50):
                oil.draw(self.screen, cam)

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
            lbl = self.font_small.render("[SHIFT]", True, (80, 80, 80))
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

        # Dibujar power-ups activos
        for item in self.powerup_items:
            if item.active:
                mx, my = self.track.get_minimap_pos(item.x, item.y)
                color = POWERUP_COLORS.get(item.power_type, (200, 200, 200))
                pygame.draw.circle(mm, color, (mx, my), 2)

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

        sorted_cars = sorted(
            self.cars, key=lambda c: c.finish_time if c.finished else 9999
        )
        for i, car in enumerate(sorted_cars):
            if car.finished:
                time_str = RaceTimer.format_time(car.finish_time)
                text = f"{i + 1}. {car.name} - {time_str}"
            else:
                text = f"{i + 1}. {car.name} - DNF"

            color = COLOR_YELLOW if car == self.winner else COLOR_WHITE
            draw_text_centered(self.screen, text, self.font_subtitle,
                               color, y_pos)
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

        draw_text_centered(self.screen, "UP/DOWN select | ENTER race | E edit | ESC back",
                           self.font, COLOR_GRAY, SCREEN_HEIGHT - 50)

    # ──────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────

    def _get_player_position(self) -> int:
        """Calcula la posición actual del jugador en la carrera."""
        player = self.player_car
        position = 1
        for car in self.cars:
            if car == player:
                continue
            if car.laps > player.laps:
                position += 1
            elif car.laps == player.laps:
                if car.last_checkpoint > player.last_checkpoint:
                    position += 1
        return position
