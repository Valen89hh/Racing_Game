"""
racing_env.py - Entorno Gymnasium para entrenamiento RL del juego de carreras.

Envuelve la física real del juego (PhysicsSystem, CollisionSystem, TileTrack, Car)
en un entorno headless que corre sin ventana visible.

Observación: 9 floats (7 raycasts + velocidad normalizada + ángulo al checkpoint)
Acciones: Discrete(4) — 0=acelerar, 1=izq+acelerar, 2=der+acelerar, 3=frenar
"""

import os
import math

# Headless pygame setup — must happen before any pygame import
os.environ['SDL_VIDEODRIVER'] = 'dummy'

import pygame
import numpy as np
import gymnasium as gym
from gymnasium import spaces

# Initialize pygame in headless mode
pygame.init()
pygame.display.set_mode((1, 1))

from settings import (
    CAR_MAX_SPEED, WORLD_WIDTH, WORLD_HEIGHT, TOTAL_LAPS,
    PLAYER_COLORS,
)
from entities.car import Car
from systems.physics import PhysicsSystem
from systems.collision import CollisionSystem
from tile_track import TileTrack
from utils.helpers import angle_to_vector, angle_between_points, normalize_angle
import track_manager


class RacingEnv(gym.Env):
    """
    Entorno Gymnasium que simula una carrera usando la física real del juego.
    """

    metadata = {"render_modes": []}

    FIXED_DT = 1.0 / 60.0
    MAX_STEPS = 3000
    MAX_STALL_FRAMES = 180
    NUM_RAYS = 7
    RAY_MAX_DIST = 300.0
    RAY_STEP = 4
    RAY_ANGLES = [-60, -40, -20, 0, 20, 40, 60]

    def __init__(self, track_path: str):
        super().__init__()

        # Load track data
        self._track_path = track_path
        data = track_manager.load_track(track_path)
        if data.get("format") != "tiles":
            raise ValueError(f"RacingEnv only supports tile-based tracks, got: {track_path}")
        self._tile_data = data

        # Build track
        self.track = TileTrack(data)
        self.physics = PhysicsSystem()
        self.collision_system = CollisionSystem(self.track)

        # Spaces
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(9,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(4)

        # State
        self.car = None
        self.steps = 0
        self.stall_frames = 0
        self.no_progress_frames = 0
        self.idle_counter = 0
        self._prev_progress = 0.0

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)

        # Create car at start position
        sp = self.track.start_positions[0]
        self.car = Car(sp[0], sp[1], sp[2], PLAYER_COLORS[0], 0)

        self.steps = 0
        self.stall_frames = 0
        self.no_progress_frames = 0
        self.idle_counter = 0
        self._prev_progress = self._compute_progress()

        obs = self._get_observation()
        return obs, {}

    def step(self, action):
        self.steps += 1

        # 1. Reset inputs and map action
        self.car.reset_inputs()
        self._apply_action(action)

        # 2. Update effects
        self.car.update_effects(self.FIXED_DT)

        # 3. Physics
        self.physics.update(self.car, self.FIXED_DT, self.track)
        self.car.update_sprite()

        # 4. Track collision
        hit_wall = False
        if self.collision_system.check_track_collision(self.car):
            normal = self.collision_system.resolve_track_collision(self.car)
            self.physics.apply_collision_response(self.car, normal)
            self.car.update_sprite()
            hit_wall = True
        else:
            self.physics.clear_wall_contact(self.car)

        # 5. Checkpoints and laps
        old_laps = self.car.laps
        old_cp = self.car.next_checkpoint_index
        self.collision_system.update_checkpoints(self.car)
        crossed_checkpoint = self.car.next_checkpoint_index != old_cp
        completed_lap = self.car.laps > old_laps

        # 6. Stall detection
        if abs(self.car.speed) < 15.0:
            self.stall_frames += 1
        else:
            self.stall_frames = 0

        # 6b. Idle detection (velocidad casi nula = política colapsada)
        if abs(self.car.speed) < 5.0:
            self.idle_counter += 1
        else:
            self.idle_counter = 0

        # 7. Calculate reward
        reward, progress_delta = self._calculate_reward(
            hit_wall, crossed_checkpoint, completed_lap
        )

        # 8. No-progress tracking
        if abs(progress_delta) < 0.5:
            self.no_progress_frames += 1
        else:
            self.no_progress_frames = 0

        # 9. Extra penalty for no progress (leve, sin truncar)
        if self.no_progress_frames > 120:
            reward -= 0.1

        # 10. Check done
        # hit_wall NO termina el episodio — el auto rebota y sigue
        # (igual que en el juego real). Solo termina al completar vueltas.
        terminated = self.car.laps >= TOTAL_LAPS
        truncated = (
            self.steps >= self.MAX_STEPS or
            self.stall_frames >= self.MAX_STALL_FRAMES
        )

        obs = self._get_observation()
        info = {
            "laps": self.car.laps,
            "speed": self.car.speed,
            "steps": self.steps,
            "hit_wall": hit_wall,
            "no_progress_frames": self.no_progress_frames,
        }

        return obs, reward, terminated, truncated, info

    def _apply_action(self, action):
        """Map discrete action to car inputs."""
        if action == 0:  # Forward
            self.car.input_accelerate = 1.0
        elif action == 1:  # Left + forward
            self.car.input_accelerate = 1.0
            self.car.input_turn = -1.0
        elif action == 2:  # Right + forward
            self.car.input_accelerate = 1.0
            self.car.input_turn = 1.0
        elif action == 3:  # Brake
            self.car.input_brake = True

    def _get_observation(self):
        """Build 9-float observation vector."""
        rays = self._cast_rays()
        speed_norm = min(abs(self.car.speed) / CAR_MAX_SPEED, 1.0)
        angle_norm = self._angle_to_next_checkpoint()

        obs = np.zeros(9, dtype=np.float32)
        obs[0:7] = rays
        obs[7] = speed_norm
        obs[8] = angle_norm
        return obs

    def _cast_rays(self):
        """Cast 7 rays from car position, return normalized distances."""
        rays = np.zeros(self.NUM_RAYS, dtype=np.float32)
        mask = self.track.boundary_mask

        for i, angle_offset in enumerate(self.RAY_ANGLES):
            ray_angle = self.car.angle + angle_offset
            rad = math.radians(ray_angle)
            dx = math.sin(rad)
            dy = -math.cos(rad)

            hit_dist = self.RAY_MAX_DIST
            step = 0
            while step < self.RAY_MAX_DIST:
                step += self.RAY_STEP
                sx = int(self.car.x + dx * step)
                sy = int(self.car.y + dy * step)

                if not (0 <= sx < WORLD_WIDTH and 0 <= sy < WORLD_HEIGHT):
                    hit_dist = step
                    break

                if mask.get_at((sx, sy)):
                    hit_dist = step
                    break

            rays[i] = hit_dist / self.RAY_MAX_DIST

        return rays

    def _angle_to_next_checkpoint(self):
        """Return normalized angle to next checkpoint (0.5 = straight ahead)."""
        zones = self.track.checkpoint_zones
        if not zones:
            # Fall back to waypoints
            if not self.track.waypoints:
                return 0.5
            wp = self.track.waypoints[0]
            target = (wp[0], wp[1])
        else:
            idx = self.car.next_checkpoint_index % len(zones)
            zone = zones[idx]
            target = (zone.centerx, zone.centery)

        target_angle = angle_between_points(
            (self.car.x, self.car.y), target
        )
        diff = normalize_angle(target_angle - self.car.angle)
        # Map [-180, 180] to [0, 1] with 0.5 = straight ahead
        return (diff + 180.0) / 360.0

    def _compute_progress(self):
        """
        Compute continuous progress as negative distance to next checkpoint.

        Retorna -dist al centro del checkpoint objetivo. A medida que el auto
        se acerca, el valor sube (se vuelve menos negativo), produciendo un
        delta positivo frame a frame = reward continuo real.
        """
        zones = self.track.checkpoint_zones
        if not zones:
            # Fallback a waypoints si no hay checkpoints manuales
            if not self.track.waypoints:
                return 0.0
            wp = self.track.waypoints[0]
            target_x, target_y = wp[0], wp[1]
        else:
            idx = self.car.next_checkpoint_index % len(zones)
            zone = zones[idx]
            target_x = zone.centerx
            target_y = zone.centery

        dist = math.hypot(target_x - self.car.x, target_y - self.car.y)
        return -dist

    def _calculate_reward(self, hit_wall, crossed_checkpoint, completed_lap):
        """
        Calculate reward for current step.

        Señales diseñadas para evitar colapso de política en mapas estrechos:
        - Progreso continuo amplificado (señal dominante: moverse = bueno)
        - Choque leve (no destruye el incentivo de moverse)
        - Idle penalty (quedarse quieto siempre es peor que chocar)

        Returns:
            (reward, progress_delta) — el delta se usa en step() para
            trackear no_progress_frames.
        """
        reward = 0.0

        # ── Progreso continuo (solo positivo, sin castigar curvas) ──
        current_progress = self._compute_progress()
        delta = current_progress - self._prev_progress
        reward += max(0.0, delta) * 3.0
        self._prev_progress = current_progress

        # ── Bonus por cruzar checkpoint ──
        if crossed_checkpoint:
            reward += 100.0
            # Resetear prev_progress al nuevo objetivo para evitar spike
            # negativo por el salto de distancia al siguiente checkpoint
            self._prev_progress = self._compute_progress()

        # ── Bonus por completar vuelta ──
        if completed_lap:
            reward += 500.0

        # ── Penalización por choque proporcional a velocidad ──
        # Base -1 + componente proporcional: chocar a 500px/s cuesta -6,
        # chocar a 50px/s cuesta -1.5. Enseña a frenar antes de curvas.
        if hit_wall:
            reward -= 1.0
            reward -= abs(self.car.speed) * 0.01

        # ── Penalización por mala alineación con checkpoint ──
        # angle_norm=0.5 = apuntando directo al checkpoint (perfecto)
        # angle_norm=0.0 o 1.0 = apuntando en dirección opuesta (máx error)
        # Corrige arranques en reversa y guía el giro tras choques.
        angle_norm = self._angle_to_next_checkpoint()
        alignment_error = abs(angle_norm - 0.5)
        reward -= alignment_error * 0.5

        # ── Penalización por fuera de pista ──
        if not self.track.is_on_track(self.car.x, self.car.y):
            reward -= 0.5

        # ── Anti-idle: penalización por velocidad casi nula ──
        # Se activa rápido (20 frames = 0.33s) con valor alto para que
        # "no moverse" sea siempre peor que moverse y chocar
        if self.idle_counter > 20:
            reward -= 0.2

        return reward, delta
