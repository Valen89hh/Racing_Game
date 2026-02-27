"""
dedicated_server.py - Servidor dedicado headless para carreras multijugador.

Ejecuta la simulacion del juego sin ventana grafica. Todos los jugadores
se conectan como clientes y reciben el mismo trato (sin ventaja de host).

Uso:
    python main.py --dedicated-server --track my_track.json --port 5555 --bots 1
"""

import sys
import time
import argparse

from settings import NET_DEFAULT_PORT, FIXED_DT
from networking.server import GameServer
from server.room import Room


class DedicatedServer:
    """Servidor dedicado headless."""

    def __init__(self, track_file, port, max_players, bot_count):
        self.track_file = track_file
        self.port = port
        self.max_players = max_players
        self.bot_count = bot_count
        self.running = False

        self.net_server = GameServer(port=port, dedicated=True)
        self.net_server.track_name = track_file
        self.net_server.host_name = "Server"

        self.room = Room(
            self.net_server, track_file, bot_count, max_players)

    def start(self):
        """Inicia el servidor y entra en el main loop."""
        try:
            self.net_server.start()
        except OSError as e:
            print(f"[DEDICATED] Cannot start server: {e}")
            sys.exit(1)

        print(f"[DEDICATED] Server started on port {self.port}")
        print(f"[DEDICATED] Track: {self.track_file}")
        print(f"[DEDICATED] Max players: {self.max_players}, Bots: {self.bot_count}")
        print(f"[DEDICATED] Waiting for players...")

        self.running = True
        self._main_loop()

    def _main_loop(self):
        """Loop principal con accumulator para timing preciso."""
        next_tick_time = time.perf_counter()

        while self.running:
            now = time.perf_counter()

            while now >= next_tick_time:
                try:
                    self.room.tick(FIXED_DT)
                except KeyboardInterrupt:
                    self.running = False
                    break
                except Exception as e:
                    print(f"[DEDICATED] Error in tick: {e}")
                    import traceback
                    traceback.print_exc()

                next_tick_time += FIXED_DT

                # Safety: si caemos >10 ticks atrás, skip ahead
                if time.perf_counter() - next_tick_time > FIXED_DT * 10:
                    print("[DEDICATED] WARNING: Fell behind, skipping ahead")
                    next_tick_time = time.perf_counter()
                    break

            # Sleep corto para no consumir 100% CPU
            remaining = next_tick_time - time.perf_counter()
            if remaining > 0.002:
                time.sleep(0.001)

        self._shutdown()

    def _shutdown(self):
        """Detiene el servidor limpiamente."""
        print("[DEDICATED] Shutting down...")
        self.net_server.stop()


def main():
    """Entry point del servidor dedicado (llamado desde main.py)."""
    parser = argparse.ArgumentParser(description="Dedicated Racing Server")
    parser.add_argument("--track", required=True,
                        help="Track filename (in tracks/ dir)")
    parser.add_argument("--port", type=int, default=NET_DEFAULT_PORT,
                        help=f"UDP port (default: {NET_DEFAULT_PORT})")
    parser.add_argument("--max-players", type=int, default=4,
                        help="Max players (default: 4)")
    parser.add_argument("--bots", type=int, default=1,
                        help="Number of bots (default: 1)")
    args = parser.parse_args()

    server = DedicatedServer(
        track_file=args.track,
        port=args.port,
        max_players=args.max_players,
        bot_count=args.bots,
    )

    try:
        server.start()
    except KeyboardInterrupt:
        server.running = False
