# HyperFrames Captions And Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve technical captions and TTS pronunciation, then insert the complete original-audio demo immediately after the first LLM handoff explanation.

**Architecture:** Keep display copy and spoken copy separate. Generate timestamped EdgeTTS audio from spoken copy, transform its subtitles into protected display captions, and insert the full-screen demo after “再把用户问题转给 LLM”. Resume with a newly recorded bridge sentence that returns from the observed result to the structured routing logic.

**Tech Stack:** Python 3, EdgeTTS, HyperFrames HTML/GSAP, FFmpeg.

---

### Task 1: Caption transformation

**Files:**
- Modify: `xiaomi-ai-llm-explainer/scripts/test_generate_captions.py`
- Modify: `xiaomi-ai-llm-explainer/scripts/generate_captions.py`

- [ ] Add failing tests for protected tokens, punctuation removal, display aliases, and post-insert timing offsets.
- [ ] From `xiaomi-ai-llm-explainer`, run `python3 -m unittest scripts/test_generate_captions.py` and confirm the new assertions fail.
- [ ] Implement token-aware splitting and timeline transformation.
- [ ] Run the test suite and confirm all assertions pass.

### Task 2: Narration assets

**Files:**
- Create: `xiaomi-ai-llm-explainer/narration-tts.txt`
- Replace: `xiaomi-ai-llm-explainer/assets/narration.mp3`
- Replace: `xiaomi-ai-llm-explainer/assets/narration.srt`
- Replace: `xiaomi-ai-llm-explainer/assets/captions.js`

- [ ] Replace “这里不是靠关键词猜测。” in `narration-tts.txt` with “这段实测背后，关键不是关键词匹配，而是读取原生结构化结果。”
- [ ] Keep technical identifiers in natural spoken Chinese without changing narrative meaning.
- [ ] Generate EdgeTTS audio and subtitles with `zh-CN-YunjianNeural`.
- [ ] Regenerate display captions with the tested transformation.
- [ ] Verify audio and caption durations with FFprobe and a cue-boundary check.

### Task 3: Full-screen demo insertion

**Files:**
- Create: `xiaomi-ai-llm-explainer/assets/full-demo.mov`
- Modify: `xiaomi-ai-llm-explainer/index.html`

- [ ] Copy the source demo into project assets.
- [ ] Read the exact SRT end timestamp of the cue containing “再把用户问题转给 LLM” and use it as the insertion point.
- [ ] Add separate muted video and original-audio clips at that insertion point.
- [ ] Split narration playback around the demo and shift the bridge sentence and all later scene starts by the exact `94.017596s` media duration.
- [ ] Add transitions into and out of the demo while keeping captions hidden during it.

### Task 4: Verification

**Files:**
- Verify: `xiaomi-ai-llm-explainer/index.html`

- [ ] From `xiaomi-ai-llm-explainer`, run `python3 -m unittest scripts/test_generate_captions.py` and require 0 failures.
- [ ] Run `npm run check` in the HyperFrames project.
- [ ] Inspect frames immediately before, during, and after the demo.
- [ ] Keep the preview server running and provide the Studio URL.
