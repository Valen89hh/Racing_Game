"""
main.py - Punto de entrada del juego Arcade Racing 2D.

Ejecutar este archivo para iniciar el juego:
    python main.py

Requisitos:
    - Python 3.10+
    - Pygame 2.x (pip install pygame)
"""

import sys
import os

# Asegurar que el directorio del proyecto esté en el path
# para que los imports funcionen correctamente
if getattr(sys, "frozen", False):
    # PyInstaller frozen exe
    sys.path.insert(0, os.path.dirname(sys.executable))
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Training subprocess mode: headless pygame, run train_ai, exit
if "--train-subprocess" in sys.argv:
    os.environ['SDL_VIDEODRIVER'] = 'dummy'
    import pygame
    pygame.init()
    pygame.display.set_mode((1, 1))
    sys.argv.remove("--train-subprocess")
    from training.train_ai import main as train_main
    train_main()
    sys.exit(0)

from game import Game


def main():
    """Inicializa y ejecuta el juego."""
    game = Game()
    game.run()


if __name__ == "__main__":
    main()
