"""Speaker receiver pipeline builder for macOS.

Constructs the verified canonical GStreamer command line for the Mac speaker receiver:
gst-launch-1.0 -m \
  udpsrc address=<MAC_BIND_IP> port=<PORT> \
  caps="application/x-rtp,media=(string)audio,encoding-name=(string)L16,clock-rate=(int)48000,encoding-params=(string)2,channels=(int)2,payload=(int)96" \
  ! rtpjitterbuffer latency=80 \
  ! rtpL16depay \
  ! audioconvert \
  ! audioresample \
  ! osxaudiosink [device=<DEVICE_ID>]
"""

import os
import shutil
from typing import List, Optional

DEFAULT_MACOS_GST_BIN = "/Library/Frameworks/GStreamer.framework/Versions/1.0/bin/gst-launch-1.0"


class SpeakerReceiverBuilder:
    """Builds the canonical GStreamer speaker receiver command on macOS."""

    def __init__(self, gst_path: Optional[str] = None):
        env_path = os.environ.get("GSTREAMER_BIN")
        if gst_path:
            self.gst_path = gst_path
        elif env_path and os.path.exists(env_path):
            self.gst_path = env_path
        elif os.path.exists(DEFAULT_MACOS_GST_BIN):
            self.gst_path = DEFAULT_MACOS_GST_BIN
        else:
            self.gst_path = shutil.which("gst-launch-1.0") or DEFAULT_MACOS_GST_BIN

    def is_gstreamer_available(self) -> bool:
        return os.path.exists(self.gst_path)

    def build_receiver_command(
        self,
        local_bind_ip: str,
        local_port: int = 5004,
        device_id: Optional[int] = None,
    ) -> List[str]:
        """Constructs the canonical command arguments list as individual tokens."""
        caps = (
            "application/x-rtp,"
            "media=(string)audio,"
            "encoding-name=(string)L16,"
            "clock-rate=(int)48000,"
            "encoding-params=(string)2,"
            "channels=(int)2,"
            "payload=(int)96"
        )
        cmd = [
            self.gst_path,
            "-m",
            "udpsrc",
            f"address={local_bind_ip}",
            f"port={local_port}",
            f"caps={caps}",
            "!",
            "rtpjitterbuffer",
            "latency=80",
            "!",
            "rtpL16depay",
            "!",
            "audioconvert",
            "!",
            "audioresample",
            "!",
            "osxaudiosink",
        ]
        if device_id is not None:
            cmd.append(f"device={device_id}")

        return cmd
