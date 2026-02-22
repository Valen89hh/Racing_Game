"""
camera.py - Camara con look-ahead fuerte y rotacion parcial suave.

La camara combina dos tecnicas para dar orientacion sin marear:

1. LOOK-AHEAD FUERTE: la camara se desplaza ~200px en la direccion
   del auto, asi el jugador siempre ve lo que viene adelante.

2. ROTACION PARCIAL SUAVE: la camara gira lentamente hacia la
   direccion del auto, pero con velocidad angular limitada (~35 deg/s).
   Durante curvas rapidas apenas rota (efecto ~25-30% de rotacion),
   y en rectas largas se alinea gradualmente.

world_to_screen() transforma cualquier punto del mundo a coordenadas
de pantalla aplicando traslacion + rotacion:

    1.  dx, dy  = mundo - centro_camara     (traslacion)
    2.  sx = dx*cos(-a) - dy*sin(-a)        (rotacion)
        sy = dx*sin(-a) + dy*cos(-a)
    3.  sx += SCREEN_W/2,  sy += SCREEN_H/2 (centrar en pantalla)
"""

import math

from settings import (
    SCREEN_WIDTH, SCREEN_HEIGHT,
    CAMERA_SMOOTHING, CAMERA_LOOK_AHEAD,
    CAMERA_ROTATION_SPEED, CAMERA_MAX_ANGULAR_SPEED,
)


# Radio de visibilidad = mitad de la diagonal de la pantalla + margen
_HALF_DIAG = math.hypot(SCREEN_WIDTH, SCREEN_HEIGHT) / 2


class Camera:
    """
    Camara 2D con look-ahead fuerte y rotacion parcial suave.
    """

    def __init__(self):
        # Centro de la vista en coordenadas del mundo
        self.cx = 0.0
        self.cy = 0.0
        self.angle = 0.0          # grados, misma convencion que Car.angle

        # Look-ahead actual (suavizado)
        self._look_x = 0.0
        self._look_y = 0.0

        # Coseno/seno de -angle, pre-calculados para world_to_screen
        self._cos = 1.0
        self._sin = 0.0

    # ────────────────────────────────

    def snap_to(self, x: float, y: float, angle: float = 0.0):
        """Posiciona la camara instantaneamente (sin lerp)."""
        self.cx = x
        self.cy = y
        self.angle = angle
        self._look_x = 0.0
        self._look_y = 0.0
        self._update_trig()

    def update(self, target_x: float, target_y: float,
               target_angle: float, target_speed: float, dt: float):
        """
        Actualiza posicion y rotacion con interpolacion suave.

        Args:
            target_x, target_y: posicion del auto en el mundo.
            target_angle: angulo del auto (grados, 0=arriba, CW).
            target_speed: velocidad escalar del auto.
            dt: delta time en segundos.
        """
        t_pos = min(CAMERA_SMOOTHING * dt, 1.0)

        # ── Look-ahead fuerte (desplazamiento en la direccion del auto) ──
        speed_ratio = min(abs(target_speed) / 500.0, 1.0)
        look_dist = CAMERA_LOOK_AHEAD * speed_ratio

        rad = math.radians(target_angle)
        target_lx = math.sin(rad) * look_dist
        target_ly = -math.cos(rad) * look_dist

        self._look_x += (target_lx - self._look_x) * t_pos
        self._look_y += (target_ly - self._look_y) * t_pos

        # ── Posicion (lerp hacia el objetivo + look-ahead) ──
        desired_x = target_x + self._look_x
        desired_y = target_y + self._look_y

        self.cx += (desired_x - self.cx) * t_pos
        self.cy += (desired_y - self.cy) * t_pos

        # ── Rotacion parcial suave ──
        # La camara intenta seguir el angulo del auto pero con:
        # - Velocidad de lerp baja (CAMERA_ROTATION_SPEED)
        # - Velocidad angular maxima limitada (CAMERA_MAX_ANGULAR_SPEED)
        # Esto hace que en curvas rapidas la camara apenas rote (~25-30%),
        # y en rectas largas se alinee gradualmente.
        t_rot = min(CAMERA_ROTATION_SPEED * dt, 1.0)
        diff = (target_angle - self.angle) % 360
        if diff > 180:
            diff -= 360

        desired_change = diff * t_rot

        # Limitar velocidad angular para evitar giros bruscos
        max_change = CAMERA_MAX_ANGULAR_SPEED * dt
        if desired_change > max_change:
            desired_change = max_change
        elif desired_change < -max_change:
            desired_change = -max_change

        self.angle = (self.angle + desired_change) % 360

        self._update_trig()

    def _update_trig(self):
        """Pre-calcula cos/sin para transformaciones rapidas."""
        rad = math.radians(-self.angle)
        self._cos = math.cos(rad)
        self._sin = math.sin(rad)

    # ────────────────────────────────

    def world_to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        """
        Transforma coordenadas del mundo a pantalla (con rotacion).

        El punto aparece en pantalla rotado segun el angulo parcial
        de la camara, dando una leve orientacion sin marear.
        """
        dx = wx - self.cx
        dy = wy - self.cy
        sx = dx * self._cos - dy * self._sin + SCREEN_WIDTH * 0.5
        sy = dx * self._sin + dy * self._cos + SCREEN_HEIGHT * 0.5
        return sx, sy

    def is_visible(self, wx: float, wy: float, margin: float = 60) -> bool:
        """
        Verifica si un punto del mundo esta dentro del area visible.
        Usa comprobacion circular (mas rapida que rotar un rect).
        """
        dx = wx - self.cx
        dy = wy - self.cy
        return (dx * dx + dy * dy) < (_HALF_DIAG + margin) ** 2

    def screen_angle(self, world_angle: float) -> float:
        """
        Convierte un angulo del mundo a angulo en pantalla.
        Util para rotar sprites de entidades.

        Con rotacion parcial, el auto del jugador aparecera ligeramente
        rotado en pantalla (no siempre apuntando arriba).
        """
        return (world_angle - self.angle) % 360
