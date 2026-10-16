# Bias Studio

**Your bias. Your lo-fi.**

Bias Studio is a late-night broadcast studio that builds an original focus companion from a 6-question discovery session ("Akinator in reverse"), runs four closed-loop multimodal verifications, and opens a 25-minute Pomodoro work room with downloadable MP4 video and a Character Card V2 kit.

---

## Architecture & Model Roster (Interactions API, `google-genai >= 2.30.1`)

All model calls use `client.interactions.create(...)` (plus `client.voices.create(...)` for custom voice design) and are logged to the live Session Trace with step name, model ID, and latency in milliseconds.

| Role | Model ID | Config & Output |
| :--- | :--- | :--- |
| **Showrunner / Question Engine / Spec / Sheet & Video Verifier** | `gemini-4-argon` | `thinking_level="low"` (questions, sheet & video verification), `thinking_level="medium"` (character spec synthesis). Structured JSON via Pydantic schema. |
| **Visual Comparison Cards (Q3 This-or-That)** | `gemini-3.1-flash-lite-image` | `1:1` `1K` mood comparison images generated in parallel during Question 3. |
| **3-View Character Sheet & Desk Scene** | `gemini-nano-banana-2.1` | `16:9` `2K` character reference sheet (front, 3/4, profile + expression inset) and multi-turn edits via `previous_interaction_id`. |
| **Voice Designer & Speech Synthesizer** | `gemini-3.8-flash-tts` | Prompted custom voice (`client.voices.create`) + speech synthesis for the DJ intro and ASMR focus check-in. |
| **ASR Word-Accuracy Verifier** | `gemini-3.5-transcribe` | Transcribes `dj.wav` and `asmr.wav` to verify word overlap (`>= 0.70`) against the target script. |
| **Audio & Music Quality Verifier** | `gemini-3.8-flash` | `thinking_level="low"`. Scores vocal naturalness/persona match and checks that the 30s music loop is strictly instrumental at the target BPM. |
| **Original Instrumental Composer** | `lyria-3-clip-preview` | Generates an original 30-second instrumental track matched to the character's genre, BPM, and key. |
| **Late-Night Work Video Generator** | `gemini-omni-1.1-flash` | Animates the verified desk scene into a looping work video (180s timeout with CSS rain/lamp fallback). |

---

## Four Closed-Loop Verification Pipelines

1. **Loop 01 — Character Sheet (`gemini-nano-banana-2.1` -> `gemini-4-argon`)**
   - Generates a 16:9 2K 3-view character reference sheet.
   - `gemini-4-argon` inspects the image against all 8 `visual_traits` in `CharacterSpec` and checks that multiple character views are present.
   - If fewer than 6/8 traits match, `gemini-4-argon` emits a targeted `edit_instruction` and `gemini-nano-banana-2.1` edits the sheet via `previous_interaction_id` (up to 3 rounds).

2. **Loop 02 — DJ & ASMR Voice (`gemini-3.8-flash-tts` -> `gemini-3.5-transcribe` + `gemini-3.8-flash`)**
   - Designs a custom voice from `voice_description` and synthesizes `dj.wav` and `asmr.wav`.
   - `gemini-3.5-transcribe` transcribes both clips to measure word overlap (`>= 0.70`), while `gemini-3.8-flash` listens to the audio to score naturalness (`>= 3/5`) and persona fit (`>= 3/5`) (up to 2 rounds).

3. **Loop 03 — Original Instrumental (`lyria-3-clip-preview` -> `gemini-3.8-flash`)**
   - Generates a 30-second loop from `music_prompt`.
   - `gemini-3.8-flash` listens to `loop.wav` to confirm `is_instrumental == true` (no unwanted vocals), estimate BPM, and score late-night focus suitability (`>= 3/5`) (up to 2 rounds).

4. **Loop 04 — Work Video (`gemini-omni-1.1-flash` -> `gemini-4-argon`)**
   - Generates `video.mp4` from the late-night desk scene.
   - `gemini-4-argon` watches `video.mp4` alongside `sheet.png` to verify character consistency (`>= 3/5`), room atmosphere, and distortion-free motion (up to 2 rounds, 180s max wall time before CSS rain + warm desk lamp scene fallback).

---

## Safety & Originality Guardrails

- **Pre-study Collision Check:** Generated character names are checked against 101 virtual character names (`prestudy_names.txt`). Collisions trigger automatic renaming.
- **Input Refusal Gate:** Requests for real people, existing copyrighted characters/VTubers (Hatsune Miku, Lofi Girl, etc.), covers of existing songs, or underage/NSFW framing are refused with a calm explanation and an original adult archetype suggestion.
- **Adult Default:** Every generated companion has an explicit adult `apparent_age` (`early 20s`, `mid 20s`, or `late 20s`).

---

## Local Development & Cloud Run Deployment

### Run Locally
```bash
cp .env.example .env  # Add GEMINI_API_KEY
uv venv --python 3.11 .venv
uv pip install -r requirements.txt
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080
```

### Deploy to Cloud Run (`asia-northeast3`)
```bash
gcloud run deploy bias-studio \
  --source . \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --set-env-vars="GEMINI_API_KEY=${GEMINI_API_KEY},GCP_PROJECT_ID=${GCP_PROJECT_ID},GCS_BUCKET_NAME=${GCP_PROJECT_ID}-bias-studio"
```
