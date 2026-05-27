"""
touch_input.py - Joystick virtual + botones para controles táctiles.

Pygame en Android emite eventos `FINGERDOWN`, `FINGERMOTION`, `FINGERUP` con
coordenadas normalizadas en [0,1] (`event.x`, `event.y`, `event.finger_id`).

`TouchInput` mantiene estado interno (qué dedo controla el stick, qué dedos
están sobre cada botón) y expone el resultado state-based para que el
`InputHandler` lo consuma del mismo modo que con teclado.

Layout (sobre una superficie lógica de 1280x720):

    +-----------------------------------------+
    |                                         |
    |                                         |
    |                                         |
    |                               [POWERUP] |   <- botón amarillo
    |   .O.                                   |
    |   (o)                          [BRAKE]  |   <- botón rojo
    |   '-'                                   |
    +-----------------------------------------+
       ^ joystick (radio = STICK_RADIUS)

El joystick es "follow stick": la base aparece donde el primer dedo toca la
mitad izquierda. Esto evita exigir precisión para encontrar un círculo fijo.
"""

from __future__ import annotations

import math
from settings import SCREEN_WIDTH, SCREEN_HEIGHT


# Geometría base (en coords lógicas 1280x720). Si la pantalla real es
# diferente, el caller debe pasar la resolución real al construir el input.
STICK_RADIUS = 110
STICK_DEADZONE = 0.18       # fracción del radio (movimiento ignorado en el centro)
BUTTON_RADIUS = 75
BRAKE_CENTER = (SCREEN_WIDTH - 120, SCREEN_HEIGHT - 130)
POWERUP_CENTER = (SCREEN_WIDTH - 270, SCREEN_HEIGHT - 230)
LEFT_HALF_X = SCREEN_WIDTH // 2   # zona donde se permite originar el stick


class TouchInput:
    """Estado de los controles táctiles. Singleton vía `get_touch_input()`."""

    def __init__(self, screen_size: tuple[int, int] = (SCREEN_WIDTH, SCREEN_HEIGHT)):
        # Tamaño LÓGICO en el que están expresadas las coords del overlay/botones.
        self.screen_w, self.screen_h = screen_size

        # Transform pantalla física → lógica. Por defecto identidad (sin letterbox).
        # En Android, Game.configure_display() lo actualiza con el offset/scale real.
        self._phys_w = float(self.screen_w)
        self._phys_h = float(self.screen_h)
        self._lb_off_x = 0.0
        self._lb_off_y = 0.0
        self._lb_w = float(self.screen_w)
        self._lb_h = float(self.screen_h)

        # Joystick
        self._stick_finger: int | None = None
        self._stick_base: tuple[float, float] = (0.0, 0.0)
        self._stick_pos: tuple[float, float] = (0.0, 0.0)

        # Botones
        self._brake_finger: int | None = None
        self._powerup_finger: int | None = None
        self._powerup_press_pending = False   # flag one-shot (consumida por consume_powerup_press)

    def configure_display(
        self,
        phys_size: tuple[int, int],
        lb_offset: tuple[int, int],
        lb_size: tuple[int, int],
    ) -> None:
        """
        Informa al input cómo convertir coords físicas (FINGER events) a las
        coords lógicas en las que están definidos los botones.
        """
        self._phys_w, self._phys_h = float(phys_size[0]), float(phys_size[1])
        self._lb_off_x, self._lb_off_y = float(lb_offset[0]), float(lb_offset[1])
        self._lb_w, self._lb_h = float(lb_size[0]), float(lb_size[1])

    # --- API para el event loop ---------------------------------------------

    def handle_event(self, event) -> bool:
        """
        Procesa un evento de Pygame. Retorna True si el evento fue manejado
        (para que el caller pueda decidir si lo pasa adelante a la UI).
        """
        import pygame
        if event.type == pygame.FINGERDOWN:
            return self._on_down(event)
        if event.type == pygame.FINGERMOTION:
            return self._on_motion(event)
        if event.type == pygame.FINGERUP:
            return self._on_up(event)
        return False

    def reset(self) -> None:
        """Libera todos los dedos. Llamar al cambiar de estado (p.ej. ESC)."""
        self._stick_finger = None
        self._stick_pos = self._stick_base
        self._brake_finger = None
        self._powerup_finger = None
        self._powerup_press_pending = False

    # --- API para input_handler / render ------------------------------------

    @property
    def stick_active(self) -> bool:
        return self._stick_finger is not None

    @property
    def stick_vector(self) -> tuple[float, float]:
        """(dx, dy) normalizado en [-1,1] con deadzone aplicada. (0,0) si inactivo."""
        if self._stick_finger is None:
            return (0.0, 0.0)
        bx, by = self._stick_base
        px, py = self._stick_pos
        dx = (px - bx) / STICK_RADIUS
        dy = (py - by) / STICK_RADIUS
        mag = math.hypot(dx, dy)
        if mag < STICK_DEADZONE:
            return (0.0, 0.0)
        if mag > 1.0:
            dx /= mag
            dy /= mag
        return (dx, dy)

    @property
    def brake_pressed(self) -> bool:
        return self._brake_finger is not None

    def consume_powerup_press(self) -> bool:
        """One-shot: True una sola vez por cada tap nuevo en el botón powerup."""
        if self._powerup_press_pending:
            self._powerup_press_pending = False
            return True
        return False

    def get_stick_render_info(self) -> tuple[tuple[int, int], tuple[int, int], bool]:
        """(base_xy, current_xy, active) para que el overlay pueda dibujar."""
        if self._stick_finger is None:
            # Render en posición de descanso (esquina inferior-izquierda).
            base = (180, self.screen_h - 180)
            return (base, base, False)
        return (
            (int(self._stick_base[0]), int(self._stick_base[1])),
            (int(self._stick_pos[0]), int(self._stick_pos[1])),
            True,
        )

    # --- Internos -----------------------------------------------------------

    def _denorm(self, event) -> tuple[float, float]:
        """Convierte FINGER event (normalizado al display físico) a coord lógica."""
        phys_x = event.x * self._phys_w
        phys_y = event.y * self._phys_h
        # Trasladar al espacio del letterbox y escalar a coords lógicas.
        logical_x = (phys_x - self._lb_off_x) * (self.screen_w / self._lb_w)
        logical_y = (phys_y - self._lb_off_y) * (self.screen_h / self._lb_h)
        return (logical_x, logical_y)

    def _on_down(self, event) -> bool:
        x, y = self._denorm(event)
        fid = event.finger_id

        # Botón BRAKE
        if _hit_circle(x, y, BRAKE_CENTER, BUTTON_RADIUS) and self._brake_finger is None:
            self._brake_finger = fid
            return True

        # Botón POWERUP
        if _hit_circle(x, y, POWERUP_CENTER, BUTTON_RADIUS) and self._powerup_finger is None:
            self._powerup_finger = fid
            self._powerup_press_pending = True
            return True

        # Joystick (sólo si el toque originó en la mitad izquierda y no hay otro stick)
        if x < LEFT_HALF_X and self._stick_finger is None:
            self._stick_finger = fid
            self._stick_base = (x, y)
            self._stick_pos = (x, y)
            return True

        return False

    def _on_motion(self, event) -> bool:
        x, y = self._denorm(event)
        fid = event.finger_id
        if fid == self._stick_finger:
            # Limita el thumb a STICK_RADIUS para feel correcto.
            bx, by = self._stick_base
            dx, dy = x - bx, y - by
            mag = math.hypot(dx, dy)
            if mag > STICK_RADIUS:
                scale = STICK_RADIUS / mag
                x = bx + dx * scale
                y = by + dy * scale
            self._stick_pos = (x, y)
            return True
        return False

    def _on_up(self, event) -> bool:
        fid = event.finger_id
        if fid == self._stick_finger:
            self._stick_finger = None
            self._stick_pos = self._stick_base
            return True
        if fid == self._brake_finger:
            self._brake_finger = None
            return True
        if fid == self._powerup_finger:
            self._powerup_finger = None
            return True
        return False


def _hit_circle(x: float, y: float, center: tuple[float, float], r: float) -> bool:
    cx, cy = center
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


# --- Singleton ----------------------------------------------------------------

_instance: TouchInput | None = None


def get_touch_input() -> TouchInput:
    """Acceso al singleton. Se crea perezosamente."""
    global _instance
    if _instance is None:
        _instance = TouchInput()
    return _instance
