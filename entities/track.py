"""
track.py - Circuito de carreras grande y complejo.

El circuito se construye a partir de una lista de puntos de control (centerline)
que se suavizan con el algoritmo de Chaikin para generar curvas orgánicas.
Los bordes interno y externo se generan desplazando la centerline perpendicular-
mente a la dirección de la pista.

El mapa es mayor que la pantalla (WORLD_WIDTH x WORLD_HEIGHT), por lo que
requiere una cámara para visualizarse.
"""

import pygame
import math

from settings import (
    WORLD_WIDTH, WORLD_HEIGHT, SCREEN_WIDTH, SCREEN_HEIGHT,
    COLOR_ASPHALT, COLOR_ASPHALT_DARK, COLOR_GRASS, COLOR_GRASS_LIGHT,
    COLOR_CURB_RED, COLOR_CURB_WHITE, COLOR_WHITE, COLOR_YELLOW,
    TRACK_HALF_WIDTH, TRACK_BORDER_THICKNESS,
    MINIMAP_SCALE, MINIMAP_MARGIN, COLOR_MINIMAP_BG,
)


class Track:
    """
    Circuito de carreras definido por una centerline suavizada.

    Proceso de generación:
    1. Puntos de control manuales (diseño del circuito).
    2. Suavizado Chaikin (3 iteraciones → curvas orgánicas).
    3. Offset perpendicular para generar bordes internos y externos.
    4. Pre-renderizado en una superficie grande.
    5. Máscara de colisión binaria.
    6. Minimapa pre-renderizado.
    """

    def __init__(self):
        # ── Paso 1: Puntos de control del circuito ──
        # Diseño inspirado en circuitos reales: rectas largas, curvas cerradas,
        # S-curves y chicanas. Sentido horario.
        control_points = [
            # Start/finish straight (arriba, hacia la derecha)
            (550, 500),  (850, 500),  (1150, 500),  (1500, 500),
            (1800, 500),

            # Curva 1 — sweeper derecha bajando al sureste
            (2050, 530),  (2250, 620),  (2400, 780),  (2480, 980),

            # Recta descendente
            (2500, 1200),  (2480, 1400),

            # Curva 2 — hairpin derecho
            (2520, 1560),  (2640, 1680),  (2820, 1720),
            (2980, 1660),  (3060, 1520),  (3060, 1360),

            # S-curves
            (3020, 1200),  (3080, 1050),  (3200, 940),
            (3150, 800),  (3020, 740),  (2880, 820),

            # Recta larga hacia el suroeste
            (2760, 960),  (2580, 1140),  (2340, 1380),
            (2080, 1620),  (1820, 1800),

            # Curva 3 — amplia izquierda al oeste
            (1540, 1900),  (1260, 1920),  (1020, 1840),
            (840, 1700),

            # Recta al noroeste
            (740, 1500),  (700, 1300),

            # Curva 4 — derecha subiendo
            (660, 1100),  (580, 940),  (520, 800),

            # Chicana final antes de la recta de meta
            (500, 700),  (520, 620),
        ]

        # ── Paso 2: Suavizar con Chaikin ──
        self.centerline = self._chaikin_smooth(control_points, iterations=3)
        self.num_points = len(self.centerline)

        # ── Paso 3: Generar bordes por offset perpendicular ──
        # Para un circuito horario (CW) en coordenadas de pantalla (y+ = abajo),
        # la normal perpendicular derecha apunta HACIA ADENTRO del circuito.
        # Por tanto:  offset negativo = outer (afuera), offset positivo = inner (adentro).
        self.outer_boundary = self._offset_path(self.centerline, -TRACK_HALF_WIDTH)
        self.inner_boundary = self._offset_path(self.centerline, TRACK_HALF_WIDTH)

        # ── Waypoints para la IA (cada N puntos de la centerline) ──
        step = max(1, self.num_points // 60)
        self.waypoints = [self.centerline[i] for i in range(0, self.num_points, step)]

        # ── Checkpoints (6, distribuidos equitativamente) ──
        cp_step = self.num_points // 6
        self.checkpoints = [self.centerline[i * cp_step] for i in range(6)]
        self.num_checkpoints = len(self.checkpoints)

        # ── Línea de meta ──
        # Perpendicular a la centerline en el punto 0
        p0 = self.centerline[0]
        p1 = self.centerline[1]
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        length = math.hypot(dx, dy)
        if length > 0:
            nx, ny = -dy / length, dx / length
        else:
            nx, ny = 0, 1
        hw = TRACK_HALF_WIDTH - 5
        self.finish_line = (
            (p0[0] + nx * hw, p0[1] + ny * hw),
            (p0[0] - nx * hw, p0[1] - ny * hw),
        )

        # ── Posiciones de inicio ──
        # Calculamos el ángulo a partir de la tangente local de la centerline
        # en la zona de la meta (los últimos puntos antes de cerrar el loop).
        idx_p1 = self.num_points - 4   # posición del auto 1
        idx_p2 = self.num_points - 10  # posición del auto 2 (más atrás)

        # Tangente local: dirección promedio en la zona de inicio
        p_back = self.centerline[(idx_p1 - 3) % self.num_points]
        p_fwd  = self.centerline[(idx_p1 + 3) % self.num_points]
        tdx = p_fwd[0] - p_back[0]
        tdy = p_fwd[1] - p_back[1]
        start_angle = math.degrees(math.atan2(tdx, -tdy)) % 360

        # Perpendicular de la tangente para colocar autos lado a lado
        tlen = math.hypot(tdx, tdy)
        if tlen > 0:
            perp_x = -tdy / tlen   # perpendicular apuntando a la derecha
            perp_y =  tdx / tlen
        else:
            perp_x, perp_y = 0, 1

        lateral = 22  # píxeles de separación lateral
        c1 = self.centerline[idx_p1]
        c2 = self.centerline[idx_p2]
        self.start_positions = [
            (c1[0] + perp_x * lateral, c1[1] + perp_y * lateral, start_angle),
            (c2[0] - perp_x * lateral, c2[1] - perp_y * lateral, start_angle),
        ]

        # ── Puntos de spawn de power-ups (distribuidos por la pista) ──
        pu_step = self.num_points // 8
        self.powerup_spawn_points = [
            self.centerline[pu_step * i] for i in range(1, 8)
        ]

        # ── Pre-render ──
        self.track_surface = self._render_track()
        self.boundary_mask, self.boundary_surface = self._create_boundary_mask()
        self.minimap_surface = self._render_minimap()

    # ────────────────────────────────────────────────────
    # GENERACIÓN DE GEOMETRÍA
    # ────────────────────────────────────────────────────

    @staticmethod
    def _chaikin_smooth(points: list[tuple[float, float]],
                        iterations: int = 3) -> list[tuple[float, float]]:
        """
        Suaviza una lista de puntos cerrada con el algoritmo de Chaikin.

        En cada iteración, cada segmento P0→P1 se reemplaza por dos puntos:
            Q = 0.75·P0 + 0.25·P1
            R = 0.25·P0 + 0.75·P1

        Esto converge a una B-spline cuadrática tras varias iteraciones,
        generando curvas suaves y orgánicas.

        Args:
            points: lista de puntos de control (polígono cerrado).
            iterations: número de pasadas de suavizado.

        Returns:
            Lista de puntos suavizados.
        """
        pts = list(points)
        for _ in range(iterations):
            new_pts = []
            n = len(pts)
            for i in range(n):
                p0 = pts[i]
                p1 = pts[(i + 1) % n]
                q = (0.75 * p0[0] + 0.25 * p1[0],
                     0.75 * p0[1] + 0.25 * p1[1])
                r = (0.25 * p0[0] + 0.75 * p1[0],
                     0.25 * p0[1] + 0.75 * p1[1])
                new_pts.append(q)
                new_pts.append(r)
            pts = new_pts
        return pts

    def _offset_path(self, centerline: list[tuple[float, float]],
                     offset_dist: float) -> list[tuple[float, float]]:
        """
        Genera un camino paralelo a la centerline desplazando cada punto
        perpendicularmente a la dirección local de la pista.

        En cada punto se calcula la dirección promediando los segmentos
        anterior y siguiente, luego se desplaza perpendicularmente.

        Args:
            centerline: lista de puntos del centro de la pista.
            offset_dist: distancia de desplazamiento (positivo = derecha).

        Returns:
            Lista de puntos del camino desplazado.
        """
        result = []
        n = len(centerline)
        for i in range(n):
            p_prev = centerline[(i - 1) % n]
            p_next = centerline[(i + 1) % n]

            dx = p_next[0] - p_prev[0]
            dy = p_next[1] - p_prev[1]
            length = math.hypot(dx, dy)
            if length < 0.001:
                result.append(centerline[i])
                continue

            # Normal perpendicular (apunta a la derecha de la dirección)
            nx = -dy / length
            ny = dx / length

            ox = centerline[i][0] + nx * offset_dist
            oy = centerline[i][1] + ny * offset_dist
            result.append((ox, oy))

        return result

    # ────────────────────────────────────────────────────
    # RENDERIZADO
    # ────────────────────────────────────────────────────

    def _render_track(self) -> pygame.Surface:
        """
        Pre-renderiza el circuito completo en una superficie del tamaño del mundo.

        Usa el método de "tubo de círculos" en lugar de polygon fill para
        evitar artefactos cuando el circuito se cruza consigo mismo
        (hairpins, S-curves).  Los círculos cubren la centerline con radio
        TRACK_HALF_WIDTH, garantizando cobertura uniforme.
        """
        surface = pygame.Surface((WORLD_WIDTH, WORLD_HEIGHT))

        # Fondo de césped con patrón de franjas
        surface.fill(COLOR_GRASS)
        stripe_width = 60
        for x in range(0, WORLD_WIDTH, stripe_width * 2):
            pygame.draw.rect(surface, COLOR_GRASS_LIGHT,
                             (x, 0, stripe_width, WORLD_HEIGHT))

        # Asfalto: dibujar círculos a lo largo de la centerline.
        # Los puntos están separados ~14px, el radio es 75px, por lo que
        # los círculos se solapan ampliamente → cobertura sin huecos.
        hw = TRACK_HALF_WIDTH
        for p in self.centerline:
            pygame.draw.circle(surface, COLOR_ASPHALT,
                               (int(p[0]), int(p[1])), hw)

        # Línea central punteada
        for i in range(0, self.num_points, 4):
            if i % 8 < 4:
                p1 = self.centerline[i]
                p2 = self.centerline[(i + 1) % self.num_points]
                pygame.draw.line(surface, COLOR_ASPHALT_DARK,
                                 (int(p1[0]), int(p1[1])),
                                 (int(p2[0]), int(p2[1])), 2)

        # Bordillos exteriores e interiores (siguen siendo polilíneas)
        self._draw_curbs(surface, self.outer_boundary)
        self._draw_curbs(surface, self.inner_boundary)

        # Bordes blancos
        self._draw_polyline(surface, self.outer_boundary, COLOR_WHITE,
                            TRACK_BORDER_THICKNESS)
        self._draw_polyline(surface, self.inner_boundary, COLOR_WHITE,
                            TRACK_BORDER_THICKNESS)

        # Línea de meta (damero)
        self._draw_finish_line(surface)

        return surface

    def _draw_curbs(self, surface: pygame.Surface,
                    boundary: list[tuple[float, float]]):
        """Dibuja bordillos alternando rojo/blanco a lo largo de un borde."""
        n = len(boundary)
        for i in range(0, n, 2):
            p1 = boundary[i]
            p2 = boundary[(i + 1) % n]
            color = COLOR_CURB_RED if (i // 2) % 2 == 0 else COLOR_CURB_WHITE
            pygame.draw.line(surface, color,
                             (int(p1[0]), int(p1[1])),
                             (int(p2[0]), int(p2[1])), 5)

    @staticmethod
    def _draw_polyline(surface: pygame.Surface,
                       points: list[tuple[float, float]],
                       color: tuple, width: int):
        """Dibuja una polilínea cerrada punto a punto."""
        n = len(points)
        int_points = [(int(p[0]), int(p[1])) for p in points]
        for i in range(n):
            pygame.draw.line(surface, color,
                             int_points[i], int_points[(i + 1) % n], width)

    def _draw_finish_line(self, surface: pygame.Surface):
        """Dibuja la línea de meta con patrón de damero."""
        sx, sy = self.finish_line[0]
        ex, ey = self.finish_line[1]

        dx = ex - sx
        dy = ey - sy
        length = math.hypot(dx, dy)
        if length < 1:
            return

        num_squares = 10
        sq_len = length / num_squares
        ux, uy = dx / length, dy / length
        # Perpendicular para el ancho del damero
        px, py = -uy * 12, ux * 12

        for i in range(num_squares):
            x0 = sx + ux * sq_len * i
            y0 = sy + uy * sq_len * i
            x1 = x0 + ux * sq_len
            y1 = y0 + uy * sq_len

            for side in range(2):
                color = COLOR_WHITE if (i + side) % 2 == 0 else (20, 20, 20)
                mult = side  # 0 o 1
                poly = [
                    (x0 + px * mult,       y0 + py * mult),
                    (x1 + px * mult,       y1 + py * mult),
                    (x1 + px * (mult + 1), y1 + py * (mult + 1)),
                    (x0 + px * (mult + 1), y0 + py * (mult + 1)),
                ]
                int_poly = [(int(p[0]), int(p[1])) for p in poly]
                pygame.draw.polygon(surface, color, int_poly)

    # ────────────────────────────────────────────────────
    # COLISIONES
    # ────────────────────────────────────────────────────

    def _create_boundary_mask(self) -> tuple[pygame.mask.Mask, pygame.Surface]:
        """
        Crea la máscara de colisión para los límites de la pista.

        Usa el método de "tubo de círculos" a lo largo de la centerline:
        dibuja círculos negros (libre) de radio TRACK_HALF_WIDTH en cada
        punto de la centerline, sobre un fondo rojo (colisión).

        Este método es robusto contra polígonos auto-intersectantes que
        surgen en curvas cerradas y S-curves donde la pista se acerca
        a sí misma.

          Negro (0,0,0) + colorkey = libre (sin colisión).
          Rojo  (255,0,0) = sólido = colisión.
        """
        surface = pygame.Surface((WORLD_WIDTH, WORLD_HEIGHT))
        surface.set_colorkey((0, 0, 0))

        # Todo es colisión
        surface.fill((255, 0, 0))

        # Liberar la pista: círculos de radio TRACK_HALF_WIDTH en la centerline
        hw = TRACK_HALF_WIDTH
        for p in self.centerline:
            pygame.draw.circle(surface, (0, 0, 0),
                               (int(p[0]), int(p[1])), hw)

        mask = pygame.mask.from_surface(surface)
        return mask, surface

    def is_on_track(self, x: float, y: float) -> bool:
        """Verifica si un punto está dentro de la pista."""
        ix, iy = int(x), int(y)
        if 0 <= ix < WORLD_WIDTH and 0 <= iy < WORLD_HEIGHT:
            return not self.boundary_mask.get_at((ix, iy))
        return False

    def check_car_collision(self, car_mask: pygame.mask.Mask,
                            car_rect: pygame.Rect) -> bool:
        """Verifica si el auto colisiona con los límites de la pista."""
        offset = (car_rect.x, car_rect.y)
        return self.boundary_mask.overlap(car_mask, offset) is not None

    def check_finish_line_cross(self, old_x: float, old_y: float,
                                new_x: float, new_y: float) -> bool:
        """Detecta si el auto cruzó la línea de meta entre dos frames."""
        fx1, fy1 = self.finish_line[0]
        fx2, fy2 = self.finish_line[1]
        return self._segments_intersect(
            old_x, old_y, new_x, new_y,
            fx1, fy1, fx2, fy2,
        )

    @staticmethod
    def _segments_intersect(x1, y1, x2, y2, x3, y3, x4, y4) -> bool:
        """Verifica intersección entre dos segmentos de línea."""
        def cross(ox, oy, ax, ay, bx, by):
            return (ax - ox) * (by - oy) - (ay - oy) * (bx - ox)

        d1 = cross(x3, y3, x4, y4, x1, y1)
        d2 = cross(x3, y3, x4, y4, x2, y2)
        d3 = cross(x1, y1, x2, y2, x3, y3)
        d4 = cross(x1, y1, x2, y2, x4, y4)

        if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
           ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
            return True
        return False

    # ────────────────────────────────────────────────────
    # MINIMAPA
    # ────────────────────────────────────────────────────

    def _render_minimap(self) -> pygame.Surface:
        """
        Pre-renderiza el minimapa: una versión pequeña del circuito.

        Returns:
            Surface con el minimapa (fondo transparente).
        """
        w = int(WORLD_WIDTH * MINIMAP_SCALE)
        h = int(WORLD_HEIGHT * MINIMAP_SCALE)
        surface = pygame.Surface((w + 10, h + 10), pygame.SRCALPHA)
        surface.fill(COLOR_MINIMAP_BG)

        # Dibujar contorno de la pista
        s = MINIMAP_SCALE
        outer_pts = [(int(p[0] * s) + 5, int(p[1] * s) + 5)
                     for p in self.outer_boundary]
        inner_pts = [(int(p[0] * s) + 5, int(p[1] * s) + 5)
                     for p in self.inner_boundary]

        # Rellenar pista (outer lleno, inner encima para el hueco)
        pygame.draw.polygon(surface, (70, 70, 70), outer_pts)
        pygame.draw.polygon(surface, (40, 40, 40), inner_pts)

        # Bordes
        pygame.draw.lines(surface, COLOR_WHITE, True, outer_pts, 1)
        pygame.draw.lines(surface, COLOR_WHITE, True, inner_pts, 1)

        return surface

    def get_minimap_pos(self, world_x: float, world_y: float) -> tuple[int, int]:
        """Convierte coordenadas del mundo a coordenadas del minimapa."""
        return (int(world_x * MINIMAP_SCALE) + 5,
                int(world_y * MINIMAP_SCALE) + 5)

    # ────────────────────────────────────────────────────
    # DIBUJADO
    # ────────────────────────────────────────────────────

    def draw(self, surface: pygame.Surface, camera):
        """
        Dibuja la porción visible de la pista con rotación de cámara.

        Extrae un cuadrado de la superficie del mundo centrado en la cámara,
        lo rota según el ángulo de la cámara, y recorta al tamaño de pantalla.
        """
        # Tamaño del chunk: diagonal de la pantalla para cubrir tras rotar
        half_diag = int(math.hypot(SCREEN_WIDTH, SCREEN_HEIGHT) / 2) + 2
        chunk_size = half_diag * 2

        # Región del mundo centrada en la posición de la cámara
        src_x = int(camera.cx) - half_diag
        src_y = int(camera.cy) - half_diag

        # Crear chunk y rellenar con césped (áreas fuera del mundo)
        chunk = pygame.Surface((chunk_size, chunk_size))
        chunk.fill(COLOR_GRASS)

        # Copiar la porción válida del track_surface al chunk
        blit_x = max(0, -src_x)
        blit_y = max(0, -src_y)
        world_x = max(0, src_x)
        world_y = max(0, src_y)
        w = min(chunk_size - blit_x, WORLD_WIDTH - world_x)
        h = min(chunk_size - blit_y, WORLD_HEIGHT - world_y)

        if w > 0 and h > 0:
            chunk.blit(self.track_surface, (blit_x, blit_y),
                       pygame.Rect(world_x, world_y, int(w), int(h)))

        # Rotar el chunk (pygame rota CCW, lo cual compensa el ángulo CW)
        rotated = pygame.transform.rotate(chunk, camera.angle)

        # Recortar el centro al tamaño de pantalla
        rw, rh = rotated.get_size()
        crop_x = (rw - SCREEN_WIDTH) // 2
        crop_y = (rh - SCREEN_HEIGHT) // 2

        surface.blit(rotated, (0, 0),
                     pygame.Rect(crop_x, crop_y, SCREEN_WIDTH, SCREEN_HEIGHT))
