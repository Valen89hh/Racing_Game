"""
car.py - Entidad del auto de carreras.

Define la clase Car que representa tanto al jugador como a los bots.
La clase es agnóstica al input: recibe comandos de aceleración/giro
y delega la física al sistema de física.

Preparado para multiplayer: cada instancia de Car puede ser controlada
por un jugador humano o por la IA.

Soporta power-ups: el auto puede llevar un power-up en inventario
y tener efectos activos que modifican sus propiedades físicas.
"""

import pygame
import math

from settings import (
    CAR_WIDTH, CAR_HEIGHT, CAR_MAX_SPEED, CAR_ACCELERATION,
    CAR_BRAKE_FORCE, CAR_FRICTION, CAR_TURN_SPEED, CAR_TURN_SPEED_MIN,
    CAR_DRIFT_FACTOR, CAR_REVERSE_MAX_SPEED, TOTAL_LAPS,
    BOOST_SPEED_MULT, BOOST_ACCEL_MULT,
    OIL_FRICTION_MULT, OIL_TURN_MULT,
    MISSILE_SLOW_FACTOR,
    MINE_SLOW_FACTOR, EMP_SLOW_FACTOR, SLOWMO_FACTOR,
    POWERUP_COLORS, POWERUP_MYSTERY_COLOR, COLOR_WHITE,
    CAR_SPRITES, SPRITE_SCALE, SPRITE_FRAME_SIZE,
    DRIFT_LEVEL_THRESHOLDS, DRIFT_LEVEL_COLORS,
    DRIFT_BAR_WIDTH, DRIFT_BAR_HEIGHT, DRIFT_BAR_OFFSET_Y,
    SKID_MARK_WHEEL_OFFSET,
)
from utils.helpers import create_car_surface, angle_to_vector
from utils.sprites import load_car_frames


class Car:
    """
    Representa un vehículo en el juego.

    Atributos principales:
        x, y: posición del centro del auto.
        angle: ángulo de orientación en grados (0° = arriba).
        speed: velocidad actual (positiva = avance, negativa = reversa).
        laps: vueltas completadas.
        held_powerup: power-up en inventario (None si vacío).
        active_effects: dict de efectos activos {nombre: tiempo_restante}.
    """

    def __init__(self, x: float, y: float, angle: float,
                 color: tuple[int, int, int], player_id: int = 0):
        # Posición y orientación
        self.x = x
        self.y = y
        self.angle = angle
        self.velocity = pygame.math.Vector2(0.0, 0.0)

        # Render state (separado de sim para suavizado visual en online)
        self.render_x = x
        self.render_y = y
        self.render_angle = angle

        # Identificador
        self.player_id = player_id
        self.color = color
        self.name = f"Player {player_id + 1}" if player_id == 0 else f"Bot {player_id}"

        # Propiedades físicas base
        self.max_speed = CAR_MAX_SPEED
        self.acceleration = CAR_ACCELERATION
        self.brake_force = CAR_BRAKE_FORCE
        self.friction = CAR_FRICTION
        self.turn_speed = CAR_TURN_SPEED
        self.turn_speed_min = CAR_TURN_SPEED_MIN
        self.drift_factor = CAR_DRIFT_FACTOR
        self.reverse_max_speed = CAR_REVERSE_MAX_SPEED

        # Multiplicadores de efectos (modificados por power-ups)
        self.speed_multiplier = 1.0
        self.accel_multiplier = 1.0
        self.friction_multiplier = 1.0
        self.turn_multiplier = 1.0

        # Comandos de input (se actualizan cada frame)
        self.input_accelerate = 0.0
        self.input_turn = 0.0
        self.input_brake = False
        self.input_use_powerup = False

        # Estado de carrera
        self.laps = 0
        self.finished = False
        self.finish_time = 0.0
        self.next_checkpoint_index = 0

        # Drift / derrape
        self.is_drifting = False   # flag activo durante handbrake drift
        self.drift_time = 0.0     # tiempo acumulado en drift actual
        self.drift_charge = 0.0   # carga de mini-turbo (0.0 - 1.0)
        self.drift_level = 0      # nivel de mini-turbo (0-3)
        self.drift_mt_boost_timer = 0.0  # tiempo restante de boost post-drift
        self.drift_direction = 0  # dirección del drift: -1 izq, +1 der, 0 sin asignar
        self.is_countersteer = False  # True cuando contra-gira durante drift

        # Colisión con pared (usado por physics.py)
        self._wall_normal = None

        # Networking flags
        self.is_remote = False       # True si es controlado por un cliente remoto
        self.is_bot_car = False      # True si es un bot en modo online

        # Power-ups
        self.held_powerup = None           # tipo de power-up en inventario
        self.is_shielded = False           # si el escudo está activo
        self.has_magnet = False            # imán de checkpoints activo
        self.has_slowmo = False            # ralentización temporal activa
        self.has_bounce = False            # rebote mejorado activo
        self.has_autopilot = False         # piloto automático activo
        self.is_spinning = False           # spin por mina
        self.active_effects = {}           # {effect_name: seconds_remaining}

        # Sprite (pixel art, frame 0 = apuntando arriba)
        self.width = CAR_WIDTH
        self.height = CAR_HEIGHT
        sprite_file = CAR_SPRITES.get(player_id, "player_blue.png")
        frames = load_car_frames(sprite_file, SPRITE_FRAME_SIZE, SPRITE_SCALE)
        self.original_surface = frames[0]
        self.surface = self.original_surface
        self.rect = self.surface.get_rect(center=(self.x, self.y))
        self.mask = pygame.mask.from_surface(self.surface)

    # ────────────────────────────────────────────
    # PROPIEDADES EFECTIVAS (base * multiplicador)
    # ────────────────────────────────────────────

    @property
    def effective_max_speed(self) -> float:
        return self.max_speed * self.speed_multiplier

    @property
    def effective_acceleration(self) -> float:
        return self.acceleration * self.accel_multiplier

    @property
    def effective_friction(self) -> float:
        return self.friction * self.friction_multiplier

    @property
    def effective_turn_speed(self) -> float:
        return self.turn_speed * self.turn_multiplier

    # ────────────────────────────────────────────
    # POWER-UP EFFECTS
    # ────────────────────────────────────────────

    def apply_effect(self, effect_name: str, duration: float):
        """
        Aplica un efecto temporal al auto.

        Args:
            effect_name: nombre del efecto ("boost", "oil_slow", "missile_slow").
            duration: duración en segundos.
        """
        self.active_effects[effect_name] = duration

    def update_effects(self, dt: float):
        """
        Actualiza los timers de los efectos activos y recalcula multiplicadores.

        Args:
            dt: delta time en segundos.
        """
        # Reducir timers y limpiar expirados
        expired = []
        for name in self.active_effects:
            self.active_effects[name] -= dt
            if self.active_effects[name] <= 0:
                expired.append(name)
        for name in expired:
            del self.active_effects[name]

        # Recalcular multiplicadores basándose en efectos activos
        self.speed_multiplier = 1.0
        self.accel_multiplier = 1.0
        self.friction_multiplier = 1.0
        self.turn_multiplier = 1.0
        self.is_shielded = False
        self.has_magnet = False
        self.has_slowmo = False
        self.has_bounce = False
        self.has_autopilot = False
        self.is_spinning = False

        if "boost" in self.active_effects:
            self.speed_multiplier = BOOST_SPEED_MULT
            self.accel_multiplier = BOOST_ACCEL_MULT

        if "shield" in self.active_effects:
            self.is_shielded = True

        if "oil_slow" in self.active_effects:
            self.friction_multiplier = OIL_FRICTION_MULT
            self.turn_multiplier = OIL_TURN_MULT

        if "missile_slow" in self.active_effects:
            self.speed_multiplier = min(self.speed_multiplier, MISSILE_SLOW_FACTOR)

        if "mine_spin" in self.active_effects:
            self.speed_multiplier = min(self.speed_multiplier, MINE_SLOW_FACTOR)
            self.turn_multiplier = 0.0  # no puede girar durante el spin
            self.is_spinning = True
            self.angle += 720 * dt      # gira 2 vueltas/segundo

        if "emp_slow" in self.active_effects:
            self.speed_multiplier = min(self.speed_multiplier, EMP_SLOW_FACTOR)

        if "magnet" in self.active_effects:
            self.has_magnet = True

        if "slowmo" in self.active_effects:
            self.has_slowmo = True

        if "bounce" in self.active_effects:
            self.has_bounce = True

        if "autopilot" in self.active_effects:
            self.has_autopilot = True

    def break_shield(self):
        """Rompe el escudo activo."""
        if "shield" in self.active_effects:
            del self.active_effects["shield"]
            self.is_shielded = False

    # ────────────────────────────────────────────
    # DRIFT HELPERS
    # ────────────────────────────────────────────

    def update_drift_level(self):
        """Calcula el nivel de mini-turbo (0-3) basado en drift_charge."""
        level = 0
        for i, threshold in enumerate(DRIFT_LEVEL_THRESHOLDS):
            if self.drift_charge >= threshold:
                level = i + 1
        self.drift_level = level

    def get_rear_wheel_positions(self) -> list[tuple[float, float]]:
        """Retorna las posiciones de las ruedas traseras en world coords."""
        rad = math.radians(self.angle)
        # Vector "detrás" del auto
        behind_x = -math.sin(rad)
        behind_y = math.cos(rad)
        # Vector lateral
        lat_x = math.cos(rad)
        lat_y = math.sin(rad)
        # Offset hacia atrás desde el centro
        back_dist = self.height * 0.35
        bx = self.x + behind_x * back_dist
        by = self.y + behind_y * back_dist
        # Dos ruedas: izquierda y derecha
        off = SKID_MARK_WHEEL_OFFSET
        return [
            (bx - lat_x * off, by - lat_y * off),
            (bx + lat_x * off, by + lat_y * off),
        ]

    # ────────────────────────────────────────────
    # SPRITE Y DIBUJO
    # ────────────────────────────────────────────

    def update_collision_mask(self):
        """Actualiza surface/rect/mask para colisión. NO toca render state."""
        self.surface = pygame.transform.rotate(
            self.original_surface, -self.angle
        )
        self.rect = self.surface.get_rect(center=(self.x, self.y))
        self.mask = pygame.mask.from_surface(self.surface)

    def sync_render_to_sim(self):
        """Snap render → sim. Para offline, remotos, setup inicial."""
        self.render_x = self.x
        self.render_y = self.y
        self.render_angle = self.angle

    def update_sprite(self):
        """Collision mask + render sync. Usado por offline/server/remotos."""
        self.update_collision_mask()
        self.sync_render_to_sim()

    def get_forward_vector(self) -> tuple[float, float]:
        """Retorna el vector de dirección frontal del auto."""
        return angle_to_vector(self.angle)

    @property
    def speed(self) -> float:
        """Velocidad proyectada sobre el forward vector (con signo)."""
        fx, fy = self.get_forward_vector()
        fwd = pygame.math.Vector2(fx, fy)
        return self.velocity.dot(fwd)

    @speed.setter
    def speed(self, value: float):
        """Escala velocity para que la componente forward sea `value`."""
        current = self.speed
        if abs(current) < 0.1:
            # Si velocity es ~0, setear directamente en dirección forward
            fx, fy = self.get_forward_vector()
            self.velocity = pygame.math.Vector2(fx * value, fy * value)
        else:
            self.velocity *= (value / current)

    def get_lateral_speed(self) -> float:
        """Magnitud del componente lateral de velocity (perpendicular a forward)."""
        fx, fy = self.get_forward_vector()
        fwd = pygame.math.Vector2(fx, fy)
        forward_proj = fwd * self.velocity.dot(fwd)
        lateral = self.velocity - forward_proj
        return lateral.length()

    def get_corners(self) -> list[tuple[float, float]]:
        """Calcula las esquinas del auto en coordenadas del mundo."""
        rad = math.radians(self.angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        hw = self.width / 2
        hh = self.height / 2
        corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
        return [
            (cx * cos_a - cy * sin_a + self.x,
             cx * sin_a + cy * cos_a + self.y)
            for cx, cy in corners
        ]

    def reset_inputs(self):
        """Resetea los comandos de input a neutral."""
        self.input_accelerate = 0.0
        self.input_turn = 0.0
        self.input_brake = False
        self.input_use_powerup = False

    def draw(self, surface: pygame.Surface, camera):
        """Dibuja el auto en pantalla usando el sprite pixel art rotado."""
        sx, sy = camera.world_to_screen(self.render_x, self.render_y)

        # Rotar sprite según ángulo relativo a la cámara
        screen_ang = camera.screen_angle(self.render_angle)
        rotated = pygame.transform.rotate(self.original_surface, -screen_ang)
        rect = rotated.get_rect(center=(int(sx), int(sy)))
        surface.blit(rotated, rect)

        # Efecto visual del escudo: círculo azul semitransparente
        if self.is_shielded:
            shield_surf = pygame.Surface((60, 60), pygame.SRCALPHA)
            pygame.draw.circle(shield_surf, (60, 140, 255, 80), (30, 30), 28)
            pygame.draw.circle(shield_surf, (100, 180, 255, 150), (30, 30), 28, 2)
            surface.blit(shield_surf, (int(sx) - 30, int(sy) - 30))

        # Barra de carga de mini-turbo durante drift
        if self.is_drifting and self.drift_charge > 0.01:
            bar_w = DRIFT_BAR_WIDTH
            bar_h = DRIFT_BAR_HEIGHT
            bar_x = int(sx) - bar_w // 2
            bar_y = int(sy) + DRIFT_BAR_OFFSET_Y
            # Surface temporal con alpha para el fondo
            bar_surf = pygame.Surface((bar_w + 2, bar_h + 2), pygame.SRCALPHA)
            bar_surf.fill((20, 20, 20, 180))
            surface.blit(bar_surf, (bar_x - 1, bar_y - 1))
            # Color de la barra según nivel
            if self.drift_level > 0:
                color = DRIFT_LEVEL_COLORS[min(self.drift_level - 1, 2)]
            else:
                color = (180, 180, 180)  # gris mientras carga al nivel 1
            fill_w = int(bar_w * min(self.drift_charge, 1.0))
            if fill_w > 0:
                pygame.draw.rect(surface, color,
                                 (bar_x, bar_y, fill_w, bar_h))

        # Efecto visual de mini-turbo boost (speed lines tras soltar drift)
        if self.drift_mt_boost_timer > 0:
            t = self.drift_mt_boost_timer / 0.6  # normalizado 0-1
            rad_scr = math.radians(screen_ang)
            behind_x = -math.sin(rad_scr)
            behind_y = math.cos(rad_scr)
            lat_x = math.cos(rad_scr)
            lat_y = math.sin(rad_scr)
            # Color según el último nivel alcanzado (usar nivel guardado o default)
            mt_color = DRIFT_LEVEL_COLORS[min(max(self._last_drift_level - 1, 0), 2)] if hasattr(self, '_last_drift_level') and self._last_drift_level > 0 else (80, 160, 255)
            alpha = int(200 * t)
            # Dibujar varias líneas de velocidad detrás del auto
            for i in range(5):
                offset_lat = (i - 2) * 6.0
                line_len = 14.0 + i * 4.0
                start_x = int(sx + behind_x * 18 + lat_x * offset_lat)
                start_y = int(sy + behind_y * 18 + lat_y * offset_lat)
                end_x = int(start_x + behind_x * line_len * t)
                end_y = int(start_y + behind_y * line_len * t)
                line_surf = pygame.Surface((abs(end_x - start_x) + 4, abs(end_y - start_y) + 4), pygame.SRCALPHA)
                # Dibujar directamente con alpha
                col = (*mt_color, alpha)
                ox = min(start_x, end_x) - 2
                oy = min(start_y, end_y) - 2
                pygame.draw.line(line_surf, col,
                                 (start_x - ox, start_y - oy),
                                 (end_x - ox, end_y - oy), 2)
                surface.blit(line_surf, (ox, oy))

        # Efecto visual del boost: llama detrás del auto
        if "boost" in self.active_effects:
            rad_scr = math.radians(screen_ang)
            behind_x = -math.sin(rad_scr)
            behind_y = math.cos(rad_scr)
            flame_x = int(sx + behind_x * 24)
            flame_y = int(sy + behind_y * 24)
            pygame.draw.circle(surface, (255, 160, 30), (flame_x, flame_y), 6)
            flame2_x = int(sx + behind_x * 28)
            flame2_y = int(sy + behind_y * 28)
            pygame.draw.circle(surface, (255, 255, 100), (flame2_x, flame2_y), 3)

    def draw_powerup_indicator(self, surface: pygame.Surface, camera):
        """Dibuja un indicador sobre el auto mostrando qué power-up lleva."""
        if self.held_powerup is None:
            return

        sx, sy = camera.world_to_screen(self.render_x, self.render_y)
        ix = int(sx)
        iy = int(sy) - 28

        color = POWERUP_COLORS.get(self.held_powerup, POWERUP_MYSTERY_COLOR)
        pygame.draw.circle(surface, (30, 30, 30), (ix, iy), 8)
        pygame.draw.circle(surface, color, (ix, iy), 6)
        pygame.draw.circle(surface, COLOR_WHITE, (ix, iy), 8, 1)

    # ────────────────────────────────────────────
    # NETWORK SERIALIZATION
    # ────────────────────────────────────────────

    def apply_net_state(self, state):
        """Aplica estado recibido del servidor (para autos remotos/interpolación)."""
        self.x = state.x
        self.y = state.y
        self.velocity.x = state.vx
        self.velocity.y = state.vy
        self.angle = state.angle
        self.laps = state.laps
        self.next_checkpoint_index = state.next_checkpoint_index
        self.held_powerup = state.held_powerup
        self.is_drifting = state.is_drifting
        self.is_countersteer = state.is_countersteer
        self.drift_charge = state.drift_charge
        self.drift_level = state.drift_level
        self.finished = state.finished
        self.finish_time = state.finish_time

        # Sync drift state completo
        self.drift_time = state.drift_time
        self.drift_direction = state.drift_direction
        self.drift_mt_boost_timer = state.drift_mt_boost_timer

        # Reconstruir active_effects con duraciones reales del servidor
        if hasattr(state, 'effect_durations') and state.effect_durations:
            new_effects = {}
            for ename in state.effects:
                new_effects[ename] = state.effect_durations.get(ename, 1.0)
            self.active_effects = new_effects
        else:
            # Fallback legacy (servidor sin duraciones)
            for ename in state.effects:
                if ename not in self.active_effects:
                    self.active_effects[ename] = 1.0
            to_remove = [k for k in self.active_effects if k not in state.effects]
            for k in to_remove:
                del self.active_effects[k]

        self.update_sprite()

    def __repr__(self) -> str:
        return (f"Car({self.name}, pos=({self.x:.0f},{self.y:.0f}), "
                f"speed={self.speed:.0f}, lap={self.laps})")
