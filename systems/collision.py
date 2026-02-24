"""
collision.py - Sistema de detección y resolución de colisiones.

Maneja colisiones entre autos y bordes de la pista (con vector normal),
detección de cruce de línea de meta, checkpoints, y colisiones con
power-ups (pickups, misiles, manchas de aceite).
"""

import math

from entities.car import Car
from entities.track import Track
from entities.powerup import PowerUpItem, Missile, OilSlick
from utils.helpers import distance
from settings import (
    WORLD_WIDTH, WORLD_HEIGHT,
    MISSILE_SLOW_DURATION, OIL_EFFECT_DURATION,
)


class CollisionSystem:
    """
    Sistema de colisiones con resolución basada en vector normal
    y detección de power-ups.
    """

    NORMAL_SAMPLE_RAYS = 16
    NORMAL_SAMPLE_DIST = 28.0
    SEPARATION_STEP = 2.0
    MAX_SEPARATION_ITERS = 20

    def __init__(self, track: Track):
        self.track = track

    # ── AUTO vs PISTA ──

    def check_track_collision(self, car: Car) -> bool:
        """Verifica si el auto colisiona con los bordes de la pista."""
        return self.track.check_car_collision(car.mask, car.rect)

    def compute_wall_normal(self, car: Car) -> tuple[float, float]:
        """
        Calcula la normal de la pared muestreando 16 rayos alrededor del auto.
        La normal apunta desde la pared hacia la pista.
        """
        wall_dx = 0.0
        wall_dy = 0.0
        mask = self.track.boundary_mask

        for i in range(self.NORMAL_SAMPLE_RAYS):
            angle = (2.0 * math.pi * i) / self.NORMAL_SAMPLE_RAYS
            ray_cos = math.cos(angle)
            ray_sin = math.sin(angle)

            for dist_factor in (0.5, 0.75, 1.0):
                sample_dist = self.NORMAL_SAMPLE_DIST * dist_factor
                sx = int(car.x + ray_cos * sample_dist)
                sy = int(car.y + ray_sin * sample_dist)

                if 0 <= sx < WORLD_WIDTH and 0 <= sy < WORLD_HEIGHT:
                    if mask.get_at((sx, sy)):
                        weight = 1.0 / dist_factor
                        wall_dx += ray_cos * weight
                        wall_dy += ray_sin * weight

        length = math.hypot(wall_dx, wall_dy)
        if length < 0.01:
            fx, fy = car.get_forward_vector()
            return -fx, -fy

        return -wall_dx / length, -wall_dy / length

    def resolve_track_collision(self, car: Car) -> tuple[float, float]:
        """
        Calcula la normal, empuja el auto fuera del muro, y retorna la normal.
        """
        nx, ny = self.compute_wall_normal(car)

        for _ in range(self.MAX_SEPARATION_ITERS):
            car.x += nx * self.SEPARATION_STEP
            car.y += ny * self.SEPARATION_STEP
            car.update_sprite()
            if not self.track.check_car_collision(car.mask, car.rect):
                break

        return nx, ny

    # ── VUELTAS Y CHECKPOINTS ──

    def update_checkpoints(self, car: Car):
        """
        Actualiza checkpoints y vueltas usando zonas rectangulares.

        Cada frame verifica si el auto está dentro de la zona del siguiente
        checkpoint. Si pasa todos los checkpoints, incrementa la vuelta.
        """
        zones = self.track.checkpoint_zones
        n = len(zones)
        if n == 0 or car.next_checkpoint_index >= n:
            return
        zone = zones[car.next_checkpoint_index]
        if zone.collidepoint(int(car.x), int(car.y)):
            car.next_checkpoint_index += 1
            if car.next_checkpoint_index >= n:
                car.laps += 1
                car.next_checkpoint_index = 0

    # ── AUTO vs AUTO ──

    def check_car_vs_car(self, car_a: Car, car_b: Car) -> bool:
        """Verifica colisión entre dos autos."""
        offset = (car_b.rect.x - car_a.rect.x, car_b.rect.y - car_a.rect.y)
        return car_a.mask.overlap(car_b.mask, offset) is not None

    def resolve_car_vs_car(self, car_a: Car, car_b: Car):
        """Resuelve colisión entre dos autos empujándolos en direcciones opuestas."""
        dx = car_b.x - car_a.x
        dy = car_b.y - car_a.y
        dist = math.hypot(dx, dy)
        if dist < 1.0:
            dx, dy, dist = 1.0, 0.0, 1.0

        nx, ny = dx / dist, dy / dist
        push = 3.0
        car_a.x -= nx * push
        car_a.y -= ny * push
        car_b.x += nx * push
        car_b.y += ny * push
        car_a.speed *= 0.7
        car_b.speed *= 0.7

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

    def check_missile_vs_wall(self, missile: Missile) -> bool:
        """Verifica si un misil chocó con un muro de la pista."""
        if not missile.alive:
            return False
        ix, iy = int(missile.x), int(missile.y)
        if 0 <= ix < WORLD_WIDTH and 0 <= iy < WORLD_HEIGHT:
            return self.track.boundary_mask.get_at((ix, iy))
        return True  # fuera del mundo = destruir
