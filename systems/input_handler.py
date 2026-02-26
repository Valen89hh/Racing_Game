"""
input_handler.py - Sistema de manejo de input.

Traduce pulsaciones de teclado a comandos normalizados para los autos.
Soporta tecla de uso de power-up (Left Shift / F).
"""

import pygame

from entities.car import Car
from settings import PLAYER_CONTROLS


class InputHandler:
    """Maneja el input del jugador y lo traduce a comandos del auto."""

    KEY_MAP = {
        "w": pygame.K_w,
        "s": pygame.K_s,
        "a": pygame.K_a,
        "d": pygame.K_d,
        "up": pygame.K_UP,
        "down": pygame.K_DOWN,
        "left": pygame.K_LEFT,
        "right": pygame.K_RIGHT,
        "space": pygame.K_SPACE,
        "lshift": pygame.K_LSHIFT,
        "rshift": pygame.K_RSHIFT,
    }

    def __init__(self):
        self.control_schemes = {}
        self._load_control_schemes()

    def _load_control_schemes(self):
        """Carga los esquemas de control desde la configuración."""
        for player_id, controls in PLAYER_CONTROLS.items():
            self.control_schemes[player_id] = {
                "up": self.KEY_MAP.get(controls["up"], pygame.K_w),
                "down": self.KEY_MAP.get(controls["down"], pygame.K_s),
                "left": self.KEY_MAP.get(controls["left"], pygame.K_a),
                "right": self.KEY_MAP.get(controls["right"], pygame.K_d),
            }

    def update(self, car: Car, keys: pygame.key.ScancodeWrapper):
        """Actualiza los comandos de input de un auto."""
        car.reset_inputs()

        controls = self.control_schemes.get(car.player_id)
        if controls is None:
            return

        # Aceleración / reversa
        if keys[controls["up"]]:
            car.input_accelerate = 1.0
        elif keys[controls["down"]]:
            car.input_accelerate = -1.0

        # Giro (A+D se cancelan a 0 para permitir drift diagonal)
        if keys[controls["left"]]:
            car.input_turn -= 1.0
        if keys[controls["right"]]:
            car.input_turn += 1.0

        # Freno de mano
        if car.player_id == 0 and keys[pygame.K_SPACE]:
            car.input_brake = True
        elif car.player_id == 1 and keys[pygame.K_RSHIFT]:
            car.input_brake = True

        # Power-up se activa con click izquierdo del mouse (ver game.py)

    def add_player(self, player_id: int, controls: dict):
        """Agrega un esquema de control para un nuevo jugador."""
        self.control_schemes[player_id] = {
            key: self.KEY_MAP.get(value, pygame.K_w)
            for key, value in controls.items()
        }
