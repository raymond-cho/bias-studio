# Bias Studio — Design System & Copy Guide

**Tagline:** *Your bias. Your lo-fi.*

Bias Studio is a late-night broadcast booth and character studio where a listener discovers an original work companion through a short question game ("Akinator in reverse"), verifies its character sheet, voice, music, and room video through closed-loop multimodal checks, and enters a 25-minute focus room.

---

## 1. Visual Direction & Mood

- **Reference atmosphere:** Rain on a studio window at 01:30 AM, a single warm desk lamp on dark matte wood, analog broadcast meters, quiet late-night FM radio.
- **Anti-patterns (strictly forbidden):**
  - No purple-to-pink or neon cyan gradients.
  - No glassmorphism blurs (`backdrop-filter: blur(...)` cards with glowing borders).
  - No floating 3D blobs, sparkles, or particle confetti.
  - No generic 3-column SaaS feature grids ("Why Choose Bias Studio?").
  - No emojis anywhere in UI labels, buttons, badges, or system messages.

---

## 2. Color Palette

| Token | Hex | Role |
| :--- | :--- | :--- |
| `--bg-base` | `#0E0F14` | Primary canvas background (deep midnight slate) |
| `--bg-surface` | `#161821` | Card & studio panel surface |
| `--bg-elevated` | `#1E202B` | Hover states, active option cards, input wells |
| `--border-hairline` | `#262936` | `1px solid` structural hairlines |
| `--border-focus` | `#E8B04B` | Active selection & focus ring |
| `--accent-amber` | `#E8B04B` | Primary accent (warm desk lamp, primary CTA, active meter) |
| `--accent-amber-dim` | `rgba(232, 176, 75, 0.14)` | Subtle amber highlight fill |
| `--accent-cool` | `#7FB3D5` | Secondary accent (rainlight blue, verification info, audio wave) |
| `--text-primary` | `#ECE9E2` | Warm off-white primary text |
| `--text-secondary` | `#9A968E` | Muted warm grey for metadata, captions, and trace logs |
| `--text-dim` | `#64615A` | Disabled states and axis ticks |
| `--status-pass` | `#52B788` | Verification loop `PASS` badge |
| `--status-warn` | `#E8B04B` | Verification retry / `UNVERIFIED` fallback badge |
| `--status-fail` | `#D96B6B` | Refusal / error state |

---

## 3. Typography

- **Display / Character Names & Headings:** `'Instrument Serif'`, Georgia, serif — used for the studio masthead, character name, question prompt headline, and focus timer display.
- **UI / Controls / Body:** `'Inter Tight'`, -apple-system, BlinkMacSystemFont, sans-serif — clean, compact, high-legibility broadcast controls.
- **Monospace / Session Trace & Verification Evidence:** `'JetBrains Mono'`, `'SF Mono'`, monospace — used for `latency_ms`, model IDs, BPM, audio duration, and verification scores.

---

## 4. Layout & Spatial Rules

1. **Question Engine View:**
   - One focal card on screen at a time (`max-width: 680px`), centered in the studio frame with generous dark breathing room.
   - Top bar shows only the studio wordmark, question progress (`Question 03 / 06`), a subtle Quick (6Q) / Full (10Q) mode switch, and a toggle for the live Session Trace drawer.
   - Question cards support three tactile response modes:
     - **3-4 Concrete Choices + No Preference:** Crisp horizontal option rows with keyboard shortcuts (`1`-`4`) so the user can shape a character concept in under 60 seconds.
     - **Yes / No / Surprise Me:** Direct binary + wildcard bar.
     - **This or That (Visual Comparison):** Two 1K mood images generated live by `gemini-3.1-flash-lite-image` side by side (`A` vs `B`) with a "Neither — go darker / softer" escape hatch.
   - Below the card: a minimal horizontal **Taste Meter** strip showing the 5 axes (`Visual`, `Personality`, `Voice`, `Music`, `Setting`) warming up in amber as certainty grows.

2. **Studio Pipeline & Verification View:**
   - Structured as an engineering broadcast rack:
     - **Character Spec & Provenance:** Every trait has a subtle source pill (`from Q1, Q3`) linking the spec directly back to the listener's answers.
     - **4 Explicit Verification Modules:**
       1. *Character Sheet (`gemini-nano-banana-2.1` -> verified by `gemini-4-argon`)*
       2. *DJ & ASMR Voice (`gemini-3.8-flash-tts` -> transcribed by `gemini-3.5-transcribe` + scored by `gemini-3.8-flash`)*
       3. *Original Instrumental (`lyria-3-clip-preview` -> verified by `gemini-3.8-flash`)*
       4. *Late-Night Work Video (`gemini-omni-1.1-flash` -> watched & verified by `gemini-4-argon`)*
     - Each module displays its round count (`Round 1/3`), model pair, latency, raw verification metrics, and a `PASS` or `UNVERIFIED` badge.

3. **"Work with `<Name>`" Focus Room (`/study/<id>`):**
   - Full-viewport 16:9 stage with the verified looping video (or animated CSS rain + warm desk lamp scene fallback if video is unverified/timed out), subtle film grain, and warm vignette.
   - Bottom broadcast console:
     - `25:00` Pomodoro focus clock (`Start`, `Pause`, `Reset`).
     - Audio deck: plays the DJ intro once, crossfades into the looping original instrumental track, and offers a `Play ASMR Check-in` button for periodic spoken encouragement.
     - Export buttons: `Download Study MP4` (`study_with_<name>.mp4`) and `Download Character Kit (.zip)` (`chara_card_v2` spec).

---

## 5. Copywriting & Voice Rules

- **Voice:** Calm late-night FM radio producer. Direct, grounded, unhurried.
- **Plain-English Loading States:**
  - *Good:* `"Drawing the 3-view character sheet..."`, `"Checking sheet against your 8 traits (Round 1/3)..."`, `"Listening back with gemini-3.5-transcribe to check word accuracy..."`
  - *Forbidden:* `" Conjuring AI magic..."`, `"Unleashing neural creativity..."`
- **Banned Marketing Words (Never appear in UI or README):**
  - `unleash`, `elevate`, `seamless`, `revolutionize`, `next-gen`, `powered by AI`, `magic`, `journey`, `dive in`, `supercharge`, `game-changing`, `craft your dream`.
