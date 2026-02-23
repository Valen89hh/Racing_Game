"""
tile_brush.py - Multi-tile brush system.

Brush: rectangular grid of tile IDs that can be stamped onto terrain.
BrushLibrary: persistence of saved brushes in brushes/*.json.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import pygame

from tile_defs import T_EMPTY, GRID_ROWS, GRID_COLS, get_tile_sprite

# Directory for saved brushes
_BRUSHES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "brushes")


class Brush:
    """Rectangular grid of tile IDs with per-cell rotations."""

    def __init__(self, tiles: list[list[int]], name: str = "",
                 rotations: list[list[int]] | None = None):
        self.tiles = tiles
        self.height = len(tiles)
        self.width = len(tiles[0]) if tiles else 0
        self.name = name
        if rotations is not None:
            self.rotations = rotations
        else:
            self.rotations = [[0] * self.width for _ in range(self.height)]

    @staticmethod
    def single(tile_id: int, rotation: int = 0) -> Brush:
        """Create a 1x1 brush from a single tile."""
        return Brush([[tile_id]], name="", rotations=[[rotation]])

    @staticmethod
    def from_selection(terrain: list[list[int]],
                       start_row: int, start_col: int,
                       end_row: int, end_col: int) -> Brush:
        """Create a brush from a rectangular region of the tileset or terrain.

        Coordinates are inclusive.  If start > end they are swapped.
        """
        r0, r1 = sorted((start_row, end_row))
        c0, c1 = sorted((start_col, end_col))
        tiles = []
        for r in range(r0, r1 + 1):
            row = []
            for c in range(c0, c1 + 1):
                if 0 <= r < len(terrain) and 0 <= c < len(terrain[0]):
                    row.append(terrain[r][c])
                else:
                    row.append(T_EMPTY)
            tiles.append(row)
        return Brush(tiles)

    @staticmethod
    def from_tileset_rect(start_row: int, start_col: int,
                          end_row: int, end_col: int) -> Brush:
        """Create a brush by selecting a rectangle from the tileset source grid.

        Uses tile_defs.get_tile_at_position to map (row,col) to tile_id.
        """
        from tile_defs import get_tile_at_position
        r0, r1 = sorted((start_row, end_row))
        c0, c1 = sorted((start_col, end_col))
        tiles = []
        for r in range(r0, r1 + 1):
            row = []
            for c in range(c0, c1 + 1):
                tid = get_tile_at_position(r, c)
                row.append(tid if tid is not None else T_EMPTY)
            tiles.append(row)
        return Brush(tiles)

    def paint_at(self, terrain: list[list[int]], row: int, col: int,
                 rotations_grid: list[list[int]] | None = None,
                 rotation_offset: int = 0):
        """Stamp this brush onto terrain at (row, col).
        T_EMPTY cells in the brush are treated as transparent (not painted).

        Args:
            rotations_grid: the editor's rotation grid to write into.
            rotation_offset: additional rotation (0-3) applied to each cell.
        """
        for dr in range(self.height):
            for dc in range(self.width):
                tid = self.tiles[dr][dc]
                if tid == T_EMPTY:
                    continue
                r = row + dr
                c = col + dc
                if 0 <= r < GRID_ROWS and 0 <= c < GRID_COLS:
                    terrain[r][c] = tid
                    if rotations_grid is not None:
                        rot = (self.rotations[dr][dc] + rotation_offset) % 4
                        rotations_grid[r][c] = rot

    def get_preview_surface(self, cell_size: int = 32,
                            rotation_offset: int = 0) -> pygame.Surface:
        """Render a small preview of this brush."""
        w = self.width * cell_size
        h = self.height * cell_size
        surf = pygame.Surface((max(1, w), max(1, h)), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        for dr in range(self.height):
            for dc in range(self.width):
                tid = self.tiles[dr][dc]
                if tid == T_EMPTY:
                    continue
                rot = (self.rotations[dr][dc] + rotation_offset) % 4
                sprite = get_tile_sprite(tid, rot)
                if sprite is not None:
                    scaled = pygame.transform.scale(sprite, (cell_size, cell_size))
                    surf.blit(scaled, (dc * cell_size, dr * cell_size))
                else:
                    pygame.draw.rect(surf, (80, 80, 80),
                                     (dc * cell_size, dr * cell_size,
                                      cell_size, cell_size))
        return surf

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "tiles": self.tiles,
        }
        # Only include rotations if any non-zero
        if any(r != 0 for row in self.rotations for r in row):
            d["rotations"] = self.rotations
        return d

    @staticmethod
    def from_dict(d: dict) -> Brush:
        return Brush(
            tiles=d["tiles"],
            name=d.get("name", ""),
            rotations=d.get("rotations"),
        )


class BrushLibrary:
    """Manages saved brushes persisted in brushes/ directory."""

    def __init__(self):
        self.brushes: list[Brush] = []
        self._load_all()

    def _load_all(self):
        self.brushes = []
        if not os.path.isdir(_BRUSHES_DIR):
            return
        for fname in sorted(os.listdir(_BRUSHES_DIR)):
            if not fname.endswith(".json"):
                continue
            try:
                path = os.path.join(_BRUSHES_DIR, fname)
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.brushes.append(Brush.from_dict(data))
            except (json.JSONDecodeError, OSError, KeyError):
                continue

    def save_brush(self, brush: Brush):
        """Save a brush to disk.  Uses its name for filename."""
        os.makedirs(_BRUSHES_DIR, exist_ok=True)
        name = brush.name.strip() or f"brush_{len(self.brushes)}"
        brush.name = name
        filename = name.lower().replace(" ", "_") + ".json"
        path = os.path.join(_BRUSHES_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(brush.to_dict(), f, indent=None)
        # Add to list if not already there
        existing = [b for b in self.brushes if b.name == brush.name]
        if existing:
            idx = self.brushes.index(existing[0])
            self.brushes[idx] = brush
        else:
            self.brushes.append(brush)

    def delete_brush(self, name: str):
        """Remove a brush by name."""
        self.brushes = [b for b in self.brushes if b.name != name]
        filename = name.lower().replace(" ", "_") + ".json"
        path = os.path.join(_BRUSHES_DIR, filename)
        if os.path.exists(path):
            os.remove(path)

    def list_brushes(self) -> list[Brush]:
        return list(self.brushes)
