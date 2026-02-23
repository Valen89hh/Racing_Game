"""
editor.py - Editor visual de circuitos basado en tiles.

Permite crear y modificar circuitos pintando tiles sobre una cuadricula.
Panel inferior muestra el tileset completo en su layout original,
con zoom, scroll y arrastre para navegacion.
"""

import pygame

from settings import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    COLOR_WHITE, COLOR_BLACK, COLOR_YELLOW, COLOR_GREEN,
    COLOR_GRAY, COLOR_RED,
)
from tile_defs import (
    TILE_SIZE, GRID_COLS, GRID_ROWS, TILE_BASE_PX,
    T_EMPTY, T_FINISH, TILE_BASE,
    CAT_ROAD, CATEGORY_NAMES,
    is_driveable, get_tile_sprite,
    get_tile_category,
    make_grass_sprite, make_finish_sprite,
    get_tileset_sheet, get_tileset_dimensions,
    get_tile_at_position, get_tile_info,
    GRASS_COLOR, GRASS_DARK,
    empty_terrain,
)
import track_manager


# ── Layout ──
BOTTOM_PANEL_H = 200
STATUS_BAR_H = 28
VIEWPORT_HEIGHT = SCREEN_HEIGHT - BOTTOM_PANEL_H - STATUS_BAR_H  # 492
TOOLS_W = 130
BROWSER_X = TOOLS_W
BROWSER_Y = VIEWPORT_HEIGHT
BROWSER_W = SCREEN_WIDTH - TOOLS_W
BROWSER_H = BOTTOM_PANEL_H

# ── Viewport ──
ZOOM_MIN = 0.1
ZOOM_MAX = 2.0
ZOOM_STEP = 0.08
MAX_UNDO = 30
TILE_PREVIEW_SIZE = 48

# ── Tileset browser ──
BROWSER_ZOOM_MIN = 3
BROWSER_ZOOM_MAX = 48

# ── UI colors ──
COL_PANEL_BG = (25, 25, 35)
COL_PANEL_BORDER = (60, 70, 90)
COL_TILE_SELECTED = (255, 220, 50)
COL_TILE_HOVER = (150, 200, 255)
COL_BAR = (20, 20, 20, 200)
COL_MSG = (100, 255, 150)
COL_DIALOG_BG = (25, 25, 35, 230)
COL_DIALOG_BORDER = (80, 120, 200)
COL_INPUT_BG = (40, 40, 55)
COL_TOOL_BG = (35, 40, 50)
COL_DRIVEABLE = (50, 200, 50)


class TileEditor:
    """Editor visual de circuitos basado en tiles."""

    def __init__(self, screen):
        self.screen = screen
        self.font = pygame.font.SysFont("consolas", 16)
        self.font_big = pygame.font.SysFont("consolas", 22, bold=True)
        self.font_small = pygame.font.SysFont("consolas", 12)

        # Tile data (single grid)
        self.terrain = empty_terrain()

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

        # Selection
        self.selected_tile = T_EMPTY
        self.brush_size = 1

        # Undo/Redo
        self.undo_stack = []
        self.redo_stack = []

        # Tileset browser state
        self.browser_zoom = BROWSER_ZOOM_MIN
        self.browser_scroll_x = 0.0
        self.browser_scroll_y = 0.0
        self.browser_hover = None  # (src_row, src_col, tile_id) or None

        # Browser panning
        self.browser_panning = False
        self.browser_pan_start = (0, 0)
        self.browser_scroll_start = (0.0, 0.0)

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

        # Build preview sprites
        self._grass_sprite = make_grass_sprite()
        self._grass_preview = pygame.transform.scale(
            self._grass_sprite, (TILE_PREVIEW_SIZE, TILE_PREVIEW_SIZE))
        finish = make_finish_sprite()
        self._finish_preview = pygame.transform.scale(
            finish, (TILE_PREVIEW_SIZE, TILE_PREVIEW_SIZE))

        self._fit_view()

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

    def _is_in_browser(self, sx, sy):
        return (sx >= BROWSER_X and sy >= BROWSER_Y and
                sy < BROWSER_Y + BROWSER_H)

    def _is_in_tools(self, sx, sy):
        return (sx < TOOLS_W and sy >= VIEWPORT_HEIGHT and
                sy < VIEWPORT_HEIGHT + BOTTOM_PANEL_H)

    def _is_in_panel(self, sx, sy):
        return sy >= VIEWPORT_HEIGHT and sy < SCREEN_HEIGHT - STATUS_BAR_H

    # ──────────────────────────────────────────
    # UNDO / REDO
    # ──────────────────────────────────────────

    def _push_undo(self):
        snap = [row[:] for row in self.terrain]
        self.undo_stack.append(snap)
        if len(self.undo_stack) > MAX_UNDO:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append([row[:] for row in self.terrain])
        self.terrain = self.undo_stack.pop()

    def _redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append([row[:] for row in self.terrain])
        self.terrain = self.redo_stack.pop()

    # ──────────────────────────────────────────
    # PAINTING
    # ──────────────────────────────────────────

    def _paint_at(self, row, col):
        half = self.brush_size // 2
        for dr in range(self.brush_size):
            for dc in range(self.brush_size):
                r = row + dr - half
                c = col + dc - half
                if 0 <= r < GRID_ROWS and 0 <= c < GRID_COLS:
                    self.terrain[r][c] = self.selected_tile

    def _erase_at(self, row, col):
        half = self.brush_size // 2
        for dr in range(self.brush_size):
            for dc in range(self.brush_size):
                r = row + dr - half
                c = col + dc - half
                if 0 <= r < GRID_ROWS and 0 <= c < GRID_COLS:
                    self.terrain[r][c] = T_EMPTY

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
        return {
            "name": self.current_name or "Untitled",
            "format": "tiles",
            "version": 3,
            "tile_size": TILE_SIZE,
            "grid_width": GRID_COLS,
            "grid_height": GRID_ROWS,
            "terrain": [row[:] for row in self.terrain],
        }

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
            track_manager.save_tile_track(filename, name, self.terrain)
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
                    self.terrain)
                self._show_msg(f"Saved: {self.current_filename}.json")
            except OSError as e:
                self._show_msg(f"Error: {e}")
        else:
            self._open_save_dialog()

    # ──────────────────────────────────────────
    # EVENT HANDLING
    # ──────────────────────────────────────────

    def handle_event(self, event):
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
        # Handle text input (pygame 2.x sends TEXTINPUT for typed characters)
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
            self.current_filename = None
            self.current_name = None
            self._show_msg("New track")
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

        # Brush size with Shift+1/2/3
        if shift:
            if event.key == pygame.K_1:
                self.brush_size = 1
                self._show_msg("Brush: 1x1")
                return True
            if event.key == pygame.K_2:
                self.brush_size = 2
                self._show_msg("Brush: 2x2")
                return True
            if event.key == pygame.K_3:
                self.brush_size = 3
                self._show_msg("Brush: 3x3")
                return True

        return True

    def _handle_mousedown(self, event):
        sx, sy = event.pos

        # ── Browser area ──
        if self._is_in_browser(sx, sy):
            if event.button == 1:
                self._handle_browser_click(sx, sy)
            elif event.button in (2, 3):
                self.browser_panning = True
                self.browser_pan_start = (sx, sy)
                self.browser_scroll_start = (
                    self.browser_scroll_x, self.browser_scroll_y)
            return True

        # ── Tools area ──
        if self._is_in_tools(sx, sy):
            if event.button == 1:
                self._handle_tools_click(sx, sy)
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
        if event.button in (2, 3):
            self.browser_panning = False
        if event.button == 1:
            self.painting = False
        if event.button == 3:
            self.erasing = False
        return True

    def _handle_mousemotion(self, event):
        sx, sy = event.pos

        # Browser panning
        if self.browser_panning:
            dx = sx - self.browser_pan_start[0]
            dy = sy - self.browser_pan_start[1]
            self.browser_scroll_x = self.browser_scroll_start[0] - dx
            self.browser_scroll_y = self.browser_scroll_start[1] - dy
            return True

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
        if self._is_in_browser(mx, my):
            self._browser_zoom_at(event.y, mx, my)
            return True

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

    def _browser_zoom_at(self, direction, mx, my):
        """Zoom the tileset browser, keeping tile under cursor stable."""
        px = mx - BROWSER_X
        py = my - BROWSER_Y
        z = self.browser_zoom

        # Tile coords under cursor before zoom
        tx = (px + self.browser_scroll_x) / z
        ty = (py + self.browser_scroll_y) / z

        if direction > 0:
            new_z = min(BROWSER_ZOOM_MAX, z + max(1, z // 3))
        else:
            new_z = max(BROWSER_ZOOM_MIN, z - max(1, z // 3))

        self.browser_zoom = new_z
        # Keep same tile under cursor after zoom
        self.browser_scroll_x = tx * new_z - px
        self.browser_scroll_y = ty * new_z - py

    # ──────────────────────────────────────────
    # PANEL CLICK HANDLING
    # ──────────────────────────────────────────

    def _handle_tools_click(self, sx, sy):
        """Handle clicks in the tools section (left of bottom panel)."""
        px = sx
        py = sy - VIEWPORT_HEIGHT

        # Grass button: (8, 8) to (56, 56)
        if 8 <= px < 8 + TILE_PREVIEW_SIZE and 8 <= py < 8 + TILE_PREVIEW_SIZE:
            self.selected_tile = T_EMPTY
            return

        # Finish button: (64, 8) to (112, 56)
        fx = 8 + TILE_PREVIEW_SIZE + 8
        if fx <= px < fx + TILE_PREVIEW_SIZE and 8 <= py < 8 + TILE_PREVIEW_SIZE:
            self.selected_tile = T_FINISH
            return

    def _handle_browser_click(self, sx, sy):
        """Handle clicks in the tileset browser (select tile)."""
        px = sx - BROWSER_X
        py = sy - BROWSER_Y
        z = self.browser_zoom
        ts_col = int((px + self.browser_scroll_x) / z)
        ts_row = int((py + self.browser_scroll_y) / z)
        tile_id = get_tile_at_position(ts_row, ts_col)
        if tile_id is not None:
            self.selected_tile = tile_id

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

        # Cache scaled sprites for this frame
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
                    sprite = get_tile_sprite(tid)
                    if sprite is not None:
                        self.screen.blit(get_scaled(sprite, tid), (isx, isy))
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

        # Hover preview
        mx, my = pygame.mouse.get_pos()
        if self._is_in_viewport(mx, my) and not self.panning:
            row, col = self.screen_to_tile(mx, my)
            if 0 <= row < GRID_ROWS and 0 <= col < GRID_COLS:
                half = self.brush_size // 2
                for dr in range(self.brush_size):
                    for dc in range(self.brush_size):
                        r = row + dr - half
                        c = col + dc - half
                        if 0 <= r < GRID_ROWS and 0 <= c < GRID_COLS:
                            bsx, bsy = self.world_to_screen(
                                c * TILE_SIZE, r * TILE_SIZE)
                            hover = pygame.Surface(
                                (tile_screen_size, tile_screen_size),
                                pygame.SRCALPHA)
                            hover.fill((255, 255, 100, 50))
                            self.screen.blit(hover, (int(bsx), int(bsy)))
                            pygame.draw.rect(self.screen, (255, 255, 100),
                                             (int(bsx), int(bsy),
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

        # ── Tools section (left) ──
        self._draw_tools_section(panel_y)

        # ── Separator line ──
        pygame.draw.line(self.screen, COL_PANEL_BORDER,
                         (TOOLS_W, panel_y), (TOOLS_W, panel_y + BOTTOM_PANEL_H), 1)

        # ── Tileset browser (right) ──
        clip_rect = pygame.Rect(BROWSER_X, BROWSER_Y, BROWSER_W, BROWSER_H)
        self.screen.set_clip(clip_rect)
        self._draw_tileset_browser()
        self.screen.set_clip(None)

    def _draw_tools_section(self, panel_y):
        """Draw tool buttons and selection info in the left section."""
        pygame.draw.rect(self.screen, COL_TOOL_BG,
                         (0, panel_y, TOOLS_W, BOTTOM_PANEL_H))

        # ── Row 1: Grass + Finish buttons ──
        gx, gy = 8, panel_y + 8
        self.screen.blit(self._grass_preview, (gx, gy))
        if self.selected_tile == T_EMPTY:
            pygame.draw.rect(self.screen, COL_TILE_SELECTED,
                             (gx - 2, gy - 2,
                              TILE_PREVIEW_SIZE + 4, TILE_PREVIEW_SIZE + 4), 3)

        fx = gx + TILE_PREVIEW_SIZE + 8
        fy = gy
        self.screen.blit(self._finish_preview, (fx, fy))
        if self.selected_tile == T_FINISH:
            pygame.draw.rect(self.screen, COL_TILE_SELECTED,
                             (fx - 2, fy - 2,
                              TILE_PREVIEW_SIZE + 4, TILE_PREVIEW_SIZE + 4), 3)

        # ── Separator ──
        sep_y = gy + TILE_PREVIEW_SIZE + 8
        pygame.draw.line(self.screen, COL_PANEL_BORDER,
                         (4, sep_y), (TOOLS_W - 4, sep_y))

        # ── Selected tile info ──
        info_y = sep_y + 6
        if self.selected_tile == T_EMPTY:
            info_text = "Grass (eraser)"
            drive_text = ""
        elif self.selected_tile == T_FINISH:
            info_text = "Finish Line"
            drive_text = "Driveable"
        else:
            cat = get_tile_category(self.selected_tile)
            cat_name = CATEGORY_NAMES.get(cat, "?") if cat else "?"
            info_text = f"{cat_name} #{self.selected_tile - TILE_BASE}"
            drive_text = "Driveable" if is_driveable(self.selected_tile) else "Solid"

        self.screen.blit(self.font_small.render(info_text, True, COLOR_WHITE),
                         (6, info_y))

        if drive_text:
            drive_color = COL_DRIVEABLE if drive_text == "Driveable" else (200, 80, 80)
            self.screen.blit(self.font_small.render(drive_text, True, drive_color),
                             (6, info_y + 15))

        self.screen.blit(self.font_small.render(
            f"Brush: {self.brush_size}x{self.brush_size}", True, COLOR_GRAY),
            (6, info_y + 30))

        # ── Hover tile info ──
        if self.browser_hover:
            _, _, htid = self.browser_hover
            hcat = get_tile_category(htid)
            hname = CATEGORY_NAMES.get(hcat, "?") if hcat else "?"
            hdrive = "drv" if is_driveable(htid) else "sld"
            self.screen.blit(self.font_small.render(
                f"[{hname}|{hdrive}]", True, (120, 140, 160)),
                (6, info_y + 50))

    def _draw_tileset_browser(self):
        """Draw the tileset in its original layout, zoomable and scrollable."""
        sheet = get_tileset_sheet()
        if sheet is None:
            self.screen.blit(
                self.font.render("No tileset", True, (180, 180, 180)),
                (BROWSER_X + 10, BROWSER_Y + 10))
            return

        ts_cols, ts_rows = get_tileset_dimensions()
        z = self.browser_zoom

        # Virtual size at current zoom
        virt_w = ts_cols * z
        virt_h = ts_rows * z

        # Clamp scroll
        max_sx = max(0, virt_w - BROWSER_W)
        max_sy = max(0, virt_h - BROWSER_H)
        self.browser_scroll_x = max(0, min(self.browser_scroll_x, max_sx))
        self.browser_scroll_y = max(0, min(self.browser_scroll_y, max_sy))

        sx = self.browser_scroll_x
        sy = self.browser_scroll_y

        # Visible tile range
        col0 = max(0, int(sx / z))
        row0 = max(0, int(sy / z))
        col1 = min(ts_cols, col0 + int(BROWSER_W / z) + 2)
        row1 = min(ts_rows, row0 + int(BROWSER_H / z) + 2)

        if col1 <= col0 or row1 <= row0:
            return

        # Extract visible portion from sheet and scale
        sheet_w, sheet_h = sheet.get_size()
        src_x = col0 * TILE_BASE_PX
        src_y = row0 * TILE_BASE_PX
        src_w = min((col1 - col0) * TILE_BASE_PX, sheet_w - src_x)
        src_h = min((row1 - row0) * TILE_BASE_PX, sheet_h - src_y)

        if src_w <= 0 or src_h <= 0:
            return

        sub = sheet.subsurface(pygame.Rect(src_x, src_y, src_w, src_h))
        dst_w = int(src_w * z / TILE_BASE_PX)
        dst_h = int(src_h * z / TILE_BASE_PX)

        if dst_w <= 0 or dst_h <= 0:
            return

        scaled = pygame.transform.scale(sub, (dst_w, dst_h))

        blit_x = BROWSER_X + int(col0 * z - sx)
        blit_y = BROWSER_Y + int(row0 * z - sy)

        self.screen.blit(scaled, (blit_x, blit_y))

        # Grid lines at higher zoom
        if z >= 12:
            self._draw_browser_grid(col0, row0, col1, row1, z, sx, sy)

        # Selection highlight
        self._draw_browser_selection(z, sx, sy)

        # Hover highlight
        self._draw_browser_hover(z, sx, sy)

    def _draw_browser_grid(self, col0, row0, col1, row1, z, sx, sy):
        """Draw grid lines between tiles in the browser at high zoom."""
        alpha = min(60, int(z * 3))
        grid_surf = pygame.Surface((BROWSER_W, BROWSER_H), pygame.SRCALPHA)
        color = (255, 255, 255, alpha)

        for col in range(col0, col1 + 1):
            x = int(col * z - sx)
            if 0 <= x < BROWSER_W:
                pygame.draw.line(grid_surf, color, (x, 0), (x, BROWSER_H))

        for row in range(row0, row1 + 1):
            y = int(row * z - sy)
            if 0 <= y < BROWSER_H:
                pygame.draw.line(grid_surf, color, (0, y), (BROWSER_W, y))

        self.screen.blit(grid_surf, (BROWSER_X, BROWSER_Y))

    def _draw_browser_selection(self, z, sx, sy):
        """Highlight the currently selected tile in the browser."""
        if self.selected_tile in (T_EMPTY, T_FINISH):
            return
        info = get_tile_info(self.selected_tile)
        if info is None:
            return
        sel_x = BROWSER_X + int(info['src_col'] * z - sx)
        sel_y = BROWSER_Y + int(info['src_row'] * z - sy)
        tile_sz = max(1, int(z))
        if (sel_x + tile_sz >= BROWSER_X and sel_x < BROWSER_X + BROWSER_W and
                sel_y + tile_sz >= BROWSER_Y and sel_y < BROWSER_Y + BROWSER_H):
            thickness = max(1, int(z / 8))
            pygame.draw.rect(self.screen, COL_TILE_SELECTED,
                             (sel_x, sel_y, tile_sz, tile_sz), thickness)

    def _draw_browser_hover(self, z, sx, sy):
        """Highlight the tile under the cursor in the browser."""
        mx, my = pygame.mouse.get_pos()
        px = mx - BROWSER_X
        py = my - BROWSER_Y

        self.browser_hover = None

        if not (0 <= px < BROWSER_W and 0 <= py < BROWSER_H):
            return
        if mx < BROWSER_X:
            return

        ts_col = int((px + sx) / z)
        ts_row = int((py + sy) / z)

        tile_id = get_tile_at_position(ts_row, ts_col)
        if tile_id is not None:
            self.browser_hover = (ts_row, ts_col, tile_id)
            hx = BROWSER_X + int(ts_col * z - sx)
            hy = BROWSER_Y + int(ts_row * z - sy)
            tile_sz = max(1, int(z))
            thickness = max(1, int(z / 12))
            pygame.draw.rect(self.screen, COL_TILE_HOVER,
                             (hx, hy, tile_sz, tile_sz), thickness)

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

        parts.append(f"Brush:{self.brush_size}x{self.brush_size}")

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
            "Left-click        Paint tile",
            "Left-drag          Paint continuously",
            "Right-click        Erase tile",
            "",
            "Middle-drag        Pan viewport",
            "Space+drag         Pan viewport",
            "Scroll             Zoom in/out",
            "",
            "Tileset: scroll    Zoom tileset",
            "Tileset: R-drag    Pan tileset",
            "Shift+1/2/3        Brush size",
            "",
            "Ctrl+Z / Ctrl+Y   Undo / Redo",
            "Ctrl+S             Save track",
            "Ctrl+O             Load track",
            "Ctrl+N             New track",
            "F                  Fit view",
            "T                  Test track",
            "H                  Toggle help",
            "ESC                Back to menu",
        ]

        line_h = 19
        pad = 10
        max_w = 320
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
