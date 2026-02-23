"""
tile_collision.py - Per-tile collision shapes and boundary mask builder.

CollisionShape: normalised polygon vertices (0-1) that can be rasterised
into a pygame.mask.Mask at any tile size.

build_boundary_mask(): constructs the world-sized collision mask from the
terrain grid using each tile's collision_type metadata (none/full/polygon).

build_friction_map(): constructs a 2D grid of friction values matching the
terrain grid.
"""

from __future__ import annotations

import pygame

from tile_defs import (
    TILE_SIZE, GRID_COLS, GRID_ROWS,
    T_EMPTY, T_FINISH,
    GRASS_COLOR,
)
from tile_meta import (
    get_manager,
    COLL_NONE, COLL_FULL, COLL_POLYGON,
)
from settings import WORLD_WIDTH, WORLD_HEIGHT


class CollisionShape:
    """Polygon collision shape with vertices normalised to [0, 1]."""

    def __init__(self, vertices: list[tuple[float, float]]):
        self.vertices = vertices  # [(x, y), ...] in 0..1 space

    @staticmethod
    def full_tile() -> CollisionShape:
        return CollisionShape([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])

    def to_mask(self, tile_size: int = TILE_SIZE) -> pygame.mask.Mask:
        """Rasterise polygon to a mask of the given tile size."""
        surf = pygame.Surface((tile_size, tile_size), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        if len(self.vertices) >= 3:
            points = [(int(v[0] * tile_size), int(v[1] * tile_size))
                      for v in self.vertices]
            pygame.draw.polygon(surf, (255, 255, 255, 255), points)
        return pygame.mask.from_surface(surf)

    def to_dict(self) -> list:
        return [list(v) for v in self.vertices]

    @staticmethod
    def from_list(data: list) -> CollisionShape:
        return CollisionShape([(v[0], v[1]) for v in data])


def rotate_polygon(polygon, rotation):
    """Rotate normalised polygon vertices (0-1 space) by rotation*90 degrees clockwise.

    Args:
        polygon: list of [x, y] pairs in 0..1 space.
        rotation: 0-3 (0=0deg, 1=90deg CW, 2=180deg, 3=270deg CW).
    Returns:
        New list of [x, y] pairs.
    """
    if rotation == 0 or not polygon:
        return polygon
    result = []
    for v in polygon:
        x, y = v[0], v[1]
        if rotation == 1:    # 90 CW
            result.append([1.0 - y, x])
        elif rotation == 2:  # 180
            result.append([1.0 - x, 1.0 - y])
        elif rotation == 3:  # 270 CW
            result.append([y, 1.0 - x])
    return result


def build_boundary_mask(terrain: list[list[int]],
                        meta_manager=None,
                        rotations=None) -> tuple[pygame.mask.Mask, pygame.Surface]:
    """Build the world-sized collision mask and debug surface.

    - collision_type "none"    -> tile is free (painted black / removed from mask)
    - collision_type "full"    -> tile is a wall (left red / set in mask)
    - collision_type "polygon" -> polygon shape is a wall within the tile

    Tiles not in metadata default to: driveable=free, non-driveable=full.

    Returns (mask, surface) identical in interface to TileTrack's original.
    """
    if meta_manager is None:
        meta_manager = get_manager()

    surface = pygame.Surface((WORLD_WIDTH, WORLD_HEIGHT))
    surface.set_colorkey((0, 0, 0))
    surface.fill((255, 0, 0))  # everything is wall by default

    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            tid = terrain[row][col]
            x = col * TILE_SIZE
            y = row * TILE_SIZE

            if tid == T_EMPTY:
                # Grass is a wall (off-track)
                continue

            meta = meta_manager.get(tid)
            coll_type = meta.collision_type

            if coll_type == COLL_NONE:
                # Free — clear the tile rect
                pygame.draw.rect(surface, (0, 0, 0),
                                 (x, y, TILE_SIZE, TILE_SIZE))

            elif coll_type == COLL_FULL:
                # Full wall — leave red
                pass

            elif coll_type == COLL_POLYGON:
                # Partial — clear tile first, then draw polygon as wall
                pygame.draw.rect(surface, (0, 0, 0),
                                 (x, y, TILE_SIZE, TILE_SIZE))
                if meta.collision_polygon and len(meta.collision_polygon) >= 3:
                    poly = meta.collision_polygon
                    rot = rotations[row][col] if rotations else 0
                    if rot:
                        poly = rotate_polygon(poly, rot)
                    points = [
                        (x + int(v[0] * TILE_SIZE), y + int(v[1] * TILE_SIZE))
                        for v in poly
                    ]
                    pygame.draw.polygon(surface, (255, 0, 0), points)

    mask = pygame.mask.from_surface(surface)
    return mask, surface


def build_friction_map(terrain: list[list[int]],
                       meta_manager=None,
                       overrides: dict | None = None) -> list[list[float]]:
    """Build a 2D grid of friction values (one per tile cell).

    Args:
        terrain: the tile grid
        meta_manager: TileMetadataManager (uses singleton if None)
        overrides: optional dict of "row,col" -> {"friction": float}
                   from track v4 tile_overrides
    Returns:
        list[list[float]] of size GRID_ROWS x GRID_COLS
    """
    if meta_manager is None:
        meta_manager = get_manager()

    fmap = []
    for row in range(GRID_ROWS):
        frow = []
        for col in range(GRID_COLS):
            tid = terrain[row][col]
            if tid == T_EMPTY:
                friction = 1.0  # off-track default
            else:
                friction = meta_manager.get_friction(tid)

            # Per-tile override from track file
            if overrides:
                key = f"{row},{col}"
                if key in overrides:
                    friction = overrides[key].get("friction", friction)

            frow.append(friction)
        fmap.append(frow)
    return fmap
