# CLAUDE.md - Arcade Racing 2D

## Project Overview

**2D top-down arcade racing game** built with **Pygame** (Python 3.12+). Features a tile-based track editor, AI opponents, power-ups, dust particles, a rotating camera system, and multiplayer via LAN or internet relay. The game supports two track formats: classic (control points + Chaikin smoothing) and tile-based (painted grid).

**Current version:** 1.2.0
**Entry point:** `python main.py`

## Directory Structure

```
racing_game/
├── main.py              (~40 lines)  - Entry point + --train-subprocess routing
├── game.py              (~1300 lines) - Game loop, state machine, orchestration
├── settings.py          (~250 lines) - All configuration constants
├── track_manager.py     (~170 lines) - Track file I/O (JSON save/load)
├── tile_track.py        (~350 lines) - Tile-based track (TileTrack class)
├── tile_defs.py         (312 lines) - Tile definitions, classification, sprites
├── editor.py           (~1200 lines) - Tile editor (TileEditor class)
├── version.txt                      - Current version number (e.g. "1.0.1")
│
├── networking/
│   ├── __init__.py                  - Package marker
│   ├── protocol.py      (~475 lines) - Binary UDP protocol (pack/unpack all packet types)
│   ├── net_state.py     (~100 lines) - Data classes (NetCarState, StateSnapshot, InputState)
│   ├── server.py        (~400 lines) - GameServer (host-side UDP, supports LAN + relay)
│   ├── client.py        (~330 lines) - GameClient (client-side UDP, supports LAN + relay)
│   ├── relay_protocol.py (~120 lines) - Relay binary protocol (room commands + forwarding)
│   └── relay_socket.py  (~210 lines) - RelaySocket drop-in adapter for transparent relay
│
├── relay_server/
│   ├── relay_server.py  (~250 lines) - Standalone relay server (stdlib only, Python 3.8+)
│   └── README.md                    - VPS deploy instructions
│
├── entities/
│   ├── car.py           (264 lines) - Car entity (physics, sprites, effects)
│   ├── track.py         (596 lines) - Classic track (Chaikin curves, rendering)
│   ├── powerup.py       (237 lines) - PowerUpItem, Missile, OilSlick
│   └── particles.py     (~130 lines) - DustParticleSystem (pool-based dust FX)
│
├── systems/
│   ├── input_handler.py  (81 lines) - Keyboard → car inputs
│   ├── physics.py       (161 lines) - Acceleration, friction, turning, wall bounce
│   ├── collision.py     (168 lines) - All collision detection & resolution
│   ├── camera.py        (159 lines) - Smooth camera with look-ahead + rotation
│   └── ai.py            (~300 lines) - Bot waypoint following + power-up tactics + RLSystem
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
├── launcher/            - Auto-updater launcher (separate PyInstaller build)
│   ├── main.py          (186 lines) - Launcher orchestrator + Pygame UI
│   ├── updater.py       (~205 lines) - Download, extract, install with rollback
│   ├── version_checker.py(132 lines) - GitHub Releases version detection
│   ├── config.py        (79 lines)  - Path resolution, config.json loading
│   └── ui.py            (216 lines) - Pygame launcher GUI (600x400)
│
├── training/
│   ├── __init__.py                  - Package marker
│   ├── racing_env.py    (~334 lines) - Gymnasium env for RL training (headless)
│   └── train_ai.py      (~235 lines) - PPO training CLI + JSONProgressCallback
│
├── models/              - Trained RL models (*.zip, gitignored)
│
├── tracks/              - Saved track files (JSON)
│   ├── default_circuit.json  - Classic format (control points)
│   └── *.json                - User-created tracks
│
├── build_game.bat       - Build game exe (PyInstaller onedir)
├── build_launcher.bat   - Build launcher exe
├── build_all.bat        - Build both
├── game.spec            - PyInstaller spec for game
├── launcher.spec        - PyInstaller spec for launcher
│
└── venv/                - Python virtual environment
```

## Architecture

### State Machine (game.py)

```
STATE_MENU → STATE_TRACK_SELECT → STATE_COUNTDOWN → STATE_RACING → STATE_VICTORY
                  ↓ (T key)
              STATE_TRAINING → (subprocess trains RL model) → back to track select

STATE_MENU → STATE_EDITOR → (test race) → STATE_COUNTDOWN → ... → back to editor

Multiplayer LAN:
  Track Select → H → STATE_HOST_LOBBY → ENTER → STATE_ONLINE_COUNTDOWN → STATE_ONLINE_RACING
  Menu → J → STATE_CONNECTING → STATE_JOIN_LOBBY → STATE_ONLINE_COUNTDOWN → STATE_ONLINE_RACING

Multiplayer Relay (internet):
  Track Select → R → STATE_RELAY_HOST → create room → STATE_HOST_LOBBY → (same as LAN)
  Menu → R → STATE_RELAY_JOIN → enter code → STATE_CONNECTING → (same as LAN)
```

States defined in `settings.py`: `STATE_MENU`, `STATE_COUNTDOWN`, `STATE_RACING`, `STATE_VICTORY`, `STATE_EDITOR`, `STATE_TRACK_SELECT`, `STATE_TRAINING`, `STATE_HOST_LOBBY`, `STATE_JOIN_LOBBY`, `STATE_CONNECTING`, `STATE_ONLINE_RACING`, `STATE_ONLINE_COUNTDOWN`, `STATE_RELAY_HOST`, `STATE_RELAY_JOIN`.

### Entity-System Pattern

**Entities** hold data, **Systems** process them each frame:
- `Car` → processed by `PhysicsSystem`, `InputHandler`, `AISystem`
- `Track`/`TileTrack` → consumed by `CollisionSystem`, `Camera`, `AISystem`
- `PowerUpItem`/`Missile`/`OilSlick` → processed in `Game._update_racing()`
- `DustParticleSystem` → emits + updates + draws in `Game._update_racing()` / `_render_race()`

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
- **Dust particles:** pool=120, threshold=80px/s, lifetime=0.3-0.8s, alpha fade+shrink
- **Networking:** port=5555 (LAN), tick_rate=30Hz, input_rate=60Hz, timeout=5s
- **Relay:** port=7777, heartbeat=3s, peer_timeout=10s, room_code=4 chars

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
- **C** — Checkpoint mode (drag=place zone, R-click=delete)
- **D** — Direction mode (drag=set arrow, R-click=delete)
- **H** — Help overlay, **F** — Fit view, **ESC** — Menu

### Features
- `load_from_file(filename)` — Load existing tile track for editing
- Save dialog uses `pygame.TEXTINPUT` events (not KEYDOWN.unicode)
- Track select screen: press **E** to edit a tile-based track

### Checkpoint System (manual only)
- Checkpoints are placed manually in the editor via **C** mode (no auto-generation)
- Displayed 0-indexed: checkpoint **0** should be placed at/near the finish line
- At runtime, TileTrack rotates the list so C0 becomes the **last** checkpoint in sequence
- This ensures the lap counter increments when the car crosses C0 (the finish area)
- If no checkpoints are placed, `checkpoint_zones = []` and lap counting relies only on finish line

### Circuit Direction (editor D mode)
- Click-drag draws a green arrow indicating the forward direction of the circuit
- Saved as `circuit_direction: [x1, y1, x2, y2]` in the track JSON (world coords)
- TileTrack uses this to orient car start positions instead of auto-computing from DFS path
- If not set, falls back to the original auto-compute (last DFS tile → finish tile)

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

### Tile Format (version 3/4)
```json
{
  "name": "My Track",
  "author": "Player",
  "version": 3,
  "format": "tiles",
  "tile_size": 64,
  "grid_width": 56,
  "grid_height": 37,
  "terrain": [[0,0,0,...], [0,1,1,...], ...],
  "rotations": [[0,0,1,...], ...],
  "checkpoint_zones": [[x, y, w, h], ...],
  "circuit_direction": [x1, y1, x2, y2]
}
```
- `rotations` (v4): per-tile rotation 0-3 (0/90/180/270 deg). Bumps version to 4.
- `checkpoint_zones`: manual checkpoint rectangles from editor (0-indexed, C0 = finish area).
- `circuit_direction`: optional arrow [start_x, start_y, end_x, end_y] in world coords.

Tracks stored in `tracks/` directory. `list_tracks()` returns both formats with `type` field.

`save_tile_track(filename, name, terrain, tile_overrides=None, rotations=None, checkpoint_zones=None, circuit_direction=None)`

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

- **AISystem**: Follows ~60 waypoints around circuit, proportional steering, looks 3 waypoints ahead
- **RLSystem**: Loads a trained PPO model (`models/{track}_model.zip`) and uses it for bot control
  - Falls back to AISystem if no model exists for the track
  - Loaded automatically in `_start_race()` when a matching model file is found

## Collision (systems/collision.py)

- **Car vs wall:** 16 rays around car, compute normal, iterative push-out
- **Car vs car:** Mask overlap, push apart
- **Car vs finish line:** Segment intersection (lap detection)
- **Car vs checkpoints:** Zone rect collision (manual zones from editor, sequential order)
- **Car vs power-ups/missiles/oil:** Distance checks

## RL Training System

### Architecture
Training runs in a **subprocess** to avoid conflicts with the game's pygame display. The subprocess runs headless (`SDL_VIDEODRIVER=dummy`) while the game UI shows progress.

```
Game (pygame real)                    Subprocess (headless)
┌──────────────────┐                 ┌──────────────────────┐
│ STATE_TRAINING   │   reads JSON    │ main.py              │
│ _render_training │ ◄────────────── │  --train-subprocess  │
│ _update_training │                 │  → train_ai.main()   │
│                  │   Popen()       │  → PPO.learn()       │
│ _launch_training │ ──────────────► │  writes progress.json│
└──────────────────┘                 └──────────────────────┘
```

### Subprocess Routing (main.py)
`main.py` checks for `--train-subprocess` flag **before** importing the game:
- If present: sets `SDL_VIDEODRIVER=dummy`, inits headless pygame, runs `train_ai.main()`, exits
- If absent: imports `Game` and runs normally
- This allows the same `game.exe` to serve as both game and training worker

### Launch Command (game.py `_launch_training`)
- **From source**: `[python.exe, main.py, --train-subprocess, track_path, --timesteps, N, --json-progress, path]`
- **From frozen exe**: `[game.exe, --train-subprocess, track_path, --timesteps, N, --json-progress, path]`
- Uses `getattr(sys, "frozen", False)` to choose the correct command

### Progress Communication
- Subprocess writes `progress.json` to `%TEMP%` every 2048 steps via `JSONProgressCallback`
- Game reads it each frame in `_update_training(dt)`
- JSON statuses: `"training"` → `"done"` | `"error"`
- On process crash: reads stderr and shows last line as error message

### Training UI (STATE_TRAINING)
- Enter from Track Select with **T** key (tile-based tracks only)
- UP/DOWN adjust timesteps (50k–1M), ENTER starts, ESC cancels
- Shows progress bar, elapsed time, mean reward, episodes count
- On completion, model saved to `models/{track_name}_model.zip`

### Training Environment (training/racing_env.py)
- Gymnasium env wrapping real game physics (PhysicsSystem, CollisionSystem, TileTrack, Car)
- Observation: 9 floats (7 raycasts + normalized speed + angle to next checkpoint)
- Actions: Discrete(4) — forward, left+forward, right+forward, brake
- Reward: continuous progress toward checkpoints + bonuses for crossing checkpoints/laps

### game.spec Requirements for Training
- Uses `collect_all('gymnasium')` and `collect_all('stable_baselines3')` to bundle all submodules/data
- Uses `collect_submodules('cloudpickle')`
- `datas`: `('models', 'models')`
- Do NOT exclude `email` or `unittest` in game.spec — SB3/torch depend on them
- PyTorch is auto-detected by PyInstaller via torch import chain

### Path Resolution in Frozen Builds (CRITICAL)
All paths to `tracks/` and `models/` **must** use `utils/base_path.py`, never `os.path.dirname(__file__)`:
- `__file__` in frozen → `dist/game/_internal/` (read-only bundled data)
- `TRACKS_DIR` → `dist/game/tracks/` (writable, next to exe)
- `get_writable_dir()/models/` → `dist/game/models/` (writable, next to exe)

```python
# WRONG (breaks in frozen exe):
path = os.path.join(os.path.dirname(__file__), "tracks", filename)

# CORRECT:
from utils.base_path import TRACKS_DIR
path = os.path.join(TRACKS_DIR, filename)
```

### Error Logging
- On subprocess crash, stderr is saved to `training_error.log` next to the exe
- UI shows last 3 lines of the traceback + path to the full log file
- `train_ai.main()` wraps all logic in a global try/except that writes errors to both stderr and the JSON progress file

## Relay System (Multiplayer por Internet)

### Architecture
```
HOST ──UDP──► RELAY SERVER (VPS:7777) ◄──UDP── CLIENT
              reenvía paquetes
              salas con código 4 chars
```
Both host and client connect **outbound** to the relay → works with any NAT/firewall. The relay does NOT process game logic, only forwards packets. LAN mode (H/J keys) still works without relay.

### Relay Protocol (`networking/relay_protocol.py`)
Wraps existing game packets with a 6-byte header:
```
Game packet:   [pkt_type:1B][seq:2B][game_data...]
Relay packet:  [RELAY_CMD:1B][ROOM:4B][TARGET:1B][game_data...]
```

| Byte | Command | Description |
|------|---------|-------------|
| 0xA0 | CREATE_ROOM | Host creates room |
| 0xA1 | ROOM_CREATED | Returns room code |
| 0xA2 | JOIN_ROOM | Client joins with code |
| 0xA3 | JOIN_OK | Accepted, returns slot |
| 0xA4 | JOIN_FAIL | Room not found/full |
| 0xA5 | LEAVE_ROOM | Exit room |
| 0xA6 | PEER_LEFT | Notification of disconnect |
| 0xA7 | HEARTBEAT | Keepalive (every 3s) |
| 0xA8 | FORWARD | Game packet forwarding |

Room codes: 4 alphanumeric chars (A-Z+2-9, no confusables 0/O/1/I/L). 31^4 = 923K combos.

### RelaySocket (`networking/relay_socket.py`)
Drop-in replacement for `socket.socket`. Key design: **the same UDP socket** handles both the room handshake AND game traffic (critical — using different sockets causes the relay to lose track of the peer).

```python
rs = RelaySocket(relay_addr)
rs.create_room()   # or rs.join_room(code) — uses internal socket
rs.start()         # starts heartbeat + recv threads
# Now pass rs to GameServer/GameClient as relay_socket= parameter
```

- `sendto(data, addr)` → wraps in RELAY_FORWARD, sends to relay
- `recvfrom(bufsize)` → receives from relay, unwraps, returns (payload, fake_addr)
- `sendto_broadcast(data)` → single packet with target=0xFF
- Fake addrs: `("relay_peer", slot)` so GameServer._clients dict works unchanged
- On RELAY_PEER_LEFT → synthesizes PKT_DISCONNECT for the game layer

### Relay Server (`relay_server/relay_server.py`)
Standalone script (stdlib only, Python 3.8+):
- Single-threaded `select()` event loop
- Room lifecycle: create → peers join → destroy on host disconnect or 10s timeout
- Deploy: `python relay_server.py --port 7777`

### Integration with GameServer/GameClient
Both accept an optional `relay_socket=` parameter:
- `GameServer(relay_socket=rs)` — uses RelaySocket instead of binding a port
- `GameClient(host_ip="relay", relay_socket=rs)` — uses RelaySocket, `host_addr = ("relay_peer", 0)`
- `broadcast()` uses `sendto_broadcast()` (one packet) instead of per-client sendto

### Client Reconciliation (CRITICAL for relay)
Higher latency (50-200ms) causes local prediction to diverge more from server state. Key fixes in `_reconcile_local_car()`:
- **Always blend velocity + angle** toward server (not just position)
- **Clear `_wall_normal`** when server shows car moving (speed > 30px/s) — prevents local-only collisions from blocking acceleration
- **Snap teleport** clears wall contact state completely

### Client Power-up Activation
Online clients do NOT call `_activate_powerup()` locally on click. Instead:
1. Click sets `input_use_powerup = True`
2. `send_input()` sends the flag to the server
3. Flag is cleared after send (one-shot)
4. Server activates the powerup authoritatively

## Important Patterns

1. **Lazy loading:** `tile_defs.py` loads tileset on first API call (`_ensure_loaded()`)
2. **Pre-rendering:** Both Track and TileTrack pre-render `track_surface` (full world size) and extract chunks per frame
3. **Coordinate systems:**
   - World coords: (0,0) to (3600, 2400)
   - Tile coords: (row, col) where row=0..36, col=0..55
   - Screen coords: (0,0) to (1280, 720) after camera transform
4. **Event handling:** Pygame 2.x uses `TEXTINPUT` for character input (not `KEYDOWN.unicode`)
5. **Track interface compatibility:** Any new track type must provide the same attributes/methods as Track
6. **Particle pool:** `DustParticleSystem` pre-allocates 120 `Particle` objects (with `__slots__`) to avoid per-frame allocations. Circular index reuses dead particles.
7. **Path resolution:** Always use `utils/base_path.py` (`TRACKS_DIR`, `ASSETS_DIR`, `get_writable_dir()`) for file paths. Never use `os.path.dirname(__file__)` for data files — it breaks in PyInstaller frozen builds.

## Render Order (_render_race)

```
1. Track surface
2. Oil slicks
3. Power-up pickups
4. Dust particles      ← particles.py
5. Cars
6. Missiles
```

## Build & Distribution

- **Build game:** `build_game.bat` → `dist/game/` (PyInstaller onedir)
- **Build launcher:** `build_launcher.bat` → `dist/launcher.exe`
- **Build all:** `build_all.bat`
- **Release:** Compress `dist/game/` as ZIP, upload to GitHub Release with tag `vX.Y.Z`
- **PyInstaller specs:** `game.spec` (hiddenimports must include all modules), `launcher.spec`
- **Adding new modules:** Remember to add to `hiddenimports` in `game.spec`
- **RL Training deps:** `game.spec` uses `collect_all()` for `gymnasium` and `stable_baselines3`. Do NOT add `email`/`unittest` to excludes. Build size ~500MB+ due to PyTorch.

## Auto-Update System (launcher/)

The launcher checks GitHub Releases for new versions and handles download/install:

1. Compare local `version.txt` vs GitHub release tag
2. Download `.zip` asset (streaming with progress)
3. Verify zip integrity
4. Extract to `game_update_temp/`
5. Backup `game/` → `game_backup/`
6. Swap: `game_update_temp/` → `game/`
7. **Restore user data:** Copy user tracks from backup to new install (preserves custom maps)
8. Write new version, cleanup backup

On failure: automatic rollback from `game_backup/`.

**Key paths (relative to dist/):**
- `game/` — Game installation
- `game/tracks/` — User tracks (preserved across updates)
- `version.txt` — Current version
- `config.json` — Update URL, timeouts

## Running the Game

```bash
cd racing_game
pip install pygame
pip install gymnasium stable-baselines3  # for RL training feature
python main.py

# To run the relay server (for internet multiplayer):
python relay_server/relay_server.py --port 7777
```

### Menu Controls
- **ENTER** — Open track selection
- **E** — Open track editor
- **J** — Join online game (LAN, enter IP)
- **R** — Join online game (Relay, enter server + room code)
- **ESC** — Quit

### Race Controls
- **W/S** — Accelerate/Reverse
- **A/D** — Turn
- **SPACE** — Handbrake
- **L-CLICK** — Use power-up
- **ESC** — Back to menu (or editor if test race)

### Track Select
- **UP/DOWN** — Navigate
- **ENTER** — Start race
- **E** — Edit selected track (tile-based only)
- **H** — Host online game (LAN)
- **R** — Host online game (Relay, creates room with code)
- **T** — Train AI model (tile-based only)
- **ESC** — Back to menu

### Training Screen
- **UP/DOWN** — Adjust timesteps (50k–1M)
- **ENTER** — Start training (idle) / Back (done/error)
- **ESC** — Cancel training / Back

## Known Bugs / Pending

*No known open bugs at this time.*

### Resolved Issues (v1.1.0 development)

Documented here for context if similar issues arise:

1. **Training subprocess launched another game window** — `sys.executable` in frozen exe points to `game.exe`, not python. Fixed with `--train-subprocess` flag in `main.py` that routes to headless training mode.

2. **ENTER key did nothing in training screen** — The `if/elif` chain in `_handle_events` handled ENTER/ESC before reaching `STATE_TRAINING`. Fixed by adding training state checks inside the existing ENTER and ESC blocks.

3. **Missing RL dependencies in PyInstaller build** — `hiddenimports` alone doesn't bundle all submodules. Fixed with `collect_all('gymnasium')` and `collect_all('stable_baselines3')` in `game.spec`.

4. **`No module named 'email'` / `'unittest'` in build** — These were in `excludes` in `game.spec` but SB3/torch need them. Fixed by removing from excludes.

5. **Track file not found in frozen exe** — `os.path.dirname(__file__)` points to `_internal/`, but tracks live next to the exe. Fixed by using `TRACKS_DIR` from `utils/base_path.py`.

6. **Trained model not loaded in frozen exe** — Same path issue as #5 but for `models/`. Fixed by using `get_writable_dir()` from `utils/base_path.py`.

7. **Errors invisible in training UI** — Subprocess crashes showed generic "exited unexpectedly". Fixed with: global try/except in `train_ai.main()`, stderr capture, `training_error.log` file, multi-line error display in UI.

8. **Relay "room not found" after joining** — The initial design used a temporary socket for room handshake then created a new RelaySocket (different local port). The relay server tracked peers by `(ip, port)`, so the new socket was unrecognized. Fixed by making `RelaySocket` perform the handshake (`create_room()`/`join_room()`) on its own internal socket, then passing the same `RelaySocket` to `GameServer`/`GameClient` via the `relay_socket=` parameter.

9. **Client stuck on walls via relay** — Higher latency caused local prediction to collide with walls while the server saw no collision. `car._wall_normal` blocked acceleration locally, creating a stuck loop. Fixed by blending velocity/angle during reconciliation and clearing `_wall_normal` when server state shows the car moving normally.

10. **Client couldn't use power-ups online** — Mouse click called `_activate_powerup()` locally, which consumed `held_powerup` without informing the server. The `input_use_powerup` flag was never set. Fixed by setting the flag on click (instead of activating locally) so `send_input()` notifies the server, which activates authoritatively.
