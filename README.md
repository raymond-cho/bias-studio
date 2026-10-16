# Bias Studio

Your bias. Your lo-fi.

Track 1, Gemini 4 Argon in entertainment. Google DeepMind AI Hackathon, Seoul, 2026-10-16.

## Start here

New here? Open the first link and tap through. Nothing to install, no sign-in.

| If you want to | Open | What you will see |
|---|---|---|
| Make your own bias (about 3 to 5 minutes) | [Live app](https://bias-studio-884389522240.asia-northeast3.run.app) | Press Try Now, pick Quick mode, answer 6 to 8 questions. The sheet, voice, music and video appear one by one with their check results. |
| See a finished result right away (no waiting) | [Finished session](https://bias-studio-884389522240.asia-northeast3.run.app/demo/default) | A character made earlier today, with every step and every check already done. |
| Just work with a companion | [Work player](https://bias-studio-884389522240.asia-northeast3.run.app/study/default) | Video, music loop, DJ intro and a 25-minute focus timer. Try the chat bar: "take me to the Han River tonight". |
| Understand how it is built | [Architecture page](https://bias-studio-884389522240.asia-northeast3.run.app/about) | Which model does what, and the four verification loops. |

If you only have one minute, open the finished session. If you have five, make your own.

### How to use it

1. Open the live app and press Try Now. Pick Quick mode.
2. Tap through the questions. Choose 'no preference' when you do not care. Question 3 shows two images; pick the one closer to your night.
3. Watch the spec, the character sheet and the checks appear. Green means a check passed; amber (UNVERIFIED) means it did not, with the reason.
4. When the player opens, press play. Use the chat bar to change the outfit, background, voice or music.
5. Download the mp4 and the Character Kit from the player page.

Source code: this repository. The version used for judging is tagged `demo-stable`.

## 1. The problem

### 1-1. K-culture runs on 'bias', and fans pay for it

In K-pop and K-culture, one word comes up everywhere: 'bias' (최애), the one member or character you love most. Fans pay to message their bias directly through subscription chat apps, buy and make goods with their bias's face on them, and spend nights on fan activity built around that one person. Naver Webtoon's 'Character Chat' shows the same pull for characters: it passed 100 million messages in its first year, and about 41 percent of messages in May 2025 were paid (Dailian, 2025-06-23). People spend real money on a bias.

### 1-2. But many fans never quite know what their bias is

Finding a bias is slow and vague. People watch stage after stage, clip after clip, and drift from group to group before something clicks. Plenty of fans are deep into fan activity without ever having put their own taste into words: what face, what voice, what temperament actually draws them. The taste is there; it is just never made explicit. That is the first problem we picked: fans spend time and money looking for a bias without a clear picture of what they are looking for.

### 1-3. Where the idea came from

Four things pointed the way.

- Bias-finder quizzes and ideal-type 'world cups' show that a few easy this-or-that taps are enough for people to say what they like. Piku hosts community-made brackets for idols, actors, anime characters and streamers, some with 1,024 candidates; smore's 'We'll find your bias' quiz records about 372,000 entries. But they only pick a winner from people and characters that already exist.
- SeeU, the first vocaloid to officially support Korean singing, came back on 2026-10-09 with a new voice after about 15 years (bnt news). A character with its own voice is something creators still want to own.
- Hatsune Miku has an official 'STUDY WITH MIKU' series, and 'study with ___' videos are a nightly habit. A character can be a work companion, not only something to watch.
- Original-character generators turn a typed description into an image. But most fans cannot write that description, and the result is a picture, not a companion.

### 1-4. What is missing

Each piece exists on its own. Nothing joins them. Derivative services built on Korean idols and webtoon characters are limited: chat stays inside one platform's licensed cast, and real idols cannot be remixed. Quizzes stop at a name. Generators stop at a picture. Study streams play someone else's character. Nobody turns your own taste into your own bias, gives it a voice, and lets it do something with you.

## 2. What we built

Bias Studio lets you build your bias yourself, through a survey, and then puts it to work.

- Survey: you tap through questions, like an ideal-type world cup, and Gemini 4 Argon turns your answers into a character. The survey covers look, outfit, pose, personality, voice and the music you work to. You never describe, draw, prompt or compose anything.
- Bias: an original character with a three-view sheet, a designed voice (DJ and ASMR), a personality, an original instrumental in your genre and a short work video. Every step is checked against your answers; anything that fails stays on screen as UNVERIFIED.
- Companion: the 'Work with <Name>' player keeps you company while you work, with a focus timer, and a chat bar where you can ask your bias for a new outfit, background, voice or track and watch it change.
- Sharing: finished characters can be published to a sharing gallery where others can listen, comment and bring them into their own study room, and exported as an 800 by 800 profile avatar and an open chara_card_v2 file.

Who it is for: K-culture fans who want a bias of their own, people who study or code late at night with work music on, and creators (new VTubers, music channel owners) who want an original host but cannot draw or prompt one.

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

## 5. Pre-study

Before the event we listed 100 popular virtual characters (Japanese and English VTubers, study and ASMR channels, virtual singers and lo-fi mascots) and grouped what fans respond to. In study and lo-fi content, soft voices, calm or caretaker temperaments and a 'quiet companion with a small ritual' dominate, and none of the 100 is a DJ who keeps a coder company at 2 AM. The taste axes in the survey come from that grouping. The names are used only to block lookalike character names and never appear in prompts or UI.

## 6. Built today

All code in this repository was written on 2026-10-16 between 11:20 and 15:20 KST. Prepared beforehand: the idea, the pre-study list and the instructions given to the coding agent. No app code existed before kickoff.

## 7. Known limits

- The originality guard checks names against the pre-study list. It does not yet score visual similarity to existing characters.
- A full run takes several minutes. For live judging we use Quick mode and keep a finished session at `/demo/default`.
- The gallery page holds sample characters made during the event, not real user uploads.
- Voice design quality varies between runs; the critic catches the worst cases, not all of them.

## 8. Run locally

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

- Piku, ideal-type world cup platform. https://www.piku.co.kr/
- smore quiz, 'We'll find your bias' (entry count as shown on the quiz page, 2026-10-16). https://smore.im/quiz/9d8LZCYHi2
- bnt news, 2026-10-09, SBS A&T releases a new voice for SeeU on Hangul Day. https://www.bntnews.co.kr/article/view/bnt202610090057
- Dailian, 2025-06-23, Naver Webtoon Character Chat one year: 100 million messages, 3.5 million users, 41 percent paid share. https://www.dailian.co.kr/news/view/1513472/
- Try OC Maker launch, September 2026. https://www.uniindia.com/press-releases/try-oc-maker-launches-ai-platform-for-creating-original-characters-from-text-and-reference-images/171562
