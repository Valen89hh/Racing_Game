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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game import Game


def main():
    """Inicializa y ejecuta el juego."""
    game = Game()
    game.run()


if __name__ == "__main__":
    main()
