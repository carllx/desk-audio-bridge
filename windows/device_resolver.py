"""Windows device resolver for desk-audio-bridge.

Provides runtime resolution of the default multimedia playback render endpoint
using Windows CoreAudio IMMDeviceEnumerator COM API via ctypes.
Does NOT store or hardcode specific endpoint GUIDs.
"""

import ctypes
from ctypes import wintypes
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# COM GUID definition
class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]

CLSID_MMDeviceEnumerator = GUID(
    0xBCDE0395, 0xE52F, 0x467C, (wintypes.BYTE * 8)(0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69, 0x2E)
)
IID_IMMDeviceEnumerator = GUID(
    0xA95664D2, 0x9614, 0x4F35, (wintypes.BYTE * 8)(0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6)
)

CLSCTX_ALL = 23
E_RENDER = 0
ER_MULTIMEDIA = 1


class WindowsDeviceResolver:
    """Resolves audio endpoint devices on Windows at runtime."""

    def resolve_default_playback_endpoint_id(self) -> Optional[str]:
        """Resolves the active default multimedia render endpoint ID.
        
        Returns the endpoint ID string (e.g. '{0.0.0.00000000}.{...}') or None if resolution fails.
        """
        ole32 = ctypes.windll.ole32
        hr_init = ole32.CoInitialize(None)
        
        p_enum = ctypes.c_void_p()
        try:
            hr = ole32.CoCreateInstance(
                ctypes.byref(CLSID_MMDeviceEnumerator),
                None,
                CLSCTX_ALL,
                ctypes.byref(IID_IMMDeviceEnumerator),
                ctypes.byref(p_enum),
            )
            if hr != 0 or not p_enum.value:
                logger.error("Failed to CoCreateInstance IMMDeviceEnumerator (hr=%d)", hr)
                return None

            vtable = ctypes.cast(p_enum, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            # IMMDeviceEnumerator VTable:
            # 0: QueryInterface, 1: AddRef, 2: Release, 3: EnumAudioEndpoints, 4: GetDefaultAudioEndpoint
            get_default_endpoint_proto = ctypes.WINFUNCTYPE(
                wintypes.LONG,
                ctypes.c_void_p,
                wintypes.UINT,
                wintypes.UINT,
                ctypes.POINTER(ctypes.c_void_p),
            )
            get_default_endpoint = get_default_endpoint_proto(vtable[4])

            p_endpoint = ctypes.c_void_p()
            hr = get_default_endpoint(p_enum, E_RENDER, ER_MULTIMEDIA, ctypes.byref(p_endpoint))
            if hr != 0 or not p_endpoint.value:
                logger.error("Failed GetDefaultAudioEndpoint (hr=%d)", hr)
                return None

            try:
                dev_vtable = ctypes.cast(
                    p_endpoint, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
                ).contents
                # IMMDevice VTable:
                # 0: QueryInterface, 1: AddRef, 2: Release, 3: Activate, 4: OpenPropertyStore, 5: GetId, 6: GetState
                get_id_proto = ctypes.WINFUNCTYPE(
                    wintypes.LONG, ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)
                )
                get_id = get_id_proto(dev_vtable[5])

                str_ptr = wintypes.LPWSTR()
                hr = get_id(p_endpoint, ctypes.byref(str_ptr))
                if hr != 0 or not str_ptr.value:
                    logger.error("Failed GetId on endpoint (hr=%d)", hr)
                    return None

                endpoint_id = str(str_ptr.value)
                ole32.CoTaskMemFree(str_ptr)
                return endpoint_id
            finally:
                release_proto = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)
                release_dev = release_proto(dev_vtable[2])
                release_dev(p_endpoint)
        finally:
            if p_enum.value:
                release_proto = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)
                release_enum = release_proto(vtable[2])
                release_enum(p_enum)
            if hr_init >= 0:
                ole32.CoUninitialize()
