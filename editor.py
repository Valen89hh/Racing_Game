"""
editor.py - Professional tile editor with panels, brushes, and property inspector.

Orchestrates TilesetBrowser, ToolsPanel, PropertyInspector, and CollisionEditor.
Supports single-tile and multi-tile brushes, per-tile metadata editing,
and custom collision polygons.
"""

import pygame

from settings import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    COLOR_WHITE, COLOR_BLACK, COLOR_YELLOW, COLOR_GREEN,
    COLOR_GRAY, COLOR_RED,
)
from tile_defs import (
    TILE_SIZE, GRID_COLS, GRID_ROWS,
    T_EMPTY, T_FINISH, TILE_BASE,
    is_driveable, get_tile_sprite,
    GRASS_COLOR, GRASS_DARK,
    empty_terrain, empty_rotations,
)
from tile_meta import get_manager, CATEGORY_DISPLAY
from tile_brush import Brush, BrushLibrary
from editor_panels import (
    TilesetBrowser, ToolsPanel, PropertyInspector,
    COL_PANEL_BG, COL_PANEL_BORDER, COL_TILE_SELECTED,
    COL_TILE_HOVER, COL_DRIVEABLE, COL_WHITE, COL_GRAY,
    COL_YELLOW, TILE_PREVIEW_SIZE,
)
import track_manager


# ── Layout ──
BOTTOM_PANEL_H = 200
STATUS_BAR_H = 28
VIEWPORT_HEIGHT = SCREEN_HEIGHT - BOTTOM_PANEL_H - STATUS_BAR_H  # 492
TOOLS_W = 130
INSPECTOR_W = 180

BROWSER_X = TOOLS_W
BROWSER_Y = VIEWPORT_HEIGHT
BROWSER_W = SCREEN_WIDTH - TOOLS_W - INSPECTOR_W
BROWSER_H = BOTTOM_PANEL_H

# ── Viewport ──
ZOOM_MIN = 0.1
ZOOM_MAX = 2.0
ZOOM_STEP = 0.08
MAX_UNDO = 30

# ── UI colors ──
COL_BAR = (20, 20, 20, 200)
COL_MSG = (100, 255, 150)
COL_DIALOG_BG = (25, 25, 35, 230)
COL_DIALOG_BORDER = (80, 120, 200)
COL_INPUT_BG = (40, 40, 55)
COL_TOOL_BG = (35, 40, 50)


class TileEditor:
    """Professional tile editor with panel-based UI."""

    def __init__(self, screen):
        self.screen = screen
        self.font = pygame.font.SysFont("consolas", 16)
        self.font_big = pygame.font.SysFont("consolas", 22, bold=True)
        self.font_small = pygame.font.SysFont("consolas", 12)

        # Tile data
        self.terrain = empty_terrain()
        self.rotations = empty_rotations()
        self.current_rotation = 0  # 0-3: 0/90/180/270 degrees

        # Viewport
        self.cam_x = (GRID_COLS * TILE_SIZE) / 2
        self.cam_y = (GRID_ROWS * TILE_SIZE) / 2
        self.zoom = 0.3

        # Viewport pan
        self.panning = False
        self.pan_start = (0, 0)
        self.pan_cam_start = (0, 0)

        # Painting
        self.painting = False
        self.erasing = False

        # Brush system (replaces selected_tile + brush_size)
        self.current_brush = Brush.single(T_EMPTY)
        self.selected_tile = T_EMPTY  # for Grass/Finish quick-select compat

        # Undo/Redo
        self.undo_stack = []
        self.redo_stack = []

        # UI state
        self.show_help = False
        self.status_msg = ""
        self.status_timer = 0.0

        # Dialog
        self.dialog_mode = None
        self.dialog_input = ""
        self.dialog_tracks = []
        self.dialog_selected = 0

        # Track info
        self.current_filename = None
        self.current_name = None

        # Result flag
        self.result = None

        # Collision editor (lazy import)
        self._collision_editor = None

        # Checkpoint mode
        self.checkpoint_mode = False
        self.checkpoint_zones = []      # list of [x, y, w, h] in world coords
        self.cp_drag_start = None       # (wx, wy) start of drag
        self.cp_drag_current = None     # (wx, wy) current drag position

        # Direction mode
        self.direction_mode = False
        self.circuit_direction = None   # [x1, y1, x2, y2] world coords, or None
        self.dir_drag_start = None      # (wx, wy) start of drag
        self.dir_drag_current = None    # (wx, wy) current position

        # Build preview sprites
        from tile_defs import make_grass_sprite
        self._grass_sprite = make_grass_sprite()

        # ── Panels ──
        self.tools_panel = ToolsPanel(pygame.Rect(
            0, VIEWPORT_HEIGHT, TOOLS_W, BOTTOM_PANEL_H))
        self.browser_panel = TilesetBrowser(pygame.Rect(
            BROWSER_X, BROWSER_Y, BROWSER_W, BROWSER_H))
        self.inspector_panel = PropertyInspector(pygame.Rect(
            SCREEN_WIDTH - INSPECTOR_W, VIEWPORT_HEIGHT,
            INSPECTOR_W, BOTTOM_PANEL_H))

        # Wire callbacks
        self.browser_panel.on_tile_selected = self._on_tile_selected
        self.browser_panel.on_brush_selected = self._on_brush_selected
        self.tools_panel.on_select_grass = lambda: self._set_tile(T_EMPTY)
        self.tools_panel.on_select_finish = lambda: self._set_tile(T_FINISH)
        self.tools_panel.on_save_brush = self._save_current_brush
        self.tools_panel.on_load_brush = self._load_brush
        self.inspector_panel.on_open_collision_editor = self._open_collision_editor

        self._fit_view()

    # ──────────────────────────────────────────
    # BRUSH / TILE SELECTION CALLBACKS
    # ──────────────────────────────────────────

    def _on_tile_selected(self, tile_id):
        self.selected_tile = tile_id
        self.current_brush = Brush.single(tile_id)
        self.inspector_panel.set_tile(tile_id)

    def _on_brush_selected(self, brush: Brush):
        self.current_brush = brush
        self.selected_tile = -1  # multi-tile brush, no single tile
        # Inspect first non-empty tile
        for row in brush.tiles:
            for tid in row:
                if tid != T_EMPTY:
                    self.inspector_panel.set_tile(tid)
                    return

    def _set_tile(self, tile_id):
        self.selected_tile = tile_id
        self.current_brush = Brush.single(tile_id)
        if tile_id not in (T_EMPTY,):
            self.inspector_panel.set_tile(tile_id)
        else:
            self.inspector_panel.set_tile(None)

    def _save_current_brush(self):
        if self.current_brush.width <= 1 and self.current_brush.height <= 1:
            self._show_msg("Select multi-tile brush first")
            return
        name = f"Brush {len(self.tools_panel.brush_library.brushes) + 1}"
        self.current_brush.name = name
        self.tools_panel.brush_library.save_brush(self.current_brush)
        self._show_msg(f"Saved: {name}")

    def _load_brush(self, brush: Brush):
        self.current_brush = brush
        self.selected_tile = -1
        self._show_msg(f"Loaded: {brush.name}")

    def _open_collision_editor(self, tile_id):
        from editor_collision import CollisionEditor
        self._collision_editor = CollisionEditor(self.screen, tile_id)

    # ──────────────────────────────────────────
    # COORDINATE TRANSFORMS
    # ──────────────────────────────────────────

    def world_to_screen(self, wx, wy):
        sx = (wx - self.cam_x) * self.zoom + SCREEN_WIDTH / 2
        sy = (wy - self.cam_y) * self.zoom + VIEWPORT_HEIGHT / 2
        return sx, sy

    def screen_to_world(self, sx, sy):
        wx = (sx - SCREEN_WIDTH / 2) / self.zoom + self.cam_x
        wy = (sy - VIEWPORT_HEIGHT / 2) / self.zoom + self.cam_y
        return wx, wy

    def screen_to_tile(self, sx, sy):
        wx, wy = self.screen_to_world(sx, sy)
        return int(wy // TILE_SIZE), int(wx // TILE_SIZE)

    # ──────────────────────────────────────────
    # HIT TESTING
    # ──────────────────────────────────────────

    def _is_in_viewport(self, sx, sy):
        return 0 <= sx < SCREEN_WIDTH and 0 <= sy < VIEWPORT_HEIGHT

    def _is_in_panel(self, sx, sy):
        return sy >= VIEWPORT_HEIGHT and sy < SCREEN_HEIGHT - STATUS_BAR_H

    # ──────────────────────────────────────────
    # UNDO / REDO
    # ──────────────────────────────────────────

    def _push_undo(self):
        snap = ([row[:] for row in self.terrain],
                [row[:] for row in self.rotations],
                [z[:] for z in self.checkpoint_zones],
                list(self.circuit_direction) if self.circuit_direction else None)
        self.undo_stack.append(snap)
        if len(self.undo_stack) > MAX_UNDO:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(([row[:] for row in self.terrain],
                                [row[:] for row in self.rotations],
                                [z[:] for z in self.checkpoint_zones],
                                list(self.circuit_direction) if self.circuit_direction else None))
        snap = self.undo_stack.pop()
        self.terrain = snap[0]
        self.rotations = snap[1]
        self.checkpoint_zones = snap[2] if len(snap) > 2 else []
        self.circuit_direction = snap[3] if len(snap) > 3 else None

    def _redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(([row[:] for row in self.terrain],
                                [row[:] for row in self.rotations],
                                [z[:] for z in self.checkpoint_zones],
                                list(self.circuit_direction) if self.circuit_direction else None))
        snap = self.redo_stack.pop()
        self.terrain = snap[0]
        self.rotations = snap[1]
        self.checkpoint_zones = snap[2] if len(snap) > 2 else []
        self.circuit_direction = snap[3] if len(snap) > 3 else None

    # ──────────────────────────────────────────
    # PAINTING
    # ──────────────────────────────────────────

    def _paint_at(self, row, col):
        """Paint current brush at grid position."""
        if self.selected_tile == T_EMPTY:
            # Eraser mode with brush size
            w, h = self.current_brush.width, self.current_brush.height
            for dr in range(h):
                for dc in range(w):
                    r, c = row + dr, col + dc
                    if 0 <= r < GRID_ROWS and 0 <= c < GRID_COLS:
                        self.terrain[r][c] = T_EMPTY
                        self.rotations[r][c] = 0
        else:
            self.current_brush.paint_at(
                self.terrain, row, col,
                rotations_grid=self.rotations,
                rotation_offset=self.current_rotation)

    def _erase_at(self, row, col):
        w = max(1, self.current_brush.width)
        h = max(1, self.current_brush.height)
        for dr in range(h):
            for dc in range(w):
                r, c = row + dr, col + dc
                if 0 <= r < GRID_ROWS and 0 <= c < GRID_COLS:
                    self.terrain[r][c] = T_EMPTY
                    self.rotations[r][c] = 0

    # ──────────────────────────────────────────
    # FIT VIEW / STATUS
    # ──────────────────────────────────────────

    def _fit_view(self):
        total_w = GRID_COLS * TILE_SIZE
        total_h = GRID_ROWS * TILE_SIZE
        self.cam_x = total_w / 2
        self.cam_y = total_h / 2
        zx = SCREEN_WIDTH / total_w
        zy = VIEWPORT_HEIGHT / total_h
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, min(zx, zy) * 0.9))

    def _show_msg(self, text, duration=2.5):
        self.status_msg = text
        self.status_timer = duration

    # ──────────────────────────────────────────
    # VALIDATION
    # ──────────────────────────────────────────

    def _has_circuit(self):
        count = 0
        has_finish = False
        for row in self.terrain:
            for t in row:
                if is_driveable(t):
                    count += 1
                if t == T_FINISH:
                    has_finish = True
        return has_finish and count >= 10

    def _build_tile_data(self):
        data = {
            "name": self.current_name or "Untitled",
            "format": "tiles",
            "version": 3,
            "tile_size": TILE_SIZE,
            "grid_width": GRID_COLS,
            "grid_height": GRID_ROWS,
            "terrain": [row[:] for row in self.terrain],
        }
        has_rotations = any(
            r != 0 for row in self.rotations for r in row)
        if has_rotations:
            data["rotations"] = [row[:] for row in self.rotations]
            data["version"] = 4
        if self.checkpoint_zones:
            data["checkpoint_zones"] = [z[:] for z in self.checkpoint_zones]
        if self.circuit_direction:
            data["circuit_direction"] = list(self.circuit_direction)
        return data

    # ──────────────────────────────────────────
    # DIALOGS
    # ──────────────────────────────────────────

    def _open_save_dialog(self):
        self.dialog_mode = "save"
        self.dialog_input = self.current_name or ""

    def _open_load_dialog(self):
        self.dialog_mode = "load"
        self.dialog_tracks = track_manager.list_tracks()
        self.dialog_selected = 0

    def _close_dialog(self):
        self.dialog_mode = None
        self.dialog_input = ""

    def _do_save(self):
        name = self.dialog_input.strip()
        if not name:
            self._show_msg("Name cannot be empty")
            return
        filename = name.lower().replace(" ", "_")
        try:
            track_manager.save_tile_track(
                filename, name, self.terrain,
                rotations=self.rotations,
                checkpoint_zones=self.checkpoint_zones or None,
                circuit_direction=self.circuit_direction)
            self.current_filename = filename
            self.current_name = name
            self._close_dialog()
            self._show_msg(f"Saved: {filename}.json")
        except OSError as e:
            self._show_msg(f"Error: {e}")

    def _do_load(self):
        if not self.dialog_tracks:
            return
        entry = self.dialog_tracks[self.dialog_selected]
        try:
            data = track_manager.load_track(entry["filename"])
            if data.get("format") != "tiles":
                self._show_msg("Classic track - not tile-based")
                return
            self._push_undo()
            self.terrain = data["terrain"]
            self.rotations = data.get("rotations", None)
            if self.rotations is None:
                self.rotations = empty_rotations()
            self.checkpoint_zones = [
                z[:] for z in data.get("checkpoint_zones", [])]
            self.circuit_direction = data.get("circuit_direction", None)
            self.current_filename = entry["filename"].replace(".json", "")
            self.current_name = data.get("name", self.current_filename)
            self._close_dialog()
            self._fit_view()
            self._show_msg(f"Loaded: {entry['name']}")
        except (OSError, KeyError) as e:
            self._show_msg(f"Error: {e}")

    def load_from_file(self, filename):
        """Load an existing tile track into the editor."""
        try:
            data = track_manager.load_track(filename)
            if data.get("format") != "tiles":
                self._show_msg("Classic track - not tile-based")
                return False
            self._push_undo()
            self.terrain = data["terrain"]
            self.rotations = data.get("rotations", None)
            if self.rotations is None:
                self.rotations = empty_rotations()
            self.checkpoint_zones = [
                z[:] for z in data.get("checkpoint_zones", [])]
            self.circuit_direction = data.get("circuit_direction", None)
            self.current_filename = filename.replace(".json", "")
            self.current_name = data.get("name", self.current_filename)
            self._fit_view()
            self._show_msg(f"Editing: {self.current_name}")
            return True
        except (OSError, KeyError) as e:
            self._show_msg(f"Error loading: {e}")
            return False

    def _quick_save(self):
        if self.current_filename:
            try:
                track_manager.save_tile_track(
                    self.current_filename,
                    self.current_name or self.current_filename,
                    self.terrain,
                    rotations=self.rotations,
                    checkpoint_zones=self.checkpoint_zones or None,
                    circuit_direction=self.circuit_direction)
                self._show_msg(f"Saved: {self.current_filename}.json")
            except OSError as e:
                self._show_msg(f"Error: {e}")
        else:
            self._open_save_dialog()

    # ──────────────────────────────────────────
    # EVENT HANDLING
    # ──────────────────────────────────────────

    def handle_event(self, event):
        # Collision editor captures all events when active
        if self._collision_editor is not None:
            result = self._collision_editor.handle_event(event)
            if self._collision_editor.done:
                self._collision_editor = None
            return True

        if self.dialog_mode:
            return self._handle_dialog_event(event)

        if event.type == pygame.KEYDOWN:
            return self._handle_keydown(event)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            return self._handle_mousedown(event)
        elif event.type == pygame.MOUSEBUTTONUP:
            return self._handle_mouseup(event)
        elif event.type == pygame.MOUSEMOTION:
            return self._handle_mousemotion(event)
        elif event.type == pygame.MOUSEWHEEL:
            return self._handle_mousewheel(event)
        return True

    def _handle_dialog_event(self, event):
        if event.type == pygame.TEXTINPUT:
            if self.dialog_mode == "save":
                if len(self.dialog_input) < 30:
                    self.dialog_input += event.text
            return True

        if event.type != pygame.KEYDOWN:
            return True
        if event.key == pygame.K_ESCAPE:
            self._close_dialog()
            return True
        if self.dialog_mode == "save":
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._do_save()
            elif event.key == pygame.K_BACKSPACE:
                self.dialog_input = self.dialog_input[:-1]
        elif self.dialog_mode == "load":
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._do_load()
            elif event.key == pygame.K_UP:
                self.dialog_selected = max(0, self.dialog_selected - 1)
            elif event.key == pygame.K_DOWN:
                self.dialog_selected = min(
                    len(self.dialog_tracks) - 1, self.dialog_selected + 1)
        return True

    def _handle_keydown(self, event):
        mods = pygame.key.get_mods()
        ctrl = mods & pygame.KMOD_CTRL
        shift = mods & pygame.KMOD_SHIFT

        if event.key == pygame.K_ESCAPE:
            if self.direction_mode:
                self.direction_mode = False
                self.dir_drag_start = None
                self.dir_drag_current = None
                self._show_msg("Direction mode OFF")
                return True
            if self.checkpoint_mode:
                self.checkpoint_mode = False
                self.cp_drag_start = None
                self.cp_drag_current = None
                self._show_msg("Checkpoint mode OFF")
                return True
            self.result = "menu"
            return True

        if ctrl and event.key == pygame.K_z:
            self._undo()
            return True
        if ctrl and event.key == pygame.K_y:
            self._redo()
            return True
        if ctrl and event.key == pygame.K_s:
            self._quick_save()
            return True
        if ctrl and event.key == pygame.K_o:
            self._open_load_dialog()
            return True
        if ctrl and event.key == pygame.K_n:
            self._push_undo()
            self.terrain = empty_terrain()
            self.rotations = empty_rotations()
            self.current_rotation = 0
            self.checkpoint_zones = []
            self.circuit_direction = None
            self.current_filename = None
            self.current_name = None
            self._show_msg("New track")
            return True

        if event.key == pygame.K_r and not ctrl:
            if shift:
                self.current_rotation = (self.current_rotation - 1) % 4
            else:
                self.current_rotation = (self.current_rotation + 1) % 4
            self._show_msg(f"Rotation: {self.current_rotation * 90}\u00b0")
            return True

        if event.key == pygame.K_h:
            self.show_help = not self.show_help
            return True
        if event.key == pygame.K_f:
            self._fit_view()
            return True

        if event.key == pygame.K_t:
            if self._has_circuit():
                self.result = "test"
            else:
                self._show_msg("Need finish + circuit (10+ driveable)")
            return True

        if event.key == pygame.K_c and not ctrl:
            self.checkpoint_mode = not self.checkpoint_mode
            self.cp_drag_start = None
            self.cp_drag_current = None
            if self.checkpoint_mode:
                self.direction_mode = False
                self._show_msg("Checkpoint mode ON  (drag=place, R-click=delete)")
            else:
                self._show_msg("Checkpoint mode OFF")
            return True

        if event.key == pygame.K_d and not ctrl:
            self.direction_mode = not self.direction_mode
            self.dir_drag_start = None
            self.dir_drag_current = None
            if self.direction_mode:
                self.checkpoint_mode = False
                self._show_msg("Direction mode ON  (drag=set arrow, R-click=delete)")
            else:
                self._show_msg("Direction mode OFF")
            return True

        # Brush size with Shift+1/2/3
        if shift:
            if event.key == pygame.K_1:
                self.current_brush = Brush.single(
                    self.selected_tile if self.selected_tile >= 0 else T_EMPTY)
                self._show_msg("Brush: 1x1")
                return True
            if event.key == pygame.K_2:
                tid = self.selected_tile if self.selected_tile >= 0 else T_EMPTY
                self.current_brush = Brush([[tid, tid], [tid, tid]])
                self._show_msg("Brush: 2x2")
                return True
            if event.key == pygame.K_3:
                tid = self.selected_tile if self.selected_tile >= 0 else T_EMPTY
                self.current_brush = Brush([[tid]*3]*3)
                self._show_msg("Brush: 3x3")
                return True

        return True

    def _handle_mousedown(self, event):
        sx, sy = event.pos

        # ── Panel areas: delegate to panels ──
        if self._is_in_panel(sx, sy):
            if self.browser_panel.contains(sx, sy):
                return self.browser_panel.handle_event(event)
            if self.tools_panel.contains(sx, sy):
                return self.tools_panel.handle_event(event)
            if self.inspector_panel.contains(sx, sy):
                return self.inspector_panel.handle_event(event)
            return True

        # ── Viewport ──
        if not self._is_in_viewport(sx, sy):
            return True

        keys = pygame.key.get_pressed()
        if event.button == 2 or (event.button == 1 and keys[pygame.K_SPACE]):
            self.panning = True
            self.pan_start = (sx, sy)
            self.pan_cam_start = (self.cam_x, self.cam_y)
            return True

        # ── Direction mode ──
        if self.direction_mode:
            if event.button == 1:
                wx, wy = self.screen_to_world(sx, sy)
                self.dir_drag_start = (wx, wy)
                self.dir_drag_current = (wx, wy)
                return True
            if event.button == 3:
                if self.circuit_direction:
                    self._push_undo()
                    self.circuit_direction = None
                    self._show_msg("Direction arrow deleted")
                return True
            return True

        # ── Checkpoint mode ──
        if self.checkpoint_mode:
            if event.button == 1:
                wx, wy = self.screen_to_world(sx, sy)
                # Snap to grid
                wx = int(wx // TILE_SIZE) * TILE_SIZE
                wy = int(wy // TILE_SIZE) * TILE_SIZE
                self.cp_drag_start = (wx, wy)
                self.cp_drag_current = (wx, wy)
                return True
            if event.button == 3:
                wx, wy = self.screen_to_world(sx, sy)
                # Find and delete zone under cursor
                for i, z in enumerate(self.checkpoint_zones):
                    r = pygame.Rect(z[0], z[1], z[2], z[3])
                    if r.collidepoint(wx, wy):
                        self._push_undo()
                        self.checkpoint_zones.pop(i)
                        self._show_msg(f"Deleted checkpoint {i}")
                        break
                return True
            return True

        if event.button == 1:
            row, col = self.screen_to_tile(sx, sy)
            if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
                self._push_undo()
                self.painting = True
                self._paint_at(row, col)
            return True

        if event.button == 3:
            row, col = self.screen_to_tile(sx, sy)
            if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
                self._push_undo()
                self.erasing = True
                self._erase_at(row, col)
            return True

        return True

    def _handle_mouseup(self, event):
        if event.button == 2 or (event.button == 1 and self.panning):
            self.panning = False

        # Direction drag finalize
        if self.direction_mode and event.button == 1 and self.dir_drag_start:
            sx, sy = event.pos
            wx, wy = self.screen_to_world(sx, sy)
            x1, y1 = self.dir_drag_start
            dist = ((wx - x1) ** 2 + (wy - y1) ** 2) ** 0.5
            if dist >= TILE_SIZE:
                self._push_undo()
                self.circuit_direction = [x1, y1, wx, wy]
                self._show_msg("Direction arrow set")
            else:
                self._show_msg("Drag longer (min 1 tile)")
            self.dir_drag_start = None
            self.dir_drag_current = None
            return True

        # Checkpoint drag finalize
        if self.checkpoint_mode and event.button == 1 and self.cp_drag_start:
            sx, sy = event.pos
            wx, wy = self.screen_to_world(sx, sy)
            # Snap end to grid
            wx = int(wx // TILE_SIZE) * TILE_SIZE + TILE_SIZE
            wy = int(wy // TILE_SIZE) * TILE_SIZE + TILE_SIZE
            x0, y0 = self.cp_drag_start
            # Normalize (ensure positive w/h)
            x1 = min(x0, wx)
            y1 = min(y0, wy)
            x2 = max(x0, wx)
            y2 = max(y0, wy)
            # Minimum 1 tile size
            if x2 - x1 < TILE_SIZE:
                x2 = x1 + TILE_SIZE
            if y2 - y1 < TILE_SIZE:
                y2 = y1 + TILE_SIZE
            self._push_undo()
            self.checkpoint_zones.append([int(x1), int(y1),
                                          int(x2 - x1), int(y2 - y1)])
            self.cp_drag_start = None
            self.cp_drag_current = None
            self._show_msg(f"Checkpoint {len(self.checkpoint_zones) - 1} placed")
            return True

        if event.button == 1:
            self.painting = False
            # Also notify browser of mouse up for selection
            self.browser_panel.handle_event(event)
        if event.button in (2, 3):
            self.browser_panel.handle_event(event)
        if event.button == 3:
            self.erasing = False
        return True

    def _handle_mousemotion(self, event):
        sx, sy = event.pos

        # Direction drag update
        if self.direction_mode and self.dir_drag_start is not None:
            wx, wy = self.screen_to_world(sx, sy)
            self.dir_drag_current = (wx, wy)
            return True

        # Checkpoint drag update
        if self.checkpoint_mode and self.cp_drag_start is not None:
            wx, wy = self.screen_to_world(sx, sy)
            wx = int(wx // TILE_SIZE) * TILE_SIZE + TILE_SIZE
            wy = int(wy // TILE_SIZE) * TILE_SIZE + TILE_SIZE
            self.cp_drag_current = (wx, wy)
            return True

        # Browser panning / selection drag
        if self.browser_panel.panning or self.browser_panel.selecting:
            return self.browser_panel.handle_event(event)

        # Viewport panning
        if self.panning:
            dx = sx - self.pan_start[0]
            dy = sy - self.pan_start[1]
            self.cam_x = self.pan_cam_start[0] - dx / self.zoom
            self.cam_y = self.pan_cam_start[1] - dy / self.zoom
            return True

        # Painting
        if self.painting and self._is_in_viewport(sx, sy):
            row, col = self.screen_to_tile(sx, sy)
            if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
                self._paint_at(row, col)
            return True

        # Erasing
        if self.erasing and self._is_in_viewport(sx, sy):
            row, col = self.screen_to_tile(sx, sy)
            if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
                self._erase_at(row, col)
            return True

        return True

    def _handle_mousewheel(self, event):
        mx, my = pygame.mouse.get_pos()

        # Browser zoom
        if self.browser_panel.contains(mx, my):
            return self.browser_panel.handle_event(event)

        # Viewport zoom
        if not self._is_in_viewport(mx, my):
            return True
        wx, wy = self.screen_to_world(mx, my)
        if event.y > 0:
            self.zoom = min(ZOOM_MAX, self.zoom + ZOOM_STEP)
        elif event.y < 0:
            self.zoom = max(ZOOM_MIN, self.zoom - ZOOM_STEP)
        self.cam_x = wx - (mx - SCREEN_WIDTH / 2) / self.zoom
        self.cam_y = wy - (my - VIEWPORT_HEIGHT / 2) / self.zoom
        return True

    # ──────────────────────────────────────────
    # UPDATE
    # ──────────────────────────────────────────

    def update(self, dt):
        if self.status_timer > 0:
            self.status_timer -= dt
            if self.status_timer <= 0:
                self.status_msg = ""

    # ──────────────────────────────────────────
    # RENDER
    # ──────────────────────────────────────────

    def render(self):
        self.screen.fill(COLOR_BLACK)
        self._draw_viewport()
        self._draw_bottom_panel()
        self._draw_status_bar()

        if self.show_help:
            self._draw_help()
        if self.status_msg:
            self._draw_status_message()
        if self.dialog_mode == "save":
            self._draw_save_dialog()
        elif self.dialog_mode == "load":
            self._draw_load_dialog()

        # Collision editor overlay
        if self._collision_editor is not None:
            self._collision_editor.draw(self.screen)

    # ──────────────────────────────────────────
    # VIEWPORT
    # ──────────────────────────────────────────

    def _draw_viewport(self):
        viewport_rect = pygame.Rect(0, 0, SCREEN_WIDTH, VIEWPORT_HEIGHT)
        self.screen.set_clip(viewport_rect)
        self.screen.fill(GRASS_DARK, viewport_rect)

        # Visible tile range
        w0x, w0y = self.screen_to_world(0, 0)
        w1x, w1y = self.screen_to_world(SCREEN_WIDTH, VIEWPORT_HEIGHT)
        start_col = max(0, int(w0x // TILE_SIZE))
        start_row = max(0, int(w0y // TILE_SIZE))
        end_col = min(GRID_COLS, int(w1x // TILE_SIZE) + 2)
        end_row = min(GRID_ROWS, int(w1y // TILE_SIZE) + 2)

        tile_screen_size = max(1, int(TILE_SIZE * self.zoom))

        # Cache scaled sprites
        scaled_cache = {}

        def get_scaled(sprite, key):
            if key in scaled_cache:
                return scaled_cache[key]
            if tile_screen_size != TILE_SIZE:
                s = pygame.transform.scale(
                    sprite, (tile_screen_size + 1, tile_screen_size + 1))
            else:
                s = sprite
            scaled_cache[key] = s
            return s

        scaled_grass = get_scaled(self._grass_sprite, "grass")

        # Draw tiles
        for row in range(start_row, end_row):
            for col in range(start_col, end_col):
                tid = self.terrain[row][col]
                sx, sy = self.world_to_screen(col * TILE_SIZE, row * TILE_SIZE)
                isx, isy = int(sx), int(sy)

                if tid == T_EMPTY:
                    self.screen.blit(scaled_grass, (isx, isy))
                else:
                    rot = self.rotations[row][col]
                    sprite = get_tile_sprite(tid, rot)
                    if sprite is not None:
                        self.screen.blit(
                            get_scaled(sprite, (tid, rot)), (isx, isy))
                    else:
                        self.screen.blit(scaled_grass, (isx, isy))

        # Grid lines
        if self.zoom > 0.2:
            self._draw_grid_lines(start_row, start_col, end_row, end_col)

        # World boundary
        bx0, by0 = self.world_to_screen(0, 0)
        bx1, by1 = self.world_to_screen(GRID_COLS * TILE_SIZE, GRID_ROWS * TILE_SIZE)
        pygame.draw.rect(self.screen, (200, 200, 200),
                         pygame.Rect(int(bx0), int(by0),
                                     int(bx1 - bx0), int(by1 - by0)), 2)

        # Checkpoint zones overlay
        self._draw_checkpoint_zones()

        # Circuit direction arrow
        self._draw_circuit_direction()

        # Hover preview (show brush outline with rotated sprite preview)
        mx, my = pygame.mouse.get_pos()
        if self._is_in_viewport(mx, my) and not self.panning:
            row, col = self.screen_to_tile(mx, my)
            if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
                bw = self.current_brush.width
                bh = self.current_brush.height
                for dr in range(bh):
                    for dc in range(bw):
                        r = row + dr
                        c = col + dc
                        if 0 <= r < GRID_ROWS and 0 <= c < GRID_COLS:
                            bsx, bsy = self.world_to_screen(
                                c * TILE_SIZE, r * TILE_SIZE)
                            ibsx, ibsy = int(bsx), int(bsy)
                            # Show rotated tile preview
                            tid = self.current_brush.tiles[dr][dc]
                            if tid != T_EMPTY and self.selected_tile != T_EMPTY:
                                brot = (self.current_brush.rotations[dr][dc]
                                        + self.current_rotation) % 4
                                preview_spr = get_tile_sprite(tid, brot)
                                if preview_spr is not None:
                                    ps = get_scaled(
                                        preview_spr, (tid, brot, "preview"))
                                    ps.set_alpha(120)
                                    self.screen.blit(ps, (ibsx, ibsy))
                                    ps.set_alpha(255)
                            else:
                                hover = pygame.Surface(
                                    (tile_screen_size, tile_screen_size),
                                    pygame.SRCALPHA)
                                hover.fill((255, 255, 100, 50))
                                self.screen.blit(hover, (ibsx, ibsy))
                            pygame.draw.rect(self.screen, (255, 255, 100),
                                             (ibsx, ibsy,
                                              tile_screen_size,
                                              tile_screen_size), 1)

        self.screen.set_clip(None)

    def _draw_grid_lines(self, start_row, start_col, end_row, end_col):
        alpha = min(50, int(self.zoom * 60))
        if alpha < 8:
            return
        color = (255, 255, 255, alpha)
        grid_surf = pygame.Surface(
            (SCREEN_WIDTH, VIEWPORT_HEIGHT), pygame.SRCALPHA)

        for col in range(start_col, end_col + 1):
            sx, _ = self.world_to_screen(col * TILE_SIZE, 0)
            isx = int(sx)
            if 0 <= isx < SCREEN_WIDTH:
                pygame.draw.line(grid_surf, color,
                                 (isx, 0), (isx, VIEWPORT_HEIGHT))

        for row in range(start_row, end_row + 1):
            _, sy = self.world_to_screen(0, row * TILE_SIZE)
            isy = int(sy)
            if 0 <= isy < VIEWPORT_HEIGHT:
                pygame.draw.line(grid_surf, color,
                                 (0, isy), (SCREEN_WIDTH, isy))

        self.screen.blit(grid_surf, (0, 0))

    def _draw_checkpoint_zones(self):
        """Draw checkpoint zone rectangles and drag preview in the viewport."""
        # Existing zones
        for i, z in enumerate(self.checkpoint_zones):
            x, y, w, h = z
            sx0, sy0 = self.world_to_screen(x, y)
            sx1, sy1 = self.world_to_screen(x + w, y + h)
            sw = int(sx1 - sx0)
            sh = int(sy1 - sy0)
            if sw < 2 or sh < 2:
                continue
            # Semi-transparent violet fill
            fill_surf = pygame.Surface((sw, sh), pygame.SRCALPHA)
            fill_surf.fill((180, 60, 220, 50))
            self.screen.blit(fill_surf, (int(sx0), int(sy0)))
            # Border
            pygame.draw.rect(self.screen, (180, 60, 220),
                             (int(sx0), int(sy0), sw, sh), 2)
            # Number label with background
            label = self.font_small.render(str(i), True, COLOR_WHITE)
            lw, lh = label.get_size()
            lcx = int(sx0 + sw / 2 - lw / 2)
            lcy = int(sy0 + sh / 2 - lh / 2)
            bg = pygame.Surface((lw + 6, lh + 4), pygame.SRCALPHA)
            bg.fill((0, 0, 0, 160))
            self.screen.blit(bg, (lcx - 3, lcy - 2))
            self.screen.blit(label, (lcx, lcy))

        # Drag preview
        if self.cp_drag_start and self.cp_drag_current:
            x0, y0 = self.cp_drag_start
            x1, y1 = self.cp_drag_current
            sx0, sy0 = self.world_to_screen(min(x0, x1), min(y0, y1))
            sx1, sy1 = self.world_to_screen(max(x0, x1), max(y0, y1))
            sw = max(2, int(sx1 - sx0))
            sh = max(2, int(sy1 - sy0))
            preview = pygame.Surface((sw, sh), pygame.SRCALPHA)
            preview.fill((220, 180, 50, 40))
            self.screen.blit(preview, (int(sx0), int(sy0)))
            pygame.draw.rect(self.screen, (220, 180, 50),
                             (int(sx0), int(sy0), sw, sh), 2)

    def _draw_circuit_direction(self):
        """Draw the circuit direction arrow (saved or drag preview)."""
        import math

        def _draw_arrow(x1, y1, x2, y2, color, thickness=3):
            """Draw an arrow from (x1,y1) to (x2,y2) in screen coords."""
            pygame.draw.line(self.screen, color,
                             (int(x1), int(y1)), (int(x2), int(y2)), thickness)
            # Arrowhead
            dx = x2 - x1
            dy = y2 - y1
            length = math.hypot(dx, dy)
            if length < 1:
                return
            ux, uy = dx / length, dy / length
            # Perpendicular
            px, py = -uy, ux
            head_len = min(20, length * 0.3)
            head_w = head_len * 0.5
            tip_x, tip_y = x2, y2
            base_x = x2 - ux * head_len
            base_y = y2 - uy * head_len
            points = [
                (int(tip_x), int(tip_y)),
                (int(base_x + px * head_w), int(base_y + py * head_w)),
                (int(base_x - px * head_w), int(base_y - py * head_w)),
            ]
            pygame.draw.polygon(self.screen, color, points)

        # Saved direction arrow (green)
        if self.circuit_direction:
            wx1, wy1, wx2, wy2 = self.circuit_direction
            sx1, sy1 = self.world_to_screen(wx1, wy1)
            sx2, sy2 = self.world_to_screen(wx2, wy2)
            _draw_arrow(sx1, sy1, sx2, sy2, (50, 220, 80), 3)
            # "START" label at base
            label = self.font_small.render("START", True, (50, 220, 80))
            self.screen.blit(label, (int(sx1) - label.get_width() // 2,
                                     int(sy1) - 16))

        # Drag preview arrow (yellow)
        if self.dir_drag_start and self.dir_drag_current:
            wx1, wy1 = self.dir_drag_start
            wx2, wy2 = self.dir_drag_current
            sx1, sy1 = self.world_to_screen(wx1, wy1)
            sx2, sy2 = self.world_to_screen(wx2, wy2)
            _draw_arrow(sx1, sy1, sx2, sy2, (220, 200, 50), 2)

    # ──────────────────────────────────────────
    # BOTTOM PANEL
    # ──────────────────────────────────────────

    def _draw_bottom_panel(self):
        panel_y = VIEWPORT_HEIGHT

        # Background
        pygame.draw.rect(self.screen, COL_PANEL_BG,
                         (0, panel_y, SCREEN_WIDTH, BOTTOM_PANEL_H))
        pygame.draw.line(self.screen, COL_PANEL_BORDER,
                         (0, panel_y), (SCREEN_WIDTH, panel_y), 2)

        # Draw panels
        self.tools_panel.draw(self.screen,
                              selected_tile=self.selected_tile,
                              current_brush=self.current_brush,
                              current_rotation=self.current_rotation)

        # Separator
        pygame.draw.line(self.screen, COL_PANEL_BORDER,
                         (TOOLS_W, panel_y), (TOOLS_W, panel_y + BOTTOM_PANEL_H), 1)

        # Browser
        self.browser_panel.draw(self.screen)

        # Separator before inspector
        insp_x = SCREEN_WIDTH - INSPECTOR_W
        pygame.draw.line(self.screen, COL_PANEL_BORDER,
                         (insp_x, panel_y), (insp_x, panel_y + BOTTOM_PANEL_H), 1)

        # Inspector
        self.inspector_panel.draw(self.screen)

    # ──────────────────────────────────────────
    # STATUS BAR
    # ──────────────────────────────────────────

    def _draw_status_bar(self):
        bar_y = SCREEN_HEIGHT - STATUS_BAR_H
        bar_surf = pygame.Surface((SCREEN_WIDTH, STATUS_BAR_H), pygame.SRCALPHA)
        bar_surf.fill(COL_BAR)
        self.screen.blit(bar_surf, (0, bar_y))

        mx, my = pygame.mouse.get_pos()
        parts = [f"Zoom:{int(self.zoom * 100)}%"]

        if self._is_in_viewport(mx, my):
            row, col = self.screen_to_tile(mx, my)
            parts.append(f"Tile:({col},{row})")

        bw = self.current_brush.width
        bh = self.current_brush.height
        parts.append(f"Brush:{bw}x{bh}")
        parts.append(f"Rot:{self.current_rotation * 90}\u00b0")

        # Show friction of tile under cursor
        if self._is_in_viewport(mx, my):
            row, col = self.screen_to_tile(mx, my)
            if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
                tid = self.terrain[row][col]
                if tid != T_EMPTY:
                    mgr = get_manager()
                    fric = mgr.get_friction(tid)
                    parts.append(f"Friction:{fric:.1f}")

        if self.direction_mode:
            parts.append("DIRECTION MODE")
        elif self.circuit_direction:
            parts.append("Dir:set")

        if self.checkpoint_mode:
            parts.append(f"CHECKPOINT MODE ({len(self.checkpoint_zones)} zones)")
        elif self.checkpoint_zones:
            parts.append(f"CPs:{len(self.checkpoint_zones)}")

        if self.current_name:
            parts.append(f"Track:{self.current_name}")

        text = "  |  ".join(parts)
        self.screen.blit(self.font.render(text, True, COLOR_GRAY), (8, bar_y + 6))

    # ──────────────────────────────────────────
    # HELP / MESSAGES / DIALOGS
    # ──────────────────────────────────────────

    def _draw_help(self):
        lines = [
            "=== TILE EDITOR ===",
            "",
            "Left-click         Paint brush",
            "Left-drag          Paint continuously",
            "Right-click        Erase",
            "",
            "Middle-drag        Pan viewport",
            "Space+drag         Pan viewport",
            "Scroll             Zoom in/out",
            "",
            "Tileset: click     Select 1 tile",
            "Tileset: drag      Select rectangle",
            "Tileset: scroll    Zoom tileset",
            "Tileset: R-drag    Pan tileset",
            "Tabs               Filter by category",
            "",
            "R / Shift+R        Rotate tile CW/CCW",
            "Shift+1/2/3        Brush size",
            "Ctrl+Z / Ctrl+Y   Undo / Redo",
            "Ctrl+S             Save track",
            "Ctrl+O             Load track",
            "Ctrl+N             New track",
            "F                  Fit view",
            "T                  Test track",
            "C                  Checkpoint mode",
            "  drag=place, R-click=delete",
            "D                  Direction mode",
            "  drag=set arrow, R-click=delete",
            "H                  Toggle help",
            "ESC                Back to menu",
            "",
            "Property Inspector (right panel):",
            "  Click fields to cycle values",
        ]

        line_h = 19
        pad = 10
        max_w = 340
        panel_h = len(lines) * line_h + pad * 2

        panel = pygame.Surface((max_w, panel_h), pygame.SRCALPHA)
        panel.fill((15, 15, 25, 220))
        pygame.draw.rect(panel, (60, 80, 140), (0, 0, max_w, panel_h), 1)

        for i, line in enumerate(lines):
            col = COLOR_YELLOW if line.startswith("===") else (180, 190, 200)
            panel.blit(self.font.render(line, True, col), (pad, pad + i * line_h))

        x = max(10, SCREEN_WIDTH - max_w - 10)
        self.screen.blit(panel, (x, 10))

    def _draw_status_message(self):
        rendered = self.font_big.render(self.status_msg, True, COL_MSG)
        rect = rendered.get_rect(centerx=SCREEN_WIDTH // 2, top=10)
        bg = pygame.Surface((rect.width + 20, rect.height + 10), pygame.SRCALPHA)
        bg.fill((10, 10, 10, 180))
        self.screen.blit(bg, (rect.x - 10, rect.y - 5))
        self.screen.blit(rendered, rect)

    def _draw_save_dialog(self):
        dw, dh = 400, 160
        dx = (SCREEN_WIDTH - dw) // 2
        dy = (VIEWPORT_HEIGHT - dh) // 2

        surf = pygame.Surface((dw, dh), pygame.SRCALPHA)
        surf.fill(COL_DIALOG_BG)
        pygame.draw.rect(surf, COL_DIALOG_BORDER, (0, 0, dw, dh), 2)
        self.screen.blit(surf, (dx, dy))

        self.screen.blit(self.font_big.render("Save Track", True, COLOR_WHITE),
                         (dx + 20, dy + 15))
        self.screen.blit(self.font.render("Track name:", True, COLOR_GRAY),
                         (dx + 20, dy + 55))

        input_rect = pygame.Rect(dx + 20, dy + 78, dw - 40, 30)
        pygame.draw.rect(self.screen, COL_INPUT_BG, input_rect)
        pygame.draw.rect(self.screen, COL_DIALOG_BORDER, input_rect, 1)
        self.screen.blit(
            self.font.render(self.dialog_input + "|", True, COLOR_WHITE),
            (input_rect.x + 6, input_rect.y + 7))

        self.screen.blit(
            self.font.render("ENTER to save  |  ESC to cancel", True, COLOR_GRAY),
            (dx + 20, dy + 125))

    def _draw_load_dialog(self):
        dw, dh = 500, 400
        dx = (SCREEN_WIDTH - dw) // 2
        dy = (VIEWPORT_HEIGHT - dh) // 2

        surf = pygame.Surface((dw, dh), pygame.SRCALPHA)
        surf.fill(COL_DIALOG_BG)
        pygame.draw.rect(surf, COL_DIALOG_BORDER, (0, 0, dw, dh), 2)
        self.screen.blit(surf, (dx, dy))

        self.screen.blit(self.font_big.render("Load Track", True, COLOR_WHITE),
                         (dx + 20, dy + 15))

        if not self.dialog_tracks:
            self.screen.blit(self.font.render("No tracks found", True, COLOR_GRAY),
                             (dx + 20, dy + 60))
        else:
            visible = 12
            start = max(0, self.dialog_selected - visible + 1)
            end = min(len(self.dialog_tracks), start + visible)

            for i_draw, i in enumerate(range(start, end)):
                entry = self.dialog_tracks[i]
                yy = dy + 50 + i_draw * 26

                if i == self.dialog_selected:
                    pygame.draw.rect(self.screen, (40, 50, 80),
                                     pygame.Rect(dx + 10, yy, dw - 20, 24))

                track_type = entry.get("type", "classic")
                type_color = COLOR_GREEN if track_type == "tiles" else (180, 140, 60)

                color = COLOR_WHITE if i == self.dialog_selected else COLOR_GRAY
                name_surf = self.font.render(entry["name"], True, color)
                type_surf = self.font_small.render(f"[{track_type}]", True, type_color)
                self.screen.blit(name_surf, (dx + 20, yy + 3))
                self.screen.blit(type_surf,
                                 (dx + 20 + name_surf.get_width() + 8, yy + 5))

        self.screen.blit(
            self.font.render("UP/DOWN select | ENTER load | ESC cancel",
                             True, COLOR_GRAY),
            (dx + 20, dy + dh - 30))
