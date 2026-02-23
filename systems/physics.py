"""
physics.py - Sistema de física arcade.

Gestiona aceleración, fricción, giro y movimiento de los autos.
Usa las propiedades efectivas del auto (base * multiplicador) para que
los power-ups modifiquen la física sin tocar este sistema.

──────────────────────────────────────────────────────────────────────
RESPUESTA A COLISIÓN POR PROYECCIÓN SOBRE VECTOR NORMAL
──────────────────────────────────────────────────────────────────────

    V = velocidad del auto (vector 2D = speed * forward)
    N = normal de la pared (apunta hacia la pista)

    V_normal     = dot(V, N) * N   → componente que penetra el muro
    V_tangencial = V - V_normal    → componente paralela = deslizamiento

    Si dot(V, N) < 0 → el auto va hacia el muro → eliminar V_normal.
    Si dot(V, N) ≥ 0 → ya se aleja → no tocar.
──────────────────────────────────────────────────────────────────────
"""

import math

from entities.car import Car
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
        self._apply_acceleration(car, dt)
        self._apply_friction(car, dt, track)
        self._apply_turning(car, dt, track)
        self._apply_movement(car, dt)

    def _apply_acceleration(self, car: Car, dt: float):
        """Aplica aceleración o frenado según el input."""
        if car.input_brake:
            if car.speed > 0:
                car.speed -= car.brake_force * dt
                if car.speed < 0:
                    car.speed = 0
            elif car.speed < 0:
                car.speed += car.brake_force * dt
                if car.speed > 0:
                    car.speed = 0
            return

        # Bloquear aceleración si el auto empuja contra un muro
        if car._wall_normal is not None:
            nx, ny = car._wall_normal
            fx, fy = car.get_forward_vector()
            if car.input_accelerate > 0:
                if fx * nx + fy * ny < -0.3:
                    return
            elif car.input_accelerate < 0:
                if -fx * nx + -fy * ny < -0.3:
                    return

        accel = car.effective_acceleration
        max_spd = car.effective_max_speed

        if car.input_accelerate > 0:
            if car.speed < 0:
                car.speed += car.brake_force * car.input_accelerate * dt
            else:
                car.speed += accel * car.input_accelerate * dt
            car.speed = min(car.speed, max_spd)

        elif car.input_accelerate < 0:
            if car.speed > 0:
                car.speed += car.brake_force * car.input_accelerate * dt
            else:
                car.speed += accel * car.input_accelerate * dt * 0.5
            car.speed = max(car.speed, -car.reverse_max_speed)

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

        if abs(car.speed) < 5.0:
            car.speed = 0
            return

        if car.speed > 0:
            car.speed -= friction * dt
            if car.speed < 0:
                car.speed = 0
        elif car.speed < 0:
            car.speed += friction * dt
            if car.speed > 0:
                car.speed = 0

    def _apply_turning(self, car: Car, dt: float, track=None):
        """Aplica rotación basándose en input, velocidad y multiplicador de giro.
        Slippery surfaces (friction < 0.8) reduce turning proportionally."""
        if car.input_turn == 0:
            return

        wall_contact = car._wall_normal is not None
        if abs(car.speed) < 1.0 and not wall_contact:
            return

        speed_ratio = clamp(abs(car.speed) / car.effective_max_speed, 0.0, 1.0)
        base_turn = lerp(car.turn_speed_min, car.effective_turn_speed, speed_ratio)

        if abs(car.speed) < 1.0 and wall_contact:
            base_turn = car.turn_speed_min

        # Reduce turning on slippery tiles
        if track and hasattr(track, 'get_friction_at'):
            tile_friction = track.get_friction_at(car.x, car.y)
            if tile_friction < 0.8:
                base_turn *= tile_friction

        direction = 1.0 if car.speed >= 0 else -1.0
        car.angle += car.input_turn * base_turn * direction * dt
        car.angle %= 360

    def _apply_movement(self, car: Car, dt: float):
        """Actualiza la posición del auto según su velocidad y dirección."""
        if abs(car.speed) < 0.1:
            return
        dx, dy = angle_to_vector(car.angle)
        car.x += dx * car.speed * dt
        car.y += dy * car.speed * dt

    def apply_collision_response(self, car: Car,
                                  wall_normal: tuple[float, float]):
        """
        Proyecta la velocidad sobre la normal de la pared.
        Elimina la componente hacia el muro y conserva la tangencial.
        """
        nx, ny = wall_normal
        fx, fy = car.get_forward_vector()
        vx = fx * car.speed
        vy = fy * car.speed

        dot = vx * nx + vy * ny

        if dot >= 0:
            car._wall_normal = None
            return

        # Componente tangencial
        vt_x = vx - dot * nx
        vt_y = vy - dot * ny
        tangential_speed = math.hypot(vt_x, vt_y)

        # Penalización leve proporcional al impacto
        impact_factor = 1.0 - abs(dot) / (abs(car.speed) + 0.01)
        penalty = 1.0 - (1.0 - impact_factor) * 0.15

        car.speed = tangential_speed * penalty
        car._wall_normal = (nx, ny)

    def clear_wall_contact(self, car: Car):
        """Limpia el estado de contacto con pared."""
        car._wall_normal = None
