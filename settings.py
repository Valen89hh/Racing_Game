"""
settings.py - Configuración central del juego.

Todas las constantes y parámetros ajustables del juego se definen aquí.
Esto permite modificar el comportamiento del juego sin tocar la lógica.
"""

# ──────────────────────────────────────────────
# PANTALLA
# ──────────────────────────────────────────────
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 60
TITLE = "Arcade Racing 2D"

# ──────────────────────────────────────────────
# MUNDO (tamaño total del mapa, mayor que la pantalla)
# ──────────────────────────────────────────────
WORLD_WIDTH = 3600
WORLD_HEIGHT = 2400

# ──────────────────────────────────────────────
# CÁMARA
# ──────────────────────────────────────────────
CAMERA_SMOOTHING = 8.0              # velocidad de interpolación de posición
CAMERA_LOOK_AHEAD = 200.0           # píxeles de anticipación (fuerte, para ver lejos)
CAMERA_ROTATION_SPEED = 1.5         # velocidad de rotación angular (suave)
CAMERA_MAX_ANGULAR_SPEED = 35.0     # máx grados/segundo de rotación de cámara

# ──────────────────────────────────────────────
# COLORES (R, G, B)
# ──────────────────────────────────────────────
COLOR_BLACK = (0, 0, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_GRAY = (80, 80, 80)
COLOR_DARK_GRAY = (40, 40, 40)
COLOR_GREEN = (34, 139, 34)
COLOR_GRASS = (46, 92, 41)
COLOR_GRASS_LIGHT = (54, 104, 48)
COLOR_ASPHALT = (85, 85, 85)
COLOR_ASPHALT_DARK = (70, 70, 70)
COLOR_CURB_RED = (200, 50, 50)
COLOR_CURB_WHITE = (220, 220, 220)
COLOR_YELLOW = (255, 215, 0)
COLOR_RED = (220, 50, 50)
COLOR_BLUE = (50, 100, 220)
COLOR_ORANGE = (255, 140, 0)
COLOR_HUD_BG = (20, 20, 20, 180)
COLOR_FINISH_LINE = (255, 255, 255)
COLOR_MINIMAP_BG = (30, 30, 30, 200)

# ──────────────────────────────────────────────
# FÍSICA DEL AUTO
# ──────────────────────────────────────────────
CAR_ACCELERATION = 300.0
CAR_BRAKE_FORCE = 400.0
CAR_MAX_SPEED = 500.0
CAR_FRICTION = 120.0
CAR_TURN_SPEED = 200.0
CAR_TURN_SPEED_MIN = 40.0
CAR_DRIFT_FACTOR = 0.92
CAR_REVERSE_MAX_SPEED = 150.0

CAR_WIDTH = 22
CAR_HEIGHT = 40

# ──────────────────────────────────────────────
# IA (BOT)
# ──────────────────────────────────────────────
BOT_WAYPOINT_REACH_DIST = 70
BOT_ACCELERATION = 290.0
BOT_MAX_SPEED = 480.0
BOT_TURN_SPEED = 195.0

# ──────────────────────────────────────────────
# CIRCUITO
# ──────────────────────────────────────────────
TRACK_HALF_WIDTH = 75          # mitad del ancho de la pista (pista total = 150px)
TRACK_BORDER_THICKNESS = 3
TOTAL_LAPS = 3

# ──────────────────────────────────────────────
# POWER-UPS
# ──────────────────────────────────────────────
POWERUP_BOOST = "boost"
POWERUP_SHIELD = "shield"
POWERUP_MISSILE = "missile"
POWERUP_OIL = "oil"

POWERUP_SIZE = 18              # radio del pickup en el mapa
POWERUP_RESPAWN_TIME = 10.0    # segundos para reaparecer tras ser recogido
POWERUP_BOB_SPEED = 3.0        # velocidad de animación flotante

# Boost
BOOST_DURATION = 3.0           # segundos
BOOST_SPEED_MULT = 1.45        # multiplicador de velocidad máxima
BOOST_ACCEL_MULT = 1.3         # multiplicador de aceleración

# Shield
SHIELD_DURATION = 12.0         # segundos (o hasta recibir impacto)

# Missile
MISSILE_SPEED = 700.0          # px/s
MISSILE_LIFETIME = 2.5         # segundos
MISSILE_SIZE = 8               # radio del proyectil
MISSILE_SLOW_DURATION = 2.0    # duración del efecto al impactar
MISSILE_SLOW_FACTOR = 0.35     # multiplicador de velocidad al impactado

# Oil Slick
OIL_SLICK_RADIUS = 30          # radio de la mancha
OIL_SLICK_LIFETIME = 8.0       # segundos en el suelo
OIL_EFFECT_DURATION = 1.5      # segundos de efecto al pisar
OIL_FRICTION_MULT = 3.0        # multiplicador de fricción (derrape)
OIL_TURN_MULT = 0.3            # multiplicador de giro (pierde control)

# ──────────────────────────────────────────────
# PARTÍCULAS DE POLVO
# ──────────────────────────────────────────────
DUST_MAX_PARTICLES = 120
DUST_SPEED_THRESHOLD = 80.0    # velocidad mínima para emitir
DUST_EMIT_RATE = 3.0           # partículas base por frame a max speed
DUST_LIFETIME_MIN = 0.3
DUST_LIFETIME_MAX = 0.8
DUST_RADIUS_MIN = 2.0
DUST_RADIUS_MAX = 5.0
DUST_MAX_ALPHA = 120
DUST_COLORS = [
    (160, 130, 100),  # brown
    (140, 120, 90),   # tan
    (130, 130, 120),  # gray
    (150, 140, 110),  # sandy
    (120, 110, 100),  # cool brown
]

# Colores de cada power-up
POWERUP_COLORS = {
    POWERUP_BOOST:   (0, 220, 80),
    POWERUP_SHIELD:  (60, 140, 255),
    POWERUP_MISSILE: (230, 50, 50),
    POWERUP_OIL:     (180, 160, 30),
}

# ──────────────────────────────────────────────
# MINIMAPA
# ──────────────────────────────────────────────
MINIMAP_SCALE = 0.06           # escala del minimapa respecto al mundo
MINIMAP_MARGIN = 15
MINIMAP_CAR_DOT = 4            # radio del punto de cada auto

# ──────────────────────────────────────────────
# HUD
# ──────────────────────────────────────────────
HUD_FONT_SIZE = 22
HUD_TITLE_FONT_SIZE = 64
HUD_SUBTITLE_FONT_SIZE = 32
HUD_MARGIN = 15

# ──────────────────────────────────────────────
# ESTADOS DEL JUEGO
# ──────────────────────────────────────────────
STATE_MENU = "menu"
STATE_COUNTDOWN = "countdown"
STATE_RACING = "racing"
STATE_VICTORY = "victory"
STATE_EDITOR = "editor"
STATE_TRACK_SELECT = "track_select"

# ──────────────────────────────────────────────
# JUGADORES (preparado para multiplayer futuro)
# ──────────────────────────────────────────────
MAX_PLAYERS = 4
PLAYER_COLORS = [
    (50, 120, 255),    # Azul  - Jugador 1
    (220, 50, 50),     # Rojo  - Bot / Jugador 2
    (50, 200, 50),     # Verde - Jugador 3
    (255, 180, 0),     # Naranja - Jugador 4
]

PLAYER_CONTROLS = {
    0: {"up": "w", "down": "s", "left": "a", "right": "d"},
    1: {"up": "up", "down": "down", "left": "left", "right": "right"},
}

# ──────────────────────────────────────────────
# PIXEL ART SPRITES
# ──────────────────────────────────────────────
SPRITE_SCALE = 3               # factor de escala para sprites 16x16 → 48x48
SPRITE_FRAME_SIZE = 16         # tamaño original de cada frame del sprite

# Archivos de sprites de autos (en assets/cars/)
CAR_SPRITES = {
    0: "player_blue.png",      # Jugador 1
    1: "player_red.png",       # Bot / Jugador 2
    2: "player_green.png",     # Jugador 3
    3: "player_yellow.png",    # Jugador 4
}

# Escala del tile de textura de pista
TRACK_TILE_SCALE = 2           # 64x64 → 128x128 por tile

# ──────────────────────────────────────────────
# TILES (editor tile-based)
# ──────────────────────────────────────────────
TILE_SIZE = 64
GRID_COLS = 56                 # WORLD_WIDTH // TILE_SIZE
GRID_ROWS = 37                 # WORLD_HEIGHT // TILE_SIZE

# ──────────────────────────────────────────────
# EDITOR LAYOUT
# ──────────────────────────────────────────────
EDITOR_BOTTOM_PANEL_H = 200
EDITOR_STATUS_BAR_H = 28
EDITOR_TOOLS_W = 130
EDITOR_INSPECTOR_W = 180

# ──────────────────────────────────────────────
# TILE CATEGORIES (used by tile_meta.py)
# ──────────────────────────────────────────────
TILE_CAT_TERRAIN = "terrain"       # driveable surfaces
TILE_CAT_PROPS = "props"           # decorative, blocks movement
TILE_CAT_OBSTACLES = "obstacles"   # walls, barriers
TILE_CAT_SPECIAL = "special"       # finish, checkpoints
