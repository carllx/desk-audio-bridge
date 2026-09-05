# desk-audio-bridge — Browser Handoff — 2026-09-05

> 用于 Fresh Browser session 接手当前项目。  
> 本文只记录可复用的项目状态、证据、边界与下一步；不要把上一轮 IDE 的临时 PID、后台进程或口头“已启动”声明当成当前事实。

---

## 0. Workflow / Project Coordinates

```text
WORKFLOW_REPO: https://github.com/carllx/matt-browser-workflow
WORKFLOW_REF: v0.13
PROJECT_REPO: https://github.com/carllx/desk-audio-bridge
MAT_REPO: https://github.com/mattpocock/skills
MAT_REF: 8b78b531ab965735c5dc74f6f7a219e1e37326df
MAT_ROUTER_PATH: skills/engineering/ask-matt/SKILL.md
```

- Workflow `v0.13` immutable tag was re-resolved during handoff; tag ref exists and resolves to annotated tag object `b8bcd629bccaa06a177cc076f4af303d77c32f12`.
- Project default branch: `main`.
- Matt lock remains pinned; do not auto-upgrade.
- `/setup-matt-pocock-skills` had already been completed for this repository before the current frontier.

Fresh Browser must still follow project startup rules: bounded sync, verify current default/active refs and tracker, then continue from the verified frontier rather than relying only on this handoff.

---

## 1. User Mission

User wants one coherent two-computer desk audio system:

1. **Windows system/app audio → MacBook Air speakers**.
2. **MacBook Air built-in microphone → Windows as a usable microphone/input**.
3. Prefer no additional hardware during PoC.
4. Low CPU / RAM / disk overhead matters, especially on the MacBook Air M1 with 8 GB memory.
5. Low latency and stable playback matter more than a technically successful but crackling/intermittent stream.
6. Final system should minimize manual switching.
7. Deskflow remains independent; do not merge/fork Deskflow for audio transport.

Human listening is a hard acceptance gate. IDE meter/log success is insufficient if actual sound is delayed, crackling, intermittent, incomplete, or routed incorrectly.

---

## 2. Host Facts

### Mac Host

Previously verified:
- MacBook Air M1 (`MacBookAir10,1`), arm64, 8 GB.
- macOS 26.5.2 build `25F84` at readiness time.
- MacBook Air Speakers available, stereo, 48 kHz.
- MacBook Air Microphone available, mono, 48 kHz.
- Deskflow runs on Mac side and stays independent.
- Mac memory/disk pressure exists; avoid unnecessary packages and persistent logs.

Current GStreamer:
- `/Library/Frameworks/GStreamer.framework`
- official GStreamer Universal installer
- version `1.24.8`
- Universal `x86_64 + arm64`
- approx. `461 MB`
- CLI:
  - `/Library/Frameworks/GStreamer.framework/Commands/gst-launch-1.0`
  - `/Library/Frameworks/GStreamer.framework/Commands/gst-inspect-1.0`
- required receiver plugins verified:
  - `udpsrc`
  - `rtpjitterbuffer`
  - `rtpopusdepay`
  - `opusdec`
  - `audioconvert`
  - `audioresample`
  - `osxaudiosink`
  - `autoaudiosink`
- local `audiotestsrc -> osxaudiosink` pipeline exited normally.
- lifecycle status: `KEEP_CANDIDATE`; do not update/reinstall by default.

### Windows Host

Previously verified:
- Windows 11 Pro 64-bit, build `10.0.22621` at readiness time.
- Realtek High Definition Audio present.
- NVIDIA / display audio render path also exists.
- User now reports audible PC monitor/screen speaker output, so never describe Windows as simply “having no speaker”.
- No usable physical/default microphone endpoint.
- Deskflow runs and remains functional during audio tests.
- HVCI / VBS / Secure Boot / Defender stay enabled.

Current GStreamer:
- official `1.28.6` MSVC x86_64 runtime
- binary path already verified:
  - `C:\Program Files\gstreamer\1.0\msvc_x86_64\bin\gst-launch-1.0.exe`
  - `C:\Program Files\gstreamer\1.0\msvc_x86_64\bin\gst-inspect-1.0.exe`
- `wasapisrc` available with `loopback=true`.
- sender plugins verified:
  - `opusenc`
  - `rtpopuspay`
  - `udpsink`
  - `audioconvert`
  - `audioresample`
- `wasapi2src` exists and was inspected late in the previous session, but no decisive human-quality comparison has been completed.

### Network

- Deskflow proved stable host-to-host connectivity.
- Later live probes verified a dedicated/direct `1 Gbps` Ethernet path between hosts.
- Prefer this direct path for audio PoC.
- Real IPs are runtime-only and intentionally omitted from this repository handoff; re-resolve them from live state.

---

## 3. Architecture Decision History

### 3.1 Deskflow

Decision: **协同设计，不合并项目**.

```text
双机桌面环境
├─ Deskflow
│  └─ keyboard / mouse / clipboard
└─ desk-audio-bridge
   └─ speaker / microphone / audio routing
```

Deskflow focus switching is not the desired default audio behavior; user wants merged/simultaneous audio capability, not “audio follows cursor focus”.

### 3.2 SonoBus

SonoBus 1.7.2 itself was proven compatible/lightweight on Mac and genuinely installed/runnable on Windows.

But the Windows system-audio capture routes used to feed SonoBus failed:
- Stereo Mix path failed real meter test.
- VB-CABLE driver failed PnP start with Code 10.

Therefore SonoBus is no longer the current Windows→Mac architecture anchor. If final architecture uses GStreamer, SonoBus on both hosts becomes experimental residue pending cleanup.

### 3.3 Current fundamental architecture

```text
Capture -> Transport -> Playback
```

For Windows→Mac, current candidate is pure user-mode:

```text
Windows app/system audio
  -> WASAPI Loopback
  -> GStreamer
  -> direct LAN
  -> GStreamer on Mac
  -> MacBook Air Speakers
```

Do not distort architecture merely to feed an app-specific input device.

---

## 4. GitHub Issue Map — Canonical

### Closed

- **#1** `Probe：验证 SonoBus 在当前 Mac 上的兼容性与资源开销`
  - completed positive compatibility/resource probe.

- **#2** `Probe：验证 Windows Stereo Mix → SonoBus 本地发送链`
  - completed negative.
  - Stereo Mix could be selected but did not carry the required actual signal into SonoBus.

- **#3** `Integration：Windows 系统播放音频经 SonoBus 输出到 MacBook 扬声器`
  - closed `not_planned` during this handoff.
  - superseded by #5 because its Stereo Mix/SonoBus preconditions are obsolete.

- **#4** `Probe：验证 VB-CABLE → SonoBus Windows 本地发送链`
  - completed negative.
  - official VB-CABLE Pack45, valid signature/WHQL, but device start Code 10.
  - do not disable HVCI/VBS/Secure Boot/Defender to force it.

### Open / Active

- **#5** `Probe：验证纯用户态 WASAPI Loopback → Mac 扬声器链路`
  - **CURRENT PRIMARY FRONTIER**.
  - status: **QUALITY FAIL / NOT ACCEPTED**.
  - a new canonical handoff comment was added during this handoff; use the newest comment as current status authority.

- **#6** `Probe：Mac 内置麦克风经网络送到 Windows 并形成可用输入`
  - open, queued.
  - do not start until #5 reaches a stable speaker-path gate.

---

## 5. Issue #5 — What Is Actually Proven

### 5.1 Windows local WASAPI capture — PASS

Official GStreamer 1.28.6 `wasapisrc loopback=true` captured real Windows playback.

Controlled three-phase proof:
- silence baseline around RMS `-189 dB`
- playback peak around `-25.70 dB`
- post-playback returned to digital silence

Resource sample from early proof:
- gst-launch RSS approx. `17.38 MB`
- low short-test CPU usage
- no recordings/raw dumps persisted
- Deskflow stayed healthy

This proves:
- native WASAPI loopback works;
- successful capture does not depend on Stereo Mix or VB-CABLE.

It does **not** prove failed VB-CABLE has been uninstalled.

### 5.2 Browser/YouTube coverage — eventually proven audible

There was an intermediate false negative where short system sounds worked but YouTube did not.

Later, using `role=multimedia`, user confirmed actual browser/YouTube audio did reach MacBook Air Speakers.

Therefore current blocker is **not source coverage**.

### 5.3 Cross-machine RTP/Opus — audible but not acceptable

A working structure existed conceptually as:

Windows:
```text
wasapisrc loopback=true
 -> audioconvert
 -> audioresample
 -> opusenc
 -> rtpopuspay
 -> udpsink
```

Mac:
```text
udpsrc
 -> rtpjitterbuffer latency=80
 -> rtpopusdepay
 -> opusdec
 -> audioconvert
 -> audioresample
 -> osxaudiosink
```

User heard real Windows/YouTube audio from Mac.

But human quality result:
- noticeable latency;
- crackling / popping;
- intermittent / incomplete audio;
- Windows local output was also still audible in later field use, causing confusing double sound.

Therefore: **audible != accepted**.

### 5.4 Candidate B was rejected

Windows IDE performed short stability tests and reported:
- baseline `low-latency=true` had dropped-sample warnings;
- explicit buffers such as `buffer-time=100ms latency-time=20ms` produced short windows with zero reported dropped samples.

IDE then overclaimed that this solved crackling.

Human result contradicted it: Mac playback remained intermittent/crackling and sometimes felt worse.

Canonical ruling:
- sender-side `0 dropped samples` is useful local evidence only;
- Candidate B is **NOT an accepted solution**;
- do not resume tuning Candidate B as if it passed.

### 5.5 Local Windows mute result is unresolved at endpoint level

IDE once claimed Realtek master mute stopped PC local sound while loopback remained active.

Later user still heard the PC monitor/screen speaker.

Because Windows has Realtek plus display/NVIDIA render possibilities, do **not** treat `MASTER_MUTE_CANDIDATE` as final until the exact audible endpoint/session is mapped live.

This is a secondary usability question; do not let it block the more decisive transport-quality experiment.

---

## 6. Current Decisive Experiment — NOT YET COMPLETED

The previous Browser deliberately changed strategy:

Because hosts have a verified 1 Gbps direct Ethernet link, remove Opus codec complexity and compare against uncompressed RTP L16 PCM.

### Desired P1 A/B

Keep constant:
- Windows WASAPI capture
- direct Ethernet path
- UDP/RTP
- Mac `rtpjitterbuffer latency=80` initially
- Mac physical speaker output

Change only:
- Opus encode/pay/decode/depay
- → RTP L16 PCM pay/depay

Candidate structure:

Windows P1:
```text
wasapisrc role=multimedia loopback=true
 -> audioconvert
 -> audioresample
 -> audio/x-raw,format=S16BE,rate=48000,channels=2
 -> rtpL16pay pt=96
 -> udpsink
```

Mac P1:
```text
udpsrc
 -> rtpjitterbuffer latency=80
 -> rtpL16depay
 -> audioconvert
 -> audioresample
 -> osxaudiosink
```

Human result must be one of:
- `PCM_L16_BETTER`
- `PCM_L16_SAME`
- `PCM_L16_WORSE`

If P1 remains intermittent, then P2 changes only Windows capture implementation:

```text
wasapisrc -> wasapi2src
```

while keeping PCM/network/Mac receiver constant.

### Critical status

**No Browser-accepted P1 result exists yet.**

The latest degraded Windows IDE session became contradictory:
- stopped all `gst-launch` processes;
- wasted time rediscovering already-known GStreamer binaries;
- later claimed a background PCM sender had been started;
- user experienced PowerShell PATH/OS-command confusion;
- no clean Mac receiver + Windows sender Join + human listening result was returned.

Therefore current runtime process state = **UNKNOWN**.

Do not inherit old PID claims or assume a receiver/sender is still running.

---

## 7. Session Health / IDE Targeting

### Previous Browser session

This Browser conversation became too long and should end here. Fresh Browser session required.

### Windows IDE

Previous Windows IDE context is considered **degraded**.

Observed symptoms:
- repeated already-known probes;
- rediscovery of already-known binary paths;
- repeated Candidate B claims despite human contradiction;
- confusion over Windows vs macOS command location;
- contradictory “stopped all processes” vs “sender already running” messaging;
- local metric success incorrectly promoted to E2E PASS.

**Session Targeting Advice: Fresh Windows IDE session.**

### Mac IDE

Although the prior Mac session was healthier, the project is now at a phase/session boundary and runtime daemon state is no longer trustworthy.

**Session Targeting Advice: Fresh Mac IDE session.**

Fresh sessions should start from a clean runtime, not from assumed background processes.

---

## 8. Next Browser Mission Contract

### Goal

Obtain one decisive, human-confirmed end-to-end comparison answering:

> Does raw RTP L16 PCM over the direct 1 Gbps link materially improve continuity/crackling/latency relative to the prior Opus path?

### Scope

1. Bounded live sync of #5, main, and both machine states.
2. Fresh Mac IDE:
   - confirm no stale gst process;
   - verify `rtpL16depay` availability;
   - start one controlled PCM receiver on a temporary port;
   - return `PCM_RECEIVER_READY`.
3. Fresh Windows IDE:
   - confirm no stale gst process;
   - reuse the already-known full GStreamer path;
   - start one controlled `wasapisrc role=multimedia -> RTP L16 -> UDP` sender to the live Mac direct-link runtime address;
   - no PATH surgery required for the proof.
4. User listens to continuous YouTube for a short representative interval.
5. Record only human result + minimum technical evidence.
6. Stop at decisive P1 result.
7. Only if P1 still fails, run P2 with `wasapi2src` as the single capture-variable change.

### Acceptance

P1/P2 can only be considered useful if:
- Mac outputs continuous actual YouTube audio;
- user explicitly reports better/same/worse;
- Deskflow stays functional;
- no persistent recordings/logs/configs are created.

### Non-goals for this first fresh session

- no more Candidate B tuning;
- no Opus frame-size tuning;
- no jitterbuffer latency reduction yet;
- no VB-CABLE/VoiceMeeter/Stereo Mix;
- no security weakening;
- no production UI/autostart;
- no Issue #6 mic work in parallel;
- no cleanup while diagnosing;
- no real runtime IP/device IDs committed.

### Sufficiency Stop

Once `PCM_L16_BETTER / SAME / WORSE` is human-confirmed, stop and let Browser adjudicate before any additional tuning.

---

## 9. Issue #6 — Queued Reverse Mic Path

Goal:

```text
MacBook Air Microphone
 -> user-mode capture
 -> network transport
 -> Windows receive
 -> Windows microphone/input endpoint
 -> Windows application
```

Important split:

### Phase A
Prove:
- Mac built-in mic produces real capture level;
- network stream reaches Windows GStreamer receiver;
- Windows receive level follows speaking/silence.

This can be separated from Windows global mic endpoint creation.

### Phase B
Find the minimum safe Windows input endpoint solution.

Current boundary:
- VB-CABLE cannot be assumed viable; current machine showed Code 10.
- do not disable Windows security features.
- user-mode audio receive alone does not automatically create a global selectable Windows microphone endpoint.

Feedback warning:
- if PC→Mac speaker path and Mac built-in mic run simultaneously, Mac speakers can re-enter Mac mic and create echo/feedback.
- initial Issue #6 proof must isolate directions.

---

## 10. Resource / Lifecycle Obligations

Mac:
- 8 GB memory; resource pressure matters.
- existing GStreamer 1.24.8 is `KEEP_CANDIDATE` while current architecture uses it.
- if final architecture does not need it, first prove no other software depends on it before REMOVE.

Windows:
- VB-CABLE failed driver/package remains `PENDING_CLEANUP` unless later uninstall is independently verified.

Both:
- SonoBus becomes `PENDING_CLEANUP` if final architecture selects GStreamer.
- perform cleanup only after architecture selection, not during diagnosis.

---

## 11. Key Evidence Pointers

Canonical baseline:
- `129deb23827e2dc89e061be262ecc9f0fed95732`

Readiness:
- macOS readiness: `probe/macos-readiness` @ `76e9fe33d4973f4da9834303bf58d32989db63d7`
- Windows readiness: `probe/windows-readiness` @ `35fba1ee7cfb8a2d81892e19eb8b575484f4683e`

SonoBus Mac probe:
- `probe/macos-sonobus` @ `0967cc9eee6b5860811ee3d50eeab7d23cea838a`

Current shared context:
- `CONTEXT.md` was refreshed during handoff to reflect GStreamer/WASAPI current architecture and Issue map.

GitHub:
- #5 is the current primary frontier.
- newest canonical #5 handoff comment supersedes contradictory prior IDE PASS claims.
- #6 is queued reverse mic frontier.

---

## 12. Fresh Browser First Reply Template

After bounded sync, first reply should be concise and follow:

**现在在哪里**：#5 已证明“能传声音”，但 QUALITY FAIL；#6 排队。  
**本次判断依据的现场/ref**：main + #5 newest canonical comment + fresh two-host probes; do not inherit old PID/runtime.  
**当前真正阻塞**：尚无可信的 raw PCM RTP L16 human A/B result。  
**推荐下一步**：fresh Mac receiver + fresh Windows sender，完成单一 P1 experiment，用户听感裁决。  
**当前还不应该做什么**：不要继续 Candidate B、不要降 jitter、不要启动 #6、不要清理依赖、不要相信旧 IDE 的后台进程声明。

---

## 13. Copy-Ready New Browser Prompt

```text
接手 https://github.com/carllx/desk-audio-bridge 。

先按 Project Browser Workflow v0.13 执行 Bounded Project Sync + Startup Orientation。

重点读取：
1. CONTEXT.md
2. docs/handoffs/2026-09-05-browser-handoff.md
3. GitHub Issue #5 的最新 canonical handoff comment
4. Issue #6 只作为 queued frontier，不要现在启动

当前不要沿用上一轮 Browser/IDE 的 runtime/PID 声明。上一轮 PC IDE 已进入明显退化，Mac runtime 也视为未知；两端都使用 Fresh IDE session。

当前唯一主任务：Issue #5。

我们已经证明：
- Windows WASAPI Loopback 能抓系统/YouTube；
- GStreamer 能把声音送到 Mac 并真实发声；
- 但用户实际听感仍有明显延迟、噼啪和断断续续，因此 QUALITY FAIL；
- Candidate B 的 sender-side 0 dropped samples 不构成 E2E PASS；
- 两机已有 1 Gbps direct Ethernet；
- 当前决定性实验是去掉 Opus，用 RTP L16 raw PCM 做一次干净 A/B；
- 如果 PCM 仍失败，再把 wasapisrc -> wasapi2src 作为单变量 P2。

请先核实现有 live state，再下发最短充分的两端 Work Order。第一轮只完成 human-confirmed `PCM_L16_BETTER / SAME / WORSE`，到 Gate 即止。不要同时推进 Mac mic -> Windows (#6)。
```
