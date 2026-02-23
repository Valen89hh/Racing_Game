"""
editor_collision.py - Modal collision polygon editor.

Displays a zoomed-up tile sprite and lets the user draw/edit a collision
polygon by placing, moving, and deleting vertices.

Controls:
  Left-click         Add vertex (or start dragging existing one)
  Right-click        Remove nearest vertex
  Enter / Return     Confirm polygon -> save to TileMeta
  Escape             Cancel (discard changes)
  G                  Cycle snap grid (off, 8, 16, 32 subdivisions)
"""

from __future__ import annotations

import math
import pygame

from tile_defs import get_tile_sprite, TILE_SIZE
from tile_meta import get_manager, COLL_POLYGON


# ── Layout ──
MODAL_W = 500
MODAL_H = 420
PREVIEW_SIZE = 320   # tile is scaled to this size
MARGIN = 20
SNAP_OPTIONS = [0, 8, 16, 32]  # 0 = off

# ── Colours ──
COL_BG = (20, 20, 30, 240)
COL_BORDER = (80, 120, 200)
COL_GRID = (60, 60, 80)
COL_POLY_FILL = (255, 80, 80, 60)
COL_POLY_LINE = (255, 100, 100)
COL_VERTEX = (255, 220, 50)
COL_VERTEX_HOVER = (100, 220, 255)
COL_WHITE = (255, 255, 255)
COL_GRAY = (140, 140, 140)

VERTEX_RADIUS = 6
VERTEX_GRAB_DIST = 12


class CollisionEditor:
    """Modal overlay for editing a tile's collision polygon."""

    def __init__(self, screen: pygame.Surface, tile_id: int):
        self.screen = screen
        self.tile_id = tile_id
        self.done = False
        self._cancelled = False

        sw, sh = screen.get_size()
        self.ox = (sw - MODAL_W) // 2
        self.oy = (sh - MODAL_H) // 2

        self.font = pygame.font.SysFont("consolas", 14)
        self.font_small = pygame.font.SysFont("consolas", 12)

        # Load current polygon from metadata
        mgr = get_manager()
        meta = mgr.get(tile_id)
        if meta.collision_polygon:
            self.vertices = [list(v) for v in meta.collision_polygon]
        else:
            self.vertices = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]

        # Preview origin (top-left of the preview tile)
        self.px = self.ox + MARGIN
        self.py = self.oy + MARGIN + 24  # below title bar

        # Snap grid
        self.snap_idx = 0  # index into SNAP_OPTIONS

        # Dragging
        self.dragging_idx = -1

        # Scaled tile sprite
        sprite = get_tile_sprite(tile_id)
        if sprite is not None:
            self.tile_surf = pygame.transform.scale(sprite,
                                                     (PREVIEW_SIZE, PREVIEW_SIZE))
        else:
            self.tile_surf = pygame.Surface((PREVIEW_SIZE, PREVIEW_SIZE))
            self.tile_surf.fill((60, 60, 60))

    # ── Coordinate helpers ──

    def _norm_to_screen(self, nx, ny):
        """Normalised [0,1] -> screen pixel."""
        return (self.px + int(nx * PREVIEW_SIZE),
                self.py + int(ny * PREVIEW_SIZE))

    def _screen_to_norm(self, sx, sy):
        """Screen pixel -> normalised [0,1]."""
        nx = (sx - self.px) / PREVIEW_SIZE
        ny = (sy - self.py) / PREVIEW_SIZE
        return nx, ny

    def _snap(self, val):
        """Snap a normalised value to the current grid."""
        subdiv = SNAP_OPTIONS[self.snap_idx]
        if subdiv == 0:
            return val
        step = 1.0 / subdiv
        return round(val / step) * step

    def _nearest_vertex(self, sx, sy):
        """Return index of nearest vertex within grab distance, or -1."""
        best_dist = VERTEX_GRAB_DIST ** 2
        best_idx = -1
        for i, (vx, vy) in enumerate(self.vertices):
            vsx, vsy = self._norm_to_screen(vx, vy)
            d2 = (sx - vsx) ** 2 + (sy - vsy) ** 2
            if d2 < best_dist:
                best_dist = d2
                best_idx = i
        return best_idx

    # ── Events ──

    def handle_event(self, event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.done = True
                self._cancelled = True
                return True
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._save_and_close()
                return True
            if event.key == pygame.K_g:
                self.snap_idx = (self.snap_idx + 1) % len(SNAP_OPTIONS)
                return True

        elif event.type == pygame.MOUSEBUTTONDOWN:
            sx, sy = event.pos
            if not self._in_preview(sx, sy):
                return True

            if event.button == 1:
                idx = self._nearest_vertex(sx, sy)
                if idx >= 0:
                    self.dragging_idx = idx
                else:
                    # Add new vertex
                    nx, ny = self._screen_to_norm(sx, sy)
                    nx = max(0.0, min(1.0, self._snap(nx)))
                    ny = max(0.0, min(1.0, self._snap(ny)))
                    # Insert after nearest edge
                    ins = self._best_insert_index(nx, ny)
                    self.vertices.insert(ins, [nx, ny])
                return True

            if event.button == 3:
                idx = self._nearest_vertex(sx, sy)
                if idx >= 0 and len(self.vertices) > 3:
                    self.vertices.pop(idx)
                return True

        elif event.type == pygame.MOUSEBUTTONUP:
            self.dragging_idx = -1

        elif event.type == pygame.MOUSEMOTION:
            if self.dragging_idx >= 0:
                sx, sy = event.pos
                nx, ny = self._screen_to_norm(sx, sy)
                nx = max(0.0, min(1.0, self._snap(nx)))
                ny = max(0.0, min(1.0, self._snap(ny)))
                self.vertices[self.dragging_idx] = [nx, ny]
                return True

        return True

    def _in_preview(self, sx, sy):
        return (self.px <= sx < self.px + PREVIEW_SIZE and
                self.py <= sy < self.py + PREVIEW_SIZE)

    def _best_insert_index(self, nx, ny):
        """Find the edge where inserting a new vertex produces least distortion."""
        if len(self.vertices) < 2:
            return len(self.vertices)
        best_dist = float('inf')
        best_i = len(self.vertices)
        for i in range(len(self.vertices)):
            j = (i + 1) % len(self.vertices)
            ax, ay = self.vertices[i]
            bx, by = self.vertices[j]
            # Distance from point to segment midpoint
            mx = (ax + bx) / 2
            my = (ay + by) / 2
            d = (nx - mx) ** 2 + (ny - my) ** 2
            if d < best_dist:
                best_dist = d
                best_i = j
        return best_i

    def _save_and_close(self):
        mgr = get_manager()
        meta = mgr.get(self.tile_id)
        meta.collision_type = COLL_POLYGON
        meta.collision_polygon = [list(v) for v in self.vertices]
        mgr.set(self.tile_id, meta)
        mgr.save()
        self.done = True

    # ── Drawing ──

    def draw(self, surface: pygame.Surface):
        # Dim background
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        surface.blit(overlay, (0, 0))

        # Modal background
        modal_surf = pygame.Surface((MODAL_W, MODAL_H), pygame.SRCALPHA)
        modal_surf.fill(COL_BG)
        pygame.draw.rect(modal_surf, COL_BORDER, (0, 0, MODAL_W, MODAL_H), 2)
        surface.blit(modal_surf, (self.ox, self.oy))

        # Title
        title = self.font.render(f"Collision Editor - Tile #{self.tile_id}",
                                 True, COL_WHITE)
        surface.blit(title, (self.ox + MARGIN, self.oy + 6))

        # Tile sprite
        surface.blit(self.tile_surf, (self.px, self.py))

        # Snap grid
        subdiv = SNAP_OPTIONS[self.snap_idx]
        if subdiv > 0:
            for i in range(1, subdiv):
                t = i / subdiv
                x = self.px + int(t * PREVIEW_SIZE)
                y = self.py + int(t * PREVIEW_SIZE)
                pygame.draw.line(surface, COL_GRID,
                                 (x, self.py), (x, self.py + PREVIEW_SIZE))
                pygame.draw.line(surface, COL_GRID,
                                 (self.px, y), (self.px + PREVIEW_SIZE, y))

        # Polygon fill
        if len(self.vertices) >= 3:
            points = [self._norm_to_screen(v[0], v[1]) for v in self.vertices]
            poly_surf = pygame.Surface((PREVIEW_SIZE, PREVIEW_SIZE), pygame.SRCALPHA)
            local_pts = [(p[0] - self.px, p[1] - self.py) for p in points]
            pygame.draw.polygon(poly_surf, COL_POLY_FILL, local_pts)
            surface.blit(poly_surf, (self.px, self.py))

            # Outline
            pygame.draw.polygon(surface, COL_POLY_LINE, points, 2)

        # Vertices
        mx, my = pygame.mouse.get_pos()
        hover_idx = self._nearest_vertex(mx, my)
        for i, (vx, vy) in enumerate(self.vertices):
            sx, sy = self._norm_to_screen(vx, vy)
            col = COL_VERTEX_HOVER if i == hover_idx else COL_VERTEX
            pygame.draw.circle(surface, col, (sx, sy), VERTEX_RADIUS)
            pygame.draw.circle(surface, COL_WHITE, (sx, sy), VERTEX_RADIUS, 1)

        # Border around preview
        pygame.draw.rect(surface, COL_BORDER,
                         (self.px - 1, self.py - 1,
                          PREVIEW_SIZE + 2, PREVIEW_SIZE + 2), 1)

        # Instructions on the right
        ix = self.px + PREVIEW_SIZE + 16
        iy = self.py
        instructions = [
            "Left-click: add vertex",
            "  or drag existing",
            "Right-click: remove",
            "",
            f"Grid: {subdiv if subdiv else 'off'} (G)",
            f"Vertices: {len(self.vertices)}",
            "",
            "ENTER: confirm",
            "ESC: cancel",
        ]
        for i, line in enumerate(instructions):
            col = COL_GRAY if not line else COL_WHITE
            surface.blit(self.font_small.render(line, True, col),
                         (ix, iy + i * 18))
