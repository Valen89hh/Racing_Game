"""
touch_overlay.py - Dibuja el joystick virtual y botones táctiles.

Se llama desde `Game._render_race` (después de cars/efectos, antes del HUD)
sólo si `IS_ANDROID` está activo o si se fuerza explícitamente.
"""

from __future__ import annotations

import pygame

from mobile.touch_input import (
    TouchInput,
    STICK_RADIUS,
    BUTTON_RADIUS,
    BRAKE_CENTER,
    POWERUP_CENTER,
)


# Colores RGBA — alpha bajo para no tapar la acción.
_COLOR_STICK_BASE = (60, 60, 70, 110)
_COLOR_STICK_BASE_BORDER = (200, 200, 220, 180)
_COLOR_STICK_THUMB = (220, 220, 235, 200)
_COLOR_BRAKE_IDLE = (180, 40, 40, 140)
_COLOR_BRAKE_PRESS = (240, 80, 80, 220)
_COLOR_POWERUP_IDLE = (200, 170, 30, 140)
_COLOR_POWERUP_PRESS = (255, 220, 60, 220)
_COLOR_BORDER = (240, 240, 245, 200)


def draw(surface: pygame.Surface, touch: TouchInput) -> None:
    """Dibuja overlay encima de la escena. `surface` debe ser la display surface."""
    # Necesitamos blending alpha; usamos una surface intermedia per_pixel_alpha.
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)

    # --- Joystick -----------------------------------------------------------
    base, thumb, active = touch.get_stick_render_info()

    pygame.draw.circle(overlay, _COLOR_STICK_BASE, base, STICK_RADIUS)
    pygame.draw.circle(overlay, _COLOR_STICK_BASE_BORDER, base, STICK_RADIUS, width=3)
    pygame.draw.circle(overlay, _COLOR_STICK_THUMB, thumb, STICK_RADIUS // 2)
    pygame.draw.circle(overlay, _COLOR_BORDER, thumb, STICK_RADIUS // 2, width=2)

    # --- Botones ------------------------------------------------------------
    brake_color = _COLOR_BRAKE_PRESS if touch.brake_pressed else _COLOR_BRAKE_IDLE
    pygame.draw.circle(overlay, brake_color, BRAKE_CENTER, BUTTON_RADIUS)
    pygame.draw.circle(overlay, _COLOR_BORDER, BRAKE_CENTER, BUTTON_RADIUS, width=3)

    powerup_active = touch._powerup_finger is not None  # estado visual continuo
    powerup_color = _COLOR_POWERUP_PRESS if powerup_active else _COLOR_POWERUP_IDLE
    pygame.draw.circle(overlay, powerup_color, POWERUP_CENTER, BUTTON_RADIUS)
    pygame.draw.circle(overlay, _COLOR_BORDER, POWERUP_CENTER, BUTTON_RADIUS, width=3)

    # Texto de los botones.
    font = pygame.font.SysFont(None, 28, bold=True)
    brake_text = font.render("BRAKE", True, (255, 255, 255))
    powerup_text = font.render("ITEM", True, (40, 30, 0))
    overlay.blit(
        brake_text,
        brake_text.get_rect(center=BRAKE_CENTER),
    )
    overlay.blit(
        powerup_text,
        powerup_text.get_rect(center=POWERUP_CENTER),
    )

    surface.blit(overlay, (0, 0))
