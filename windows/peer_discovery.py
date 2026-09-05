"""Peer discovery mechanism for desk-audio-bridge.

Implements multi-interface broadcast/handshake and source/bind resolution:
- Discovers candidate active IPv4 interfaces (excluding loopback).
- Sends HandshakeHello to subnet broadcast and link-local targets from each candidate interface.
- Includes local source IP hint in handshake packets.
- On receiving HELLO/ACK from the opposite role, records both:
  1. peer_address: the incoming socket address of the peer.
  2. local_bind_address: the local interface address that successfully communicated with this peer.
- Does NOT store or hardcode IP addresses or interface indices in persistent SSOT.
"""

import ipaddress
import json
import logging
import socket
import threading
import time
from typing import Callable, List, Optional, Tuple

import psutil

from bridge_core.contract import (
    CONTROL_PROTOCOL_VERSION,
    DEFAULT_CONTROL_PORT,
    DEFAULT_SPEAKER_RTP_PORT,
    HandshakeAck,
    HandshakeHello,
    HostRole,
)

logger = logging.getLogger(__name__)


class InterfaceEnumerator:
    """Enumerates candidate IPv4 local interfaces and their subnet broadcast addresses."""

    def get_candidate_interfaces(self) -> List[Tuple[str, str]]:
        """Returns a list of (local_ip, broadcast_ip) tuples for active non-loopback IPv4 interfaces."""
        candidates = []
        try:
            for iface_name, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        ip = addr.address
                        netmask = addr.netmask
                        if ip.startswith("127."):
                            continue
                        # Determine broadcast address
                        broadcast = None
                        if addr.broadcast:
                            broadcast = addr.broadcast
                        elif netmask:
                            try:
                                net = ipaddress.IPv4Network((ip, netmask), strict=False)
                                broadcast = str(net.broadcast_address)
                            except Exception:
                                pass
                        if not broadcast:
                            broadcast = "255.255.255.255"
                        candidates.append((ip, broadcast))
        except Exception as exc:
            logger.debug("Failed to enumerate network interfaces: %s", exc)
        return candidates


class PeerDiscoveryService:
    """Manages control plane discovery and peer/local address resolution."""

    def __init__(
        self,
        local_role: HostRole = HostRole.WINDOWS,
        instance_id: str = "inst",
        control_port: int = DEFAULT_CONTROL_PORT,
        speaker_port: int = DEFAULT_SPEAKER_RTP_PORT,
        interface_enumerator: Optional[InterfaceEnumerator] = None,
        on_peer_discovered: Optional[Callable[[str, str, int, str], None]] = None,
        on_peer_lost: Optional[Callable[[], None]] = None,
    ):
        self.local_role = local_role
        self.target_role = (
            HostRole.MACOS if local_role == HostRole.WINDOWS else HostRole.WINDOWS
        )
        self.instance_id = instance_id
        self.control_port = control_port
        self.speaker_port = speaker_port
        self.enumerator = interface_enumerator or InterfaceEnumerator()
        self.on_peer_discovered = on_peer_discovered
        self.on_peer_lost = on_peer_lost

        self._running = False
        self._listener_sock: Optional[socket.socket] = None
        self._recv_thread: Optional[threading.Thread] = None

        self._peer_address: Optional[str] = None
        self._local_bind_address: Optional[str] = None
        self._peer_speaker_port: int = speaker_port
        self._peer_instance_id: Optional[str] = None
        self._last_peer_seen: float = 0.0
        self._lock = threading.RLock()

    @property
    def peer_available(self) -> bool:
        with self._lock:
            if not self._peer_address:
                return False
            return (time.time() - self._last_peer_seen) < 15.0

    @property
    def peer_address(self) -> Optional[str]:
        with self._lock:
            return self._peer_address

    @property
    def local_bind_address(self) -> Optional[str]:
        with self._lock:
            return self._local_bind_address

    @property
    def peer_speaker_port(self) -> int:
        with self._lock:
            return self._peer_speaker_port

    def start(self) -> None:
        """Starts the control listener socket."""
        with self._lock:
            if self._running:
                return

            self._listener_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._listener_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._listener_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                self._listener_sock.bind(("", self.control_port))
            except Exception as exc:
                logger.error("Failed to bind discovery socket on port %d: %s", self.control_port, exc)
                self._listener_sock.close()
                self._listener_sock = None
                raise

            self._running = True
            self._recv_thread = threading.Thread(
                target=self._listen_loop, daemon=True, name="PeerDiscoveryRecv"
            )
            self._recv_thread.start()

    def stop(self) -> None:
        """Stops the discovery listener."""
        with self._lock:
            self._running = False
            if self._listener_sock:
                try:
                    self._listener_sock.close()
                except Exception:
                    pass
                self._listener_sock = None
            if self._recv_thread and self._recv_thread.is_alive():
                self._recv_thread.join(timeout=1.0)
            self._recv_thread = None

    def broadcast_hello(self) -> None:
        """Broadcasts HandshakeHello across all active candidate interfaces."""
        if not self._running:
            return

        candidates = self.enumerator.get_candidate_interfaces()
        if not candidates:
            candidates = [("0.0.0.0", "255.255.255.255")]

        for local_ip, bcast_ip in candidates:
            hello = HandshakeHello(
                version=CONTROL_PROTOCOL_VERSION,
                role=self.local_role.value,
                instance_id=self.instance_id,
                speaker_port=self.speaker_port,
                source_ip=local_ip if local_ip != "0.0.0.0" else None,
            )
            data = json.dumps(hello.to_dict()).encode("utf-8")
            
            # Send from a temporary socket bound to local_ip if specific
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                if local_ip != "0.0.0.0":
                    try:
                        sock.bind((local_ip, 0))
                    except Exception:
                        pass
                sock.sendto(data, (bcast_ip, self.control_port))
                # Also send to global broadcast
                if bcast_ip != "255.255.255.255":
                    sock.sendto(data, ("255.255.255.255", self.control_port))
            except Exception as exc:
                logger.debug("Failed broadcast on %s -> %s: %s", local_ip, bcast_ip, exc)
            finally:
                if sock:
                    sock.close()

    def _listen_loop(self) -> None:
        while self._running and self._listener_sock:
            try:
                data, addr = self._listener_sock.recvfrom(4096)
            except (OSError, socket.error):
                break

            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue

            msg_role = msg.get("role")
            version = msg.get("version")
            if version != CONTROL_PROTOCOL_VERSION or msg_role != self.target_role.value:
                continue

            peer_ip = addr[0]
            peer_inst = msg.get("instance_id", "")
            peer_spk_port = msg.get("speaker_port", DEFAULT_SPEAKER_RTP_PORT)

            # Determine local routing source IP to this specific peer
            local_source_ip = self._resolve_local_route_to(peer_ip)

            # Reply with ACK if this was a HELLO
            if "peer_instance_id" not in msg:
                ack = HandshakeAck(
                    version=CONTROL_PROTOCOL_VERSION,
                    role=self.local_role.value,
                    instance_id=self.instance_id,
                    speaker_port=self.speaker_port,
                    peer_instance_id=peer_inst,
                    source_ip=local_source_ip,
                )
                ack_bytes = json.dumps(ack.to_dict()).encode("utf-8")
                try:
                    self._listener_sock.sendto(ack_bytes, (peer_ip, self.control_port))
                except Exception as exc:
                    logger.debug("Failed sending ACK to %s: %s", peer_ip, exc)

            with self._lock:
                was_avail = (
                    (time.time() - self._last_peer_seen) < 15.0
                    and self._peer_address is not None
                )
                self._peer_address = peer_ip
                self._local_bind_address = local_source_ip
                self._peer_instance_id = peer_inst
                self._peer_speaker_port = peer_spk_port
                self._last_peer_seen = time.time()

            if not was_avail and self.on_peer_discovered:
                self.on_peer_discovered(peer_ip, local_source_ip, peer_spk_port, peer_inst)

    def _resolve_local_route_to(self, target_ip: str) -> str:
        """Determines the exact local interface IP used to route to target_ip."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target_ip, self.control_port))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return "0.0.0.0"
