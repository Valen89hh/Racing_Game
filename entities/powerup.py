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
    POWERUP_MINE, POWERUP_EMP, POWERUP_MAGNET, POWERUP_SLOWMO,
    POWERUP_BOUNCE, POWERUP_AUTOPILOT, POWERUP_TELEPORT,
    POWERUP_SMART_MISSILE,
    POWERUP_COLORS, POWERUP_MYSTERY_COLOR,
    MISSILE_SPEED, MISSILE_LIFETIME, MISSILE_SIZE,
    SMART_MISSILE_SPEED, SMART_MISSILE_LIFETIME,
    SMART_MISSILE_TURN_SPEED, SMART_MISSILE_SIZE,
    OIL_SLICK_RADIUS, OIL_SLICK_LIFETIME,
    MINE_RADIUS, MINE_LIFETIME,
    WORLD_WIDTH, WORLD_HEIGHT,
)

# Todos los tipos disponibles para spawn aleatorio
ALL_POWERUP_TYPES = [
    POWERUP_BOOST, POWERUP_SHIELD, POWERUP_MISSILE, POWERUP_OIL,
    POWERUP_MINE, POWERUP_EMP, POWERUP_MAGNET, POWERUP_SLOWMO,
    POWERUP_BOUNCE, POWERUP_AUTOPILOT, POWERUP_TELEPORT,
    POWERUP_SMART_MISSILE,
]


class PowerUpItem:
    """
    Un pickup de power-up en la pista (caja misteriosa).

    Aparece en un punto fijo del circuito como caja dorada con "?".
    Al ser recogido, asigna un tipo aleatorio y desaparece.
    Reaparece después de un tiempo.
    """

    _q_font = None  # class-level cached font for "?" rendering

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y
        self.power_type = None          # tipo desconocido hasta recoger
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
                self.power_type = None  # misterio de nuevo

    def collect(self) -> str:
        """
        Recoge el power-up. Asigna tipo aleatorio y lo desactiva.

        Returns:
            Tipo de power-up recogido.
        """
        ptype = random.choice(ALL_POWERUP_TYPES)
        self.power_type = ptype
        self.active = False
        self.respawn_timer = POWERUP_RESPAWN_TIME
        return ptype

    def draw(self, surface: pygame.Surface, camera, time: float):
        """
        Dibuja el power-up como caja misteriosa dorada con "?".

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

        r = self.radius
        ix, iy = int(sx), int(sy)

        # Fondo circular oscuro + dorado
        pygame.draw.circle(surface, (30, 30, 30), (ix, iy), r + 3)
        pygame.draw.circle(surface, POWERUP_MYSTERY_COLOR, (ix, iy), r)

        # "?" blanco centrado
        if PowerUpItem._q_font is None:
            PowerUpItem._q_font = pygame.font.SysFont("consolas", r * 2, bold=True)
        q_surf = PowerUpItem._q_font.render("?", True, (255, 255, 255))
        q_rect = q_surf.get_rect(center=(ix, iy))
        surface.blit(q_surf, q_rect)

        # Borde blanco
        pygame.draw.circle(surface, (255, 255, 255), (ix, iy), r + 3, 2)


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


class Mine:
    """
    Mina explosiva dejada en la pista.

    Al pasar por encima, causa spin (rotación forzada) y reducción de
    velocidad. Se destruye tras ser activada o al agotar su lifetime.
    """

    def __init__(self, x: float, y: float, owner_id: int):
        self.x = x
        self.y = y
        self.owner_id = owner_id
        self.radius = MINE_RADIUS
        self.lifetime = MINE_LIFETIME
        self.alive = True

    def update(self, dt: float):
        """Reduce el lifetime."""
        if not self.alive:
            return
        self.lifetime -= dt
        if self.lifetime <= 0:
            self.alive = False

    def draw(self, surface: pygame.Surface, camera):
        """Dibuja la mina como un círculo oscuro con picos."""
        if not self.alive:
            return

        sx, sy = camera.world_to_screen(self.x, self.y)
        ix, iy = int(sx), int(sy)
        r = self.radius

        # Círculo base
        pygame.draw.circle(surface, (60, 20, 20), (ix, iy), r)
        pygame.draw.circle(surface, (160, 40, 40), (ix, iy), r, 2)

        # Picos (triángulos alrededor)
        for i in range(6):
            a = math.radians(i * 60)
            px = ix + int(math.cos(a) * (r + 5))
            py = iy + int(math.sin(a) * (r + 5))
            pygame.draw.circle(surface, (180, 50, 50), (px, py), 3)

        # Punto rojo central (indicador)
        pygame.draw.circle(surface, (255, 60, 60), (ix, iy), 4)


class SmartMissile:
    """
    Misil inteligente que persigue al auto en primera posición.

    Gira hacia su objetivo cada frame. Se destruye al impactar,
    chocar con un muro, o agotar su lifetime.
    """

    def __init__(self, x: float, y: float, angle: float,
                 owner_id: int, target):
        self.x = x
        self.y = y
        self.angle = angle
        self.owner_id = owner_id
        self.target = target           # Car object al que persigue
        self.speed = SMART_MISSILE_SPEED
        self.lifetime = SMART_MISSILE_LIFETIME
        self.alive = True
        self.radius = SMART_MISSILE_SIZE

    def update(self, dt: float):
        """Actualiza posición con homing hacia el target."""
        if not self.alive:
            return

        # Girar hacia el objetivo
        if self.target and not self.target.finished:
            dx = self.target.x - self.x
            dy = self.target.y - self.y
            target_angle = math.degrees(math.atan2(dx, -dy)) % 360
            current = self.angle % 360
            diff = (target_angle - current + 180) % 360 - 180
            max_turn = SMART_MISSILE_TURN_SPEED * dt
            if abs(diff) < max_turn:
                self.angle = target_angle
            else:
                self.angle += max_turn if diff > 0 else -max_turn

        # Mover adelante
        rad = math.radians(self.angle)
        self.x += math.sin(rad) * self.speed * dt
        self.y += -math.cos(rad) * self.speed * dt

        self.lifetime -= dt
        if self.lifetime <= 0:
            self.alive = False

        # Fuera del mundo
        if (self.x < -50 or self.x > WORLD_WIDTH + 50 or
                self.y < -50 or self.y > WORLD_HEIGHT + 50):
            self.alive = False

    def draw(self, surface: pygame.Surface, camera):
        """Dibuja el misil inteligente como triángulo naranja."""
        if not self.alive:
            return

        sx, sy = camera.world_to_screen(self.x, self.y)
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
        pygame.draw.polygon(surface, (255, 100, 30), int_pts)
        pygame.draw.polygon(surface, (255, 200, 50), int_pts, 2)

        # Estela
        tail_x = sx - sin_a * r * 3
        tail_y = sy + cos_a * r * 3
        pygame.draw.line(surface, (255, 140, 30),
                         (int(sx), int(sy)), (int(tail_x), int(tail_y)), 2)
