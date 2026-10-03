# Fixel Voice Questions: Design Spec

**Date:** 2026-10-02
**Status:** Approved in brainstorming, pending written-spec review
**Builds on:** `docs/superpowers/specs/2026-09-30-fixel-design.md`

## 1. Purpose

Ask Fixel a question out loud instead of typing it. Speech is turned into text **on the Mac** (nothing about the audio leaves the machine). The text lands in Fixel's prompt, where the user can check and edit it before pressing Enter.

### Spike findings this design rests on (2026-10-02, throwaway test, M3 / 8 GB / macOS 26.6.2)

- A Python process started from Terminal.app can record the microphone: macOS prompts for Terminal, and the audio comes through cleanly. Terminal declares neither `NSMicrophoneUsageDescription` nor `NSSpeechRecognitionUsageDescription`, so **Apple's Speech framework is ruled out** (macOS may kill the process that asks for it). Microphone access worked anyway.
- On-device Whisper via `mlx-whisper` transcribed clearly. Two models independently produced the same sentence from TV audio in the room. Timing: `whisper-large-v3-turbo` took 1.4 s warm (4.2 s on first load); `whisper-small.en` took 0.9 s.
- Recording at 16 kHz directly from a 48 kHz mic produced nonsense in round 1. Capturing at the device's native rate and resampling in software fixed it.
- The mic picks up anything nearby (a TV, in the test). This is mitigated by hold-to-talk and by showing the text before sending.

### Success criteria

1. From any app: tap Right Option, tap again and **hold**; within ~0.3 s Fixel plays a start sound and records while ⌥ is held.
2. On release: a stop sound plays and the drag-to-select crosshair appears (Esc = voice-only question). Transcription runs **while** the user selects.
3. The transcribed text appears in Fixel's prompt (Fixel window in front) within ~2 s of release on an M-series Mac with the model warm.
4. A quick double-tap still takes a plain screenshot exactly as before.
5. Without the voice add-on, without mic permission, or with silence, Fixel says clearly what's wrong and the screenshot still works.

## 2. Constraints

- Voice is an **optional extra**: `pip install -e '.[voice]'` adds `mlx-whisper`, `sounddevice`, `scipy`, and `pyobjc-framework-AVFoundation` (~1.2 GB including PyTorch). The core install stays lean, and Fixel without the extra must behave exactly as today, with `/help` and setup explaining how to add voice.
- Apple Silicon only (MLX). On Intel Macs, voice reports "not supported on this Mac".
- Audio stays in memory only: it's never written to disk and never sent to a model provider.
- Default model `mlx-community/whisper-large-v3-turbo` (1.6 GB download on first use); `mlx-community/whisper-small.en-mlx` is the documented lighter option.
- Recording is capped at 60 s.

## 3. Gesture: double-tap vs double-tap-and-hold

`DoubleTapDetector` becomes an event source instead of returning a boolean:

| Sequence | Event(s) |
|---|---|
| tap, tap (2nd release < `voice_hold_seconds` after 2nd press) | `shot` on 2nd release |
| tap, press-and-hold ≥ `voice_hold_seconds` (default 0.3 s) | `voice_start` when the hold threshold passes, `voice_end` on release |
| ⌥ + another key before the hold threshold passes | nothing (a chord, as today) |
| other keys after `voice_start` | ignored; still recording until ⌥ is released |

API (pure, unit-tested): `option_down(t)`, `option_up(t) -> str | None`, `other_key(t)`, `tick(t) -> str | None`. `HotkeyListener` schedules a `threading.Timer(voice_hold_seconds)` on the second press that calls `tick`. A lock serializes the detector between the event-tap thread and the timer thread. The listener reports event names (`"shot"`, `"voice_start"`, `"voice_end"`) to the app's queue.

## 4. Components

```
fixel/voice/
  __init__.py      # available() -> (bool, reason): extra installed? Apple Silicon?
  recorder.py      # Recorder: start()/stop() on a sounddevice InputStream at the device's native rate
  audio.py         # to_16k(samples, rate) via scipy.signal.resample_poly; is_silent(samples)
  transcribe.py    # Transcriber(model): warm() and transcribe(samples_16k) -> str, run in a worker thread
  sounds.py        # play("start" | "stop") via afplay with /System/Library/Sounds/Tink.aiff / Pop.aiff
```

- **Recorder:** opens the default input device at its `default_samplerate`, mono float32, and appends callback blocks. `stop()` returns `(samples, rate)` and stops at the 60 s cap.
- **audio.to_16k:** `resample_poly(samples, 16000 / g, rate / g)` with `g = gcd`. **is_silent:** peak < 0.003.
- **Transcriber:** `mlx_whisper.transcribe(audio, path_or_hf_repo=model, language="en", condition_on_previous_text=False, initial_prompt=VOCAB_HINT)`. `VOCAB_HINT` lists common tech and school words (Python, pandas, npm, zsh, Git, JavaScript, venv, VS Code, calculus, …) to bias spelling. `warm()` transcribes 0.5 s of zeros once so the model loads in the background.
- **Mic permission:** `permissions.microphone_status()` uses AVFoundation (`AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)`): authorized / denied / not determined. Added to `fixel setup` and to the startup banner when voice is enabled.

## 5. Flow

1. **Startup:** if `voice = true` and `voice.available()` is true, start `Transcriber.warm()` in the background (`asyncio.to_thread`). Otherwise show one dim line: "Voice is off: <reason>".
2. **`voice_start`:** play `start` sound, `Recorder.start()`, toolbar shows `🎙 listening… let go of ⌥ when you're done`.
3. **`voice_end`:** play `stop` sound, `samples, rate = Recorder.stop()`. Then **concurrently**: (a) the normal screenshot path (`capture_once`, which raises the Fixel window afterwards); (b) if not silent, `transcribe(to_16k(...))` in a worker thread.
4. When transcription finishes, its text is **inserted into the prompt** at the cursor. If an answer is streaming, it's queued and pre-filled into the next prompt. The user edits it if needed and presses Enter: the normal ask path, tray included.
5. A screenshot cancelled with Esc gives a voice-only question (text, empty tray).

`UI.offer_text(text)`: if the prompt is active, `current_buffer.insert_text(text)`; otherwise store it and merge it into the next `prompt(default=…)`.

## 6. Errors

| Condition | Behavior |
|---|---|
| Voice extra not installed | Startup dim line + `/help` note: "Voice is off. Add it with `pip install -e '.[voice]'` in the Fixel folder." Hold-to-talk falls back to a normal screenshot. |
| Not Apple Silicon | "Voice needs an Apple Silicon Mac." Same fallback. |
| Mic permission denied | Red banner at startup (if voice enabled) with the System Settings path (Privacy & Security → Microphone → Terminal). On `voice_start`, flash the same hint and take the screenshot only. |
| Silence (peak < 0.003) | Flash "Didn't hear anything. Is the mic allowed and unmuted?" No transcription; the screenshot still happens. |
| Model download fails (offline first run) | Flash "Couldn't load the Whisper model (needs internet the first time)"; voice retries on the next use. |
| Transcription raises | Flash "Couldn't turn that into text"; audio discarded; screenshot unaffected. |
| Recording hits 60 s | Stop automatically as if ⌥ were released. |

## 7. Config

```toml
voice = true                                         # hold ⌥ on the 2nd tap to ask out loud
whisper_model = "mlx-community/whisper-large-v3-turbo"   # or "mlx-community/whisper-small.en-mlx" (lighter)
voice_hold_seconds = 0.3                             # how long the 2nd tap must be held to mean "voice"
```

## 8. Testing

- **Unit (offline, no mic):**
  - detector event sequences (shot, voice start/end, chord before threshold, keys during voice, timing edges)
  - `to_16k` (length and that a 440 Hz tone keeps its frequency after 48k→16k and 44.1k→16k)
  - `is_silent`
  - `Transcriber` with an injected fake `transcribe_fn` (arguments include `language="en"` and the hint)
  - `voice.available()` reasons
  - app flow with fake recorder/transcriber/capture: `voice_start` → `voice_end` gives a capture call plus offered text; silent audio gives a flash and no transcription; extra missing gives a screenshot-only fallback
  - `UI.offer_text` while the prompt is idle vs during streaming
- **Live:** the user holds ⌥, speaks a known sentence with the TV off, selects a region, and checks the text in the prompt; then a quick double-tap still takes a plain screenshot.

## 9. Out of scope

Wake words, continuous listening, spoken answers (text-to-speech), non-English languages (Whisper can do them; `language="en"` is pinned for v1 accuracy), and saving audio.
