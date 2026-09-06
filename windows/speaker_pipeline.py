"""Speaker pipeline builder for Windows.

Constructs the verified canonical GStreamer command line for the speaker path:
wasapi2src loopback=true low-latency=true [device=...]
  ! queue max-size-buffers=0 max-size-time=2000000000 max-size-bytes=0
  ! audioconvert
  ! audioresample
  ! audio/x-raw,format=S16BE,rate=48000,channels=2
  ! rtpL16pay pt=96
  ! udpsink host=<MAC_IP> port=<SPEAKER_PORT> sync=false [bind-address=<LOCAL_IP>]
"""

import os
from typing import List, Optional

DEFAULT_WINDOWS_GST_BIN = r"C:\Program Files\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe"


class SpeakerPipelineBuilder:
    """Builds the canonical GStreamer speaker sender command."""

    def __init__(self, gst_path: Optional[str] = None):
        self.gst_path = gst_path or os.environ.get("GSTREAMER_BIN", DEFAULT_WINDOWS_GST_BIN)

    def is_gstreamer_available(self) -> bool:
        return os.path.exists(self.gst_path)

    def build_sender_command(
        self,
        target_host: str,
        target_port: int,
        device_id: Optional[str] = None,
        local_bind_ip: Optional[str] = None,
    ) -> List[str]:
        """Constructs the canonical command arguments list as individual tokens."""
        cmd = [
            self.gst_path,
            "-v",
            "wasapi2src",
            "loopback=true",
            "low-latency=true",
        ]
        if device_id:
            cmd.append(f"device={device_id}")

        cmd.extend([
            "!",
            "queue",
            "max-size-buffers=0",
            "max-size-time=2000000000",
            "max-size-bytes=0",
            "!",
            "audioconvert",
            "!",
            "audioresample",
            "!",
            "audio/x-raw,format=S16BE,rate=48000,channels=2",
            "!",
            "rtpL16pay",
            "pt=96",
            "!",
            "udpsink",
            f"host={target_host}",
            f"port={target_port}",
            "sync=false",
        ])
        if local_bind_ip and local_bind_ip != "0.0.0.0":
            cmd.append(f"bind-address={local_bind_ip}")

        return cmd
