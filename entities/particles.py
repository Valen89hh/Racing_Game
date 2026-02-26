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
    SPARK_EMIT_RATE, SPARK_LIFETIME_MIN, SPARK_LIFETIME_MAX,
    SPARK_RADIUS, SPARK_SPEED,
    DRIFT_LEVEL_COLORS,
    SKID_MARK_POOL_SIZE, SKID_MARK_LIFETIME, SKID_MARK_WIDTH, SKID_MARK_COLOR,
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
    """Sistema de partículas de polvo con pool fijo (incluye sparks)."""

    def __init__(self):
        self._pool = [Particle() for _ in range(DUST_MAX_PARTICLES + 80)]
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

    def emit_drift_sparks(self, car):
        """Emite chispas coloreadas por nivel de mini-turbo desde ruedas traseras."""
        if not car.is_drifting or car.drift_level < 1:
            return

        lateral = car.get_lateral_speed()
        if lateral < DRIFT_LATERAL_THRESHOLD:
            return

        intensity = min(1.0, lateral / (car.effective_max_speed * 0.4))
        count = int(intensity * SPARK_EMIT_RATE) + (
            1 if random.random() < (intensity * SPARK_EMIT_RATE) % 1 else 0
        )
        if count < 1:
            return

        color = DRIFT_LEVEL_COLORS[min(car.drift_level - 1, 2)]
        # Variantes de brillo
        bright = (
            min(255, color[0] + 60),
            min(255, color[1] + 60),
            min(255, color[2] + 60),
        )

        wheels = car.get_rear_wheel_positions()
        for _ in range(count):
            p = self._acquire()
            p.alive = True

            # Spawn desde una rueda trasera aleatoria
            wx, wy = random.choice(wheels)
            p.x = wx + random.uniform(-3.0, 3.0)
            p.y = wy + random.uniform(-3.0, 3.0)

            # Velocidad: dispersión aleatoria
            angle = random.uniform(0, math.pi * 2)
            spd = random.uniform(SPARK_SPEED * 0.5, SPARK_SPEED)
            p.vx = math.cos(angle) * spd
            p.vy = math.sin(angle) * spd

            p.lifetime = random.uniform(SPARK_LIFETIME_MIN, SPARK_LIFETIME_MAX)
            p.max_lifetime = p.lifetime
            p.radius = SPARK_RADIUS
            p.color = random.choice([color, bright, (255, 255, 200)])

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


class SkidMark:
    """Un segmento de marca de derrape."""
    __slots__ = ('alive', 'x1', 'y1', 'x2', 'y2', 'lifetime', 'max_lifetime')

    def __init__(self):
        self.alive = False
        self.x1 = 0.0
        self.y1 = 0.0
        self.x2 = 0.0
        self.y2 = 0.0
        self.lifetime = 0.0
        self.max_lifetime = 0.0


class SkidMarkSystem:
    """Sistema de marcas de derrape en la pista."""

    def __init__(self):
        self._pool = [SkidMark() for _ in range(SKID_MARK_POOL_SIZE)]
        self._next = 0
        # Posiciones previas de ruedas por car_id: {id: [(x,y), (x,y)]}
        self._prev_wheels = {}

    def _acquire(self) -> SkidMark:
        pool = self._pool
        n = len(pool)
        for i in range(n):
            idx = (self._next + i) % n
            m = pool[idx]
            if not m.alive:
                self._next = (idx + 1) % n
                return m
        oldest = pool[self._next]
        self._next = (self._next + 1) % n
        return oldest

    def record_from_car(self, car):
        """Registra marcas de derrape si el auto está drifteando."""
        cid = car.player_id
        wheels = car.get_rear_wheel_positions()

        if not car.is_drifting or car.get_lateral_speed() < DRIFT_LATERAL_THRESHOLD:
            # No driftea: borrar posición previa para no conectar segmentos
            self._prev_wheels.pop(cid, None)
            return

        prev = self._prev_wheels.get(cid)
        if prev is not None:
            for i in range(2):
                px, py = prev[i]
                wx, wy = wheels[i]
                # Solo crear marca si se movió lo suficiente
                dx = wx - px
                dy = wy - py
                if dx * dx + dy * dy > 4.0:
                    m = self._acquire()
                    m.alive = True
                    m.x1 = px
                    m.y1 = py
                    m.x2 = wx
                    m.y2 = wy
                    m.lifetime = SKID_MARK_LIFETIME
                    m.max_lifetime = SKID_MARK_LIFETIME

        self._prev_wheels[cid] = wheels

    def update(self, dt: float):
        """Decrementa lifetime de las marcas."""
        for m in self._pool:
            if not m.alive:
                continue
            m.lifetime -= dt
            if m.lifetime <= 0:
                m.alive = False

    def draw(self, surface: pygame.Surface, camera):
        """Dibuja las marcas de derrape con alpha fade."""
        for m in self._pool:
            if not m.alive:
                continue
            # Visibilidad rápida (punto medio del segmento)
            mx = (m.x1 + m.x2) * 0.5
            my = (m.y1 + m.y2) * 0.5
            if not camera.is_visible(mx, my, 40):
                continue

            sx1, sy1 = camera.world_to_screen(m.x1, m.y1)
            sx2, sy2 = camera.world_to_screen(m.x2, m.y2)

            t = m.lifetime / m.max_lifetime
            alpha = int(180 * t)
            r, g, b = SKID_MARK_COLOR
            # Dibujar directamente con color atenuado (sin surface extra para rendimiento)
            color = (r + int((80 - r) * (1 - t)),
                     g + int((80 - g) * (1 - t)),
                     b + int((80 - b) * (1 - t)))
            pygame.draw.line(surface, color,
                             (int(sx1), int(sy1)), (int(sx2), int(sy2)),
                             SKID_MARK_WIDTH)

    def clear(self):
        """Limpia todas las marcas."""
        for m in self._pool:
            m.alive = False
        self._prev_wheels.clear()
