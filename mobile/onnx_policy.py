"""
onnx_policy.py - Inferencia de la política de bot.

Reemplaza a RLSystem (stable_baselines3 + PyTorch) en cualquier entorno que no
pueda cargar PyTorch (principalmente Android/ARM via Buildozer).

Dos backends, en orden de preferencia:
  1. **onnxruntime** — carga el `.onnx` exportado por `tools/export_ppo_to_onnx.py`.
  2. **numpy puro** — fallback. Carga el `.npz` que también genera el exporter
     (pesos crudos W1/b1/W2/b2/W3/b3) y hace forward pass con 3 matmuls + tanh.
     Útil cuando `onnxruntime` no está disponible (p.ej. si su recipe de p4a
     falla en la build de Android).

Interfaz compatible con RLSystem:
    sys = ONNXPolicy(track, "models/level_3_model.onnx")
    if sys.is_loaded:
        sys.update(car, dt)

La red exportada es 9 → 128 → tanh → 128 → tanh → 4 (≈18k params, ~72 KB).
"""

from __future__ import annotations

import os
import numpy as np

from entities.car import Car
from utils.observation import build_observation, apply_action


class ONNXPolicy:
    """Bot RL con backend onnxruntime preferido y fallback numpy puro."""

    def __init__(self, track, onnx_path: str):
        self.track = track
        self._onnx_path = onnx_path

        # Backend ONNX Runtime (preferido)
        self._session = None
        self._input_name = None
        self._output_name = None

        # Backend numpy (fallback)
        self._weights = None  # tuple (W1, b1, W2, b2, W3, b3) o None

        if not os.path.isfile(onnx_path):
            print(f"[ONNXPolicy] Model not found: {onnx_path}")
            return

        # Intento 1: onnxruntime.
        if self._try_load_onnxruntime(onnx_path):
            return

        # Intento 2: cargar pesos crudos del .npz para inferencia numpy.
        npz_path = onnx_path.replace(".onnx", ".npz")
        if self._try_load_numpy(npz_path):
            return

        print(f"[ONNXPolicy] No backend available for {onnx_path}")

    def _try_load_onnxruntime(self, onnx_path: str) -> bool:
        try:
            import onnxruntime as ort
        except ImportError:
            return False
        try:
            self._session = ort.InferenceSession(
                onnx_path,
                providers=["CPUExecutionProvider"],
            )
            self._input_name = self._session.get_inputs()[0].name
            self._output_name = self._session.get_outputs()[0].name
            print(f"[ONNXPolicy] Loaded (onnxruntime): {onnx_path}")
            return True
        except Exception as e:
            print(f"[ONNXPolicy] onnxruntime load failed: {e}")
            self._session = None
            return False

    def _try_load_numpy(self, npz_path: str) -> bool:
        if not os.path.isfile(npz_path):
            return False
        try:
            data = np.load(npz_path)
            self._weights = (
                data["W1"], data["b1"],
                data["W2"], data["b2"],
                data["W3"], data["b3"],
            )
            print(f"[ONNXPolicy] Loaded (numpy fallback): {npz_path}")
            return True
        except Exception as e:
            print(f"[ONNXPolicy] numpy fallback load failed: {e}")
            self._weights = None
            return False

    @property
    def is_loaded(self) -> bool:
        return self._session is not None or self._weights is not None

    def update(self, car: Car, dt: float, other_cars: list = None):
        """Actualiza el auto controlado. Mismo contrato que RLSystem.update()."""
        if not self.is_loaded:
            return

        car.reset_inputs()
        obs = build_observation(car, self.track)

        try:
            if self._session is not None:
                action = self._infer_onnx(obs)
            else:
                action = self._infer_numpy(obs)
        except Exception:
            return

        apply_action(car, action)

    def _infer_onnx(self, obs: np.ndarray) -> int:
        x = obs.reshape(1, 9)
        logits = self._session.run([self._output_name], {self._input_name: x})[0]
        return int(np.argmax(logits, axis=1)[0])

    def _infer_numpy(self, obs: np.ndarray) -> int:
        # Forward MLP: x → tanh(xW1+b1) → tanh(.W2+b2) → .W3+b3 → argmax
        W1, b1, W2, b2, W3, b3 = self._weights
        h1 = np.tanh(obs @ W1 + b1)
        h2 = np.tanh(h1 @ W2 + b2)
        logits = h2 @ W3 + b3
        return int(np.argmax(logits))
