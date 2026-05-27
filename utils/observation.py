"""
observation.py - Construcción de observación para el bot RL.

Vector único de 9 floats compartido entre:
  - training/racing_env.py (RacingEnv para entrenamiento)
  - systems/ai.py (RLSystem para inferencia con PPO en desktop)
  - mobile/onnx_policy.py (ONNXPolicy para inferencia con onnxruntime)

Mantener una sola implementación garantiza que un modelo entrenado con
RacingEnv produzca exactamente los mismos inputs cuando se infiere en el
juego real (con PPO o con ONNX).

Layout del vector (9 floats, todos en [0,1]):
  [0..6] = 7 raycasts normalizados a RAY_MAX_DIST (1.0 = vía libre)
  [7]    = velocidad normalizada a CAR_MAX_SPEED
  [8]    = ángulo al próximo checkpoint (0.5 = de frente)
"""

from __future__ import annotations

import math
import numpy as np

from settings import CAR_MAX_SPEED, WORLD_WIDTH, WORLD_HEIGHT
from utils.helpers import angle_between_points, normalize_angle


NUM_RAYS = 7
RAY_MAX_DIST = 300.0
RAY_STEP = 4
RAY_ANGLES = (-60, -40, -20, 0, 20, 40, 60)


def cast_rays(car, boundary_mask) -> np.ndarray:
    """Lanza 7 rayos desde el auto, devuelve distancias normalizadas (1.0 = no hit)."""
    rays = np.zeros(NUM_RAYS, dtype=np.float32)

    for i, angle_offset in enumerate(RAY_ANGLES):
        ray_angle = car.angle + angle_offset
        rad = math.radians(ray_angle)
        dx = math.sin(rad)
        dy = -math.cos(rad)

        hit_dist = RAY_MAX_DIST
        step = 0
        while step < RAY_MAX_DIST:
            step += RAY_STEP
            sx = int(car.x + dx * step)
            sy = int(car.y + dy * step)

            if not (0 <= sx < WORLD_WIDTH and 0 <= sy < WORLD_HEIGHT):
                hit_dist = step
                break

            if boundary_mask.get_at((sx, sy)):
                hit_dist = step
                break

        rays[i] = hit_dist / RAY_MAX_DIST

    return rays


def angle_to_next_checkpoint(car, track) -> float:
    """
    Ángulo al próximo checkpoint normalizado a [0,1].
    0.5 = de frente, 0.0/1.0 = atrás.
    """
    zones = track.checkpoint_zones
    if not zones:
        if not track.waypoints:
            return 0.5
        wp = track.waypoints[0]
        target = (wp[0], wp[1])
    else:
        idx = car.next_checkpoint_index % len(zones)
        zone = zones[idx]
        target = (zone.centerx, zone.centery)

    target_angle = angle_between_points((car.x, car.y), target)
    diff = normalize_angle(target_angle - car.angle)
    return (diff + 180.0) / 360.0


def build_observation(car, track) -> np.ndarray:
    """Construye el vector de 9 floats (forma esperada por la red MLP)."""
    obs = np.zeros(9, dtype=np.float32)
    obs[0:7] = cast_rays(car, track.boundary_mask)
    obs[7] = min(abs(car.speed) / CAR_MAX_SPEED, 1.0)
    obs[8] = angle_to_next_checkpoint(car, track)
    return obs


# Mapping de acción discreta (Discrete(4)) a inputs del auto.
# Compartido también porque RacingEnv y RLSystem lo replican.
def apply_action(car, action: int) -> None:
    """Aplica la acción discreta al auto (0=acelerar, 1=izq+acel, 2=der+acel, 3=frenar)."""
    if action == 0:
        car.input_accelerate = 1.0
    elif action == 1:
        car.input_accelerate = 1.0
        car.input_turn = -1.0
    elif action == 2:
        car.input_accelerate = 1.0
        car.input_turn = 1.0
    elif action == 3:
        car.input_brake = True
