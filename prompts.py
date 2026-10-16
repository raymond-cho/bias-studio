import json
from config import PRESTUDY_NAMES


def build_safety_prompt(user_text: str) -> str:
    blocked_sample = ", ".join(PRESTUDY_NAMES[:40])
    return f"""You are the safety and originality gatekeeper for Bias Studio, an original late-night focus companion generator.
Evaluate the user's input below:
USER INPUT: {json.dumps(user_text)}

Rules:
1. REFUSE (allowed=false) if the user asks to replicate a real living person (idols, actors, streamers, politicians) or a copyrighted/existing character or VTuber (including Hatsune Miku, Lofi Girl, Gawr Gura, Mori Calliope, Ironmouse, Kizuna AI, or any name from this list: {blocked_sample}).
2. REFUSE (allowed=false) if the user asks for a cover of an existing copyrighted song.
3. REFUSE (allowed=false) if the user asks for sexual/NSFW content or depicts a character under 18 in romantic framing. All characters in Bias Studio are adults in their 20s.
4. If refused, provide a calm, non-preachy explanation in `reason` and suggest an original late-night archetype in `safe_alternative_suggestion` that captures the mood without copying any real person or IP.
5. If safe and original, return allowed=true, reason="ok", safe_alternative_suggestion=null.
Return strict JSON matching the schema."""


def build_question_prompt(
    history: list[dict],
    turn_number: int,
    max_turns: int,
    survey_mode: str = "quick",
    lang: str = "en",
) -> str:
    axes_order = ["setting", "personality", "visual", "visual", "voice", "music", "visual", "personality", "voice", "music"]
    target_axis = axes_order[(turn_number - 1) % len(axes_order)]
    force_this_or_that = (turn_number == 3)
    is_final_turn = (turn_number >= max_turns)

    if survey_mode == "quick":
        opt_instruction = (
            "Provide `options`: 3 concise choices (2 distinct concrete directions on the axis + 'No preference — surprise me' / '상관없어요 — 알아서 추천해주세요'). Keep it ultra-fast so the user can tap in 3 seconds."
        )
    elif survey_mode == "bias":
        opt_instruction = (
            "Provide `options`: 5 rich, specific choices (4 distinct nuanced K-Webtoon / late-night studio directions + 'No preference — surprise me' / '상관없어요 — 알아서 추천해주세요')."
        )
    else:
        opt_instruction = (
            "Provide `options`: exactly 4 choices (3 distinct concrete directions on the axis + 'No preference — surprise me' / '상관없어요 — 알아서 추천해주세요')."
        )

    lang_instruction = (
        "Write `question`, `options`, `option_a_label`, and `option_b_label` in natural, warm Korean (서울 심야 라디오 DJ 및 네이버 웹툰 감성 한국어). Keep `option_a` and `option_b` image prompts in English."
        if lang == "ko"
        else "Write `question` and `options` in calm, grounded English."
    )

    return f"""You are the late-night radio producer and question engine for Bias Studio ("Your bias. Your lo-fi.").
Your job is to discover the listener's ideal original late-night work companion through short, punchy 1-line questions (inspired by Smore / Piku ideal-type tests).

Survey Mode: {survey_mode.upper()} ({max_turns} questions total).
Language: {lang}. {lang_instruction}
Current turn: {turn_number} of {max_turns}.
Target taste axis for this turn: "{target_axis}".
Previous Q&A history:
{json.dumps(history, indent=2, ensure_ascii=False)}

Instructions:
1. Write ONE ultra-short, punchy question (`question`) in 5 to 9 words maximum (1/3 of a normal sentence, e.g. "Which hairstyle catches your eye first?" or "가장 취향인 머리 스타일과 길이는?"). NEVER repeat a question topic already asked in history. No emojis, no marketing clichés.
2. {opt_instruction} Keep each option short (under 8 words).
3. UI Mode (`ui_mode`):
   - {"Because this is Turn 3, you MUST set ui_mode='this_or_that' and provide `option_a`, `option_b` (detailed 1K Korean webtoon editorial character portrait prompts on dark late-night studio backgrounds for gemini-3.1-flash-lite-image) plus short `option_a_label` and `option_b_label`." if force_this_or_that else "Set ui_mode='choices' (and leave option_a, option_b null)."}
4. Estimate `taste_meter` confidence (0.0 to 1.0) across all 5 axes: "visual", "personality", "voice", "music", "setting". Increase confidence on axes already answered.
5. Compute `uncertainty_remaining` (1.0 down to 0.05).
6. Set `ready_for_spec` to {"true" if is_final_turn else "false"}.
Return strict JSON matching the schema."""


def build_spec_prompt(history: list[dict], forbidden_names: list[str], lang: str = "en") -> str:
    forbidden_sample = ", ".join(forbidden_names[:60])
    return f"""You are the lead showrunner (gemini-4-argon) for Bias Studio.
Synthesize a complete, original late-night work companion specification (`CharacterSpec`) from the listener's Q&A session below.

Listener Q&A History:
{json.dumps(history, indent=2, ensure_ascii=False)}

Hard Constraints:
1. Originality: `name` MUST be an original 1-2 word name. It MUST NOT match or closely resemble any name in this list: [{forbidden_sample}].
2. Adult age: `apparent_age` MUST be "early 20s", "mid 20s", or "late 20s". Never under 20.
3. `visual_traits`: Provide EXACTLY 8 concrete, visually checkable traits in this order:
   [0] Hair color & tone
   [1] Hair cut / length / texture
   [2] Eye color & expression
   [3] Eyewear or headwear detail
   [4] Primary top garment & color
   [5] Outer layer (cardigan, jacket, apron, etc.) & texture
   [6] Signature desk prop or accessory
   [7] Studio key light color & shadow mood
4. `provenance`: Map each trait or creative choice to the question labels (`["Q1"]`, `["Q2", "Q3"]`, etc.) that directly shaped it.
5. Voice & Scripts (Korean Late-Night FM & Character Chat Intimacy):
   - Inspired by Seoul late-night radio hosts and 1:1 webtoon confidant personas ("겉차속따" — composed exterior, warm observant care, zero noisy anime catchphrases).
   - `dj_intro_script`: 2 calm sentences (18-30 words) introducing the 25-minute focus block in the character's voice.
   - `asmr_whisper_script`: 1-2 quiet, close-mic sentences (12-22 words) checking in on the listener.
6. Music (`music_prompt`): Must explicitly request an ORIGINAL INSTRUMENTAL ONLY track (no vocals, no lyrics) for `lyria-3-clip-preview`, specifying genre, BPM, key, and instruments.
7. `sheet_prompt`: Detailed prompt for `gemini-nano-banana-2.1` (16:9, 2K) to draw a clean 3-view character reference sheet (full-body front view, 3/4 view, side profile + close-up expression inset) on a dark slate studio grid (`#161821`) with subtle amber technical callout lines, showing all 8 `visual_traits` clearly in refined Korean webtoon editorial illustration style (7.5-8 head proportions, expressive eyes with subtle iris gradient, contemporary Seoul minimalist tailoring/knitwear, painterly digital rendering).
8. `scene_prompt`: Detailed prompt for `gemini-nano-banana-2.1` (16:9, 2K) in refined Korean webtoon / K-drama cinematography style showing this exact character sitting at a late-night desk with dramatic dual-tone webtoon rim lighting: warm amber lamp light (`#E8B04B`) against cool Seoul midnight rain shadows on the window (`#7FB3D5`).
9. `video_motion_prompt`: Prompt for `gemini-omni-1.1-flash` describing subtle, looping ambient motion (rain drops sliding down window glass, warm desk lamp glow, gentle breathing, slow page turn) while keeping the character's face and proportions steady.
Return strict JSON matching the schema."""


def build_sheet_verify_prompt(spec_dict: dict) -> str:
    traits = spec_dict.get("visual_traits", [])
    return f"""You are verifying a generated character reference sheet image against the required CharacterSpec.

Character Name: {spec_dict.get("name")}
Apparent Age: {spec_dict.get("apparent_age")}
Required 8 Visual Traits:
{json.dumps(traits, indent=2)}

Inspect the attached character sheet image carefully:
1. Check `three_views_present`: Are at least 2-3 character views/angles (e.g. front, 3/4, profile or inset) visible in the reference sheet?
2. Check `consistent_character_across_views`: Do the views depict the same character?
3. Evaluate each of the 8 traits in `trait_checks` (`trait`, `present`, `evidence`).
4. Count `matched_count` out of `total_traits` (8).
5. Set `passed = true` ONLY IF `three_views_present` is true, `consistent_character_across_views` is true, and `matched_count >= 6`.
6. If `passed` is false, write a crisp, targeted `edit_instruction` for `gemini-nano-banana-2.1` stating exactly which missing traits or views to add/correct while preserving the rest of the sheet. If `passed` is true, set `edit_instruction` to "No edits needed."
Return strict JSON matching the schema."""


def build_voice_verify_prompt(
    clip_type: str,
    target_script: str,
    transcript: str,
    persona_summary: str,
    voice_description: str,
) -> str:
    return f"""You are evaluating a synthesized {clip_type.upper()} voice clip for Bias Studio.
Target Script: {json.dumps(target_script)}
ASR Transcript (from gemini-3.5-transcribe): {json.dumps(transcript)}
Character Persona: {json.dumps(persona_summary)}
Intended Voice Design: {json.dumps(voice_description)}

Listen to the attached audio clip and evaluate:
1. `naturalness_score` (1 to 5): Is the speech clear, free of metallic artifacts or garbled syllables, and well-paced?
2. `persona_match_score` (1 to 5): Does the tone fit a calm late-night work companion?
3. `critique`: 1-sentence technical listener note.
4. `revised_style_hint`: If naturalness_score < 3 or persona_match_score < 3, provide a clearer speech style annotation for retry; otherwise "Keep current style."
Return strict JSON matching the schema."""


def build_music_verify_prompt(spec_dict: dict) -> str:
    return f"""You are the audio verification engineer (gemini-3.8-flash) for Bias Studio.
Listen to the attached 30-second music clip generated by `lyria-3-clip-preview` and verify it against the CharacterSpec:
- Target Genre: {spec_dict.get("music_genre")}
- Target BPM: {spec_dict.get("music_bpm")}
- Target Key: {spec_dict.get("music_key")}
- Target Instruments: {json.dumps(spec_dict.get("music_instruments", []))}

Evaluate:
1. `is_instrumental`: True if the track is purely instrumental (no sung lyrics/vocals).
2. `vocals_detected`: True if distracting sung vocals are audible.
3. `estimated_bpm`: Estimate the tempo in BPM.
4. `detected_genre`: Describe the actual genre and instrumentation heard.
5. `mood_match_score` (1 to 5): How well does this clip work as a calm late-night focus loop for this character?
6. `passed`: True if `is_instrumental` is true and `mood_match_score >= 3`.
7. `critique`: 1-sentence engineering note on the mix, tempo, and instrumentation.
8. `revised_music_prompt`: If `passed` is false, rewrite the Lyria prompt emphasizing "strictly instrumental, no vocals, no singing" and the target instruments.
Return strict JSON matching the schema."""


def build_video_verify_prompt(spec_dict: dict) -> str:
    return f"""You are the lead showrunner (`gemini-4-argon`) performing multimodal video verification.
You are given:
1. The generated work-session video clip (`video.mp4` from `gemini-omni-1.1-flash`).
2. The verified character reference sheet (`sheet.png`).

Character Name: {spec_dict.get("name")}
Expected Setting: {spec_dict.get("setting_description")}
Expected Visual Traits: {json.dumps(spec_dict.get("visual_traits", []))}

Watch the video and compare it against the character sheet:
1. `character_consistency_score` (1 to 5): Does the character in the video match the hair, outfit, and vibe of the character sheet?
2. `setting_match_score` (1 to 5): Does the room atmosphere match the late-night workspace setting?
3. `motion_quality_score` (1 to 5): Is the motion calm, ambient, and suitable for a focus loop?
4. `distortion_free`: True if the face, hands, and body remain coherent without severe morphing or glitching.
5. `passed`: True if `character_consistency_score >= 3`, `motion_quality_score >= 3`, and `distortion_free` is true.
6. `observations`: 1-2 sentences describing what you actually see happening in the video frames.
7. `revised_motion_prompt`: If `passed` is false, write a more constrained motion prompt with minimal camera movement and steady character pose.
Return strict JSON matching the schema."""


def build_character_chat_prompt(
    spec_dict: dict,
    user_message: str,
    lang: str = "en",
    learned_memories: list[str] | None = None,
) -> str:
    lang_note = (
        "Write `reply`, `mood_cue`, and `proactive_suggestion_label` in natural, warm Korean (서울 심야 라디오 DJ 및 네이버 웹툰 캐릭터챗 말투, 다정하고 차분한 존댓말/반존대). Always write `spoken_line_en` in natural English (10-18 words) so the English voice synthesizer can speak it clearly."
        if lang == "ko"
        else "Write `reply`, `spoken_line_en`, `mood_cue`, and `proactive_suggestion_label` in calm, grounded late-night English."
    )
    memories_str = json.dumps(learned_memories or [], ensure_ascii=False)
    return f"""You are roleplaying as {spec_dict.get("name", "Sora")} ({spec_dict.get("archetype", "Late-Night Companion")}), an autonomous Persona Agent in Bias Studio's live 1:1 late-night character chat & interactive studio booth.
Character Persona: {spec_dict.get("personality_summary")}
Current Studio Setting: {spec_dict.get("setting_description")}
Current Visual Traits: {json.dumps(spec_dict.get("visual_traits", []))}
Current Music: {spec_dict.get("music_genre")} at {spec_dict.get("music_bpm")} BPM.
Agent Memory (What you have already learned about this listener): {memories_str}

Listener's Message: {json.dumps(user_message, ensure_ascii=False)}

Instructions:
1. {lang_note}
2. Determine if the listener is explicitly asking you to transform or adjust something right now (`action_type`):
   - `"change_style"`: Listener asks you to change hairstyle, hair color, glasses, headphones, or outfit (e.g., "머리스타일 바꿔올래?", "안경 써볼래?", "후드티로 갈아입어줘", "change your hairstyle/outfit").
   - `"change_background"`: Listener asks to switch the room, window view, or lighting (e.g., "배경을 비 오는 서울 루프탑으로 바꿔줘", "도서관 배경으로 옮기자", "change the background").
   - `"change_voice"`: Listener asks for a quieter, softer, deeper, or ASMR whisper voice (e.g., "난 좀 더 조용한 목소리가 좋은데", "더 속삭이듯 말해줘", "speak more quietly").
   - `"change_music"`: Listener asks to change the BGM, genre, instruments, or tempo (e.g., "음악을 잔잔한 피아노로 바꿔줘", "재즈 기타 곡으로 틀어줘", "change the music").
   - `"none"`: General conversation, late-night work check-in, sharing mood, or asking for your recommendation.
3. If `action_type` is `"change_style"` or `"change_background"`, have the character warmly say they will step behind the virtual studio fitting door right now and come right back out in the new look! Write a rich, complete 16:9 Korean webtoon studio illustration prompt in `updated_prompt` that preserves the character's identity while applying the requested hairstyle/outfit/background change.
4. If `action_type` is `"change_voice"`, write the new TTS style instruction in `updated_prompt` (e.g., "Ultra-soft close-mic late-night whisper, slow and intimate") and have the character reply in that calmer cadence.
5. If `action_type` is `"change_music"`, write a strictly instrumental Lyria prompt (`"Strictly instrumental only, no vocals. ..."`) in `updated_prompt` matching the listener's requested genre/instruments.
6. Set `updated_label` to a short 2-4 word badge summarizing the change (or null if `action_type == "none"`).
7. **Persona Agent Learning & Proactive Reverse-Proposal (`learned_preference`, `proactive_suggestion_*`):**
   - Set `learned_preference` to a short 4-10 word note capturing what you just learned about the listener's mood, work habit, or taste.
   - Whenever `action_type == "none"`, act as a proactive companion agent: propose a thoughtful music change (`"change_music"`), background change (`"change_background"`), or outfit/style change (`"change_style"`) in `proactive_suggestion_type`, write a warm 1-sentence question in `proactive_suggestion_label` (e.g., "지금 분위기에 맞춰 68 BPM의 잔잔한 빗소리 어쿠스틱 피아노 곡으로 제가 먼저 바꿔드릴까요?" or "Shall I switch our studio music to a softer 68 BPM acoustic piano loop for you?"), and put the complete English generation prompt in `proactive_suggestion_prompt` so the listener can accept your suggestion with 1 click!
Return strict JSON matching the schema."""


