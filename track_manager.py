"""
track_manager.py - Gestión de archivos de pistas.

Permite guardar, cargar y listar circuitos en formato JSON.
Los control points originales del juego se centralizan aquí.
"""

import json
import os
import time


# Directorio donde se guardan las pistas
from utils.base_path import TRACKS_DIR


def get_default_control_points():
    """Retorna los ~40 puntos de control del circuito original."""
    return [
        (550, 500),  (850, 500),  (1150, 500),  (1500, 500),
        (1800, 500),
        (2050, 530),  (2250, 620),  (2400, 780),  (2480, 980),
        (2500, 1200),  (2480, 1400),
        (2520, 1560),  (2640, 1680),  (2820, 1720),
        (2980, 1660),  (3060, 1520),  (3060, 1360),
        (3020, 1200),  (3080, 1050),  (3200, 940),
        (3150, 800),  (3020, 740),  (2880, 820),
        (2760, 960),  (2580, 1140),  (2340, 1380),
        (2080, 1620),  (1820, 1800),
        (1540, 1900),  (1260, 1920),  (1020, 1840),
        (840, 1700),
        (740, 1500),  (700, 1300),
        (660, 1100),  (580, 940),  (520, 800),
        (500, 700),  (520, 620),
    ]


def _ensure_tracks_dir():
    """Crea el directorio de pistas si no existe."""
    os.makedirs(TRACKS_DIR, exist_ok=True)


def save_track(filename, name, control_points):
    """Guarda una pista clasica como archivo JSON.

    Args:
        filename: nombre del archivo (sin extensión, se agrega .json).
        name: nombre visible de la pista.
        control_points: lista de (x, y) tuples.
    """
    _ensure_tracks_dir()
    if not filename.endswith(".json"):
        filename += ".json"
    data = {
        "name": name,
        "author": "Player",
        "version": 1,
        "control_points": [list(p) for p in control_points],
    }
    filepath = os.path.join(TRACKS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return filepath


def save_tile_track(filename, name, terrain, tile_overrides=None,
                    rotations=None, checkpoint_zones=None,
                    circuit_direction=None, powerup_zones=None):
    """Guarda una pista tile-based como archivo JSON.

    Args:
        filename: nombre del archivo (sin extensión, se agrega .json).
        name: nombre visible de la pista.
        terrain: grid 2D de IDs de terreno.
        tile_overrides: optional dict of "row,col" -> {"friction": float}
        rotations: optional 2D grid of rotation values (0-3).
        powerup_zones: optional list of [x, y, w, h] power-up spawn zones.
    """
    _ensure_tracks_dir()
    if not filename.endswith(".json"):
        filename += ".json"

    has_overrides = bool(tile_overrides)
    has_rotations = rotations and any(
        r != 0 for row in rotations for r in row)
    version = 4 if (has_overrides or has_rotations) else 3
    data = {
        "name": name,
        "author": "Player",
        "version": version,
        "format": "tiles",
        "tile_size": 64,
        "grid_width": len(terrain[0]) if terrain else 0,
        "grid_height": len(terrain),
        "terrain": terrain,
    }
    if tile_overrides:
        data["tile_overrides"] = tile_overrides
    if has_rotations:
        data["rotations"] = rotations
    if checkpoint_zones:
        data["checkpoint_zones"] = checkpoint_zones
    if circuit_direction:
        data["circuit_direction"] = circuit_direction
    if powerup_zones:
        data["powerup_zones"] = powerup_zones

    # Embed driveable tile IDs so dedicated servers don't need tileset.png
    from tile_defs import is_driveable as _td_is_driveable, T_EMPTY
    driveable_ids = set()
    for row in terrain:
        for tid in row:
            if tid != T_EMPTY and _td_is_driveable(tid):
                driveable_ids.add(tid)
    data["driveable_tiles"] = sorted(driveable_ids)

    filepath = os.path.join(TRACKS_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=None)
    return filepath


def load_track(filename):
    """Carga una pista desde un archivo JSON (soporta ambos formatos).

    Args:
        filename: nombre del archivo (con o sin extensión).

    Returns:
        dict con los datos de la pista. Incluye key "format" = "tiles" o ausente (classic).
    """
    if not filename.endswith(".json"):
        filename += ".json"
    filepath = os.path.join(TRACKS_DIR, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Detectar formato
    if data.get("format") == "tiles" or "terrain" in data:
        # Formato tiles (v3 or v4) - retornar tal cual
        data["format"] = "tiles"
        # v4 may have tile_overrides, v3 doesn't - both work
    else:
        # Formato clasico
        data["control_points"] = [tuple(p) for p in data["control_points"]]

    return data


def list_tracks():
    """Lista las pistas disponibles ordenadas por fecha de modificación (más reciente primero).

    Returns:
        lista de dicts con keys: filename, name, path, modified, type.
    """
    _ensure_tracks_dir()
    tracks = []
    for fname in os.listdir(TRACKS_DIR):
        if not fname.endswith(".json"):
            continue
        filepath = os.path.join(TRACKS_DIR, fname)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            track_type = "tiles" if (data.get("format") == "tiles" or "terrain" in data) else "classic"

            tracks.append({
                "filename": fname,
                "name": data.get("name", fname),
                "path": filepath,
                "modified": os.path.getmtime(filepath),
                "type": track_type,
            })
        except (json.JSONDecodeError, OSError):
            continue
    tracks.sort(key=lambda t: t["modified"], reverse=True)
    return tracks


def export_default_track():
    """Crea tracks/default_circuit.json con el circuito original si no existe."""
    _ensure_tracks_dir()
    filepath = os.path.join(TRACKS_DIR, "default_circuit.json")
    if os.path.exists(filepath):
        return
    data = {
        "name": "Grand Circuit",
        "author": "Default",
        "version": 1,
        "control_points": [list(p) for p in get_default_control_points()],
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
