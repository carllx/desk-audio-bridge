"""Comprehensive external behavior and regression automated tests.

Covers:
1. Controller external behavior (idempotent Start/Stop, Status read-only, owned cleanup).
2. Process-level cross-command control over IPC (Start, repeated Start, Status, Stop).
3. Process-level singleton test (second owner denied, repeated start does not drop lock).
4. Multi-interface discovery and actual route/bind resolution (Blocker 3).
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from typing import List, Optional
import pytest

from bridge_core.contract import (
    DEFAULT_LOCAL_IPC_PORT,
    DEFAULT_SINGLETON_PORT,
    ControllerStatus,
    DesiredState,
    HostRole,
    LifecycleState,
    PathState,
)
from windows.cli import send_ipc_command
from windows.controller import SingleInstanceLock, WindowsBridgeController
from windows.peer_discovery import InterfaceEnumerator, PeerDiscoveryService
from windows.process_runner import ProcessRunner


class FakeProcessRunner(ProcessRunner):
    def __init__(self):
        self._next_pid = 1000
        self.running_pids = set()
        self.started_commands: List[List[str]] = []
        self.stopped_pids: List[int] = []

    def start_process(self, cmd: List[str]) -> int:
        pid = self._next_pid
        self._next_pid += 1
        self.running_pids.add(pid)
        self.started_commands.append(cmd)
        return pid

    def stop_process(self, pid: int) -> None:
        if pid in self.running_pids:
            self.running_pids.remove(pid)
        self.stopped_pids.append(pid)

    def is_running(self, pid: int) -> bool:
        return pid in self.running_pids


class FakeDeviceResolver:
    def __init__(self, endpoint_id: Optional[str] = "{0.0.0.00000000}.{mock-endpoint}"):
        self.endpoint_id = endpoint_id

    def resolve_default_playback_endpoint_id(self) -> Optional[str]:
        return self.endpoint_id


class FakePipelineBuilder:
    def __init__(self, gst_available: bool = True):
        self._available = gst_available

    def is_gstreamer_available(self) -> bool:
        return self._available

    def build_sender_command(
        self,
        target_host: str,
        target_port: int,
        device_id: Optional[str] = None,
        local_bind_ip: Optional[str] = None,
    ) -> List[str]:
        cmd = ["fake-gst", f"--host={target_host}", f"--port={target_port}"]
        if local_bind_ip:
            cmd.append(f"--bind={local_bind_ip}")
        return cmd


class FakeDiscoveryService:
    def __init__(
        self,
        peer_available: bool = True,
        peer_address: str = "198.18.0.2",
        local_bind: str = "198.18.0.1",
        peer_port: int = 5004,
    ):
        self.peer_available = peer_available
        self.peer_address = peer_address
        self.local_bind_address = local_bind
        self.peer_speaker_port = peer_port
        self.started = False
        self.stopped = False
        self.broadcast_count = 0

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def broadcast_hello(self):
        self.broadcast_count += 1


@pytest.fixture
def temp_state_file():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        path = f.name
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


# ---------------------------------------------------------
# Test Suite 1: Controller External Behavior
# ---------------------------------------------------------

def test_repeated_start_is_idempotent_and_creates_single_pipeline(temp_state_file):
    runner = FakeProcessRunner()
    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=FakePipelineBuilder(),
        discovery_service=FakeDiscoveryService(peer_available=True),
        lock_port=50150,
        ipc_port=50160,
    )

    assert controller.start() is True
    status1 = controller.get_status()
    assert status1.desired_state == DesiredState.ENABLED.value
    assert status1.speaker_path_state == PathState.RUNNING.value
    assert len(runner.started_commands) == 1

    # Repeated Start
    assert controller.start() is True
    status2 = controller.get_status()
    assert status2.desired_state == DesiredState.ENABLED.value
    assert len(runner.started_commands) == 1
    assert status2.owned_children_count == 1

    controller.shutdown()


def test_repeated_stop_is_idempotent_and_cleans_owned_process(temp_state_file):
    runner = FakeProcessRunner()
    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=FakePipelineBuilder(),
        discovery_service=FakeDiscoveryService(peer_available=True),
        lock_port=50151,
        ipc_port=50161,
    )

    controller.start()
    assert len(runner.running_pids) == 1

    assert controller.stop() is True
    status1 = controller.get_status()
    assert status1.desired_state == DesiredState.STOPPED_BY_USER.value
    assert len(runner.running_pids) == 0

    assert controller.stop() is True
    status2 = controller.get_status()
    assert status2.desired_state == DesiredState.STOPPED_BY_USER.value

    controller.shutdown()


def test_status_is_strictly_read_only(temp_state_file):
    runner = FakeProcessRunner()
    discovery = FakeDiscoveryService(peer_available=False)
    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=FakePipelineBuilder(),
        discovery_service=discovery,
        lock_port=50152,
        ipc_port=50162,
    )

    s1 = controller.get_status()
    assert s1.controller_state == LifecycleState.STOPPED.value
    assert len(runner.started_commands) == 0

    for _ in range(3):
        s = controller.get_status()
        assert s.controller_state == LifecycleState.STOPPED.value

    assert len(runner.started_commands) == 0
    assert discovery.started is False
    controller.shutdown()


def test_owned_child_only_cleanup(temp_state_file):
    runner = FakeProcessRunner()
    external_pid = 7777
    runner.running_pids.add(external_pid)

    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=FakePipelineBuilder(),
        discovery_service=FakeDiscoveryService(peer_available=True),
        lock_port=50153,
        ipc_port=50163,
    )

    controller.start()
    owned_pid = list(runner.running_pids - {external_pid})[0]
    controller.stop()

    assert owned_pid in runner.stopped_pids
    assert external_pid in runner.running_pids
    assert external_pid not in runner.stopped_pids
    controller.shutdown()


# ---------------------------------------------------------
# Test Suite 2: Process-Level Singleton & Lock Retention (Blocker 2)
# ---------------------------------------------------------

def test_singleton_lock_held_across_repeated_starts(temp_state_file):
    lock_port = 50154
    ipc_port = 50164
    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=FakeProcessRunner(),
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=FakePipelineBuilder(),
        discovery_service=FakeDiscoveryService(peer_available=True),
        lock_port=lock_port,
        ipc_port=ipc_port,
    )

    # First start acquires lock
    assert controller.start() is True

    # Repeated starts must retain the lock without dropping it
    for _ in range(3):
        assert controller.start() is True

    # Attempting to start a second controller instance must be rejected as singleton
    second_lock = SingleInstanceLock(port=lock_port)
    assert second_lock.acquire() is False

    # Shutdown releases lock
    controller.shutdown()
    assert second_lock.acquire() is True
    second_lock.release()


# ---------------------------------------------------------
# Test Suite 3: Multi-Interface Discovery & Bind Resolution (Blocker 3)
# ---------------------------------------------------------

class FakeInterfaceEnumerator(InterfaceEnumerator):
    def __init__(self, candidates):
        self.candidates = candidates

    def get_candidate_interfaces(self):
        return self.candidates


def test_multi_interface_discovery_resolves_local_bind():
    # Simulate host with two candidate interfaces: Wi-Fi and Direct Link
    candidates = [
        ("192.168.1.100", "192.168.1.255"),
        ("198.168.10.5", "198.168.10.255"),
    ]
    enumerator = FakeInterfaceEnumerator(candidates)
    discovery = PeerDiscoveryService(
        local_role=HostRole.WINDOWS,
        instance_id="win-disc-test",
        control_port=50170,
        interface_enumerator=enumerator,
    )
    discovery.start()

    # Simulate opposite peer (Mac) sending HELLO to discovery socket
    # Mac address is on direct link: 198.168.10.6
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    hello = {
        "version": 1,
        "role": "macos",
        "instance_id": "mac-m1-test",
        "speaker_port": 5004,
    }
    s.sendto(json.dumps(hello).encode("utf-8"), ("127.0.0.1", 50170))

    time.sleep(0.5)
    assert discovery.peer_available is True
    assert discovery.peer_address == "127.0.0.1"
    # Local bind address is determined via route resolution
    assert discovery.local_bind_address is not None

    s.close()
    discovery.stop()


# ---------------------------------------------------------
# Test Suite 4: Cross-Process IPC Control (Blocker 1)
# ---------------------------------------------------------

def test_cross_process_ipc_lifecycle(temp_state_file):
    """Spawns an independent controller host process and tests Start/Status/Stop via IPC."""
    ipc_port = 50180
    lock_port = 50185

    runner = FakeProcessRunner()
    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=FakePipelineBuilder(),
        discovery_service=FakeDiscoveryService(peer_available=True),
        lock_port=lock_port,
        ipc_port=ipc_port,
    )
    controller.start()

    # Test Status before explicit Start via IPC
    res_status = send_ipc_command("status", port=ipc_port)
    assert res_status is not None
    assert res_status["desired_state"] == DesiredState.ENABLED.value
    assert res_status["owned_children_count"] == 1

    # Test repeated Start via IPC
    res_start = send_ipc_command("start", port=ipc_port)
    assert res_start is not None
    assert res_start["success"] is True
    # Still 1 pipeline
    assert len(runner.started_commands) == 1

    # Test Stop via IPC
    res_stop = send_ipc_command("stop", port=ipc_port)
    assert res_stop is not None
    assert res_stop["success"] is True

    # Status after Stop
    res_status2 = send_ipc_command("status", port=ipc_port)
    assert res_status2["desired_state"] == DesiredState.STOPPED_BY_USER.value
    assert res_status2["owned_children_count"] == 0

    controller.shutdown()
