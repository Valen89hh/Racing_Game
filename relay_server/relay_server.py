#!/usr/bin/env python3
"""
relay_server.py - Servidor relay UDP para multijugador por internet.

Reenvía paquetes entre jugadores sin procesar lógica de juego.
Usa salas con código de 4 caracteres (ej. "A3K9").

Requisitos: Solo Python 3.8+ stdlib (socket, select, struct).
Ejecución: python relay_server.py [--port 7777] [--max-rooms 100]
"""

import socket
import select
import struct
import time
import random
import argparse
import sys

# ── Comandos relay (mismos que relay_protocol.py) ──
RELAY_CREATE_ROOM  = 0xA0
RELAY_ROOM_CREATED = 0xA1
RELAY_JOIN_ROOM    = 0xA2
RELAY_JOIN_OK      = 0xA3
RELAY_JOIN_FAIL    = 0xA4
RELAY_LEAVE_ROOM   = 0xA5
RELAY_PEER_LEFT    = 0xA6
RELAY_HEARTBEAT    = 0xA7
RELAY_FORWARD      = 0xA8

RELAY_FAIL_NOT_FOUND = 1
RELAY_FAIL_FULL = 2

# Caracteres para room codes (sin confusables 0/O/1/I/L)
ROOM_CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
MAX_PEERS_PER_ROOM = 4
PEER_TIMEOUT = 10.0
CLEANUP_INTERVAL = 1.0


class Peer:
    """Un jugador conectado a una sala."""
    __slots__ = ('addr', 'slot', 'last_seen')

    def __init__(self, addr, slot):
        self.addr = addr
        self.slot = slot
        self.last_seen = time.time()


class Room:
    """Una sala de juego con host + hasta 3 clientes."""
    __slots__ = ('code', 'host', 'clients', 'created_at')

    def __init__(self, code, host_peer):
        self.code = code
        self.host = host_peer
        self.clients = {}  # slot → Peer
        self.created_at = time.time()

    def all_peers(self):
        """Retorna todos los peers (host + clientes)."""
        peers = [self.host]
        peers.extend(self.clients.values())
        return peers

    def next_slot(self):
        """Retorna el siguiente slot disponible (1-3) o None si está llena."""
        for s in range(1, MAX_PEERS_PER_ROOM):
            if s not in self.clients:
                return s
        return None

    def peer_count(self):
        return 1 + len(self.clients)


class RelayServer:
    """Servidor relay UDP single-threaded con select()."""

    def __init__(self, port=7777, max_rooms=100):
        self.port = port
        self.max_rooms = max_rooms
        self.sock = None

        # Room management
        self.rooms = {}          # code → Room
        self.addr_to_room = {}   # addr → (Room, slot)

        self._running = False
        self._last_cleanup = 0.0

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", self.port))
        self.sock.setblocking(False)
        self._running = True
        print(f"[RELAY] Started on port {self.port}")
        print(f"[RELAY] Max rooms: {self.max_rooms}, Peer timeout: {PEER_TIMEOUT}s")

    def run(self):
        """Main event loop."""
        self.start()
        try:
            while self._running:
                readable, _, _ = select.select([self.sock], [], [], 0.5)
                if readable:
                    self._read_packets()
                now = time.time()
                if now - self._last_cleanup >= CLEANUP_INTERVAL:
                    self._cleanup(now)
                    self._last_cleanup = now
        except KeyboardInterrupt:
            print("\n[RELAY] Shutting down...")
        finally:
            self.sock.close()
            print("[RELAY] Stopped")

    def _read_packets(self):
        """Lee todos los paquetes disponibles."""
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
            except (BlockingIOError, OSError):
                break

            if len(data) < 1:
                continue

            cmd = data[0]
            try:
                if cmd == RELAY_CREATE_ROOM:
                    self._handle_create(addr)
                elif cmd == RELAY_JOIN_ROOM:
                    self._handle_join(data, addr)
                elif cmd == RELAY_LEAVE_ROOM:
                    self._handle_leave(addr)
                elif cmd == RELAY_HEARTBEAT:
                    self._handle_heartbeat(addr)
                elif cmd == RELAY_FORWARD:
                    self._handle_forward(data, addr)
            except Exception as e:
                print(f"[RELAY] Error handling cmd 0x{cmd:02x} from {addr}: {e}")

    def _handle_create(self, addr):
        """Host solicita crear una sala."""
        # Si ya está en una sala, salir primero
        if addr in self.addr_to_room:
            self._remove_peer(addr)

        if len(self.rooms) >= self.max_rooms:
            # Sala llena global
            self._send(struct.pack("!BB", RELAY_JOIN_FAIL, RELAY_FAIL_FULL), addr)
            return

        # Generar código único
        code = self._generate_code()
        host_peer = Peer(addr, 0)
        room = Room(code, host_peer)
        self.rooms[code] = room
        self.addr_to_room[addr] = (room, 0)

        # Responder con código de sala
        resp = struct.pack("!B4s", RELAY_ROOM_CREATED, code.encode("ascii"))
        self._send(resp, addr)
        print(f"[RELAY] Room {code} created by {addr}")

    def _handle_join(self, data, addr):
        """Cliente se une a una sala existente."""
        if len(data) < 5:
            return

        code = data[1:5].decode("ascii", errors="replace")
        room = self.rooms.get(code)

        if not room:
            self._send(struct.pack("!BB", RELAY_JOIN_FAIL, RELAY_FAIL_NOT_FOUND), addr)
            return

        # Si ya está en esta sala, re-enviar OK
        if addr in self.addr_to_room:
            existing_room, existing_slot = self.addr_to_room[addr]
            if existing_room.code == code:
                self._send(struct.pack("!BB", RELAY_JOIN_OK, existing_slot), addr)
                return
            # Estaba en otra sala, salir primero
            self._remove_peer(addr)

        slot = room.next_slot()
        if slot is None:
            self._send(struct.pack("!BB", RELAY_JOIN_FAIL, RELAY_FAIL_FULL), addr)
            return

        peer = Peer(addr, slot)
        room.clients[slot] = peer
        self.addr_to_room[addr] = (room, slot)

        self._send(struct.pack("!BB", RELAY_JOIN_OK, slot), addr)
        print(f"[RELAY] {addr} joined room {code} as slot {slot} ({room.peer_count()}/{MAX_PEERS_PER_ROOM})")

    def _handle_leave(self, addr):
        """Peer sale voluntariamente."""
        if addr in self.addr_to_room:
            self._remove_peer(addr)

    def _handle_heartbeat(self, addr):
        """Actualiza timestamp del peer."""
        entry = self.addr_to_room.get(addr)
        if entry:
            room, slot = entry
            if slot == 0:
                room.host.last_seen = time.time()
            else:
                peer = room.clients.get(slot)
                if peer:
                    peer.last_seen = time.time()

    def _handle_forward(self, data, addr):
        """Reenvía paquete de juego a los destinatarios correctos."""
        if len(data) < 7:
            return

        entry = self.addr_to_room.get(addr)
        if not entry:
            return

        room, sender_slot = entry
        # Actualizar last_seen
        if sender_slot == 0:
            room.host.last_seen = time.time()
        else:
            peer = room.clients.get(sender_slot)
            if peer:
                peer.last_seen = time.time()

        target = data[5]
        payload = data[6:]

        # Reconstruir paquete con sender_slot en vez de target
        # El receptor sabrá quién envió el paquete
        def make_fwd(dest_slot_info):
            return struct.pack("!B4sB", RELAY_FORWARD,
                               room.code.encode("ascii"), sender_slot) + payload

        if target == 0xFF:
            # Broadcast: enviar a todos EXCEPTO al sender
            fwd = make_fwd(None)
            for peer in room.all_peers():
                if peer.addr != addr:
                    self._send(fwd, peer.addr)
        elif target == 0x00:
            # Al host
            if sender_slot != 0:
                fwd = make_fwd(None)
                self._send(fwd, room.host.addr)
        else:
            # A un slot específico
            peer = room.clients.get(target)
            if peer and peer.addr != addr:
                fwd = make_fwd(None)
                self._send(fwd, peer.addr)

    def _remove_peer(self, addr):
        """Remueve un peer de su sala y notifica a los demás."""
        entry = self.addr_to_room.pop(addr, None)
        if not entry:
            return

        room, slot = entry

        if slot == 0:
            # Host se fue → destruir sala entera
            print(f"[RELAY] Host left room {room.code}, destroying room")
            # Notificar a todos los clientes
            notify = struct.pack("!BB", RELAY_PEER_LEFT, 0)
            for client_peer in room.clients.values():
                self._send(notify, client_peer.addr)
                self.addr_to_room.pop(client_peer.addr, None)
            del self.rooms[room.code]
        else:
            # Cliente se fue → notificar al resto
            room.clients.pop(slot, None)
            print(f"[RELAY] Slot {slot} left room {room.code} ({room.peer_count()}/{MAX_PEERS_PER_ROOM})")
            notify = struct.pack("!BB", RELAY_PEER_LEFT, slot)
            for peer in room.all_peers():
                if peer.addr != addr:
                    self._send(notify, peer.addr)

    def _cleanup(self, now):
        """Limpia peers y salas que excedieron timeout."""
        to_remove = []
        for addr, (room, slot) in list(self.addr_to_room.items()):
            if slot == 0:
                if now - room.host.last_seen > PEER_TIMEOUT:
                    to_remove.append(addr)
            else:
                peer = room.clients.get(slot)
                if peer and now - peer.last_seen > PEER_TIMEOUT:
                    to_remove.append(addr)

        for addr in to_remove:
            print(f"[RELAY] Timeout: {addr}")
            self._remove_peer(addr)

    def _generate_code(self):
        """Genera un código de sala único de 4 caracteres."""
        for _ in range(100):
            code = "".join(random.choice(ROOM_CODE_CHARS) for _ in range(4))
            if code not in self.rooms:
                return code
        # Fallback extremo (nunca debería pasar)
        return "".join(random.choice(ROOM_CODE_CHARS) for _ in range(4))

    def _send(self, data, addr):
        """Envía datos a una dirección UDP."""
        try:
            self.sock.sendto(data, addr)
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description="Relay Server for Racing Game")
    parser.add_argument("--port", type=int, default=7777, help="UDP port (default: 7777)")
    parser.add_argument("--max-rooms", type=int, default=100, help="Max concurrent rooms")
    args = parser.parse_args()

    server = RelayServer(port=args.port, max_rooms=args.max_rooms)
    server.run()


if __name__ == "__main__":
    main()
