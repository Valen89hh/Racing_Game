# CLAUDE.md - Arcade Racing 2D

## Project Overview

**2D top-down arcade racing game** built with **Pygame** (Python 3.12+). Features a tile-based track editor, AI opponents, power-ups, and a rotating camera system. The game supports two track formats: classic (control points + Chaikin smoothing) and tile-based (painted grid).

**Entry point:** `python main.py`

## Directory Structure

```
racing_game/
├── main.py              (29 lines)  - Entry point
├── game.py              (834 lines) - Game loop, state machine, orchestration
├── settings.py          (187 lines) - All configuration constants
├── track_manager.py     (163 lines) - Track file I/O (JSON save/load)
├── tile_track.py        (400 lines) - Tile-based track (TileTrack class)
├── tile_defs.py         (312 lines) - Tile definitions, classification, sprites
├── editor.py           (1123 lines) - Tile editor (TileEditor class)
│
├── entities/
│   ├── car.py           (264 lines) - Car entity (physics, sprites, effects)
│   ├── track.py         (596 lines) - Classic track (Chaikin curves, rendering)
│   └── powerup.py       (237 lines) - PowerUpItem, Missile, OilSlick
│
├── systems/
│   ├── input_handler.py  (81 lines) - Keyboard → car inputs
│   ├── physics.py       (161 lines) - Acceleration, friction, turning, wall bounce
│   ├── collision.py     (168 lines) - All collision detection & resolution
│   ├── camera.py        (159 lines) - Smooth camera with look-ahead + rotation
│   └── ai.py            (172 lines) - Bot waypoint following + power-up tactics
│
├── utils/
│   ├── helpers.py       (183 lines) - Math utilities, procedural car sprite
│   ├── sprites.py       (120 lines) - Asset loading, sprite sheets, scaling
│   └── timer.py          (96 lines) - Race timer, lap tracking
│
├── assets/
│   ├── cars/            - Pixel art sprites (16x16, 8 directions per car)
│   │   ├── player_blue.png, player_red.png, player_green.png, player_yellow.png
│   │   ├── npc_cars.png, police.png
│   ├── levels/
│   │   └── tileset.png  (148 KB) - Master tileset (1120x1648, 70x103 tiles at 16x16)
│   ├── props/
│   │   ├── misc_props.png, road_markings.png
│   └── sounds/
│
├── tracks/              - Saved track files (JSON)
│   ├── default_circuit.json  - Classic format (control points)
│   └── *.json                - User-created tracks
│
└── venv/                - Python virtual environment
```

## Architecture

### State Machine (game.py)

```
STATE_MENU → STATE_TRACK_SELECT → STATE_COUNTDOWN → STATE_RACING → STATE_VICTORY
                                                                         ↓
STATE_MENU → STATE_EDITOR → (test race) → STATE_COUNTDOWN → ... → back to editor
```

States defined in `settings.py`: `STATE_MENU`, `STATE_COUNTDOWN`, `STATE_RACING`, `STATE_VICTORY`, `STATE_EDITOR`, `STATE_TRACK_SELECT`.

### Entity-System Pattern

**Entities** hold data, **Systems** process them each frame:
- `Car` → processed by `PhysicsSystem`, `InputHandler`, `AISystem`
- `Track`/`TileTrack` → consumed by `CollisionSystem`, `Camera`, `AISystem`
- `PowerUpItem`/`Missile`/`OilSlick` → processed in `Game._update_racing()`

### Two Track Formats

| | Classic (`Track`) | Tile-Based (`TileTrack`) |
|---|---|---|
| Source | `entities/track.py` | `tile_track.py` |
| Input | ~40 control points | 56x37 grid of tile IDs |
| Smoothing | Chaikin (3 iterations) | N/A |
| Collision | Tube of circles along path | Per-tile driveable check |
| Waypoints | Sampled from smoothed path | DFS trace through driveable tiles |
| Created by | Legacy/default circuit | Tile editor |

**Both expose the same interface** so all systems work unchanged:
```
ATTRIBUTES: waypoints, checkpoints, num_checkpoints, start_positions,
            powerup_spawn_points, finish_line, boundary_mask,
            boundary_surface, track_surface, minimap_surface

METHODS:    draw(surface, camera), check_car_collision(mask, rect),
            check_finish_line_cross(ox, oy, nx, ny),
            get_minimap_pos(wx, wy), is_on_track(x, y)
```

## Key Constants (settings.py)

- **Screen:** 1280x720, 60 FPS
- **World:** 3600x2400 (larger than screen, camera follows player)
- **Tiles:** TILE_SIZE=64, Grid=56x37, Base pixel=16x16 (scaled 4x)
- **Car physics:** max_speed=500, acceleration=300, turn=200, drift=0.92
- **Bot:** max_speed=480, acceleration=290
- **Laps:** 3 per race
- **Power-ups:** Boost (3s), Shield (12s), Missile (700px/s), Oil (8s on ground)

## Tile System (tile_defs.py)

### Tile IDs
- `T_EMPTY = 0` — Grass background (not driveable)
- `T_FINISH = 1` — Checkered finish line (driveable)
- `TILE_BASE = 10` — Tileset tiles start here (10, 11, 12, ...)

### Categories (auto-classified by pixel color analysis)
- `CAT_ROAD` — Gray/uniform surfaces → **driveable**
- `CAT_NATURE` — Green dominant → not driveable
- `CAT_DECOR` — Everything else → not driveable

### Tileset
- Source: `assets/levels/tileset.png` (Road Racers Adrenaline Assets)
- 1120x1648 pixels = 70 columns x 103 rows of 16x16 tiles
- ~1982 non-empty tiles loaded, ~796 classified as road
- Sprites cached at 64x64 in `_sprites` dict

### Key API
```python
is_driveable(tile_id) → bool
get_tile_sprite(tile_id) → Surface(64x64) | None
get_tiles_by_category(cat) → [tile_id, ...]
get_tileset_sheet() → Surface (original image)
get_tileset_dimensions() → (cols, rows)
get_tile_at_position(src_row, src_col) → tile_id | None
get_tile_info(tile_id) → dict | None
empty_terrain() → [[T_EMPTY]*56 for _ in range(37)]
```

## Editor (editor.py — TileEditor)

### Layout
```
┌─────────────────────────────────────────────────┐
│                                                 │
│              VIEWPORT (grid)                    │  ← Full width, top 492px
│              zoom + pan                         │
│                                                 │
├──────────┬──────────────────────────────────────┤
│ TOOLS    │   TILESET BROWSER                    │  ← Bottom panel, 200px
│ (130px)  │   (zoom, scroll, drag)               │
├──────────┴──────────────────────────────────────┤
│ Status bar: zoom, coords, brush, track name     │  ← 28px
└─────────────────────────────────────────────────┘
```

### Controls
- **Left-click** — Paint selected tile
- **Right-click** — Erase (set to grass)
- **Middle-drag / Space+drag** — Pan viewport
- **Scroll** — Zoom viewport
- **Tileset: scroll** — Zoom browser
- **Tileset: right-drag** — Pan browser
- **Shift+1/2/3** — Brush size (1x1, 2x2, 3x3)
- **Ctrl+S** — Save, **Ctrl+O** — Load, **Ctrl+N** — New
- **Ctrl+Z/Y** — Undo/Redo (max 30 snapshots)
- **T** — Test race (needs finish tiles + 10+ driveable)
- **H** — Help overlay, **F** — Fit view, **ESC** — Menu

### Features
- `load_from_file(filename)` — Load existing tile track for editing
- Save dialog uses `pygame.TEXTINPUT` events (not KEYDOWN.unicode)
- Track select screen: press **E** to edit a tile-based track

## Track File Formats (track_manager.py)

### Classic Format (version 1)
```json
{
  "name": "Grand Circuit",
  "author": "Default",
  "version": 1,
  "control_points": [[550, 500], [850, 500], ...]
}
```

### Tile Format (version 3)
```json
{
  "name": "My Track",
  "author": "Player",
  "version": 3,
  "format": "tiles",
  "tile_size": 64,
  "grid_width": 56,
  "grid_height": 37,
  "terrain": [[0,0,0,...], [0,1,1,...], ...]
}
```

Tracks stored in `tracks/` directory. `list_tracks()` returns both formats with `type` field.

## Camera System (systems/camera.py)

- **Look-ahead:** 200px in car's forward direction (speed-scaled)
- **Partial rotation:** Camera gradually rotates toward car angle, capped at 35 deg/s
- **Smooth interpolation:** Position lerps at factor 8.0
- **Transform:** Translate → Rotate → Center on screen

## Physics (systems/physics.py)

- Arcade model (not simulation)
- Speed-dependent turning (less turn at low speed)
- Drift factor 0.92
- Wall collision: project velocity onto wall normal, keep tangent component
- Power-up effects modify multipliers (speed, accel, friction, turn)

## AI (systems/ai.py)

- Follows ~60 waypoints around circuit
- Proportional steering control
- Looks 3 waypoints ahead to predict curves and brake
- Tactical power-up usage (boost on straights, missile at aligned targets, etc.)

## Collision (systems/collision.py)

- **Car vs wall:** 16 rays around car, compute normal, iterative push-out
- **Car vs car:** Mask overlap, push apart
- **Car vs finish line:** Segment intersection (lap detection)
- **Car vs checkpoints:** Distance check (80px radius)
- **Car vs power-ups/missiles/oil:** Distance checks

## Important Patterns

1. **Lazy loading:** `tile_defs.py` loads tileset on first API call (`_ensure_loaded()`)
2. **Pre-rendering:** Both Track and TileTrack pre-render `track_surface` (full world size) and extract chunks per frame
3. **Coordinate systems:**
   - World coords: (0,0) to (3600, 2400)
   - Tile coords: (row, col) where row=0..36, col=0..55
   - Screen coords: (0,0) to (1280, 720) after camera transform
4. **Event handling:** Pygame 2.x uses `TEXTINPUT` for character input (not `KEYDOWN.unicode`)
5. **Track interface compatibility:** Any new track type must provide the same attributes/methods as Track

## Running the Game

```bash
cd racing_game
pip install pygame
python main.py
```

### Menu Controls
- **ENTER** — Open track selection
- **E** — Open track editor
- **ESC** — Quit

### Race Controls
- **W/S** — Accelerate/Reverse
- **A/D** — Turn
- **SPACE** — Handbrake
- **L-SHIFT** — Use power-up
- **ESC** — Back to menu (or editor if test race)

### Track Select
- **UP/DOWN** — Navigate
- **ENTER** — Start race
- **E** — Edit selected track (tile-based only)
- **ESC** — Back to menu
