"""
physics.py - Sistema de física arcade.

Gestiona aceleración, fricción, giro y movimiento de los autos.
Usa las propiedades efectivas del auto (base * multiplicador) para que
los power-ups modifiquen la física sin tocar este sistema.

──────────────────────────────────────────────────────────────────────
DRIFT POR VECTOR DE VELOCIDAD REAL
──────────────────────────────────────────────────────────────────────

    velocity = vector 2D real de movimiento
    forward  = dirección visual del auto (car.angle)

    Cada frame, velocity se descompone en forward + lateral respecto
    a car.angle. La componente lateral se amortigua según el grip:
      - Normal (sin SPACE): lateral *= 0.2   → agarre alto
      - Drift  (con SPACE): lateral *= 0.85  → deslizamiento

    El drift emerge naturalmente de la diferencia entre orientación
    y dirección real de velocidad.

──────────────────────────────────────────────────────────────────────
RESPUESTA A COLISIÓN POR PROYECCIÓN SOBRE VECTOR NORMAL
──────────────────────────────────────────────────────────────────────

    V = velocity del auto (vector 2D real)
    N = normal de la pared (apunta hacia la pista)

    V_normal     = dot(V, N) * N   → componente que penetra el muro
    V_tangencial = V - V_normal    → componente paralela = deslizamiento

    Si dot(V, N) < 0 → el auto va hacia el muro → eliminar V_normal.
    Si dot(V, N) ≥ 0 → ya se aleja → no tocar.
──────────────────────────────────────────────────────────────────────
"""

import math
import pygame

from entities.car import Car
from settings import (
    DRIFT_MIN_SPEED, DRIFT_MAX_ANGLE, DRIFT_TURN_BOOST, DRIFT_SPEED_BOOST,
    DRIFT_LATERAL_GRIP_NORMAL, DRIFT_LATERAL_GRIP_DRIFT, DRIFT_EXIT_BOOST,
    DRIFT_GRIP_TRANSITION_TIME, DRIFT_CHARGE_RATE,
    DRIFT_LEVEL_BOOSTS, DRIFT_MT_BOOST_DURATION,
    DRIFT_COUNTERSTEER_TURN_MULT, DRIFT_COUNTERSTEER_GRIP,
)
from utils.helpers import angle_to_vector, clamp, lerp


class PhysicsSystem:
    """
    Sistema de física que actualiza el movimiento de los autos.
    Usa las propiedades effective_* del Car para soportar power-ups.
    """

    def update(self, car: Car, dt: float, track=None):
        """Actualiza la física de un auto para el frame actual.

        Args:
            car: the car entity
            dt: delta time
            track: optional track with get_friction_at(x,y) for per-tile friction
        """
        was_drifting = car.is_drifting
        self._apply_acceleration(car, dt)
        self._apply_friction(car, dt, track)
        self._apply_turning(car, dt, track)
        self._apply_grip(car, dt)
        self._update_drift_charge(car, dt)
        self._apply_movement(car, dt)

        # Mini-turbo boost timer (post-drift boost activo)
        if car.drift_mt_boost_timer > 0:
            car.drift_mt_boost_timer -= dt
            if car.drift_mt_boost_timer <= 0:
                car.drift_mt_boost_timer = 0.0

        # Drift exit boost (escalado por nivel de mini-turbo)
        if was_drifting and not car.is_drifting and not car.input_brake:
            level = car.drift_level
            car._last_drift_level = level  # guardar para efecto visual
            if level > 0 and level <= len(DRIFT_LEVEL_BOOSTS):
                boost = DRIFT_LEVEL_BOOSTS[level - 1]
                car.velocity *= boost
                car.drift_mt_boost_timer = DRIFT_MT_BOOST_DURATION
            else:
                car.velocity *= DRIFT_EXIT_BOOST
            # Reset drift state
            car.drift_charge = 0.0
            car.drift_level = 0
            car.drift_time = 0.0
            car.drift_direction = 0
            car.is_countersteer = False

    def _apply_acceleration(self, car: Car, dt: float):
        """Aplica aceleración o frenado según el input."""
        fx, fy = car.get_forward_vector()
        forward = pygame.math.Vector2(fx, fy)
        speed_mag = car.velocity.length()

        if car.input_brake:
            if speed_mag >= DRIFT_MIN_SPEED:
                # Drift: activar flag, conservar inercia
                car.is_drifting = True
                # drift_direction sigue el input actual (dinámico)
                if car.input_turn != 0:
                    car.drift_direction = 1 if car.input_turn > 0 else -1
                # Counter-steer: ambas teclas presionadas (input_turn = 0) mientras ya hay dirección
                car.is_countersteer = (car.input_turn == 0 and car.drift_direction != 0)
                return
            else:
                # Baja velocidad: freno duro hacia 0
                car.is_drifting = False
                if speed_mag > 0:
                    brake_amount = car.brake_force * dt
                    if brake_amount >= speed_mag:
                        car.velocity.x = 0.0
                        car.velocity.y = 0.0
                    else:
                        car.velocity.scale_to_length(speed_mag - brake_amount)
                return

        # Bloquear aceleración si el auto empuja contra un muro
        if car._wall_normal is not None:
            nx, ny = car._wall_normal
            if car.input_accelerate > 0:
                if fx * nx + fy * ny < -0.3:
                    return
            elif car.input_accelerate < 0:
                if -fx * nx + -fy * ny < -0.3:
                    return

        accel = car.effective_acceleration
        max_spd = car.effective_max_speed

        if car.input_accelerate > 0:
            fwd_speed = car.speed  # proyección forward (con signo)
            if fwd_speed < 0:
                # Frenando marcha atrás
                car.velocity += forward * car.brake_force * car.input_accelerate * dt
            else:
                car.velocity += forward * accel * car.input_accelerate * dt
            # Clamp magnitud a max_speed
            if car.velocity.length() > max_spd:
                car.velocity.scale_to_length(max_spd)

        elif car.input_accelerate < 0:
            fwd_speed = car.speed
            if fwd_speed > 0:
                # Frenando marcha adelante
                car.velocity += forward * car.brake_force * car.input_accelerate * dt
            else:
                car.velocity += forward * accel * car.input_accelerate * dt * 0.5
            # Clamp a reverse max speed
            if car.velocity.length() > car.reverse_max_speed:
                car.velocity.scale_to_length(car.reverse_max_speed)

    def _apply_friction(self, car: Car, dt: float, track=None):
        """Aplica fricción cuando no se acelera.
        Per-tile friction modulates the base friction value."""
        if car.input_accelerate != 0:
            return

        friction = car.effective_friction

        # Modulate by tile friction
        tile_friction = 1.0
        if track and hasattr(track, 'get_friction_at'):
            tile_friction = track.get_friction_at(car.x, car.y)
        friction *= tile_friction

        speed_mag = car.velocity.length()
        if speed_mag < 5.0:
            car.velocity.x = 0.0
            car.velocity.y = 0.0
            return

        new_speed = speed_mag - friction * dt
        if new_speed <= 0:
            car.velocity.x = 0.0
            car.velocity.y = 0.0
        else:
            car.velocity.scale_to_length(new_speed)

    def _apply_turning(self, car: Car, dt: float, track=None):
        """Aplica rotación basándose en input, velocidad y multiplicador de giro.
        Slippery surfaces (friction < 0.8) reduce turning proportionally."""
        if car.input_turn == 0:
            return

        wall_contact = car._wall_normal is not None
        speed_mag = car.velocity.length()
        if speed_mag < 1.0 and not wall_contact:
            return

        speed_ratio = clamp(speed_mag / car.effective_max_speed, 0.0, 1.0)
        base_turn = lerp(car.turn_speed_min, car.effective_turn_speed, speed_ratio)

        if speed_mag < 1.0 and wall_contact:
            base_turn = car.turn_speed_min

        # Giro durante drift
        if car.is_drifting:
            base_turn *= DRIFT_TURN_BOOST

        # Reduce turning on slippery tiles
        if track and hasattr(track, 'get_friction_at'):
            tile_friction = track.get_friction_at(car.x, car.y)
            if tile_friction < 0.8:
                base_turn *= tile_friction

        direction = 1.0 if car.speed >= 0 else -1.0
        new_angle = car.angle + car.input_turn * base_turn * direction * dt

        # Durante drift: limitar ángulo máximo entre orientación y velocidad
        if car.is_drifting and speed_mag > 1.0:
            vel_angle = math.degrees(math.atan2(car.velocity.x, -car.velocity.y)) % 360
            diff = (new_angle - vel_angle + 180) % 360 - 180
            if abs(diff) > DRIFT_MAX_ANGLE:
                clamped_diff = DRIFT_MAX_ANGLE if diff > 0 else -DRIFT_MAX_ANGLE
                new_angle = vel_angle + clamped_diff

        car.angle = new_angle % 360

    def _apply_grip(self, car: Car, dt: float):
        """Descompone velocity en forward + lateral y amortigua lateral según grip.
        Grip progresivo: transiciona suavemente de normal a drift en DRIFT_GRIP_TRANSITION_TIME.
        Durante drift conserva la magnitud total (inercia)."""
        speed_mag = car.velocity.length()
        if speed_mag < 0.1:
            return

        fx, fy = car.get_forward_vector()
        forward = pygame.math.Vector2(fx, fy)

        # Descomponer velocity
        forward_dot = car.velocity.dot(forward)
        forward_component = forward * forward_dot
        lateral_component = car.velocity - forward_component

        # Grip progresivo: lerp entre normal y drift basado en drift_time
        if car.is_drifting:
            car.drift_time += dt
            if car.is_countersteer:
                # Counter-steer (A+D): NO tocar lateral → dirección se mantiene = diagonal
                pass
            else:
                t = clamp(car.drift_time / DRIFT_GRIP_TRANSITION_TIME, 0.0, 1.0)
                grip = lerp(DRIFT_LATERAL_GRIP_NORMAL, DRIFT_LATERAL_GRIP_DRIFT, t)
                lateral_component *= grip
                car.velocity = forward_component + lateral_component
        else:
            grip = DRIFT_LATERAL_GRIP_NORMAL
            lateral_component *= grip
            car.velocity = forward_component + lateral_component

        # Durante drift: conservar magnitud + ligero boost de velocidad
        if car.is_drifting:
            new_mag = car.velocity.length()
            if new_mag > 0.1:
                boosted = min(speed_mag * DRIFT_SPEED_BOOST, car.effective_max_speed)
                car.velocity.scale_to_length(boosted)

        # Si no está en drift y no hay handbrake, desactivar flag
        if not car.input_brake:
            car.is_drifting = False
            car.drift_time = 0.0
            car.drift_direction = 0
            car.is_countersteer = False

    def _update_drift_charge(self, car: Car, dt: float):
        """Acumula carga de mini-turbo durante drift, basado en input de giro y velocidad lateral."""
        if car.is_drifting:
            # Factor de input de giro (más carga si giras activamente)
            turn_factor = abs(car.input_turn)
            # Factor de velocidad lateral (más carga si deslizas más)
            lateral = car.get_lateral_speed()
            lat_factor = clamp(lateral / (car.effective_max_speed * 0.4), 0.0, 1.0)
            # Combinar: necesita algo de giro Y deslizamiento
            charge_rate = DRIFT_CHARGE_RATE * (0.3 + 0.7 * turn_factor) * (0.4 + 0.6 * lat_factor)
            car.drift_charge = clamp(car.drift_charge + charge_rate * dt, 0.0, 1.0)
            car.update_drift_level()
        else:
            # Decay rápido cuando no driftea
            if car.drift_charge > 0:
                car.drift_charge = max(0.0, car.drift_charge - 2.0 * dt)
                car.update_drift_level()

    def _apply_movement(self, car: Car, dt: float):
        """Actualiza la posición del auto según su velocity."""
        car.x += car.velocity.x * dt
        car.y += car.velocity.y * dt

    def apply_collision_response(self, car: Car,
                                  wall_normal: tuple[float, float]):
        """
        Proyecta la velocidad sobre la normal de la pared.
        Elimina la componente hacia el muro y conserva la tangencial.
        """
        nx, ny = wall_normal
        vx = car.velocity.x
        vy = car.velocity.y

        dot = vx * nx + vy * ny

        if dot >= 0:
            car._wall_normal = None
            return

        # Componente tangencial
        vt_x = vx - dot * nx
        vt_y = vy - dot * ny

        # Penalización leve proporcional al impacto
        speed_mag = car.velocity.length()
        impact_factor = 1.0 - abs(dot) / (speed_mag + 0.01)
        penalty = 1.0 - (1.0 - impact_factor) * 0.15

        car.velocity.x = vt_x * penalty
        car.velocity.y = vt_y * penalty
        car._wall_normal = (nx, ny)

        # Resetear drift al impactar un muro
        car.is_drifting = False
        car.drift_time = 0.0
        car.drift_charge = 0.0
        car.drift_level = 0
        car.drift_direction = 0
        car.is_countersteer = False

    def clear_wall_contact(self, car: Car):
        """Limpia el estado de contacto con pared."""
        car._wall_normal = None
