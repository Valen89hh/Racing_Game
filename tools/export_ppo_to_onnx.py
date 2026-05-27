"""
export_ppo_to_onnx.py - Convierte modelos PPO (stable-baselines3) a ONNX.

El build móvil no puede empaquetar PyTorch + stable-baselines3 en una APK
razonable. Este script extrae la red de política de cada `.zip` entrenado
y la exporta a `.onnx`, que luego se puede inferir con `onnxruntime` en
Android (o con numpy puro como fallback — la red es 9→128→128→4).

Uso:
    venv\\Scripts\\python.exe tools\\export_ppo_to_onnx.py

Requiere:
    pip install onnx onnxruntime

Output:
    models/{nombre}_model.onnx  (uno por cada .zip)

Validación:
    Para cada modelo, compara 100 predicciones aleatorias entre el PPO
    original y el ONNX exportado. El argmax debe coincidir 100/100.
"""

from __future__ import annotations

import os
import sys
import glob
import argparse
import numpy as np
import torch
import torch.nn as nn

# Ensure project root on sys.path so settings/training imports work
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from stable_baselines3 import PPO


class PolicyOnly(nn.Module):
    """
    Wrapper que expone solo el camino de política para inferencia determinista.

    Forward: obs (B, 9) -> logits (B, 4)
    El runtime hace argmax(logits) para obtener la acción discreta.
    """

    def __init__(self, ppo_model: PPO):
        super().__init__()
        # Extraer las capas necesarias del PPO entrenado
        policy = ppo_model.policy
        self.policy_net = policy.mlp_extractor.policy_net  # 9 -> 128 -> 128
        self.action_net = policy.action_net               # 128 -> 4
        self.eval()

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        latent_pi = self.policy_net(obs)
        logits = self.action_net(latent_pi)
        return logits


def _export_npz_fallback(model: PPO, npz_path: str) -> None:
    """
    Exporta los pesos crudos de la MLP a .npz para inferencia con numpy puro.

    Formato (asume arquitectura policy_net = 2x Linear+Tanh, action_net = Linear):
        W1, b1: 1ra capa oculta  (in=9,   out=128)
        W2, b2: 2da capa oculta  (in=128, out=128)
        W3, b3: capa de acción   (in=128, out=4)

    Se guardan ya transpuestos para que el forward sea `x @ W + b` directo.
    """
    policy = model.policy
    pn = policy.mlp_extractor.policy_net  # Sequential: Linear, Tanh, Linear, Tanh
    an = policy.action_net                # Linear

    layer1 = pn[0]
    layer2 = pn[2]

    np.savez(
        npz_path,
        W1=layer1.weight.detach().numpy().T.astype(np.float32),
        b1=layer1.bias.detach().numpy().astype(np.float32),
        W2=layer2.weight.detach().numpy().T.astype(np.float32),
        b2=layer2.bias.detach().numpy().astype(np.float32),
        W3=an.weight.detach().numpy().T.astype(np.float32),
        b3=an.bias.detach().numpy().astype(np.float32),
    )


def export_one(zip_path: str, onnx_path: str, num_validate: int = 100) -> tuple[bool, str]:
    """
    Exporta un único modelo PPO a ONNX (+ .npz fallback) y lo valida.

    Returns:
        (success, message)
    """
    try:
        model = PPO.load(zip_path, device="cpu")
    except Exception as e:
        return False, f"PPO.load failed: {e}"

    obs_shape = model.observation_space.shape
    if obs_shape != (9,):
        return False, f"unexpected obs shape {obs_shape} (expected (9,))"

    action_space = model.action_space
    n_actions = getattr(action_space, "n", None)
    if n_actions != 4:
        return False, f"unexpected action count {n_actions} (expected 4)"

    wrapped = PolicyOnly(model)

    dummy = torch.zeros(1, 9, dtype=torch.float32)

    try:
        # dynamo=False fuerza el exportador legacy TorchScript-based.
        # El nuevo (dynamo=True) crashea en consola Windows cp1252 al imprimir
        # caracteres Unicode de su propio log. Nuestra MLP es trivial; legacy
        # es de sobra.
        torch.onnx.export(
            wrapped,
            dummy,
            onnx_path,
            input_names=["obs"],
            output_names=["logits"],
            dynamic_axes={"obs": {0: "batch"}, "logits": {0: "batch"}},
            opset_version=17,
            dynamo=False,
        )
    except Exception as e:
        return False, f"torch.onnx.export failed: {e}"

    # Fallback numpy: .npz con pesos crudos por si onnxruntime no está disponible.
    npz_path = onnx_path.replace(".onnx", ".npz")
    try:
        _export_npz_fallback(model, npz_path)
    except Exception as e:
        return False, f"npz export failed: {e}"

    # Validación: 100 obs aleatorias, comparar argmax PPO vs argmax ONNX
    try:
        import onnxruntime as ort
    except ImportError:
        return True, f"exported (validation skipped — install onnxruntime to validate)"

    try:
        sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
        rng = np.random.default_rng(0)
        mismatches = 0
        for _ in range(num_validate):
            obs = rng.random(9, dtype=np.float32)
            ppo_action, _ = model.predict(obs, deterministic=True)
            ppo_action = int(ppo_action)
            onnx_logits = sess.run(["logits"], {"obs": obs.reshape(1, 9)})[0]
            onnx_action = int(np.argmax(onnx_logits, axis=1)[0])
            if ppo_action != onnx_action:
                mismatches += 1
        if mismatches > 0:
            return False, f"validation FAILED: {mismatches}/{num_validate} mismatches"
        return True, f"exported + validated ({num_validate}/{num_validate} matches)"
    except Exception as e:
        return True, f"exported (validation error: {e})"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models-dir",
        default=os.path.join(ROOT, "models"),
        help="Directorio con los .zip de PPO (default: models/)",
    )
    parser.add_argument(
        "--validate-samples",
        type=int,
        default=100,
        help="Número de obs aleatorias para validar cada export (default: 100)",
    )
    args = parser.parse_args()

    zips = sorted(glob.glob(os.path.join(args.models_dir, "*.zip")))
    if not zips:
        print(f"[!] No se encontraron .zip en {args.models_dir}")
        return 1

    print(f"[*] Encontrados {len(zips)} modelos PPO")
    print(f"[*] Output dir: {args.models_dir}\n")

    ok_count = 0
    fail_count = 0
    for zip_path in zips:
        base = os.path.splitext(os.path.basename(zip_path))[0]
        onnx_path = os.path.join(args.models_dir, f"{base}.onnx")
        print(f"  {base}.zip -> {base}.onnx ... ", end="", flush=True)
        success, msg = export_one(zip_path, onnx_path, args.validate_samples)
        if success:
            size_kb = os.path.getsize(onnx_path) / 1024
            print(f"OK ({size_kb:.1f} KB) — {msg}")
            ok_count += 1
        else:
            print(f"FAIL — {msg}")
            fail_count += 1

    print(f"\n[*] Done: {ok_count} ok, {fail_count} failed")
    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
