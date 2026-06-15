# micnorm —— 追问录音电平归一化（保分辨率）

追问录音送小米云端 ASR 前的预处理小工具（armhf 静态，~42KB，无模型）。

## 解决什么问题

`Capture` 设备原生是 **S32/48kHz**。你**安静说话**时信号在 S32 里数值很小，但保有 ~23bit 分辨率。
若像以前那样直接 `arecord -f S16_LE` 采集，ALSA 把 S32 转 S16 时取高 16 位，安静语音被砍到
**~8bit**，量化太粗 → 云端 ASR 返回空（实测：同一句安静的话，S16 直采识别为空，S32+归一化后识别正确）。

`micnorm` 读 **S32_LE/mono WAV**，在 float 域**峰值归一化**（既抬电平又保住分辨率）后输出
**S16_LE/mono WAV**（同采样率）。`vad_record.sh` 的 window 模式检测到 `/data/micnorm` 即自动启用
「S32 采集 → micnorm 归一化」链路。

> 注：噪声/波束/AGC 都试过、对本机低 SNR 裸麦无效（详见 docs/concepts/native-first.md 追问一节）。
> 真正的杠杆是**采集分辨率**，故本工具只做"保分辨率 + 归一化"，不做降噪。
> 内置一个可选分块 AGC（`max_boost>1` 启用），但默认关（低 SNR 下抬轻声=连噪声一起抬，无净收益）。

## 用法

```
micnorm in_s32.wav out_s16.wav [target_peak=18000] [min_peak_s32=1200000] [max_boost=1]
# 退出码: 0 成功; 124 信号过弱(无有效语音); 1 错误
```

## 构建 / 部署

```sh
bash build.sh                                   # 交叉编译 → dist/micnorm（dist/ 不入库）
scp -O dist/micnorm root@<speaker>:/data/micnorm
```

依赖：`brew install zig`（同 ettsc 工具链）。
