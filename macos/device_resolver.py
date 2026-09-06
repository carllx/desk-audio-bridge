"""CoreAudio device resolver for macOS.

Resolves MacBook built-in speakers stably by inspecting:
- CoreAudio Transport Type == "bltn" (Built-in)
- Actual output channel capacity > 0 (parsed from AudioBufferList output stream configuration)
- Stable CoreAudio Device UID
- Diagnostic name preference (e.g. "Speakers", "内置扬声器", "Built-in Output") and default output fallback

Maps stable identity to runtime AudioDeviceID without hardcoding temporary integers or UIDs into Git.
"""

import ctypes
import logging
import struct
from typing import List, NamedTuple, Optional

logger = logging.getLogger(__name__)

# FourCC helper
def _fourcc(s: str) -> int:
    return struct.unpack(">I", s.encode("ascii"))[0]

# CoreAudio constants
kAudioObjectSystemObject = 1
kAudioHardwarePropertyDevices = _fourcc("dev#")
kAudioHardwarePropertyDefaultOutputDevice = _fourcc("dOut")
kAudioHardwarePropertyDefaultInputDevice = _fourcc("dIn ")
kAudioObjectPropertyScopeGlobal = _fourcc("glob")
kAudioObjectPropertyScopeInput = _fourcc("inpt")
kAudioObjectPropertyScopeOutput = _fourcc("outp")
kAudioObjectPropertyElementMain = 0

kAudioObjectPropertyName = _fourcc("lnam")
kAudioDevicePropertyDeviceUID = _fourcc("uid ")
kAudioDevicePropertyTransportType = _fourcc("tran")
kAudioDevicePropertyStreamConfiguration = _fourcc("slay")
kAudioDeviceTransportTypeBuiltIn = _fourcc("bltn")


class AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


class ResolvedAudioDevice(NamedTuple):
    device_id: int
    device_uid: str
    device_name: str
    is_builtin: bool
    output_channels: int
    is_default: bool
    input_channels: int = 0


class MacCoreAudioDeviceResolver:
    """Resolves the macOS built-in speakers endpoint dynamically via CoreAudio C API."""

    def __init__(self):
        try:
            self._coreaudio = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
            )
            self._cf = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
            )
            self._cf.CFStringGetCString.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_long,
                ctypes.c_uint32,
            ]
            self._cf.CFStringGetCString.restype = ctypes.c_bool
            self._cf.CFRelease.argtypes = [ctypes.c_void_p]
            self._initialized = True
        except Exception as exc:
            logger.warning("CoreAudio library initialization failed: %s", exc)
            self._initialized = False

    def _get_string_property(self, dev_id: int, selector: int) -> str:
        if not self._initialized:
            return ""
        val_ref = ctypes.c_void_p()
        val_size = ctypes.c_uint32(ctypes.sizeof(val_ref))
        addr = AudioObjectPropertyAddress(
            selector, kAudioObjectPropertyScopeGlobal, kAudioObjectPropertyElementMain
        )
        st = self._coreaudio.AudioObjectGetPropertyData(
            dev_id, ctypes.byref(addr), 0, None, ctypes.byref(val_size), ctypes.byref(val_ref)
        )
        if st == 0 and val_ref.value:
            buf = ctypes.create_string_buffer(512)
            # 0x08000100 = kCFStringEncodingUTF8
            if self._cf.CFStringGetCString(val_ref, buf, 512, 0x08000100):
                res = buf.value.decode("utf-8", errors="replace")
            else:
                res = ""
            self._cf.CFRelease(val_ref)
            return res
        return ""

    def _get_transport_type(self, dev_id: int) -> int:
        if not self._initialized:
            return 0
        tran = ctypes.c_uint32(0)
        tran_size = ctypes.c_uint32(ctypes.sizeof(tran))
        addr = AudioObjectPropertyAddress(
            kAudioDevicePropertyTransportType,
            kAudioObjectPropertyScopeGlobal,
            kAudioObjectPropertyElementMain,
        )
        st = self._coreaudio.AudioObjectGetPropertyData(
            dev_id, ctypes.byref(addr), 0, None, ctypes.byref(tran_size), ctypes.byref(tran)
        )
        if st == 0:
            return tran.value
        return 0

    def _get_output_channels(self, dev_id: int) -> int:
        if not self._initialized:
            return 0
        addr = AudioObjectPropertyAddress(
            kAudioDevicePropertyStreamConfiguration,
            kAudioObjectPropertyScopeOutput,
            kAudioObjectPropertyElementMain,
        )
        buf_size = ctypes.c_uint32(0)
        st = self._coreaudio.AudioObjectGetPropertyDataSize(
            dev_id, ctypes.byref(addr), 0, None, ctypes.byref(buf_size)
        )
        if st != 0 or buf_size.value == 0:
            return 0

        raw_buf = ctypes.create_string_buffer(buf_size.value)
        st = self._coreaudio.AudioObjectGetPropertyData(
            dev_id, ctypes.byref(addr), 0, None, ctypes.byref(buf_size), raw_buf
        )
        if st != 0:
            return 0

        # AudioBufferList on 64-bit macOS:
        # UInt32 mNumberBuffers (4 bytes)
        # 4 bytes padding (aligning mBuffers to 8 bytes boundary)
        # Array of AudioBuffer (16 bytes each: UInt32 channels, UInt32 size, void* data)
        try:
            num_buffers = struct.unpack_from("<I", raw_buf.raw, 0)[0]
            total_channels = 0
            offset = 8
            for _ in range(num_buffers):
                if offset + 4 <= buf_size.value:
                    channels = struct.unpack_from("<I", raw_buf.raw, offset)[0]
                    total_channels += channels
                    offset += 16
            return total_channels
        except Exception:
            return 0

    def _get_input_channels(self, dev_id: int) -> int:
        if not self._initialized:
            return 0
        addr = AudioObjectPropertyAddress(
            kAudioDevicePropertyStreamConfiguration,
            kAudioObjectPropertyScopeInput,
            kAudioObjectPropertyElementMain,
        )
        buf_size = ctypes.c_uint32(0)
        st = self._coreaudio.AudioObjectGetPropertyDataSize(
            dev_id, ctypes.byref(addr), 0, None, ctypes.byref(buf_size)
        )
        if st != 0 or buf_size.value == 0:
            return 0

        raw_buf = ctypes.create_string_buffer(buf_size.value)
        st = self._coreaudio.AudioObjectGetPropertyData(
            dev_id, ctypes.byref(addr), 0, None, ctypes.byref(buf_size), raw_buf
        )
        if st != 0:
            return 0

        try:
            num_buffers = struct.unpack_from("<I", raw_buf.raw, 0)[0]
            total_channels = 0
            offset = 8
            for _ in range(num_buffers):
                if offset + 4 <= buf_size.value:
                    channels = struct.unpack_from("<I", raw_buf.raw, offset)[0]
                    total_channels += channels
                    offset += 16
            return total_channels
        except Exception:
            return 0

    def _get_default_output_device_id(self) -> int:
        if not self._initialized:
            return 0
        addr = AudioObjectPropertyAddress(
            kAudioHardwarePropertyDefaultOutputDevice,
            kAudioObjectPropertyScopeGlobal,
            kAudioObjectPropertyElementMain,
        )
        default_dev = ctypes.c_uint32(0)
        size = ctypes.c_uint32(ctypes.sizeof(default_dev))
        st = self._coreaudio.AudioObjectGetPropertyData(
            kAudioObjectSystemObject,
            ctypes.byref(addr),
            0,
            None,
            ctypes.byref(size),
            ctypes.byref(default_dev),
        )
        if st == 0:
            return default_dev.value
        return 0

    def _get_default_input_device_id(self) -> int:
        if not self._initialized:
            return 0
        addr = AudioObjectPropertyAddress(
            kAudioHardwarePropertyDefaultInputDevice,
            kAudioObjectPropertyScopeGlobal,
            kAudioObjectPropertyElementMain,
        )
        default_dev = ctypes.c_uint32(0)
        size = ctypes.c_uint32(ctypes.sizeof(default_dev))
        st = self._coreaudio.AudioObjectGetPropertyData(
            kAudioObjectSystemObject,
            ctypes.byref(addr),
            0,
            None,
            ctypes.byref(size),
            ctypes.byref(default_dev),
        )
        if st == 0:
            return default_dev.value
        return 0

    def enumerate_output_devices(self) -> List[ResolvedAudioDevice]:
        if not self._initialized:
            return []

        addr = AudioObjectPropertyAddress(
            kAudioHardwarePropertyDevices,
            kAudioObjectPropertyScopeGlobal,
            kAudioObjectPropertyElementMain,
        )
        size = ctypes.c_uint32(0)
        st = self._coreaudio.AudioObjectGetPropertyDataSize(
            kAudioObjectSystemObject, ctypes.byref(addr), 0, None, ctypes.byref(size)
        )
        if st != 0 or size.value == 0:
            return []

        num_devices = size.value // ctypes.sizeof(ctypes.c_uint32)
        dev_ids = (ctypes.c_uint32 * num_devices)()
        st = self._coreaudio.AudioObjectGetPropertyData(
            kAudioObjectSystemObject,
            ctypes.byref(addr),
            0,
            None,
            ctypes.byref(size),
            ctypes.byref(dev_ids),
        )
        if st != 0:
            return []

        default_id = self._get_default_output_device_id()
        devices = []
        for dev_id in dev_ids:
            uid = self._get_string_property(dev_id, kAudioDevicePropertyDeviceUID)
            name = self._get_string_property(dev_id, kAudioObjectPropertyName)
            tran = self._get_transport_type(dev_id)
            channels = self._get_output_channels(dev_id)
            is_builtin = (tran == kAudioDeviceTransportTypeBuiltIn)
            is_default = (dev_id == default_id)

            if channels > 0:
                devices.append(
                    ResolvedAudioDevice(
                        device_id=dev_id,
                        device_uid=uid,
                        device_name=name,
                        is_builtin=is_builtin,
                        output_channels=channels,
                        is_default=is_default,
                    )
                )
        return devices

    def resolve_builtin_speaker_device(self) -> Optional[ResolvedAudioDevice]:
        """Stably resolves the MacBook built-in speaker output device.
        
        Priority:
        1. Built-in transport (`bltn`) + output channels > 0 + name contains speaker keywords
        2. Built-in transport (`bltn`) + output channels > 0 + is default output device
        3. Any Built-in transport (`bltn`) with output channels > 0
        
        Refuses to fallback to non-built-in devices (virtual drivers, HDMI, etc.).
        """
        all_outputs = self.enumerate_output_devices()
        builtin_outputs = [d for d in all_outputs if d.is_builtin and d.output_channels > 0]
        if not builtin_outputs:
            logger.warning("No built-in output devices found with active output channels")
            return None

        # Priority 1: Builtin with speaker in name
        speaker_keywords = ("speaker", "扬声器", "built-in output", "internal speaker")
        for d in builtin_outputs:
            lower_name = d.device_name.lower()
            if any(kw in lower_name for kw in speaker_keywords):
                return d

        # Priority 2: Builtin default
        for d in builtin_outputs:
            if d.is_default:
                return d

        # Priority 3: First available builtin output
        return builtin_outputs[0]

    def enumerate_input_devices(self) -> List[ResolvedAudioDevice]:
        if not self._initialized:
            return []

        addr = AudioObjectPropertyAddress(
            kAudioHardwarePropertyDevices,
            kAudioObjectPropertyScopeGlobal,
            kAudioObjectPropertyElementMain,
        )
        size = ctypes.c_uint32(0)
        st = self._coreaudio.AudioObjectGetPropertyDataSize(
            kAudioObjectSystemObject, ctypes.byref(addr), 0, None, ctypes.byref(size)
        )
        if st != 0 or size.value == 0:
            return []

        num_devices = size.value // ctypes.sizeof(ctypes.c_uint32)
        dev_ids = (ctypes.c_uint32 * num_devices)()
        st = self._coreaudio.AudioObjectGetPropertyData(
            kAudioObjectSystemObject,
            ctypes.byref(addr),
            0,
            None,
            ctypes.byref(size),
            ctypes.byref(dev_ids),
        )
        if st != 0:
            return []

        default_id = self._get_default_input_device_id()
        devices = []
        for dev_id in dev_ids:
            uid = self._get_string_property(dev_id, kAudioDevicePropertyDeviceUID)
            name = self._get_string_property(dev_id, kAudioObjectPropertyName)
            tran = self._get_transport_type(dev_id)
            channels = self._get_input_channels(dev_id)
            is_builtin = (tran == kAudioDeviceTransportTypeBuiltIn)
            is_default = (dev_id == default_id)

            if channels > 0:
                devices.append(
                    ResolvedAudioDevice(
                        device_id=dev_id,
                        device_uid=uid,
                        device_name=name,
                        is_builtin=is_builtin,
                        output_channels=0,
                        is_default=is_default,
                        input_channels=channels,
                    )
                )
        return devices

    def resolve_builtin_microphone_device(self) -> Optional[ResolvedAudioDevice]:
        """Stably resolves the MacBook built-in microphone input device.

        Priority:
        1. Built-in transport (`bltn`) + input channels > 0 + name contains microphone keywords
        2. Built-in transport (`bltn`) + input channels > 0 + is default input device
        3. Any Built-in transport (`bltn`) with input channels > 0

        Refuses to fallback to non-built-in devices (virtual drivers, AirPods, iPhone Continuity, USB mic, etc.).
        """
        all_inputs = self.enumerate_input_devices()
        builtin_inputs = [d for d in all_inputs if d.is_builtin and d.input_channels > 0]
        if not builtin_inputs:
            logger.warning("No built-in input devices found with active input channels")
            return None

        # Priority 1: Builtin with microphone in name
        mic_keywords = ("microphone", "麦克风", "mic", "built-in input", "internal mic")
        for d in builtin_inputs:
            lower_name = d.device_name.lower()
            if any(kw in lower_name for kw in mic_keywords):
                return d

        # Priority 2: Builtin default
        for d in builtin_inputs:
            if d.is_default:
                return d

        # Priority 3: First available builtin input
        return builtin_inputs[0]
