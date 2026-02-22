"""
timer.py - Sistema de cronómetro para la carrera.

Gestiona el tiempo transcurrido, tiempos por vuelta y mejor tiempo.
Usa delta time para precisión independiente del framerate.
"""

import pygame


class RaceTimer:
    """Cronómetro de carrera con soporte para tiempos por vuelta."""

    def __init__(self):
        self.total_time = 0.0        # tiempo total transcurrido (segundos)
        self.lap_time = 0.0          # tiempo de la vuelta actual
        self.lap_times = []          # lista de tiempos por vuelta completada
        self.best_lap = None         # mejor tiempo de vuelta
        self.running = False         # si el cronómetro está activo

    def start(self):
        """Inicia o reanuda el cronómetro."""
        self.running = True

    def stop(self):
        """Detiene el cronómetro."""
        self.running = False

    def reset(self):
        """Reinicia todos los tiempos a cero."""
        self.total_time = 0.0
        self.lap_time = 0.0
        self.lap_times.clear()
        self.best_lap = None
        self.running = False

    def update(self, dt: float):
        """
        Actualiza el cronómetro cada frame.

        Args:
            dt: delta time en segundos.
        """
        if not self.running:
            return

        self.total_time += dt
        self.lap_time += dt

    def complete_lap(self) -> float:
        """
        Registra una vuelta completada y reinicia el cronómetro de vuelta.

        Returns:
            El tiempo de la vuelta que acaba de completarse.
        """
        completed_time = self.lap_time
        self.lap_times.append(completed_time)

        # Actualizar mejor vuelta
        if self.best_lap is None or completed_time < self.best_lap:
            self.best_lap = completed_time

        self.lap_time = 0.0
        return completed_time

    @staticmethod
    def format_time(seconds: float) -> str:
        """
        Formatea un tiempo en segundos a formato mm:ss.ms

        Args:
            seconds: tiempo en segundos.

        Returns:
            String formateado como "01:23.456"
        """
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{minutes:02d}:{secs:02d}.{millis:03d}"

    @property
    def current_lap_number(self) -> int:
        """Retorna el número de la vuelta actual (1-indexed)."""
        return len(self.lap_times) + 1

    @property
    def formatted_total(self) -> str:
        """Retorna el tiempo total formateado."""
        return self.format_time(self.total_time)

    @property
    def formatted_lap(self) -> str:
        """Retorna el tiempo de vuelta actual formateado."""
        return self.format_time(self.lap_time)
