"""
powerup.py - Entidades de power-ups, misiles y manchas de aceite.

Tipos de power-up:
    BOOST   (verde)  — Aumenta velocidad y aceleración por unos segundos.
    SHIELD  (azul)   — Absorbe el próximo impacto (muro, misil o auto).
    MISSILE (rojo)   — Dispara un proyectil que ralentiza al impactado.
    OIL     (amarillo) — Deja una mancha en el suelo que hace derrapar.
"""

import math
import random
import pygame

from settings import (
    POWERUP_SIZE, POWERUP_RESPAWN_TIME, POWERUP_BOB_SPEED,
    POWERUP_BOOST, POWERUP_SHIELD, POWERUP_MISSILE, POWERUP_OIL,
    POWERUP_COLORS,
    MISSILE_SPEED, MISSILE_LIFETIME, MISSILE_SIZE,
    OIL_SLICK_RADIUS, OIL_SLICK_LIFETIME,
    WORLD_WIDTH, WORLD_HEIGHT,
)

# Todos los tipos disponibles para spawn aleatorio
ALL_POWERUP_TYPES = [POWERUP_BOOST, POWERUP_SHIELD, POWERUP_MISSILE, POWERUP_OIL]


class PowerUpItem:
    """
    Un pickup de power-up en la pista.

    Aparece en un punto fijo del circuito. Al ser recogido, desaparece
    y reaparece después de un tiempo con un tipo aleatorio.
    """

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y
        self.power_type: str = random.choice(ALL_POWERUP_TYPES)
        self.active = True              # visible y recogible
        self.respawn_timer = 0.0        # cuenta regresiva para reaparecer
        self.bob_offset = random.uniform(0, math.pi * 2)  # fase de animación
        self.radius = POWERUP_SIZE

    def update(self, dt: float):
        """Actualiza el timer de respawn si está inactivo."""
        if not self.active:
            self.respawn_timer -= dt
            if self.respawn_timer <= 0:
                self.active = True
                self.power_type = random.choice(ALL_POWERUP_TYPES)

    def collect(self) -> str:
        """
        Recoge el power-up. Retorna el tipo y lo desactiva.

        Returns:
            Tipo de power-up recogido.
        """
        ptype = self.power_type
        self.active = False
        self.respawn_timer = POWERUP_RESPAWN_TIME
        return ptype

    def draw(self, surface: pygame.Surface, camera, time: float):
        """
        Dibuja el power-up con animación de flotación.

        Args:
            surface: superficie de destino (pantalla).
            camera: objeto Camera con world_to_screen().
            time: tiempo total del juego para la animación.
        """
        if not self.active:
            return

        sx, sy = camera.world_to_screen(self.x, self.y)

        # Animación de flotación vertical suave (bob)
        bob = math.sin(time * POWERUP_BOB_SPEED + self.bob_offset) * 4
        sy += bob

        color = POWERUP_COLORS.get(self.power_type, (200, 200, 200))
        r = self.radius

        # Fondo circular
        pygame.draw.circle(surface, (30, 30, 30), (int(sx), int(sy)), r + 3)
        pygame.draw.circle(surface, color, (int(sx), int(sy)), r)

        # Icono según tipo
        self._draw_icon(surface, int(sx), int(sy), r)

        # Borde blanco
        pygame.draw.circle(surface, (255, 255, 255), (int(sx), int(sy)), r + 3, 2)

    def _draw_icon(self, surface: pygame.Surface, cx: int, cy: int, r: int):
        """Dibuja el icono interior del power-up."""
        if self.power_type == POWERUP_BOOST:
            # Flecha hacia arriba (velocidad)
            pts = [(cx, cy - r // 2), (cx + r // 2, cy + r // 3),
                   (cx - r // 2, cy + r // 3)]
            pygame.draw.polygon(surface, (255, 255, 255), pts)

        elif self.power_type == POWERUP_SHIELD:
            # Escudo (arco)
            pygame.draw.circle(surface, (255, 255, 255),
                               (cx, cy), r - 5, 3)

        elif self.power_type == POWERUP_MISSILE:
            # Triángulo/cohete apuntando arriba
            pts = [(cx, cy - r // 2), (cx + r // 3, cy + r // 2),
                   (cx - r // 3, cy + r // 2)]
            pygame.draw.polygon(surface, (255, 255, 255), pts)
            pygame.draw.rect(surface, (255, 200, 50),
                             (cx - 2, cy + r // 4, 4, r // 3))

        elif self.power_type == POWERUP_OIL:
            # Gota
            pygame.draw.circle(surface, (40, 40, 40), (cx, cy + 2), r // 2)
            pts = [(cx, cy - r // 2), (cx + r // 3, cy),
                   (cx - r // 3, cy)]
            pygame.draw.polygon(surface, (40, 40, 40), pts)


class Missile:
    """
    Proyectil disparado por un auto.

    Viaja en línea recta a alta velocidad. Al impactar un auto enemigo,
    lo ralentiza. Se destruye al chocar con un muro o tras agotar su lifetime.
    """

    def __init__(self, x: float, y: float, angle: float, owner_id: int):
        self.x = x
        self.y = y
        self.angle = angle
        self.owner_id = owner_id       # ID del auto que lo disparó
        self.speed = MISSILE_SPEED
        self.lifetime = MISSILE_LIFETIME
        self.alive = True
        self.radius = MISSILE_SIZE

        # Vector de dirección (fijo al momento del disparo)
        rad = math.radians(angle)
        self.dx = math.sin(rad)
        self.dy = -math.cos(rad)

    def update(self, dt: float):
        """Actualiza posición y lifetime."""
        if not self.alive:
            return

        self.x += self.dx * self.speed * dt
        self.y += self.dy * self.speed * dt

        self.lifetime -= dt
        if self.lifetime <= 0:
            self.alive = False

        # Fuera del mundo
        if (self.x < -50 or self.x > WORLD_WIDTH + 50 or
                self.y < -50 or self.y > WORLD_HEIGHT + 50):
            self.alive = False

    def draw(self, surface: pygame.Surface, camera):
        """Dibuja el misil como un triángulo rojo orientado."""
        if not self.alive:
            return

        sx, sy = camera.world_to_screen(self.x, self.y)

        # Ángulo en pantalla (relativo a la cámara)
        screen_ang = camera.screen_angle(self.angle)
        r = self.radius
        rad = math.radians(screen_ang)
        cos_a, sin_a = math.cos(rad), math.sin(rad)

        # Punta, esquina izquierda, esquina derecha
        pts = [
            (sx + sin_a * r * 2,       sy - cos_a * r * 2),
            (sx - cos_a * r - sin_a * r, sy - sin_a * r + cos_a * r),
            (sx + cos_a * r - sin_a * r, sy + sin_a * r + cos_a * r),
        ]
        int_pts = [(int(p[0]), int(p[1])) for p in pts]
        pygame.draw.polygon(surface, (230, 50, 50), int_pts)
        pygame.draw.polygon(surface, (255, 150, 50), int_pts, 2)

        # Estela (línea detrás)
        tail_x = sx - sin_a * r * 3
        tail_y = sy + cos_a * r * 3
        pygame.draw.line(surface, (255, 180, 50),
                         (int(sx), int(sy)), (int(tail_x), int(tail_y)), 2)


class OilSlick:
    """
    Mancha de aceite dejada en la pista.

    Los autos que pasan por encima pierden tracción temporalmente
    (aumento de fricción y reducción de giro).
    """

    def __init__(self, x: float, y: float, owner_id: int):
        self.x = x
        self.y = y
        self.owner_id = owner_id
        self.radius = OIL_SLICK_RADIUS
        self.lifetime = OIL_SLICK_LIFETIME
        self.alive = True

    def update(self, dt: float):
        """Reduce el lifetime."""
        if not self.alive:
            return
        self.lifetime -= dt
        if self.lifetime <= 0:
            self.alive = False

    def draw(self, surface: pygame.Surface, camera):
        """Dibuja la mancha de aceite como un charco oscuro."""
        if not self.alive:
            return

        sx, sy = camera.world_to_screen(self.x, self.y)
        sx, sy = int(sx), int(sy)
        r = self.radius

        # Charco principal (semitransparente para parecer líquido)
        oil_surface = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
        pygame.draw.ellipse(oil_surface, (20, 18, 15, 180),
                            (0, 0, r * 2 + 4, r * 2))
        pygame.draw.ellipse(oil_surface, (40, 35, 25, 120),
                            (4, 3, r * 2 - 4, r * 2 - 6))
        # Brillo
        pygame.draw.ellipse(oil_surface, (80, 70, 50, 60),
                            (r // 2, r // 3, r, r // 2))
        surface.blit(oil_surface, (sx - r - 2, sy - r))
