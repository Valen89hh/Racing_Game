"""
tile_meta.py - Tile metadata system.

Provides per-tile metadata (category, friction, collision, tags) stored in
tileset_meta.json.  Auto-generates initial metadata from pixel color heuristic
on first run, then lets the user edit it via the PropertyInspector.

Categories:
  terrain   - Driveable surfaces (roads, paths)
  props     - Decorative elements that block movement (trees, bushes)
  obstacles - Walls, barriers, hard collisions
  special   - Finish line, checkpoints

Migration from legacy:
  CAT_ROAD   -> terrain
  CAT_NATURE -> props
  CAT_DECOR  -> obstacles
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

# Categories
META_TERRAIN = "terrain"
META_PROPS = "props"
META_OBSTACLES = "obstacles"
META_SPECIAL = "special"

ALL_CATEGORIES = [META_TERRAIN, META_PROPS, META_OBSTACLES, META_SPECIAL]

CATEGORY_DISPLAY = {
    META_TERRAIN: "Terrain",
    META_PROPS: "Props",
    META_OBSTACLES: "Obstacles",
    META_SPECIAL: "Special",
}

# Friction presets (cycle order in PropertyInspector)
FRICTION_PRESETS = [0.3, 0.7, 1.0, 1.3, 1.8]

# Collision types
COLL_NONE = "none"
COLL_FULL = "full"
COLL_POLYGON = "polygon"

COLLISION_TYPES = [COLL_NONE, COLL_FULL, COLL_POLYGON]

# Path to the metadata JSON
from utils.base_path import ASSETS_DIR
_META_DIR = os.path.join(ASSETS_DIR, "levels")
_META_PATH = os.path.join(_META_DIR, "tileset_meta.json")


@dataclass
class TileMeta:
    """Metadata for a single tile."""
    tile_id: int
    category: str = META_TERRAIN
    friction: float = 1.0
    blocks_movement: bool = False
    collision_type: str = COLL_NONE      # "none", "full", "polygon"
    collision_polygon: Optional[list] = None  # [[x,y], ...] normalised 0-1
    display_name: str = ""
    tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "category": self.category,
            "friction": self.friction,
            "blocks_movement": self.blocks_movement,
            "collision_type": self.collision_type,
            "collision_polygon": self.collision_polygon,
            "display_name": self.display_name,
            "tags": self.tags,
        }
        return d

    @staticmethod
    def from_dict(tile_id: int, d: dict) -> TileMeta:
        return TileMeta(
            tile_id=tile_id,
            category=d.get("category", META_TERRAIN),
            friction=d.get("friction", 1.0),
            blocks_movement=d.get("blocks_movement", False),
            collision_type=d.get("collision_type", COLL_NONE),
            collision_polygon=d.get("collision_polygon"),
            display_name=d.get("display_name", ""),
            tags=d.get("tags", []),
        )


# ──────────────────────────────────────────────
# SINGLETON MANAGER
# ──────────────────────────────────────────────

_manager: Optional[TileMetadataManager] = None


class TileMetadataManager:
    """Singleton that owns all tile metadata.  Lazy-loads from JSON or
    auto-generates from the legacy colour heuristic."""

    def __init__(self):
        self._data: dict[int, TileMeta] = {}
        self._loaded = False
        self._dirty = False

    # ── Loading ──

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        if os.path.exists(_META_PATH):
            self._load_json()
        else:
            self._auto_generate()
            self.save()

    def _load_json(self):
        try:
            with open(_META_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[tile_meta] WARNING: could not read {_META_PATH}: {e}")
            self._auto_generate()
            return
        tiles = raw.get("tiles", {})
        for tid_str, tdata in tiles.items():
            tid = int(tid_str)
            self._data[tid] = TileMeta.from_dict(tid, tdata)

    def _auto_generate(self):
        """Generate metadata from the legacy pixel-colour classification
        already in tile_defs (importing lazily to avoid circular deps)."""
        import tile_defs
        tile_defs._ensure_loaded()

        # Map legacy categories to new ones
        _legacy_map = {
            tile_defs.CAT_ROAD: META_TERRAIN,
            tile_defs.CAT_NATURE: META_PROPS,
        }

        for tinfo in tile_defs._tiles:
            tid = tinfo["tile_id"]
            old_cat = tinfo["category"]
            new_cat = _legacy_map.get(old_cat, META_OBSTACLES)
            driveable = tinfo["driveable"]
            self._data[tid] = TileMeta(
                tile_id=tid,
                category=new_cat,
                friction=1.0,
                blocks_movement=not driveable,
                collision_type=COLL_NONE if driveable else COLL_FULL,
            )

        # Special: finish tile
        self._data[tile_defs.T_FINISH] = TileMeta(
            tile_id=tile_defs.T_FINISH,
            category=META_SPECIAL,
            friction=1.0,
            blocks_movement=False,
            collision_type=COLL_NONE,
            display_name="Finish Line",
        )
        print(f"[tile_meta] Auto-generated metadata for {len(self._data)} tiles")

    # ── Saving ──

    def save(self):
        os.makedirs(_META_DIR, exist_ok=True)
        out = {
            "version": 1,
            "tileset_file": "tileset.png",
            "tiles": {},
        }
        for tid in sorted(self._data.keys()):
            out["tiles"][str(tid)] = self._data[tid].to_dict()
        try:
            with open(_META_PATH, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=None, ensure_ascii=False)
            self._dirty = False
        except OSError as e:
            print(f"[tile_meta] ERROR saving: {e}")

    # ── Public API ──

    def get(self, tile_id: int) -> TileMeta:
        self._ensure_loaded()
        if tile_id in self._data:
            return self._data[tile_id]
        # Return sensible default for unknown tiles
        return TileMeta(tile_id=tile_id)

    def set(self, tile_id: int, meta: TileMeta):
        self._ensure_loaded()
        self._data[tile_id] = meta
        self._dirty = True

    def is_driveable(self, tile_id: int) -> bool:
        self._ensure_loaded()
        if tile_id in self._data:
            return not self._data[tile_id].blocks_movement
        return False

    def get_friction(self, tile_id: int) -> float:
        self._ensure_loaded()
        if tile_id in self._data:
            return self._data[tile_id].friction
        return 1.0

    def get_category(self, tile_id: int) -> str:
        self._ensure_loaded()
        if tile_id in self._data:
            return self._data[tile_id].category
        return META_OBSTACLES

    def get_tiles_by_category(self, category: str) -> list[int]:
        self._ensure_loaded()
        return [tid for tid, m in self._data.items() if m.category == category]

    def all_tile_ids(self) -> list[int]:
        self._ensure_loaded()
        return list(self._data.keys())

    @property
    def dirty(self) -> bool:
        return self._dirty


def get_manager() -> TileMetadataManager:
    """Return the singleton TileMetadataManager."""
    global _manager
    if _manager is None:
        _manager = TileMetadataManager()
    return _manager
