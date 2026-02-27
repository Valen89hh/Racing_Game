"""
relay_socket.py - Adaptador drop-in que reemplaza socket.socket para relay.

RelaySocket envuelve/desenvuelve paquetes con el header del relay de forma
transparente. GameServer y GameClient lo usan sin saber que están detrás
de un relay.

Flujo correcto:
    1. Crear RelaySocket (aún no conectado)
    2. Llamar create_room() o join_room() (usa el socket interno)
    3. Llamar start() (inicia hilos de heartbeat y recepción)
    4. Usar sendto/recvfrom normalmente

Esto garantiza que el mismo socket UDP (mismo puerto local) se usa
tanto para el handshake como para el tráfico de juego.
"""

import socket
import struct
import threading
import time
import queue

from networking.relay_protocol import (
    RELAY_FORWARD, RELAY_PEER_LEFT, RELAY_HEARTBEAT,
    RELAY_ROOM_CREATED, RELAY_JOIN_OK, RELAY_JOIN_FAIL,
    TARGET_HOST, TARGET_BROADCAST,
    pack_forward, unpack_forward, pack_heartbeat,
    pack_create_room, pack_join_room, pack_leave_room,
    unpack_room_created, unpack_join_ok, unpack_join_fail, unpack_peer_left,
    get_relay_cmd,
)
from networking.protocol import pack_disconnect


class RelaySocket:
    """Socket UDP que envuelve/desenvuelve paquetes relay transparentemente.

    Simula un socket regular para que GameServer/GameClient no necesiten cambios.
    """

    def __init__(self, relay_addr, room_code=None, is_host=False):
        """
        Args:
            relay_addr: (ip, port) del relay server
            room_code: código de sala (puede ser None si se va a crear)
            is_host: True si es el host de la sala
        """
        self.relay_addr = relay_addr
        self.room_code = room_code or ""
        self.is_host = is_host
        self._my_slot = 0 if is_host else -1

        # Socket UDP real — se usa para TODO (handshake + juego)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.1)

        # Cola de paquetes desenvueltos para recvfrom
        self._recv_queue = queue.Queue()

        # Mapeo slot ↔ fake addr
        self._slot_to_addr = {}  # slot → ("relay_peer", slot)
        self._addr_to_slot = {}  # ("relay_peer", slot) → slot

        # Estado
        self._closed = False
        self._timeout = None

        # Heartbeat thread
        self._hb_thread = None
        self._hb_running = False

        # Receiver thread (desenvuelve paquetes relay y los encola)
        self._recv_thread = None
        self._recv_running = False

    # ── Handshake con el relay (ANTES de start()) ──

    def create_room(self, timeout=5.0):
        """Crea una sala en el relay. Retorna room_code o None.

        Usa el socket interno, así el relay registra ESTA dirección.
        """
        self._sock.settimeout(min(timeout, 2.0))
        start = time.time()
        self._sock.sendto(pack_create_room(), self.relay_addr)

        while time.time() - start < timeout:
            try:
                data, _ = self._sock.recvfrom(256)
            except socket.timeout:
                self._sock.sendto(pack_create_room(), self.relay_addr)
                continue

            cmd = get_relay_cmd(data)
            if cmd == RELAY_ROOM_CREATED:
                self.room_code = unpack_room_created(data)
                self.is_host = True
                self._my_slot = 0
                self._sock.settimeout(0.1)
                return self.room_code
            elif cmd == RELAY_JOIN_FAIL:
                self._sock.settimeout(0.1)
                return None

        self._sock.settimeout(0.1)
        return None

    def join_room(self, room_code, timeout=5.0):
        """Se une a una sala existente. Retorna slot (int) o None.

        Usa el socket interno, así el relay registra ESTA dirección.
        """
        self.room_code = room_code
        self._sock.settimeout(min(timeout, 2.0))
        start = time.time()
        self._sock.sendto(pack_join_room(room_code), self.relay_addr)

        while time.time() - start < timeout:
            try:
                data, _ = self._sock.recvfrom(256)
            except socket.timeout:
                self._sock.sendto(pack_join_room(room_code), self.relay_addr)
                continue

            cmd = get_relay_cmd(data)
            if cmd == RELAY_JOIN_OK:
                self._my_slot = unpack_join_ok(data)
                self.is_host = False
                self._sock.settimeout(0.1)
                return self._my_slot
            elif cmd == RELAY_JOIN_FAIL:
                self._sock.settimeout(0.1)
                return None

        self._sock.settimeout(0.1)
        return None

    # ── Iniciar hilos (DESPUÉS del handshake) ──

    def start(self):
        """Inicia los hilos de heartbeat y recepción."""
        self._hb_running = True
        self._recv_running = True
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._hb_thread.start()
        self._recv_thread.start()

    def _get_fake_addr(self, slot):
        """Retorna fake addr para un slot. Crea si no existe."""
        if slot not in self._slot_to_addr:
            addr = ("relay_peer", slot)
            self._slot_to_addr[slot] = addr
            self._addr_to_slot[addr] = slot
        return self._slot_to_addr[slot]

    def _get_slot(self, addr):
        """Retorna slot para una dirección. Retorna TARGET_HOST si no se encuentra."""
        return self._addr_to_slot.get(addr, TARGET_HOST)

    # ── API compatible con socket.socket ──

    def bind(self, addr):
        """No-op: relay no necesita bind local."""
        pass

    def settimeout(self, timeout):
        """Configura timeout para recvfrom."""
        self._timeout = timeout

    def setsockopt(self, *args):
        """No-op."""
        pass

    def sendto(self, data, addr):
        """Envía datos a un peer específico a través del relay."""
        if self._closed:
            raise OSError("Socket closed")

        slot = self._get_slot(addr)
        if not self.is_host:
            target = TARGET_HOST
        else:
            target = slot

        pkt = pack_forward(self.room_code, target, data)
        self._sock.sendto(pkt, self.relay_addr)

    def sendto_broadcast(self, data):
        """Envía datos a todos los peers (broadcast) a través del relay."""
        if self._closed:
            raise OSError("Socket closed")
        pkt = pack_forward(self.room_code, TARGET_BROADCAST, data)
        self._sock.sendto(pkt, self.relay_addr)

    def recvfrom(self, bufsize):
        """Recibe el siguiente paquete desenvuelto. Bloquea según timeout."""
        if self._closed:
            raise OSError("Socket closed")
        try:
            data, addr = self._recv_queue.get(timeout=self._timeout)
            return data, addr
        except queue.Empty:
            raise socket.timeout("timed out")

    def close(self):
        """Cierra el socket y detiene hilos."""
        if self._closed:
            return
        self._closed = True
        self._hb_running = False
        self._recv_running = False

        # Enviar LEAVE al relay
        if self.room_code:
            try:
                self._sock.sendto(pack_leave_room(self.room_code), self.relay_addr)
            except OSError:
                pass

        try:
            self._sock.close()
        except OSError:
            pass

    # ── Hilos internos ──

    def _heartbeat_loop(self):
        """Envía heartbeat al relay cada 3 segundos."""
        while self._hb_running and not self._closed:
            try:
                self._sock.sendto(pack_heartbeat(self.room_code), self.relay_addr)
            except OSError:
                pass
            for _ in range(30):
                if not self._hb_running:
                    break
                time.sleep(0.1)

    def _recv_loop(self):
        """Recibe paquetes del relay, los desenvuelve y los encola."""
        while self._recv_running and not self._closed:
            try:
                data, addr = self._sock.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                break

            if len(data) < 1:
                continue

            cmd = get_relay_cmd(data)

            if cmd == RELAY_FORWARD:
                if len(data) < 7:
                    continue
                _, sender_slot, payload = unpack_forward(data)
                fake_addr = self._get_fake_addr(sender_slot)
                self._recv_queue.put((payload, fake_addr))

            elif cmd == RELAY_PEER_LEFT:
                if len(data) >= 2:
                    left_slot = unpack_peer_left(data)
                    fake_addr = self._get_fake_addr(left_slot)
                    disconnect_pkt = pack_disconnect()
                    self._recv_queue.put((disconnect_pkt, fake_addr))
