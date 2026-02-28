"""
world_simulation.py - Simulacion autoritativa del mundo de carrera.

Extrae la logica de simulacion de game.py:_update_online_racing_host()
para uso en el servidor dedicado. Ejecuta fisica, colisiones, checkpoints,
power-ups y AI de forma determinista a FIXED_DT.
"""

import math

from entities.car import Car
from entities.track import Track
from entities.powerup import PowerUpItem, Missile, OilSlick, Mine, SmartMissile
from systems.physics import PhysicsSystem
from systems.collision import CollisionSystem
from systems.ai import AISystem
from utils.timer import RaceTimer
from race_progress import RaceProgressTracker
from tile_track import TileTrack

from settings import (
    PLAYER_COLORS, MAX_PLAYERS, TOTAL_LAPS, FIXED_DT,
    BOT_ACCELERATION, BOT_MAX_SPEED, BOT_TURN_SPEED,
    POWERUP_BOOST, POWERUP_SHIELD, POWERUP_MISSILE, POWERUP_OIL,
    POWERUP_MINE, POWERUP_EMP, POWERUP_MAGNET, POWERUP_SLOWMO,
    POWERUP_BOUNCE, POWERUP_AUTOPILOT, POWERUP_TELEPORT,
    POWERUP_SMART_MISSILE,
    BOOST_DURATION, SHIELD_DURATION,
    MISSILE_SLOW_DURATION, OIL_EFFECT_DURATION,
    MINE_SPIN_DURATION, EMP_RANGE, EMP_SLOW_DURATION,
    MAGNET_DURATION, SLOWMO_DURATION, BOUNCE_DURATION,
    AUTOPILOT_DURATION, TELEPORT_DISTANCE,
    SMART_MISSILE_LIFETIME,
    SLOWMO_FACTOR,
)
from networking.protocol import pack_powerup_event, PW_EVENT_COLLECT


class WorldSimulation:
    """Simulacion autoritativa de la carrera para el servidor dedicado."""

    def __init__(self, track_data, player_list, bot_count):
        """
        Args:
            track_data: dict con datos del track (JSON parseado).
            player_list: lista de (player_id, name) de jugadores humanos.
            bot_count: numero de bots a crear.
        """
        # Crear track
        if track_data.get("format") == "tiles":
            self.track = TileTrack(track_data)
        else:
            self.track = Track(control_points=track_data["control_points"])

        # Sistemas
        self.physics = PhysicsSystem()
        self.collision_system = CollisionSystem(self.track)
        self.ai_system = AISystem(self.track)
        self.race_timer = RaceTimer()
        self.race_timer.reset()

        # Crear autos
        self.cars = []
        sp = self.track.start_positions

        for i, (pid, name) in enumerate(player_list):
            pos_idx = min(i, len(sp) - 1)
            car = Car(sp[pos_idx][0], sp[pos_idx][1], sp[pos_idx][2],
                      PLAYER_COLORS[pid % len(PLAYER_COLORS)], pid)
            car.name = name
            car.is_remote = True  # Todos son remotos para el servidor
            self.cars.append(car)

        # Bots
        bot_start_idx = len(player_list)
        for b in range(bot_count):
            bot_visual_idx = bot_start_idx + b
            pos_idx = min(bot_visual_idx, len(sp) - 1)
            bot = Car(sp[pos_idx][0], sp[pos_idx][1], sp[pos_idx][2],
                      PLAYER_COLORS[bot_visual_idx % len(PLAYER_COLORS)],
                      100 + b)
            bot.name = f"Bot {b + 1}"
            bot.is_bot_car = True
            bot.acceleration = BOT_ACCELERATION
            bot.max_speed = BOT_MAX_SPEED
            bot.turn_speed = BOT_TURN_SPEED
            self.cars.append(bot)
            self.ai_system.register_bot(bot)

        # Asegurar que ningún auto spawneó dentro de un muro
        for car in self.cars:
            self.collision_system.ensure_valid_spawn(car)

        # Power-ups
        self.powerup_items = [
            PowerUpItem(p[0], p[1]) for p in self.track.powerup_spawn_points
        ]
        self.missiles = []
        self.oil_slicks = []
        self.mines = []
        self.smart_missiles = []

        # Race progress tracker
        fl = self.track.finish_line
        fl_center = ((fl[0][0] + fl[1][0]) / 2, (fl[0][1] + fl[1][1]) / 2)
        self.race_progress = RaceProgressTracker(
            self.track.checkpoints, fl_center
        )
        for car in self.cars:
            self.race_progress.register_car(car.player_id)

        # Tracking
        self.server_tick = 0
        self.winner = None
        self.final_times = {}

        # Eventos pendientes para broadcast (powerup collect, etc.)
        self.pending_events = []

    def step(self, dt, remote_inputs):
        """Ejecuta un tick de simulacion.

        Args:
            dt: delta time (normalmente FIXED_DT).
            remote_inputs: dict {player_id: InputState} — ya popped (1 por jugador).
        """
        self.server_tick += 1

        # DEBUG: primeros 5 ticks, imprimir posicion de todos los autos
        if self.server_tick <= 5:
            for car in self.cars:
                has_input = car.player_id in remote_inputs
                print(f"[DEBUG-SERVER] tick={self.server_tick} "
                      f"car={car.name}(pid={car.player_id}) "
                      f"x={car.x:.1f} y={car.y:.1f} "
                      f"spd={car.speed:.1f} "
                      f"has_input={has_input}")

        # Detectar slowmo owner
        slowmo_owner = None
        for car in self.cars:
            if car.has_slowmo:
                slowmo_owner = car
                break

        for car in self.cars:
            if car.finished:
                continue

            # Aplicar inputs remotos
            if car.is_remote and not car.is_bot_car:
                inp = remote_inputs.get(car.player_id)
                if inp:
                    car.reset_inputs()
                    car.input_accelerate = inp.accel
                    car.input_turn = inp.turn
                    car.input_brake = inp.brake
                    car.input_use_powerup = inp.use_powerup
                # Si no hay input, el auto mantiene inputs anteriores (coast)
            elif car.is_bot_car:
                self.ai_system.update(car, dt, self.cars)

            # Autopilot sobreescribe
            if car.has_autopilot:
                self._autopilot_steer(car)

            # SlowMo
            car_dt = dt
            if (slowmo_owner is not None and
                    car.player_id != slowmo_owner.player_id):
                car_dt = dt * SLOWMO_FACTOR

            # Simulacion (effects + physics + wall collision)
            self._simulate_car_step(car, car_dt)

            # Checkpoints y vueltas
            old_laps = car.laps
            self.collision_system.update_checkpoints(car)
            if car.laps > old_laps:
                if car.laps >= TOTAL_LAPS:
                    car.finished = True
                    car.finish_time = self.race_timer.total_time
                    self.final_times[car.name] = car.finish_time
                    if self.winner is None:
                        self.winner = car

            # Progress
            self.race_progress.update(car)

            # Power-up usage
            if car.input_use_powerup and car.held_powerup is not None:
                self._activate_powerup(car)

        # Car vs car collisions
        for i in range(len(self.cars)):
            for j in range(i + 1, len(self.cars)):
                if self.collision_system.check_car_vs_car(
                        self.cars[i], self.cars[j]):
                    a, b = self.cars[i], self.cars[j]
                    if a.is_shielded:
                        a.break_shield()
                    elif b.is_shielded:
                        b.break_shield()
                    self.collision_system.resolve_car_vs_car(a, b)
                    a.update_sprite()
                    b.update_sprite()

        # Recoger power-ups
        for car in self.cars:
            if car.held_powerup is not None:
                continue
            for idx, item in enumerate(self.powerup_items):
                if self.collision_system.check_car_vs_powerup(car, item):
                    ptype = item.collect()
                    car.held_powerup = ptype
                    evt_data = pack_powerup_event(
                        PW_EVENT_COLLECT, car.player_id,
                        ptype, idx, item.x, item.y)
                    self.pending_events.append(evt_data)
                    break

        # Update power-up items (respawn timers)
        for item in self.powerup_items:
            item.update(dt)

        # Missiles
        for missile in self.missiles:
            missile.update(dt)
            if self.collision_system.check_missile_vs_wall(missile):
                missile.alive = False
            for car in self.cars:
                if self.collision_system.check_car_vs_missile(car, missile):
                    missile.alive = False
                    if car.is_shielded:
                        car.break_shield()
                    else:
                        car.apply_effect("missile_slow", MISSILE_SLOW_DURATION)
                        car.speed *= 0.3
        self.missiles = [m for m in self.missiles if m.alive]

        # Oil slicks
        for oil in self.oil_slicks:
            oil.update(dt)
            for car in self.cars:
                if car.player_id == oil.owner_id:
                    continue
                if self.collision_system.check_car_vs_oil(car, oil):
                    if "oil_slow" not in car.active_effects:
                        car.apply_effect("oil_slow", OIL_EFFECT_DURATION)
        self.oil_slicks = [o for o in self.oil_slicks if o.alive]

        # Mines
        for mine in self.mines:
            mine.update(dt)
            for car in self.cars:
                if self.collision_system.check_car_vs_mine(car, mine):
                    mine.alive = False
                    if car.is_shielded:
                        car.break_shield()
                    else:
                        car.apply_effect("mine_spin", MINE_SPIN_DURATION)
                        car.speed *= 0.3
        self.mines = [m for m in self.mines if m.alive]

        # Smart missiles
        for sm in self.smart_missiles:
            sm.update(dt)
            if self.collision_system.check_missile_vs_wall(sm):
                sm.alive = False
            for car in self.cars:
                if self.collision_system.check_car_vs_smart_missile(car, sm):
                    sm.alive = False
                    if car.is_shielded:
                        car.break_shield()
                    else:
                        car.apply_effect("missile_slow", MISSILE_SLOW_DURATION)
                        car.speed *= 0.3
        self.smart_missiles = [m for m in self.smart_missiles if m.alive]

        # Timer
        self.race_timer.update(dt)

    def _simulate_car_step(self, car, dt):
        """Un paso determinista de simulacion de auto.
        Incluye: effects, fisica, drift, colision con muros."""
        car.update_effects(dt)
        self.physics.update(car, dt, self.track)
        hit, normal, remaining = self.collision_system.move_with_substeps(car, dt)
        if hit:
            if car.is_shielded:
                car.break_shield()
                car.speed *= 0.7
            elif car.has_bounce:
                self.physics.apply_collision_response(car, normal)
                car.speed *= 1.3
            else:
                self.physics.apply_collision_response(car, normal)
            if remaining > 0:
                self.collision_system.move_with_substeps(car, remaining)
        car.update_sprite()

    def _activate_powerup(self, car):
        """Activa el power-up que lleva el auto."""
        ptype = car.held_powerup
        car.held_powerup = None

        if ptype == POWERUP_BOOST:
            car.apply_effect("boost", BOOST_DURATION)
        elif ptype == POWERUP_SHIELD:
            car.apply_effect("shield", SHIELD_DURATION)
        elif ptype == POWERUP_MISSILE:
            fx, fy = car.get_forward_vector()
            mx = car.x + fx * 30
            my = car.y + fy * 30
            self.missiles.append(Missile(mx, my, car.angle, car.player_id))
        elif ptype == POWERUP_OIL:
            fx, fy = car.get_forward_vector()
            ox = car.x - fx * 30
            oy = car.y - fy * 30
            self.oil_slicks.append(OilSlick(ox, oy, car.player_id))
        elif ptype == POWERUP_MINE:
            fx, fy = car.get_forward_vector()
            mx = car.x - fx * 35
            my = car.y - fy * 35
            self.mines.append(Mine(mx, my, car.player_id))
        elif ptype == POWERUP_EMP:
            for other in self.cars:
                if other.player_id == car.player_id:
                    continue
                dist = math.hypot(other.x - car.x, other.y - car.y)
                if dist < EMP_RANGE:
                    other.apply_effect("emp_slow", EMP_SLOW_DURATION)
                    if "boost" in other.active_effects:
                        del other.active_effects["boost"]
        elif ptype == POWERUP_MAGNET:
            car.apply_effect("magnet", MAGNET_DURATION)
        elif ptype == POWERUP_SLOWMO:
            car.apply_effect("slowmo", SLOWMO_DURATION)
        elif ptype == POWERUP_BOUNCE:
            car.apply_effect("bounce", BOUNCE_DURATION)
        elif ptype == POWERUP_AUTOPILOT:
            car.apply_effect("autopilot", AUTOPILOT_DURATION)
        elif ptype == POWERUP_TELEPORT:
            fx, fy = car.get_forward_vector()
            new_x = car.x + fx * TELEPORT_DISTANCE
            new_y = car.y + fy * TELEPORT_DISTANCE
            if self.track.is_on_track(new_x, new_y):
                car.x = new_x
                car.y = new_y
                car.update_sprite()
        elif ptype == POWERUP_SMART_MISSILE:
            target = self._find_leader_rival(car)
            if target:
                fx, fy = car.get_forward_vector()
                mx = car.x + fx * 30
                my = car.y + fy * 30
                self.smart_missiles.append(
                    SmartMissile(mx, my, car.angle, car.player_id, target))

    def _autopilot_steer(self, car):
        """Piloto automatico: dirige el auto hacia los waypoints."""
        wps = self.track.waypoints
        if not wps:
            return
        min_dist = float('inf')
        best_idx = 0
        for i, (wx, wy) in enumerate(wps):
            d = math.hypot(car.x - wx, car.y - wy)
            if d < min_dist:
                min_dist = d
                best_idx = i
        target_idx = (best_idx + 3) % len(wps)
        tx, ty = wps[target_idx]
        dx = tx - car.x
        dy = ty - car.y
        target_angle = math.degrees(math.atan2(dx, -dy)) % 360
        current = car.angle % 360
        diff = (target_angle - current + 180) % 360 - 180
        car.input_accelerate = 1.0
        if diff > 5:
            car.input_turn = 1.0
        elif diff < -5:
            car.input_turn = -1.0

    def _find_leader_rival(self, car):
        """Encuentra el auto rival mas avanzado en la carrera."""
        best = None
        best_score = -1
        for other in self.cars:
            if other.player_id == car.player_id or other.finished:
                continue
            score = other.laps * 1000 + other.next_checkpoint_index
            if score > best_score:
                best_score = score
                best = other
        return best

    def is_race_over(self):
        """Verifica si la carrera termino."""
        all_finished = all(car.finished for car in self.cars)
        if all_finished:
            return True
        if (self.winner and
                self.race_timer.total_time > self.winner.finish_time + 15):
            return True
        return False

    def flush_events(self):
        """Retorna y limpia los eventos pendientes."""
        events = self.pending_events
        self.pending_events = []
        return events
