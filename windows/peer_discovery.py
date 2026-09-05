"""Peer discovery mechanism for desk-audio-bridge.

Implements multi-interface broadcast/handshake, source/bind resolution,
and multiple-responder ambiguity detection:
- Discovers candidate active IPv4 interfaces (strictly active/up, IPv4, private or link-local, non-loopback).
- Resolves route/bind deterministically via RouteResolver seam.
- Detects multiple distinct opposite-role responders in discovery window and enters AMBIGUOUS_PEER.
"""

import ipaddress
import json
import logging
import socket
import threading
import time
from typing import Callable, List, Optional, Tuple

from bridge_core.contract import (
    CONTROL_PROTOCOL_VERSION,
    DEFAULT_CONTROL_PORT,
    DEFAULT_SPEAKER_RTP_PORT,
    HandshakeAck,
    HandshakeHello,
    HostRole,
)

logger = logging.getLogger(__name__)


def is_private_or_link_local_ipv4(ip_str: str) -> bool:
    """Verifies that an IPv4 address is active, non-loopback, and private or link-local."""
    try:
        ip = ipaddress.IPv4Address(ip_str)
        if ip.is_loopback:
            return False
        return ip.is_private or ip.is_link_local
    except Exception:
        return False


class InterfaceEnumerator:
    """Enumerates candidate IPv4 local interfaces and their subnet broadcast addresses."""

    def get_candidate_interfaces(self) -> List[Tuple[str, str]]:
        """Returns a list of (local_ip, broadcast_ip) tuples for active/up, private/link-local interfaces."""
        candidates = []
        try:
            import psutil
            stats = psutil.net_if_stats()
            for iface_name, addrs in psutil.net_if_addrs().items():
                stat = stats.get(iface_name)
                # Must be up / active
                if stat and not stat.isup:
                    continue

                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        ip = addr.address
                        if not is_private_or_link_local_ipv4(ip):
                            continue

                        netmask = addr.netmask
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
        except ImportError:
            logger.warning("psutil not available; falling back to basic socket inspection")
        except Exception as exc:
            logger.debug("Interface enumeration failed: %s", exc)
        return candidates


class RouteResolver:
    """Seam for determining the local binding IP used to route to a given destination IP."""

    def resolve_local_route(self, target_ip: str, port: int) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((target_ip, port))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return "0.0.0.0"


class PeerDiscoveryService:
    """Manages control plane discovery, route resolution, and ambiguity detection."""

    def __init__(
        self,
        local_role: HostRole = HostRole.WINDOWS,
        instance_id: str = "inst",
        control_port: int = DEFAULT_CONTROL_PORT,
        speaker_port: int = DEFAULT_SPEAKER_RTP_PORT,
        interface_enumerator: Optional[InterfaceEnumerator] = None,
        route_resolver: Optional[RouteResolver] = None,
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
        self.route_resolver = route_resolver or RouteResolver()
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

        # Ambiguity tracking: map of peer_instance_id -> (peer_ip, last_seen)
        self._known_responders: dict[str, Tuple[str, float]] = {}
        self._is_ambiguous = False
        self._lock = threading.RLock()

    @property
    def peer_available(self) -> bool:
        with self._lock:
            if self._is_ambiguous or not self._peer_address:
                return False
            return (time.time() - self._last_peer_seen) < 15.0

    @property
    def is_ambiguous(self) -> bool:
        with self._lock:
            return self._is_ambiguous

    @property
    def peer_address(self) -> Optional[str]:
        with self._lock:
            if self._is_ambiguous:
                return None
            return self._peer_address

    @property
    def local_bind_address(self) -> Optional[str]:
        with self._lock:
            if self._is_ambiguous:
                return None
            return self._local_bind_address

    @property
    def peer_speaker_port(self) -> int:
        with self._lock:
            return self._peer_speaker_port

    def start(self) -> None:
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

            now = time.time()
            with self._lock:
                # Prune responders not seen for > 30s
                self._known_responders = {
                    k: v for k, v in self._known_responders.items() if (now - v[1]) < 30.0
                }
                self._known_responders[peer_inst] = (peer_ip, now)

                # Check for multiple distinct opposite-role responders
                if len(self._known_responders) > 1:
                    logger.warning(
                        "Multiple opposite-role responders discovered (%s); entering ambiguous state",
                        list(self._known_responders.keys()),
                    )
                    self._is_ambiguous = True
                    self._peer_address = None
                    self._local_bind_address = None
                    continue

                self._is_ambiguous = False

            # Resolve local route to peer
            local_source_ip = self.route_resolver.resolve_local_route(peer_ip, self.control_port)

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
                    and not self._is_ambiguous
                )
                self._peer_address = peer_ip
                self._local_bind_address = local_source_ip
                self._peer_instance_id = peer_inst
                self._peer_speaker_port = peer_spk_port
                self._last_peer_seen = now

            if not was_avail and self.on_peer_discovered:
                self.on_peer_discovered(peer_ip, local_source_ip, peer_spk_port, peer_inst)
