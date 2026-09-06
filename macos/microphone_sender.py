"""Microphone sender pipeline builder for macOS.

Constructs the verified canonical GStreamer command line for the Mac microphone sender:
gst-launch-1.0 -m \
  osxaudiosrc [device=<DEVICE_ID>] \
  ! audioconvert \
  ! audioresample \
  ! audio/x-raw,format=S16BE,rate=48000,channels=1 \
  ! rtpL16pay pt=97 \
  ! udpsink host=<WINDOWS_PEER> port=5006 sync=false [bind-address=<LOCAL_IP>]
"""

import os
import shutil
from typing import List, Optional

from bridge_core.contract import (
    CANONICAL_MIC_CHANNELS,
    CANONICAL_MIC_PAYLOAD_TYPE,
    CANONICAL_MIC_SAMPLE_RATE,
    DEFAULT_MIC_RTP_PORT,
)

DEFAULT_MACOS_GST_BIN = "/Library/Frameworks/GStreamer.framework/Versions/1.0/bin/gst-launch-1.0"


class MicrophoneSenderBuilder:
    """Builds the canonical GStreamer microphone sender command on macOS."""

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

    def build_sender_command(
        self,
        target_host: str,
        target_port: int = DEFAULT_MIC_RTP_PORT,
        device_id: Optional[int] = None,
        local_bind_ip: Optional[str] = None,
    ) -> List[str]:
        """Constructs the canonical command arguments list as individual tokens."""
        cmd = [
            self.gst_path,
            "-m",
            "osxaudiosrc",
        ]
        if device_id is not None:
            cmd.append(f"device={device_id}")

        cmd.extend([
            "!",
            "audioconvert",
            "!",
            "audioresample",
            "!",
            (
                f"audio/x-raw,"
                f"format=S16BE,"
                f"rate={CANONICAL_MIC_SAMPLE_RATE},"
                f"channels={CANONICAL_MIC_CHANNELS}"
            ),
            "!",
            "rtpL16pay",
            f"pt={CANONICAL_MIC_PAYLOAD_TYPE}",
            "!",
            "udpsink",
            f"host={target_host}",
            f"port={target_port}",
            "sync=false",
        ])
        if local_bind_ip and local_bind_ip != "0.0.0.0":
            cmd.append(f"bind-address={local_bind_ip}")

        return cmd
