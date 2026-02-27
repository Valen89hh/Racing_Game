"""
collision.py - Sistema de detección y resolución de colisiones.

Usa circle collider + rollback para colisiones auto-pista.
Sin push-out iterativo, sin binary search. Determinista al 100%.

Colisiones auto-auto usan distancia simple entre centros.
"""

import math

from entities.car import Car
from entities.track import Track
from entities.powerup import PowerUpItem, Missile, OilSlick, Mine, SmartMissile
from utils.helpers import distance
from settings import (
    WORLD_WIDTH, WORLD_HEIGHT,
    MISSILE_SLOW_DURATION, OIL_EFFECT_DURATION,
    CAR_COLLISION_RADIUS, CAR_COLLISION_SAMPLES, CAR_VS_CAR_SPEED_PENALTY,
)


class CollisionSystem:
    """
    Sistema de colisiones con circle collider + rollback.
    """

    def __init__(self, track: Track):
        self.track = track
        # Pre-calcular ángulos del perímetro
        self._sample_angles = [
            (2.0 * math.pi * i) / CAR_COLLISION_SAMPLES
            for i in range(CAR_COLLISION_SAMPLES)
        ]
        self._cos_angles = [math.cos(a) for a in self._sample_angles]
        self._sin_angles = [math.sin(a) for a in self._sample_angles]

    # ── AUTO vs PISTA (circle collider) ──

    def check_track_collision(self, car: Car) -> bool:
        """Verifica si algún punto del perímetro del circle collider toca boundary."""
        mask = self.track.boundary_mask
        r = car.collision_radius

        for i in range(CAR_COLLISION_SAMPLES):
            sx = int(car.x + self._cos_angles[i] * r)
            sy = int(car.y + self._sin_angles[i] * r)

            if 0 <= sx < WORLD_WIDTH and 0 <= sy < WORLD_HEIGHT:
                if mask.get_at((sx, sy)):
                    return True
            else:
                return True  # fuera del mundo = colisión

        return False

    def compute_wall_normal(self, car: Car) -> tuple[float, float]:
        """
        Calcula la normal de la pared desde los puntos penetrantes del perímetro.
        La normal apunta desde la pared hacia la pista (dirección de escape).
        """
        wall_dx = 0.0
        wall_dy = 0.0
        mask = self.track.boundary_mask
        r = car.collision_radius

        for i in range(CAR_COLLISION_SAMPLES):
            cos_a = self._cos_angles[i]
            sin_a = self._sin_angles[i]
            sx = int(car.x + cos_a * r)
            sy = int(car.y + sin_a * r)

            hit = False
            if 0 <= sx < WORLD_WIDTH and 0 <= sy < WORLD_HEIGHT:
                if mask.get_at((sx, sy)):
                    hit = True
            else:
                hit = True

            if hit:
                wall_dx += cos_a
                wall_dy += sin_a

        length = math.hypot(wall_dx, wall_dy)
        if length < 0.01:
            fx, fy = car.get_forward_vector()
            return -fx, -fy

        return -wall_dx / length, -wall_dy / length

    def resolve_track_collision(self, car: Car,
                                old_x: float, old_y: float
                                ) -> tuple[float, float]:
        """
        Rollback: mueve el auto a la posición anterior y retorna la normal.
        Sin push-out, sin iteraciones. 100% determinista.
        """
        nx, ny = self.compute_wall_normal(car)
        car.x = old_x
        car.y = old_y
        return nx, ny

    # ── VUELTAS Y CHECKPOINTS ──

    def update_checkpoints(self, car: Car):
        """
        Actualiza checkpoints y vueltas usando zonas rectangulares.

        Cada frame verifica si el auto está dentro de la zona del siguiente
        checkpoint. Si tiene efecto imán, usa una zona más grande.
        """
        zones = self.track.checkpoint_zones
        n = len(zones)
        if n == 0 or car.next_checkpoint_index >= n:
            return
        zone = zones[car.next_checkpoint_index]

        if car.has_magnet:
            from settings import MAGNET_RADIUS_MULT
            expanded = zone.inflate(
                int(zone.width * (MAGNET_RADIUS_MULT - 1)),
                int(zone.height * (MAGNET_RADIUS_MULT - 1)))
            hit = expanded.collidepoint(int(car.x), int(car.y))
        else:
            hit = zone.collidepoint(int(car.x), int(car.y))

        if hit:
            car.next_checkpoint_index += 1
            if car.next_checkpoint_index >= n:
                car.laps += 1
                car.next_checkpoint_index = 0

    # ── AUTO vs AUTO (distancia simple) ──

    def check_car_vs_car(self, car_a: Car, car_b: Car) -> bool:
        """Verifica colisión entre dos autos por distancia de centros."""
        dx = car_b.x - car_a.x
        dy = car_b.y - car_a.y
        dist = math.hypot(dx, dy)
        min_dist = car_a.collision_radius + car_b.collision_radius
        return dist < min_dist

    def resolve_car_vs_car(self, car_a: Car, car_b: Car):
        """Resuelve colisión entre dos autos: push por overlap exacto."""
        dx = car_b.x - car_a.x
        dy = car_b.y - car_a.y
        dist = math.hypot(dx, dy)
        if dist < 1.0:
            dx, dy, dist = 1.0, 0.0, 1.0

        nx, ny = dx / dist, dy / dist
        min_dist = car_a.collision_radius + car_b.collision_radius
        overlap = min_dist - dist
        if overlap > 0:
            half = overlap * 0.5
            car_a.x -= nx * half
            car_a.y -= ny * half
            car_b.x += nx * half
            car_b.y += ny * half
        car_a.speed *= CAR_VS_CAR_SPEED_PENALTY
        car_b.speed *= CAR_VS_CAR_SPEED_PENALTY

    # ── POWER-UPS ──

    def check_car_vs_powerup(self, car: Car,
                              item: PowerUpItem) -> bool:
        """Verifica si el auto recoge un power-up."""
        if not item.active:
            return False
        return distance((car.x, car.y), (item.x, item.y)) < item.radius + 18

    def check_car_vs_missile(self, car: Car, missile: Missile) -> bool:
        """Verifica si un misil impacta un auto (que no sea el dueño)."""
        if not missile.alive or car.player_id == missile.owner_id:
            return False
        return distance((car.x, car.y), (missile.x, missile.y)) < missile.radius + 18

    def check_car_vs_oil(self, car: Car, oil: OilSlick) -> bool:
        """Verifica si un auto pisa una mancha de aceite."""
        if not oil.alive:
            return False
        return distance((car.x, car.y), (oil.x, oil.y)) < oil.radius + 10

    def check_car_vs_mine(self, car: Car, mine: Mine) -> bool:
        """Verifica si un auto pisa una mina (que no sea el dueño)."""
        if not mine.alive or car.player_id == mine.owner_id:
            return False
        return distance((car.x, car.y), (mine.x, mine.y)) < mine.radius + 15

    def check_car_vs_smart_missile(self, car: Car,
                                    missile: SmartMissile) -> bool:
        """Verifica si un misil inteligente impacta un auto."""
        if not missile.alive or car.player_id == missile.owner_id:
            return False
        return distance((car.x, car.y), (missile.x, missile.y)) < missile.radius + 18

    def check_missile_vs_wall(self, missile) -> bool:
        """Verifica si un misil chocó con un muro de la pista."""
        if not missile.alive:
            return False
        ix, iy = int(missile.x), int(missile.y)
        if 0 <= ix < WORLD_WIDTH and 0 <= iy < WORLD_HEIGHT:
            return self.track.boundary_mask.get_at((ix, iy))
        return True  # fuera del mundo = destruir
