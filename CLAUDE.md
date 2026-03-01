# CLAUDE.md - Arcade Racing 2D

## Project Overview

**2D top-down arcade racing game** built with **Pygame** (Python 3.12+). Features a tile-based track editor, AI opponents, power-ups, dust particles, a rotating camera system, and multiplayer via LAN or internet relay. The game supports two track formats: classic (control points + Chaikin smoothing) and tile-based (painted grid).

**Current version:** 1.2.0
**Entry point:** `python main.py`

## Directory Structure

```
racing_game/
├── main.py              (~40 lines)  - Entry point + --train/--dedicated routing
├── game.py              (~2250 lines) - Game loop, state machine, orchestration
├── settings.py          (~270 lines) - All configuration constants
├── track_manager.py     (~200 lines) - Track file I/O (JSON save/load)
├── tile_track.py        (~500 lines) - Tile-based track (TileTrack class)
├── tile_defs.py         (~360 lines) - Tile definitions, classification, sprites
├── tile_meta.py         (~240 lines) - Per-tile metadata (friction, collision shapes)
├── tile_collision.py    (~180 lines) - Collision shapes + boundary mask builder
├── editor.py           (~1200 lines) - Tile editor (TileEditor class)
├── version.txt                      - Current version number (e.g. "1.2.0")
│
├── networking/
│   ├── __init__.py                  - Package marker
│   ├── protocol.py      (~530 lines) - Binary UDP protocol (pack/unpack, redundant inputs)
│   ├── net_state.py     (~100 lines) - Data classes (NetCarState, StateSnapshot, InputState)
│   ├── server.py        (~470 lines) - GameServer (host-side UDP, supports LAN + relay)
│   ├── client.py        (~410 lines) - GameClient (client-side UDP, adaptive interp, redundant input)
│   ├── relay_protocol.py (~120 lines) - Relay binary protocol (room commands + forwarding)
│   └── relay_socket.py  (~210 lines) - RelaySocket drop-in adapter for transparent relay
│
├── server/
│   ├── __init__.py                  - Package marker
│   ├── dedicated_server.py (~120 lines) - Headless dedicated server (fixed timestep loop)
│   ├── room.py          (~190 lines) - Room state machine (LOBBY→COUNTDOWN→RACING→DONE)
│   └── world_simulation.py (~410 lines) - Authoritative world simulation (physics, AI, powerups)
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
│   ├── physics.py       (~170 lines) - Acceleration, friction, turning, wall bounce
│   ├── collision.py     (~470 lines) - Circle-vs-Tile-AABB + sub-stepped CCD collisions
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

Dedicated Server (headless):
  main.py --dedicated-server → DedicatedServer → Room(LOBBY→COUNTDOWN→RACING→DONE)
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
- **Networking:** port=5555 (LAN), tick_rate=60Hz, snapshot_rate=30Hz, input_rate=60Hz, timeout=5s
- **Networking advanced:** input_redundancy=3, interp_min=33ms, interp_max=200ms, extrapolation_max=100ms
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

### Key API (tile_defs.py)
```python
is_driveable(tile_id) → bool      # WARNING: returns False for all tiles on headless server (no tileset.png)
get_tile_sprite(tile_id) → Surface(64x64) | None
get_tiles_by_category(cat) → [tile_id, ...]
get_tileset_sheet() → Surface (original image)
get_tileset_dimensions() → (cols, rows)
get_tile_at_position(src_row, src_col) → tile_id | None
get_tile_info(tile_id) → dict | None
empty_terrain() → [[T_EMPTY]*56 for _ in range(37)]
```

### Tile Metadata (tile_meta.py)
Per-tile metadata stored in `assets/levels/tileset_meta.json`. Auto-generated from pixel classification on first run.
- Categories: `terrain` (driveable), `props` (decorative blockers), `obstacles` (walls), `special` (finish)
- Collision types: `none` (free), `full` (solid wall), `polygon` (custom shape with normalized 0-1 vertices)
- `TileMetadataManager` singleton: `get_manager()` → `.get(tid)`, `.is_driveable(tid)`, `.get_friction(tid)`

### Boundary Mask (tile_collision.py)
- `build_boundary_mask(terrain, rotations, driveable_set)` — world-sized `pygame.mask.Mask` for ray/missile collision
- Uses `tile_meta` collision_type per tile. Accepts `driveable_set` for server-safe fallback.
- `build_friction_map(terrain, overrides)` — per-tile friction grid for variable surface friction

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
  "circuit_direction": [x1, y1, x2, y2],
  "driveable_tiles": [1, 206, 207, 271]
}
```
- `rotations` (v4): per-tile rotation 0-3 (0/90/180/270 deg). Bumps version to 4.
- `checkpoint_zones`: manual checkpoint rectangles from editor (0-indexed, C0 = finish area).
- `circuit_direction`: optional arrow [start_x, start_y, end_x, end_y] in world coords.
- `driveable_tiles`: sorted list of unique tile IDs that are driveable (auto-computed on save). **Critical for dedicated servers** that don't have `tileset.png` — without this field, the server cannot determine which tiles are road vs wall.

Tracks stored in `tracks/` directory. `list_tracks()` returns both formats with `type` field.

`save_tile_track(filename, name, terrain, tile_overrides=None, rotations=None, checkpoint_zones=None, circuit_direction=None, powerup_zones=None)`

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

Two collision backends depending on track type:

### Tile tracks: Circle-vs-Tile-AABB (geometric)
- Car has `collision_radius` (default 12px). Each frame, the circle is tested against solid tile AABBs.
- `_circle_vs_tiles(cx, cy, r)` → finds closest point on each nearby solid tile's AABB to the circle center, returns (hit, normal, penetration).
- `_solid` grid pre-computed in `__init__` from track's `_driveable_set` (or `tile_defs.is_driveable()` fallback).
- `move_with_substeps(car, dt)` — CCD anti-tunneling: splits movement into sub-steps of max `COLLISION_MAX_STEP` (8px). On collision: geometric push-out by penetration depth. Falls back to rollback if push-out creates new collision (corners/narrow corridors).
- `ensure_valid_spawn(car)` — iterative push-out (max 10 steps) to ensure car doesn't spawn inside a wall.

### Classic tracks: 16-point mask sampling (fallback)
- 16 points sampled around circle perimeter tested against `boundary_mask`.
- On collision: rollback to previous position.

### Other collisions
- **Car vs car:** Distance between centers < sum of radii. Push apart by overlap, reflect velocities.
- **Car vs checkpoints:** Zone rect collision (manual zones from editor, sequential order).
- **Car vs power-ups/missiles/oil/mines:** Distance checks.

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

### Client Predictive Car-vs-Car Collision
Local prediction (`_simulate_car_step_headless`) only simulates wall collisions. Without car-vs-car prediction, the local car visually passes through remote cars for a few frames until the server correction arrives (causing a "teleport snap-back").

**Solution:** `_predict_car_vs_car_local(local_car, remote_car)` — one-sided push that only moves the local car away from the remote car. Uses the same `half = (overlap+1)*0.5` push distance as the server so the prediction matches. Applied in two places:
1. After `_simulate_car_step_headless()` in the main prediction loop (each tick)
2. After `_simulate_car_step_headless()` in the reconciliation replay loop

Does NOT move remote cars (server-authoritative). Does NOT modify the server, protocol, or collision system.

### Input Redundancy (Packet Loss Recovery)
Each input packet carries the last 3 inputs (newest first) instead of just 1. If packet N is lost but N+1 arrives, the server recovers input N from the redundant data in N+1.

**Protocol format:** `[header][count:1B][input1:7B][input2:7B][input3:7B]`
- `count`: 1–3 (number of inputs in packet)
- Each input: same `INPUT_FMT` as before (player_id, accel, turn, brake, use_pw, seq)
- `pack_input_redundant(pid, inputs)` / `unpack_input(data)` → returns list of dicts
- **Backward compatible:** `unpack_input` auto-detects legacy single-input packets

**Client:** `_recent_inputs` ring buffer (max 3 entries, newest first). `send_input()` calls `pack_input_redundant()`.
**Server:** `_handle_input()` iterates over the input list. Existing dedup by seq rejects already-processed inputs.
**Overhead:** +15 bytes/packet (25 vs 10). At 60Hz = ~900 bytes/s extra.

### Remote Car Extrapolation (Dead Reckoning)
When `render_time` is beyond the latest snapshot (late arrival / jitter), instead of freezing the remote car at the last known position, extrapolate using velocity:
```python
target_car.x += car_state.vx * dt_extra
target_car.y += car_state.vy * dt_extra
```
- `dt_extra` capped at `NET_EXTRAPOLATION_MAX` (100ms) to prevent runaway divergence
- Only activates when no snapshot pair is available for interpolation
- Falls back to regular `apply_net_state()` when snapshots arrive on time

### Adaptive Interpolation Delay
The interpolation delay for remote cars adjusts dynamically based on measured network jitter, instead of using a fixed 100ms constant.

**Algorithm:** In `_handle_snapshot()`, measure inter-arrival times of consecutive snapshots. Compute:
```
adaptive_delay = avg_interval + 2 * stddev(intervals)
```
Clamped between `NET_INTERP_MIN_DELAY` (33ms) and `NET_INTERP_MAX_DELAY` (200ms).

**Measured results:**
- **LAN** (~2ms jitter): delay = ~36ms (vs 100ms fixed — 64ms more responsive)
- **Relay** (~20ms jitter): delay = ~78ms (auto-adapts)
- **Bad connection** (~40ms jitter): delay = ~119ms (auto-buffers more)

**API:** `GameClient.get_adaptive_delay()` → float (seconds). Used in `game.py` for `render_time` calculation. Shown in F3 debug overlay as "Interp dl".

**Reset:** `clear_snapshots()` resets jitter samples and falls back to `NET_INTERPOLATION_DELAY` (100ms) until enough samples (5+) are collected.

## Dedicated Server (server/)

### Architecture
Headless authoritative server that runs the full game simulation without a display. Clients connect via LAN or relay and receive state snapshots.

```
main.py --dedicated-server track_file [--bots N] [--port P]
  → SDL_VIDEODRIVER=dummy + pygame.display.set_mode((1,1))
  → DedicatedServer(track, bots, port).run()
```

### Components

| File | Role |
|------|------|
| `dedicated_server.py` | Fixed-timestep main loop (60Hz physics, MAX_TICKS_PER_FRAME=2 catch-up) |
| `room.py` | State machine: LOBBY → COUNTDOWN → RACING → DONE |
| `world_simulation.py` | Authoritative simulation: physics, collisions, AI, power-ups, checkpoints |

### Room State Machine
- **LOBBY**: Broadcasts lobby state every 250ms. Auto-starts race when `DEDICATED_MIN_PLAYERS` connected for `DEDICATED_AUTO_START_DELAY` seconds.
- **COUNTDOWN**: 4 seconds total (`_countdown_secs=4`). Sends `display_countdown=3` to clients (shows "3, 2, 1, GO!"). Must match client countdown duration to avoid position jumps.
- **RACING**: Pops 1 input per player per tick. Runs `WorldSimulation.step()`. Broadcasts snapshots at 30Hz (every 2nd tick). Broadcasts power-up events (3x redundancy).
- **DONE**: Race finished (all cars done or 15s after winner).

### Server-Safe Tile Classification (CRITICAL)
The dedicated server typically runs on a VPS **without `tileset.png`**. Without the tileset image, `tile_defs._do_load()` fails and ALL road tiles are treated as walls. This causes wrong start positions, wrong collision grid, and wrong DFS path.

**Solution:** Track JSON includes `driveable_tiles` (list of driveable tile IDs, auto-computed when saving from the editor). At runtime:
- `TileTrack` builds `_driveable_set` from the embedded list
- `CollisionSystem._solid` grid uses `track._driveable_set` instead of `tile_defs.is_driveable()`
- `tile_collision.build_boundary_mask()` uses `driveable_set` for tiles not in `tile_meta`
- All internal `_trace_circuit()`, `_is_driveable_at()`, `_is_world_pos_driveable()` use the embedded set

**Tracks must be re-saved from the editor** after this change to embed `driveable_tiles`. Old tracks without this field fall back to `tile_defs.is_driveable()`.

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
8. **Server-safe tile checks:** Never call `tile_defs.is_driveable()` directly in code that runs on the dedicated server. Use `track._driveable_set` (from embedded `driveable_tiles` in the track JSON) or `track._is_tid_driveable()` instead. The server has no `tileset.png` and `is_driveable()` returns `False` for all tileset tiles.
9. **Input redundancy:** Client sends last 3 inputs per packet via `pack_input_redundant()`. Server deduplicates naturally via seq check. If modifying input protocol, update both `pack_input_redundant()` and `unpack_input()` in `protocol.py`.
10. **Adaptive interpolation:** Remote car interpolation delay is dynamic (`get_adaptive_delay()`), not the fixed `NET_INTERPOLATION_DELAY` constant. The constant is only used as the initial fallback before enough jitter samples are collected.
11. **Client-side car-vs-car prediction:** `_predict_car_vs_car_local()` only pushes the local car (one-sided). Never move remote cars in client prediction — they are server-authoritative.

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

## Server Deployment (DigitalOcean Droplet)

The dedicated server is deployed to a DigitalOcean droplet using **git sparse checkout**. Only the ~28 Python files the server needs are materialized on the droplet (no `game.py`, `editor.py`, `assets/cars/`, `launcher/`). Updating the server = `git pull`.

### Architecture

```
Windows (Git Bash)                    Droplet (Ubuntu)
┌──────────────────┐   git push      ┌──────────────────────────────┐
│ racing_game/     │ ──────────────► │ /home/racing/racing_server/  │
│ (full repo)      │                 │ (sparse checkout, ~28 files) │
│                  │   SSH           │                              │
│ deploy_server.sh │ ──────────────► │ systemctl restart            │
└──────────────────┘                 │ racing-server.service        │
                                     └──────────────────────────────┘
```

### deploy_server.sh

Script bash (compatible con Git Bash en Windows) que automatiza el deploy. Se configura con variables de entorno o editando los valores por defecto al inicio del script.

**Variables de configuración:**

| Variable | Default | Descripción |
|----------|---------|-------------|
| `RACING_SERVER_IP` | (requerido) | IP del droplet |
| `RACING_SERVER_USER` | `racing` | Usuario SSH |
| `RACING_SSH_KEY` | (system default) | Path a SSH key |
| `RACING_REPO_URL` | (from `origin` remote) | URL del repo Git |
| `RACING_TRACK_FILE` | `leve_4.json` | Nombre del track (sin `tracks/`) |
| `RACING_BOT_COUNT` | `1` | Número de bots |
| `RACING_GAME_PORT` | `5555` | Puerto UDP del juego |
| `RACING_BRANCH` | `main` | Branch de git |

**Modos de uso:**

```bash
# Configurar IP (o editar directamente en deploy_server.sh línea 18)
export RACING_SERVER_IP=143.198.138.38

# Setup inicial (una vez): instala python, git, pygame, clona repo con sparse checkout
bash deploy_server.sh --setup

# Instalar servicio systemd (una vez): crea el servicio, lo habilita e inicia
bash deploy_server.sh --install-service

# Deploy normal (diario): git push + git pull en droplet + restart servicio
bash deploy_server.sh
```

### Server Management Commands

```bash
# Ver estado del servicio
ssh racing@IP "systemctl status racing-server"

# Ver logs en tiempo real
ssh racing@IP "journalctl -u racing-server -f"

# Ver últimas N líneas de logs
ssh racing@IP "journalctl -u racing-server -n 20"

# Reiniciar el servidor manualmente
ssh racing@IP "sudo systemctl restart racing-server"

# Parar el servidor
ssh racing@IP "sudo systemctl stop racing-server"

# Iniciar el servidor
ssh racing@IP "sudo systemctl start racing-server"

# Ver qué archivos tiene el servidor (verificar sparse checkout)
ssh racing@IP "find /home/racing/racing_server -name '*.py' -not -path '*/venv/*'"

# Ver el archivo del servicio systemd
ssh racing@IP "cat /etc/systemd/system/racing-server.service"
```

### Files

| File | Description |
|------|-------------|
| `deploy_server.sh` | Script de deploy con 3 modos (--setup, --install-service, deploy) |
| `server/requirements-server.txt` | Dependencias del servidor (solo pygame) |
| `.github/workflows/deploy-server.yml` | GitHub Actions auto-deploy (deshabilitado, requiere secrets) |

### IMPORTANT: Track filename

The `--track` argument takes only the filename (e.g. `leve_4.json`), NOT the full path. The code internally prepends `TRACKS_DIR` (`tracks/`). Passing `tracks/leve_4.json` causes a double path: `tracks/tracks/leve_4.json`.

### CI/CD (optional, future)

`.github/workflows/deploy-server.yml` auto-deploys when server-relevant files change on `main`. Currently disabled (`if: false`). To enable:
1. Add GitHub secrets: `SERVER_SSH_KEY`, `SERVER_IP`, `SERVER_USER`
2. Remove the `if: false` line from the workflow

## Running the Game

```bash
cd racing_game
pip install pygame
pip install gymnasium stable-baselines3  # for RL training feature
python main.py

# To run the dedicated server (headless, for multiplayer):
python main.py --dedicated-server --track leve_4.json --bots 1 --port 5555

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

### Resolved Issues (v1.2.0 — Dedicated Server + Collision Rewrite)

11. **Countdown timing mismatch (server vs client)** — Server had `_countdown_secs=3` while client expected 4 seconds (3,2,1,GO!). The 1-second gap caused the server to start physics before the client's countdown finished, resulting in a position jump when the client entered RACING state. Fixed by setting server `_countdown_secs=4` and sending `display_countdown = _countdown_secs - 1 = 3` to clients.

12. **Dedicated server wrong tile classification (tileset.png missing)** — Root cause of cars spawning inside checkpoints/walls on the dedicated server. The VPS had no `tileset.png`, so `tile_defs._do_load()` failed silently → `_road_ids` empty → ALL road tiles treated as non-driveable → wrong DFS path → wrong start positions → `ensure_valid_spawn` pushed car into wrong location (40px x 96px mismatch vs client). Fixed by embedding `driveable_tiles` list in track JSON at save time. `TileTrack`, `CollisionSystem`, and `build_boundary_mask` now use this embedded set instead of `tile_defs.is_driveable()` when available.

13. **Collision system rewrite (mask-based → circle-vs-tile-AABB)** — Original collision used pygame mask overlap which was angle-dependent, resolution-sensitive, and non-deterministic between client/server. Rewrote to geometric circle-vs-AABB intersection with sub-stepped CCD movement (`COLLISION_MAX_STEP=8px`). Cars have `collision_radius=12`. Push-out by exact penetration depth, with rollback fallback for corner cases. Consistent across all platforms.

### Networking Improvements (v1.2.x — Multiplayer Quality)

14. **Car-vs-car visual pass-through in multiplayer** — Client prediction (`_simulate_car_step_headless`) only simulated wall collisions but not car-vs-car. When Player A drove into Player B, A's local prediction showed pass-through for a few frames, then snapped back when the server correction arrived. Fixed with `_predict_car_vs_car_local()` — one-sided push matching the server's `half = (overlap+1)*0.5` formula. Applied in both the prediction loop and the reconciliation replay loop.

15. **Input packet loss causing server-side prediction errors** — Each input was sent once per frame. A single lost UDP packet meant the server had no input for that tick and repeated the previous one, causing divergence and large reconciliation corrections. Fixed by sending the last 3 inputs in every packet (`pack_input_redundant`). Server deduplicates via existing seq check. Overhead: +15 bytes/packet (~900 bytes/s at 60Hz).

16. **Remote cars freezing on late snapshots** — When a snapshot arrived late (jitter), remote cars froze at their last known position until the next snapshot. Fixed with dead-reckoning extrapolation: `pos += velocity * dt_extra` capped at 100ms (`NET_EXTRAPOLATION_MAX`). Cars now continue moving in their last known direction instead of stopping.

17. **Fixed 100ms interpolation delay too high for LAN, too low for relay** — The constant `NET_INTERPOLATION_DELAY = 0.1` was a compromise that was too sluggish for LAN (~2ms RTT) and sometimes insufficient for relay (~150ms RTT). Fixed with adaptive delay based on measured snapshot inter-arrival jitter: `delay = avg_interval + 2 * stddev`. LAN auto-tunes to ~36ms, relay to ~78-120ms depending on conditions. Clamped between 33ms and 200ms.
