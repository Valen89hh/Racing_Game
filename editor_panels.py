"""
editor_panels.py - UI panels for the professional tile editor.

Panel (base), TilesetBrowser (with category tabs + rectangular selection),
ToolsPanel (brush management), PropertyInspector (per-tile metadata editing).
"""

from __future__ import annotations

import pygame

from tile_defs import (
    T_EMPTY, T_FINISH, TILE_BASE, TILE_BASE_PX,
    is_driveable, get_tile_sprite, get_tile_category,
    get_tileset_sheet, get_tileset_dimensions,
    get_tile_at_position, get_tile_info,
    make_grass_sprite, make_finish_sprite,
)
from tile_meta import (
    get_manager, TileMeta,
    ALL_CATEGORIES, CATEGORY_DISPLAY, FRICTION_PRESETS,
    COLLISION_TYPES, COLL_NONE, COLL_FULL, COLL_POLYGON,
    META_TERRAIN, META_PROPS, META_OBSTACLES, META_SPECIAL,
)
from tile_brush import Brush, BrushLibrary

# ──────────────────────────────────────────────
# COLOURS
# ──────────────────────────────────────────────
COL_PANEL_BG = (25, 25, 35)
COL_TOOL_BG = (35, 40, 50)
COL_PANEL_BORDER = (60, 70, 90)
COL_TILE_SELECTED = (255, 220, 50)
COL_TILE_HOVER = (150, 200, 255)
COL_DRIVEABLE = (50, 200, 50)
COL_TAB_ACTIVE = (60, 80, 130)
COL_TAB_INACTIVE = (35, 40, 55)
COL_TAB_HOVER = (50, 60, 90)
COL_BTN = (45, 55, 70)
COL_BTN_HOVER = (65, 80, 110)
COL_WHITE = (255, 255, 255)
COL_GRAY = (140, 140, 140)
COL_LIGHT_GRAY = (180, 190, 200)
COL_YELLOW = (255, 220, 50)

TILE_PREVIEW_SIZE = 48

# Browser zoom limits
BROWSER_ZOOM_MIN = 3
BROWSER_ZOOM_MAX = 48

# Tab definitions: label, filter category (None = all)
TABS = [
    ("All", None),
    ("Terrain", META_TERRAIN),
    ("Props", META_PROPS),
    ("Obstacles", META_OBSTACLES),
    ("Special", META_SPECIAL),
]

TAB_HEIGHT = 24


class Panel:
    """Base class for editor panels."""

    def __init__(self, rect: pygame.Rect):
        self.rect = rect

    def handle_event(self, event) -> bool:
        """Process an event.  Return True if consumed."""
        return False

    def update(self, dt: float):
        pass

    def draw(self, surface: pygame.Surface):
        pass

    def contains(self, x: int, y: int) -> bool:
        return self.rect.collidepoint(x, y)


# ══════════════════════════════════════════════
# TILESET BROWSER
# ══════════════════════════════════════════════

class TilesetBrowser(Panel):
    """Tileset browser with category tabs and rectangular multi-tile selection."""

    def __init__(self, rect: pygame.Rect):
        super().__init__(rect)
        self.font = pygame.font.SysFont("consolas", 12)

        # Zoom / scroll
        self.zoom = BROWSER_ZOOM_MIN
        self.scroll_x = 0.0
        self.scroll_y = 0.0

        # Panning
        self.panning = False
        self.pan_start = (0, 0)
        self.scroll_start = (0.0, 0.0)

        # Tabs
        self.active_tab = 0  # index into TABS

        # Selection (tileset source coords)
        self.selecting = False
        self.sel_start = None   # (src_row, src_col) or None
        self.sel_end = None     # (src_row, src_col) or None

        # Hover
        self.hover_tile = None  # (src_row, src_col, tile_id) or None

        # Result: callback will be set by editor
        self.on_tile_selected = None    # fn(tile_id)
        self.on_brush_selected = None   # fn(Brush)

    # ── Content area (below tabs) ──

    @property
    def content_rect(self) -> pygame.Rect:
        return pygame.Rect(
            self.rect.x, self.rect.y + TAB_HEIGHT,
            self.rect.width, self.rect.height - TAB_HEIGHT,
        )

    def _in_content(self, x, y):
        return self.content_rect.collidepoint(x, y)

    def _in_tabs(self, x, y):
        return (self.rect.x <= x < self.rect.right and
                self.rect.y <= y < self.rect.y + TAB_HEIGHT)

    # ── Coordinate helpers ──

    def _screen_to_tileset(self, sx, sy):
        """Convert screen coords to tileset source (row, col)."""
        cr = self.content_rect
        px = sx - cr.x
        py = sy - cr.y
        z = self.zoom
        ts_col = int((px + self.scroll_x) / z)
        ts_row = int((py + self.scroll_y) / z)
        return ts_row, ts_col

    # ── Events ──

    def handle_event(self, event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN:
            sx, sy = event.pos
            if self._in_tabs(sx, sy):
                return self._handle_tab_click(sx, sy)
            if self._in_content(sx, sy):
                if event.button == 1:
                    return self._handle_content_click(sx, sy)
                if event.button in (2, 3):
                    self.panning = True
                    self.pan_start = (sx, sy)
                    self.scroll_start = (self.scroll_x, self.scroll_y)
                    return True

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button in (2, 3):
                self.panning = False
            if event.button == 1 and self.selecting:
                self._finish_selection(event.pos)
                return True

        elif event.type == pygame.MOUSEMOTION:
            sx, sy = event.pos
            if self.panning:
                dx = sx - self.pan_start[0]
                dy = sy - self.pan_start[1]
                self.scroll_x = self.scroll_start[0] - dx
                self.scroll_y = self.scroll_start[1] - dy
                return True
            if self.selecting and self._in_content(sx, sy):
                r, c = self._screen_to_tileset(sx, sy)
                self.sel_end = (r, c)
                return True

        elif event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if self._in_content(mx, my):
                self._zoom_at(event.y, mx, my)
                return True

        return False

    def _handle_tab_click(self, sx, sy):
        tab_w = self.rect.width // len(TABS)
        idx = (sx - self.rect.x) // tab_w
        if 0 <= idx < len(TABS):
            self.active_tab = idx
        return True

    def _handle_content_click(self, sx, sy):
        r, c = self._screen_to_tileset(sx, sy)
        tid = get_tile_at_position(r, c)

        # Check tab filter
        if tid is not None and not self._passes_filter(tid):
            tid = None

        if tid is not None:
            # Start potential rectangular selection
            self.selecting = True
            self.sel_start = (r, c)
            self.sel_end = (r, c)
        return True

    def _finish_selection(self, pos):
        self.selecting = False
        if self.sel_start is None or self.sel_end is None:
            return

        r0, c0 = self.sel_start
        r1, c1 = self.sel_end
        sr0, sr1 = sorted((r0, r1))
        sc0, sc1 = sorted((c0, c1))

        # Single tile?
        if sr0 == sr1 and sc0 == sc1:
            tid = get_tile_at_position(sr0, sc0)
            if tid is not None and self.on_tile_selected:
                self.on_tile_selected(tid)
        else:
            # Multi-tile: create brush
            brush = Brush.from_tileset_rect(sr0, sc0, sr1, sc1)
            if brush.width > 0 and brush.height > 0 and self.on_brush_selected:
                self.on_brush_selected(brush)

    def _passes_filter(self, tile_id):
        """Check if tile passes current tab filter."""
        _, cat_filter = TABS[self.active_tab]
        if cat_filter is None:
            return True
        mgr = get_manager()
        return mgr.get_category(tile_id) == cat_filter

    def _zoom_at(self, direction, mx, my):
        cr = self.content_rect
        px = mx - cr.x
        py = my - cr.y
        z = self.zoom
        tx = (px + self.scroll_x) / z
        ty = (py + self.scroll_y) / z
        if direction > 0:
            new_z = min(BROWSER_ZOOM_MAX, z + max(1, z // 3))
        else:
            new_z = max(BROWSER_ZOOM_MIN, z - max(1, z // 3))
        self.zoom = new_z
        self.scroll_x = tx * new_z - px
        self.scroll_y = ty * new_z - py

    # ── Drawing ──

    def draw(self, surface: pygame.Surface):
        # Background
        pygame.draw.rect(surface, COL_PANEL_BG, self.rect)

        # Tabs
        self._draw_tabs(surface)

        # Content
        cr = self.content_rect
        surface.set_clip(cr)
        self._draw_tileset_content(surface)
        surface.set_clip(None)

    def _draw_tabs(self, surface):
        tab_w = self.rect.width // len(TABS)
        mx, my = pygame.mouse.get_pos()
        for i, (label, _) in enumerate(TABS):
            tx = self.rect.x + i * tab_w
            ty = self.rect.y
            r = pygame.Rect(tx, ty, tab_w, TAB_HEIGHT)

            if i == self.active_tab:
                color = COL_TAB_ACTIVE
            elif r.collidepoint(mx, my):
                color = COL_TAB_HOVER
            else:
                color = COL_TAB_INACTIVE

            pygame.draw.rect(surface, color, r)
            pygame.draw.rect(surface, COL_PANEL_BORDER, r, 1)

            text_color = COL_YELLOW if i == self.active_tab else COL_GRAY
            lbl = self.font.render(label, True, text_color)
            surface.blit(lbl, (tx + (tab_w - lbl.get_width()) // 2,
                               ty + (TAB_HEIGHT - lbl.get_height()) // 2))

    def _draw_tileset_content(self, surface):
        sheet = get_tileset_sheet()
        if sheet is None:
            lbl = self.font.render("No tileset", True, COL_GRAY)
            cr = self.content_rect
            surface.blit(lbl, (cr.x + 10, cr.y + 10))
            return

        ts_cols, ts_rows = get_tileset_dimensions()
        z = self.zoom
        cr = self.content_rect

        # Clamp scroll
        virt_w = ts_cols * z
        virt_h = ts_rows * z
        max_sx = max(0, virt_w - cr.width)
        max_sy = max(0, virt_h - cr.height)
        self.scroll_x = max(0, min(self.scroll_x, max_sx))
        self.scroll_y = max(0, min(self.scroll_y, max_sy))

        sx = self.scroll_x
        sy = self.scroll_y

        # Visible tile range
        col0 = max(0, int(sx / z))
        row0 = max(0, int(sy / z))
        col1 = min(ts_cols, col0 + int(cr.width / z) + 2)
        row1 = min(ts_rows, row0 + int(cr.height / z) + 2)

        if col1 <= col0 or row1 <= row0:
            return

        # Extract and scale visible portion
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
        blit_x = cr.x + int(col0 * z - sx)
        blit_y = cr.y + int(row0 * z - sy)
        surface.blit(scaled, (blit_x, blit_y))

        # Dim non-matching tiles when filtering
        _, cat_filter = TABS[self.active_tab]
        if cat_filter is not None and z >= 6:
            self._draw_filter_overlay(surface, col0, row0, col1, row1,
                                      z, sx, sy, cat_filter)

        # Grid at high zoom
        if z >= 12:
            self._draw_grid(surface, col0, row0, col1, row1, z, sx, sy)

        # Selection rect
        self._draw_selection_rect(surface, z, sx, sy)

        # Current selection highlight
        self._draw_current_highlight(surface, z, sx, sy)

        # Hover
        self._update_hover(surface, z, sx, sy)

    def _draw_filter_overlay(self, surface, col0, row0, col1, row1,
                             z, sx, sy, cat_filter):
        """Dim tiles that don't match the active category filter."""
        cr = self.content_rect
        mgr = get_manager()
        dim = pygame.Surface((max(1, int(z)), max(1, int(z))), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 140))
        for r in range(row0, row1):
            for c in range(col0, col1):
                tid = get_tile_at_position(r, c)
                if tid is None:
                    continue
                if mgr.get_category(tid) != cat_filter:
                    tx = cr.x + int(c * z - sx)
                    ty = cr.y + int(r * z - sy)
                    surface.blit(dim, (tx, ty))

    def _draw_grid(self, surface, col0, row0, col1, row1, z, sx, sy):
        cr = self.content_rect
        alpha = min(60, int(z * 3))
        grid_surf = pygame.Surface((cr.width, cr.height), pygame.SRCALPHA)
        color = (255, 255, 255, alpha)
        for col in range(col0, col1 + 1):
            x = int(col * z - sx)
            if 0 <= x < cr.width:
                pygame.draw.line(grid_surf, color, (x, 0), (x, cr.height))
        for row in range(row0, row1 + 1):
            y = int(row * z - sy)
            if 0 <= y < cr.height:
                pygame.draw.line(grid_surf, color, (0, y), (cr.width, y))
        surface.blit(grid_surf, (cr.x, cr.y))

    def _draw_selection_rect(self, surface, z, sx, sy):
        """Draw the in-progress rectangular selection."""
        if not self.selecting or self.sel_start is None or self.sel_end is None:
            return
        cr = self.content_rect
        r0, c0 = self.sel_start
        r1, c1 = self.sel_end
        sr0, sr1 = sorted((r0, r1))
        sc0, sc1 = sorted((c0, c1))
        x = cr.x + int(sc0 * z - sx)
        y = cr.y + int(sr0 * z - sy)
        w = int((sc1 - sc0 + 1) * z)
        h = int((sr1 - sr0 + 1) * z)
        # Semi-transparent fill
        sel_surf = pygame.Surface((max(1, w), max(1, h)), pygame.SRCALPHA)
        sel_surf.fill((255, 220, 50, 40))
        surface.blit(sel_surf, (x, y))
        pygame.draw.rect(surface, COL_TILE_SELECTED, (x, y, w, h), 2)

    def _draw_current_highlight(self, surface, z, sx, sy):
        """Highlight currently selected tile in browser (set externally)."""
        # This is handled by the editor setting sel_start/sel_end
        pass

    def _update_hover(self, surface, z, sx, sy):
        mx, my = pygame.mouse.get_pos()
        cr = self.content_rect
        self.hover_tile = None
        if not cr.collidepoint(mx, my):
            return
        ts_row, ts_col = self._screen_to_tileset(mx, my)
        tid = get_tile_at_position(ts_row, ts_col)
        if tid is not None:
            self.hover_tile = (ts_row, ts_col, tid)
            hx = cr.x + int(ts_col * z - sx)
            hy = cr.y + int(ts_row * z - sy)
            tile_sz = max(1, int(z))
            thickness = max(1, int(z / 12))
            pygame.draw.rect(surface, COL_TILE_HOVER,
                             (hx, hy, tile_sz, tile_sz), thickness)


# ══════════════════════════════════════════════
# TOOLS PANEL
# ══════════════════════════════════════════════

class ToolsPanel(Panel):
    """Left-side tools: Grass/Finish buttons, brush info, saved brushes list."""

    def __init__(self, rect: pygame.Rect):
        super().__init__(rect)
        self.font = pygame.font.SysFont("consolas", 12)
        self.font_big = pygame.font.SysFont("consolas", 14, bold=True)

        self._grass_preview = pygame.transform.scale(
            make_grass_sprite(), (TILE_PREVIEW_SIZE, TILE_PREVIEW_SIZE))
        self._finish_preview = pygame.transform.scale(
            make_finish_sprite(), (TILE_PREVIEW_SIZE, TILE_PREVIEW_SIZE))

        self.brush_library = BrushLibrary()
        self.scroll_offset = 0

        # Callbacks
        self.on_select_grass = None    # fn()
        self.on_select_finish = None   # fn()
        self.on_save_brush = None      # fn()
        self.on_load_brush = None      # fn(Brush)

    def handle_event(self, event) -> bool:
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False
        sx, sy = event.pos
        if not self.contains(sx, sy):
            return False

        px = sx - self.rect.x
        py = sy - self.rect.y

        # Grass button
        if 8 <= px < 8 + TILE_PREVIEW_SIZE and 8 <= py < 8 + TILE_PREVIEW_SIZE:
            if self.on_select_grass:
                self.on_select_grass()
            return True

        # Finish button
        fx = 8 + TILE_PREVIEW_SIZE + 8
        if fx <= px < fx + TILE_PREVIEW_SIZE and 8 <= py < 8 + TILE_PREVIEW_SIZE:
            if self.on_select_finish:
                self.on_select_finish()
            return True

        # Save brush button (y = ~120)
        btn_y = TILE_PREVIEW_SIZE + 80
        if 8 <= px < self.rect.width - 8 and btn_y <= py < btn_y + 22:
            if self.on_save_brush:
                self.on_save_brush()
            return True

        # Saved brush list items
        list_y = btn_y + 30
        for i, brush in enumerate(self.brush_library.brushes):
            item_y = list_y + i * 20 - self.scroll_offset
            if 0 <= item_y < self.rect.height - list_y:
                if 8 <= px < self.rect.width - 8 and item_y <= py - list_y < item_y + 20:
                    if self.on_load_brush:
                        self.on_load_brush(brush)
                    return True

        return False

    def draw(self, surface: pygame.Surface,
             selected_tile: int = T_EMPTY,
             current_brush: Brush = None):
        pygame.draw.rect(surface, COL_TOOL_BG, self.rect)
        rx, ry = self.rect.x, self.rect.y

        # Grass button
        gx, gy = rx + 8, ry + 8
        surface.blit(self._grass_preview, (gx, gy))
        if selected_tile == T_EMPTY and (current_brush is None or
                                          (current_brush.width == 1 and
                                           current_brush.height == 1 and
                                           current_brush.tiles[0][0] == T_EMPTY)):
            pygame.draw.rect(surface, COL_TILE_SELECTED,
                             (gx - 2, gy - 2,
                              TILE_PREVIEW_SIZE + 4, TILE_PREVIEW_SIZE + 4), 3)

        # Finish button
        fx = gx + TILE_PREVIEW_SIZE + 8
        surface.blit(self._finish_preview, (fx, gy))
        if selected_tile == T_FINISH:
            pygame.draw.rect(surface, COL_TILE_SELECTED,
                             (fx - 2, gy - 2,
                              TILE_PREVIEW_SIZE + 4, TILE_PREVIEW_SIZE + 4), 3)

        # Separator
        sep_y = gy + TILE_PREVIEW_SIZE + 8
        pygame.draw.line(surface, COL_PANEL_BORDER,
                         (rx + 4, sep_y), (rx + self.rect.width - 4, sep_y))

        # Info section
        info_y = sep_y + 6
        if current_brush:
            brush_text = f"Brush: {current_brush.width}x{current_brush.height}"
        else:
            brush_text = "Brush: 1x1"
        surface.blit(self.font.render(brush_text, True, COL_GRAY),
                     (rx + 6, info_y))

        if selected_tile == T_EMPTY:
            surface.blit(self.font.render("Grass (eraser)", True, COL_WHITE),
                         (rx + 6, info_y + 15))
        elif selected_tile == T_FINISH:
            surface.blit(self.font.render("Finish Line", True, COL_WHITE),
                         (rx + 6, info_y + 15))
            surface.blit(self.font.render("Driveable", True, COL_DRIVEABLE),
                         (rx + 6, info_y + 28))
        elif current_brush and current_brush.width == 1 and current_brush.height == 1:
            tid = current_brush.tiles[0][0]
            mgr = get_manager()
            meta = mgr.get(tid)
            cat_name = CATEGORY_DISPLAY.get(meta.category, "?")
            surface.blit(self.font.render(f"{cat_name} #{tid - TILE_BASE}", True, COL_WHITE),
                         (rx + 6, info_y + 15))
            drive_text = "Driveable" if not meta.blocks_movement else "Solid"
            drive_color = COL_DRIVEABLE if not meta.blocks_movement else (200, 80, 80)
            surface.blit(self.font.render(drive_text, True, drive_color),
                         (rx + 6, info_y + 28))

        # Save brush button
        btn_y = ry + TILE_PREVIEW_SIZE + 80
        btn_rect = pygame.Rect(rx + 8, btn_y, self.rect.width - 16, 22)
        mx, my = pygame.mouse.get_pos()
        btn_col = COL_BTN_HOVER if btn_rect.collidepoint(mx, my) else COL_BTN
        pygame.draw.rect(surface, btn_col, btn_rect, border_radius=3)
        pygame.draw.rect(surface, COL_PANEL_BORDER, btn_rect, 1, border_radius=3)
        lbl = self.font.render("[Save Brush]", True, COL_LIGHT_GRAY)
        surface.blit(lbl, (btn_rect.x + (btn_rect.width - lbl.get_width()) // 2,
                           btn_rect.y + 4))

        # Saved brushes list
        list_y = btn_y + 28
        surface.blit(self.font.render("Brushes:", True, COL_GRAY),
                     (rx + 6, list_y))
        list_y += 16
        for i, brush in enumerate(self.brush_library.brushes):
            iy = list_y + i * 18
            if iy - ry > self.rect.height - 4:
                break
            lbl = f"{brush.name} ({brush.width}x{brush.height})"
            surface.blit(self.font.render(lbl, True, COL_LIGHT_GRAY), (rx + 10, iy))


# ══════════════════════════════════════════════
# PROPERTY INSPECTOR
# ══════════════════════════════════════════════

class PropertyInspector(Panel):
    """Right-side panel: shows and edits per-tile metadata."""

    def __init__(self, rect: pygame.Rect):
        super().__init__(rect)
        self.font = pygame.font.SysFont("consolas", 13)
        self.font_title = pygame.font.SysFont("consolas", 14, bold=True)
        self.font_small = pygame.font.SysFont("consolas", 11)

        self._tile_id = None  # currently inspected tile

        # Callbacks
        self.on_open_collision_editor = None  # fn(tile_id)

    @property
    def current_tile_id(self):
        return self._tile_id

    def set_tile(self, tile_id: int | None):
        self._tile_id = tile_id

    def handle_event(self, event) -> bool:
        if self._tile_id is None:
            return False
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return False
        sx, sy = event.pos
        if not self.contains(sx, sy):
            return False

        py = sy - self.rect.y
        mgr = get_manager()
        meta = mgr.get(self._tile_id)

        # Category row (~40)
        if 36 <= py < 54:
            idx = ALL_CATEGORIES.index(meta.category) if meta.category in ALL_CATEGORIES else 0
            idx = (idx + 1) % len(ALL_CATEGORIES)
            meta.category = ALL_CATEGORIES[idx]
            # Auto-set blocks_movement based on category
            if meta.category in (META_TERRAIN, META_SPECIAL):
                meta.blocks_movement = False
                if meta.collision_type == COLL_FULL:
                    meta.collision_type = COLL_NONE
            elif meta.category in (META_OBSTACLES,):
                meta.blocks_movement = True
                if meta.collision_type == COLL_NONE:
                    meta.collision_type = COLL_FULL
            mgr.set(self._tile_id, meta)
            mgr.save()
            return True

        # Friction row (~58)
        if 54 <= py < 72:
            try:
                idx = FRICTION_PRESETS.index(meta.friction)
            except ValueError:
                idx = -1
            idx = (idx + 1) % len(FRICTION_PRESETS)
            meta.friction = FRICTION_PRESETS[idx]
            mgr.set(self._tile_id, meta)
            mgr.save()
            return True

        # Blocks movement row (~76)
        if 72 <= py < 90:
            meta.blocks_movement = not meta.blocks_movement
            mgr.set(self._tile_id, meta)
            mgr.save()
            return True

        # Collision type row (~94)
        if 90 <= py < 108:
            idx = COLLISION_TYPES.index(meta.collision_type) if meta.collision_type in COLLISION_TYPES else 0
            idx = (idx + 1) % len(COLLISION_TYPES)
            meta.collision_type = COLLISION_TYPES[idx]
            if meta.collision_type == COLL_POLYGON and meta.collision_polygon is None:
                meta.collision_polygon = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
            mgr.set(self._tile_id, meta)
            mgr.save()
            return True

        # Edit Polygon button (~114)
        if 110 <= py < 130:
            if meta.collision_type == COLL_POLYGON and self.on_open_collision_editor:
                self.on_open_collision_editor(self._tile_id)
            return True

        return False

    def draw(self, surface: pygame.Surface):
        pygame.draw.rect(surface, COL_PANEL_BG, self.rect)
        pygame.draw.rect(surface, COL_PANEL_BORDER, self.rect, 1)

        rx, ry = self.rect.x + 6, self.rect.y

        # Title
        surface.blit(self.font_title.render("Properties", True, COL_YELLOW),
                     (rx, ry + 4))

        if self._tile_id is None:
            surface.blit(self.font.render("No tile selected", True, COL_GRAY),
                         (rx, ry + 26))
            return

        mgr = get_manager()
        meta = mgr.get(self._tile_id)

        # Tile preview
        sprite = get_tile_sprite(self._tile_id)
        if sprite is not None:
            preview = pygame.transform.scale(sprite, (24, 24))
            surface.blit(preview, (self.rect.right - 34, ry + 4))

        y = ry + 22
        row_h = 18

        # ID
        surface.blit(self.font_small.render(f"ID: {self._tile_id}", True, COL_GRAY),
                     (rx, y))
        y += row_h

        # Category (clickable)
        cat_name = CATEGORY_DISPLAY.get(meta.category, meta.category)
        cat_color = {
            META_TERRAIN: (80, 200, 80),
            META_PROPS: (100, 180, 220),
            META_OBSTACLES: (220, 100, 80),
            META_SPECIAL: (220, 200, 50),
        }.get(meta.category, COL_WHITE)
        surface.blit(self.font.render("Category:", True, COL_LIGHT_GRAY), (rx, y))
        surface.blit(self.font.render(f"[{cat_name}]", True, cat_color),
                     (rx + 72, y))
        y += row_h

        # Friction (clickable)
        surface.blit(self.font.render("Friction:", True, COL_LIGHT_GRAY), (rx, y))
        fric_color = COL_WHITE
        if meta.friction < 0.8:
            fric_color = (100, 180, 255)  # icy blue
        elif meta.friction > 1.2:
            fric_color = (220, 160, 60)   # sandy
        surface.blit(self.font.render(f"[{meta.friction:.1f}]", True, fric_color),
                     (rx + 72, y))
        y += row_h

        # Blocks movement (toggle)
        surface.blit(self.font.render("Blocks:", True, COL_LIGHT_GRAY), (rx, y))
        blk_text = "Yes" if meta.blocks_movement else "No"
        blk_color = (220, 80, 80) if meta.blocks_movement else COL_DRIVEABLE
        surface.blit(self.font.render(f"[{blk_text}]", True, blk_color),
                     (rx + 72, y))
        y += row_h

        # Collision type (cycle)
        surface.blit(self.font.render("Collision:", True, COL_LIGHT_GRAY), (rx, y))
        surface.blit(self.font.render(f"[{meta.collision_type}]", True, COL_WHITE),
                     (rx + 72, y))
        y += row_h

        # Edit Polygon button
        if meta.collision_type == COLL_POLYGON:
            btn_rect = pygame.Rect(rx, y, self.rect.width - 16, 18)
            mx, my_mouse = pygame.mouse.get_pos()
            btn_col = COL_BTN_HOVER if btn_rect.collidepoint(mx, my_mouse) else COL_BTN
            pygame.draw.rect(surface, btn_col, btn_rect, border_radius=2)
            lbl = self.font_small.render("[Edit Polygon]", True, COL_LIGHT_GRAY)
            surface.blit(lbl, (btn_rect.x + 4, btn_rect.y + 2))
        y += row_h + 4

        # Display name
        if meta.display_name:
            surface.blit(self.font_small.render(f'"{meta.display_name}"', True, COL_GRAY),
                         (rx, y))
            y += 14

        # Tags
        if meta.tags:
            tags_str = ", ".join(meta.tags[:3])
            surface.blit(self.font_small.render(f"Tags: {tags_str}", True, COL_GRAY),
                         (rx, y))
