"""
tile_defs.py - Tile definitions from Road Racers tileset.

Single tileset (tileset.png, 1120x1648, 70x103 tiles at 16x16).
All tiles extracted, auto-classified, and indexed for editor and game.

Tile IDs:
  0       = empty (grass background, not driveable)
  1       = finish line (generated checkered, driveable)
  10..N   = tileset tiles (driveable if classified as road)
"""

import pygame

# ──────────────────────────────────────────────
# GRID
# ──────────────────────────────────────────────
TILE_SIZE = 64
TILE_BASE_PX = 16
GRID_COLS = 56   # WORLD_WIDTH (3600) / TILE_SIZE
GRID_ROWS = 37   # WORLD_HEIGHT (2400) / TILE_SIZE

# ──────────────────────────────────────────────
# TILE IDs
# ──────────────────────────────────────────────
T_EMPTY = 0      # grass background
T_FINISH = 1     # finish line (driveable)
TILE_BASE = 10   # tileset tiles start here

# ──────────────────────────────────────────────
# CATEGORIES
# ──────────────────────────────────────────────
CAT_ROAD = "road"
CAT_NATURE = "nature"
CAT_DECOR = "decor"

CATEGORY_NAMES = {
    CAT_ROAD: "Road",
    CAT_NATURE: "Nature",
    CAT_DECOR: "Decor",
}

# ──────────────────────────────────────────────
# VISUAL
# ──────────────────────────────────────────────
GRASS_COLOR = (66, 173, 55)
GRASS_DARK = (55, 148, 46)

# ──────────────────────────────────────────────
# INTERNAL STATE (populated lazily on first access)
# ──────────────────────────────────────────────
_loaded = False
_tiles = []        # list of tile info dicts
_sprites = {}      # tile_id -> Surface(64x64)
_categories = {}   # category -> [tile_id, ...]
_road_ids = set()  # driveable tile IDs
_tileset_sheet = None   # original tileset Surface (preserved for browser)
_position_map = {}      # (src_row, src_col) -> tile_id
TILESET_COLS = 0        # tile columns in tileset
TILESET_ROWS = 0        # tile rows in tileset


def _ensure_loaded():
    global _loaded
    if _loaded:
        return
    _loaded = True
    _do_load()


def _do_load():
    global _tiles, _sprites, _categories, _road_ids
    global _tileset_sheet, _position_map, TILESET_COLS, TILESET_ROWS
    from utils.sprites import load_image

    try:
        sheet = load_image("levels/tileset.png")
    except (FileNotFoundError, pygame.error):
        print("[tile_defs] WARNING: tileset.png not found")
        _categories = {CAT_ROAD: [], CAT_NATURE: [], CAT_DECOR: []}
        return

    sheet_w, sheet_h = sheet.get_size()
    src_cols = sheet_w // TILE_BASE_PX
    src_rows = sheet_h // TILE_BASE_PX

    _tileset_sheet = sheet
    TILESET_COLS = src_cols
    TILESET_ROWS = src_rows

    # Raw pixel data for fast access
    raw = pygame.image.tostring(sheet, "RGBA")
    bpp = 4

    _tiles = []
    _sprites = {}
    _road_ids = set()
    _position_map = {}
    _categories = {CAT_ROAD: [], CAT_NATURE: [], CAT_DECOR: []}

    # Special sprites
    _sprites[T_FINISH] = _make_finish_sprite()

    for row in range(src_rows):
        for col in range(src_cols):
            bx = col * TILE_BASE_PX
            by = row * TILE_BASE_PX

            # Quick empty check (9 sample pixels)
            has_content = False
            for sy in (0, 7, 15):
                for sx in (0, 7, 15):
                    idx = ((by + sy) * sheet_w + (bx + sx)) * bpp
                    if raw[idx + 3] > 10:
                        has_content = True
                        break
                if has_content:
                    break
            if not has_content:
                continue

            # Full pixel analysis
            colors = set()
            tr = tg = tb = cnt = 0
            for dy in range(TILE_BASE_PX):
                for dx in range(TILE_BASE_PX):
                    idx = ((by + dy) * sheet_w + (bx + dx)) * bpp
                    a = raw[idx + 3]
                    if a > 10:
                        rv = raw[idx]
                        gv = raw[idx + 1]
                        bv = raw[idx + 2]
                        tr += rv
                        tg += gv
                        tb += bv
                        cnt += 1
                        colors.add((rv, gv, bv))

            if cnt < 5:
                continue

            avg_r = tr // cnt
            avg_g = tg // cnt
            avg_b = tb // cnt
            unique = len(colors)

            cat = _classify(avg_r, avg_g, avg_b, unique)
            driveable = (cat == CAT_ROAD)

            # Extract and scale sprite
            sub = pygame.Surface((TILE_BASE_PX, TILE_BASE_PX), pygame.SRCALPHA)
            sub.blit(sheet, (0, 0),
                     pygame.Rect(bx, by, TILE_BASE_PX, TILE_BASE_PX))
            scaled = pygame.transform.scale(sub, (TILE_SIZE, TILE_SIZE))

            tile_id = TILE_BASE + len(_tiles)
            _tiles.append({
                'tile_id': tile_id,
                'sprite': scaled,
                'category': cat,
                'driveable': driveable,
                'src_row': row,
                'src_col': col,
            })
            _sprites[tile_id] = scaled
            _position_map[(row, col)] = tile_id
            _categories[cat].append(tile_id)
            if driveable:
                _road_ids.add(tile_id)

    print(f"[tile_defs] Loaded {len(_tiles)} tiles: "
          f"{len(_categories[CAT_ROAD])} road, "
          f"{len(_categories[CAT_NATURE])} nature, "
          f"{len(_categories[CAT_DECOR])} decor")


def _classify(avg_r, avg_g, avg_b, unique_colors):
    """Classify tile by average color and color complexity."""
    gray = max(abs(avg_r - avg_g), abs(avg_r - avg_b), abs(avg_g - avg_b))
    bright = (avg_r + avg_g + avg_b) / 3

    # Road: gray tones with low color variety (uniform surfaces)
    if gray < 35 and 40 < bright < 220 and unique_colors <= 8:
        return CAT_ROAD

    # Very dark uniform tiles (road edges, shadows)
    if bright < 45 and unique_colors <= 3:
        return CAT_ROAD

    # Green dominant = nature
    if avg_g > avg_r + 15 and avg_g > avg_b + 10:
        return CAT_NATURE

    return CAT_DECOR


def _make_finish_sprite():
    """Generate checkered finish line tile."""
    s = pygame.Surface((TILE_SIZE, TILE_SIZE))
    sq = 8
    for y in range(0, TILE_SIZE, sq):
        for x in range(0, TILE_SIZE, sq):
            c = (240, 240, 240) if (x // sq + y // sq) % 2 == 0 else (30, 30, 30)
            pygame.draw.rect(s, c, (x, y, sq, sq))
    return s


def _make_grass_sprite():
    """Generate grass background tile."""
    s = pygame.Surface((TILE_SIZE, TILE_SIZE))
    s.fill(GRASS_COLOR)
    for y in range(0, TILE_SIZE, 8):
        for x in range(0, TILE_SIZE, 8):
            if (x // 8 + y // 8) % 3 == 0:
                pygame.draw.rect(s, GRASS_DARK, (x, y, 4, 4))
    return s


# ──────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────

def is_driveable(tile_id):
    """Returns True if tile is driveable (road or finish).
    Delegates to TileMetadataManager when metadata is available."""
    if tile_id == T_EMPTY:
        return False
    if tile_id == T_FINISH:
        return True
    _ensure_loaded()
    from tile_meta import get_manager
    mgr = get_manager()
    if mgr._loaded or tile_id not in _road_ids:
        return mgr.is_driveable(tile_id)
    return tile_id in _road_ids


def get_tile_sprite(tile_id):
    """Returns 64x64 Surface for the tile, or None for T_EMPTY."""
    if tile_id == T_EMPTY:
        return None
    _ensure_loaded()
    return _sprites.get(tile_id)


def get_tiles_by_category(category):
    """Returns list of tile_ids in the given category.
    Also supports new meta categories (terrain, props, obstacles, special)."""
    _ensure_loaded()
    # Support new meta categories directly
    from tile_meta import ALL_CATEGORIES, get_manager
    if category in ALL_CATEGORIES:
        return get_manager().get_tiles_by_category(category)
    return _categories.get(category, [])


def get_all_tile_ids():
    """Returns list of all tileset tile_ids."""
    _ensure_loaded()
    return [t['tile_id'] for t in _tiles]


def get_tile_count():
    """Returns total number of tileset tiles loaded."""
    _ensure_loaded()
    return len(_tiles)


def get_tile_category(tile_id):
    """Returns the category of a tile.
    Delegates to TileMetadataManager when metadata is available."""
    if tile_id == T_EMPTY:
        return None
    if tile_id == T_FINISH:
        return CAT_ROAD
    _ensure_loaded()
    from tile_meta import get_manager
    mgr = get_manager()
    if mgr._loaded:
        cat = mgr.get_category(tile_id)
        # Map new categories back to legacy for compatibility
        from tile_meta import META_TERRAIN, META_PROPS, META_OBSTACLES, META_SPECIAL
        _reverse_map = {
            META_TERRAIN: CAT_ROAD,
            META_PROPS: CAT_NATURE,
            META_OBSTACLES: CAT_DECOR,
            META_SPECIAL: CAT_ROAD,
        }
        return _reverse_map.get(cat, CAT_DECOR)
    idx = tile_id - TILE_BASE
    if 0 <= idx < len(_tiles):
        return _tiles[idx]['category']
    return None


def make_grass_sprite():
    """Returns a new grass tile sprite."""
    return _make_grass_sprite()


def make_finish_sprite():
    """Returns the finish line sprite."""
    _ensure_loaded()
    return _sprites.get(T_FINISH, _make_finish_sprite())


def empty_terrain():
    """Creates an empty terrain grid (all grass)."""
    return [[T_EMPTY] * GRID_COLS for _ in range(GRID_ROWS)]


def get_tileset_sheet():
    """Returns the original tileset Surface, or None if not loaded."""
    _ensure_loaded()
    return _tileset_sheet


def get_tileset_dimensions():
    """Returns (cols, rows) of the tileset in tile units."""
    _ensure_loaded()
    return TILESET_COLS, TILESET_ROWS


def get_tile_at_position(src_row, src_col):
    """Returns tile_id at the given tileset position, or None if empty."""
    _ensure_loaded()
    return _position_map.get((src_row, src_col))


def get_tile_info(tile_id):
    """Returns tile info dict for a tileset tile, or None."""
    _ensure_loaded()
    idx = tile_id - TILE_BASE
    if 0 <= idx < len(_tiles):
        return _tiles[idx]
    return None
