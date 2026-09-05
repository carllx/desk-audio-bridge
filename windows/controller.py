"""Production Audio Bridge Controller for Windows.

Implements the single-instance controller lifecycle:
- Start: Idempotently enables speaker path and reconciles.
- Stop: Idempotently stops owned pipeline and sets STOPPED_BY_USER.
- Status: Read-only query of controller, peer, and speaker state without side effects.
- Singleton guard: Ensures only one controller instance runs per host.
- Ownership: Tracks and terminates ONLY owned child processes.
"""

import json
import logging
import os
import sys
import threading
import time
from typing import Optional

from .bridge_common import (
    DEFAULT_CONTROL_PORT,
    DEFAULT_SPEAKER_RTP_PORT,
    ControllerStatus,
    DesiredState,
    HostRole,
    LifecycleState,
    PathState,
)
from .device_resolver import WindowsDeviceResolver
from .peer_discovery import PeerDiscoveryService
from .process_runner import ProcessRunner, WindowsOwnedProcessRunner
from .speaker_pipeline import SpeakerPipelineBuilder

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = os.path.join(os.environ.get("LOCALAPPDATA", "."), "desk-audio-bridge", "controller_state.json")
DEFAULT_LOCK_PORT = 50105


class SingleInstanceLock:
    """Guarantees controller singleton execution per machine via local socket bind."""

    def __init__(self, port: int = DEFAULT_LOCK_PORT):
        self.port = port
        self._sock = None

    def acquire(self) -> bool:
        import socket
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.bind(("127.0.0.1", self.port))
            return True
        except (OSError, socket.error):
            self._sock = None
            return False

    def release(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


class WindowsBridgeController:
    """The central Windows controller for desk-audio-bridge."""

    def __init__(
        self,
        state_file: str = DEFAULT_STATE_FILE,
        process_runner: Optional[ProcessRunner] = None,
        device_resolver: Optional[WindowsDeviceResolver] = None,
        pipeline_builder: Optional[SpeakerPipelineBuilder] = None,
        discovery_service: Optional[PeerDiscoveryService] = None,
        lock_port: int = DEFAULT_LOCK_PORT,
    ):
        self.state_file = state_file
        self.process_runner = process_runner or WindowsOwnedProcessRunner()
        self.device_resolver = device_resolver or WindowsDeviceResolver()
        self.pipeline_builder = pipeline_builder or SpeakerPipelineBuilder()
        self.lock_port = lock_port
        self._singleton_lock = SingleInstanceLock(port=lock_port)

        self._desired_state = self._load_persisted_desired_state()
        self._controller_state = LifecycleState.STOPPED
        self._speaker_path_state = PathState.IDLE
        self._last_actionable_error: Optional[str] = None
        self._speaker_child_pid: Optional[int] = None
        self._lock = threading.RLock()

        # Wire discovery service
        self.discovery_service = discovery_service or PeerDiscoveryService(
            local_role=HostRole.WINDOWS,
            instance_id=f"win-{os.getpid()}-{int(time.time())}",
            on_peer_discovered=self._on_peer_discovered,
        )

    def _load_persisted_desired_state(self) -> DesiredState:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    val = data.get("desired_state")
                    if val in (DesiredState.ENABLED.value, DesiredState.STOPPED_BY_USER.value):
                        return DesiredState(val)
            except Exception as exc:
                logger.debug("Could not read state file: %s", exc)
        return DesiredState.STOPPED_BY_USER

    def _persist_desired_state(self, state: DesiredState) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump({"desired_state": state.value}, f)
        except Exception as exc:
            logger.warning("Could not persist desired state: %s", exc)

    def start(self) -> bool:
        """Idempotently enables the controller and triggers reconcile."""
        with self._lock:
            if not self._singleton_lock.acquire():
                # Another instance is already running or holding the lock
                logger.info("Controller singleton already active on host")
                self._desired_state = DesiredState.ENABLED
                self._persist_desired_state(DesiredState.ENABLED)
                return True

            self._desired_state = DesiredState.ENABLED
            self._persist_desired_state(DesiredState.ENABLED)
            self._controller_state = LifecycleState.STARTING
            self._last_actionable_error = None

            # Start discovery
            try:
                self.discovery_service.start()
            except Exception as exc:
                self._last_actionable_error = f"Discovery start failed: {exc}"
                self._controller_state = LifecycleState.ERROR

            self.reconcile()
            return True

    def stop(self) -> bool:
        """Idempotently stops the speaker pipeline and sets STOPPED_BY_USER."""
        with self._lock:
            self._desired_state = DesiredState.STOPPED_BY_USER
            self._persist_desired_state(DesiredState.STOPPED_BY_USER)

            # Stop owned speaker pipeline child
            if self._speaker_child_pid is not None:
                self.process_runner.stop_process(self._speaker_child_pid)
                self._speaker_child_pid = None
            self._speaker_path_state = PathState.STOPPED

            # Stop discovery
            self.discovery_service.stop()

            self._controller_state = LifecycleState.STOPPED
            self._singleton_lock.release()
            return True

    def get_status(self) -> ControllerStatus:
        """Pure read-only query of controller status without side-effects."""
        with self._lock:
            owned_count = 1 if (self._speaker_child_pid and self.process_runner.is_running(self._speaker_child_pid)) else 0
            return ControllerStatus(
                controller_state=self._controller_state.value,
                desired_state=self._desired_state.value,
                role=HostRole.WINDOWS.value,
                peer_available=self.discovery_service.peer_available,
                peer_address=self.discovery_service.peer_address,
                speaker_path_state=self._speaker_path_state.value,
                speaker_target_port=self.discovery_service.peer_speaker_port,
                last_actionable_error=self._last_actionable_error,
                owned_children_count=owned_count,
            )

    def reconcile(self) -> None:
        """Idempotently brings actual state toward desired state."""
        with self._lock:
            if self._desired_state == DesiredState.STOPPED_BY_USER:
                if self._speaker_child_pid is not None:
                    self.process_runner.stop_process(self._speaker_child_pid)
                    self._speaker_child_pid = None
                self._speaker_path_state = PathState.STOPPED
                self._controller_state = LifecycleState.STOPPED
                return

            # Desired state is ENABLED
            if not self.pipeline_builder.is_gstreamer_available():
                self._last_actionable_error = "GStreamer binary not found at configured path"
                self._controller_state = LifecycleState.ERROR
                self._speaker_path_state = PathState.FAILED
                return

            if not self.discovery_service.peer_available:
                # Peer not discovered yet; broadcast hello and wait in DISCOVERING
                self._controller_state = LifecycleState.DISCOVERING
                self.discovery_service.broadcast_hello()
                if self._speaker_child_pid is not None:
                    self.process_runner.stop_process(self._speaker_child_pid)
                    self._speaker_child_pid = None
                    self._speaker_path_state = PathState.IDLE
                return

            # Peer is available; resolve playback endpoint
            endpoint_id = self.device_resolver.resolve_default_playback_endpoint_id()
            if not endpoint_id:
                self._last_actionable_error = "Windows Playback Source endpoint resolution failed"
                self._controller_state = LifecycleState.ERROR
                self._speaker_path_state = PathState.FAILED
                return

            # Verify if pipeline already running
            if self._speaker_child_pid and self.process_runner.is_running(self._speaker_child_pid):
                self._controller_state = LifecycleState.ACTIVE
                self._speaker_path_state = PathState.RUNNING
                return

            # Create pipeline child
            target_ip = self.discovery_service.peer_address
            target_port = self.discovery_service.peer_speaker_port
            cmd = self.pipeline_builder.build_sender_command(
                target_host=target_ip,
                target_port=target_port,
                device_id=endpoint_id,
            )

            try:
                pid = self.process_runner.start_process(cmd)
                self._speaker_child_pid = pid
                self._speaker_path_state = PathState.RUNNING
                self._controller_state = LifecycleState.ACTIVE
                self._last_actionable_error = None
            except Exception as exc:
                self._last_actionable_error = f"Failed to start speaker pipeline: {exc}"
                self._speaker_path_state = PathState.FAILED
                self._controller_state = LifecycleState.ERROR

    def _on_peer_discovered(self, peer_ip: str, peer_port: int, peer_inst: str) -> None:
        """Callback when discovery receives peer greeting."""
        with self._lock:
            if self._desired_state == DesiredState.ENABLED:
                self.reconcile()
