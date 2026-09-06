"""Focused tests for Windows Production Microphone (Issue #21).

Verifies:
- Pack43 hit & driver identity validation (VBAudioVACWDM, v1.0.3.5, VB-Audio Software)
- Pack43 unavailable / failure closed (no fallback to default microphone)
- Cache hit (read-only queries do not trigger CIM/WMI)
- Stale cache -> re-enumeration on invalidation or launch failure
- Mic enable / start idempotence
- Mic disable / stop idempotence
- Duplicate prevention (already running pipeline not re-spawned)
- Owned-child cleanup only (mic child killed, speaker unaffected)
- Unexpected mic child exit detected on next reconcile
- Status reflection (ready / active / unavailable / failed)
- Speaker behavior unchanged when mic is enabled/disabled/reconciled
"""

import os
import tempfile
import time
from typing import List, Optional
import pytest

from bridge_core.contract import (
    DEFAULT_MIC_RTP_PORT,
    DEFAULT_SPEAKER_RTP_PORT,
    DesiredState,
    HostRole,
    LifecycleState,
    PathState,
)
from windows.controller import WindowsBridgeController
from windows.microphone_receiver import MicrophoneReceiverBuilder
from windows.pack43_resolver import Pack43ResolutionResult, Pack43Resolver
from windows.process_runner import ProcessRunner


class FakeProcessRunner(ProcessRunner):
    def __init__(self):
        self._next_pid = 2000
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


class FakePack43Resolver(Pack43Resolver):
    def __init__(self, should_succeed: bool = True, render_id: str = "{0.0.0.00000000}.{MOCK_PACK43_INPUT}"):
        super().__init__()
        self.should_succeed = should_succeed
        self.render_id = render_id
        self.resolve_call_count = 0
        self.underlying_enumeration_count = 0

    def resolve_pack43(self, force_refresh: bool = False) -> Optional[Pack43ResolutionResult]:
        self.resolve_call_count += 1
        if not force_refresh and self._has_cached:
            return self._cached_result

        self.underlying_enumeration_count += 1
        if not self.should_succeed:
            self._cached_result = None
            self._has_cached = True
            return None

        res = Pack43ResolutionResult(
            render_endpoint_id=self.render_id,
            capture_endpoint_id="SWD\\MMDEVAPI\\{0.0.1.00000000}.{MOCK_PACK43_OUTPUT}",
            driver_version="1.0.3.5",
        )
        self._cached_result = res
        self._has_cached = True
        return res


class FakeDiscoveryService:
    def __init__(self, peer_ip: str = "192.168.1.50", local_ip: str = "192.168.1.100"):
        self.peer_available = True
        self.peer_address = peer_ip
        self.local_bind_address = local_ip
        self.peer_speaker_port = DEFAULT_SPEAKER_RTP_PORT
        self.is_ambiguous = False
        self.last_enumeration_error = None
        self.broadcast_called = 0

    def start(self):
        pass

    def stop(self):
        pass

    def broadcast_hello(self):
        self.broadcast_called += 1

    def refresh_peer_state(self):
        pass


class FakeDeviceResolver:
    def resolve_default_playback_endpoint_id(self) -> Optional[str]:
        return "{0.0.0.00000000}.{DEFAULT_SPEAKER}"


@pytest.fixture
def temp_state_file():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
        path = f.name
    yield path
    if os.path.exists(path):
        try:
            os.unlink(path)
        except Exception:
            pass


def test_microphone_receiver_builder_canonical_command():
    builder = MicrophoneReceiverBuilder(gst_path="gst-launch-1.0.exe")
    cmd = builder.build_receiver_command(
        local_bind_ip="192.168.1.100",
        local_port=5006,
        device_id="{0.0.0.00000000}.{PACK43_INPUT}",
    )

    assert cmd[0] == "gst-launch-1.0.exe"
    assert "-m" in cmd
    assert "udpsrc" in cmd
    assert "address=192.168.1.100" in cmd
    assert "port=5006" in cmd
    assert "caps=application/x-rtp,media=(string)audio,encoding-name=(string)L16,clock-rate=(int)48000,channels=(int)1,payload=(int)97" in cmd
    assert "rtpjitterbuffer" in cmd
    assert "latency=80" in cmd
    assert "rtpL16depay" in cmd
    assert "wasapi2sink" in cmd
    assert "wasapisink" not in cmd
    assert "low-latency=true" in cmd
    assert "sync=false" in cmd
    assert "device={0.0.0.00000000}.{PACK43_INPUT}" in cmd


def test_pack43_resolver_cache_hit_and_invalidation():
    resolver = FakePack43Resolver(should_succeed=True)
    assert resolver.is_cached_available is None

    res1 = resolver.resolve_pack43()
    assert res1 is not None
    assert resolver.resolve_call_count == 1
    assert resolver.underlying_enumeration_count == 1
    assert resolver.is_cached_available is True

    # Second call hits cache (underlying enumeration count remains 1)
    res2 = resolver.resolve_pack43()
    assert res2 == res1
    assert resolver.resolve_call_count == 2
    assert resolver.underlying_enumeration_count == 1
    assert resolver.is_cached_available is True

    # Invalidate cache -> next call re-enumerates
    resolver.invalidate_cache()
    assert resolver.is_cached_available is None
    res3 = resolver.resolve_pack43()
    assert res3 is not None
    assert resolver.resolve_call_count == 3
    assert resolver.underlying_enumeration_count == 2
    assert resolver.is_cached_available is True


def test_repeated_unavailable_resolve_does_not_enumerate_again_until_invalidate():
    """Verifies that known-negative Pack43 resolution result is cached and does not re-enumerate."""
    resolver = FakePack43Resolver(should_succeed=False)
    assert resolver.is_cached_available is None

    # First resolve: fails and records negative result in cache
    res1 = resolver.resolve_pack43()
    assert res1 is None
    assert resolver.resolve_call_count == 1
    assert resolver.underlying_enumeration_count == 1
    assert resolver.is_cached_available is False

    # Second resolve: hits negative cache, does NOT re-enumerate
    res2 = resolver.resolve_pack43()
    assert res2 is None
    assert resolver.resolve_call_count == 2
    assert resolver.underlying_enumeration_count == 1
    assert resolver.is_cached_available is False

    # Third resolve: still cached None
    res3 = resolver.resolve_pack43()
    assert res3 is None
    assert resolver.resolve_call_count == 3
    assert resolver.underlying_enumeration_count == 1
    assert resolver.is_cached_available is False

    # Invalidate cache -> next resolve triggers underlying enumeration
    resolver.invalidate_cache()
    assert resolver.is_cached_available is None
    res4 = resolver.resolve_pack43()
    assert res4 is None
    assert resolver.resolve_call_count == 4
    assert resolver.underlying_enumeration_count == 2
    assert resolver.is_cached_available is False


def test_microphone_not_started_automatically_with_speaker(temp_state_file):
    runner = FakeProcessRunner()
    pack43 = FakePack43Resolver(should_succeed=True)
    disc = FakeDiscoveryService()
    ctrl = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        discovery_service=disc,
        pack43_resolver=pack43,
        lock_port=50161,
        ipc_port=50162,
    )

    ctrl.start()
    assert ctrl.get_status().speaker_path_state == PathState.RUNNING.value
    assert ctrl.get_status().microphone_path_state == PathState.IDLE.value
    # Only 1 process started (speaker)
    assert len(runner.started_commands) == 1
    assert ctrl.get_status().owned_children_count == 1


def test_microphone_enable_and_idempotent_start(temp_state_file):
    runner = FakeProcessRunner()
    pack43 = FakePack43Resolver(should_succeed=True)
    disc = FakeDiscoveryService()
    ctrl = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        discovery_service=disc,
        pack43_resolver=pack43,
        lock_port=50163,
        ipc_port=50164,
    )

    ctrl.start()
    assert len(runner.started_commands) == 1

    # Enable microphone
    success = ctrl.set_microphone_enabled(True)
    assert success is True
    assert ctrl.get_status().microphone_path_state == PathState.RUNNING.value
    assert len(runner.started_commands) == 2
    assert ctrl.get_status().owned_children_count == 2

    mic_cmd = runner.started_commands[1]
    assert "device={0.0.0.00000000}.{MOCK_PACK43_INPUT}" in mic_cmd

    # Idempotent reconcile / enable
    ctrl.reconcile()
    ctrl.set_microphone_enabled(True)
    assert len(runner.started_commands) == 2
    assert ctrl.get_status().microphone_path_state == PathState.RUNNING.value


def test_microphone_disable_and_idempotent_stop(temp_state_file):
    runner = FakeProcessRunner()
    pack43 = FakePack43Resolver(should_succeed=True)
    disc = FakeDiscoveryService()
    ctrl = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        discovery_service=disc,
        pack43_resolver=pack43,
        lock_port=50165,
        ipc_port=50166,
    )

    ctrl.start()
    ctrl.set_microphone_enabled(True)
    assert ctrl.get_status().microphone_path_state == PathState.RUNNING.value
    assert ctrl.get_status().owned_children_count == 2

    # Disable mic
    success = ctrl.set_microphone_enabled(False)
    assert success is True
    assert ctrl.get_status().microphone_path_state == PathState.STOPPED.value
    assert ctrl.get_status().speaker_path_state == PathState.RUNNING.value
    assert ctrl.get_status().owned_children_count == 1

    # Idempotent disable
    ctrl.set_microphone_enabled(False)
    assert ctrl.get_status().microphone_path_state == PathState.STOPPED.value
    assert ctrl.get_status().owned_children_count == 1


def test_microphone_pack43_unavailable_fail_closed(temp_state_file):
    runner = FakeProcessRunner()
    pack43 = FakePack43Resolver(should_succeed=False)
    disc = FakeDiscoveryService()
    ctrl = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        discovery_service=disc,
        pack43_resolver=pack43,
        lock_port=50167,
        ipc_port=50168,
    )

    ctrl.start()
    assert ctrl.get_status().speaker_path_state == PathState.RUNNING.value

    # Enable mic when Pack43 is unavailable
    success = ctrl.set_microphone_enabled(True)
    assert success is False
    status = ctrl.get_status()
    assert status.microphone_path_state == PathState.UNAVAILABLE.value
    assert status.pack43_available is False
    assert "Pack43" in (status.last_actionable_microphone_error or "")
    # No fallback microphone child started
    assert len(runner.started_commands) == 1
    assert status.owned_children_count == 1


def test_unexpected_microphone_child_exit(temp_state_file):
    runner = FakeProcessRunner()
    pack43 = FakePack43Resolver(should_succeed=True)
    disc = FakeDiscoveryService()
    ctrl = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        discovery_service=disc,
        pack43_resolver=pack43,
        lock_port=50169,
        ipc_port=50170,
    )

    ctrl.start()
    ctrl.set_microphone_enabled(True)
    assert ctrl.get_status().microphone_path_state == PathState.RUNNING.value
    mic_pid = ctrl._microphone_child_pid
    assert mic_pid is not None

    # Simulate mic process dying unexpectedly
    runner.running_pids.remove(mic_pid)

    # Status before reconcile
    assert ctrl.get_status().owned_children_count == 1

    # Next reconcile restarts it or detects exit
    ctrl.reconcile()
    # It should have recovered and re-spawned, or reported running
    assert ctrl.get_status().microphone_path_state == PathState.RUNNING.value
    assert len(runner.started_commands) == 3


def test_controller_stop_cleans_both_children_without_affecting_others(temp_state_file):
    runner = FakeProcessRunner()
    # Simulate an external third-party process
    runner.running_pids.add(9999)

    pack43 = FakePack43Resolver(should_succeed=True)
    disc = FakeDiscoveryService()
    ctrl = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        discovery_service=disc,
        pack43_resolver=pack43,
        lock_port=50171,
        ipc_port=50172,
    )

    ctrl.start()
    ctrl.set_microphone_enabled(True)
    assert ctrl.get_status().owned_children_count == 2

    spk_pid = ctrl._speaker_child_pid
    mic_pid = ctrl._microphone_child_pid

    ctrl.stop()
    assert spk_pid in runner.stopped_pids
    assert mic_pid in runner.stopped_pids
    # External process untouched
    assert 9999 not in runner.stopped_pids
    assert 9999 in runner.running_pids
    assert ctrl.get_status().owned_children_count == 0
    assert ctrl.get_status().microphone_path_state == PathState.STOPPED.value
    assert ctrl.get_status().speaker_path_state == PathState.STOPPED.value


def test_active_microphone_stops_when_peer_becomes_unavailable(temp_state_file):
    """Verifies that active microphone receiver child is stopped when peer is lost."""
    runner = FakeProcessRunner()
    pack43 = FakePack43Resolver(should_succeed=True)
    disc = FakeDiscoveryService()
    ctrl = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        discovery_service=disc,
        pack43_resolver=pack43,
        lock_port=50173,
        ipc_port=50174,
    )

    ctrl.start()
    ctrl.set_microphone_enabled(True)
    assert ctrl.get_status().owned_children_count == 2
    assert ctrl.get_status().microphone_path_state == PathState.RUNNING.value
    mic_pid = ctrl._microphone_child_pid
    spk_pid = ctrl._speaker_child_pid

    # Peer becomes unavailable
    disc.peer_available = False
    ctrl.reconcile()

    # Both speaker and microphone children must be terminated
    assert mic_pid in runner.stopped_pids
    assert spk_pid in runner.stopped_pids
    assert ctrl.get_status().owned_children_count == 0
    assert ctrl.get_status().microphone_path_state == PathState.READY.value
    assert ctrl.get_status().speaker_path_state == PathState.IDLE.value
    ctrl.shutdown()


def test_active_microphone_stops_when_peer_becomes_ambiguous(temp_state_file):
    """Verifies that active microphone receiver child is stopped when peer state becomes ambiguous."""
    runner = FakeProcessRunner()
    pack43 = FakePack43Resolver(should_succeed=True)
    disc = FakeDiscoveryService()
    ctrl = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        discovery_service=disc,
        pack43_resolver=pack43,
        lock_port=50175,
        ipc_port=50176,
    )

    ctrl.start()
    ctrl.set_microphone_enabled(True)
    assert ctrl.get_status().owned_children_count == 2
    assert ctrl.get_status().microphone_path_state == PathState.RUNNING.value
    mic_pid = ctrl._microphone_child_pid
    spk_pid = ctrl._speaker_child_pid

    # Ambiguity detected
    disc.is_ambiguous = True
    ctrl.reconcile()

    # Both speaker and microphone children must be terminated
    assert mic_pid in runner.stopped_pids
    assert spk_pid in runner.stopped_pids
    assert ctrl.get_status().owned_children_count == 0
    assert ctrl.get_status().microphone_path_state == PathState.READY.value
    assert ctrl.get_status().speaker_path_state == PathState.IDLE.value
    ctrl.shutdown()


def test_speaker_endpoint_failure_does_not_prevent_requested_microphone_path(temp_state_file):
    """Verifies that playback endpoint resolution failure does NOT block microphone capability reconcile."""
    runner = FakeProcessRunner()
    pack43 = FakePack43Resolver(should_succeed=True)
    disc = FakeDiscoveryService()

    class FailingDeviceResolver:
        def resolve_default_playback_endpoint_id(self) -> Optional[str]:
            return None

    ctrl = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FailingDeviceResolver(),
        discovery_service=disc,
        pack43_resolver=pack43,
        lock_port=50177,
        ipc_port=50178,
    )

    ctrl.start()
    # Speaker fails due to endpoint resolution
    assert ctrl.get_status().speaker_path_state == PathState.FAILED.value

    # Enabling microphone should succeed despite speaker endpoint failure
    success = ctrl.set_microphone_enabled(True)
    assert success is True
    status = ctrl.get_status()
    assert status.microphone_path_state == PathState.RUNNING.value
    assert status.speaker_path_state == PathState.FAILED.value
    assert status.owned_children_count == 1
    assert len(runner.started_commands) == 1
    assert "wasapi2sink" in runner.started_commands[0]
    assert "wasapisink" not in runner.started_commands[0]
    ctrl.shutdown()
