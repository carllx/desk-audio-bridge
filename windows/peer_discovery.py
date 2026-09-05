"""Peer discovery mechanism for desk-audio-bridge.

Implements lightweight UDP control handshake between Windows and Mac:
- Broadcasts / multicasts / sends HandshakeHello on local interfaces.
- Listens on DEFAULT_CONTROL_PORT.
- Replies to valid opposite-role HELLO with ACK.
- Resolves peer IP and verifies route without persisting any IP.
"""

import json
import logging
import socket
import threading
import time
from typing import Callable, Optional, Tuple

from .bridge_common import (
    CONTROL_PROTOCOL_VERSION,
    DEFAULT_CONTROL_PORT,
    DEFAULT_SPEAKER_RTP_PORT,
    HandshakeAck,
    HandshakeHello,
    HostRole,
)

logger = logging.getLogger(__name__)


class PeerDiscoveryService:
    """Manages control plane discovery and peer availability tracking."""

    def __init__(
        self,
        local_role: HostRole = HostRole.WINDOWS,
        instance_id: str = "win-inst",
        control_port: int = DEFAULT_CONTROL_PORT,
        speaker_port: int = DEFAULT_SPEAKER_RTP_PORT,
        on_peer_discovered: Optional[Callable[[str, int, str], None]] = None,
        on_peer_lost: Optional[Callable[[], None]] = None,
    ):
        self.local_role = local_role
        self.target_role = (
            HostRole.MACOS if local_role == HostRole.WINDOWS else HostRole.WINDOWS
        )
        self.instance_id = instance_id
        self.control_port = control_port
        self.speaker_port = speaker_port
        self.on_peer_discovered = on_peer_discovered
        self.on_peer_lost = on_peer_lost

        self._running = False
        self._sock: Optional[socket.socket] = None
        self._recv_thread: Optional[threading.Thread] = None

        self._peer_address: Optional[str] = None
        self._peer_speaker_port: int = speaker_port
        self._peer_instance_id: Optional[str] = None
        self._last_peer_seen: float = 0.0
        self._lock = threading.Lock()

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
    def peer_speaker_port(self) -> int:
        with self._lock:
            return self._peer_speaker_port

    def start(self) -> None:
        """Starts the control socket and discovery receiver thread."""
        if self._running:
            return

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            self._sock.bind(("", self.control_port))
        except Exception as exc:
            logger.error("Failed to bind discovery socket on port %d: %s", self.control_port, exc)
            self._sock.close()
            self._sock = None
            raise

        self._running = True
        self._recv_thread = threading.Thread(target=self._listen_loop, daemon=True, name="PeerDiscoveryRecv")
        self._recv_thread.start()

    def stop(self) -> None:
        """Stops the discovery listener."""
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._recv_thread and self._recv_thread.is_alive():
            self._recv_thread.join(timeout=1.0)
        self._recv_thread = None

    def broadcast_hello(self, destination: str = "255.255.255.255") -> None:
        """Sends a HandshakeHello broadcast or targeted packet."""
        if not self._running or not self._sock:
            return

        hello = HandshakeHello(
            version=CONTROL_PROTOCOL_VERSION,
            role=self.local_role.value,
            instance_id=self.instance_id,
            speaker_port=self.speaker_port,
        )
        data = json.dumps(hello.to_dict()).encode("utf-8")
        try:
            self._sock.sendto(data, (destination, self.control_port))
        except Exception as exc:
            logger.debug("Failed sending HELLO to %s: %s", destination, exc)

    def _listen_loop(self) -> None:
        while self._running and self._sock:
            try:
                data, addr = self._sock.recvfrom(4096)
            except (OSError, socket.error):
                break

            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue

            msg_type = msg.get("role")
            version = msg.get("version")
            if version != CONTROL_PROTOCOL_VERSION:
                continue

            # Check if this packet is from our opposite peer
            if msg_type == self.target_role.value:
                peer_inst = msg.get("instance_id", "")
                peer_spk_port = msg.get("speaker_port", DEFAULT_SPEAKER_RTP_PORT)
                peer_ip = addr[0]

                # If HELLO, reply with ACK
                if "peer_instance_id" not in msg:
                    ack = HandshakeAck(
                        version=CONTROL_PROTOCOL_VERSION,
                        role=self.local_role.value,
                        instance_id=self.instance_id,
                        speaker_port=self.speaker_port,
                        peer_instance_id=peer_inst,
                    )
                    ack_bytes = json.dumps(ack.to_dict()).encode("utf-8")
                    try:
                        self._sock.sendto(ack_bytes, (peer_ip, self.control_port))
                    except Exception as exc:
                        logger.debug("Failed replying ACK to %s: %s", peer_ip, exc)

                with self._lock:
                    was_avail = (time.time() - self._last_peer_seen) < 15.0 and self._peer_address is not None
                    self._peer_address = peer_ip
                    self._peer_instance_id = peer_inst
                    self._peer_speaker_port = peer_spk_port
                    self._last_peer_seen = time.time()

                if not was_avail and self.on_peer_discovered:
                    self.on_peer_discovered(peer_ip, peer_spk_port, peer_inst)
