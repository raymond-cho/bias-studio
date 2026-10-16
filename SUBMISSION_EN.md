# Cerebral Valley Final Submission Package (English Only)
**Event:** Google DeepMind AI Hackathon Seoul (2026-10-16)
**Submission Portal:** https://cerebralvalley.ai/e/google-deepmind-ai-hackathon
**Deadline:** 15:20 KST (Sharp)
**Track:** Track 1 — Gemini 4 Argon in Entertainment

---

## 1. Project Name
**Bias Studio — "Your bias. Your lo-fi."**

---

## 2. Short Tagline / Elevator Pitch (1–2 sentences)
An interactive Korean Webtoon & Lo-Fi Broadcast Studio powered by **Gemini 4 Argon**, where 6–20 adaptive questions cast an original 2D cel-shaded companion, synthesize a bespoke voice bank and 30-second lo-fi radio track, stage 10 iconic Korean nightscape backgrounds, and co-work with you through real-time voice chat and self-verified multimodal orchestration.

---

## 3. Live Deployment & Repository Links
- **Live Google Cloud Run URL (HTTPS):** `https://bias-studio-1017983721857.asia-northeast3.run.app`
- **Instant Pre-Built Demo Session (`/demo/default`):** `https://bias-studio-1017983721857.asia-northeast3.run.app/demo/default`
- **Interactive 1:1 Study Room (`/study/default`):** `https://bias-studio-1017983721857.asia-northeast3.run.app/study/default`
- **OpenSea × Cyworld Minihompy Marketplace (`/marketplace`):** `https://bias-studio-1017983721857.asia-northeast3.run.app/marketplace`
- **Public GitHub Repository:** `https://github.com/raycho2023/Google-Hackathon`

---

## 4. Problem & Inspiration (Track 1: Entertainment in Korea)
Korea—and Seoul in particular—is a global powerhouse in webtoons, virtual idols, and fandom culture:
1. **Passive Loops vs. Personal Connection:** Millions of people study or code to 24/7 lo-fi streams, yet the character on screen is static, generic, and someone else's creation.
2. **Text-Only Character Chat vs. Living Broadcast Studio:** Paid character chat services on Korean webtoon platforms prove massive demand for 1:1 companionship, while the revival of Korean virtual vocal engines (like *SeeU*) and AI music tools shows fans want custom voices and music—not just text bubbles.
3. **Eliminating the "AI Plastic Look":** Fans of Korean webtoons and 2D subculture reject glossy 3D/plastic AI renders. They want crisp hand-drawn ink linework, flat cel-shading, and relatable Seoul nightscapes (Han River Banpo Bridge, Seongsu-dong ateliers, Yeonnam-dong rooftops, Jeju workation stays).

**Bias Studio** bridges all three: it acts as a personal **Showrunner (`gemini-4-argon`)** that interviews your taste, casts a 100% original 2D hand-drawn companion, verifies its own multimodal output across 8 traits, and opens an interactive late-night radio studio set across 10 iconic Korean locations.

---

## 5. How We Built It — Full Google DeepMind Multimodal Stack (`google-genai >= 2.30.1` Interactions API)

Every model call uses the official **`client.interactions.create`** API with strict Pydantic JSON schemas and full session trace logging:

| Studio Role | Google Model ID | How It Powers Bias Studio |
| :--- | :--- | :--- |
| **Showrunner, Taste Interviewer & Multimodal Critic** | **`gemini-4-argon`** (`thinking_level="low"` / `"high"`) | Conducts the 6Q/10Q/20Q adaptive taste interview across 5 axes, enforces IP/safety guardrails + 135-character originality check, authors the character & radio spec, runs **closed-loop multimodal verification** on generated images/voice/music/video, and drives the 1:1 Persona Learning Chat with proactive reverse-proposals. |
| **2K 3-View Character Sheet & 10 Korean Nightscapes** | **`gemini-nano-banana-2.1`** | Renders the 3-view character turnaround sheet (`sheet.png`) and 2K 16:9 studio scene (`scene.png`), plus multi-turn reference-locked live transformations behind the Virtual Studio Door (changing hairstyles, outfits, or switching between 10 Korean landmarks while preserving character identity). |
| **Fast 1K Visual A/B Taste Calibration** | **`gemini-3.1-flash-lite-image`** | Generates real-time Option A vs. Option B visual cards on Turn 3 of the survey to calibrate framing and color temperature. |
| **Bespoke Voice Bank Design & Broadcast TTS** | **`gemini-3.8-flash-tts`** + **`client.voices.create`** | Designs a custom character voice bank (`voice_id`) from a natural-language persona description and synthesizes the DJ opening intro (`dj.wav`), whisper check-in (`asmr.wav`), live 1:1 chat voice replies, and vocal melody hooks. |
| **30-Second Instrumental Lo-Fi & Backing Track** | **`lyria-3-clip-preview`** (`Lyria 3`) | Composes a 30-second instrumental lo-fi hip-hop stream loop (`loop.wav`) and custom backing tracks inside the Sound & Vocal Studio. |
| **Animated Broadcast Loop & Continuity Check** | **`gemini-omni-1.1-flash`** | Generates the animated character loop (`loop.mp4`) verified by `gemini-4-argon` for frame continuity, paired with a deterministic 16fps 2.5D breathing, window-rain, and cosine cross-dissolve compositor (`FFmpeg libx264`). |
| **Cloud Infrastructure & Persistence** | **Google Cloud Run + Cloud Storage** | Containerized FastAPI + FFmpeg server deployed on Cloud Run (`asia-northeast3`) with completed sessions persisted to `gs://h2gdm-hack26icn-2731-bias-studio`. |

---

## 6. Key Engineering Highlights & Open-Source Integration
1. **Closed-Loop Multimodal Verification (`verify_character_sheet`, `verify_voice`, `verify_music`, `verify_video`):**
   - `gemini-4-argon` (`thinking_level="high"`) inspects the generated `sheet.png` against all 8 visual traits. If fewer than 6/8 traits match or text/subtitles appear, it rewrites the prompt and regenerates automatically.
2. **2D Hand-Drawn Cel-Shading & Variable Ink Linework Pipeline (`anime_opensource_engine.py`):**
   - Post-processes generated frames with a Difference-of-Gaussians sepia ink edge extractor and soft cel-quantization filter to eliminate AI plastic sheen and deliver an authentic Korean webtoon aesthetic.
3. **Smooth 16fps Cosine Cross-Dissolve & Virtual Studio Door:**
   - When a user asks the companion to change hairstyle or switch the window view to **Han River Banpo Bridge, Lotte World Tower, Namsan Tower, Yeonnam-dong, Seongsu-dong, Itaewon, Jeju Island, Seoraksan Mountain Cabin, Haeundae Busan, or Jeonju Hanok Village**, the Virtual Studio Door slides shut, `gemini-nano-banana-2.1` edits the scene using `sheet.png` as a multi-turn reference, and `FFmpeg` renders a 16fps cosine cross-dissolve transition (`prev_scene.png` → `scene.png`).
4. **Open-Source Interoperability (`TavernAI / SillyTavern chara_card_v2`):**
   - Embeds Base64 `chara_card_v2` JSON metadata directly into the PNG `tEXt` chunk of `sheet.png` (`/api/session/{id}/card.png`) plus a circular 512×512 Google Account Avatar PNG (`/api/session/{id}/google-avatar`).
5. **OpenSea × Cyworld Minihompy Marketplace:**
   - Users connect their Google creator profile, publish their verified companion + BGM room to a nostalgic Korean Cyworld Minihompy card with visitor counters (`TODAY / TOTAL`), BGM preview player, and 1-Chon Pyeong (`일촌평`) guestbook comments.
