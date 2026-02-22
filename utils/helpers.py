"""
helpers.py - Funciones auxiliares reutilizables.

Contiene utilidades matemáticas y gráficas que se usan
en múltiples partes del juego.
"""

import math
import pygame


def angle_to_vector(angle_degrees: float) -> tuple[float, float]:
    """
    Convierte un ángulo en grados a un vector unitario de dirección.
    En Pygame, 0° apunta hacia arriba y los ángulos aumentan en sentido horario.

    Args:
        angle_degrees: ángulo en grados.

    Returns:
        Tupla (dx, dy) representando el vector de dirección.
    """
    radians = math.radians(angle_degrees)
    # En nuestro sistema: 0° = arriba, 90° = derecha
    dx = math.sin(radians)
    dy = -math.cos(radians)
    return dx, dy


def distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """
    Calcula la distancia euclidiana entre dos puntos.

    Args:
        p1: primer punto (x, y).
        p2: segundo punto (x, y).

    Returns:
        Distancia entre los puntos.
    """
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def angle_between_points(origin: tuple[float, float],
                         target: tuple[float, float]) -> float:
    """
    Calcula el ángulo desde el origen hacia el objetivo.

    Args:
        origin: punto de origen (x, y).
        target: punto objetivo (x, y).

    Returns:
        Ángulo en grados (0° = arriba, sentido horario).
    """
    dx = target[0] - origin[0]
    dy = target[1] - origin[1]
    # atan2 con ejes invertidos para que 0° = arriba
    return math.degrees(math.atan2(dx, -dy)) % 360


def normalize_angle(angle: float) -> float:
    """
    Normaliza un ángulo al rango [-180, 180).

    Args:
        angle: ángulo en grados.

    Returns:
        Ángulo normalizado.
    """
    angle = angle % 360
    if angle > 180:
        angle -= 360
    return angle


def lerp(a: float, b: float, t: float) -> float:
    """
    Interpolación lineal entre dos valores.

    Args:
        a: valor inicial.
        b: valor final.
        t: factor de interpolación (0.0 a 1.0).

    Returns:
        Valor interpolado.
    """
    return a + (b - a) * t


def clamp(value: float, min_val: float, max_val: float) -> float:
    """
    Limita un valor dentro de un rango.

    Args:
        value: valor a limitar.
        min_val: valor mínimo.
        max_val: valor máximo.

    Returns:
        Valor dentro del rango [min_val, max_val].
    """
    return max(min_val, min(value, max_val))


def create_car_surface(width: int, height: int,
                       color: tuple[int, int, int]) -> pygame.Surface:
    """
    Crea un sprite procedural para un auto de carreras.
    Genera un auto con forma aerodinámica, parabrisas y detalles.

    Args:
        width: ancho del sprite.
        height: alto del sprite.
        color: color principal del auto (R, G, B).

    Returns:
        Surface de Pygame con el sprite del auto.
    """
    surface = pygame.Surface((width, height), pygame.SRCALPHA)

    # Cuerpo principal del auto (forma redondeada)
    body_rect = pygame.Rect(2, 4, width - 4, height - 8)
    pygame.draw.rect(surface, color, body_rect, border_radius=5)

    # Parabrisas (parte frontal del auto, arriba en top-down)
    windshield_color = (180, 210, 240)
    windshield_rect = pygame.Rect(4, 6, width - 8, height // 4)
    pygame.draw.rect(surface, windshield_color, windshield_rect, border_radius=3)

    # Ventana trasera
    rear_window = pygame.Rect(4, height - 14, width - 8, 6)
    pygame.draw.rect(surface, windshield_color, rear_window, border_radius=2)

    # Ruedas (4 rectángulos oscuros)
    wheel_color = (30, 30, 30)
    wheel_w, wheel_h = 4, 8
    # Rueda frontal izquierda
    pygame.draw.rect(surface, wheel_color, (0, 6, wheel_w, wheel_h))
    # Rueda frontal derecha
    pygame.draw.rect(surface, wheel_color, (width - wheel_w, 6, wheel_w, wheel_h))
    # Rueda trasera izquierda
    pygame.draw.rect(surface, wheel_color, (0, height - 14, wheel_w, wheel_h))
    # Rueda trasera derecha
    pygame.draw.rect(surface, wheel_color,
                     (width - wheel_w, height - 14, wheel_w, wheel_h))

    # Línea central decorativa
    stripe_color = (
        min(255, color[0] + 60),
        min(255, color[1] + 60),
        min(255, color[2] + 60),
    )
    pygame.draw.line(surface, stripe_color,
                     (width // 2, 10), (width // 2, height - 10), 2)

    return surface


def draw_text_centered(surface: pygame.Surface, text: str,
                       font: pygame.font.Font, color: tuple,
                       y: int, x: int = None):
    """
    Dibuja texto centrado horizontalmente en la pantalla.

    Args:
        surface: superficie donde dibujar.
        text: texto a mostrar.
        font: fuente de Pygame.
        color: color del texto.
        y: posición vertical.
        x: posición horizontal (None = centrado).
    """
    rendered = font.render(text, True, color)
    rect = rendered.get_rect()
    if x is None:
        rect.centerx = surface.get_width() // 2
    else:
        rect.centerx = x
    rect.y = y
    surface.blit(rendered, rect)
