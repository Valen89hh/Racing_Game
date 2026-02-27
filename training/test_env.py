"""
test_env.py - Prueba controlada del entorno de entrenamiento.

Fuerza acción=0 (acelerar) durante 120 frames y verifica que:
1. La velocidad aumente progresivamente
2. La posición cambie
3. La física funcione correctamente

Uso: python -m training.test_env tracks/<pista>.json
"""

import os
import sys

# Headless pygame
os.environ['SDL_VIDEODRIVER'] = 'dummy'

import pygame
pygame.init()
pygame.display.set_mode((1, 1))

# Agregar directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from training.racing_env import RacingEnv


def test_acceleration(track_path: str):
    """Fuerza acción=0 durante 120 frames e imprime diagnóstico."""
    print(f"=== Test de Aceleración ===")
    print(f"Track: {track_path}")
    print()

    env = RacingEnv(track_path)
    obs, info = env.reset()

    print(f"Start position: ({env.car.x:.1f}, {env.car.y:.1f})")
    print(f"Start angle: {env.car.angle:.1f}°")
    print(f"Start speed: {env.car.speed:.1f}")
    print(f"On track: {env.track.is_on_track(env.car.x, env.car.y)}")
    print(f"Checkpoints: {len(env.track.checkpoint_zones)}")
    print(f"Waypoints: {len(env.track.waypoints)}")
    print()

    # Test: colisión inmediata al inicio
    initial_collision = env.collision_system.check_track_collision(env.car)
    print(f"Collision at start: {initial_collision}")
    print(f"Collision radius: {env.car.collision_radius}")
    print()

    print(f"{'Frame':>5} {'Action':>6} {'Speed':>8} {'X':>8} {'Y':>8} "
          f"{'Wall':>5} {'Term':>5} {'Trunc':>5} {'Reward':>8}")
    print("-" * 75)

    total_reward = 0
    for frame in range(120):
        action = 0  # Siempre acelerar
        obs, reward, terminated, truncated, info = env.step(action)
        total_reward += reward

        hit = info.get("hit_wall", False)

        if frame < 20 or frame % 10 == 0 or terminated or truncated:
            print(f"{frame:5d} {action:6d} {env.car.speed:8.1f} "
                  f"{env.car.x:8.1f} {env.car.y:8.1f} "
                  f"{str(hit):>5} {str(terminated):>5} {str(truncated):>5} "
                  f"{reward:8.2f}")

        if terminated or truncated:
            print(f"\n>>> Episodio terminó en frame {frame}")
            print(f"    terminated={terminated}, truncated={truncated}")
            print(f"    Stall frames: {env.stall_frames}")
            print(f"    No-progress frames: {env.no_progress_frames}")
            break

    print(f"\n=== Resultados ===")
    print(f"Speed final: {env.car.speed:.1f}")
    print(f"Posición final: ({env.car.x:.1f}, {env.car.y:.1f})")
    print(f"Reward total: {total_reward:.2f}")
    print(f"Laps: {env.car.laps}")

    if env.car.speed > 50:
        print("\n✓ PASS: El auto acelera correctamente")
    elif env.car.speed > 0:
        print("\n~ PARCIAL: El auto acelera pero lentamente (posible fricción o choques)")
    else:
        print("\n✗ FAIL: El auto NO acelera — revisar física")

    env.close()


def test_all_actions(track_path: str):
    """Prueba cada acción individualmente durante 30 frames."""
    print(f"\n=== Test de Todas las Acciones ===\n")
    action_names = {0: "Acelerar", 1: "Izq+Acel", 2: "Der+Acel", 3: "Frenar"}

    env = RacingEnv(track_path)

    for action_id, name in action_names.items():
        obs, info = env.reset()
        start_x, start_y = env.car.x, env.car.y

        for _ in range(30):
            obs, reward, terminated, truncated, info = env.step(action_id)
            if terminated or truncated:
                break

        dx = env.car.x - start_x
        dy = env.car.y - start_y
        print(f"Action {action_id} ({name:>10}): "
              f"speed={env.car.speed:7.1f}  "
              f"moved=({dx:7.1f}, {dy:7.1f})  "
              f"angle={env.car.angle:6.1f}°")

    env.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m training.test_env tracks/<pista>.json")
        sys.exit(1)

    track_path = sys.argv[1]
    if not os.path.isabs(track_path):
        track_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            track_path
        )

    test_acceleration(track_path)
    test_all_actions(track_path)
