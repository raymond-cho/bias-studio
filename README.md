# Bias Studio — Your bias. Your lo-fi. (나만의 최애, 나만의 심야 작업실)

**Track 1 — Gemini 4 Argon in Entertainment (Google DeepMind AI Hackathon, Seoul, 2026-10-16)**  
- **Live Cloud Run URL:** https://bias-studio-884389522240.asia-northeast3.run.app  
- **Instant Pre-Verified Demo (`/demo/default`):** https://bias-studio-884389522240.asia-northeast3.run.app/demo/default  
- **Architecture & 4 Verification Loops (`/about`):** https://bias-studio-884389522240.asia-northeast3.run.app/about  
- **Public GitHub Repository:** https://github.com/raymond-cho/bias-studio  

---

## 🇺🇸 Part 1 — Engineering Notes (English)

### 1. Problem & Korean Entertainment Context
Late-night focus streams (*"Study with ___"*, lo-fi radio booths, webtoon OST rooms) have millions of daily listeners, yet the companion across the desk is always someone else's fixed character. Meanwhile, in Korea's entertainment ecosystem:
1. **K-Webtoon Visual & Emotional Grammar (NAVER Webtoon / Toomics):** Fans bond deeply with semi-realistic 7.5–8 head editorial webtoon characters framed in warm amber/cool midnight rim lighting ("Webtoon Glow") with grounded, dry-witted companionship (*"겉차속따"*).
2. **1:1 Character Chat (`캐릭터챗`):** NAVER Webtoon's Character Chat crossed 3.5M users and 100M+ messages with 41% paid conversion because fans want interactive 1:1 late-night conversation with their bias.
3. **Custom Vocal & Sound Synthesis (`SeeU` 15th Anniversary Revival & Suno):** The revival of Korea's pioneer virtual singer *SeeU (시유)* after 15 years highlights strong creator demand for owning a custom character voice bank (`gemini-3.8-flash-tts`) paired with an original soundtrack studio (`lyria-3-clip-preview`).

**Bias Studio** combines all three into a single verified pipeline orchestrated by **`gemini-4-argon`** via the **Interactions API (`google-genai >= 2.3.0`)**.

---

### 2. System Architecture & 7-Model Roster (`client.interactions.create`)

```
[3 Survey Modes: Quick (6Q, ~30s) | General (10Q, ~75s) | Bias Master (20Q+, Free Prompt)]
                                    │
                                    ▼
                     ┌──────────────────────────────┐
                     │        gemini-4-argon        │
                     │  Showrunner, Question Engine │
                     │  & CharacterSpec Synthesizer │
                     └──────────────┬───────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
┌───────────────────┐     ┌───────────────────┐     ┌───────────────────┐
│ Loop #1: Sheet    │     │ Loop #2: Voice    │     │ Loop #3: Music    │
│ nano-banana-2.1   │     │ 3.8-flash-tts     │     │ lyria-3-clip      │
│ (16:9 2K 3-View)  │     │ (DJ + ASMR WAVs)  │     │ (30s Instrumental)│
│        │          │     │        │          │     │        │          │
│ Verified by Argon │     │ Verified by       │     │ Verified by       │
│ (8/8 Trait Check) │     │ 3.5-transcribe +  │     │ 3.8-flash         │
└─────────┬─────────┘     │ 3.8-flash (>=70%) │     │ (No vocals / BPM) │
          │               └─────────┬─────────┘     └─────────┬─────────┘
          └─────────────────────────┼─────────────────────────┘
                                    ▼
                     ┌──────────────────────────────┐
                     │ Loop #4: Late-Night Video    │
                     │ gemini-omni-1.1-flash (MP4)  │
                     │ Watched & Verified by Argon  │
                     └──────────────┬───────────────┘
                                    ▼
     [STUDY WITH <NAME> - PART 1 Player + 1:1 Live Chat + Virtual Fitting Door]
     [Exports: study_with_<name>.mp4 + chara_card_v2.png + character_kit.zip]
```

| Role | Official Model ID | API Surface | Verification / Usage |
| :--- | :--- | :--- | :--- |
| **Showrunner & Verifier** | `gemini-4-argon` | `client.interactions.create` (`thinking_level="low"`) | Adaptive reverse-Akinator questions, `CharacterSpec` synthesis, Sheet 8-trait verification, Video consistency verification, 1:1 Character Chat |
| **Visual A/B & Fast Scene Edit** | `gemini-3.1-flash-lite-image` | `client.interactions.create` (`1K`) | Question 3 This-or-That 1K portrait pair + real-time Virtual Studio Door style transformation |
| **2K Sheet & Scene Artist** | `gemini-nano-banana-2.1` | `client.interactions.create` (`16:9`, `2K`) | 3-view character reference sheet (`sheet.png`) + multi-turn trait repair + 2K desk scene (`scene.png`) |
| **Voice Designer & TTS** | `gemini-3.8-flash-tts` | `client.voices.create` + `interactions.create` | Custom voice bank design + DJ intro (`dj.wav`), ASMR check-in (`asmr.wav`), and live chat TTS replies |
| **ASR Verifier** | `gemini-3.5-transcribe` | `client.interactions.create` | Transcribes generated WAVs to verify word overlap (`>= 0.70`) against target script |
| **Audio Critic** | `gemini-3.8-flash` | `client.interactions.create` (`thinking_level="low"`) | Evaluates vocal naturalness/persona match (1–5) and verifies Lyria music is purely instrumental |
| **Instrumental Composer** | `lyria-3-clip-preview` | `client.interactions.create` | Generates 30-second original instrumental focus tracks (`loop.wav`) |
| **Video Animator** | `gemini-omni-1.1-flash` | `client.interactions.create` (180s timeout) | Animates late-night work loop (`video.mp4`) anchored on `sheet.png` and `scene.png` |

---

### 3. Four Explicit Self-Correcting Verification Loops

1. **Loop #1 — 3-View Character Sheet (`run_sheet_loop`):**
   - `gemini-nano-banana-2.1` renders a 16:9 2K 3-view reference sheet.
   - `gemini-4-argon` inspects the image against all 8 `visual_traits` in `CharacterSpec`. If `matched_count < 6` or `three_views_present == False`, Argon writes a targeted `edit_instruction` and passes `previous_interaction_id` back to `gemini-nano-banana-2.1` (up to 3 rounds).
2. **Loop #2 — Custom Voice Design & ASR/Critique (`run_voice_loop`):**
   - `gemini-3.8-flash-tts` designs a custom voice via `client.voices.create` and synthesizes `dj.wav` and `asmr.wav` in parallel.
   - `gemini-3.5-transcribe` checks word accuracy (`word_overlap_ratio >= 0.70`) while `gemini-3.8-flash` scores naturalness and persona fit (`>= 3/5`). On failure, `revised_style_hint` triggers re-synthesis.
3. **Loop #3 — Original Instrumental Music (`run_music_loop`):**
   - `lyria-3-clip-preview` composes a 30s track.
   - `gemini-3.8-flash` listens to `loop.wav` to verify `is_instrumental == True`, `vocals_detected == False`, and `mood_match_score >= 3`.
4. **Loop #4 — Late-Night Work Video (`run_video_loop`):**
   - `gemini-omni-1.1-flash` generates `video.mp4` (guarded by a 180s wall-clock timeout with an automatic CSS rain + warm desk lamp scene fallback).
   - `video.mp4` is uploaded via `client.files.upload` and watched by `gemini-4-argon` alongside `sheet.png` to verify `character_consistency_score >= 3` and `distortion_free == True`.

---

### 4. Key Interactive Features
- **Bilingual UI (`EN | 한국어`):** Instant language switcher in the top navigation bar.
- **NAVER Webtoon MON–SUN Character Grid + Live Video Hero + 3D Mouse Tracking:** Cursor-following perspective tilt, gaze parallax, and warm amber desk lamp spotlight.
- **3 Survey Modes:**
  - **Quick Mode:** 6–8 questions, 2–3 choices, ~30s user effort.
  - **General Mode:** 10–15 questions, 3–4 choices, ~60–90s user effort.
  - **Bias Mode:** 20–30 questions, up to 5 choices + free-text prompt input on every turn, 2–3+ min effort.
- **Live 1:1 Character Chat + "Virtual Studio Door" Transformation:** Ask your companion in the bottom chat bar to change their hairstyle, outfit, background, voice tone, or music. The character replies out loud via TTS (`gemini-3.8-flash-tts`), steps behind an animated **Virtual Studio Fitting Door** while the AI generates the new look/audio, and emerges transformed.
- **Portable `chara_card_v2` Kit (`.zip`):** Embeds base64 `chara_card_v2` metadata directly into `sheet.png` (`tEXt` chunk `chara`) and packages `study_with_<name>.mp4`, `persona.md`, `character_spec.json`, `verification_report.md`, and WAV stems.

---

### 5. Local Setup & Cloud Run Deployment

```bash
cd app
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt

# Configure app/.env (never committed)
# GEMINI_API_KEY=...
# GCP_PROJECT_ID=h2gdm-hack26icn-2731

uvicorn main:app --host 0.0.0.0 --port 8080
```

---

## 🇰🇷 Part 2 — 프로젝트 기술 문서 및 사용 안내 (한국어)

### 1. 기획 배경: 왜 '한국형 엔터테인먼트(K-Webtoon & 버추얼 신스)'인가?
유튜브와 스트리밍 플랫폼에서 *"Study with me"*, 심야 로파이 라디오, 웹툰 OST 작업실 영상은 매일 수백만 명이 찾지만 화면 속 캐릭터는 언제나 '남이 만들어 둔 캐릭터'입니다. 동시에 한국 엔터테인먼트 시장에는 세 가지 강력한 흐름이 존재합니다:
1. **K-웹툰(네이버 웹툰 / 투믹스) 비주얼 문법:** 7.5~8등신 세미 리얼리스틱 비율, 앰버 스탠드 조명과 서울 심야 빗빛이 교차하는 '웹툰 글로우(Webtoon Glow)', 과장된 애니메이션 말투 대신 담백하고 다정한 '겉차속따' 동료 페르소나.
2. **유료 1:1 '캐릭터챗(Character Chat)' 열풍:** 네이버 웹툰 캐릭터챗이 누적 사용자 350만 명·메시지 1억 건(유료 메시지 비중 41%)을 돌파한 것처럼, 팬들은 최애 캐릭터와 실시간으로 대화하며 교감하기를 원합니다.
3. **한국 버추얼 싱어 '시유(SeeU)' 15주년 부활 & 나만의 보이스/사운드 스튜디오 수요:** 15년 만에 부활한 한국 버추얼 싱어 '시유'와 Suno 등 오픈 보이스 음악 제작 트렌드처럼, 팬들은 **나만의 최애 보이스 뱅크(`gemini-3.8-flash-tts`)**와 **오리지널 사운드트랙(`lyria-3-clip-preview`)**을 직접 소유하고 싶어 합니다.

**Bias Studio**는 이 세 가지를 **`gemini-4-argon` 쇼러너**와 **4대 자율 검증 루프**로 결합한 인터랙티브 심야 작업실 스튜디오입니다.

---

### 2. 핵심 기능 요약
1. **상단 배너 `EN | 한국어` 실시간 언어 설정 전환:** 참가자와 심사위원이 원할 때 언제든 한국어/영어 UI를 즉시 전환할 수 있습니다.
2. **최상단 라이브 비디오 + 네이버 웹툰 스타일 월~일(MON~SUN) 캐릭터 그리드 + 마우스 추적 인터랙션:** 마우스 커서 움직임에 따라 캐릭터가 시선/고개를 돌리는 3D 패럴랙스 및 앰버 조명 인터랙션을 제공합니다.
3. **설문 시작 전 3가지 모드 제공 (`Quick / General / Bias Mode`):**
   - **Quick Mode (퀵 모드):** 6~8문항, 선택지 2~3개, 약 30초 소요
   - **General Mode (제너럴 모드):** 10~15문항, 선택지 3~4개, 약 60~90초 소요
   - **Bias Mode (최애 마스터 모드):** 20~30문항, 선택지 최대 5개 + 자유 프롬프트 입력, 2~3분 이상 소요
4. **`STUDY WITH <NAME> - PART 1` 플레이어 & 실시간 '가상의 문(Virtual Studio Door)' 변신 인터랙션:**
   - 하단 채팅창에서 *"너 머리스타일 바꿔올래?"*, *"난 좀 더 조용한 목소리가 좋은데"*, *"배경을 비 오는 서울 루프탑으로 바꿔줘"*, *"음악을 잔잔한 피아노로 바꿔줘"*를 클릭하거나 입력하면, 캐릭터가 **즉시 TTS 음성으로 응답**한 뒤 **가상의 스튜디오 피팅룸 문(Virtual Door)에 들어갔다 나오면서 새로운 스타일/목소리/음악/배경으로 실시간 변신**합니다.
5. **로컬 `Demo/` 폴더 내 사용자 매뉴얼 및 샘플 산출물 완비:**
   - 로컬 PC의 `Demo/00_USER_MANUAL_사용설명서_및_시나리오.md` 및 `Demo/sample_outputs/`에서 모든 설명서와 검증된 샘플 파일(`study_with_sora.mp4`, `sheet.png`, `sora_character_kit_v2.zip` 등)을 바로 확인하실 수 있습니다.
