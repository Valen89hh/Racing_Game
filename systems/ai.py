"""
ai.py - Sistema de inteligencia artificial para los bots.

El bot sigue waypoints del circuito con steering suave y proporcional,
ajusta velocidad anticipando curvas con look-ahead de 5 waypoints,
detecta cuando queda atascado y ejecuta maniobras de recuperación,
y usa power-ups de forma táctica.
"""

import math
import random

from entities.car import Car
from entities.track import Track
from utils.helpers import (
    angle_between_points, normalize_angle, distance, clamp, lerp,
)
from settings import (
    BOT_WAYPOINT_REACH_DIST,
    BOT_STUCK_CHECK_INTERVAL, BOT_STUCK_DIST_THRESHOLD,
    BOT_STUCK_TIME_THRESHOLD, BOT_RECOVERY_DURATION,
    BOT_LOOK_AHEAD, BOT_STEER_DEADZONE, BOT_STEER_RANGE,
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

        # Pre-computar ángulos entre segmentos de waypoints
        self._segment_angles = self._precompute_path_data()

        # Anti-stuck state per bot
        self._stuck_timers = {}      # player_id -> timer acumulado desde último check
        self._stuck_positions = {}   # player_id -> (x, y) snapshot
        self._stuck_accum = {}       # player_id -> tiempo acumulado "sin moverse"
        self._recovery_timers = {}   # player_id -> tiempo restante de recovery

    def _precompute_path_data(self) -> list:
        """Pre-computa el cambio de ángulo en cada segmento para O(1) lookup."""
        angles = []
        for i in range(self.num_waypoints):
            wp_a = self.waypoints[i]
            wp_b = self.waypoints[(i + 1) % self.num_waypoints]
            angle_ab = angle_between_points(wp_a, wp_b)

            wp_prev = self.waypoints[(i - 1) % self.num_waypoints]
            angle_prev = angle_between_points(wp_prev, wp_a)
            change = abs(normalize_angle(angle_ab - angle_prev))
            angles.append(change)
        return angles

    def register_bot(self, car: Car):
        """Registra un auto como bot y encuentra el waypoint más cercano."""
        nearest = 0
        min_dist = float('inf')
        for i, wp in enumerate(self.waypoints):
            d = distance((car.x, car.y), wp)
            if d < min_dist:
                min_dist = d
                nearest = i
        pid = car.player_id
        self.current_waypoints[pid] = nearest
        self.powerup_cooldowns[pid] = 0.0
        self._stuck_timers[pid] = 0.0
        self._stuck_positions[pid] = (car.x, car.y)
        self._stuck_accum[pid] = 0.0
        self._recovery_timers[pid] = 0.0

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

        pid = car.player_id
        car.reset_inputs()

        # ── Modo recuperación (anti-stuck) ──
        if self._recovery_timers[pid] > 0:
            self._recovery_timers[pid] -= dt
            self._do_recovery(car, dt)
            return

        # ── Detección de stuck ──
        self._check_stuck(car, dt)

        # ── Navegación por waypoints ──
        wp_index = self.current_waypoints[pid]
        target = self.waypoints[wp_index]

        dist_to_wp = distance((car.x, car.y), target)
        if dist_to_wp < BOT_WAYPOINT_REACH_DIST:
            wp_index = (wp_index + 1) % self.num_waypoints
            self.current_waypoints[pid] = wp_index
            target = self.waypoints[wp_index]
            dist_to_wp = distance((car.x, car.y), target)

        # ── Waypoint blending ──
        # Cuando se acerca al waypoint actual, mezclar target con el siguiente
        next_wp_index = (wp_index + 1) % self.num_waypoints
        next_target = self.waypoints[next_wp_index]
        blend_radius = BOT_WAYPOINT_REACH_DIST * 2.0
        if dist_to_wp < blend_radius:
            t = 1.0 - (dist_to_wp / blend_radius)
            target = (
                lerp(target[0], next_target[0], t * 0.5),
                lerp(target[1], next_target[1], t * 0.5),
            )

        # Ángulo hacia el objetivo
        target_angle = angle_between_points((car.x, car.y), target)
        angle_diff = normalize_angle(target_angle - car.angle)

        # ── Steering suave con deadzone ──
        if abs(angle_diff) > BOT_STEER_DEADZONE:
            car.input_turn = clamp(angle_diff / BOT_STEER_RANGE, -1.0, 1.0)

        # ── Control de velocidad con look-ahead mejorado ──
        speed_factor = self._calculate_speed_factor(wp_index)
        car.input_accelerate = speed_factor

        # Reducir velocidad según ángulo actual (orden corregido)
        abs_diff = abs(angle_diff)
        if abs_diff > 90:
            car.input_brake = True
            car.input_accelerate = 0.0
        elif abs_diff > 60:
            car.input_accelerate = 0.3

        # ── Uso táctico de power-ups ──
        self.powerup_cooldowns[pid] = max(
            0, self.powerup_cooldowns[pid] - dt
        )
        if (car.held_powerup is not None and
                self.powerup_cooldowns[pid] <= 0):
            if self._should_use_powerup(car, other_cars or []):
                car.input_use_powerup = True
                self.powerup_cooldowns[pid] = 2.0

    def _check_stuck(self, car: Car, dt: float):
        """Detecta si el bot está atascado y activa modo recuperación."""
        pid = car.player_id
        self._stuck_timers[pid] += dt

        if self._stuck_timers[pid] >= BOT_STUCK_CHECK_INTERVAL:
            self._stuck_timers[pid] = 0.0
            old_pos = self._stuck_positions[pid]
            moved = distance(old_pos, (car.x, car.y))
            self._stuck_positions[pid] = (car.x, car.y)

            if moved < BOT_STUCK_DIST_THRESHOLD:
                self._stuck_accum[pid] += BOT_STUCK_CHECK_INTERVAL
                if self._stuck_accum[pid] >= BOT_STUCK_TIME_THRESHOLD:
                    self._recovery_timers[pid] = BOT_RECOVERY_DURATION
                    self._stuck_accum[pid] = 0.0
            else:
                self._stuck_accum[pid] = 0.0

    def _do_recovery(self, car: Car, dt: float):
        """Ejecuta maniobra de recuperación: reversa + giro hacia waypoint."""
        pid = car.player_id
        wp_index = self.current_waypoints[pid]
        target = self.waypoints[wp_index]
        target_angle = angle_between_points((car.x, car.y), target)
        angle_diff = normalize_angle(target_angle - car.angle)

        car.input_accelerate = -0.6
        car.input_turn = clamp(angle_diff / 45.0, -1.0, 1.0)

    def _calculate_speed_factor(self, current_wp: int) -> float:
        """Mira waypoints adelante para anticipar curvas y reducir velocidad."""
        total_angle_change = 0.0
        max_single_change = 0.0

        for i in range(BOT_LOOK_AHEAD):
            idx = (current_wp + i) % self.num_waypoints
            change = self._segment_angles[idx]
            total_angle_change += change
            if change > max_single_change:
                max_single_change = change

        # Usar tanto el cambio total como el cambio máximo individual
        if max_single_change > 45 or total_angle_change > 90:
            return 0.3
        elif total_angle_change > 60:
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
