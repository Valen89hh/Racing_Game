"""
collision.py - Sistema de detección y resolución de colisiones.

Tile tracks: Circle vs Tile-AABB geométrico (intersección matemática real).
Classic tracks: Fallback a 16-point sampling contra boundary_mask.

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
    COLLISION_MAX_STEP,
)


class CollisionSystem:
    """
    Sistema de colisiones.

    Tile tracks: circle-vs-AABB geométrico (sin sampling, sin dependencia
    de ángulo ni redondeo). Detecta intersección aunque sea de 0.001px.

    Classic tracks: 16-point perimeter sampling contra boundary_mask
    (suficiente para bordes curvos generados por Chaikin).
    """

    def __init__(self, track):
        self.track = track

        # Detectar tipo de track
        self._use_tile_aabb = hasattr(track, 'terrain')

        if self._use_tile_aabb:
            from tile_defs import (
                TILE_SIZE, GRID_COLS, GRID_ROWS, T_EMPTY, is_driveable,
            )
            self._tile_size = TILE_SIZE
            self._grid_cols = GRID_COLS
            self._grid_rows = GRID_ROWS

            # Pre-computar grid de sólidos (una vez, en init)
            # Use track's embedded driveable_set if available (server-safe)
            terrain = track.terrain
            driveable_set = getattr(track, '_driveable_set', None)
            self._solid = []
            for row in range(GRID_ROWS):
                srow = []
                for col in range(GRID_COLS):
                    tid = terrain[row][col]
                    if driveable_set is not None:
                        solid = (tid == T_EMPTY) or (tid not in driveable_set)
                    else:
                        solid = (tid == T_EMPTY) or not is_driveable(tid)
                    srow.append(solid)
                self._solid.append(srow)

        # Pre-calcular ángulos para fallback mask (classic tracks)
        self._sample_angles = [
            (2.0 * math.pi * i) / CAR_COLLISION_SAMPLES
            for i in range(CAR_COLLISION_SAMPLES)
        ]
        self._cos_angles = [math.cos(a) for a in self._sample_angles]
        self._sin_angles = [math.sin(a) for a in self._sample_angles]

    # ══════════════════════════════════════════════
    # AUTO vs PISTA — Circle vs Tile AABB (geométrico)
    # ══════════════════════════════════════════════

    def _is_tile_solid(self, col, row):
        """Lookup rápido en grid pre-computado. Fuera de bounds = sólido."""
        if not (0 <= row < self._grid_rows and 0 <= col < self._grid_cols):
            return True
        return self._solid[row][col]

    def _circle_vs_tiles(self, cx, cy, r):
        """Intersección geométrica real: círculo vs tiles AABB.

        Calcula el punto más cercano del AABB al centro del círculo.
        Si la distancia al punto más cercano < radio → colisión.

        Revisa como máximo 4 tiles (radio 16 << tile 64).

        Returns:
            (hit, nx, ny, penetration)
            hit: True si hay colisión.
            nx, ny: normal de separación (apunta del muro hacia el auto).
            penetration: profundidad de penetración (para push-out exacto).
        """
        ts = self._tile_size
        r_sq = r * r

        min_col = int((cx - r) // ts)
        max_col = int((cx + r) // ts)
        min_row = int((cy - r) // ts)
        max_row = int((cy + r) // ts)

        total_nx = 0.0
        total_ny = 0.0
        max_pen = 0.0
        hit = False

        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                if not self._is_tile_solid(col, row):
                    continue

                # AABB del tile
                tile_left = col * ts
                tile_top = row * ts
                tile_right = tile_left + ts
                tile_bottom = tile_top + ts

                # Punto más cercano del AABB al centro del círculo
                closest_x = max(tile_left, min(cx, tile_right))
                closest_y = max(tile_top, min(cy, tile_bottom))

                dx = cx - closest_x
                dy = cy - closest_y
                dist_sq = dx * dx + dy * dy

                if dist_sq < r_sq:
                    hit = True

                    if dist_sq > 0.0001:
                        dist = math.sqrt(dist_sq)
                        pen = r - dist
                        nx = dx / dist
                        ny = dy / dist
                    else:
                        # Centro dentro del tile — push hacia borde más cercano
                        mid_x = tile_left + ts * 0.5
                        mid_y = tile_top + ts * 0.5
                        off_x = cx - mid_x
                        off_y = cy - mid_y
                        if abs(off_x) > abs(off_y):
                            nx = 1.0 if off_x > 0 else -1.0
                            ny = 0.0
                        else:
                            nx = 0.0
                            ny = 1.0 if off_y > 0 else -1.0
                        pen = r

                    # Ponderar por penetración (tiles con más overlap dominan)
                    total_nx += nx * pen
                    total_ny += ny * pen
                    if pen > max_pen:
                        max_pen = pen

        if hit:
            length = math.hypot(total_nx, total_ny)
            if length > 0.001:
                return True, total_nx / length, total_ny / length, max_pen
            # Fallback: normal opuesta al forward del auto
            return True, 0.0, 0.0, max_pen

        return False, 0.0, 0.0, 0.0

    # ══════════════════════════════════════════════
    # SPAWN SAFETY — push car out if spawned inside wall
    # ══════════════════════════════════════════════

    def ensure_valid_spawn(self, car: Car):
        """Si el auto spawneó dentro de un tile sólido, lo empuja afuera.

        Usa _circle_vs_tiles iterativamente (máx 10 pasos) para
        separar al auto del muro. Solo aplica a tile tracks.
        """
        if not self._use_tile_aabb:
            return

        orig_x, orig_y = car.x, car.y

        for _ in range(10):
            hit, nx, ny, pen = self._circle_vs_tiles(
                car.x, car.y, car.collision_radius)
            if not hit:
                if abs(car.x - orig_x) > 0.1 or abs(car.y - orig_y) > 0.1:
                    print(f"[DEBUG-SPAWN-FIX] car pid={car.player_id} "
                          f"moved from ({orig_x:.1f},{orig_y:.1f}) "
                          f"to ({car.x:.1f},{car.y:.1f})")
                return  # Libre, no hay nada que hacer

            if abs(nx) > 0.001 or abs(ny) > 0.001:
                # Push-out con margen extra de 1px
                car.x += nx * (pen + 1.0)
                car.y += ny * (pen + 1.0)
            else:
                # Normal degenerada — mover hacia centro del tile más cercano libre
                ts = self._tile_size
                col = int(car.x // ts)
                row = int(car.y // ts)
                # Buscar tile libre adyacente
                for dr, dc in [(0, 1), (0, -1), (1, 0), (-1, 0),
                                (1, 1), (1, -1), (-1, 1), (-1, -1)]:
                    nr, nc = row + dr, col + dc
                    if (0 <= nr < self._grid_rows and
                            0 <= nc < self._grid_cols and
                            not self._solid[nr][nc]):
                        car.x = nc * ts + ts * 0.5
                        car.y = nr * ts + ts * 0.5
                        return
                # No hay tile libre adyacente — push genérico
                car.x += ts * 0.5
                break

        car.update_sprite()

    # ══════════════════════════════════════════════
    # AUTO vs PISTA — Mask sampling (fallback para classic tracks)
    # ══════════════════════════════════════════════

    def _check_mask_collision(self, car):
        """16 puntos del perímetro contra boundary_mask."""
        mask = self.track.boundary_mask
        r = car.collision_radius

        for i in range(CAR_COLLISION_SAMPLES):
            sx = int(car.x + self._cos_angles[i] * r)
            sy = int(car.y + self._sin_angles[i] * r)

            if 0 <= sx < WORLD_WIDTH and 0 <= sy < WORLD_HEIGHT:
                if mask.get_at((sx, sy)):
                    return True
            else:
                return True
        return False

    def _compute_mask_normal(self, car):
        """Normal desde puntos penetrantes del perímetro (classic tracks)."""
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

    # ══════════════════════════════════════════════
    # API PÚBLICA — dispatch según tipo de track
    # ══════════════════════════════════════════════

    def check_track_collision(self, car: Car) -> bool:
        """Verifica si el auto colisiona con la pista."""
        if self._use_tile_aabb:
            hit, _, _, _ = self._circle_vs_tiles(car.x, car.y,
                                                  car.collision_radius)
            return hit
        return self._check_mask_collision(car)

    def compute_wall_normal(self, car: Car) -> tuple[float, float]:
        """Calcula la normal de la pared en la posición actual del auto."""
        if self._use_tile_aabb:
            hit, nx, ny, _ = self._circle_vs_tiles(car.x, car.y,
                                                    car.collision_radius)
            if hit and (abs(nx) > 0.001 or abs(ny) > 0.001):
                return (nx, ny)
            fx, fy = car.get_forward_vector()
            return (-fx, -fy)
        return self._compute_mask_normal(car)

    def move_with_substeps(self, car: Car, dt: float):
        """
        Movimiento sub-stepped con colisión integrada.

        Tile tracks: push-out geométrico (el auto queda tocando la pared,
        preserva movimiento tangencial).
        Classic tracks: rollback (el auto vuelve a la posición anterior).

        Returns:
            (hit_wall, normal, remaining_dt)
        """
        speed = math.hypot(car.velocity.x, car.velocity.y)
        total_dist = speed * dt

        if total_dist < 0.01:
            return False, None, 0.0

        steps = max(1, math.ceil(total_dist / COLLISION_MAX_STEP))
        sub_dt = dt / steps

        for s in range(steps):
            old_x, old_y = car.x, car.y
            car.x += car.velocity.x * sub_dt
            car.y += car.velocity.y * sub_dt

            if self._use_tile_aabb:
                hit, nx, ny, pen = self._circle_vs_tiles(
                    car.x, car.y, car.collision_radius)
                if hit:
                    # Push-out: separación exacta por penetración
                    if abs(nx) > 0.001 or abs(ny) > 0.001:
                        car.x += nx * pen
                        car.y += ny * pen
                    else:
                        # Normal degenerada — fallback a rollback
                        car.x = old_x
                        car.y = old_y

                    # Verificar que el push-out no metió al auto en otro tile
                    still_hit, _, _, _ = self._circle_vs_tiles(
                        car.x, car.y, car.collision_radius)
                    if still_hit:
                        # Esquina/corredor estrecho — rollback seguro
                        car.x = old_x
                        car.y = old_y

                    remaining = (steps - s - 1) * sub_dt
                    return True, (nx, ny), remaining
            else:
                if self._check_mask_collision(car):
                    normal = self._compute_mask_normal(car)
                    car.x = old_x
                    car.y = old_y
                    remaining = (steps - s - 1) * sub_dt
                    return True, normal, remaining

        return False, None, 0.0

    # ══════════════════════════════════════════════
    # VUELTAS Y CHECKPOINTS
    # ══════════════════════════════════════════════

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

    # ══════════════════════════════════════════════
    # AUTO vs AUTO (distancia simple)
    # ══════════════════════════════════════════════

    def check_car_vs_car(self, car_a: Car, car_b: Car) -> bool:
        """Verifica colisión entre dos autos por distancia de centros."""
        dx = car_b.x - car_a.x
        dy = car_b.y - car_a.y
        dist = math.hypot(dx, dy)
        min_dist = car_a.collision_radius + car_b.collision_radius
        return dist < min_dist

    def resolve_car_vs_car(self, car_a: Car, car_b: Car):
        """Resuelve colisión entre dos autos: push + reflejo de velocidad."""
        dx = car_b.x - car_a.x
        dy = car_b.y - car_a.y
        dist = math.hypot(dx, dy)
        if dist < 1.0:
            dx, dy, dist = 1.0, 0.0, 1.0

        nx, ny = dx / dist, dy / dist
        min_dist = car_a.collision_radius + car_b.collision_radius
        overlap = min_dist - dist

        # 1. Separar posiciones por overlap exacto + margen
        if overlap > 0:
            half = (overlap + 1.0) * 0.5
            car_a.x -= nx * half
            car_a.y -= ny * half
            car_b.x += nx * half
            car_b.y += ny * half

        # 2. Reflejo de velocidad sobre la normal de colisión
        dot_a = car_a.velocity.x * nx + car_a.velocity.y * ny
        dot_b = car_b.velocity.x * nx + car_b.velocity.y * ny

        if dot_a - dot_b > 0:
            car_a.velocity.x += (dot_b - dot_a) * nx
            car_a.velocity.y += (dot_b - dot_a) * ny
            car_b.velocity.x += (dot_a - dot_b) * nx
            car_b.velocity.y += (dot_a - dot_b) * ny

        # 3. Penalización de velocidad
        car_a.speed *= CAR_VS_CAR_SPEED_PENALTY
        car_b.speed *= CAR_VS_CAR_SPEED_PENALTY

    # ══════════════════════════════════════════════
    # POWER-UPS
    # ══════════════════════════════════════════════

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
        return True
