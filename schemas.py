from typing import Literal, Optional
from pydantic import BaseModel, Field


class SafetyCheckResult(BaseModel):
    allowed: bool = Field(description="False if input requests a real person, existing copyrighted character/VTuber, song cover, or underage/unsafe content.")
    reason: str = Field(description="Calm explanation if refused, or 'ok' if allowed.")
    safe_alternative_suggestion: Optional[str] = Field(
        default=None,
        description="Original archetype alternative if the user named a protected character or real person.",
    )


class QuestionTurn(BaseModel):
    question: str = Field(description="Single question under 18 words in a calm late-night radio host tone.")
    axis: Literal["visual", "personality", "voice", "music", "setting"] = Field(
        description="Which of the 5 taste axes this question probes."
    )
    ui_mode: Literal["choices", "yes_no", "this_or_that"] = Field(
        description="UI presentation mode. Use 'this_or_that' on question 3 for visual A/B comparison, otherwise 'choices' with 4 concrete options."
    )
    options: list[str] = Field(
        description="3 concrete, evocative choices plus a 4th 'No preference — surprise me' option."
    )
    option_a: Optional[str] = Field(
        default=None,
        description="Image generation prompt for Option A when ui_mode is 'this_or_that'.",
    )
    option_b: Optional[str] = Field(
        default=None,
        description="Image generation prompt for Option B when ui_mode is 'this_or_that'.",
    )
    option_a_label: Optional[str] = Field(
        default=None,
        description="Short caption for Option A image card.",
    )
    option_b_label: Optional[str] = Field(
        default=None,
        description="Short caption for Option B image card.",
    )
    uncertainty_remaining: float = Field(
        ge=0.0, le=1.0, description="Estimated remaining uncertainty from 0.0 to 1.0."
    )
    taste_meter: dict[str, float] = Field(
        description="Confidence 0.0-1.0 across axes: visual, personality, voice, music, setting."
    )
    ready_for_spec: bool = Field(
        description="True when enough signal is collected to synthesize the CharacterSpec."
    )


class TraitProvenanceItem(BaseModel):
    trait: str = Field(description="Exact checkable trait or spec attribute.")
    source_questions: list[str] = Field(
        description="Question IDs that shaped this trait, e.g. ['Q1', 'Q3']."
    )


class CharacterSpec(BaseModel):
    name: str = Field(description="Original 1-2 word character name. Must not match any existing VTuber or anime character.")
    tagline: str = Field(description="Short broadcast-style subtitle, e.g. '01:30 AM Attic Archivist'.")
    apparent_age: str = Field(description="Must be 'early 20s', 'mid 20s', or 'late 20s'.")
    archetype: str = Field(description="Concise late-night companion archetype.")
    visual_traits: list[str] = Field(
        min_length=8,
        max_length=8,
        description="Exactly 8 concrete, visually verifiable traits (hair color, hair cut, eye color, eyewear/headwear, top garment, outer layer, signature desk prop, key lighting color).",
    )
    provenance: list[TraitProvenanceItem] = Field(
        description="Links each trait back to the question numbers that inspired it."
    )
    personality_summary: str = Field(description="2-sentence persona description.")
    setting_description: str = Field(description="Late-night workspace atmosphere description.")
    voice_gender: Literal["female", "male", "neutral"] = Field(description="Voice register gender for TTS creation.")
    voice_description: str = Field(
        description="Detailed voice design prompt for gemini-3.8-flash-tts describing timbre, pacing, mic proximity, and warmth."
    )
    voice_style_dj: str = Field(description="Style annotation for the DJ intro line.")
    voice_style_asmr: str = Field(description="Style annotation for the quiet ASMR focus check-in.")
    dj_intro_script: str = Field(
        description="2-sentence spoken broadcast intro welcoming the listener to a 25-minute focus block (18-30 words)."
    )
    asmr_whisper_script: str = Field(
        description="1-2 sentence quiet, close-mic spoken encouragement for mid-session check-in (12-22 words)."
    )
    music_genre: str = Field(description="Original instrumental subgenre, e.g. 'Late-night Rhodes lo-fi jazz'.")
    music_bpm: int = Field(ge=55, le=130, description="Target tempo in BPM.")
    music_key: str = Field(description="Musical key, e.g. 'F minor' or 'D dorian'.")
    music_instruments: list[str] = Field(description="3-5 lead and rhythm instruments.")
    music_prompt: str = Field(
        description="Detailed prompt for lyria-3-clip-preview specifying instrumental-only, genre, BPM, key, instruments, and late-night mood."
    )
    sheet_prompt: str = Field(
        description="Prompt for gemini-nano-banana-2.1 to draw a 16:9 2K 3-view character reference sheet (full-body front, 3/4 view, side profile + expression inset) on a clean dark neutral studio backdrop."
    )
    scene_prompt: str = Field(
        description="Prompt for gemini-nano-banana-2.1 to draw a 16:9 2K late-night work scene featuring this exact character at their desk with warm lamp light and rain window."
    )
    video_motion_prompt: str = Field(
        description="Prompt for gemini-omni-1.1-flash to animate subtle looping motion: rain streaks on window, warm lamp flicker, slow breathing, subtle page turn or pen movement."
    )


class TraitCheckItem(BaseModel):
    trait: str
    present: bool
    evidence: str


class SheetVerificationResult(BaseModel):
    three_views_present: bool = Field(description="True if multiple character angles/views are visible on the sheet.")
    consistent_character_across_views: bool = Field(description="True if all views depict the same character.")
    trait_checks: list[TraitCheckItem] = Field(description="Evaluation of each of the 8 visual_traits.")
    matched_count: int = Field(description="Number of visual_traits confirmed present.")
    total_traits: int = Field(description="Total number of traits checked (8).")
    passed: bool = Field(description="True if three_views_present and matched_count >= 6.")
    edit_instruction: str = Field(
        description="If passed is False, exact instruction for gemini-nano-banana-2.1 to fix missing traits while keeping existing layout."
    )


class VoiceQualityScore(BaseModel):
    naturalness_score: int = Field(ge=1, le=5, description="1-5 score for vocal naturalness and clarity.")
    persona_match_score: int = Field(ge=1, le=5, description="1-5 score for how well the delivery fits the late-night host persona.")
    critique: str = Field(description="Brief assessment of pacing, warmth, and clarity.")
    revised_style_hint: str = Field(description="Adjusted style instruction if retry is needed.")


class VoiceVerificationResult(BaseModel):
    clip_type: Literal["dj", "asmr"]
    transcript: str
    target_script: str
    word_overlap_ratio: float
    naturalness_score: int
    persona_match_score: int
    passed: bool
    critique: str
    revised_style_hint: str
    round_num: int = 1


class MusicVerificationResult(BaseModel):
    is_instrumental: bool = Field(description="True if no sung vocals or lyrics are present.")
    vocals_detected: bool = Field(description="True if distracting vocals are heard.")
    estimated_bpm: int = Field(description="Estimated tempo in BPM.")
    detected_genre: str = Field(description="Perceived genre and instrumentation.")
    mood_match_score: int = Field(ge=1, le=5, description="1-5 score for late-night study suitability and spec match.")
    passed: bool = Field(description="True if is_instrumental is True and mood_match_score >= 3.")
    critique: str = Field(description="Short technical listener note.")
    revised_music_prompt: str = Field(description="Adjusted Lyria prompt if retry is needed.")
    round_num: int = 1


class VideoVerificationResult(BaseModel):
    character_consistency_score: int = Field(ge=1, le=5, description="1-5 score comparing video character against the verified sheet.")
    setting_match_score: int = Field(ge=1, le=5, description="1-5 score for late-night studio atmosphere.")
    motion_quality_score: int = Field(ge=1, le=5, description="1-5 score for calm, non-distorted looping motion.")
    distortion_free: bool = Field(description="True if face and hands remain coherent without severe morphing.")
    passed: bool = Field(description="True if character_consistency_score >= 3, motion_quality_score >= 3, and distortion_free is True.")
    observations: str = Field(description="What gemini-4-argon observed while watching the generated video.")
    revised_motion_prompt: str = Field(description="Adjusted motion prompt if retry is needed.")
    round_num: int = 1


class TraceEntry(BaseModel):
    step: str
    model: str
    latency_ms: int
    summary: str
    timestamp: str
    status: Literal["ok", "retry", "fallback", "refused"] = "ok"


class AnswerSubmission(BaseModel):
    answer: str
    free_text: Optional[str] = None
