"""
race_progress.py - Sistema profesional de progreso y posiciones de carrera.

Calcula un progress_score continuo para cada auto basado en vuelta,
checkpoint y distancia al siguiente checkpoint, permitiendo un ranking
preciso incluso cuando dos autos están en la misma vuelta y checkpoint.
"""

from utils.helpers import distance


class CarProgress:
    """Datos de progreso de un auto individual."""
    __slots__ = (
        'player_id', 'lap', 'checkpoint_index',
        'progress_score', 'finished', 'finish_time',
    )

    def __init__(self, player_id: int):
        self.player_id = player_id
        self.lap = 0
        self.checkpoint_index = 0
        self.progress_score = 0.0
        self.finished = False
        self.finish_time = 0.0


class RaceProgressTracker:
    """
    Motor de ranking que mantiene un score continuo para cada auto.

    Fórmula (next_checkpoint_index es 0-based):
        score = (lap * 100_000) + (next_checkpoint_index * 1000) + bonus
    Para autos finalizados:
        score = 999_999_999 - finish_time * 100  (primero en terminar = mayor score)
    """

    def __init__(self, checkpoints: list, finish_line_center: tuple):
        self.checkpoints = checkpoints
        self.num_checkpoints = len(checkpoints)
        self.finish_line_center = finish_line_center
        self._progress = {}  # player_id -> CarProgress

        # Pre-calcular distancias máximas entre checkpoints consecutivos
        self._max_distances = []
        for i in range(self.num_checkpoints):
            if i + 1 < self.num_checkpoints:
                next_cp = checkpoints[i + 1]
            else:
                next_cp = checkpoints[0]  # wrap around to first checkpoint
            d = distance(checkpoints[i], next_cp)
            self._max_distances.append(max(d, 1.0))

    def register_car(self, player_id: int):
        """Registra un auto para el tracking."""
        self._progress[player_id] = CarProgress(player_id)

    def update(self, car):
        """
        Sincroniza datos del auto y recalcula progress_score.

        Args:
            car: instancia de Car con atributos laps, next_checkpoint_index,
                 finished, finish_time, x, y.
        """
        prog = self._progress.get(car.player_id)
        if prog is None:
            return

        prog.lap = car.laps
        prog.checkpoint_index = car.next_checkpoint_index
        prog.finished = car.finished
        prog.finish_time = car.finish_time

        if prog.finished:
            prog.progress_score = 999_999_999.0 - prog.finish_time * 100.0
            return

        # Base score: vuelta + checkpoint
        base = (prog.lap * 100_000) + (prog.checkpoint_index * 1000)

        # Bonus por distancia al siguiente checkpoint (0-1000)
        # next_checkpoint_index apunta al checkpoint que el auto necesita alcanzar
        car_pos = (car.x, car.y)
        if self.num_checkpoints > 0 and prog.checkpoint_index < self.num_checkpoints:
            target_cp = self.checkpoints[prog.checkpoint_index]
            # Use the distance from previous checkpoint (or start) as max
            if prog.checkpoint_index > 0:
                max_d = self._max_distances[prog.checkpoint_index - 1]
            else:
                max_d = self._max_distances[-1] if self._max_distances else 1.0
        else:
            target_cp = self.finish_line_center
            max_d = 1.0

        dist_to_next = distance(car_pos, target_cp)
        dist_normalized = min(1000.0, (dist_to_next / max_d) * 1000.0)
        bonus = 1000.0 - dist_normalized

        prog.progress_score = base + bonus

    def get_position(self, player_id: int) -> int:
        """Retorna la posición 1-indexed del auto en la carrera."""
        target = self._progress.get(player_id)
        if target is None:
            return 1

        position = 1
        for pid, prog in self._progress.items():
            if pid == player_id:
                continue
            if prog.progress_score > target.progress_score:
                position += 1

        return position

    def get_all_rankings(self) -> list:
        """
        Retorna todos los autos ordenados por posición.

        Returns:
            Lista de tuplas (position, player_id, score) ordenadas.
        """
        sorted_progs = sorted(
            self._progress.values(),
            key=lambda p: p.progress_score,
            reverse=True,
        )
        return [
            (i + 1, p.player_id, p.progress_score)
            for i, p in enumerate(sorted_progs)
        ]
