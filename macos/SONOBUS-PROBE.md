# macOS 平台 SonoBus 探测报告 (SonoBus Probe)

> 关联 Issue: [#1 Probe：验证 SonoBus 在当前 Mac 上的兼容性与资源开销](https://github.com/carllx/desk-audio-bridge/issues/1)  
> 基线 Commit: `129deb23827e2dc89e061be262ecc9f0fed95732` (origin/main)  
> 探测时间：2026-09-05  
> 状态：PASS (无 Blocker，环境及资源达标)

---

## 1. 安装包与安全核实 (Security & Verification)

* **官方来源**: GitHub 官方发布源 `sonosaurus/sonobus`
* **精确版本**: `1.7.2` (Tag: `1.7.2`)
* **安装介质**: `sonobus-1.7.2-mac.dmg` (官方 Release Asset)
* **下载镜像大小**: 134 MiB (140,693,153 字节)
* **SHA-256 校验和**: `4ba6eff849973238f45e0a3538b90c9a2d64c0b001d62882d0d337f46e0ddaa9`
* **二进制架构 (Mach-O)**:
  * Universal Binary: `arm64` 与 `x86_64`
  * 原生运行于 Apple Silicon (`arm64`)，无需 Rosetta 转译
* **代码签名与 Gatekeeper**:
  * 开发者证书: `Developer ID Application: Sonosaurus LLC (XCS435894D)`
  * 苹果公证状态 (Notarization): `accepted (source=Notarized Developer ID)`，票据已装订 (stapled)
  * 结论: **安全策略完全合规**，无需降低系统安全等级或强行绕过 Gatekeeper。

---

## 2. 安装与磁盘占用 (Disk Footprint)

* **安装形态**: 仅部署独立应用程序 `/Applications/SonoBus.app`（未安装 DAW 插件包如 AU/VST/AAX，保持系统干净）
* **应用实际占用**: `/Applications/SonoBus.app` 为 **50 MiB**
* **运行缓存与持久化目录**:
  * `~/Library/Application Support/SonoBus`: 0 B（未创建冗余大文件）
  * `~/Library/Caches/com.Sonosaurus.SonoBus`: ~144 KiB
  * `~/Library/HTTPStorages/com.Sonosaurus.SonoBus`: ~56 KiB
* **无界持续写入检查**: 未检测到自动录音、未发现无界日志写入或异常膨胀的缓存文件。

---

## 3. 运行资源开销 (Resource Consumption)

测试场景：SonoBus 启动后处于就绪待命状态（未建立网络会话，未开启录音，未启用 Soundboard）。

### 进程级开销 (SonoBus Process)
* **CPU 使用率**:
  * 启动初始待机: ~0.0% - 0.5%
  * 音频面板就绪与周期性图形渲染: ~4.2% - 5.9%
  * 均值稳定在极低水平，无异常尖峰。
* **内存占用**:
  * RSS (物理常驻内存): **28 MiB - 43 MiB**
  * Top RPRVT (私有常驻内存): ~23 MiB - 67 MiB
  * %MEM: 约 0.3% - 0.5%

### 系统级影响 (System Impact)
* **可用磁盘空间**:
  * 启动前: 9.2 GiB
  * 运行与清理临时包后: 9.3 GiB（保持稳定）
* **Swap / 内存压力对比**:
  * Swap 使用量: 3038 MB -> 3237 MB（常规后台轻微波动，未出现异常暴增或系统卡顿）
  * 系统交互流畅，未观察到任何卡顿或异常挂起。

---

## 4. 音频设备识别 (Audio Device Readiness)

* **Mac Speaker Sink 探测**:
  * 默认输出设备识别为: `MacBook Air Speakers`（成功识别内置物理扬声器）
  * 活动输出通道 (Active Output Channels): 2 通道 (Stereo) 默认勾选激活
* **输入设备识别**:
  * 默认输入设备识别为: `MacBook Air Microphone`
* **音频参数**:
  * 默认采样率: 48000 Hz
  * 默认缓冲区大小: 512 samples
* **系统音频设置影响**: 未更改系统全局音频路由，未安装虚拟驱动。

---

## 5. 外部依赖解耦验证

* **Deskflow 状态**:
  * `deskflow-core server` 与 `Deskflow` 保持平稳运行（CPU ~2%，内存 ~15 MB）。
  * SonoBus 启动与测试期间，键盘与鼠标局域网共享未受任何干扰。

---

## 6. 验收结论 (Acceptance Decision)

* **最终判定**: **PASS**
* **判定依据**:
  1. 官方原生支持 Apple Silicon (`arm64`)；
  2. 官方签名及苹果公证完备，Gatekeeper 直接放行，无需任何安全降级；
  3. 磁盘占用极小（仅 50 MiB），无异常缓存/录音增长；
  4. 进程常驻内存仅 ~40 MiB，待机 CPU 开销极低；
  5. 准确识别物理音频输出设备 `MacBook Air Speakers`，具备作为 Mac Speaker Sink 的完全就绪条件；
  6. 对 Deskflow 键鼠共享零干扰。
* **Blocker**: 无。
