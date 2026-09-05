# 双机音频传输基准排查与端到端链路验证报告

- **日期**：2026-09-05
- **参与方**：Windows Agent、Mac 会话、人类维护者
- **验收结论**：`NETWORK_RTP_BASELINE_PASS` & `WASAPI2SRC_BASELINE_PASS`

---

## 一、 背景与疑点重置

在前期实验中，曾出现以下相互矛盾的现象：
1. **Mac 接收端长久无声**：此前推断可能是采集源异常或 GStreamer 管道未就绪。
2. **直连地址疑点**：Windows 发送端目标地址曾被怀疑是否存在拼写笔误。
3. **Windows 喇叭异常声**：在某些测试管道下，Windows 本机喇叭监听曾观察到杂音。

**决策**：暂停关于“采集端某特定实现已完全解决所有音频瑕疵”的推断，重置基准，将问题划分为 **本地音频状态**、**物理链路与路由**、**UDP 数据包可达性**、**RTP 解包层**、**音频渲染层** 逐层剥离断点。

---

## 二、 逐层排查过程与关键证据链

### 阶段 0：Windows 本地音频与进程清理 (Clean Audio State)
- **动作**：终止所有残留的 GStreamer 进程，确保 `GST_PROCESS_COUNT = 0`。
- **验证（PHASE 0B）**：在无任何 GStreamer 管道挂载 loopback 的情况下播放测试音频，确认 Windows 本机喇叭播放正常。
- **推论**：此前观察到的异常杂音与残留 GStreamer pipeline 强相关；清除所有后台 gst 进程后，原生播放恢复正常。不超出实验能够证明的因果范围。

### 阶段 1：物理拓扑与直连网络验证
- **探测结果**：
  - Windows 有线以太网网卡配置直连网段 IP。
  - ARP 缓存与连通性测试表明直连链路通畅，RTT 处于 0~1 ms 级别，丢包率 0%。
- **结论**：直连以太网配置为物理直连路径，可作为低延迟音频传输的首选介质。

### 阶段 2A：数据包交付证明 (Packet-Level Proof)
- **方法**：绕过真实音频采集，Windows 仅使用纯数学测试音源 `audiotestsrc wave=sine freq=440` 打包 RTP 发送至直连链路目标端口。
- **Mac 内核抓包**：
  ```bash
  sudo tcpdump -n udp port <AUDIO_PORT>
  ```
- **证据记录**：持续捕获满带宽 UDP 报文，内核层未出现丢包。
- **推论**：直连物理传输与底层 UDP 报文交付成立，无底层网络或防火墙阻断。

### 阶段 2B：接收端接口绑定验证 (Interface Binding)
- **现象**：当 Mac 端未显式指定接收地址启动 GStreamer 接收时，管道出现超时，未接收到报文。
- **排查与修正**：在当前多网卡环境下，未显式绑定直连接口时 GStreamer receiver 未收到流；改在 Mac `udpsrc` 中显式指定直连接口地址 `address=<MAC_DIRECT_IP>` 后立即恢复。
- **验证结果**：`level` 插件稳定输出非静音数据，持续几十秒无丢包或超时。达成 **`RTP_L16_DEPAY_PASS`**。
- **说明**：此处记录多网卡环境下显式绑定与接收恢复的事实，不将未直接证明的内部 socket 路由选择机制断定为唯一因果。

### 阶段 2C：Mac 扬声器纯音基准 (Audio Baseline Pass)
- **测试**：将接收端 sink 接通至 `osxaudiosink`。
- **听觉反馈**：Mac 内置扬声器播放出连续、稳定的 440Hz 正弦纯音，无明显卡顿与断续。达成 **`NETWORK_RTP_BASELINE_PASS`**。

### 阶段 3：wasapi2src 系统音频验证
- **测试**：Windows 停止测试音源，启用 `wasapi2src loopback=true low-latency=true` 并辅以平滑缓冲队列，采集 Windows 系统播放音频并推流至 Mac。
- **最终验收**：Mac 扬声器稳定输出 Windows 播放音频，听感连续清晰，无明显噼啪声。当前 Windows → Mac speaker path 达到本轮基准线。

---

## 三、 规范化运行命令（模板化参考）

### Windows 端发送命令：
```powershell
& "<GSTREAMER_BIN>\gst-launch-1.0.exe" -v `
  wasapi2src loopback=true low-latency=true `
  ! queue max-size-buffers=0 max-size-time=2000000000 max-size-bytes=0 `
  ! audioconvert `
  ! audioresample `
  ! "audio/x-raw,format=S16BE,rate=48000,channels=2" `
  ! rtpL16pay pt=96 `
  ! udpsink host=<MAC_DIRECT_IP> port=5004 sync=false
```

### Mac 端接收命令（多网卡环境下需显式声明直连 IP）：
```bash
gst-launch-1.0 -m \
  udpsrc address=<MAC_DIRECT_IP> port=5004 \
  caps="application/x-rtp,media=(string)audio,encoding-name=(string)L16,clock-rate=(int)48000,encoding-params=(string)2,channels=(int)2,payload=(int)96" \
  ! rtpjitterbuffer latency=80 \
  ! rtpL16depay \
  ! audioconvert \
  ! audioresample \
  ! osxaudiosink
```
