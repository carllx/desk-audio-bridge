# desk-audio-bridge

> 让同一局域网中的 Windows PC 使用 Mac 的扬声器和麦克风。

## 项目使命 (Mission)

在不添加任何新硬件的前提下，利用现有成熟开源软件与系统音频接口，实现同一局域网中 Windows PC 与 Mac 之间的双向音频桥接（Windows 音频输出至 Mac 扬声器播放；Mac 内置麦克风采集音频输入至 Windows）。

核心目标是实现轻量、稳定的 Proof of Concept (PoC)，将**低 CPU、低内存、低磁盘占用**和**可接受的低延迟**作为核心验收条件。

---

## 环境现状与基线 (Environmental Baseline)

* **Windows PC**：当前不依赖物理独立扬声器、耳机或麦克风。
* **Mac**：配备内置扬声器与内置麦克风。
* **网络环境**：两台机器处于同一局域网（LAN）。
* **外设共享现状**：两台机器已通过 [Deskflow](https://github.com/deskflow/deskflow) 共享键盘与鼠标。
  * *注：Deskflow 与本项目保持独立，并非 v0.1 硬性依赖，禁止 fork 或侵入式修改 Deskflow。*

---

## 核心设计与验收原则 (Design & Acceptance Principles)

1. **零新增硬件 (Zero New Hardware)**：仅通过软件和网络协议达成。
2. **轻量低开销 (Minimal Overhead)**：
   - 低 CPU / 内存占用，保障后台无感运行；
   - 杜绝大型无界日志与运行缓存膨胀；
   - 网络传输与编解码延迟控制在日常音视频与通话可接受范围内。
3. **避免过度设计与重复造轮子**：
   - 充分复用开源生态；
   - 禁止自行研发复杂底层驱动；
   - 依赖评估按阶段严格准入（例如当前阶段不预先引入 BlackHole 或 SonoBus，先做轻量化验证）。

---

## 项目骨架 (Directory Layout)

```text
desk-audio-bridge/
├── .gitignore            # 忽略录音、缓存、日志及本地敏感配置
├── AGENTS.md             # 维护者守则、双机协作规范及 Agent Skills 设定
├── CONTEXT.md            # 项目领域上下文、统一术语与权威基线
├── README.md             # 项目概览与使能目标
├── docs/                 # 共享设计文档、ADR 与协作契约
│   ├── adr/              # 架构决策记录 (Architecture Decision Records)
│   └── agents/           # Agent 工具链与 Issue Tracker 配置
├── macos/                # macOS 专属脚本与配置空间
└── windows/              # Windows 专属脚本与配置空间
```

---

## 双机协作守则 (Dual-Machine Collaboration)

* **权威代码库**：`carllx/desk-audio-bridge`，以 GitHub `origin/main` 为唯一合并基线。
* **分工协作**：两台机器各自建立独立本地 workspace，严禁两端 IDE 并发直推 `main` 分支。
* **分支与同步**：以独立 Feature Branch 和 GitHub PR 为汇聚机制，共享文件需指定单 Owner。
* **详细规范**：详见权威协作规范文档 [docs/agents/dual-machine-collaboration.md](docs/agents/dual-machine-collaboration.md)。
