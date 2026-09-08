# 解码回归样本

`tone-24k-mono.mp3` 是为本测试生成的 997 Hz 正弦音，24 kHz 单声道、1 秒、48 kbps MP3。
不包含用户录音、语音内容或外部下载素材。编码帧包含填充，因此解码时长略长于 1 秒。

生成命令（本地 FFmpeg + libmp3lame）：

```sh
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i 'sine=frequency=997:sample_rate=24000:duration=1' \
  -ac 1 -c:a libmp3lame -b:a 48k -map_metadata -1 \
  -write_xing 0 -id3v2_version 0 tone-24k-mono.mp3
```

固定提交的二进制样本，避免编码器升级改变回归基线。
修复前使用 registry `minimp3 0.5.2` 解码该样本的 32 次拼接，得到：

- 1408 帧、811008 个 i16 采样。
- aarch64 macOS、S16LE 字节 SHA-256：
  `7332e81ec31e2ca5eb96ea8e3e28bf3e24f622b48994f3c4fcb23824838751f1`。
