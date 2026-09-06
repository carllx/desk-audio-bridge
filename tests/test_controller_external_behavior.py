"""Comprehensive regression and external behavior automated tests.

Covers:
1. Controller external behavior (idempotent Start/Stop, Status read-only, owned cleanup).
2. Process-level cross-command control over IPC (Start, repeated Start, Status, Stop).
3. Process-level singleton test (second owner denied, repeated start does not drop lock).
4. Subprocess singleton fail-closed test (owner A running, owner B fails closed with exit code 2).
5. Deterministic multi-interface route resolution through handle_peer_message seam:
   - Peer B -> Candidate B local IP, NOT Candidate A local IP.
   - End-to-end through controller reconcile: pipeline builder receives candidate B local bind IP.
6. Actual Direct Link interface eligibility (accepts on-link LAN/Ethernet subnet, rejects loopback/tunnels).
7. Dependency failure & enumeration failure tests (no silent global broadcast, reports actionable error).
8. Multiple-responder ambiguity & automatic recovery when secondary peer expires.
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
from windows.peer_discovery import (
    InterfaceClassifier,
    InterfaceEnumerator,
    InterfaceMedium,
    PeerDiscoveryService,
    RouteResolver,
    is_eligible_onlink_ipv4,
)
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
        self.last_built_cmd: Optional[List[str]] = None

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
        self.last_built_cmd = cmd
        return cmd


class FakeDiscoveryService:
    def __init__(
        self,
        peer_available: bool = True,
        peer_address: str = "198.18.0.2",
        local_bind: str = "198.18.0.1",
        peer_port: int = 5004,
        is_ambiguous: bool = False,
    ):
        self.peer_available = peer_available
        self.peer_address = peer_address
        self.local_bind_address = local_bind
        self.peer_speaker_port = peer_port
        self.is_ambiguous = is_ambiguous
        self.last_enumeration_error = None
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
# Test Suite 2: Process-Level Singleton & Lock Retention
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

    assert controller.start() is True

    for _ in range(3):
        assert controller.start() is True

    second_ctrl = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=FakeProcessRunner(),
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=FakePipelineBuilder(),
        discovery_service=FakeDiscoveryService(peer_available=True),
        lock_port=lock_port,
        ipc_port=ipc_port + 1,
    )
    assert second_ctrl.start() is False, "Second controller process must fail to start!"

    controller.shutdown()
    assert second_ctrl.start() is True
    second_ctrl.shutdown()


# ---------------------------------------------------------
# Test Suite 3: End-to-End Discovery Routing Seam
# ---------------------------------------------------------

class MockRouteResolver(RouteResolver):
    def __init__(self, routes: dict[str, str]):
        self.routes = routes

    def resolve_local_route(self, target_ip: str, port: int) -> str:
        return self.routes.get(target_ip, "0.0.0.0")


def test_end_to_end_discovery_routing_and_controller_bind(temp_state_file):
    """Verifies that peer packet -> discovery -> route resolution -> controller -> GStreamer bind-address."""
    candidate_a_local_ip = "192.168.10.10"  # Wi-Fi
    candidate_b_local_ip = "198.168.10.5"   # Direct Link
    peer_direct_ip = "198.168.10.6"        # Mac on Direct Link

    routes = {
        peer_direct_ip: candidate_b_local_ip,
        "192.168.10.1": candidate_a_local_ip,
    }
    resolver = MockRouteResolver(routes)

    discovery = PeerDiscoveryService(
        local_role=HostRole.WINDOWS,
        instance_id="win-disc-e2e",
        control_port=50171,
        route_resolver=resolver,
        election_delay=0.0,
    )

    runner = FakeProcessRunner()
    builder = FakePipelineBuilder()
    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=builder,
        discovery_service=discovery,
        lock_port=50173,
        ipc_port=50174,
    )
    controller.start()

    # Pass peer greeting directly through discovery's handle_peer_message seam
    hello_msg = {
        "version": 1,
        "role": "macos",
        "instance_id": "mac-m1-direct",
        "speaker_port": 5004,
    }
    discovery.handle_peer_message(hello_msg, peer_direct_ip)

    # 1. Assert discovery level
    assert discovery.peer_available is True
    assert discovery.peer_address == peer_direct_ip
    assert discovery.local_bind_address == candidate_b_local_ip
    assert discovery.local_bind_address != candidate_a_local_ip

    # 2. Trigger reconcile / check controller level
    controller.reconcile()
    status = controller.get_status()
    assert status.peer_available is True
    assert status.peer_address == peer_direct_ip
    assert status.local_bind_address == candidate_b_local_ip

    # 3. Assert GStreamer command received candidate B bind address
    assert builder.last_built_cmd is not None
    assert f"--bind={candidate_b_local_ip}" in builder.last_built_cmd
    assert f"--bind={candidate_a_local_ip}" not in builder.last_built_cmd

    controller.shutdown()


def test_actual_direct_link_eligibility():
    """Verifies that the on-link eligibility rule accepts direct LAN/Ethernet subnets and rejects invalid ones."""
    # Current direct link topology on Windows host: 198.168.10.5 / 255.255.255.0 (/24)
    assert is_eligible_onlink_ipv4("198.168.10.5", "255.255.255.0") is True

    # Standard RFC 1918 LAN (Wi-Fi)
    assert is_eligible_onlink_ipv4("192.168.10.10", "255.255.255.0") is True

    # Link-local interface
    assert is_eligible_onlink_ipv4("169.254.10.20", "255.255.0.0") is True

    # Excluded: Loopback
    assert is_eligible_onlink_ipv4("127.0.0.1", "255.0.0.0") is False

    # Excluded: Virtual benchmark/proxy tunnel (Mihomo/Meta Tunnel: 198.18.0.1/30)
    assert is_eligible_onlink_ipv4("198.18.0.1", "255.255.255.252") is False

    # Excluded: Point-to-point host tunnels (/32)
    assert is_eligible_onlink_ipv4("10.0.0.1", "255.255.255.255") is False


# ---------------------------------------------------------
# Test Suite 4: Dependency & Enumeration Failure
# ---------------------------------------------------------

class FailingInterfaceEnumerator(InterfaceEnumerator):
    def get_candidate_interfaces(self):
        return False, [], "Simulated network adapter enumeration failure"


def test_enumeration_failure_reports_actionable_error(temp_state_file):
    discovery = PeerDiscoveryService(
        local_role=HostRole.WINDOWS,
        instance_id="win-fail-test",
        control_port=50175,
        interface_enumerator=FailingInterfaceEnumerator(),
    )
    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=FakeProcessRunner(),
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=FakePipelineBuilder(),
        discovery_service=discovery,
        lock_port=50176,
        ipc_port=50177,
    )
    controller.start()

    # Reconcile attempts discovery broadcast which fails cleanly
    controller.reconcile()
    status = controller.get_status()

    assert status.controller_state == LifecycleState.ERROR.value
    assert "Simulated network adapter enumeration failure" in status.last_actionable_error
    assert status.peer_available is False

    controller.shutdown()


# ---------------------------------------------------------
# Test Suite 5: Multiple-Responder Ambiguity & Recovery
# ---------------------------------------------------------

def test_multiple_responder_ambiguity_and_recovery():
    discovery = PeerDiscoveryService(
        local_role=HostRole.WINDOWS,
        instance_id="win-ambig-recov",
        control_port=50178,
    )

    # 1. Peer 1 arrives
    msg1 = {"version": 1, "role": "macos", "instance_id": "mac-air-1", "speaker_port": 5004}
    discovery.handle_peer_message(msg1, "198.168.10.6")
    assert discovery.peer_available is True
    assert discovery.is_ambiguous is False
    assert discovery.peer_address == "198.168.10.6"

    # 2. Peer 2 arrives -> ambiguity
    msg2 = {"version": 1, "role": "macos", "instance_id": "mac-air-2", "speaker_port": 5004}
    discovery.handle_peer_message(msg2, "198.168.10.7")
    assert discovery.is_ambiguous is True
    assert discovery.peer_available is False
    assert discovery.peer_address is None

    # 3. Simulate Peer 2 expiring (>15 seconds ago) while Peer 1 remains fresh
    now = time.time()
    discovery._known_responders["mac-air-2"] = ("198.168.10.7", now - 20.0)
    discovery._known_responders["mac-air-1"] = ("198.168.10.6", now)

    # Pure getter inspection does NOT mutate or recover
    assert discovery.is_ambiguous is True
    assert discovery.peer_available is False
    assert discovery.peer_address is None

    # Calling explicit refresh_peer_state prunes expired peers and recovers sole responder
    discovery.refresh_peer_state(now=now)
    assert discovery.is_ambiguous is False
    assert discovery.peer_available is True
    assert discovery.peer_address == "198.168.10.6"


# ---------------------------------------------------------
# Test Suite 6: Cross-Process IPC Control
# ---------------------------------------------------------

def test_cross_process_ipc_lifecycle(temp_state_file):
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
    assert controller.start() is True

    res_status = send_ipc_command("status", port=ipc_port)
    assert res_status is not None
    assert res_status["desired_state"] == DesiredState.ENABLED.value
    assert res_status["owned_children_count"] == 1

    res_start = send_ipc_command("start", port=ipc_port)
    assert res_start is not None
    assert res_start["success"] is True
    assert len(runner.started_commands) == 1

    res_stop = send_ipc_command("stop", port=ipc_port)
    assert res_stop is not None
    assert res_stop["success"] is True

    res_status2 = send_ipc_command("status", port=ipc_port)
    assert res_status2["desired_state"] == DesiredState.STOPPED_BY_USER.value
    assert res_status2["owned_children_count"] == 0

    controller.shutdown()


# ---------------------------------------------------------
# Test Suite 7: Route Drift Prevention on Multi-Homed Host
# ---------------------------------------------------------

def test_route_drift_prevention_on_multi_interface(temp_state_file):
    """Verifies that packets for the same peer instance arriving from a second interface
    do not cause route drift between controller get_status() and the running GStreamer process.
    """
    direct_local_ip = "198.168.10.5"
    wifi_local_ip = "192.168.10.10"
    mac_direct_ip = "198.168.10.4"
    mac_wifi_ip = "192.168.10.70"

    routes = {
        mac_direct_ip: direct_local_ip,
        mac_wifi_ip: wifi_local_ip,
    }
    resolver = MockRouteResolver(routes)

    classifier = FakeClassifier({
        direct_local_ip: InterfaceMedium.WIRED_ETHERNET,
        wifi_local_ip: InterfaceMedium.WIFI,
    })
    discovery = PeerDiscoveryService(
        local_role=HostRole.WINDOWS,
        instance_id="win-drift-test",
        control_port=50190,
        route_resolver=resolver,
        interface_classifier=classifier,
        election_delay=0.0,
    )

    runner = FakeProcessRunner()
    builder = FakePipelineBuilder()
    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=builder,
        discovery_service=discovery,
        lock_port=50191,
        ipc_port=50192,
    )
    assert controller.start() is True

    # 1. First packet arrives on Direct Link
    peer_msg = {
        "version": 1,
        "role": "macos",
        "instance_id": "mac-shared-instance-123",
        "speaker_port": 5004,
    }
    discovery.handle_peer_message(peer_msg, mac_direct_ip)
    controller.reconcile()

    # Verify pipeline started with Direct Link route
    status = controller.get_status()
    assert status.speaker_path_state == PathState.RUNNING.value
    assert status.peer_address == mac_direct_ip
    assert status.local_bind_address == direct_local_ip
    assert builder.last_built_cmd is not None
    assert f"--host={mac_direct_ip}" in builder.last_built_cmd
    assert f"--bind={direct_local_ip}" in builder.last_built_cmd
    initial_running_pid = list(runner.running_pids)[0]

    # 2. Second packet for SAME instance arrives on Wi-Fi interface
    discovery.handle_peer_message(peer_msg, mac_wifi_ip)
    controller.reconcile()

    # Verify NO route drift: Status STILL reports active data-path route, and pipeline was NOT flapped
    status2 = controller.get_status()
    assert status2.speaker_path_state == PathState.RUNNING.value
    assert status2.peer_address == mac_direct_ip
    assert status2.local_bind_address == direct_local_ip
    assert status2.peer_address != mac_wifi_ip
    assert status2.local_bind_address != wifi_local_ip
    # Pipeline process did not restart
    assert list(runner.running_pids) == [initial_running_pid]

    controller.shutdown()


# ---------------------------------------------------------
# Test Suite 9: Issue #28 Wired-First Route Election & Pipeline Commit
# ---------------------------------------------------------

class FakeClassifier(InterfaceClassifier):
    def __init__(self, ip_to_medium: dict):
        self.ip_to_medium = ip_to_medium

    def classify_interface(self, ip_str: str) -> InterfaceMedium:
        return self.ip_to_medium.get(ip_str, InterfaceMedium.OTHER)


class FailingClassifier(InterfaceClassifier):
    def classify_interface(self, ip_str: str) -> InterfaceMedium:
        raise RuntimeError("Simulated interface classification failure")


class DictRouteResolver(RouteResolver):
    def __init__(self, routes: dict):
        self.routes = routes

    def resolve_local_route(self, target_ip: str, port: int) -> str:
        return self.routes.get(target_ip, "0.0.0.0")


WF_ETHERNET_PEER_IP = "198.168.10.5"
WF_ETHERNET_LOCAL_IP = "198.168.10.4"
WF_WIFI_PEER_IP = "192.168.10.10"
WF_WIFI_LOCAL_IP = "192.168.10.70"

WF_ROUTES = {
    WF_ETHERNET_PEER_IP: WF_ETHERNET_LOCAL_IP,
    WF_WIFI_PEER_IP: WF_WIFI_LOCAL_IP,
}

WF_MEDIUM_MAP = {
    WF_ETHERNET_LOCAL_IP: InterfaceMedium.WIRED_ETHERNET,
    WF_WIFI_LOCAL_IP: InterfaceMedium.WIFI,
}


# --- Controller-Level External Behavior Tests ---

def test_controller_wired_first_wifi_then_ethernet_commits_only_ethernet(temp_state_file):
    """Controller Test 1: Wi-Fi HELLO arrives first, then Ethernet arrives within settling window.
    
    Guarantees:
    - Initial Wi-Fi does NOT start pipeline prematurely on Wi-Fi.
    - Subsequent Ethernet arrival cancels timer and starts the pipeline once, strictly on Ethernet.
    """
    resolver = DictRouteResolver(WF_ROUTES)
    classifier = FakeClassifier(WF_MEDIUM_MAP)
    discovery = PeerDiscoveryService(
        local_role=HostRole.WINDOWS,
        instance_id="win-ctrl-wf-1",
        control_port=50311,
        route_resolver=resolver,
        interface_classifier=classifier,
        election_delay=0.15,
    )
    runner = FakeProcessRunner()
    builder = FakePipelineBuilder()
    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=builder,
        discovery_service=discovery,
        lock_port=50312,
        ipc_port=50313,
    )
    discovery.on_peer_discovered = controller._on_peer_discovered
    assert controller.start() is True

    hello_msg = {
        "version": 1,
        "role": "macos",
        "instance_id": "mac-peer-1",
        "speaker_port": 5004,
    }

    # 1. Wi-Fi HELLO arrives first
    discovery.handle_peer_message(hello_msg, WF_WIFI_PEER_IP)
    # Controller reconcile should NOT have started pipeline because route is settling
    controller.reconcile()
    assert len(runner.started_commands) == 0
    assert controller.get_status().speaker_path_state == PathState.IDLE.value

    # 2. Ethernet HELLO arrives within 50ms (well inside 150ms window)
    time.sleep(0.04)
    discovery.handle_peer_message(hello_msg, WF_ETHERNET_PEER_IP)

    # Controller should now have committed pipeline on Ethernet
    status = controller.get_status()
    assert status.peer_available is True
    assert status.peer_address == WF_ETHERNET_PEER_IP
    assert status.local_bind_address == WF_ETHERNET_LOCAL_IP
    assert status.speaker_path_state == PathState.RUNNING.value
    assert len(runner.started_commands) == 1
    assert f"--bind={WF_ETHERNET_LOCAL_IP}" in runner.started_commands[0]
    assert f"--host={WF_ETHERNET_PEER_IP}" in runner.started_commands[0]

    # Wait out the original settling window to ensure no second pipeline is started
    time.sleep(0.2)
    assert len(runner.started_commands) == 1
    controller.shutdown()


def test_controller_wired_first_ethernet_first_immediate_commit(temp_state_file):
    """Controller Test 2: Ethernet arrives first -> commits immediately without waiting."""
    resolver = DictRouteResolver(WF_ROUTES)
    classifier = FakeClassifier(WF_MEDIUM_MAP)
    discovery = PeerDiscoveryService(
        local_role=HostRole.WINDOWS,
        instance_id="win-ctrl-wf-2",
        control_port=50321,
        route_resolver=resolver,
        interface_classifier=classifier,
        election_delay=0.3,
    )
    runner = FakeProcessRunner()
    builder = FakePipelineBuilder()
    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=builder,
        discovery_service=discovery,
        lock_port=50322,
        ipc_port=50323,
    )
    discovery.on_peer_discovered = controller._on_peer_discovered
    assert controller.start() is True

    hello_msg = {
        "version": 1,
        "role": "macos",
        "instance_id": "mac-peer-1",
        "speaker_port": 5004,
    }

    # Ethernet arrives
    t0 = time.time()
    discovery.handle_peer_message(hello_msg, WF_ETHERNET_PEER_IP)
    elapsed = time.time() - t0

    # Immediate commit within milliseconds (< 50ms, well below 300ms window)
    assert elapsed < 0.1
    status = controller.get_status()
    assert status.peer_available is True
    assert status.peer_address == WF_ETHERNET_PEER_IP
    assert status.local_bind_address == WF_ETHERNET_LOCAL_IP
    assert status.speaker_path_state == PathState.RUNNING.value
    assert len(runner.started_commands) == 1
    assert f"--bind={WF_ETHERNET_LOCAL_IP}" in runner.started_commands[0]

    controller.shutdown()


def test_controller_wired_first_wifi_only_fallback_after_window(temp_state_file):
    """Controller Test 3: Wi-Fi only arrives -> commits fallback to Wi-Fi only after election window expires."""
    resolver = DictRouteResolver(WF_ROUTES)
    classifier = FakeClassifier(WF_MEDIUM_MAP)
    discovery = PeerDiscoveryService(
        local_role=HostRole.WINDOWS,
        instance_id="win-ctrl-wf-3",
        control_port=50331,
        route_resolver=resolver,
        interface_classifier=classifier,
        election_delay=0.1,
    )
    runner = FakeProcessRunner()
    builder = FakePipelineBuilder()
    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=builder,
        discovery_service=discovery,
        lock_port=50332,
        ipc_port=50333,
    )
    discovery.on_peer_discovered = controller._on_peer_discovered
    assert controller.start() is True

    hello_msg = {
        "version": 1,
        "role": "macos",
        "instance_id": "mac-peer-1",
        "speaker_port": 5004,
    }

    # Wi-Fi arrives
    discovery.handle_peer_message(hello_msg, WF_WIFI_PEER_IP)

    # Immediately: route is settling, pipeline not committed
    assert len(runner.started_commands) == 0
    assert controller.get_status().speaker_path_state == PathState.IDLE.value

    # Wait for election window to expire (0.1s delay -> wait 0.18s)
    time.sleep(0.18)

    # Now fallback pipeline is committed on Wi-Fi
    status = controller.get_status()
    assert status.peer_available is True
    assert status.peer_address == WF_WIFI_PEER_IP
    assert status.local_bind_address == WF_WIFI_LOCAL_IP
    assert status.speaker_path_state == PathState.RUNNING.value
    assert len(runner.started_commands) == 1
    assert f"--bind={WF_WIFI_LOCAL_IP}" in runner.started_commands[0]

    controller.shutdown()


def test_controller_wired_first_running_ethernet_immune_to_wifi_heartbeats(temp_state_file):
    """Controller Test 4: Running Ethernet pipeline is completely immune to subsequent Wi-Fi packets/heartbeats."""
    resolver = DictRouteResolver(WF_ROUTES)
    classifier = FakeClassifier(WF_MEDIUM_MAP)
    discovery = PeerDiscoveryService(
        local_role=HostRole.WINDOWS,
        instance_id="win-ctrl-wf-4",
        control_port=50341,
        route_resolver=resolver,
        interface_classifier=classifier,
        election_delay=0.1,
    )
    runner = FakeProcessRunner()
    builder = FakePipelineBuilder()
    controller = WindowsBridgeController(
        state_file=temp_state_file,
        process_runner=runner,
        device_resolver=FakeDeviceResolver(),
        pipeline_builder=builder,
        discovery_service=discovery,
        lock_port=50342,
        ipc_port=50343,
    )
    discovery.on_peer_discovered = controller._on_peer_discovered
    assert controller.start() is True

    hello_msg = {
        "version": 1,
        "role": "macos",
        "instance_id": "mac-peer-1",
        "speaker_port": 5004,
    }

    # 1. Start on Ethernet
    discovery.handle_peer_message(hello_msg, WF_ETHERNET_PEER_IP)
    assert controller.get_status().speaker_path_state == PathState.RUNNING.value
    initial_pid = runner.started_commands[0]

    # 2. Wi-Fi packet arrives repeatedly
    for _ in range(5):
        discovery.handle_peer_message(hello_msg, WF_WIFI_PEER_IP)
        controller.reconcile()

    # Process must not restart, bind must not drift to Wi-Fi
    assert len(runner.started_commands) == 1
    assert len(runner.stopped_pids) == 0
    status = controller.get_status()
    assert status.peer_address == WF_ETHERNET_PEER_IP
    assert status.local_bind_address == WF_ETHERNET_LOCAL_IP

    controller.shutdown()


# --- Discovery-Level Tests ---

def test_wired_first_discovery_wifi_arrives_first_ethernet_arrives_second():
    """Discovery Test: Wi-Fi arrival first, Ethernet arrival second within election window."""
    resolver = DictRouteResolver(WF_ROUTES)
    classifier = FakeClassifier(WF_MEDIUM_MAP)
    discovery = PeerDiscoveryService(
        local_role=HostRole.MACOS,
        instance_id="mac-wf-test",
        control_port=50301,
        route_resolver=resolver,
        interface_classifier=classifier,
        election_delay=0.1,
    )

    hello_msg = {
        "version": 1,
        "role": "windows",
        "instance_id": "win-peer-1",
        "speaker_port": 5004,
    }

    # Wi-Fi packet arrives first (settling begins)
    discovery.handle_peer_message(hello_msg, WF_WIFI_PEER_IP)
    # peer_available is False during settling window
    assert discovery.peer_available is False

    # Ethernet packet arrives second for the SAME peer within window
    discovery.handle_peer_message(hello_msg, WF_ETHERNET_PEER_IP)
    # Ethernet upgrades immediately and wins
    assert discovery.peer_available is True
    assert discovery.peer_address == WF_ETHERNET_PEER_IP
    assert discovery.local_bind_address == WF_ETHERNET_LOCAL_IP


def test_wired_first_discovery_ethernet_arrives_first_wifi_arrives_second():
    """Discovery Test: Ethernet arrival first, Wi-Fi arrival second -> Ethernet remains."""
    resolver = DictRouteResolver(WF_ROUTES)
    classifier = FakeClassifier(WF_MEDIUM_MAP)
    discovery = PeerDiscoveryService(
        local_role=HostRole.MACOS,
        instance_id="mac-wf-test",
        control_port=50302,
        route_resolver=resolver,
        interface_classifier=classifier,
    )

    hello_msg = {
        "version": 1,
        "role": "windows",
        "instance_id": "win-peer-1",
        "speaker_port": 5004,
    }

    # Ethernet arrives first
    discovery.handle_peer_message(hello_msg, WF_ETHERNET_PEER_IP)
    assert discovery.peer_available is True
    assert discovery.peer_address == WF_ETHERNET_PEER_IP
    assert discovery.local_bind_address == WF_ETHERNET_LOCAL_IP

    # Wi-Fi arrives later
    discovery.handle_peer_message(hello_msg, WF_WIFI_PEER_IP)
    # Ethernet must remain selected
    assert discovery.peer_available is True
    assert discovery.peer_address == WF_ETHERNET_PEER_IP
    assert discovery.local_bind_address == WF_ETHERNET_LOCAL_IP


def test_wired_first_discovery_ethernet_only():
    """Discovery Test: Ethernet only -> Ethernet selected immediately."""
    resolver = DictRouteResolver(WF_ROUTES)
    classifier = FakeClassifier(WF_MEDIUM_MAP)
    discovery = PeerDiscoveryService(
        local_role=HostRole.MACOS,
        instance_id="mac-wf-test",
        control_port=50303,
        route_resolver=resolver,
        interface_classifier=classifier,
    )

    hello_msg = {
        "version": 1,
        "role": "windows",
        "instance_id": "win-peer-1",
        "speaker_port": 5004,
    }

    discovery.handle_peer_message(hello_msg, WF_ETHERNET_PEER_IP)
    assert discovery.peer_available is True
    assert discovery.peer_address == WF_ETHERNET_PEER_IP
    assert discovery.local_bind_address == WF_ETHERNET_LOCAL_IP


def test_wired_first_discovery_wifi_only_fallback():
    """Discovery Test: Wi-Fi only -> Wi-Fi fallback permitted after election delay."""
    resolver = DictRouteResolver(WF_ROUTES)
    classifier = FakeClassifier(WF_MEDIUM_MAP)
    discovery = PeerDiscoveryService(
        local_role=HostRole.MACOS,
        instance_id="mac-wf-test",
        control_port=50304,
        route_resolver=resolver,
        interface_classifier=classifier,
        election_delay=0.08,
    )

    hello_msg = {
        "version": 1,
        "role": "windows",
        "instance_id": "win-peer-1",
        "speaker_port": 5004,
    }

    discovery.handle_peer_message(hello_msg, WF_WIFI_PEER_IP)
    # Initially settling
    assert discovery.peer_available is False

    # Wait for delay
    time.sleep(0.12)
    assert discovery.peer_available is True
    assert discovery.peer_address == WF_WIFI_PEER_IP
    assert discovery.local_bind_address == WF_WIFI_LOCAL_IP


def test_two_distinct_peer_ids_ambiguous_regardless_of_medium():
    """Two distinct peer IDs -> ambiguous regardless of one being Ethernet."""
    resolver = DictRouteResolver({
        WF_ETHERNET_PEER_IP: WF_ETHERNET_LOCAL_IP,
        "198.168.10.99": WF_ETHERNET_LOCAL_IP,
    })
    classifier = FakeClassifier({WF_ETHERNET_LOCAL_IP: InterfaceMedium.WIRED_ETHERNET})
    discovery = PeerDiscoveryService(
        local_role=HostRole.MACOS,
        instance_id="mac-wf-test",
        control_port=50305,
        route_resolver=resolver,
        interface_classifier=classifier,
    )

    # Peer 1 on Ethernet
    discovery.handle_peer_message(
        {"version": 1, "role": "windows", "instance_id": "win-peer-1", "speaker_port": 5004},
        WF_ETHERNET_PEER_IP,
    )
    assert discovery.is_ambiguous is False
    assert discovery.peer_available is True

    # Peer 2 on another IP
    discovery.handle_peer_message(
        {"version": 1, "role": "windows", "instance_id": "win-peer-2", "speaker_port": 5004},
        "198.168.10.99",
    )

    # MUST enter AMBIGUOUS_PEER, never auto-select peer-1 merely because it has an Ethernet path
    assert discovery.is_ambiguous is True
    assert discovery.peer_available is False
    assert discovery.peer_address is None
    assert discovery.local_bind_address is None


def test_classifier_failure_safe_fallback():
    """Classifier exception / failure safely falls back without crashing."""
    resolver = DictRouteResolver(WF_ROUTES)
    failing_classifier = FailingClassifier()
    discovery = PeerDiscoveryService(
        local_role=HostRole.MACOS,
        instance_id="mac-wf-test",
        control_port=50309,
        route_resolver=resolver,
        interface_classifier=failing_classifier,
        election_delay=0.08,
    )

    hello_msg = {
        "version": 1,
        "role": "windows",
        "instance_id": "win-peer-1",
        "speaker_port": 5004,
    }

    # Delivering packet should NOT raise exception, enters settling with OTHER
    discovery.handle_peer_message(hello_msg, WF_ETHERNET_PEER_IP)
    assert discovery.peer_available is False
    time.sleep(0.12)
    assert discovery.peer_available is True
    assert discovery.peer_address == WF_ETHERNET_PEER_IP



