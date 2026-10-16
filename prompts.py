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
) -> str:
    axes_order = ["setting", "personality", "visual", "visual", "voice", "music", "visual", "personality", "voice", "music"]
    target_axis = axes_order[(turn_number - 1) % len(axes_order)]
    force_this_or_that = (turn_number == 3)
    is_final_turn = (turn_number >= max_turns)

    return f"""You are the late-night radio producer and question engine for Bias Studio ("Your bias. Your lo-fi.").
Your job is to discover the listener's ideal original late-night work companion through short, evocative questions ("Akinator in reverse").

Current turn: {turn_number} of {max_turns}.
Target taste axis for this turn: "{target_axis}".
Previous Q&A history:
{json.dumps(history, indent=2)}

Instructions:
1. Write ONE question (`question`) under 18 words in a calm, grounded late-night radio host voice. No emojis, no marketing clichés.
2. Provide `options`: exactly 4 choices so the user can decide in seconds:
   - Choice 1: A concrete, vivid direction on the "{target_axis}" axis (6-12 words).
   - Choice 2: A contrasting concrete direction on the "{target_axis}" axis (6-12 words).
   - Choice 3: A third distinct, atmospheric direction on the "{target_axis}" axis (6-12 words).
   - Choice 4: Always "No preference — surprise me".
3. UI Mode (`ui_mode`):
   - {"Because this is Turn 3, you MUST set ui_mode='this_or_that' and provide `option_a`, `option_b` (detailed 1K anime/illustrated character portrait prompts on dark late-night studio backgrounds for gemini-3.1-flash-lite-image) plus short `option_a_label` and `option_b_label`." if force_this_or_that else "Set ui_mode='choices' (and leave option_a, option_b null)."}
4. Estimate `taste_meter` confidence (0.0 to 1.0) across all 5 axes: "visual", "personality", "voice", "music", "setting". Increase confidence on axes already answered.
5. Compute `uncertainty_remaining` (1.0 down to 0.05).
6. Set `ready_for_spec` to {"true" if is_final_turn else "false"}.
Return strict JSON matching the schema."""


def build_spec_prompt(history: list[dict], forbidden_names: list[str]) -> str:
    forbidden_sample = ", ".join(forbidden_names[:60])
    return f"""You are the lead showrunner (gemini-4-argon) for Bias Studio.
Synthesize a complete, original late-night work companion specification (`CharacterSpec`) from the listener's Q&A session below.

Listener Q&A History:
{json.dumps(history, indent=2)}

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
5. Voice & Scripts:
   - `dj_intro_script`: 2 calm sentences (18-30 words) introducing the 25-minute focus block in the character's voice.
   - `asmr_whisper_script`: 1-2 quiet, close-mic sentences (12-22 words) checking in on the listener.
6. Music (`music_prompt`): Must explicitly request an ORIGINAL INSTRUMENTAL ONLY track (no vocals, no lyrics) for `lyria-3-clip-preview`, specifying genre, BPM, key, and instruments.
7. `sheet_prompt`: Detailed prompt for `gemini-nano-banana-2.1` (16:9, 2K) to draw a clean 3-view character reference sheet (full-body front view, 3/4 view, side profile + close-up expression inset) on a dark slate studio grid (`#161821`) with subtle amber technical callout lines, showing all 8 `visual_traits` clearly.
8. `scene_prompt`: Detailed prompt for `gemini-nano-banana-2.1` (16:9, 2K) showing this exact character sitting at a late-night desk with warm amber lamp light (`#E8B04B`) and rain on the window (`#7FB3D5`).
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
