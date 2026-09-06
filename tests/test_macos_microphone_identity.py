"""Focused tests for macOS CoreAudio stable microphone identity and UID hint resolver (Issue #21).

Verifies:
- Built-in microphone stable identity hit (transport bltn, input_channels > 0, stable UID)
- Non-built-in microphone rejected (AirPods, USB mic, virtual devices, iPhone Continuity)
- Empty or whitespace UID built-in microphone rejected
- Persistent Device UID recognition across restart when runtime DeviceID changes
- Stale cached UID hint refreshes and persists new UID
- Cached non-builtin UID hint is never accepted and falls back to real built-in
"""

import os
import json
import pytest

from macos.device_resolver import MacCoreAudioDeviceResolver, ResolvedAudioDevice


def test_builtin_microphone_stable_identity_hit():
    """Device resolver stably selects built-in microphone with bltn transport, input_channels > 0, and stable UID."""
    resolver = MacCoreAudioDeviceResolver()
    # Mock enumerate_input_devices to return realistic devices
    devices = [
        ResolvedAudioDevice(
            device_id=102,
            device_uid="NDI_Audio_UID",
            device_name="NDI Audio",
            is_builtin=False,
            output_channels=0,
            is_default=False,
            input_channels=2,
        ),
        ResolvedAudioDevice(
            device_id=89,
            device_uid="BuiltInMicUID_123",
            device_name="MacBook Air Microphone",
            is_builtin=True,
            output_channels=0,
            is_default=True,
            input_channels=1,
        ),
        ResolvedAudioDevice(
            device_id=151,
            device_uid="iPhone_Mic_UID",
            device_name="yam’s iPhone Microphone",
            is_builtin=False,
            output_channels=0,
            is_default=False,
            input_channels=1,
        ),
    ]
    resolver.enumerate_input_devices = lambda: devices

    dev = resolver.resolve_builtin_microphone_device()
    assert dev is not None
    assert dev.device_id == 89
    assert dev.device_uid == "BuiltInMicUID_123"
    assert dev.device_name == "MacBook Air Microphone"
    assert dev.is_builtin is True
    assert dev.input_channels == 1


def test_non_builtin_microphone_rejected():
    """Refuses to fall back to non-built-in devices (virtual drivers, iPhone, USB, etc.)."""
    resolver = MacCoreAudioDeviceResolver()
    # Only non-builtin inputs present
    devices = [
        ResolvedAudioDevice(
            device_id=102,
            device_uid="NDI_Audio_UID",
            device_name="NDI Audio",
            is_builtin=False,
            output_channels=0,
            is_default=False,
            input_channels=2,
        ),
        ResolvedAudioDevice(
            device_id=151,
            device_uid="iPhone_Mic_UID",
            device_name="yam’s iPhone Microphone",
            is_builtin=False,
            output_channels=0,
            is_default=True,
            input_channels=1,
        ),
        ResolvedAudioDevice(
            device_id=200,
            device_uid="USB_Mic_UID",
            device_name="USB Condenser Mic",
            is_builtin=False,
            output_channels=0,
            is_default=False,
            input_channels=2,
        ),
    ]
    resolver.enumerate_input_devices = lambda: devices

    dev = resolver.resolve_builtin_microphone_device()
    assert dev is None, "Must refuse fallback to non-built-in devices"


def test_empty_uid_builtin_microphone_rejected():
    """验证空 UID 或无效 UID 的内置设备会被拒绝，确保稳定身份契约。"""
    resolver = MacCoreAudioDeviceResolver()
    devices = [
        ResolvedAudioDevice(
            device_id=89,
            device_uid="",  # 空 UID
            device_name="MacBook Air Microphone",
            is_builtin=True,
            output_channels=0,
            is_default=True,
            input_channels=1,
        ),
        ResolvedAudioDevice(
            device_id=90,
            device_uid="   ",  # 纯空格 UID
            device_name="Internal Mic",
            is_builtin=True,
            output_channels=0,
            is_default=False,
            input_channels=1,
        ),
    ]
    resolver.enumerate_input_devices = lambda: devices

    dev = resolver.resolve_builtin_microphone_device()
    assert dev is None, "空或纯空格 UID 的设备必须被拒绝"


def test_persistent_mic_uid_restart_and_runtime_device_id_change(tmp_path):
    """Verifies persistent Device UID recognition across restart when runtime DeviceID changes."""
    hint_file = str(tmp_path / "mic_hint.json")

    # Instance 1: Initial enumeration with DeviceID=89, UID="BuiltInMicStableUID"
    resolver_1 = MacCoreAudioDeviceResolver(mic_hint_file=hint_file)
    devices_1 = [
        ResolvedAudioDevice(
            device_id=89,
            device_uid="BuiltInMicStableUID",
            device_name="MacBook Air Microphone",
            is_builtin=True,
            output_channels=0,
            is_default=True,
            input_channels=1,
        ),
    ]
    resolver_1.enumerate_input_devices = lambda: devices_1

    dev_1 = resolver_1.resolve_builtin_microphone_device()
    assert dev_1 is not None
    assert dev_1.device_id == 89
    assert dev_1.device_uid == "BuiltInMicStableUID"

    # Verify UID was persisted to hint file outside Git and NO DeviceID was persisted
    assert os.path.exists(hint_file)
    with open(hint_file, "r", encoding="utf-8") as f:
        hint_data = json.load(f)
    assert hint_data.get("microphone_uid") == "BuiltInMicStableUID"
    assert "device_id" not in hint_data
    assert "device_name" not in hint_data

    # Instance 2: Fresh resolver instance after reboot/replug where runtime DeviceID changed to 104
    resolver_2 = MacCoreAudioDeviceResolver(mic_hint_file=hint_file)
    devices_2 = [
        ResolvedAudioDevice(
            device_id=104,  # Runtime ID changed
            device_uid="BuiltInMicStableUID",  # Same stable UID
            device_name="MacBook Air Microphone",
            is_builtin=True,
            output_channels=0,
            is_default=False,  # Even if default changed
            input_channels=1,
        ),
        ResolvedAudioDevice(
            device_id=120,
            device_uid="Another_Builtin_Mic_UID",
            device_name="Internal Mic 2",
            is_builtin=True,
            output_channels=0,
            is_default=True,
            input_channels=1,
        ),
    ]
    resolver_2.enumerate_input_devices = lambda: devices_2

    dev_2 = resolver_2.resolve_builtin_microphone_device()
    assert dev_2 is not None
    assert dev_2.device_id == 104, "Must return current runtime DeviceID"
    assert dev_2.device_uid == "BuiltInMicStableUID", "Must match cached UID hint"


def test_stale_mic_uid_hint_refreshes_and_persists_new_uid(tmp_path):
    """Verifies that stale cached UID is rejected, fresh discovery runs, and new UID is persisted."""
    hint_file = str(tmp_path / "mic_hint.json")
    # Pre-populate hint file with old/stale UID
    with open(hint_file, "w", encoding="utf-8") as f:
        json.dump({"microphone_uid": "OldBuiltInMicUID"}, f)

    resolver = MacCoreAudioDeviceResolver(mic_hint_file=hint_file)
    # Current hardware enumeration only contains new UID
    devices = [
        ResolvedAudioDevice(
            device_id=95,
            device_uid="NewBuiltInMicUID",
            device_name="MacBook Air Microphone",
            is_builtin=True,
            output_channels=0,
            is_default=True,
            input_channels=1,
        ),
    ]
    resolver.enumerate_input_devices = lambda: devices

    dev = resolver.resolve_builtin_microphone_device()
    assert dev is not None
    assert dev.device_id == 95
    assert dev.device_uid == "NewBuiltInMicUID"

    # Hint file must be updated to new UID
    with open(hint_file, "r", encoding="utf-8") as f:
        new_data = json.load(f)
    assert new_data.get("microphone_uid") == "NewBuiltInMicUID"


def test_cached_mic_uid_never_falls_back_to_non_builtin(tmp_path):
    """Cached UID matching a non-built-in device must NEVER be accepted."""
    hint_file = str(tmp_path / "mic_hint.json")
    # Cache an AirPods/USB UID
    with open(hint_file, "w", encoding="utf-8") as f:
        json.dump({"microphone_uid": "AirPods_Mic_UID"}, f)

    resolver = MacCoreAudioDeviceResolver(mic_hint_file=hint_file)
    # Enumeration contains the non-built-in matching device, and a valid built-in device
    devices = [
        ResolvedAudioDevice(
            device_id=150,
            device_uid="AirPods_Mic_UID",
            device_name="AirPods Pro",
            is_builtin=False,  # NOT built-in
            output_channels=0,
            is_default=True,
            input_channels=1,
        ),
        ResolvedAudioDevice(
            device_id=89,
            device_uid="RealBuiltInMicUID",
            device_name="MacBook Air Microphone",
            is_builtin=True,  # Real built-in
            output_channels=0,
            is_default=False,
            input_channels=1,
        ),
    ]
    resolver.enumerate_input_devices = lambda: devices

    dev = resolver.resolve_builtin_microphone_device()
    assert dev is not None
    # Must reject non-builtin even if UID matches, and resolve real built-in
    assert dev.device_uid == "RealBuiltInMicUID"
    assert dev.device_id == 89
    assert dev.is_builtin is True
