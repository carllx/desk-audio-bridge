"""Microphone receiver pipeline builder for Windows.

Constructs the verified canonical GStreamer command line for the Windows microphone receiver:
gst-launch-1.0 -m \
  udpsrc [address=<LOCAL_BIND_IP>] port=<PORT> \
  caps="application/x-rtp,media=(string)audio,encoding-name=(string)L16,clock-rate=(int)48000,channels=(int)1,payload=(int)97" \
  ! rtpjitterbuffer latency=80 \
  ! rtpL16depay \
  ! audioconvert \
  ! audioresample \
  ! wasapisink low-latency=true sync=false [device=<PACK43_RENDER_DEVICE_ID>]
"""

import os
import shutil
from typing import List, Optional

from bridge_core.contract import (
    CANONICAL_MIC_CHANNELS,
    CANONICAL_MIC_ENCODING_NAME,
    CANONICAL_MIC_PAYLOAD_TYPE,
    CANONICAL_MIC_SAMPLE_RATE,
    DEFAULT_MIC_RTP_PORT,
)

DEFAULT_WINDOWS_GST_BIN = r"C:\Program Files\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe"


class MicrophoneReceiverBuilder:
    """Builds the canonical GStreamer microphone receiver command on Windows."""

    def __init__(self, gst_path: Optional[str] = None):
        env_path = os.environ.get("GSTREAMER_BIN")
        if gst_path:
            self.gst_path = gst_path
        elif env_path and os.path.exists(env_path):
            self.gst_path = env_path
        elif os.path.exists(DEFAULT_WINDOWS_GST_BIN):
            self.gst_path = DEFAULT_WINDOWS_GST_BIN
        else:
            self.gst_path = shutil.which("gst-launch-1.0.exe") or shutil.which("gst-launch-1.0") or DEFAULT_WINDOWS_GST_BIN

    def is_gstreamer_available(self) -> bool:
        return os.path.exists(self.gst_path)

    def build_receiver_command(
        self,
        local_bind_ip: Optional[str] = None,
        local_port: int = DEFAULT_MIC_RTP_PORT,
        device_id: Optional[str] = None,
    ) -> List[str]:
        """Constructs the canonical command arguments list as individual tokens."""
        caps = (
            f"application/x-rtp,"
            f"media=(string)audio,"
            f"encoding-name=(string){CANONICAL_MIC_ENCODING_NAME},"
            f"clock-rate=(int){CANONICAL_MIC_SAMPLE_RATE},"
            f"channels=(int){CANONICAL_MIC_CHANNELS},"
            f"payload=(int){CANONICAL_MIC_PAYLOAD_TYPE}"
        )
        cmd = [
            self.gst_path,
            "-m",
            "udpsrc",
        ]
        if local_bind_ip and local_bind_ip != "0.0.0.0":
            cmd.append(f"address={local_bind_ip}")
        cmd.append(f"port={local_port}")
        cmd.append(f"caps={caps}")

        cmd.extend([
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
            "wasapisink",
            "low-latency=true",
            "sync=false",
        ])
        if device_id:
            cmd.append(f"device={device_id}")

        return cmd
