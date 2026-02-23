"""
launcher/ui.py - Pygame GUI for the launcher (600x400, dark theme).
"""

import pygame

# Colors
BG_TOP = (20, 20, 35)
BG_BOTTOM = (35, 30, 55)
TEXT_WHITE = (230, 230, 230)
TEXT_GRAY = (160, 160, 170)
TEXT_YELLOW = (255, 220, 50)
TEXT_GREEN = (80, 220, 100)
TEXT_RED = (220, 80, 80)
TEXT_CYAN = (80, 200, 220)
BTN_PLAY = (50, 180, 80)
BTN_PLAY_HOVER = (60, 210, 95)
BTN_PLAY_DISABLED = (60, 80, 60)
BTN_UPDATE = (60, 120, 180)
BTN_UPDATE_HOVER = (70, 140, 210)
BTN_UPDATE_DISABLED = (60, 70, 90)
BAR_BG = (50, 50, 60)
BAR_FILL = (80, 180, 255)
BAR_BORDER = (100, 100, 120)

WIDTH = 600
HEIGHT = 400


class Button:
    """Simple clickable button."""

    def __init__(self, rect, text, color, hover_color, disabled_color):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.color = color
        self.hover_color = hover_color
        self.disabled_color = disabled_color
        self.enabled = True
        self.hovered = False
        self._font = None

    def _get_font(self):
        if self._font is None:
            self._font = pygame.font.SysFont("consolas", 18, bold=True)
        return self._font

    def update(self, mouse_pos):
        self.hovered = self.enabled and self.rect.collidepoint(mouse_pos)

    def draw(self, surface):
        if not self.enabled:
            color = self.disabled_color
        elif self.hovered:
            color = self.hover_color
        else:
            color = self.color

        # Rounded rect
        pygame.draw.rect(surface, color, self.rect, border_radius=6)
        pygame.draw.rect(surface, (255, 255, 255, 60), self.rect, width=1,
                         border_radius=6)

        font = self._get_font()
        txt = font.render(self.text, True, TEXT_WHITE)
        tx = self.rect.centerx - txt.get_width() // 2
        ty = self.rect.centery - txt.get_height() // 2
        surface.blit(txt, (tx, ty))

    def is_clicked(self, mouse_pos):
        return self.enabled and self.rect.collidepoint(mouse_pos)


class LauncherUI:
    """Manages the launcher window and rendering."""

    def __init__(self):
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Arcade Racing 2D - Launcher")

        # Fonts (initialized lazily)
        self._title_font = None
        self._status_font = None
        self._version_font = None
        self._small_font = None

        # State (thread-safe under GIL for simple assignments)
        self.status_text = "Ready"
        self.status_color = TEXT_WHITE
        self.progress = -1.0  # negative = hidden
        self.progress_text = ""
        self.version_text = "v?.?.?"

        # Buttons
        play_rect = (WIDTH // 2 - 110, 200, 220, 50)
        self.btn_play = Button(play_rect, "PLAY", BTN_PLAY,
                               BTN_PLAY_HOVER, BTN_PLAY_DISABLED)

        update_rect = (WIDTH // 2 - 110, 265, 220, 40)
        self.btn_update = Button(update_rect, "Check for Updates",
                                 BTN_UPDATE, BTN_UPDATE_HOVER,
                                 BTN_UPDATE_DISABLED)

        # Pre-render gradient background
        self._bg = self._make_gradient()

    def _get_title_font(self):
        if self._title_font is None:
            self._title_font = pygame.font.SysFont("consolas", 32, bold=True)
        return self._title_font

    def _get_status_font(self):
        if self._status_font is None:
            self._status_font = pygame.font.SysFont("consolas", 16)
        return self._status_font

    def _get_version_font(self):
        if self._version_font is None:
            self._version_font = pygame.font.SysFont("consolas", 13)
        return self._version_font

    def _get_small_font(self):
        if self._small_font is None:
            self._small_font = pygame.font.SysFont("consolas", 12)
        return self._small_font

    def _make_gradient(self):
        """Create a vertical gradient surface."""
        surf = pygame.Surface((WIDTH, HEIGHT))
        for y in range(HEIGHT):
            t = y / HEIGHT
            r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
            g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
            b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
            pygame.draw.line(surf, (r, g, b), (0, y), (WIDTH, y))
        return surf

    def pump_events(self):
        """Process pygame events. Returns list of events for the app to handle."""
        events = []
        for ev in pygame.event.get():
            events.append(ev)
        return events

    def render(self):
        """Draw one frame of the launcher UI."""
        mouse_pos = pygame.mouse.get_pos()
        self.btn_play.update(mouse_pos)
        self.btn_update.update(mouse_pos)

        # Background
        self.screen.blit(self._bg, (0, 0))

        # Decorative line
        pygame.draw.line(self.screen, (80, 70, 120), (40, 80), (WIDTH - 40, 80), 1)

        # Title
        title_font = self._get_title_font()
        title = title_font.render("ARCADE RACING 2D", True, TEXT_YELLOW)
        self.screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 30))

        # Subtitle
        status_font = self._get_status_font()
        sub = status_font.render("Launcher", True, TEXT_GRAY)
        self.screen.blit(sub, (WIDTH // 2 - sub.get_width() // 2, 65))

        # Status text
        status = status_font.render(self.status_text, True, self.status_color)
        self.screen.blit(status, (WIDTH // 2 - status.get_width() // 2, 110))

        # Progress bar (only when active)
        if self.progress >= 0:
            bar_x = 80
            bar_y = 145
            bar_w = WIDTH - 160
            bar_h = 22
            # Background
            pygame.draw.rect(self.screen, BAR_BG,
                             (bar_x, bar_y, bar_w, bar_h), border_radius=4)
            # Fill
            fill_w = int(bar_w * min(self.progress, 1.0))
            if fill_w > 0:
                pygame.draw.rect(self.screen, BAR_FILL,
                                 (bar_x, bar_y, fill_w, bar_h), border_radius=4)
            # Border
            pygame.draw.rect(self.screen, BAR_BORDER,
                             (bar_x, bar_y, bar_w, bar_h), width=1, border_radius=4)
            # Percentage text
            small_font = self._get_small_font()
            pct_text = f"{int(self.progress * 100)}%"
            pct = small_font.render(pct_text, True, TEXT_WHITE)
            self.screen.blit(pct, (bar_x + bar_w // 2 - pct.get_width() // 2,
                                   bar_y + 4))

            # Progress detail text
            if self.progress_text:
                detail = small_font.render(self.progress_text, True, TEXT_GRAY)
                self.screen.blit(detail,
                                 (WIDTH // 2 - detail.get_width() // 2, bar_y + 26))

        # Buttons
        self.btn_play.draw(self.screen)
        self.btn_update.draw(self.screen)

        # Version info (bottom-right)
        ver_font = self._get_version_font()
        ver = ver_font.render(self.version_text, True, TEXT_GRAY)
        self.screen.blit(ver, (WIDTH - ver.get_width() - 12, HEIGHT - 22))

        # Bottom-left credit
        credit = ver_font.render("Powered by PyInstaller", True,
                                 (80, 80, 90))
        self.screen.blit(credit, (12, HEIGHT - 22))

        pygame.display.flip()
