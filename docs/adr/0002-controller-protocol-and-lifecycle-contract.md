# Shared Controller Protocol & Architecture Contract

> Cross-Machine SSOT for desk-audio-bridge Controller Phase 1 (Issue #20).

## 1. Overview

The `desk-audio-bridge` controller is a lightweight user-mode control plane that manages the lifecycle of GStreamer media pipelines.
The controller itself runs per-user, while the actual media transport (GStreamer RTP/UDP pipelines) is instantiated, supervised, and torn down on demand.

## 2. Control Plane Protocol & Peer Discovery

### Wire Protocol
- Transport: UDP on port `50100` (`DEFAULT_CONTROL_PORT`).
- Payload: UTF-8 JSON.
- Version: `1`.

### Handshake Messages
1. **`HandshakeHello`**:
   ```json
   {
     "version": 1,
     "role": "windows" | "macos",
     "instance_id": "<opaque-instance-id>",
     "speaker_port": 5004
   }
   ```
2. **`HandshakeAck`**:
   ```json
   {
     "version": 1,
     "role": "windows" | "macos",
     "instance_id": "<opaque-instance-id>",
     "speaker_port": 5004,
     "peer_instance_id": "<opaque-peer-instance-id>"
   }
   ```

### Addressing & Routing Rules
- No persistent IP addresses or interface indices in configuration files or Git.
- Senders discover peers dynamically via UDP broadcast or directed LAN packets.
- The receiving address of the opposite peer's packets establishes the peer IP for media transport.

## 3. Speaker Path Media Pipeline Specification

- Encoding: Uncompressed RTP L16 Big-Endian PCM (`format=S16BE,rate=48000,channels=2`).
- Payload Type: `pt=96`.
- Default Media Port: `5004` (UDP).

### Windows Sender (Produced by Windows Controller)
```powershell
gst-launch-1.0 -v wasapi2src loopback=true low-latency=true [device=<ENDPOINT_ID>] `
  ! queue max-size-buffers=0 max-size-time=2000000000 max-size-bytes=0 `
  ! audioconvert `
  ! audioresample `
  ! audio/x-raw,format=S16BE,rate=48000,channels=2 `
  ! rtpL16pay pt=96 `
  ! udpsink host=<PEER_IP> port=5004 sync=false
```

### macOS Receiver (Required Contract for Mac IDE Relay)
```bash
gst-launch-1.0 -m \
  udpsrc address=<MAC_BIND_IP> port=5004 \
  caps="application/x-rtp,media=(string)audio,encoding-name=(string)L16,clock-rate=(int)48000,encoding-params=(string)2,channels=(int)2,payload=(int)96" \
  ! rtpjitterbuffer latency=80 \
  ! rtpL16depay \
  ! audioconvert \
  ! audioresample \
  ! osxaudiosink
```

## 4. Lifecycle & Ownership Contract

- **Singleton Guarantee**: Only one controller instance per host machine (enforced via local bind lock port `50105`).
- **Idempotent Start**: Calling `Start` multiple times reconciles to desired state `ENABLED` without launching duplicate pipelines.
- **Idempotent Stop**: Calling `Stop` sets `STOPPED_BY_USER` and terminates only owned child processes.
- **Read-Only Status**: Querying status never triggers side-effects, reconciliation, or pipeline spawning.
- **Owned Child Management**:
  - Windows controller isolates children using Windows Job Objects (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`).
  - No global `killall gst-launch` or process-name-based killing. Unrelated user GStreamer processes remain untouched.
