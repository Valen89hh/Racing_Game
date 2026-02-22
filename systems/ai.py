"""
ai.py - Sistema de inteligencia artificial para los bots.

El bot sigue waypoints del circuito con steering proporcional,
ajusta velocidad en curvas, y usa power-ups de forma táctica.
"""

import math
import random

from entities.car import Car
from entities.track import Track
from utils.helpers import angle_between_points, normalize_angle, distance
from settings import (
    BOT_WAYPOINT_REACH_DIST,
    POWERUP_BOOST, POWERUP_SHIELD, POWERUP_MISSILE, POWERUP_OIL,
)


class AISystem:
    """
    IA que controla los autos bot con waypoints y uso de power-ups.
    """

    def __init__(self, track: Track):
        self.track = track
        self.waypoints = track.waypoints
        self.num_waypoints = len(self.waypoints)
        self.current_waypoints = {}

        # Cooldown para uso de power-ups (evitar spam)
        self.powerup_cooldowns = {}

    def register_bot(self, car: Car):
        """Registra un auto como bot y encuentra el waypoint más cercano."""
        nearest = 0
        min_dist = float('inf')
        for i, wp in enumerate(self.waypoints):
            d = distance((car.x, car.y), wp)
            if d < min_dist:
                min_dist = d
                nearest = i
        self.current_waypoints[car.player_id] = nearest
        self.powerup_cooldowns[car.player_id] = 0.0

    def update(self, car: Car, dt: float, other_cars: list[Car] = None):
        """
        Actualiza los comandos del bot.

        Args:
            car: auto bot.
            dt: delta time.
            other_cars: lista de otros autos (para uso táctico de power-ups).
        """
        if car.player_id not in self.current_waypoints:
            self.register_bot(car)

        car.reset_inputs()

        # ── Navegación por waypoints ──
        wp_index = self.current_waypoints[car.player_id]
        target = self.waypoints[wp_index]

        dist_to_wp = distance((car.x, car.y), target)
        if dist_to_wp < BOT_WAYPOINT_REACH_DIST:
            wp_index = (wp_index + 1) % self.num_waypoints
            self.current_waypoints[car.player_id] = wp_index
            target = self.waypoints[wp_index]

        # Ángulo hacia el objetivo
        target_angle = angle_between_points((car.x, car.y), target)
        angle_diff = normalize_angle(target_angle - car.angle)

        # Steering proporcional
        turn_threshold = 3.0
        if angle_diff > turn_threshold:
            car.input_turn = min(1.0, angle_diff / 45.0)
        elif angle_diff < -turn_threshold:
            car.input_turn = max(-1.0, angle_diff / 45.0)

        # Control de velocidad
        speed_factor = self._calculate_speed_factor(wp_index)
        car.input_accelerate = speed_factor

        if abs(angle_diff) > 60:
            car.input_accelerate = 0.3
        elif abs(angle_diff) > 90:
            car.input_brake = True

        # ── Uso táctico de power-ups ──
        self.powerup_cooldowns[car.player_id] = max(
            0, self.powerup_cooldowns[car.player_id] - dt
        )
        if (car.held_powerup is not None and
                self.powerup_cooldowns[car.player_id] <= 0):
            if self._should_use_powerup(car, other_cars or []):
                car.input_use_powerup = True
                self.powerup_cooldowns[car.player_id] = 2.0

    def _calculate_speed_factor(self, current_wp: int) -> float:
        """Mira waypoints adelante para anticipar curvas y reducir velocidad."""
        look_ahead = 3
        total_angle_change = 0.0

        for i in range(look_ahead):
            wp_a = self.waypoints[(current_wp + i) % self.num_waypoints]
            wp_b = self.waypoints[(current_wp + i + 1) % self.num_waypoints]
            angle_a = angle_between_points(wp_a, wp_b)

            if i > 0:
                wp_prev = self.waypoints[(current_wp + i - 1) % self.num_waypoints]
                angle_prev = angle_between_points(wp_prev, wp_a)
                total_angle_change += abs(normalize_angle(angle_a - angle_prev))

        if total_angle_change > 60:
            return 0.5
        elif total_angle_change > 30:
            return 0.7
        return 1.0

    def _should_use_powerup(self, car: Car, other_cars: list[Car]) -> bool:
        """Decide si el bot debe usar su power-up ahora."""
        ptype = car.held_powerup

        if ptype == POWERUP_BOOST:
            # Usar boost en rectas (angle_diff pequeño con siguiente waypoint)
            wp_idx = self.current_waypoints.get(car.player_id, 0)
            speed_factor = self._calculate_speed_factor(wp_idx)
            return speed_factor > 0.8 and car.speed > 200

        elif ptype == POWERUP_SHIELD:
            # Usar shield al acercarse a otro auto
            for other in other_cars:
                if other.player_id == car.player_id:
                    continue
                if distance((car.x, car.y), (other.x, other.y)) < 200:
                    return True
            # O usarlo aleatoriamente si no hay nadie cerca
            return random.random() < 0.01

        elif ptype == POWERUP_MISSILE:
            # Disparar si hay un auto enemigo adelante y relativamente alineado
            fx, fy = car.get_forward_vector()
            for other in other_cars:
                if other.player_id == car.player_id:
                    continue
                dx = other.x - car.x
                dy = other.y - car.y
                dist = math.hypot(dx, dy)
                if dist < 500 and dist > 30:
                    # Verificar si está "adelante" (dot product positivo)
                    dot = (dx * fx + dy * fy) / dist
                    if dot > 0.7:  # bastante alineado
                        return True
            return False

        elif ptype == POWERUP_OIL:
            # Dejar aceite si un auto viene detrás
            fx, fy = car.get_forward_vector()
            for other in other_cars:
                if other.player_id == car.player_id:
                    continue
                dx = other.x - car.x
                dy = other.y - car.y
                dist = math.hypot(dx, dy)
                if dist < 300:
                    dot = (dx * fx + dy * fy) / (dist + 0.01)
                    if dot < -0.3:  # detrás del bot
                        return True
            return random.random() < 0.005

        return False
