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
COLOR_PROGRESS_BAR = (0, 180, 80)
COLOR_PROGRESS_BG = (40, 40, 50)

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

# ──────────────────────────────────────────────
# DRIFT / DERRAPE
# ──────────────────────────────────────────────
DRIFT_MIN_SPEED = 80.0          # velocidad mínima para poder driftar
DRIFT_MAX_ANGLE = 45.0          # ángulo máximo entre orientación y velocidad durante drift
DRIFT_TURN_BOOST = 1.15          # multiplicador de giro durante drift
DRIFT_SPEED_BOOST = 1.06         # multiplicador de velocidad durante drift
DRIFT_LATERAL_GRIP_NORMAL = 0.2   # retención lateral sin drift (grip alto, agarre)
DRIFT_LATERAL_GRIP_DRIFT = 0.85   # retención lateral en drift (grip bajo, desliza)
DRIFT_EXIT_BOOST = 1.05           # boost de velocidad al salir del drift
DRIFT_LATERAL_THRESHOLD = 20.0    # velocidad lateral mínima para considerar "deslizando"
DRIFT_SMOKE_RATE = 4.0          # partículas de humo por frame durante drift
DRIFT_SMOKE_COLORS = [
    (180, 180, 180),  # gris claro
    (160, 160, 170),  # gris azulado
    (200, 200, 200),  # blanco humo
    (140, 140, 150),  # gris medio
]

# ── Mini-turbo (carga durante drift) ──
DRIFT_CHARGE_RATE = 0.55            # carga por segundo drifteando (a full input)
DRIFT_LEVEL_THRESHOLDS = (0.33, 0.66, 1.0)  # L1, L2, L3
DRIFT_LEVEL_BOOSTS = (1.08, 1.15, 1.25)     # boost de velocidad al soltar por nivel
DRIFT_LEVEL_COLORS = [
    (80, 160, 255),    # L1: azul
    (255, 160, 40),    # L2: naranja
    (255, 80, 200),    # L3: rosa
]
DRIFT_MT_BOOST_DURATION = 0.6       # duración del mini-turbo boost tras soltar

# ── Counter-steer drift (derrape diagonal) ──
DRIFT_COUNTERSTEER_TURN_MULT = 0.15  # (reservado para uso futuro)
DRIFT_COUNTERSTEER_GRIP = 1.0        # sin corrección lateral → mantiene trayectoria diagonal exacta

# ── Grip progresivo ──
DRIFT_GRIP_TRANSITION_TIME = 0.3    # segundos para transicionar de grip normal a drift

# ── Skid marks (marcas de derrape) ──
SKID_MARK_POOL_SIZE = 600
SKID_MARK_LIFETIME = 3.0            # segundos antes de desaparecer
SKID_MARK_WIDTH = 3                 # ancho de la línea
SKID_MARK_COLOR = (30, 30, 30)      # negro oscuro
SKID_MARK_WHEEL_OFFSET = 9.0        # offset lateral de ruedas traseras

# ── Camera shake durante drift ──
CAMERA_SHAKE_MAX_OFFSET = 3.0       # píxeles máx de desplazamiento
CAMERA_SHAKE_INTENSITY_SCALE = 0.008  # escala de intensidad por velocidad lateral
CAMERA_SHAKE_DECAY_RATE = 8.0       # velocidad de decaimiento cuando no driftea

# ── Spark particles (chispas durante drift) ──
SPARK_EMIT_RATE = 6.0               # partículas por frame durante drift
SPARK_LIFETIME_MIN = 0.15
SPARK_LIFETIME_MAX = 0.4
SPARK_RADIUS = 2.0
SPARK_SPEED = 80.0                  # velocidad de dispersión

# ── HUD drift charge bar ──
DRIFT_BAR_WIDTH = 30
DRIFT_BAR_HEIGHT = 4
DRIFT_BAR_OFFSET_Y = 22            # offset debajo del auto

CAR_WIDTH = 22
CAR_HEIGHT = 40

# ──────────────────────────────────────────────
# IA (BOT)
# ──────────────────────────────────────────────
BOT_WAYPOINT_REACH_DIST = 70
BOT_ACCELERATION = 290.0
BOT_MAX_SPEED = 480.0
BOT_TURN_SPEED = 195.0
BOT_STUCK_CHECK_INTERVAL = 0.5
BOT_STUCK_DIST_THRESHOLD = 10.0
BOT_STUCK_TIME_THRESHOLD = 1.5
BOT_RECOVERY_DURATION = 1.0
BOT_LOOK_AHEAD = 5
BOT_STEER_DEADZONE = 1.5
BOT_STEER_RANGE = 60.0

# ──────────────────────────────────────────────
# CIRCUITO
# ──────────────────────────────────────────────
TRACK_HALF_WIDTH = 75          # mitad del ancho de la pista (pista total = 150px)
TRACK_BORDER_THICKNESS = 3
TOTAL_LAPS = 3
DEBUG_CHECKPOINTS = True    # Dibujar zonas de checkpoint y next_cp sobre autos

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
SHIELD_DURATION = 5.0          # segundos (o hasta recibir impacto)

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

# Mine (Mina Explosiva)
POWERUP_MINE = "mine"
MINE_RADIUS = 25               # radio del collider
MINE_LIFETIME = 15.0           # segundos en la pista
MINE_SPIN_DURATION = 2.0       # duración del spin al pisar
MINE_SLOW_FACTOR = 0.3         # multiplicador de velocidad al pisar

# EMP (Pulso Electromagnético)
POWERUP_EMP = "emp"
EMP_RANGE = 300.0              # radio de efecto
EMP_SLOW_DURATION = 3.0        # duración del slowdown
EMP_SLOW_FACTOR = 0.5          # multiplicador de velocidad

# Magnet (Imán de Checkpoints)
POWERUP_MAGNET = "magnet"
MAGNET_DURATION = 8.0          # duración del efecto
MAGNET_RADIUS_MULT = 3.0       # multiplicador del radio de detección

# SlowMo (Ralentización Temporal)
POWERUP_SLOWMO = "slowmo"
SLOWMO_DURATION = 3.0          # duración del bullet time
SLOWMO_FACTOR = 0.7            # rivales a 70% velocidad

# Bounce (Rebote Mejorado)
POWERUP_BOUNCE = "bounce"
BOUNCE_DURATION = 8.0          # duración del efecto

# Autopilot
POWERUP_AUTOPILOT = "autopilot"
AUTOPILOT_DURATION = 1.0       # duración del piloto automático

# Teleport
POWERUP_TELEPORT = "teleport"
TELEPORT_DISTANCE = 100.0      # píxeles hacia adelante

# Smart Missile (Misil Inteligente)
POWERUP_SMART_MISSILE = "smart_missile"
SMART_MISSILE_SPEED = 500.0    # px/s
SMART_MISSILE_LIFETIME = 5.0   # segundos
SMART_MISSILE_TURN_SPEED = 180.0  # grados/s de giro
SMART_MISSILE_SIZE = 8         # radio

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
    POWERUP_BOOST:          (0, 220, 80),      # verde
    POWERUP_SHIELD:         (60, 140, 255),     # azul
    POWERUP_MISSILE:        (230, 50, 50),      # rojo
    POWERUP_OIL:            (180, 160, 30),     # amarillo oscuro
    POWERUP_MINE:           (160, 40, 40),      # marrón rojizo
    POWERUP_EMP:            (0, 200, 255),      # cian
    POWERUP_MAGNET:         (220, 60, 220),     # magenta
    POWERUP_SLOWMO:         (160, 80, 220),     # púrpura
    POWERUP_BOUNCE:         (255, 160, 30),     # naranja
    POWERUP_AUTOPILOT:      (30, 180, 130),     # teal
    POWERUP_TELEPORT:       (100, 200, 255),    # celeste
    POWERUP_SMART_MISSILE:  (255, 100, 30),     # naranja oscuro
}
POWERUP_MYSTERY_COLOR = (255, 200, 40)

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
STATE_TRAINING = "training"

# Online multiplayer states
STATE_HOST_LOBBY = "host_lobby"
STATE_JOIN_LOBBY = "join_lobby"
STATE_CONNECTING = "connecting"
STATE_ONLINE_RACING = "online_racing"
STATE_ONLINE_COUNTDOWN = "online_countdown"

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

# ──────────────────────────────────────────────
# NETWORKING (multiplayer online)
# ──────────────────────────────────────────────
NET_DEFAULT_PORT = 5555
NET_TICK_RATE = 30              # snapshots/segundo del host a clientes
NET_INPUT_RATE = 60             # inputs/segundo del cliente al host
NET_TIMEOUT = 5.0               # segundos sin heartbeat → disconnect
NET_HEARTBEAT_INTERVAL = 1.0    # segundos entre pings
NET_INTERPOLATION_DELAY = 0.05  # 50ms de buffer para interpolación
NET_MAX_SNAPSHOT_BUFFER = 5     # snapshots en buffer circular
NET_RECONCILE_SNAP_DIST = 100.0 # distancia para snap teleport
NET_RECONCILE_BLEND = 0.2      # factor de blend hacia servidor

# ──────────────────────────────────────────────
# RELAY SERVER (multiplayer por internet)
# ──────────────────────────────────────────────
RELAY_DEFAULT_PORT = 7777
RELAY_HEARTBEAT_INTERVAL = 3.0
RELAY_TIMEOUT = 10.0
ROOM_CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# Estados relay
STATE_RELAY_HOST = "relay_host"
STATE_RELAY_JOIN = "relay_join"
