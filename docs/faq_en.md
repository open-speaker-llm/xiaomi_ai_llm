# FAQ

[简体中文](faq.md) · [Project README](../README_en.md)

Each answer was checked against the current code and docs. If the repo does not state it, it is not added here.

**Bilibili video series**

- Episode 1: [小爱答不上来的问题，自动转给 DeepSeek：老音箱直连大模型，家电照常控制](https://www.bilibili.com/video/BV1ShjG6tEVz/)
- Episode 2: [「小爱同学，呼叫 DeepSeek！」老款小爱直连大模型，原理一次讲清](https://www.bilibili.com/video/BV1Vzja69ELB/)
- Episode 3: [让小爱联网搜最新新闻，播到一半喊"开灯"，灯亮了、新闻没停](https://www.bilibili.com/video/BV1bu4u6GEEL/) (1:40)
- Episode 4: [小爱现在是不是大模型在回答？这次听声音就知道](https://www.bilibili.com/video/BV16W4E6XEtv/) (3:57, Published 2026-11-07)

<a id="models"></a>

## Which speaker models are supported?

Only one has been tested: the **Xiaomi AI Speaker, product model MDZ-25-DA**. The system hostname and internal codename are **S12A**. The SoC is an Amlogic A113X. The PCB silkscreen reads `DKSND-S12C-ECHO-AB-20180820`, which is not the same string as the product model or the hostname. The docs list all three as measured, and do not collapse them into one name.

No other model has been tested. A similar case does not mean the firmware or the connector is the same. The commands are not portable.

<a id="hardware"></a>

## Do I have to solder or flash the speaker?

No soldering. Open the back cover with a Phillips screwdriver. The board already has a JST UART socket. The cable used in the docs is an **SH1.0 to 2.54 mm Dupont 3-pin** lead. The USB-TTL example is a CH340. Three wires: adapter TX to speaker RX, adapter RX to speaker TX, GND to GND. **115200 8N1**. Do not connect the adapter's 5V or 3.3V pin to the board, and do not trust wire color for TX, RX, and GND. Check the pins with a meter first.

This is not a flash that replaces the system and takes over the microphone and playback. XiaoAI's own recognition and device control stay in place. If SSH is not already available, a startup script has to be written into the system partition so dropbear starts. The boot0 and boot1 runbooks both modify the matching rootfs; the boot1 runbook records an `mtd` write of `system1`. A bad partition write can leave the device unable to boot. UART stays the recovery path after SSH works. If SSH already works, the docs say not to rewrite the partition just to follow the steps again.

The commands live in those pages, not here: [hardware](reference/hardware.md), [bring-up](getting-started/bringup.md), [boot0 SSH](runbooks/boot0-ssh.md), [boot1 SSH](runbooks/boot1-ssh.md).

<a id="offline"></a>

## Does the speaker run the LLM? Does it work offline?

No. An LLM conversation does not work offline.

The speaker runs the client: it routes each turn and plays audio. Speech recognition, device control, and XiaoAI's own answers stay on Xiaomi's cloud, as before. The LLM is the cloud API you configure. By default the speaker calls it. With `LLM_PIPELINE=server`, a service you run calls it instead. EdgeTTS is Microsoft's online speech synthesis, called by the speaker or by the TTS service. If it fails, playback can fall back to native XiaoAI TTS.

The docs say that without a network, only native XiaoAI remains. Optional boot1 Silero VAD runs on the speaker and only decides whether speech has stopped. The words still come from Xiaomi's cloud. That component is not an LLM.

<a id="always-on"></a>

## Does a computer or NAS have to stay on?

You need a computer to deploy, copy files, and change configuration. You do not necessarily need one for everyday conversation.

Conversation does not depend on an always-on computer or NAS when all of these are true:

- `LLM_PIPELINE=native` (this is the client default when the variable is unset)
- `TTS_ENGINE=device` (on-speaker `ettsc` calls EdgeTTS directly)
- follow-up uses boot1's native recognition, not audio sent to a computer

Model calls and speech synthesis then leave from the speaker. Recognition still uses Xiaomi's cloud.

In [`device/native_first.env.example`](../device/native_first.env.example), `TTS_ENGINE` is `server`. If the variable is unset, the client also falls back to `server`. The example address is `http://192.168.8.150:8080`. Leave that default in place and the TTS service has to be up while the speaker answers. With `LLM_PIPELINE=server`, the optional FastAPI service has to keep running and it calls the model and synthesizes speech. An older boot1 follow-up path sends audio to a Mac for recognition; that path also needs the computer on.

The status page says: with on-device TTS and native follow-up, a Mac does not have to stay running.

<a id="native"></a>

## Do lights, weather, and the other native features still work?

Yes. That is the main path, called native-first. Lights, weather, time, and volume, when XiaoAI already handles them, still go to XiaoAI. boot0 looks at domain, action, and failure text in the native result. boot1 first checks whether the utterance names the LLM. The default patterns are `DEEPSEEK`, `DeepSeek`, and `deepseek`. Otherwise it waits for XiaoAI's failure prompt and only then sends the turn to the LLM.

boot1 uses text rules. The docs say an unseen failure sentence can be missed, and a similar normal answer can be misread. Not every utterance is guaranteed to route correctly.

During LLM playback you can wake XiaoAI again for device control, and playback continues. That is the behavior described in the docs and the demo. Stopping the LLM answer by voice while it is playing is not implemented.

<a id="llm"></a>

## Which LLMs are supported, how do I switch, and is there web search?

On the direct-from-speaker path, set `BACKEND` in `/data/native_first.env` on the device and restart the client when it is idle. Defaults in the current script:

| `BACKEND` | Default model when not overridden |
|---|---|
| `deepseek` (also the default if unset) | `deepseek-flash` |
| `glm` | `glm-5.3-flash` |
| `kimi` | `kimi-k2.6` |
| `minimax` | `MiniMax-M2.7` |

If `LLM_API_BASE`, `LLM_MODEL`, or `LLM_API_KEY` is set, it overrides that table. Changing only `BACKEND` while an old override remains sends the request to the old endpoint or model. Saying "call Kimi" to the speaker does not switch backends. The default direct-to-LLM patterns are the three DeepSeek spellings above; change `DIRECT_LLM_QUERY_PATTERNS` to adjust them.

The English README says local models (Ollama is the example) have not been tested. Any other OpenAI-compatible endpoint can be filled into the three overrides. That does not mean it has been tried on this speaker.

The optional computer service's [`config.yaml`](../config.yaml) also lists Claude and OpenAI. Those apply only when `LLM_PIPELINE=server`. The on-speaker path does not use them.

Web search exists only when the speaker calls the model itself and `BACKEND=deepseek`. The default `LLM_WEB_SEARCH=auto` first decides whether the question needs live information (news, prices, opening status, a given page, and similar). If it does, the speaker calls DeepSeek's official Search or Fetch API and the answer names its sources. Other backends do not have this, and neither does the `server` pipeline. `off` disables both the decision and the search. On failure, an empty result, or an invalid decision, the client says exactly “暂时无法联网查询，请稍后再试。” and does not continue with an unchecked live answer. Each LLM turn adds one decision request. See [web search](reference/native-web-search.md).

<a id="audio-feedback"></a>

## How do I know the LLM is answering, and when it has finished?

Green status feedback already existed. [PR #17](https://github.com/open-speaker-llm/xiaomi_ai_llm/pull/17), merged on 2026-11-06, adds audio cues: with on-device streaming, “dong-dong” and the green takeover light signal routing to the LLM. Web search first says “搜索中，请稍等。” (Searching, please wait). The green light rotates when the first filler or answer audio starts playing.

A single “dong” after the complete answer signals that the turn has finished. With the boot1 real-time follow-up component installed and enabled, listening resumes after the end cue, with a steady green light; you can continue without the wake word. Do not rely on an end cue after playback failure or a new wake interrupting the turn. Firmware-managed `native_multirounds` skips the end cue.

See [configuration](reference/configuration.md) for supported paths and controls: `LLM_ROUTE_BEEP` for the route cue, `LLM_END_BEEP` for the end cue, and `LLM_WEB_FILLER` for the search filler (empty disables it). Suppression of the native “欸” follow-up prompt is separate from the new “dong-dong” cue.

<a id="followup"></a>

## Can I ask follow-ups without the wake word, and how does that end?

Yes, but copying the example config is not enough. The matching component has to be installed and enabled. On boot1, after an LLM answer finishes playing, the speaker can listen again without another “小爱同学”, in the same context. The words still come from Xiaomi's cloud. A steady green light means it is ready for the next utterance. Native VAD decides when speech has stopped. After the end cue, real-time follow-up uses `FOLLOWUP_TIMEOUT` (8 seconds by default) as the listening turn’s timeout limit. Native VAD or a session-end event may stop listening earlier; it is not a guaranteed full 8-second wait. Without the end-cue path, `NATIVE_ASR_LISTEN_TIMEOUT` (20 seconds by default) is the whole-turn safety timeout. Staying quiet ends the session.

boot0 follow-up is a different path: record on the device, then Xiaomi file recognition. The status page lists it as experimental. The boot1 native follow-up component does not transfer onto boot0.

Spoken exit phrases are off by default. In [`device/native_first_client.sh`](../device/native_first_client.sh), anything other than `FOLLOWUP_EXIT_ENABLED=1` returns immediately. The example config is `0`. After you set it to `1` and restart the client while idle, the session ends only if a follow-up window is already open and the utterance is exactly one of these five:

**结束对话, 退出对话, 停止对话, 不聊了, 退下**

Leading and trailing space is allowed, and so is trailing `。！？.!?`. The same words in the first question are not intercepted. “不要结束对话”, “请结束对话”, and “不要再讲了” are not in the list. The status page says real listening checks for this switch are not finished.

Saying “小爱同学” again during follow-up hands the turn back to XiaoAI. Details: [exit phrases](reference/configuration.md#用结束语退出追问).

<a id="compare"></a>

## How is this different from mi-gpt and open-xiaoai?

The README names [mi-gpt](https://github.com/idootop/mi-gpt) and [open-xiaoai](https://github.com/idootop/open-xiaoai) as projects this repo learned from, and says both repositories are archived and no longer maintained. [comparison.md](concepts/comparison.md) classifies where each approach attaches. Its notes were collected in 2026-06. It is not a current feature or maintenance review. Check those repositories for their present state.

mi-gpt uses Xiaomi account interfaces, and the program runs on a computer or NAS. This project does not poll an account. The client runs on the speaker, which means opening the case for UART, and only MDZ-25-DA has been tested.

In this repo's description, open-xiaoai flashes the speaker and takes over audio. The models named there include LX06 / OH2P. This project leaves XiaoAI recognition and device control on the original path and sends only open questions to the LLM. It does not support LX06 / OH2P. The README says the `/data/init.sh` autostart approach comes from open-xiaoai.

Both can use an OpenAI-compatible API. The difference recorded here is where the software attaches.

<a id="cost"></a>

## What does it cost?

The LLM API is billed by the provider you choose. This repo does not list prices. DeepSeek web search uses the same `DEEPSEEK_API_KEY`. The docs say the decision request and successful Search/Fetch calls are billed separately. Prices are whatever DeepSeek publishes.

The README marks EdgeTTS as free. The on-speaker EdgeTTS client has no separate EdgeTTS API-key setting. XiaoAI recognition and device control still use the speaker's existing Xiaomi services. This repo does not charge a fee.

<a id="license"></a>

## What are the risks, and what license is this?

Code written in this repository is [MIT](../LICENSE). MIT does not cover third-party dependencies. [`device/ettsc/src/gec_v2.rs`](../device/ettsc/NOTICE.edge-tts.md) is LGPL-3.0-only, as that directory's notice says. The repository MIT license does not cover that file.

This is not an official Xiaomi or XiaoAI project, and it is not affiliated with, endorsed by, or representing them. The names only identify the hardware. Use it only on a device you own or are allowed to modify. Opening the case, enabling SSH, or writing system partitions can brick the device, lose data, void the warranty, or conflict with terms of service. Voice, text, and device-control requests are sent to the LLM and TTS services you configure, and to Xiaomi's cloud recognition. Do not send sensitive content.
