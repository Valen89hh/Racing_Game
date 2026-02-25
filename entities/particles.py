"""
particles.py - Sistema de partículas de polvo/tierra.

Partículas que aparecen detrás de los autos cuando corren,
dando feedback visual de velocidad.

Usa un pool fijo de partículas pre-alocadas para evitar
allocations por frame.
"""

import math
import random
import pygame

from settings import (
    DUST_MAX_PARTICLES, DUST_SPEED_THRESHOLD, DUST_EMIT_RATE,
    DUST_LIFETIME_MIN, DUST_LIFETIME_MAX,
    DUST_RADIUS_MIN, DUST_RADIUS_MAX,
    DUST_MAX_ALPHA, DUST_COLORS,
    DRIFT_SMOKE_RATE, DRIFT_SMOKE_COLORS, DRIFT_LATERAL_THRESHOLD,
)


class Particle:
    """Una partícula de polvo individual."""
    __slots__ = ('alive', 'x', 'y', 'vx', 'vy', 'lifetime', 'max_lifetime',
                 'radius', 'color')

    def __init__(self):
        self.alive = False
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.lifetime = 0.0
        self.max_lifetime = 0.0
        self.radius = 0.0
        self.color = (160, 130, 100)


class DustParticleSystem:
    """Sistema de partículas de polvo con pool fijo."""

    def __init__(self):
        self._pool = [Particle() for _ in range(DUST_MAX_PARTICLES)]
        self._next = 0  # índice circular para buscar partículas libres
        # Surface reutilizable para dibujar partículas
        self._surf = pygame.Surface((12, 12), pygame.SRCALPHA)

    def _acquire(self) -> Particle:
        """Obtiene una partícula libre del pool (circular)."""
        pool = self._pool
        n = len(pool)
        for i in range(n):
            idx = (self._next + i) % n
            p = pool[idx]
            if not p.alive:
                self._next = (idx + 1) % n
                return p
        # Pool lleno: reciclar la más vieja (menor lifetime)
        oldest = pool[self._next]
        self._next = (self._next + 1) % n
        return oldest

    def emit_from_car(self, car):
        """Emite partículas de polvo detrás de un carro según su velocidad."""
        speed = car.velocity.length()
        if speed < DUST_SPEED_THRESHOLD:
            return

        # Cantidad proporcional a velocidad (0..DUST_EMIT_RATE)
        t = min(1.0, (speed - DUST_SPEED_THRESHOLD) /
                (car.effective_max_speed - DUST_SPEED_THRESHOLD + 1.0))
        count = int(t * DUST_EMIT_RATE) + (1 if random.random() < (t * DUST_EMIT_RATE) % 1 else 0)
        if count < 1:
            return

        # Vector "detrás" del carro (misma convención que boost flame en car.py)
        rad = math.radians(car.angle)
        behind_x = -math.sin(rad)
        behind_y = math.cos(rad)
        # Vector lateral para spread
        lat_x = math.cos(rad)
        lat_y = math.sin(rad)

        for _ in range(count):
            p = self._acquire()
            p.alive = True

            # Spawn detrás del carro con spread lateral
            offset_back = random.uniform(18.0, 26.0)
            offset_lat = random.uniform(-8.0, 8.0)
            p.x = car.x + behind_x * offset_back + lat_x * offset_lat
            p.y = car.y + behind_y * offset_back + lat_y * offset_lat

            # Velocidad: drift hacia atrás + algo de dispersión
            p.vx = behind_x * random.uniform(10.0, 40.0) + random.uniform(-15.0, 15.0)
            p.vy = behind_y * random.uniform(10.0, 40.0) + random.uniform(-15.0, 15.0)

            p.lifetime = random.uniform(DUST_LIFETIME_MIN, DUST_LIFETIME_MAX)
            p.max_lifetime = p.lifetime
            p.radius = random.uniform(DUST_RADIUS_MIN, DUST_RADIUS_MAX)
            p.color = random.choice(DUST_COLORS)

    def emit_drift_smoke(self, car):
        """Emite partículas de humo durante drift (grises/blancas, más grandes)."""
        lateral = car.get_lateral_speed()
        if not car.is_drifting or lateral < DRIFT_LATERAL_THRESHOLD:
            return

        # Intensidad proporcional a la velocidad lateral
        intensity = min(1.0, lateral / (car.effective_max_speed * 0.5))
        count = int(intensity * DRIFT_SMOKE_RATE) + (
            1 if random.random() < (intensity * DRIFT_SMOKE_RATE) % 1 else 0
        )
        if count < 1:
            return

        # Vector "detrás" del carro
        rad = math.radians(car.angle)
        behind_x = -math.sin(rad)
        behind_y = math.cos(rad)
        # Vector lateral
        lat_x = math.cos(rad)
        lat_y = math.sin(rad)

        for _ in range(count):
            p = self._acquire()
            p.alive = True

            # Spawn desde ruedas traseras (desplazadas lateralmente)
            offset_back = random.uniform(16.0, 24.0)
            offset_lat = random.choice([-1, 1]) * random.uniform(8.0, 14.0)
            p.x = car.x + behind_x * offset_back + lat_x * offset_lat
            p.y = car.y + behind_y * offset_back + lat_y * offset_lat

            # Velocidad: dispersión lateral + algo hacia atrás
            p.vx = behind_x * random.uniform(5.0, 20.0) + random.uniform(-20.0, 20.0)
            p.vy = behind_y * random.uniform(5.0, 20.0) + random.uniform(-20.0, 20.0)

            # Mayor lifetime y radio que el polvo normal
            p.lifetime = random.uniform(0.5, 1.2)
            p.max_lifetime = p.lifetime
            p.radius = random.uniform(3.0, 7.0)
            p.color = random.choice(DRIFT_SMOKE_COLORS)

    def update(self, dt: float):
        """Actualiza todas las partículas vivas."""
        for p in self._pool:
            if not p.alive:
                continue
            p.lifetime -= dt
            if p.lifetime <= 0:
                p.alive = False
                continue
            # Mover con damping
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vx *= 0.95
            p.vy *= 0.95

    def draw(self, surface: pygame.Surface, camera):
        """Dibuja las partículas vivas en coordenadas de pantalla."""
        surf = self._surf
        for p in self._pool:
            if not p.alive:
                continue
            if not camera.is_visible(p.x, p.y, 10):
                continue

            sx, sy = camera.world_to_screen(p.x, p.y)

            # Interpolación de vida: 1.0 (recién nacida) → 0.0 (muerta)
            t = p.lifetime / p.max_lifetime
            alpha = int(DUST_MAX_ALPHA * t)
            radius = max(1, int(p.radius * (0.4 + 0.6 * t)))

            # Dibujar círculo con alpha
            size = radius * 2 + 2
            surf = pygame.Surface((size, size), pygame.SRCALPHA)
            surf.fill((0, 0, 0, 0))
            pygame.draw.circle(surf, (*p.color, alpha), (size // 2, size // 2), radius)
            surface.blit(surf, (int(sx) - size // 2, int(sy) - size // 2))

    def clear(self):
        """Mata todas las partículas (para reset de carrera)."""
        for p in self._pool:
            p.alive = False
