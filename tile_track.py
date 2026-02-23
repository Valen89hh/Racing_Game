"""
tile_track.py - Pista construida a partir de tiles.

TileTrack genera un objeto compatible con Track desde datos de tiles,
permitiendo que todos los sistemas del juego (AI, colision, camera)
funcionen sin modificaciones.
"""

import math
import pygame

from settings import (
    WORLD_WIDTH, WORLD_HEIGHT, SCREEN_WIDTH, SCREEN_HEIGHT,
    MINIMAP_SCALE, COLOR_MINIMAP_BG,
)
from tile_defs import (
    TILE_SIZE, GRID_COLS, GRID_ROWS,
    T_EMPTY, T_FINISH, is_driveable,
    GRASS_COLOR, get_tile_sprite,
)
from tile_collision import build_boundary_mask, build_friction_map


class TileTrack:
    """
    Pista basada en tiles, compatible con la interfaz de Track.

    Atributos requeridos por los sistemas:
        waypoints, checkpoints, num_checkpoints, start_positions,
        powerup_spawn_points, finish_line, boundary_mask,
        boundary_surface, track_surface, minimap_surface

    Metodos requeridos:
        draw(surface, camera), check_car_collision(mask, rect),
        check_finish_line_cross(ox, oy, nx, ny),
        get_minimap_pos(wx, wy), is_on_track(x, y)
    """

    def __init__(self, tile_data: dict):
        self.terrain = tile_data["terrain"]
        self._tile_overrides = tile_data.get("tile_overrides", None)
        self.rotations = tile_data.get("rotations", None)
        if self.rotations is None:
            self.rotations = [[0] * GRID_COLS for _ in range(GRID_ROWS)]

        # ── Pre-render ──
        self.track_surface = self._render_track()
        self.boundary_mask, self.boundary_surface = self._create_boundary_mask()

        # ── Friction map ──
        self.friction_map = build_friction_map(
            self.terrain, overrides=self._tile_overrides)

        # ── Finish line ──
        self.finish_line = self._find_finish_line()

        # ── Waypoints (auto-generados via DFS) ──
        raw_path = self._trace_circuit()
        self.waypoints = self._sample_waypoints(raw_path, target=60)

        # ── Checkpoints ──
        self.checkpoints = self._distribute_points(self.waypoints, 6)
        self.num_checkpoints = len(self.checkpoints)

        # ── Start positions ──
        self.start_positions = self._compute_start_positions(raw_path)

        # ── Power-up spawn points ──
        self.powerup_spawn_points = self._distribute_points(self.waypoints, 7)

        # ── Minimap ──
        self.minimap_surface = self._render_minimap()

    # ────────────────────────────────────────────
    # RENDERING
    # ────────────────────────────────────────────

    def _render_track(self) -> pygame.Surface:
        """Pre-renderiza toda la pista."""
        surface = pygame.Surface((WORLD_WIDTH, WORLD_HEIGHT))
        surface.fill(GRASS_COLOR)

        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                tid = self.terrain[row][col]
                if tid == T_EMPTY:
                    continue
                rot = self.rotations[row][col]
                sprite = get_tile_sprite(tid, rot)
                if sprite is not None:
                    surface.blit(sprite, (col * TILE_SIZE, row * TILE_SIZE))

        return surface

    def _create_boundary_mask(self):
        """
        Crea mascara de colision usando el nuevo builder con soporte
        para collision_type none/full/polygon por tile.
        """
        return build_boundary_mask(self.terrain, rotations=self.rotations)

    # ────────────────────────────────────────────
    # FINISH LINE
    # ────────────────────────────────────────────

    def _find_finish_line(self):
        finish_tiles = []
        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                if self.terrain[row][col] == T_FINISH:
                    finish_tiles.append((row, col))

        if not finish_tiles:
            return ((WORLD_WIDTH // 2 - 50, WORLD_HEIGHT // 2),
                    (WORLD_WIDTH // 2 + 50, WORLD_HEIGHT // 2))

        avg_col = sum(c for _, c in finish_tiles) / len(finish_tiles)
        avg_row = sum(r for r, _ in finish_tiles) / len(finish_tiles)
        cx = avg_col * TILE_SIZE + TILE_SIZE // 2
        cy = avg_row * TILE_SIZE + TILE_SIZE // 2

        direction = self._infer_track_direction(finish_tiles)
        perp_x = -direction[1]
        perp_y = direction[0]
        half_w = max(len(finish_tiles) * TILE_SIZE // 2, TILE_SIZE)

        return (
            (cx + perp_x * half_w, cy + perp_y * half_w),
            (cx - perp_x * half_w, cy - perp_y * half_w),
        )

    def _infer_track_direction(self, finish_tiles):
        if not finish_tiles:
            return (1, 0)
        rows = set(r for r, _ in finish_tiles)
        cols = set(c for _, c in finish_tiles)

        if len(rows) == 1 and len(cols) > 1:
            return (0, 1)
        if len(cols) == 1 and len(rows) > 1:
            return (1, 0)

        for r, c in finish_tiles:
            if self._is_driveable_at(r - 1, c) or self._is_driveable_at(r + 1, c):
                return (0, 1)
            if self._is_driveable_at(r, c - 1) or self._is_driveable_at(r, c + 1):
                return (1, 0)
        return (1, 0)

    def _is_driveable_at(self, row, col):
        if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
            return is_driveable(self.terrain[row][col])
        return False

    # ────────────────────────────────────────────
    # CIRCUIT TRACING
    # ────────────────────────────────────────────

    def _trace_circuit(self):
        start = None
        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                if self.terrain[row][col] == T_FINISH:
                    start = (row, col)
                    break
            if start:
                break

        if start is None:
            for row in range(GRID_ROWS):
                for col in range(GRID_COLS):
                    if is_driveable(self.terrain[row][col]):
                        start = (row, col)
                        break
                if start:
                    break

        if start is None:
            return [(GRID_ROWS // 2, GRID_COLS // 2)]

        path = [start]
        visited = {start}
        DIRS = [(-1, 0), (0, 1), (1, 0), (0, -1)]

        current = start
        prev_dir = None

        for _ in range(GRID_ROWS * GRID_COLS):
            r, c = current
            neighbors = []

            for di, (dr, dc) in enumerate(DIRS):
                nr, nc = r + dr, c + dc
                if (nr, nc) == start and len(path) > 3:
                    return path

                if (nr, nc) in visited:
                    continue
                if not (0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS):
                    continue
                if not is_driveable(self.terrain[nr][nc]):
                    continue

                if prev_dir is not None:
                    diff = abs(di - prev_dir)
                    if diff > 2:
                        diff = 4 - diff
                    priority = diff
                else:
                    priority = 0

                neighbors.append((priority, nr, nc, di))

            if not neighbors:
                break

            neighbors.sort(key=lambda x: x[0])
            _, nr, nc, di = neighbors[0]
            current = (nr, nc)
            path.append(current)
            visited.add(current)
            prev_dir = di

        return path

    def _sample_waypoints(self, path, target=60):
        if len(path) <= 1:
            cx = WORLD_WIDTH // 2
            cy = WORLD_HEIGHT // 2
            return [(cx, cy), (cx + 100, cy), (cx + 100, cy + 100), (cx, cy + 100)]

        world_path = [
            (col * TILE_SIZE + TILE_SIZE // 2,
             row * TILE_SIZE + TILE_SIZE // 2)
            for row, col in path
        ]

        if len(world_path) <= target:
            return world_path

        step = max(1, len(world_path) // target)
        return [world_path[i] for i in range(0, len(world_path), step)]

    def _distribute_points(self, waypoints, count):
        if len(waypoints) < count:
            return list(waypoints)
        step = max(1, len(waypoints) // count)
        return [waypoints[i * step % len(waypoints)] for i in range(count)]

    # ────────────────────────────────────────────
    # START POSITIONS
    # ────────────────────────────────────────────

    def _compute_start_positions(self, raw_path):
        if len(raw_path) < 4:
            return [
                (WORLD_WIDTH // 2 - 30, WORLD_HEIGHT // 2, 0),
                (WORLD_WIDTH // 2 + 30, WORLD_HEIGHT // 2, 0),
            ]

        idx1 = max(0, len(raw_path) - 3)
        idx2 = max(0, len(raw_path) - 8)

        r1, c1 = raw_path[idx1]
        r2, c2 = raw_path[idx2]

        x1 = c1 * TILE_SIZE + TILE_SIZE // 2
        y1 = r1 * TILE_SIZE + TILE_SIZE // 2
        x2 = c2 * TILE_SIZE + TILE_SIZE // 2
        y2 = r2 * TILE_SIZE + TILE_SIZE // 2

        if len(raw_path) >= 5:
            idx_back = max(0, idx1 - 3)
            idx_fwd = min(len(raw_path) - 1, idx1 + 3)
            rb, cb = raw_path[idx_back]
            rf, cf = raw_path[idx_fwd]
            dx = (cf - cb) * TILE_SIZE
            dy = (rf - rb) * TILE_SIZE
            angle = math.degrees(math.atan2(dx, -dy)) % 360
        else:
            angle = 0

        angle_rad = math.radians(angle)
        perp_x = math.cos(angle_rad)
        perp_y = -math.sin(angle_rad)
        lateral = 22

        return [
            (x1 + perp_x * lateral, y1 + perp_y * lateral, angle),
            (x2 - perp_x * lateral, y2 - perp_y * lateral, angle),
        ]

    # ────────────────────────────────────────────
    # MINIMAP
    # ────────────────────────────────────────────

    def _render_minimap(self) -> pygame.Surface:
        w = int(WORLD_WIDTH * MINIMAP_SCALE)
        h = int(WORLD_HEIGHT * MINIMAP_SCALE)
        surface = pygame.Surface((w + 10, h + 10), pygame.SRCALPHA)
        surface.fill(COLOR_MINIMAP_BG)

        s = MINIMAP_SCALE
        tile_w = max(1, int(TILE_SIZE * s))
        tile_h = max(1, int(TILE_SIZE * s))

        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                tid = self.terrain[row][col]
                if is_driveable(tid):
                    color = (90, 90, 90)
                elif tid != T_EMPTY:
                    color = (60, 80, 60)
                else:
                    continue
                x = int(col * TILE_SIZE * s) + 5
                y = int(row * TILE_SIZE * s) + 5
                pygame.draw.rect(surface, color, (x, y, tile_w, tile_h))

        return surface

    def get_minimap_pos(self, world_x: float, world_y: float) -> tuple:
        return (int(world_x * MINIMAP_SCALE) + 5,
                int(world_y * MINIMAP_SCALE) + 5)

    # ────────────────────────────────────────────
    # COLLISION / QUERIES
    # ────────────────────────────────────────────

    def is_on_track(self, x: float, y: float) -> bool:
        ix, iy = int(x), int(y)
        if 0 <= ix < WORLD_WIDTH and 0 <= iy < WORLD_HEIGHT:
            return not self.boundary_mask.get_at((ix, iy))
        return False

    def get_friction_at(self, x: float, y: float) -> float:
        """Return the friction value at world position (x, y)."""
        col = int(x // TILE_SIZE)
        row = int(y // TILE_SIZE)
        if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
            return self.friction_map[row][col]
        return 1.0

    def check_car_collision(self, car_mask, car_rect) -> bool:
        offset = (car_rect.x, car_rect.y)
        return self.boundary_mask.overlap(car_mask, offset) is not None

    def check_finish_line_cross(self, old_x: float, old_y: float,
                                new_x: float, new_y: float) -> bool:
        fx1, fy1 = self.finish_line[0]
        fx2, fy2 = self.finish_line[1]
        return self._segments_intersect(
            old_x, old_y, new_x, new_y,
            fx1, fy1, fx2, fy2,
        )

    @staticmethod
    def _segments_intersect(x1, y1, x2, y2, x3, y3, x4, y4) -> bool:
        def cross(ox, oy, ax, ay, bx, by):
            return (ax - ox) * (by - oy) - (ay - oy) * (bx - ox)

        d1 = cross(x3, y3, x4, y4, x1, y1)
        d2 = cross(x3, y3, x4, y4, x2, y2)
        d3 = cross(x1, y1, x2, y2, x3, y3)
        d4 = cross(x1, y1, x2, y2, x4, y4)

        if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
           ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
            return True
        return False

    # ────────────────────────────────────────────
    # DRAW
    # ────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, camera):
        half_diag = int(math.hypot(SCREEN_WIDTH, SCREEN_HEIGHT) / 2) + 2
        chunk_size = half_diag * 2

        src_x = int(camera.cx) - half_diag
        src_y = int(camera.cy) - half_diag

        chunk = pygame.Surface((chunk_size, chunk_size))
        chunk.fill(GRASS_COLOR)

        blit_x = max(0, -src_x)
        blit_y = max(0, -src_y)
        world_x = max(0, src_x)
        world_y = max(0, src_y)
        w = min(chunk_size - blit_x, WORLD_WIDTH - world_x)
        h = min(chunk_size - blit_y, WORLD_HEIGHT - world_y)

        if w > 0 and h > 0:
            chunk.blit(self.track_surface, (blit_x, blit_y),
                       pygame.Rect(world_x, world_y, int(w), int(h)))

        rotated = pygame.transform.rotate(chunk, camera.angle)

        rw, rh = rotated.get_size()
        crop_x = (rw - SCREEN_WIDTH) // 2
        crop_y = (rh - SCREEN_HEIGHT) // 2

        surface.blit(rotated, (0, 0),
                     pygame.Rect(crop_x, crop_y, SCREEN_WIDTH, SCREEN_HEIGHT))
