# CONTEXT.md

> 项目领域上下文、统一领域语言与系统约束基线（Ubiquitous Language & Domain Context）

---

## 1. 领域使命与核心目标 (Mission & Vision)

**使命**：让同一桌面环境中的 Windows PC 使用 Mac 的内置扬声器和麦克风，形成低开销、低延迟、尽量无需人工切换的双机音频桥。  
**实现原则**：优先复用成熟、可审计、可逆的用户态能力；先做 Proof of Concept (PoC)，再决定是否需要额外硬件或更深层系统集成。  
**核心验收条件**：
1. **资源低开销**：低 CPU、低内存、低磁盘常驻占用。
2. **低延迟且稳定**：日常多媒体播放不能持续断音、爆音或产生明显不可接受延迟。
3. **零硬件追加优先**：PoC 阶段不购置额外外置声卡、USB 麦克风或音频物理转接线。
4. **人耳 Gate**：端到端“可用”不能只看 meter / logs；真实播放质量必须由用户听感确认。

---

## 2. 统一领域语言 (Ubiquitous Language)

* **Windows Host**：Windows 主机。可产生系统/应用播放音频，并存在 Realtek 与显示/显卡相关 render endpoints；当前没有可用物理麦克风。目标上既是 Windows Playback Source，也是未来 Windows Virtual Microphone Endpoint 的接入归宿。
* **Mac Host**：MacBook Air M1。具备内置扬声器与内置麦克风，作为 Mac Speaker Sink 与 Mac Microphone Source。
* **Windows Playback Source**：Windows 应用/系统产生、需要发送到 Mac 的播放音频，包括浏览器/YouTube 等普通应用音频。
* **Mac Speaker Sink**：消费 Windows 播放音频并由 MacBook Air Speakers 发声的一端。
* **Mac Microphone Source**：Mac 内置麦克风产生的音频。
* **Windows Virtual Microphone Endpoint**：接收来自 Mac 的麦克风音频，并在 Windows 中向普通应用暴露为可选择的麦克风输入设备。
* **Deskflow**：现有键鼠共享工具。两机已稳定通过它协作；本项目保持独立，不 fork、不侵入式修改。Deskflow 的现有直连网络也提供了双机连通性证据。
* **WASAPI Loopback**：Windows 用户态系统播放捕获机制。当前已实证可以抓取系统/浏览器播放音频，不依赖 Stereo Mix 或虚拟声卡。
* **GStreamer**：当前 Windows→Mac 用户态音频链路的主要实验框架。Windows 已验证 1.28.6；Mac 已有官方 Universal `GStreamer.framework` 1.24.8，暂定 `KEEP_CANDIDATE`。
* **SonoBus**：已完成兼容性实验，但不再是当前 Windows→Mac 主路线。若最终采用 GStreamer，应作为实验残留进入后续清理 Gate。
* **VB-CABLE**：Windows 上实验失败；官方 Pack45 在当前机器出现 PnP Code 10。除非出现新的明确兼容性证据，不再作为默认方案。
* **BlackHole**：macOS 虚拟音频驱动。当前 PoC 不需要，禁止提前引入。

---

## 3. 当前已知环境事实 (Known Environmental Facts)

| 维度 | Windows 端事实 | Mac 端事实 | 备注 |
| :--- | :--- | :--- | :--- |
| **播放能力** | 存在 Realtek 与显示/显卡相关 render endpoints；用户现场可听到 PC 屏幕/显示器侧播放 | MacBook Air Speakers 可用 | 不得再笼统描述为“Windows 无扬声器” |
| **麦克风** | 当前没有可用物理麦克风/默认录音 endpoint | MacBook Air 内置麦克风可用 | 反向链路见 Issue #6 |
| **GStreamer** | 官方 1.28.6 MSVC x86_64 已安装，可用 `wasapisrc` / RTP / UDP / Opus 等 | 官方 Universal 1.24.8 framework 已存在，约 461 MB，RTP/Opus/CoreAudio 插件齐全 | Mac 当前不需要升级 |
| **键鼠共享** | Deskflow 正常 | Deskflow 正常 | 独立于音频项目 |
| **网络拓扑** | 与 Mac 存在已验证的 1 Gbps 直连以太网路径 | 与 Windows 存在同一直连路径 | 音频 PoC 应优先复用直连路径；真实 IP 不入 Git |
| **安全边界** | HVCI/VBS/Secure Boot/Defender 保持开启 | 不绕过 Gatekeeper/系统安全 | 不为音频桥降低系统安全 |

---

## 4. 当前架构事实与决策边界

### 4.1 Windows → Mac Speaker Path

已达成的稳定基线：

`Windows app/system audio -> wasapi2src loopback -> GStreamer RTP L16/UDP -> network -> GStreamer on Mac -> MacBook Air Speakers`

当前状态与事实：
- **Issue #5 阶段性收口**：已通过当前 human listening gate，端到端听感连续、丝滑，无明显噼啪；
- **当前稳定候选**：`wasapi2src -> RTP L16/UDP -> Mac GStreamer -> MacBook Air Speakers`；
- **接口绑定约束**：在多网卡环境下，Mac receiver 需显式声明绑定直连接口地址（`address=<MAC_DIRECT_IP>`）；
- **日常可用性体验**：目前尚依赖手动终端命令，未封装为日常易用的 Start/Stop 体验，该部分工作独立解耦为后续 Integration Issue。

### 4.2 Mac → Windows Microphone Path

当前 active/primary frontier：**Issue #6**。

目标：

`MacBook Air Microphone -> user-mode capture -> network -> Windows receive -> Windows microphone/input endpoint -> Windows app`

重要边界与推进阶段：
- **当前事实**：Mac 内置麦克风尚不能在 Windows 普通语音输入（如会议软件、语音识别等）中使用；Windows 端普通应用尚无由 Mac mic 驱动的 selectable microphone endpoint；
- **分阶段推进**：
  - **Phase A**：优先在网络与数据流层面证明 `Mac mic -> network -> Windows receive level`（验证麦克风用户态采集与网络送达）；
  - **Phase B**：再解决 Windows 端 selectable microphone endpoint（向系统/普通应用暴露为可用录音设备）；
  - 严禁将两阶段混杂在一起，避免诊断断点模糊；
- 在 Issue #5 speaker path 稳定后，Issue #6 作为当前核心主战场推进。

---

## 5. GitHub Issue 语义

- **#1**：SonoBus on Mac compatibility/resource probe — completed。
- **#2**：Stereo Mix -> SonoBus — completed negative。
- **#3**：旧 SonoBus 双机集成 — `not_planned`，已被 #5 取代；不得作为当前架构依据。
- **#4**：VB-CABLE -> SonoBus — completed negative；Code 10，后续 pending cleanup。
- **#5**：WASAPI/GStreamer Windows -> Mac speaker path — **COMPLETED，已通过当前 human listening gate 达成基线收口**。
- **#6**：Mac mic -> Windows input — **OPEN，当前 primary frontier，分 Phase A/B 推进**。
- **#7（待创建）**：Integration：将双向音频桥收敛为日常可启动/停止的用户体验 — **QUEUED，在双向链路能力稳定后推进**。

当 IDE 输出与用户真实听感冲突时，以用户 Human Gate + Browser 复核后的 Issue canonical comment 为准，不接受 IDE 自报 PASS 自动升级为事实。

---

## 6. 双机协作规范 (Dual-Machine Collaboration Rules)

跨机器协作与 Git 同步冲突防护规则（详细规范与 SOP 详见 `docs/agents/dual-machine-collaboration.md`，权威依据 Issue #9）：

1. **统一远端仓库与唯一基线**：项目唯一远端 `https://github.com/carllx/desk-audio-bridge`，`origin/main` 为两机唯一合并基线。本地后台进程、未推送分支和口头状态不构成跨机 SSOT。
2. **独立本地工作区与禁止网盘同步**：两台物理机器各维护独立 clone，禁止共享同一文件系统工作区，严禁引入网盘/Dropbox/rsync 等双向目录同步替代 Git。
3. **独立 Feature Branch**：每个独立 Work Unit 从最新 `origin/main` 检出独立 feature branch，禁止在旧基线上直接开发。
4. **开工标准同步协议**：开工前统一执行 `git fetch origin` → `git switch main` → `git pull --ff-only origin main` → 创建/切换工作分支。
5. **平台专属目录职责**：`windows/**` 优先且仅归属 Windows 端；`macos/**` 优先且仅归属 macOS 端。
6. **共享文件单 Owner 机制**：`CONTEXT.md`、`README.md`、`docs/**`、`AGENTS.md` 属于共享文件，同一时刻只能有一个明确 owner 修改，另一端保持只读或等待 merge。
7. **禁止并发直推 main**：两端 IDE 严禁并发直接 push `main`。实现通过 feature branch + fixed pushed commit SHA / PR 汇聚后合并。
8. **Merge 后强制对端重同步**：任一任务 merge 入 `main` 后，另一端继续工作前必须重新 `fetch` + `pull --ff-only`，不得基于旧基线继续。
9. **Local-only State 保护**：若发现本地已有未提交/未推送修改，必须先报告 `Local-only state`，严禁直接 pull/rebase/reset 覆盖。
10. **运行时配置隔离**：IP、endpoint GUID、设备 ID 等 runtime-only 配置保存在 ignored local config，真实值不入 Git。
11. **Session 健康**：出现反复询问已知事实、重复旧结论、忽略 Human Gate、把局部 metric 当端到端 PASS 等退化信号时，在 Work Unit/阶段边界切 Fresh IDE session。

---

## 7. 本地配置与隐私安全守则 (Privacy & Local Configurations)

绝对禁止提交：
1. 真实内网/公网 IP（除非 example 占位符）；
2. 带用户名/机器名的本地绝对路径；
3. 音频 endpoint GUID / Instance ID / 设备硬件指纹；
4. 凭证、Token、API Key、Cookie；
5. cache、dump、pcap、大型日志；
6. 真实录音测试文件。

本地配置：
- 模板：`*.example`
- 实际主机配置：`*.local` / `*.local.*`，必须被 `.gitignore` 忽略。

---

## 8. Lifecycle Cleanup Obligations

架构选定后再统一清理，避免边测边删导致诊断漂移：
- Windows VB-CABLE failed driver/package：若仍存在，需清理；
- Windows/macOS SonoBus：若最终不用，需卸载并清理实验残留；
- macOS GStreamer.framework：当前 `KEEP_CANDIDATE`；若最终架构不再需要，必须先确认无其他软件依赖，再决定 REMOVE；
- 不得因本项目不用某共享 framework 就盲删系统/其他应用依赖。
