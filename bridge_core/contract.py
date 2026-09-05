"""Shared cross-platform controller contract for desk-audio-bridge.

Defines protocol constants, state enums, status structures, and handshake models
shared by both Windows and macOS controller implementations.
"""

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Optional

# Control plane protocol constants
CONTROL_PROTOCOL_VERSION = 1
DEFAULT_CONTROL_PORT = 50100
DEFAULT_SPEAKER_RTP_PORT = 5004

# Local IPC control surface
DEFAULT_LOCAL_IPC_PORT = 50106
DEFAULT_SINGLETON_PORT = 50105

# RTP L16 canonical audio parameters
CANONICAL_SAMPLE_RATE = 48000
CANONICAL_CHANNELS = 2
CANONICAL_PAYLOAD_TYPE = 96
CANONICAL_ENCODING_NAME = "L16"


class HostRole(str, Enum):
    WINDOWS = "windows"
    MACOS = "macos"


class DesiredState(str, Enum):
    ENABLED = "ENABLED"
    STOPPED_BY_USER = "STOPPED_BY_USER"


class LifecycleState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    DISCOVERING = "DISCOVERING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    AMBIGUOUS_PEER = "AMBIGUOUS_PEER"
    ERROR = "ERROR"


class PathState(str, Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


@dataclass
class HandshakeHello:
    version: int
    role: str
    instance_id: str
    speaker_port: int
    source_ip: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HandshakeAck:
    version: int
    role: str
    instance_id: str
    speaker_port: int
    peer_instance_id: str
    source_ip: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ControllerStatus:
    controller_state: str
    desired_state: str
    role: str
    peer_available: bool
    peer_address: Optional[str]
    local_bind_address: Optional[str]
    speaker_path_state: str
    speaker_target_port: int
    last_actionable_error: Optional[str]
    owned_children_count: int
    owner_pid: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
