"""
sprites.py - Carga y gestión de sprites pixel art.

Carga sprite sheets del asset pack y las prepara para uso en el juego:
- Autos: 8 frames direccionales (16x16 cada uno), escalados a tamaño de juego.
- Tiles de pista: texturas de asfalto y césped.
- Props: objetos decorativos.
"""

import os
import pygame

# Ruta base de assets (relativa al directorio del proyecto)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(_BASE_DIR, "assets")


def load_image(relative_path: str) -> pygame.Surface:
    """Carga una imagen desde la carpeta assets."""
    path = os.path.join(ASSETS_DIR, relative_path)
    return pygame.image.load(path).convert_alpha()


def load_car_frames(filename: str, frame_size: int = 16,
                    scale: int = 3) -> list[pygame.Surface]:
    """
    Carga un sprite sheet de auto con 8 frames direccionales.

    El sprite sheet es horizontal: 128x16 (8 frames de 16x16).
    Los frames representan 8 direcciones en sentido horario:
        0=arriba, 1=arriba-derecha, 2=derecha, 3=abajo-derecha,
        4=abajo, 5=abajo-izquierda, 6=izquierda, 7=arriba-izquierda

    Args:
        filename: nombre del archivo en assets/cars/
        frame_size: tamaño de cada frame (16x16 por defecto)
        scale: factor de escala (3x = 48x48 px finales)

    Returns:
        Lista de 8 superficies escaladas, una por dirección.
    """
    sheet = load_image(os.path.join("cars", filename))
    frames = []
    scaled_size = frame_size * scale

    for i in range(8):
        rect = pygame.Rect(i * frame_size, 0, frame_size, frame_size)
        frame = pygame.Surface((frame_size, frame_size), pygame.SRCALPHA)
        frame.blit(sheet, (0, 0), rect)
        # Escalar con NEAREST para preservar pixel art nítido
        scaled = pygame.transform.scale(frame, (scaled_size, scaled_size))
        frames.append(scaled)

    return frames


def get_frame_for_angle(frames: list[pygame.Surface],
                        angle: float) -> pygame.Surface:
    """
    Selecciona el frame correcto para un ángulo dado.

    El ángulo del juego es: 0°=arriba, 90°=derecha, 180°=abajo, 270°=izquierda.
    Los frames están en el mismo orden: 0=arriba, 1=45°, 2=90°, etc.

    Args:
        frames: lista de 8 frames direccionales.
        angle: ángulo en grados (0-360).

    Returns:
        El frame más cercano al ángulo dado.
    """
    # Normalizar a 0-360
    angle = angle % 360
    # Mapear a índice de frame (cada 45°)
    index = round(angle / 45) % 8
    return frames[index]


def load_tile(relative_path: str, scale: int = 1) -> pygame.Surface:
    """Carga un tile y opcionalmente lo escala."""
    img = load_image(relative_path)
    if scale != 1:
        w, h = img.get_size()
        img = pygame.transform.scale(img, (w * scale, h * scale))
    return img


def extract_tiles(relative_path: str, tile_size: int = 16,
                  scale: int = 1) -> list[pygame.Surface]:
    """
    Extrae tiles individuales de un sprite sheet horizontal.

    Args:
        relative_path: ruta relativa en assets/
        tile_size: tamaño de cada tile
        scale: factor de escala

    Returns:
        Lista de superficies de tiles.
    """
    sheet = load_image(relative_path)
    sheet_w, sheet_h = sheet.get_size()
    tiles = []

    cols = sheet_w // tile_size
    rows = sheet_h // tile_size

    for row in range(rows):
        for col in range(cols):
            rect = pygame.Rect(col * tile_size, row * tile_size,
                               tile_size, tile_size)
            tile = pygame.Surface((tile_size, tile_size), pygame.SRCALPHA)
            tile.blit(sheet, (0, 0), rect)
            if scale != 1:
                tile = pygame.transform.scale(
                    tile, (tile_size * scale, tile_size * scale)
                )
            tiles.append(tile)

    return tiles
