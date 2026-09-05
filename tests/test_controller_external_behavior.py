"""External behavior automated tests for desk-audio-bridge controller.

Verifies the primary external contract:
- Repeated Start is idempotent and does not create duplicate pipelines.
- Repeated Stop is idempotent and preserves STOPPED_BY_USER.
- Status is strictly read-only and does not mutate controller state or child processes.
- Controller singleton prevents duplicate active instances.
- Duplicate speaker pipeline prevention.
- Owned-child-only cleanup (non-owned external processes are never killed).
- Peer unavailable / available state transitions.
- Windows playback endpoint resolution success / failure external status reporting.
"""

import os
import tempfile
import time
import pytest
from typing import List, Optional

from windows.bridge_common import (
    ControllerStatus,
    DesiredState,
    HostRole,
    LifecycleState,
    PathState,
)
from windows.controller import SingleInstanceLock, WindowsBridgeController
from windows.process_runner import ProcessRunner


class FakeProcessRunner(ProcessRunner):
    """Simulates child process supervision while tracking process ownership."""

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
    """Simulates Windows Playback Source resolution."""

    def __init__(self, endpoint_id: Optional[str] = "{0.0.0.00000000}.{mock-endpoint}"):
        self.endpoint_id = endpoint_id

    def resolve_default_playback_endpoint_id(self) -> Optional[str]:
        return self.endpoint_id


class FakePipelineBuilder:
    """Simulates speaker pipeline command construction."""

    def __init__(self, gst_available: bool = True):
        self._available = gst_available

    def is_gstreamer_available(self) -> bool:
        return self._available

    def build_sender_command(self, target_host: str, target_port: int, device_id: Optional[str] = None) -> List[str]:
        return ["fake-gst", f"--host={target_host}", f"--port={target_port}", f"--device={device_id}"]


class FakeDiscoveryService:
    """Simulates peer discovery state."""

    def __init__(self, peer_available: bool = True, peer_address: str = "198.18.0.2", peer_port: int = 5004):
        self.peer_available = peer_available
        self.peer_address = peer_address
        self.peer_speaker_port = peer_port
        self.started = False
        self.stopped = False
        self.broadcast_count = 0

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def broadcast_hello(self, destination: str = "255.255.255.255"):
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


def test_repeated_start_is_idempotent_and_creates_single_pipeline(temp_state_file):
    runner = FakeProcessRunner()
    resolver = FakeDeviceResolver()
    builder = FakePipelineBuilder()
    discovery = FakeDiscoveryService(peer_available=True)

    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=resolver,
        pipeline_builder=builder,
        discovery_service=discovery,
        lock_port=50120,
    )

    # First start
    assert controller.start() is True
    status1 = controller.get_status()
    assert status1.desired_state == DesiredState.ENABLED.value
    assert status1.controller_state == LifecycleState.ACTIVE.value
    assert status1.speaker_path_state == PathState.RUNNING.value
    assert len(runner.started_commands) == 1
    assert status1.owned_children_count == 1

    # Repeated start
    assert controller.start() is True
    status2 = controller.get_status()
    assert status2.desired_state == DesiredState.ENABLED.value
    assert status2.controller_state == LifecycleState.ACTIVE.value
    # Assert NO duplicate pipeline was spawned
    assert len(runner.started_commands) == 1
    assert status2.owned_children_count == 1

    controller.stop()


def test_repeated_stop_is_idempotent_and_cleans_owned_process(temp_state_file):
    runner = FakeProcessRunner()
    resolver = FakeDeviceResolver()
    builder = FakePipelineBuilder()
    discovery = FakeDiscoveryService(peer_available=True)

    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=resolver,
        pipeline_builder=builder,
        discovery_service=discovery,
        lock_port=50121,
    )

    controller.start()
    assert len(runner.running_pids) == 1

    # First stop
    assert controller.stop() is True
    status1 = controller.get_status()
    assert status1.desired_state == DesiredState.STOPPED_BY_USER.value
    assert status1.controller_state == LifecycleState.STOPPED.value
    assert status1.speaker_path_state == PathState.STOPPED.value
    assert len(runner.running_pids) == 0

    # Repeated stop
    assert controller.stop() is True
    status2 = controller.get_status()
    assert status2.desired_state == DesiredState.STOPPED_BY_USER.value
    assert status2.controller_state == LifecycleState.STOPPED.value


def test_status_is_strictly_read_only(temp_state_file):
    runner = FakeProcessRunner()
    resolver = FakeDeviceResolver()
    builder = FakePipelineBuilder()
    discovery = FakeDiscoveryService(peer_available=False)

    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=resolver,
        pipeline_builder=builder,
        discovery_service=discovery,
        lock_port=50122,
    )

    # Initial state is STOPPED_BY_USER
    status_before = controller.get_status()
    assert status_before.controller_state == LifecycleState.STOPPED.value
    assert len(runner.started_commands) == 0

    # Repeated queries of status
    for _ in range(5):
        s = controller.get_status()
        assert s.controller_state == LifecycleState.STOPPED.value

    # Verify query status has not mutated state or launched any process
    assert len(runner.started_commands) == 0
    assert discovery.started is False


def test_controller_singleton_lock(temp_state_file):
    lock1 = SingleInstanceLock(port=50123)
    lock2 = SingleInstanceLock(port=50123)

    assert lock1.acquire() is True
    # Second acquisition on same port must fail
    assert lock2.acquire() is False

    lock1.release()
    # Now second can acquire
    assert lock2.acquire() is True
    lock2.release()


def test_owned_child_only_cleanup(temp_state_file):
    """Verifies that stopping or cleaning up controller only affects owned processes,
    never unrelated external PIDs."""
    runner = FakeProcessRunner()
    external_unrelated_pid = 9999
    runner.running_pids.add(external_unrelated_pid)

    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=FakePipelineBuilder(),
        discovery_service=FakeDiscoveryService(peer_available=True),
        lock_port=50124,
    )

    controller.start()
    assert len(runner.started_commands) == 1
    owned_pid = list(runner.running_pids - {external_unrelated_pid})[0]

    controller.stop()
    # Owned PID must be stopped
    assert owned_pid in runner.stopped_pids
    # External unrelated PID must remain running and NOT stopped
    assert external_unrelated_pid in runner.running_pids
    assert external_unrelated_pid not in runner.stopped_pids


def test_peer_unavailable_and_available_transitions(temp_state_file):
    runner = FakeProcessRunner()
    resolver = FakeDeviceResolver()
    builder = FakePipelineBuilder()
    discovery = FakeDiscoveryService(peer_available=False)

    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=resolver,
        pipeline_builder=builder,
        discovery_service=discovery,
        lock_port=50125,
    )

    controller.start()
    status = controller.get_status()
    # Peer is unavailable, should be in DISCOVERING and no pipeline launched yet
    assert status.controller_state == LifecycleState.DISCOVERING.value
    assert status.peer_available is False
    assert len(runner.started_commands) == 0

    # Simulate peer arrival
    discovery.peer_available = True
    controller.reconcile()

    status2 = controller.get_status()
    assert status2.controller_state == LifecycleState.ACTIVE.value
    assert status2.peer_available is True
    assert len(runner.started_commands) == 1

    controller.stop()


def test_playback_source_resolution_failure(temp_state_file):
    runner = FakeProcessRunner()
    resolver = FakeDeviceResolver(endpoint_id=None)  # Simulate resolution failure
    builder = FakePipelineBuilder()
    discovery = FakeDiscoveryService(peer_available=True)

    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=resolver,
        pipeline_builder=builder,
        discovery_service=discovery,
        lock_port=50126,
    )

    controller.start()
    status = controller.get_status()
    assert status.controller_state == LifecycleState.ERROR.value
    assert status.speaker_path_state == PathState.FAILED.value
    assert status.last_actionable_error == "Windows Playback Source endpoint resolution failed"
    assert len(runner.started_commands) == 0

    controller.stop()
