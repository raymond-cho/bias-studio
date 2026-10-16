# Bias Studio

Your bias. Your lo-fi.

Track 1, Gemini 4 Argon in entertainment. Google DeepMind AI Hackathon, Seoul, 2026-10-16.

- Live app: https://bias-studio-884389522240.asia-northeast3.run.app
- Finished session (replay): https://bias-studio-884389522240.asia-northeast3.run.app/demo/default
- Work player: https://bias-studio-884389522240.asia-northeast3.run.app/study/default
- Architecture page: https://bias-studio-884389522240.asia-northeast3.run.app/about
- Stable tag: `demo-stable`

## 1. The problem

The market is already here, and the need is strong.

- People talk to characters. Naver Webtoon's 'Character Chat' launched in June 2024 and passed 100 million messages and about 3.5 million users within a year; about 41 percent of messages in May 2025 were paid (Dailian, 2025-06-23).
- People work next to characters. 'Study with ___' videos are a daily habit for students and developers. Hatsune Miku has an official 'STUDY WITH MIKU' series; the Lofi Girl channel is one of the largest live streams on YouTube.
- People want characters of their own. Original-character generators such as Try OC Maker (launched September 2026) let anyone describe a character in text and get an image back.

What is missing sits between these three.

- None of them makes a character from your taste. They need a prompt, a reference image, or someone else's character. Most people cannot describe what they like; they know it when they see it.
- None of them puts the character to work. A chat bot talks. An image generator draws. A lo-fi stream plays. Nothing turns one original character into a companion that keeps you company while you work, with its own voice and music, and keeps that identity consistent across all of it.

Everything a person needs for 'my own character, doing something for me tonight' is spread across separate tools. That is the problem.

## 2. What Bias Studio does

'Bias' is the K-pop word for the one you like most. Bias Studio builds yours from questions alone and puts it to work as a late-night companion.

You never describe, draw, prompt or compose anything. You tap through questions, Akinator in reverse, and get an original character with its own look, voice, music and a short work video. Every step is checked against your answers before you see it. Then the character keeps you company: a work player with a focus timer, and a chat bar where you can ask for a different outfit, background, voice or music and watch the character change.

Who it is for: people who code or study late at night with work music on, and creators (new VTubers, music channel owners) who want an original host but cannot draw or prompt one.

## 3. How it works

| Step | What happens | Model |
|---|---|---|
| Survey | Quick (6 to 8 questions), General (10 to 15) or Bias (20 to 30). Each question has 2 to 5 choices. Question 3 is a this-or-that image pair. | gemini-4-argon asks; gemini-3.1-flash-lite-image draws the pair |
| Spec | One ongoing Argon interaction (`previous_interaction_id`) holds every answer and every rejected image, then writes a character spec. Each trait points back to the answers it came from. | gemini-4-argon |
| Sheet | 16:9 character sheet, three views, 2K. Checked against 8 visual traits; Argon writes a targeted edit if fewer than 6 pass. Up to 3 rounds. | gemini-nano-banana-2.1, checked by gemini-4-argon |
| Voice | A voice is designed from the spec (`client.voices.create`), then a DJ intro and an ASMR line are spoken. Checked by transcription (word overlap at least 0.70) and by a listening critic (persona fit at least 3 of 5). | gemini-3.8-flash-tts, checked by gemini-3.5-transcribe and gemini-3.8-flash |
| Music | A 30-second original instrumental in the genre you chose (lo-fi jazz, orchestral, chamber strings, solo piano, jazz trio, city pop, ambient). Checked for no vocals and mood match. | lyria-3-clip-preview, checked by gemini-3.8-flash |
| Video | A short work loop of the character at the desk. Argon watches the clip next to the sheet and checks that it is the same character. If Omni is slow or fails, a local 16fps 2.5D renderer animates the still scene so the player never stops. | gemini-omni-1.1-flash, checked by gemini-4-argon |
| Player | 'Work with <Name>': video, music loop, DJ intro, ASMR line, 25-minute focus timer. | |
| Chat | Ask the character for a new outfit, background, voice or track. It answers in its own voice, steps behind a studio door while the new version is generated, and comes back changed. Ten Korean night backgrounds are pre-made (Han River, Namsan, Gyeongbokgung, Seongsu, Jeju and others). | gemini-4-argon, gemini-3.8-flash-tts, gemini-nano-banana-2.1 |

Items that fail their check are shown as UNVERIFIED with the reason. Nothing is hidden. Every model call is written to a session trace that the UI shows.

All calls use the Interactions API (`google-genai >= 2.3.0`). The app runs on Cloud Run; finished sessions are copied to Cloud Storage so `/demo/<id>` survives redeploys. No accounts, no database.

## 4. What you get

- `study_with_<name>.mp4`: the work video with music and the DJ intro, ready to upload or loop.
- Character Kit zip: sheet, scene, voice clips, music loop, spec, persona, verification report.
- `chara_card_v2`: an open character-card file that existing open-source character apps can import, so the character is not locked to this app.
- An 800 by 800 avatar cut for profile pictures.

## 5. How to use it

1. Open the live app and pick Quick mode.
2. Tap through the questions. Pick 'no preference' when you do not care.
3. Watch the spec, the sheet and the checks appear. Amber badges mean a check did not pass.
4. When the player opens, press play. Try the chat bar: 'take me to the Han River tonight'.
5. Download the kit from the player page.

A finished session is always available at `/demo/default` for a quick look.

## 6. Pre-study

Before the event we listed 100 popular virtual characters (Japanese and English VTubers, study and ASMR channels, virtual singers and lo-fi mascots) and grouped what fans respond to. In study and lo-fi content, soft voices, calm or caretaker temperaments and a 'quiet companion with a small ritual' dominate, and none of the 100 is a DJ who keeps a coder company at 2 AM. The taste axes in the survey come from that grouping. The names are used only to block lookalike character names and never appear in prompts or UI.

## 7. Built today

All code in this repository was written on 2026-10-16 between 11:20 and 15:20 KST. Prepared beforehand: the idea, the pre-study list and the instructions given to the coding agent. No app code existed before kickoff.

## 8. Known limits

- The originality guard checks names against the pre-study list. It does not yet score visual similarity to existing characters.
- A full run takes several minutes. For live judging we use Quick mode and keep a finished session at `/demo/default`.
- The gallery page holds sample characters made during the event, not real user uploads.
- Voice design quality varies between runs; the critic catches the worst cases, not all of them.

## 9. Run locally

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

## Sources

- Dailian, 2025-06-23, Naver Webtoon Character Chat one year: 100 million messages, 3.5 million users, 41 percent paid share. https://www.dailian.co.kr/news/view/1513472/
- Try OC Maker launch, September 2026. https://www.uniindia.com/press-releases/try-oc-maker-launches-ai-platform-for-creating-original-characters-from-text-and-reference-images/171562
