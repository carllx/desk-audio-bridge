"""Peer discovery mechanism for desk-audio-bridge (Windows re-export layer).

Re-exports platform-neutral discovery implementation from bridge_core.peer_discovery
for backward compatibility.
"""

from bridge_core.peer_discovery import (
    CONTROL_PROTOCOL_VERSION,
    DEFAULT_CONTROL_PORT,
    DEFAULT_SPEAKER_RTP_PORT,
    HandshakeAck,
    HandshakeHello,
    HostRole,
    InterfaceClassifier,
    InterfaceEnumerator,
    InterfaceMedium,
    PeerDiscoveryService,
    RouteResolver,
    is_eligible_onlink_ipv4,
)

__all__ = [
    "CONTROL_PROTOCOL_VERSION",
    "DEFAULT_CONTROL_PORT",
    "DEFAULT_SPEAKER_RTP_PORT",
    "HandshakeAck",
    "HandshakeHello",
    "HostRole",
    "InterfaceClassifier",
    "InterfaceEnumerator",
    "InterfaceMedium",
    "PeerDiscoveryService",
    "RouteResolver",
    "is_eligible_onlink_ipv4",
]

