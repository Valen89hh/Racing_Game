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
        self.speed = 0.0

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

        # Colisión con pared (usado por physics.py)
        self._wall_normal = None

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
    # SPRITE Y DIBUJO
    # ────────────────────────────────────────────

    def update_sprite(self):
        """Actualiza el sprite rotado según el ángulo actual."""
        self.surface = pygame.transform.rotate(
            self.original_surface, -self.angle
        )
        self.rect = self.surface.get_rect(center=(self.x, self.y))
        self.mask = pygame.mask.from_surface(self.surface)

    def get_forward_vector(self) -> tuple[float, float]:
        """Retorna el vector de dirección frontal del auto."""
        return angle_to_vector(self.angle)

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
        sx, sy = camera.world_to_screen(self.x, self.y)

        # Rotar sprite según ángulo relativo a la cámara
        screen_ang = camera.screen_angle(self.angle)
        rotated = pygame.transform.rotate(self.original_surface, -screen_ang)
        rect = rotated.get_rect(center=(int(sx), int(sy)))
        surface.blit(rotated, rect)

        # Efecto visual del escudo: círculo azul semitransparente
        if self.is_shielded:
            shield_surf = pygame.Surface((60, 60), pygame.SRCALPHA)
            pygame.draw.circle(shield_surf, (60, 140, 255, 80), (30, 30), 28)
            pygame.draw.circle(shield_surf, (100, 180, 255, 150), (30, 30), 28, 2)
            surface.blit(shield_surf, (int(sx) - 30, int(sy) - 30))

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

        sx, sy = camera.world_to_screen(self.x, self.y)
        ix = int(sx)
        iy = int(sy) - 28

        color = POWERUP_COLORS.get(self.held_powerup, POWERUP_MYSTERY_COLOR)
        pygame.draw.circle(surface, (30, 30, 30), (ix, iy), 8)
        pygame.draw.circle(surface, color, (ix, iy), 6)
        pygame.draw.circle(surface, COLOR_WHITE, (ix, iy), 8, 1)

    def __repr__(self) -> str:
        return (f"Car({self.name}, pos=({self.x:.0f},{self.y:.0f}), "
                f"speed={self.speed:.0f}, lap={self.laps})")
