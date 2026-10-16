# Bias Studio

Your bias. Your lo-fi.

Track 1, Gemini 4 Argon in entertainment. Google DeepMind AI Hackathon, Seoul, 2026-10-16.

- Live app: https://bias-studio-884389522240.asia-northeast3.run.app
- Finished session (replay): https://bias-studio-884389522240.asia-northeast3.run.app/demo/default
- Work player: https://bias-studio-884389522240.asia-northeast3.run.app/study/default
- Architecture page: https://bias-studio-884389522240.asia-northeast3.run.app/about

## What it does

"Bias" is the K-pop word for the one you like most. Late-night "study with ___" videos (lo-fi jazz, orchestral anime-BGM style) are everywhere, but the character keeping you company is always someone else's.

Bias Studio builds yours. You never describe, draw, prompt or compose anything. You tap through questions, Akinator in reverse, and get an original late-night work companion with its own look, voice, music and a short work video. Every step is checked by a model before you see it.

Who it is for: people who code or study late at night with work music on, and creators (new VTubers, music channel owners) who want an original host but cannot draw or prompt one.

## Flow

1. Pick a survey mode: Quick (6 to 8 questions, 2 to 3 choices), General (10 to 15 questions, 3 to 4 choices) or Bias (20 to 30 questions, up to 5 choices plus free text).
2. `gemini-4-argon` asks each next question in one ongoing interaction (`previous_interaction_id`), so every answer and every image you rejected stays in the same context. Question 3 is a this-or-that pair drawn by `gemini-3.1-flash-lite-image`.
3. Argon writes a character spec. Each trait points back to the answers it came from.
4. Four checked steps: character sheet, voice, music, work video (see below).
5. The "Work with <Name>" player: work video, music loop, DJ intro, ASMR line, 25-minute focus timer.
6. Keep talking to the character in the chat bar. Ask for a different outfit, background, voice or music; the character answers in its own voice, walks behind a studio door while the new version is generated, and comes back changed. Ten Korean night backgrounds are pre-made (Han River, Namsan, Gyeongbokgung, Seongsu, Jeju and others), so background changes are quick.
7. Download: `study_with_<name>.mp4`, a Character Kit zip, and a `chara_card_v2` file that open-source character apps can import.

## Models

| Job | Model |
|---|---|
| Question engine, spec, edit instructions, sheet check, video check, character chat | `gemini-4-argon` |
| This-or-that images, quick style changes | `gemini-3.1-flash-lite-image` |
| Character sheet (16:9, 2K), desk scene, targeted edits | `gemini-nano-banana-2.1` |
| Voice and music critic | `gemini-3.8-flash` |
| Voice design (`client.voices.create`) and speech | `gemini-3.8-flash-tts` |
| Line check | `gemini-3.5-transcribe` |
| 30-second original instrumental | `lyria-3-clip-preview` |
| Work video | `gemini-omni-1.1-flash` |

All calls go through the Interactions API with `google-genai >= 2.3.0`. Every call is logged to a session trace that the UI shows.

## Verification loops

| Loop | Made by | Checked by | Pass rule | Retries |
|---|---|---|---|---|
| 1. Character sheet | nano-banana-2.1 | gemini-4-argon | at least 6 of 8 visual traits, all three views present | up to 3 rounds; Argon writes a targeted edit each round |
| 2. Voice | 3.8-flash-tts | 3.5-transcribe and 3.8-flash | word overlap at least 0.70, persona fit at least 3 of 5 | re-synthesis with a revised style hint |
| 3. Music | lyria-3-clip-preview | 3.8-flash (listens) | instrumental, no vocals, mood match at least 3 of 5 | one retry with a rewritten prompt |
| 4. Video | omni-1.1-flash | gemini-4-argon (watches the clip next to the sheet) | character consistency at least 3 of 5, no distortion | one retry |

Items that still fail are shown as UNVERIFIED with the reason. Nothing is hidden.

If Omni fails or passes the 180-second limit, a local 16fps 2.5D renderer (Pillow and ffmpeg) animates the desk scene instead, so the player never stops.

## Pre-study

Before the event we listed 100 popular virtual characters (Japanese and English VTubers, study and ASMR channels, virtual singers and lo-fi mascots) and grouped what fans respond to. In study and lo-fi content, soft voices, calm or caretaker temperaments and a "quiet companion with a small ritual" dominate, and none of the 100 is a DJ who keeps a coder company at 2 AM. The taste axes in the question engine come from that grouping. The names are used only to block lookalike character names; they never appear in prompts or UI.

## Built today

All code in this repository was written on 2026-10-16 between 11:20 and 15:20 KST. Prepared beforehand: the idea, the pre-study list and the instructions given to the coding agent. No app code existed before kickoff.

## Known limits

- The originality guard checks names against the pre-study list. It does not yet score visual similarity to existing characters.
- A full run takes several minutes end to end. For live judging we use Quick mode and keep a finished session at `/demo/default`.
- The gallery page holds sample entries made during the event, not real user uploads.
- No accounts and no database. Sessions live in memory and in a Cloud Storage bucket.

## Run locally

```bash
cd app
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
# app/.env (never committed): GEMINI_API_KEY=...
uvicorn main:app --host 0.0.0.0 --port 8080
```

Deploy:

```bash
gcloud run deploy bias-studio --source . --region asia-northeast3 \
  --allow-unauthenticated --max-instances=1 --timeout=900 --memory=2Gi
```

## 한국어 요약

Bias Studio는 질문에 답하기만 하면 나만의 '최애' 작업 동료 캐릭터를 만들어 주는 서비스입니다. 그림을 그리거나 프롬프트를 쓸 필요가 없고, 버튼으로 고르기만 하면 됩니다.

흐름은 다음과 같습니다.
- 설문 모드를 고릅니다 (Quick 6~8문항, General 10~15문항, Bias 20~30문항).
- gemini-4-argon이 답을 모두 기억한 채로 다음 질문을 고르고, 답에 근거한 캐릭터 설정서를 씁니다.
- 캐릭터 시트, 목소리, 음악, 작업용 영상을 차례로 만들고, 단계마다 다른 모델이 설정서와 맞는지 확인합니다. 통과하지 못한 항목은 숨기지 않고 'UNVERIFIED'로 표시합니다.
- 완성되면 'Work with <이름>' 화면에서 영상, 음악, DJ 멘트, 25분 집중 타이머를 함께 쓸 수 있습니다.
- 채팅으로 의상, 배경(한강, 남산, 경복궁 등 10곳), 목소리, 음악을 바꿔 달라고 하면, 캐릭터가 목소리로 답한 뒤 '스튜디오 문' 뒤에서 바뀐 모습으로 다시 나옵니다.

모든 코드는 대회 당일(2026-10-16) 11:20~15:20에 작성했습니다. 사전에 준비한 것은 아이디어, 캐릭터 100명 pre-study 목록, 코딩 에이전트용 지시문뿐입니다.
