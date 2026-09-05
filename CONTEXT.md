# CONTEXT.md

> 项目领域上下文、统一领域语言与系统约束基线（Ubiquitous Language & Domain Context）

---

## 1. 领域使命与核心目标 (Mission & Vision)

**使命**：让同一局域网中的 Windows PC 使用 Mac 的内置扬声器和麦克风。  
**实现路径**：首选利用现有开源成熟软件，在**零新增硬件**的前提下建立双向音频流转发 Proof of Concept (PoC)。  
**核心验收条件**：
1. **资源低开销**：低 CPU 占用、低内存占用、低磁盘空间占用。
2. **低延迟**：满足日常语音通话与系统多媒体播放的可接受延迟要求。
3. **零硬件追加**：不购置额外外置声卡、USB 麦克风或音频物理转接线。

---

## 2. 统一领域语言 (Ubiquitous Language)

* **Windows Host**：局域网内的 Windows 操作系统主机。当前无物理扬声器、耳机及麦克风，作为系统音频输出的发送端（Audio Sink Client）与麦克风输入的接收端（Audio Source Client）。
* **Mac Host**：局域网内的 macOS 操作系统主机。配备高品质内置扬声器与内置麦克风，作为扬声器播放端与麦克风采集端。
* **Deskflow**：基于局域网的开源键鼠共享工具，当前已在两台主机间平稳运行。在本项目中保持完全独立，不是 v0.1 的硬性依赖，严禁对其进行 fork 或侵入式修改。
* **Audio Routing / Loopback (音频路由与环回)**：在操作系统层面将应用程序的音频流重定向至网络传输桥，或将接收到的网络音频流重定向至虚拟/物理录音与播放设备。
* **SonoBus**：当前候选的端到端轻量开源 P2P 音频流传输软件。本阶段仅作为技术选型备选池成员，本轮不进行安装、配置、fork 或 vendor。
* **BlackHole**：macOS 下的虚拟音频驱动。当前评估其并非 v0.1 最小 PoC 必需项，严禁提前引入造成环境污染。

---

## 3. 当前已知环境事实 (Known Environmental Facts)

| 维度 | Windows 端事实 | Mac 端事实 | 备注 |
| :--- | :--- | :--- | :--- |
| **物理音频外设** | 无独立扬声器、无耳机、无物理麦克风 | 具备内置扬声器、内置麦克风 | 硬件资源单向不对称 |
| **键鼠共享状态** | 已通过 Deskflow 与 Mac 建立连接 | 已通过 Deskflow 与 Windows 建立连接 | Deskflow 独立运行，不作修改 |
| **网络拓扑** | 同一局域网内 (LAN) | 同一局域网内 (LAN) | 具备高速低延迟直连条件 |
| **权限与驱动** | 具备管理员权限 | 具备用户及 sudo 权限 | 遵循最小特权原则，避免安装未经评估的内核扩展 |

---

## 4. 双机协作规范 (Dual-Machine Collaboration Rules)

由于项目跨越两台不同系统的物理机器，并由两个独立运行的 IDE Agent 协同开发，必须严格遵循以下协作准则：

1. **统一远端仓库**：
   - 唯一的 Git 仓库权威地址为 `https://github.com/carllx/desk-audio-bridge`。
   - 默认分支为 `main`。
2. **独立本地工作区**：
   - 两台物理机器各维护一份本地独立的 Git 仓库 clone。
3. **禁止并发直推 main**：
   - 两台机器上的 IDE Agent 绝对禁止同时向 `main` 分支执行未经验证的直接 push。
   - 所有实质功能开发应基于独立的 Feature Branch 与 GitHub Issue 进行。
4. **目录与职责边界隔离**：
   - `macos/**`：macOS 平台专属工作区。
   - `windows/**`：Windows 平台专属工作区。
   - `docs/**`、`README.md`、`CONTEXT.md`、`AGENTS.md`：属于两端共享状态，任何一方修改需确保对齐，严禁未协调的并发覆写。
5. **跨机权威状态真理来源 (Canonical State)**：
   - GitHub Issue / PR、已推送到远端的 Commit 以及仓库内的权威文档（`docs/`）是唯一的跨机有效状态。
   - 严禁依赖不同 Agent 之间的口头转述或易失性会话假定。最终成果必须以远端落地的代码与文档为准。

---

## 5. 本地配置与隐私安全守则 (Privacy & Local Configurations)

为防止仓库膨胀以及泄漏个人敏感信息，严格执行以下约束：

* **绝对禁止提交的内容**：
  1. 真实内网/公网 IP 地址（除非在 `*.example` 中标记为 `192.168.1.xxx` 占位符）。
  2. 带有具体用户名或机器名的本地绝对路径（如 `C:\Users\<username>\...` 或 `/Users/<username>/...`）。
  3. 系统具体音频设备 GUID、硬件序列号或设备硬件指纹。
  4. 任何敏感凭证、Token、API Key、Cookie 等。
  5. 本地运行时产生的缓存、编译产物、原始内存转储文件（*.dump）、网络抓包（*.pcap）以及大型日志。
  6. 真实录音测试文件（*.wav, *.mp3, *.flac 等），严禁造成 Git 历史膨胀。
* **本地配置文件命名契约**：
  - 需纳入 Git 跟踪的配置模板：统一命名为 `*.example`（如 `config.json.example`）。
  - 各主机本地实际使用的配置文件：统一命名为 `*.local` 或 `*.local.*`，并在 `.gitignore` 中默认被完全忽略。
