"""
train_ai.py - Script CLI para entrenar un modelo PPO en una pista específica.

Uso:
    python -m training.train_ai tracks/mi_pista.json [--timesteps 200000] [--name modelo] [--lr 0.0003]

El modelo entrenado se guarda en models/{track_name}_model.zip
"""

import os
import sys
import json
import time
import argparse

import numpy as np

# Headless pygame — must happen before any pygame import
os.environ['SDL_VIDEODRIVER'] = 'dummy'

import pygame
pygame.init()
pygame.display.set_mode((1, 1))


class JSONProgressCallback:
    """SB3-compatible callback that writes training progress to a JSON file."""

    def __init__(self, json_path, total_timesteps):
        self.json_path = json_path
        self.total_timesteps = total_timesteps
        self.start_time = time.time()
        self.model = None
        self.num_timesteps = 0
        self.n_calls = 0

    def init_callback(self, model):
        self.model = model

    def _on_step(self):
        self.n_calls += 1
        self.num_timesteps = self.model.num_timesteps
        data = {
            "status": "training",
            "timesteps_done": self.num_timesteps,
            "timesteps_total": self.total_timesteps,
            "elapsed_seconds": round(time.time() - self.start_time, 1),
        }
        if len(self.model.ep_info_buffer) > 0:
            data["mean_reward"] = round(
                float(np.mean([ep["r"] for ep in self.model.ep_info_buffer])), 2
            )
            data["episodes_done"] = len(self.model.ep_info_buffer)
        try:
            with open(self.json_path, "w") as f:
                json.dump(data, f)
        except IOError:
            pass
        return True

    def on_step(self):
        return self._on_step()


def _make_sb3_callback(json_callback):
    """Wrap JSONProgressCallback into an SB3 BaseCallback."""
    from stable_baselines3.common.callbacks import BaseCallback

    class _Wrapper(BaseCallback):
        def __init__(self, cb):
            super().__init__()
            self._cb = cb

        def _on_training_start(self):
            self._cb.init_callback(self.model)

        def _on_step(self):
            self._cb.model = self.model
            return self._cb._on_step()

    return _Wrapper(json_callback)


def make_env(track_path: str):
    """Factory function for creating RacingEnv instances."""
    def _init():
        from training.racing_env import RacingEnv
        return RacingEnv(track_path)
    return _init


def main():
    parser = argparse.ArgumentParser(
        description="Train a PPO model for a specific racing track."
    )
    parser.add_argument(
        "track_path",
        help="Path to the track JSON file (e.g. tracks/my_track.json)"
    )
    parser.add_argument(
        "--timesteps", type=int, default=200_000,
        help="Total training timesteps (default: 200000)"
    )
    parser.add_argument(
        "--name", type=str, default=None,
        help="Model name (default: derived from track filename)"
    )
    parser.add_argument(
        "--lr", type=float, default=3e-4,
        help="Learning rate (default: 0.0003)"
    )
    parser.add_argument(
        "--num-envs", type=int, default=4,
        help="Number of parallel environments (default: 4)"
    )
    parser.add_argument(
        "--json-progress", type=str, default=None,
        help="Path to write JSON progress updates (for GUI integration)"
    )
    args = parser.parse_args()

    # Resolve track path
    track_path = args.track_path
    if not os.path.isabs(track_path):
        track_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            track_path
        )

    if not os.path.exists(track_path):
        print(f"Error: Track file not found: {track_path}")
        sys.exit(1)

    # Model name
    track_basename = os.path.splitext(os.path.basename(track_path))[0]
    model_name = args.name or track_basename

    # Output path
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    models_dir = os.path.join(project_root, "models")
    os.makedirs(models_dir, exist_ok=True)
    model_path = os.path.join(models_dir, f"{model_name}_model")

    json_progress = args.json_progress
    quiet = json_progress is not None

    if not quiet:
        print(f"=== RL Training ===")
        print(f"Track: {track_path}")
        print(f"Model: {model_name}")
        print(f"Timesteps: {args.timesteps}")
        print(f"Learning rate: {args.lr}")
        print(f"Parallel envs: {args.num_envs}")
        print()

    # Import RL libraries
    try:
        from stable_baselines3 import PPO
        from stable_baselines3.common.vec_env import DummyVecEnv
    except ImportError:
        msg = "stable-baselines3 not installed. Run: pip install gymnasium stable-baselines3"
        if json_progress:
            with open(json_progress, "w") as f:
                json.dump({"status": "error", "message": msg}, f)
        else:
            print(f"Error: {msg}")
        sys.exit(1)

    # Create vectorized environment
    env = DummyVecEnv([make_env(track_path) for _ in range(args.num_envs)])

    # Create PPO model
    model = PPO(
        "MlpPolicy",
        env,
        learning_rate=args.lr,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,
        verbose=0 if quiet else 1,
        policy_kwargs=dict(
            net_arch=dict(pi=[128, 128], vf=[128, 128])
        ),
    )

    # Setup callback for JSON progress
    callback = None
    if json_progress:
        json_cb = JSONProgressCallback(json_progress, args.timesteps)
        callback = _make_sb3_callback(json_cb)

    # Train
    if not quiet:
        print(f"\nStarting training for {args.timesteps} timesteps...")
    try:
        model.learn(
            total_timesteps=args.timesteps,
            progress_bar=not quiet,
            callback=callback,
        )
    except KeyboardInterrupt:
        if not quiet:
            print("\nTraining interrupted by user.")
    except Exception as e:
        if json_progress:
            with open(json_progress, "w") as f:
                json.dump({"status": "error", "message": str(e)}, f)
            env.close()
            sys.exit(1)
        raise

    # Save model
    model.save(model_path)
    if not quiet:
        print(f"\nModel saved to: {model_path}.zip")

    # Write final status
    if json_progress:
        with open(json_progress, "w") as f:
            json.dump({
                "status": "done",
                "model_path": f"{model_path}.zip",
                "timesteps_done": args.timesteps,
                "timesteps_total": args.timesteps,
            }, f)

    env.close()


if __name__ == "__main__":
    main()
