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
    option_a_url: Optional[str] = Field(
        default=None,
        description="Dynamic visual world-cup image URL for Option A.",
    )
    option_b_url: Optional[str] = Field(
        default=None,
        description="Dynamic visual world-cup image URL for Option B.",
    )
    stage_id: Optional[str] = Field(
        default=None,
        description="Stage ID: stage_1_design (Q1-Q10), stage_2_personality (Q11-Q13), stage_3_atmosphere (Q14-Q18).",
    )
    stage_title: Optional[str] = Field(
        default=None,
        description="Toss-style stage badge title.",
    )
    stage_intro_banner: Optional[str] = Field(
        default=None,
        description="Toss-style conversational intro banner shown when entering a stage.",
    )
    interstitial_after: bool = Field(
        default=False,
        description="Whether to show a Toss-style background generation interstitial after this question.",
    )
    interstitial_title: Optional[str] = Field(default=None)
    interstitial_subtitle: Optional[str] = Field(default=None)
    interstitial_duration_sec: int = Field(default=0)
    batch_stage: Optional[str] = Field(
        default=None,
        description="Batch pre-generation stage triggered on answer submission (batch_q5, batch_q10, batch_q13).",
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
    mbti: str = Field(default="INFJ", description="Character's MBTI personality type, e.g. INFJ, ENFP, INTJ.")
    signature_drink: str = Field(default="핸드드립 에티오피아 커피 & 따뜻한 캐모마일", description="Character's favorite late-night desk beverage.")
    secret_habit: str = Field(default="집중할 때 만년필 캡을 72 BPM 박자에 맞춰 살짝 톡톡 두드리는 버릇", description="Endearing subtle habit visible during late-night study sessions.")
    first_greeting_narration: str = Field(
        default="*조용히 황동 스탠드 조명을 켜고, 김이 모락모락 나는 머그컵을 당신의 책상 한편에 놓아주며 다정하게 눈을 맞춘다.*",
        description="Zeta/Caveduck style opening scene action narration.",
    )
    first_greeting_line: str = Field(
        default="왔어요? 오늘 밤도 당신 옆자리 비워뒀어요. 급하게 생각하지 말고, 나랑 천천히 한 페이지씩 시작해 볼까요?",
        description="Opening spoken line when the user enters the focus room.",
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


class ChatSubmission(BaseModel):
    message: str
    lang: Literal["en", "ko"] = "ko"
    synthesize_voice: bool = False
    user_nickname: Optional[str] = "메이트"
    relationship_preset: Optional[str] = "다정한 작업실 선배"
    episode_context: Optional[str] = None
    episode_scenario: Optional[str] = None


class CharacterChatReply(BaseModel):
    reply: str = Field(description="1-2 sentence in-character late-night companion spoken dialogue in the requested language.")
    narration: str = Field(
        default="*따뜻한 스탠드 불빛 아래에서 조용히 눈을 맞추며 다정하게 미소 짓는다.*",
        description="Zeta/Caveduck style novelistic action & expression narration enclosed in *asterisks* in the requested language.",
    )
    inner_thought: str = Field(
        default="(오늘 밤도 포기하지 않고 책상 앞에 앉아 있는 모습이 참 든든하고 좋다)",
        description="Caveduck/LoveyDovey style secret inner thought [속마음] of the character in parentheses.",
    )
    emotion_state: Literal["calm_focus", "warm_smile", "shy_flutter", "cheering", "sleepy_night"] = Field(
        default="warm_smile",
        description="Current visual emotion state of the character: calm_focus, warm_smile, shy_flutter, cheering, or sleepy_night.",
    )
    affection_delta: int = Field(
        default=8,
        ge=1,
        le=20,
        description="Affection XP increase from this interaction (1 to 20).",
    )
    suggested_replies: list[str] = Field(
        default_factory=lambda: [
            "고마워, 네가 옆에 있어서 훨씬 집중이 잘 돼!",
            "지금 너는 무슨 작업 하고 있는지 궁금해",
            "우리 5분만 커피 마시면서 수다 떨까?",
        ],
        description="3 contextual clickable suggested user replies for the next turn (Zeta / LoveyDovey style).",
    )
    spoken_line_en: str = Field(
        description="Short 1-sentence spoken version in natural English (10-20 words) for TTS voice synthesis acknowledging the user or stepping behind the studio door."
    )
    mood_cue: str = Field(description="Short atmospheric stage direction, e.g. 'steps behind the studio fitting door' or 'adjusts brass desk lamp'.")
    action_type: Literal["none", "change_style", "change_background", "change_voice", "change_music"] = Field(
        default="none",
        description="Set to 'change_style' if user asks to change hairstyle/outfit/glasses, 'change_background' if user asks to change room/background/lighting, 'change_voice' if user asks for a quieter/different voice tone, 'change_music' if user asks to change the BGM/music, or 'none' for regular conversation.",
    )
    updated_prompt: Optional[str] = Field(
        default=None,
        description="When action_type != 'none', the detailed prompt to apply the requested visual/scene/voice/music change while keeping character identity.",
    )
    updated_label: Optional[str] = Field(
        default=None,
        description="Short 2-5 word badge describing the new style, background, voice, or music.",
    )
    learned_preference: Optional[str] = Field(
        default=None,
        description="A short 4-10 word note summarizing what the character agent learned about the user's mood or taste from this message.",
    )
    proactive_suggestion_type: Literal["none", "change_music", "change_background", "change_style"] = Field(
        default="none",
        description="When action_type == 'none', the persona agent can proactively suggest a music, background, or style change that fits the user's mood.",
    )
    proactive_suggestion_label: Optional[str] = Field(
        default=None,
        description="1-sentence proactive suggestion from the character in the user's language (e.g. '비 소리에 어울리는 68 BPM 어쿠스틱 피아노로 바꿔볼까요?').",
    )
    proactive_suggestion_prompt: Optional[str] = Field(
        default=None,
        description="English generation prompt to execute if the user clicks Accept on the character's proactive suggestion.",
    )


class PersonaUpdateSubmission(BaseModel):
    user_nickname: str = "메이트"
    relationship_preset: str = "다정한 작업실 선배"
    episode_context: Optional[str] = None


class DiaryRequestSubmission(BaseModel):
    completed_tasks: list[str] = Field(default_factory=list)
    completed_todos: list[str] = Field(default_factory=list)
    focus_minutes: int = 25
    lang: Literal["en", "ko"] = "ko"


class TransformSubmission(BaseModel):
    action_type: Literal["change_style", "change_background", "change_voice", "change_music"]
    updated_prompt: str
    updated_label: Optional[str] = None
    lang: Literal["en", "ko"] = "en"


class VocalStudioSubmission(BaseModel):
    script: str
    style_hint: str = "Calm late-night FM radio host, warm close-mic presence"
    music_prompt: Optional[str] = None


class MarketplacePublishSubmission(BaseModel):
    session_id: str = "default"
    creator_name: str = "Hackathon Builder"
    creator_email: str = "builder@workspace.google.com"
    minihompy_title: Optional[str] = None
    status_message: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class MarketplaceCommentSubmission(BaseModel):
    author_name: str = "Ilchon Friend"
    author_email: str = "friend@workspace.google.com"
    relation_label: str = "일촌 (Studio Friend)"
    message: str


class BatchPrewarmSubmission(BaseModel):
    stage: str = Field(
        default="batch_q10",
        description="Batch stage identifier: batch_q5, batch_q10, or batch_q13",
    )


class GoogleProfileSyncSubmission(BaseModel):
    name: str
    email: str
    picture_url: Optional[str] = None
    workspace_domain: Optional[str] = "google.com"




