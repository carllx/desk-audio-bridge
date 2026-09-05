# Dual-Machine Collaboration & Git Synchronization Rules

> 跨机协作与 Git 同步冲突防护规范（Dual-Machine Collaboration Layer）  
> 适用对象：Windows IDE Agent、macOS IDE Agent 及参与本仓库维护的开发者  
> 权威依据：GitHub Issue #9

---

## 1. 核心目标与协作拓扑

本项目涉及同一局域网下 Windows PC 与 Mac 双机协同开发。为防止两端 IDE Agent 并发修改共享文件、直接推 `main` 或基于过时基线工作导致冲突与覆盖，特制定本规范。

### 架构原则与拓扑约束
1. **单一权威远端 (Single Remote SSOT)**：项目唯一远端代码库为 `https://github.com/carllx/desk-audio-bridge`。
2. **两机独立工作区 (Independent Clones)**：Windows PC 与 Mac 各自拥有独立的本地 Git workspace clone，物理隔离，严禁将两台机器挂载或软链接到同一文件系统目录。
3. **禁止文件系统级双向同步工具**：严禁使用 Dropbox、OneDrive、iCloud、Google Drive、rsync、Syncthing 等双向文件/目录同步工具来替代 Git。所有跨机协作必须且仅通过 Git 进行。

---

## 2. 规范十大核心不变量 (Canonical Sync Model)

1. **唯一合并基线**：GitHub `origin/main` 是跨机器唯一合并基线。本地后台进程、未推送的分支、临时会话记忆或口头状态均不构成跨机 SSOT。
2. **独立 Clone 隔离**：两台机器均保留独立 Git clone，禁止共享同一文件系统工作区。
3. **独立 Feature Branch**：每个独立 Work Unit（Issue / Task）必须从最新 `origin/main` 检出独立 feature branch。
4. **开工标准同步协议**：任何开工前统一执行：
   ```bash
   git fetch origin
   git switch main
   git pull --ff-only origin main
   git switch -c <feature-branch-name>
   ```
5. **平台目录职责划分**：
   - Windows 专属实现优先且仅落在 `windows/**`；
   - macOS 专属实现优先且仅落在 `macos/**`。
6. **共享文件单 Owner 机制**：
   - 根目录文档（`CONTEXT.md`、`README.md`、`AGENTS.md`）及 `docs/**` 属于跨机共享状态；
   - **同一时刻只能由一个明确指定的机器/会话作为 Owner 进行写入**；
   - 另一端在此期间保持只读或等待其合并后再同步。
7. **严禁并发直推 main**：禁止 Windows IDE 与 Mac IDE 并发直接 push `main`。所有变更必须通过 Feature Branch + 明确推送的 commit SHA / PR 汇聚，再合并到 `main`。
8. **Merge 后强制对端重同步**：一个任务分支合并到 `main` 后，另一台机器在开展后续工作前必须重新执行 `git fetch origin` 与 `git pull --ff-only origin main`，严禁继续基于过时的 `main` 开发。
9. **Local-only State 保护**：若在操作前发现本地已有未提交修改或未推送分支，必须立即向用户报告 `Local-only state`，严禁执行破坏性 `git reset --hard`、`git clean` 或直接 `pull`/`rebase` 进行覆盖。
10. **运行时配置与隐私隔离**：IP、endpoint GUID、设备硬件指纹等 runtime-only 配置仅存放在被 `.gitignore` 忽略的本地配置文件（如 `*.local`），绝不通过 Git 在两机之间同步真实配置值（配置模板统一使用 `*.example`）。

---

## 3. 标准操作流 (Standard Operating Procedure)

### 3.1 任务开工前 (Pre-flight)
在进入任何新的 Work Unit / Issue 时，IDE Agent 必须按序检查：
```bash
# 1. 检查本地工作区是否干净
git status

# 2. 获取远端最新状态
git fetch origin

# 3. 切回 main 并快速向前合并
git switch main
git pull --ff-only origin main

# 4. 确认包含目标基线 commit
git log -n 5 --oneline

# 5. 创建独立 feature branch
git switch -c feature/<issue-number>-<description>
```

> [!CAUTION]
> 若 `git status` 显示本地有尚未提交或未处理的改动，**绝不能盲目覆盖**，必须先停下来核对该 `Local-only state` 是否需要保存、stash 或汇报用户。

### 3.2 共享文件修改协调 (Shared-File Ownership)
当任务需要修改 `CONTEXT.md`、`README.md`、`AGENTS.md` 或 `docs/**` 时：
1. 确认当前 Issue / Task 是否是该共享文档修改的指定单一负责端。
2. 若另一台机器正在进行包含共享文档修改的任务，本端应等待该任务合并，或仅进行平台专属目录（`windows/**` 或 `macos/**`）的代码工作。
3. 杜绝两端在各自独立分支中同时重构或大幅修改同一份共享文档。

### 3.3 任务完成与 Gate 汇报 (Completion Gate)
完成一个 Work Unit 后，Agent 必须执行以下交付步骤：
1. 将修改 commit 到独立 feature branch（遵循 Conventional Commits，如 `docs: ...`、`feat: ...`、`chore: ...`）。
2. push 到 GitHub 远端：
   ```bash
   git push -u origin <feature-branch-name>
   ```
3. 返回固定的已推送 commit SHA（Fixed pushed commit SHA）。
4. 清晰列出本次修改的文件列表、`git status` 及是否存在任何 `Local-only state`。
5. 经 PR / Review 合并入 `main` 后，通知或等待另一端拉取最新基线。

### 3.4 接收对端 Merge 结果 (Catch-up / Resync)
当另一台机器完成任务并合入 `main` 后，本机开工下一任务时：
```bash
git fetch origin
git switch main
git pull --ff-only origin main
```
确保两端随时处于可验证、单向演进的最新基线之上。
