# Windows Readiness Probe Report

## 1. Baseline & Environment
- **Canonical Baseline**: `129deb23827e2dc89e061be262ecc9f0fed95732`
- **Current Branch**: `probe/windows-readiness`
- **OS Version**: Microsoft Windows 11 Pro 64-bit (Version 10.0.22621, Build 22621)
- **CPU Architecture**: Intel Xeon CPU E5-1607 v3 @ 3.10GHz (4 cores, 4 logical processors, x86_64)

## 2. Resource Baseline (Idle / No Bridge Workload)
- **CPU Idle Load**: ~10% - 49% (background processes snapshot)
- **Physical RAM**: 15.90 GB Total, ~3.69 - 3.91 GB Free (~12.0 - 12.2 GB in use)
- **System Disk (C:)**: 232.08 GB Total, ~12.5 GB Free Space

## 3. Audio Hardware & Endpoints
- **Audio Adapters (Hardware)**:
  - Realtek High Definition Audio (Status: OK)
  - NVIDIA High Definition Audio (Status: OK)
- **Playback (Render) Devices**:
  - `Speakers (Realtek High Definition Audio)`: **Active** (`DeviceState: Active / 0x00000001`).
  - Default Playback Endpoint: Configured to `Speakers (Realtek High Definition Audio)` for Console, Multimedia, and Communications roles.
  - Other playback endpoints (Beats Flex, HDMI, iPhone Hands-Free): Unplugged or Not Present.
- **Recording (Capture) Devices**:
  - Physical Microphones & Line-In: **Unplugged** (`DeviceState: Unplugged / 0x00000008` or Not Present).
  - Default Recording Endpoint: **None** (CoreAudio returns `ERROR_NOT_FOUND` / `0x80070490` for Console, Multimedia, Communications).
- **Stereo Mix (立体声混音)**:
  - Exists in Realtek driver endpoint registry, but is currently **Disabled / Hidden** (`DeviceState: 0x10000001`, inactive in CoreAudio endpoint enumeration).
- **Virtual Audio Cables / Devices**:
  - VB-CABLE: **Not Installed**
  - VoiceMeeter: **Not Installed**
  - Other virtual audio devices: **None present**

## 4. Target Software Presence
- **SonoBus**: **Not Installed** (no binary, service, or registry entries).
- **VB-CABLE / VoiceMeeter**: **Not Installed**.
- **Deskflow**:
  - Status: **Installed & Running** (v1.26.0.0).
  - Background Services: `Deskflow` service running (Automatic).
  - Core Processes: `deskflow-core`, `deskflow-daemon`, `synergyc`, `synergyd`.
  - Connectivity: Actively connected to Mac host via port 24800 (`TCP Established`).
  - Integrity: Intact, unmodified.

## 5. Network & LAN Readiness
- **Active Interfaces**:
  - Wi-Fi: Intel Wireless-AC 9260 (Status: Up, ~390 Mbps, Profile: Public, IPv4 Internet)
  - Ethernet: Intel Ethernet Connection I218-LM (Status: Up, 1 Gbps, Profile: Public, NoTraffic)
- **Connectivity with Mac**:
  - Deskflow LAN session is active and stable on port 24800, confirming mutual LAN reachability between Windows and Mac hosts.
- **Firewall Observations**:
  - Domain, Private, and Public profiles are all enabled.
  - Wi-Fi network profile is currently categorized as `Public`. Windows Firewall allows Deskflow because explicit inbound allow rules exist for `Any` profile.
  - For future P2P / socket tools (e.g. SonoBus), firewall inbound rules or switching the network profile to `Private` will be required.

## 6. Key Blocker / Gap for Next Phase
- **Absence of Active Recording Endpoint**:
  Windows currently has zero active recording endpoints (microphones are unplugged, Stereo Mix is disabled).
  For the Windows side to consume the Mac microphone stream as a Windows microphone input (the *Windows Virtual Microphone Endpoint*), Windows will require a virtual audio endpoint (e.g. virtual audio cable driver) or an enabled input device, otherwise applications expecting microphone input will find no capture device.
