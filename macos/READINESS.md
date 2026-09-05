# macOS 平台就绪状态探测报告 (Readiness Probe)

> 基于 Baseline Commit: `129deb23827e2dc89e061be262ecc9f0fed95732`  
> 探测时间：2026-09-05  
> 状态：纯只读事实探测已完成，未修改系统状态与驱动配置

---

## 1. 硬件与操作系统环境

* **操作系统**: macOS 26.5.2 (Build `25F84`)
* **机型型号**: `MacBookAir10,1`
* **CPU 架构**: Apple Silicon (`Apple M1`, `arm64`)
* **物理内存**: 8 GB 统一内存

---

## 2. 物理音频设备状态

* **系统默认输出设备 (Default Output Device)**:
  * 设备名称: `MacBook Air Speakers`
  * 传输类型: `Built-in`（内置扬声器）
  * 通道与采样率: 2 通道，48000 Hz
* **系统默认输入设备 (Default Input Device)**:
  * 设备名称: `MacBook Air Microphone`
  * 传输类型: `Built-in`（内置麦克风）
  * 通道与采样率: 1 通道，48000 Hz
* **物理设备存在性确认**: 内置扬声器与内置麦克风均在线且处于系统默认工作状态。

---

## 3. 虚拟音频设备检测

* **已检测到的虚拟音频设备**:
  * `NDI Audio` (NewTek / Apple Inc.)
  * `DTAudioPlugin` (DingTalk Ltd)
  * `OrayVirtualAudioDevice` (Shanghai best oray information s&t co.,ltd)
  * `ZoomAudioDevice` (zoom.us)
* **目标候选虚拟设备状态**:
  * **BlackHole**: **未安装**（HAL 驱动插件目录及系统中均未发现）
  * **Loopback**: **未安装**
  * **Soundflower**: **未安装**

---

## 4. 相关软件状态

* **SonoBus**:
  * 安装状态: **未安装**（无应用包，Homebrew 未安装）
  * 运行状态: **未运行**
* **BlackHole**:
  * 安装状态: **未安装**
  * 驱动状态: **未加载**
* **Deskflow**:
  * 安装状态: **已安装**（`/Applications/Deskflow.app`，Homebrew `deskflow`）
  * 运行状态: **正在运行**
  * 角色: Mac 正在作为 Deskflow Server 提供键鼠共享服务（保持独立运行，未作任何修改）

---

## 5. 资源基线 (空闲无音频桥工作负载)

* **CPU 使用概况**:
  * User: ~27% - 36%
  * System: ~33% - 35%
  * Idle: ~29% - 39%
* **内存概况 (总计 8 GB)**:
  * 已使用: ~7.4 GB（含 Wired ~1.9 GB，Compressor ~2.8 GB）
  * 空闲/未分配: ~120 MB - 190 MB（macOS 统一内存动态缓存管理）
* **磁盘空间 (`/System/Volumes/Data`)**:
  * 容量: 228 GiB
  * 已用: 183 GiB
  * 可用: ~20 GiB (约 9% 可用空间)

---

## 6. 局域网就绪度 (LAN Readiness)

* **活动接口**: `en0` (Wi-Fi)，默认路由正常指向本地网关。
* **双机连通性验证**:
  * Deskflow 对应通信端口已建立稳定连接（`ESTABLISHED`）。
  * 证实 Mac 与 Windows 当前处于同一可用局域网环境，具备双向低延迟数据传输链路。
* *(注：根据隐私保护规则，真实局域网 IP 与物理 MAC 地址已脱敏屏蔽)*。

---

## 7. 非阻塞考量项 (Non-blocking Considerations)

1. **内存与磁盘边界**:
   * 本机为 8GB 内存且日常使用中系统内存压缩率较高，可用磁盘约为 20 GiB。
   * 后续音频传输服务必须遵循轻量设计，避免过大内存占用导致频繁磁盘交换 (Swap)。
2. **声学回声抑制 (AEC)**:
   * 采用一体机内置麦克风与内置扬声器，后续在双向全双工工作（Windows 发声 + Mac 拾音）时需关注声学回声消除与防啸叫处理。
