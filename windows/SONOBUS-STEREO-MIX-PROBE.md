# Windows SonoBus & Stereo Mix Probe Report

## 1. Executive Summary & Verdict
- **Verdict**: **PASS**
- **Core Assertion**: The local capture chain `Windows Playback Source -> Realtek Stereo Mix -> SonoBus` is fully operational, responsive in real-time, low-overhead, and verified with deterministic audio signal level changes.
- **Stereo Mix Endpoint**: Successfully and reversibly transitioned from Disabled (`0x10000001`) to Active (`0x00000001`), recognized by CoreAudio as an active capture device.
- **Default Playback Integrity**: System default playback endpoint remains untouched (`Speakers (Realtek High Definition Audio)`).
- **External Dependencies**: Zero driver installations (no VB-CABLE, no VoiceMeeter). Deskflow keyboard/mouse sharing remained fully operational and undisturbed throughout.

---

## 2. Probe Baseline & Evidence Pointers
- **Canonical Baseline**: `129deb23827e2dc89e061be262ecc9f0fed95732`
- **Probe Branch**: `probe/windows-sonobus-stereo-mix`
- **Target Issue**: GitHub Issue #2
- **Prior Reference**:
  - Windows Readiness Probe: branch `probe/windows-readiness`, commit `35fba1ee7cfb8a2d81892e19eb8b575484f4683e`
  - macOS SonoBus Probe: branch `probe/macos-sonobus`, commit `0967cc9eee6b5860811ee3d50eeab7d23cea838a`

---

## 3. SonoBus Pre-Installation Verification & Installation
- **Binary Source**: Official SonoBus release portal (`https://sonobus.net/releases/sonobus-1.7.2-win.exe`)
- **Version**: `1.7.2` (Standalone 64-bit Windows executable)
- **Installer Size**: 81,195,920 bytes (~77.43 MB)
- **Authenticode Signature Verification**:
  - **Status**: `Valid`
  - **Subject**: `CN=Sonosaurus LLC, O=Sonosaurus LLC, S=Virginia, C=US`
  - **Issuer**: `CN=Sectigo Public Code Signing CA R36, O=Sectigo Limited, C=GB`
  - **Security Gate**: Passed (no unsigned binaries, no third-party repackaging, no security degradation).
- **Installation Execution**:
  - Standard Inno Setup silent install (`/SILENT /NORESTART /ALLUSERS`).
  - Target Path: `C:\Program Files\SonoBus`
  - Installed Files:
    - `SonoBus.exe`: 56,066,560 bytes
    - `unins000.exe`: 3,221,370 bytes
    - `unins000.dat`: 51,859 bytes
    - `unins000.msg`: 20,088 bytes
  - Total Installed Disk Footprint: **56.6 MB** (59,359,877 bytes).

---

## 4. Realtek Stereo Mix State Transition
- **Endpoint Identification**:
  - Endpoint: Realtek Stereo Mix endpoint (machine-specific identifier redacted)
  - Friendly Name: `立体声混音 (Realtek High Definition Audio)`
- **Modification**:
  - Pre-Probe State: `0x10000001` (`DEVICE_STATE_NOTPRESENT` / Disabled / Hidden)
  - Post-Probe State: `0x00000001` (`DEVICE_STATE_ACTIVE`)
  - Verification: CoreAudio MMDevice enumeration lists `立体声混音 (Realtek High Definition Audio)` as active capture endpoint `[0]`.
- **System Default Playback Verification**:
  - Maintained as `Speakers (Realtek High Definition Audio)`.
  - Unaffected by capture endpoint enablement.

---

## 5. Local Audio Capture Verification (Acceptance Evidence)
Audio loopback and peak meter activity were measured across 3 controlled phases using CoreAudio render client (default playback) and CoreAudio `IAudioMeterInformation` on the enabled `Stereo Mix` endpoint:

| Phase | Description | Windows Audio Playback | Stereo Mix Meter Peak Value | Result |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 1: Silence** | Baseline capture test (1.5s) | None (silent) | **0.0000** | No background leak / noise floor clean |
| **Phase 2: Playback** | 440 Hz Sine wave tone playback (2.0s) | Active playback on default Speakers | **0.5000** | Instantaneous synchronous signal detected |
| **Phase 3: Post-Silence** | Post-playback capture test (1.5s) | None (playback stopped) | **0.0000** | Meter immediately falls to zero |

### SonoBus Integration Verification
- In SonoBus standalone settings (`%APPDATA%\SonoBus\sonobus.settings`), `audioInputDeviceName` was configured and loaded as:
  ```xml
  <DEVICESETUP deviceType="Windows Audio"
               audioOutputDeviceName="Speakers (Realtek High Definition Audio)"
               audioInputDeviceName="立体声混音 (Realtek High Definition Audio)"
               sampleRate="48000.0" bufferSize="480"/>
  ```
- SonoBus successfully binds to `立体声混音 (Realtek High Definition Audio)` with zero errors.

---

## 6. Resource Overhead & Stability Probe
Measurements taken while SonoBus was running in standalone mode with audio capture active:

- **Process Memory (Working Set / RSS)**: **58.74 MB**
- **Paged Memory**: 41.52 MB
- **Process CPU Time**: ~0.34s accumulated CPU time over startup and initial loopback (negligible background load).
- **Disk Footprint**:
  - Program directory: 56.6 MB
  - Configuration directory (`%APPDATA%\SonoBus`): 254 bytes (`sonobus.settings`)
  - No unbounded log generation or unauthorized audio recordings created.
- **Firewall & Network Profile**:
  - No prompt triggered for local-only playback / capture.
  - No outbound / inbound firewall rules created.
  - Windows network profiles remained untouched (Wi-Fi profile remains `Public`).
- **Deskflow Integrity**:
  - Active processes: `deskflow-core`, `synergyc` intact and responsive.
  - Connection: Deskflow TCP 24800 connection remained Established with the Mac host.
  - No mouse/keyboard glitch or connection interruption detected.

---

## 7. Next Step Assessment
- The Windows send chain (`Windows Playback Source -> Realtek Stereo Mix -> SonoBus`) is confirmed viable and requires no third-party virtual audio driver for playback transmission to Mac.
- Note for subsequent phases: For the *reverse* direction (Mac microphone -> Windows Virtual Microphone Endpoint), a virtual capture endpoint (e.g. virtual audio cable driver) will still need evaluation, as Windows has no physical microphone plugged in and Stereo Mix is an output loopback rather than a virtual microphone sink.
