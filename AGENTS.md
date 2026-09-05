# AGENTS.md

> 仓库维护者规则层（Repository-Maintainer Layer）  
> 读者：IDE Agent 及参与本仓库维护的 Agent  
> 核心问题：IDE Agent 应如何协作与维护 `desk-audio-bridge` 仓库？

---

## 1. 仓库定位与双机协作体系 (Dual-Machine Collaboration)

本项目旨在实现同一局域网内 Windows PC 使用 Mac 的内置扬声器与麦克风。本项目涉及跨平台双机开发，其协作架构与维护边界如下（完整 SOP 详见 `docs/agents/dual-machine-collaboration.md`）：

### A. 存储与工作区架构
* **单一权威代码库**：项目唯一远端为 `https://github.com/carllx/desk-audio-bridge`，`origin/main` 为跨机唯一合并基线。
* **独立工作区与禁止网盘同步**：Windows PC 与 Mac 各自拥有独立的本地 Git workspace clone，禁止共享同一文件系统工作区，严禁引入网盘/Dropbox/rsync 等双向目录同步替代 Git。
* **开工标准流与分支隔离**：每个独立 Work Unit 从最新 `origin/main` 检出独立 feature branch。开工前统一执行：`fetch -> main -> pull --ff-only -> feature branch`。
* **禁止并发直推 main**：两台机器上的 IDE Agent **严禁**并发直接向 `main` 分支 push 代码。所有变更必须通过 feature branch + 固定 pushed commit SHA / PR 汇聚后合并。
* **对端 Merge 重同步**：任一分支 merge 入 `main` 后，另一台机器开工前必须重新 `fetch` + `pull --ff-only`，严禁基于过时基线工作。
* **Local-only State 保护**：若发现本地已有未提交或未推送修改，先向用户报告 `Local-only state`，严禁直接 pull/rebase/reset 覆盖。
* **跨机权威状态 (Canonical Cross-Machine State)**：GitHub Issue、PR、已推送 Commit 及 `docs/` 文档是跨机器唯一的权威状态（SSOT），绝不依赖 Agent 之间的口头转述或易失会话记忆。

### B. 目录边界划分与共享文件所有权
* **平台专属区域**：
  * `macos/**`：macOS 端专用逻辑、配置及脚本，由 Mac 侧会话主要负责。
  * `windows/**`：Windows 端专用逻辑、配置及脚本，由 Windows 侧会话主要负责。
* **共享区域与单一 Owner 机制**：
  * 根目录文档（`README.md`、`CONTEXT.md`、`AGENTS.md`）及 `docs/**` 属于两端共享状态。
  * **同一时间只能有一个明确指定的机器/会话作为 Owner 写入共享文件**；另一端保持只读或等待 merge，杜绝并发冲突。

---

## 2. 核心执行守则 (Maintainer Principles)

1. **零新增硬件与低开销契约**：
   - 优先通过成熟开源方案完成 PoC，禁止重复造轮子（如自行编写底层音频驱动）。
   - 核心验收基准为：低 CPU、低内存、低磁盘占用和人耳可接受的低延迟。
2. **外部依赖解耦边界**：
   - **Deskflow**：当前已用于键鼠共享，但保持完全独立，不是 v0.1 硬依赖；严禁 fork 或就地修改 Deskflow。
   - **SonoBus**：作为当前候选传输方案，本阶段严禁提前安装、配置、fork 或 vendor。
   - **BlackHole**：不是 v0.1 必需依赖，严禁提前引入。
3. **语言契约 (Language Contract)**：
   - GitHub Issue、PR 描述、计划、架构说明、反馈等人类可读材料**默认使用清晰简体中文**；
   - 代码、文件路径、终端命令、API、Git 标识符及技术术语保持英文。
4. **防止过度设计 (Avoid Overdesign)**：
   - 保持最小可用结构，严禁建立当前不需要的复杂抽象层或冗余工程脚手架。

---

## 3. 本地配置与隐私保护规则 (Privacy & Local State)

严禁向 Git 仓库提交以下内容：
* 本机局域网/公网 IP 地址等易变配置（示例请统一写入 `*.example` 模板）。
* 带有用户主目录的本机绝对路径。
* 具体音频硬件 ID / 设备 GUID。
* 密码、Token、Cookies 及各类凭据。
* 本地运行缓存、大型日志及原始性能采样文件（*.dump, *.pcap, *.perf 等）。
* 真实录音文件（*.wav, *.mp3 等）。

配置规范：
* 配置模板纳入版本控制：`*.example` 或模板文件。
* 真实本机配置文件统一忽略：`*.local` 或加入 `.gitignore`，绝不通过 Git 同步真实 runtime 配置值。

---

## Agent skills

### Issue tracker

GitHub issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical label mapping. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context. See `docs/agents/domain.md`.

### Dual-machine collaboration

Git synchronization and conflict prevention rules across Windows and macOS clones. See `docs/agents/dual-machine-collaboration.md`.
