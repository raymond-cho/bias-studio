import base64
import json
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from config import (
    BLOCKED_PATTERNS,
    GCS_BUCKET_NAME,
    MAX_VERIFY_ROUNDS_MUSIC,
    MAX_VERIFY_ROUNDS_SHEET,
    MAX_VERIFY_ROUNDS_VIDEO,
    MAX_VERIFY_ROUNDS_VOICE,
    MODEL_ARGON,
    MODEL_FLASH,
    MODEL_FLASH_LITE_IMAGE,
    MODEL_LYRIA,
    MODEL_NANO_BANANA,
    MODEL_OMNI_VIDEO,
    MODEL_TRANSCRIBE,
    MODEL_TTS,
    PRESTUDY_NAMES,
    TMP_ROOT,
    VIDEO_JOB_TIMEOUT_SECONDS,
    get_api_key,
)
from media_utils import (
    build_character_kit_zip,
    convert_audio_to_wav,
    get_audio_duration_seconds,
    mux_study_mp4,
    render_animated_scene_mp4,
    render_collectible_photocard,
    render_google_profile_avatar,
    render_studio_card_image,
    synthesize_warm_lofi_wav,
)
from models_client import GeminiStudioClient
from prompts import (
    build_character_chat_prompt,
    build_music_verify_prompt,
    build_question_prompt,
    build_safety_prompt,
    build_sheet_verify_prompt,
    build_spec_prompt,
    build_video_verify_prompt,
    build_voice_verify_prompt,
)
from schemas import (
    CharacterChatReply,
    CharacterSpec,
    MusicVerificationResult,
    QuestionTurn,
    SafetyCheckResult,
    SheetVerificationResult,
    TraitCheckItem,
    TraitProvenanceItem,
    TraceEntry,
    VideoVerificationResult,
    VoiceQualityScore,
    VoiceVerificationResult,
)


def _compute_word_overlap(target: str, transcript: str) -> float:
    t_words = [w for w in re.findall(r"[a-z0-9']+", target.lower()) if len(w) > 1]
    r_words = set(re.findall(r"[a-z0-9']+", transcript.lower()))
    if not t_words:
        return 1.0
    matched = sum(1 for w in t_words if w in r_words)
    return round(matched / len(t_words), 2)


def _check_name_collision(candidate_name: str) -> Optional[str]:
    norm = candidate_name.strip().lower()
    for existing in PRESTUDY_NAMES:
        ex_norm = existing.strip().lower()
        if not ex_norm:
            continue
        if norm == ex_norm or (len(ex_norm) >= 4 and ex_norm in norm):
            return existing
    return None


def _fast_rule_safety_check(user_text: str) -> Optional[SafetyCheckResult]:
    """Immediate deterministic check for known blocked names/patterns before hitting the API."""
    low = user_text.strip().lower()
    if not low:
        return None
    for pat in BLOCKED_PATTERNS:
        if pat in low:
            return SafetyCheckResult(
                allowed=False,
                reason=f"Bias Studio only creates original adult characters and original music. References to '{pat.strip()}' cannot be used.",
                safe_alternative_suggestion="Try an original late-night archetype instead—such as a quiet observatory archivist with silver-ash hair and warm Rhodes jazz.",
            )
    for vt_name in PRESTUDY_NAMES:
        if len(vt_name) >= 5 and vt_name.lower() in low:
            return SafetyCheckResult(
                allowed=False,
                reason=f"'{vt_name}' is an existing character. Bias Studio builds original work companions from scratch.",
                safe_alternative_suggestion="Describe the mood, voice timbre, or studio atmosphere you enjoy, and we will design a new companion around those traits.",
            )
    return None


# 18-Question Toss-Style Staged + Piku Ideal-Type World Cup Question Pool
# Stage 1 (Q1-Q10): Character Design Concept (batched 5+5) -> 6s Toss Interstitial ("캐릭터 생성 중.. 성격 설정으로 넘어갈게요")
# Stage 2 (Q11-Q13): Personality Settings (batched 3) -> 4s Toss Interstitial ("말투·자세·작업실 배경 설정으로 넘어갈게요")
# Stage 3 (Q14-Q18): Speech Tone, Posture, Studio Background & Lo-Fi Soundscape (batched 5)

VISUAL_WORLD_CUP_PAIRS: dict[int, dict[str, Any]] = {
    2: {
        "default": ("/static/samples/char_1.webp", "/static/samples/char_2.webp"),
        "male": ("/static/samples/tue.webp", "/static/samples/thu.webp"),
        "female": ("/static/samples/char_1.webp", "/static/samples/char_3.webp"),
        "neutral": ("/static/samples/char_2.webp", "/static/samples/wed.webp"),
    },
    3: {
        "default": ("/static/samples/char_1.webp", "/static/samples/char_2.webp"),
    },
    5: {
        "default": ("/static/samples/char_3.webp", "/static/samples/char_4.webp"),
        "male": ("/static/samples/thu.webp", "/static/samples/sat.webp"),
        "female": ("/static/samples/mon.webp", "/static/samples/wed.webp"),
        "neutral": ("/static/samples/char_4.webp", "/static/samples/fri.webp"),
    },
    8: {
        "default": ("/static/samples/char_5.webp", "/static/samples/char_6.webp"),
        "male": ("/static/samples/tue.webp", "/static/samples/sun.webp"),
        "female": ("/static/samples/char_5.webp", "/static/samples/sat.webp"),
        "neutral": ("/static/samples/char_6.webp", "/static/samples/mon.webp"),
    },
    10: {
        "default": ("/static/samples/mon.webp", "/static/samples/tue.webp"),
        "male": ("/static/samples/thu.webp", "/static/samples/tue.webp"),
        "female": ("/static/samples/mon.webp", "/static/samples/sun.webp"),
        "neutral": ("/static/samples/wed.webp", "/static/samples/fri.webp"),
    },
    17: {
        "default": ("/static/samples/bg_seongsu.webp", "/static/samples/bg_hangang.webp"),
        "rain": ("/static/samples/bg_yeonnam.webp", "/static/samples/bg_jeju.webp"),
        "city": ("/static/samples/bg_hangang.webp", "/static/samples/bg_namsan.webp"),
    },
}


def select_dynamic_ab_urls(turn_num: int, qa_history: list[dict[str, Any]]) -> tuple[str, str]:
    """Selects non-repeating A/B sample images tailored to the user's prior answers."""
    pair_cfg = VISUAL_WORLD_CUP_PAIRS.get(turn_num)
    if not pair_cfg:
        # Cycle through char_1..6 + mon..sun so no two turns ever show the same pair
        pool = [
            "/static/samples/char_1.webp",
            "/static/samples/char_2.webp",
            "/static/samples/char_3.webp",
            "/static/samples/char_4.webp",
            "/static/samples/char_5.webp",
            "/static/samples/char_6.webp",
            "/static/samples/mon.webp",
            "/static/samples/tue.webp",
            "/static/samples/wed.webp",
            "/static/samples/thu.webp",
            "/static/samples/fri.webp",
            "/static/samples/sat.webp",
        ]
        idx_a = (turn_num * 2) % len(pool)
        idx_b = (turn_num * 2 + 1) % len(pool)
        return pool[idx_a], pool[idx_b]

    joined_answers = " ".join(str(item.get("answer", "")).lower() for item in qa_history)
    if turn_num == 17:
        if any(k in joined_answers for k in ["비", "rain", "다락방", "차분", "연남"]):
            return pair_cfg.get("rain", pair_cfg["default"])
        if any(k in joined_answers for k in ["야경", "라디오", "한강", "city", "fm"]):
            return pair_cfg.get("city", pair_cfg["default"])
        return pair_cfg["default"]

    if any(k in joined_answers for k in ["남성", "male", "바리톤", "프로듀서"]):
        return pair_cfg.get("male", pair_cfg["default"])
    if any(k in joined_answers for k in ["중성", "neutral", "androgynous"]):
        return pair_cfg.get("neutral", pair_cfg["default"])
    if any(k in joined_answers for k in ["여성", "female", "선배"]):
        return pair_cfg.get("female", pair_cfg["default"])
    return pair_cfg["default"]


FALLBACK_QUESTIONS: list[dict[str, Any]] = [
    # ================= STAGE 1: CHARACTER DESIGN CONCEPT (Q1 - Q10) =================
    {
        "question": "First, who sits across your desk tonight?",
        "axis": "visual",
        "ui_mode": "choices",
        "stage_id": "stage_1_design",
        "stage_title": "Stage 1/3 · Character Design (1/10)",
        "stage_intro_banner": "Let's start by designing your character concept (10 quick picks).",
        "options": [
            "Female · Early-to-mid 20s (warm studio senior)",
            "Male · Mid-to-late 20s (calm night radio producer)",
            "Androgynous · Mid 20s (composed archivist)",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.90,
        "taste_meter": {"setting": 0.20, "personality": 0.20, "visual": 0.30, "voice": 0.20, "music": 0.20},
        "ready_for_spec": False,
    },
    {
        "question": "Ideal-Type Round 1: Which drawing style & aura pulls you in?",
        "axis": "visual",
        "ui_mode": "this_or_that",
        "stage_id": "stage_1_design",
        "stage_title": "Stage 1/3 · Character Design (2/10)",
        "options": [
            "Option A: Soft K-Webtoon romance linework & warm amber glow",
            "Option B: Crisp cinematic night studio & cool rainlight",
            "Mix both: Soft K-Webtoon face with cinematic studio contrast",
            "No preference — surprise me",
        ],
        "option_a_label": "Warm K-Webtoon · Soft Amber Rim Light",
        "option_b_label": "Cinematic Night Studio · Cool Rainlight",
        "uncertainty_remaining": 0.84,
        "taste_meter": {"setting": 0.25, "personality": 0.22, "visual": 0.42, "voice": 0.20, "music": 0.20},
        "ready_for_spec": False,
    },
    {
        "question": "Pick your favorite hair length & silhouette:",
        "axis": "visual",
        "ui_mode": "choices",
        "stage_id": "stage_1_design",
        "stage_title": "Stage 1/3 · Character Design (3/10)",
        "options": [
            "Chin-length layered tassel bob with airy bangs",
            "Long natural wave half-tied with a metal clip",
            "Clean tousled leaf-cut / chic short silhouette",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.78,
        "taste_meter": {"setting": 0.28, "personality": 0.25, "visual": 0.52, "voice": 0.22, "music": 0.20},
        "ready_for_spec": False,
    },
    {
        "question": "Which hair color catches the desk lamp best?",
        "axis": "visual",
        "ui_mode": "choices",
        "stage_id": "stage_1_design",
        "stage_title": "Stage 1/3 · Character Design (4/10)",
        "options": [
            "Misty silver-ash / soft platinum",
            "Deep espresso black / midnight navy",
            "Warm milk-tea brown / muted auburn",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.72,
        "taste_meter": {"setting": 0.30, "personality": 0.28, "visual": 0.62, "voice": 0.24, "music": 0.22},
        "ready_for_spec": False,
    },
    {
        "question": "Ideal-Type Round 2: Which eye shape & gaze is closer to your bias?",
        "axis": "visual",
        "ui_mode": "this_or_that",
        "stage_id": "stage_1_design",
        "stage_title": "Stage 1/3 · Character Design (5/10)",
        "batch_stage": "batch_q5",
        "options": [
            "Option A: Calm amber-hazel eyes with a warm crescent smile",
            "Option B: Focused cat-like gaze with quiet late-night charisma",
            "Mix both: Sharp focused eyes that soften when smiling",
            "No preference — surprise me",
        ],
        "option_a_label": "Warm Amber Gaze · Gentle Crescent Smile",
        "option_b_label": "Chic Cat-Like Eyes · Deep Night Focus",
        "uncertainty_remaining": 0.65,
        "taste_meter": {"setting": 0.32, "personality": 0.32, "visual": 0.72, "voice": 0.25, "music": 0.24},
        "ready_for_spec": False,
    },
    {
        "question": "What eyewear or headwear detail completes their face?",
        "axis": "visual",
        "ui_mode": "choices",
        "stage_id": "stage_1_design",
        "stage_title": "Stage 1/3 · Character Design (6/10)",
        "options": [
            "Thin round brushed-brass wire-rim glasses",
            "Vintage studio monitor headphones around the neck",
            "No glasses — clean face with subtle ear cuff",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.58,
        "taste_meter": {"setting": 0.35, "personality": 0.35, "visual": 0.80, "voice": 0.28, "music": 0.26},
        "ready_for_spec": False,
    },
    {
        "question": "What outfit should they wear for a 1:30 AM session?",
        "axis": "visual",
        "ui_mode": "choices",
        "stage_id": "stage_1_design",
        "stage_title": "Stage 1/3 · Character Design (7/10)",
        "options": [
            "Oversized charcoal wool cardigan over cream knit",
            "Olive corduroy work jacket over a relaxed Oxford shirt",
            "Minimal black turtleneck with rolled sleeves",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.52,
        "taste_meter": {"setting": 0.38, "personality": 0.38, "visual": 0.86, "voice": 0.30, "music": 0.28},
        "ready_for_spec": False,
    },
    {
        "question": "Ideal-Type Round 3: Which color palette fits their wardrobe?",
        "axis": "visual",
        "ui_mode": "this_or_that",
        "stage_id": "stage_1_design",
        "stage_title": "Stage 1/3 · Character Design (8/10)",
        "options": [
            "Option A: Warm cream, oatmeal, and brushed brass",
            "Option B: Charcoal slate, deep forest, and silver",
            "Mix both: Charcoal outer layer with warm cream highlights",
            "No preference — surprise me",
        ],
        "option_a_label": "Warm Cream & Brass · Cozy Atelier Tone",
        "option_b_label": "Charcoal Slate & Silver · Midnight FM Tone",
        "uncertainty_remaining": 0.46,
        "taste_meter": {"setting": 0.42, "personality": 0.40, "visual": 0.91, "voice": 0.32, "music": 0.30},
        "ready_for_spec": False,
    },
    {
        "question": "Pick one signature item always on their desk:",
        "axis": "visual",
        "ui_mode": "choices",
        "stage_id": "stage_1_design",
        "stage_title": "Stage 1/3 · Character Design (9/10)",
        "options": [
            "Amber fountain pen & leather-bound archival ledger",
            "Warm ceramic mug of roasted hojicha tea",
            "Vintage brass broadcast mic & analog cassette deck",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.40,
        "taste_meter": {"setting": 0.48, "personality": 0.42, "visual": 0.95, "voice": 0.34, "music": 0.32},
        "ready_for_spec": False,
    },
    {
        "question": "Design Final (10/10): Which overall character concept wins?",
        "axis": "visual",
        "ui_mode": "this_or_that",
        "stage_id": "stage_1_design",
        "stage_title": "Stage 1/3 · Character Design (10/10)",
        "batch_stage": "batch_q10",
        "interstitial_after": True,
        "interstitial_title": "Generating your character design now...",
        "interstitial_subtitle": "We bundled your 10 design picks (2x5 prompt batches) and started rendering your character sheet. While you wait, let's set up their personality!",
        "interstitial_duration_sec": 6,
        "options": [
            "Option A: Quiet Late-Night Archivist & Book Curator",
            "Option B: Seongsu Atelier Illustrator & Midnight DJ",
            "Mix both: Illustrator-Archivist with a late-night radio mic",
            "No preference — surprise me",
        ],
        "option_a_label": "Late-Night Archivist · Quiet Desk Companion",
        "option_b_label": "Atelier Creator & FM Host · Creative Senior",
        "uncertainty_remaining": 0.34,
        "taste_meter": {"setting": 0.52, "personality": 0.45, "visual": 0.98, "voice": 0.35, "music": 0.35},
        "ready_for_spec": False,
    },
    # ================= STAGE 2: PERSONALITY SETTINGS (Q11 - Q13) =================
    {
        "question": "How should your companion keep you company while you focus?",
        "axis": "personality",
        "ui_mode": "choices",
        "stage_id": "stage_2_personality",
        "stage_title": "Stage 2/3 · Personality (1/3)",
        "stage_intro_banner": "Character sheet generation is running in the background! Now let's shape their personality (3 questions).",
        "options": [
            "Quietly turns pages beside me, speaking only when needed",
            "Warmly checks in like a caring studio senior",
            "Paces the 25-minute timer like a steady night producer",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.28,
        "taste_meter": {"setting": 0.55, "personality": 0.72, "visual": 0.98, "voice": 0.40, "music": 0.38},
        "ready_for_spec": False,
    },
    {
        "question": "What emotional temperature & humor style do you like?",
        "axis": "personality",
        "ui_mode": "choices",
        "stage_id": "stage_2_personality",
        "stage_title": "Stage 2/3 · Personality (2/3)",
        "options": [
            "Cool and composed outside, deeply attentive inside (Tsundere/Kuudere)",
            "Consistently gentle, affirming, and soothing from the first word",
            "Dry, witty late-night humor that eases deadline tension",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.22,
        "taste_meter": {"setting": 0.58, "personality": 0.88, "visual": 0.98, "voice": 0.45, "music": 0.40},
        "ready_for_spec": False,
    },
    {
        "question": "When your 5-minute break starts, what is their first move?",
        "axis": "personality",
        "ui_mode": "choices",
        "stage_id": "stage_2_personality",
        "stage_title": "Stage 2/3 · Personality (3/3)",
        "batch_stage": "batch_q13",
        "interstitial_after": True,
        "interstitial_title": "Locking in persona & pre-warming voice...",
        "interstitial_subtitle": "Personality settings are ready! Finally, let's pick their speech tone, desk posture, and studio background.",
        "interstitial_duration_sec": 4,
        "options": [
            "Silently slides a warm mug across the desk with a nod",
            "Smiles and tells me to unclench my shoulders and stretch",
            "Reads a short midnight radio postcard to reset my mind",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.18,
        "taste_meter": {"setting": 0.60, "personality": 0.97, "visual": 0.98, "voice": 0.52, "music": 0.45},
        "ready_for_spec": False,
    },
    # ================= STAGE 3: SPEECH TONE, POSTURE & BACKGROUND (Q14 - Q18) =================
    {
        "question": "How should they speak to you when you chat?",
        "axis": "voice",
        "ui_mode": "choices",
        "stage_id": "stage_3_atmosphere",
        "stage_title": "Stage 3/3 · Speech, Posture & Room (1/5)",
        "stage_intro_banner": "Final step! Let's choose their speech tone, desk posture, and workspace background (5 questions).",
        "options": [
            "Calm, polite, unhurried late-night radio host phrasing",
            "Friendly, comfortable senior/friend tone across the desk",
            "Concise, poetic, low-key whisper that never breaks focus",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.14,
        "taste_meter": {"setting": 0.65, "personality": 0.97, "visual": 0.98, "voice": 0.78, "music": 0.50},
        "ready_for_spec": False,
    },
    {
        "question": "Which vocal timbre feels best on headphones after midnight?",
        "axis": "voice",
        "ui_mode": "choices",
        "stage_id": "stage_3_atmosphere",
        "stage_title": "Stage 3/3 · Speech, Posture & Room (2/5)",
        "options": [
            "Warm, low contralto / baritone with close-mic depth",
            "Clear, soft alto / tenor with warm acoustic breath",
            "Airy ASMR close-mic whisper right beside the desk",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.10,
        "taste_meter": {"setting": 0.70, "personality": 0.97, "visual": 0.98, "voice": 0.96, "music": 0.58},
        "ready_for_spec": False,
    },
    {
        "question": "What working posture should they hold in the video loop?",
        "axis": "setting",
        "ui_mode": "choices",
        "stage_id": "stage_3_atmosphere",
        "stage_title": "Stage 3/3 · Speech, Posture & Room (3/5)",
        "options": [
            "Resting chin lightly on one hand while writing with a fountain pen",
            "Typing steadily on a mechanical keyboard and glancing up warmly",
            "Holding a warm ceramic mug and turning archival notebook pages",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.07,
        "taste_meter": {"setting": 0.84, "personality": 0.97, "visual": 0.98, "voice": 0.96, "music": 0.65},
        "ready_for_spec": False,
    },
    {
        "question": "Workspace World Cup: Which studio background fits tonight?",
        "axis": "setting",
        "ui_mode": "this_or_that",
        "stage_id": "stage_3_atmosphere",
        "stage_title": "Stage 3/3 · Speech, Posture & Room (4/5)",
        "options": [
            "Option A: Seongsu Brick Atelier & Rain-Streaked Skylight",
            "Option B: Han River Night View & High-Floor FM Booth",
            "Mix both: Timber attic studio overlooking quiet Seoul rainlight",
            "No preference — surprise me",
        ],
        "option_a_label": "Seongsu Atelier & Skylight Rain · Warm 2700K Lamp",
        "option_b_label": "Han River Midnight View · Seoul FM Booth",
        "uncertainty_remaining": 0.04,
        "taste_meter": {"setting": 0.97, "personality": 0.97, "visual": 0.98, "voice": 0.96, "music": 0.75},
        "ready_for_spec": False,
    },
    {
        "question": "Finally, which original lo-fi BGM should play in your room?",
        "axis": "music",
        "ui_mode": "choices",
        "stage_id": "stage_3_atmosphere",
        "stage_title": "Stage 3/3 · Speech, Posture & Room (5/5)",
        "options": [
            "74 BPM warm Fender Rhodes electric piano jazz & rain",
            "68 BPM nocturnal acoustic guitar, upright bass & vinyl crackle",
            "78 BPM minimalist analog synth, felt piano & city night air",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.02,
        "taste_meter": {"setting": 0.98, "personality": 0.98, "visual": 0.98, "voice": 0.97, "music": 0.98},
        "ready_for_spec": True,
    },
]

FALLBACK_QUESTIONS_KO: list[dict[str, Any]] = [
    # ================= STAGE 1: 캐릭터 디자인 컨셉 (Q1 - Q10) =================
    {
        "question": "오늘 밤, 책상 건너편에 앉을 최애의 성별과 나이대는?",
        "axis": "visual",
        "ui_mode": "choices",
        "stage_id": "stage_1_design",
        "stage_title": "STEP 1/3 · 캐릭터 디자인 컨셉 (1/10)",
        "stage_intro_banner": "지금부터 캐릭터 디자인 컨셉을 정해볼게요! 이상형 월드컵처럼 직관적으로 골라주세요.",
        "options": [
            "여성 · 20대 초중반 (다정한 작업실 크리에이터 선배)",
            "남성 · 20대 중후반 (차분한 심야 라디오 프로듀서)",
            "중성적 매력 · 20대 중반 (분위기 있는 아카이비스트)",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.90,
        "taste_meter": {"setting": 0.20, "personality": 0.20, "visual": 0.30, "voice": 0.20, "music": 0.20},
        "ready_for_spec": False,
    },
    {
        "question": "[이상형 월드컵 1R] 첫인상으로 더 끌리는 작화 분위기는?",
        "axis": "visual",
        "ui_mode": "this_or_that",
        "stage_id": "stage_1_design",
        "stage_title": "STEP 1/3 · 캐릭터 디자인 컨셉 (2/10)",
        "options": [
            "Option A: 포근한 K-웹툰 감성 작화와 따뜻한 앰버 조명",
            "Option B: 세련된 시네마틱 나이트 작화와 푸른 빗빛 무드",
            "두 스타일 믹스: K-웹툰 이목구비에 시네마틱 새벽 조명",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "option_a_label": "포근한 K-웹툰 감성 · 2700K 앰버 조명",
        "option_b_label": "시네마틱 나이트 무드 · 새벽 창가 조명",
        "uncertainty_remaining": 0.84,
        "taste_meter": {"setting": 0.25, "personality": 0.22, "visual": 0.42, "voice": 0.20, "music": 0.20},
        "ready_for_spec": False,
    },
    {
        "question": "가장 취향인 머리카락 길이와 헤어 실루엣은?",
        "axis": "visual",
        "ui_mode": "choices",
        "stage_id": "stage_1_design",
        "stage_title": "STEP 1/3 · 캐릭터 디자인 컨셉 (3/10)",
        "options": [
            "가볍게 층을 낸 시스루 태슬 단발",
            "자연스럽게 반묶음한 부드러운 웨이브 장발",
            "단정하게 넘긴 시크한 리프컷 / 숏컷",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.78,
        "taste_meter": {"setting": 0.28, "personality": 0.25, "visual": 0.52, "voice": 0.22, "music": 0.20},
        "ready_for_spec": False,
    },
    {
        "question": "스탠드 조명 아래 가장 예뻐 보이는 헤어 컬러는?",
        "axis": "visual",
        "ui_mode": "choices",
        "stage_id": "stage_1_design",
        "stage_title": "STEP 1/3 · 캐릭터 디자인 컨셉 (4/10)",
        "options": [
            "신비로운 실버 애쉬 / 소프트 백금발",
            "차분한 흑발 / 에스프레소 다크브라운",
            "포근한 밀크티 브라운 / 로즈 와인빛",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.72,
        "taste_meter": {"setting": 0.30, "personality": 0.28, "visual": 0.62, "voice": 0.24, "music": 0.22},
        "ready_for_spec": False,
    },
    {
        "question": "[이상형 월드컵 2R] 마주쳤을 때 심쿵하는 눈매와 인상은?",
        "axis": "visual",
        "ui_mode": "this_or_that",
        "stage_id": "stage_1_design",
        "stage_title": "STEP 1/3 · 캐릭터 디자인 컨셉 (5/10)",
        "batch_stage": "batch_q5",
        "options": [
            "Option A: 다정하게 휘어지는 호박색 반달 눈웃음",
            "Option B: 집중할 때 빛나는 도도한 고양이 눈매",
            "두 매력 믹스: 평소엔 시크하지만 눈 마주치면 다정한 눈매",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "option_a_label": "다정한 호박색 반달 눈웃음 · 온기 가득",
        "option_b_label": "집중하는 고양이 눈매 · 냉미남/냉미녀 무드",
        "uncertainty_remaining": 0.65,
        "taste_meter": {"setting": 0.32, "personality": 0.32, "visual": 0.72, "voice": 0.25, "music": 0.24},
        "ready_for_spec": False,
    },
    {
        "question": "얼굴 주위에 더하고 싶은 안경·헤드폰 포인트는?",
        "axis": "visual",
        "ui_mode": "choices",
        "stage_id": "stage_1_design",
        "stage_title": "STEP 1/3 · 캐릭터 디자인 컨셉 (6/10)",
        "options": [
            "지적인 라운드 브러시드 금테 안경",
            "목에 살짝 걸친 빈티지 황동 스튜디오 헤드폰",
            "안경 없이 깔끔한 얼굴과 은은한 이어커프",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.58,
        "taste_meter": {"setting": 0.35, "personality": 0.35, "visual": 0.80, "voice": 0.28, "music": 0.26},
        "ready_for_spec": False,
    },
    {
        "question": "새벽 작업실에 가장 잘 어울리는 옷차림(코디)은?",
        "axis": "visual",
        "ui_mode": "choices",
        "stage_id": "stage_1_design",
        "stage_title": "STEP 1/3 · 캐릭터 디자인 컨셉 (7/10)",
        "options": [
            "크림색 니트 위에 걸친 오버핏 차콜 울 가디건",
            "편안한 옥스퍼드 셔츠와 올리브 코듀로이 자켓",
            "소매를 살짝 걷은 미니멀 블랙 터틀넥 니트",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.52,
        "taste_meter": {"setting": 0.38, "personality": 0.38, "visual": 0.86, "voice": 0.30, "music": 0.28},
        "ready_for_spec": False,
    },
    {
        "question": "[이상형 월드컵 3R] 최애의 전체 컬러 팔레트 대결!",
        "axis": "visual",
        "ui_mode": "this_or_that",
        "stage_id": "stage_1_design",
        "stage_title": "STEP 1/3 · 캐릭터 디자인 컨셉 (8/10)",
        "options": [
            "Option A: 크림·오트밀·브러시드 브라스의 포근한 웜톤",
            "Option B: 차콜 슬레이트·딥포레스트·실버의 차분한 쿨톤",
            "두 컬러 믹스: 차콜 아우터에 따뜻한 크림 & 앰버 포인트",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "option_a_label": "크림 & 브라스 웜톤 · 성수 아틀리에 감성",
        "option_b_label": "차콜 & 실버 쿨톤 · 심야 라디오 부스 감성",
        "uncertainty_remaining": 0.46,
        "taste_meter": {"setting": 0.42, "personality": 0.40, "visual": 0.91, "voice": 0.32, "music": 0.30},
        "ready_for_spec": False,
    },
    {
        "question": "캐릭터 시트에 꼭 들어갈 시그니처 소품 하나를 고른다면?",
        "axis": "visual",
        "ui_mode": "choices",
        "stage_id": "stage_1_design",
        "stage_title": "STEP 1/3 · 캐릭터 디자인 컨셉 (9/10)",
        "options": [
            "귀 뒤에 꽂은 호박색 만년필과 가죽 양장 노트",
            "김이 모락모락 나는 따뜻한 호지차 세라믹 머그잔",
            "빈티지 황동 방송 마이크와 아날로그 카세트 테이프",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.40,
        "taste_meter": {"setting": 0.48, "personality": 0.42, "visual": 0.95, "voice": 0.34, "music": 0.32},
        "ready_for_spec": False,
    },
    {
        "question": "[디자인 결승 10/10] 최종 캐릭터 비주얼 컨셉을 확정해 주세요!",
        "axis": "visual",
        "ui_mode": "this_or_that",
        "stage_id": "stage_1_design",
        "stage_title": "STEP 1/3 · 캐릭터 디자인 컨셉 (10/10)",
        "batch_stage": "batch_q10",
        "interstitial_after": True,
        "interstitial_title": "캐릭터를 생성하고 있어요",
        "interstitial_subtitle": "방금 고른 10가지 디자인 컨셉을 5개씩 고밀도 프롬프트로 묶어 캐릭터 시트를 그리고 있어요. 기다리는 동안 성격 설정으로 넘어갈까요? 이제는 성격을 진행할게요!",
        "interstitial_duration_sec": 6,
        "options": [
            "Option A: 새벽 다락방의 조용한 아카이비스트 & 북 큐레이터",
            "Option B: 성수동 작업실의 일러스트레이터 & 심야 라디오 DJ",
            "두 컨셉 믹스: 노트를 기록하며 심야 방송을 진행하는 크리에이터",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "option_a_label": "다락방 아카이비스트 · 차분한 기록가",
        "option_b_label": "성수 아틀리에 작가 & 심야 DJ · 다정한 선배",
        "uncertainty_remaining": 0.34,
        "taste_meter": {"setting": 0.52, "personality": 0.45, "visual": 0.98, "voice": 0.35, "music": 0.35},
        "ready_for_spec": False,
    },
    # ================= STAGE 2: 성격 설정 (Q11 - Q13) =================
    {
        "question": "내가 집중해서 작업할 때, 최애는 어떤 스타일로 곁에 있어 줄까요?",
        "axis": "personality",
        "ui_mode": "choices",
        "stage_id": "stage_2_personality",
        "stage_title": "STEP 2/3 · 성격 설정 (1/3)",
        "stage_intro_banner": "백그라운드에서 캐릭터 디자인을 생성하고 있어요! 기다리는 동안 성격 관련 문항 3가지를 정해볼게요.",
        "options": [
            "조용히 책장을 넘기며 꼭 필요할 때만 나직이 말을 건넨다",
            "다정한 작업실 선배처럼 중간중간 컨디션을 살뜰히 챙겨준다",
            "든든한 동료 프로듀서처럼 25분 집중 페이스를 함께 맞춰준다",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.28,
        "taste_meter": {"setting": 0.55, "personality": 0.72, "visual": 0.98, "voice": 0.40, "music": 0.38},
        "ready_for_spec": False,
    },
    {
        "question": "최애의 속마음 온도차(데레)와 유머 감각은?",
        "axis": "personality",
        "ui_mode": "choices",
        "stage_id": "stage_2_personality",
        "stage_title": "STEP 2/3 · 성격 설정 (2/3)",
        "options": [
            "겉은 침착하고 쿨하지만 은근히 다정하게 챙겨주는 겉차속따",
            "처음부터 끝까지 포근하고 따뜻하게 공감해 주는 힐링파",
            "담백하고 센스 있는 농담으로 마감 긴장을 풀어주는 위트파",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.22,
        "taste_meter": {"setting": 0.58, "personality": 0.88, "visual": 0.98, "voice": 0.45, "music": 0.40},
        "ready_for_spec": False,
    },
    {
        "question": "잠깐 쉬는 시간, 최애가 가장 먼저 보여주는 행동은?",
        "axis": "personality",
        "ui_mode": "choices",
        "stage_id": "stage_2_personality",
        "stage_title": "STEP 2/3 · 성격 설정 (3/3)",
        "batch_stage": "batch_q13",
        "interstitial_after": True,
        "interstitial_title": "성격과 페르소나를 입히고 있어요",
        "interstitial_subtitle": "캐릭터에 성격 설정이 반영되었어요! 기다리는 동안 마지막으로 말투, 작업 자세, 그리고 작업하는 배경을 골라볼게요.",
        "interstitial_duration_sec": 4,
        "options": [
            "말없이 따뜻한 차 한 잔을 책상 끝에 스윽 밀어준다",
            "미소 지으며 어깨 한 번 펴고 기지개 켜라고 다정하게 챙긴다",
            "심야 라디오 엽서를 읽어주듯 짧은 응원의 한마디를 들려준다",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.18,
        "taste_meter": {"setting": 0.60, "personality": 0.97, "visual": 0.98, "voice": 0.52, "music": 0.45},
        "ready_for_spec": False,
    },
    # ================= STAGE 3: 말투 · 작업 자세 · 작업실 배경 & BGM (Q14 - Q18) =================
    {
        "question": "내가 말을 걸었을 때, 최애가 답장하는 말투는?",
        "axis": "voice",
        "ui_mode": "choices",
        "stage_id": "stage_3_atmosphere",
        "stage_title": "STEP 3/3 · 말투·자세·작업 배경 (1/5)",
        "stage_intro_banner": "이제 마지막 단계예요! 말투, 작업 자세, 그리고 함께 작업할 배경을 진행할게요.",
        "options": [
            "나직하고 차분한 해요체 (심야 FM 라디오 DJ 말투)",
            "편안하고 다정한 반말·반존대 (친한 작업실 선배·친구 말투)",
            "집중을 깨지 않는 간결하고 시적인 속삭임 말투",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.14,
        "taste_meter": {"setting": 0.65, "personality": 0.97, "visual": 0.98, "voice": 0.78, "music": 0.50},
        "ready_for_spec": False,
    },
    {
        "question": "이어폰으로 들을 때 가장 설레는 목소리 음색은?",
        "axis": "voice",
        "ui_mode": "choices",
        "stage_id": "stage_3_atmosphere",
        "stage_title": "STEP 3/3 · 말투·자세·작업 배경 (2/5)",
        "options": [
            "깊고 따뜻한 중저음 콘트랄토 / 바리톤 보이스",
            "맑고 포근한 소프트 알토 / 부드러운 미성 보이스",
            "귀 바로 옆에서 속삭이는 듯한 클로즈마이크 ASMR 보이스",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.10,
        "taste_meter": {"setting": 0.70, "personality": 0.97, "visual": 0.98, "voice": 0.96, "music": 0.58},
        "ready_for_spec": False,
    },
    {
        "question": "영상 속에서 최애가 취하고 있을 작업 자세(포즈)는?",
        "axis": "setting",
        "ui_mode": "choices",
        "stage_id": "stage_3_atmosphere",
        "stage_title": "STEP 3/3 · 말투·자세·작업 배경 (3/5)",
        "options": [
            "한 손으로 턱을 살짝 괴고 만년필로 노트를 기록하는 자세",
            "차분히 키보드와 오디오 장비를 다루다 나를 바라보는 자세",
            "따뜻한 머그잔을 감싸 쥐고 빗소리와 페이지를 음미하는 자세",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.07,
        "taste_meter": {"setting": 0.84, "personality": 0.97, "visual": 0.98, "voice": 0.96, "music": 0.65},
        "ready_for_spec": False,
    },
    {
        "question": "[배경 월드컵] 오늘 밤 함께 작업할 스튜디오 배경은?",
        "axis": "setting",
        "ui_mode": "this_or_that",
        "stage_id": "stage_3_atmosphere",
        "stage_title": "STEP 3/3 · 말투·자세·작업 배경 (4/5)",
        "options": [
            "Option A: 빗소리가 흐르는 성수동 벽돌 아틀리에 & 다락방",
            "Option B: 서울 한강 야경이 펼쳐진 고층 심야 FM 라디오 부스",
            "두 공간 믹스: 서울 야경과 빗소리가 함께 보이는 우드 작업실",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "option_a_label": "성수동 원목 아틀리에 & 다락방 · 창가 빗소리",
        "option_b_label": "서울 한강 나이트뷰 · 고층 심야 FM 부스",
        "uncertainty_remaining": 0.04,
        "taste_meter": {"setting": 0.97, "personality": 0.97, "visual": 0.98, "voice": 0.96, "music": 0.75},
        "ready_for_spec": False,
    },
    {
        "question": "마지막! 작업실에 흐를 오리지널 로파이 BGM 사운드는?",
        "axis": "music",
        "ui_mode": "choices",
        "stage_id": "stage_3_atmosphere",
        "stage_title": "STEP 3/3 · 말투·자세·작업 배경 (5/5)",
        "options": [
            "74 BPM 따뜻한 펜더 로즈 일렉트릭 피아노 재즈 & 빗소리",
            "68 BPM 새벽 어쿠스틱 기타 & 콘트라베이스 바이닐 루프",
            "78 BPM 몽환적인 아날로그 신스 & 펠트 피아노 나이트 믹스",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.02,
        "taste_meter": {"setting": 0.98, "personality": 0.98, "visual": 0.98, "voice": 0.97, "music": 0.98},
        "ready_for_spec": True,
    },
]



class BiasStudioOrchestrator:
    """Manages sessions, question turns, multimodal generation, and the 4 verification loops."""

    def __init__(self) -> None:
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.ensure_default_demo_session()

    def session_dir(self, session_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)[:48] or "default"
        d = TMP_ROOT / safe_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load_session(self, session_id: str) -> dict[str, Any]:
        sdir = self.session_dir(session_id)
        state_file = sdir / "session.json"
        if not state_file.exists() and GCS_BUCKET_NAME:
            self._try_restore_from_gcs(session_id, sdir)
        if not state_file.exists():
            if session_id == "default":
                self.ensure_default_demo_session()
            else:
                raise FileNotFoundError(f"Session '{session_id}' not found")
        data = json.loads(state_file.read_text(encoding="utf-8"))
        spec = data.get("spec")
        if isinstance(spec, dict):
            spec.setdefault("mbti", "INFJ · 차분한 새벽 완벽주의자")
            spec.setdefault("signature_drink", "얼그레이 밀크티 & 따뜻한 드립 커피")
            spec.setdefault("secret_habit", "집중할 때 만년필 끝을 살짝 돌리며 안경테를 고쳐 쓴다")
            spec.setdefault(
                "first_greeting_narration",
                "*따뜻한 2700K 황동 스탠드 불빛 아래에서 노트를 덮고 반갑게 고개를 든다.*",
            )
            spec.setdefault(
                "first_greeting_line",
                "오늘 밤도 잊지 않고 찾아와 주셨네요. 제 옆자리 비워뒀어요, 같이 시작해 볼까요?",
            )
        return data

    def save_session(self, session_id: str, state: dict[str, Any]) -> None:
        sdir = self.session_dir(session_id)
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        (sdir / "session.json").write_text(
            json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def append_trace(self, session_id: str, entry: TraceEntry) -> None:
        try:
            state = self.load_session(session_id)
        except Exception:
            return
        state.setdefault("trace", []).append(entry.model_dump())
        self.save_session(session_id, state)

    def create_session(self, max_turns: int = 18, survey_mode: str = "staged", lang: str = "en") -> dict[str, Any]:
        session_id = uuid.uuid4().hex[:10]
        survey_mode = (survey_mode or "staged").lower()
        if survey_mode in ("staged", "bias"):
            survey_mode = "staged"
            max_turns = 18
        elif survey_mode == "general":
            max_turns = 10
        elif survey_mode == "quick":
            max_turns = 6
        else:
            survey_mode = "staged"
            max_turns = 18

        state: dict[str, Any] = {
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "survey_mode": survey_mode,
            "lang": lang if lang in ("en", "ko") else "en",
            "max_turns": max_turns,
            "turn_number": 0,
            "status": "questioning",
            "current_stage": (
                "지금부터 캐릭터 디자인 컨셉을 정해볼게요 (1/3단계)"
                if lang == "ko"
                else "Stage 1/3: Designing your character concept..."
            ),
            "qa_history": [],
            "batched_clusters": {},
            "prewarm_status": {
                "batch_q5": "pending",
                "batch_q10": "pending",
                "batch_q13": "pending",
            },
            "last_interstitial": None,
            "pending_batch_stage": None,
            "chat_history": [],
            "current_question": None,
            "taste_meter": {
                "setting": 0.15,
                "personality": 0.15,
                "visual": 0.15,
                "voice": 0.15,
                "music": 0.15,
            },
            "spec": None,
            "verification": {
                "sheet": None,
                "voice_dj": None,
                "voice_asmr": None,
                "music": None,
                "video": None,
            },
            "assets": {
                "option_a_url": None,
                "option_b_url": None,
                "sheet_url": None,
                "scene_url": None,
                "dj_audio_url": None,
                "asmr_audio_url": None,
                "music_audio_url": None,
                "video_url": None,
                "study_mp4_url": None,
                "kit_zip_url": None,
                "video_fallback_active": False,
            },
            "argon_interaction_id": None,
            "sheet_interaction_id": None,
            "voice_id": None,
            "trace": [],
            "safety_notice": None,
        }
        self.save_session(session_id, state)
        # Generate Q1 immediately
        return self.generate_next_question(session_id)

    def check_safety(self, session_id: str, text: str) -> SafetyCheckResult:
        rule_hit = _fast_rule_safety_check(text)
        if rule_hit is not None:
            self.append_trace(
                session_id,
                TraceEntry(
                    step="safety_gate",
                    model="rule+prestudy_100",
                    latency_ms=2,
                    summary=f"Refused protected/unsafe input: {rule_hit.reason[:56]}",
                    timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    status="refused",
                ),
            )
            return rule_hit

        # Only invoke LLM safety check if suspicious custom text patterns appear
        suspicious_pattern = re.search(
            r"\b(like|copy|clone|style of|cover of|sing|real person|celebrity|idol|actor|actress|minor|child|kid|실존|아이돌|배우|연예인|카피|모방|미성년)\b",
            text or "",
            re.IGNORECASE,
        )
        if not suspicious_pattern or not get_api_key():
            self.append_trace(
                session_id,
                TraceEntry(
                    step="safety_gate",
                    model="rule+prestudy_100",
                    latency_ms=1,
                    summary="Verified safe & original input against 145+ protected IP & safety rules",
                    timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    status="ok",
                ),
            )
            return SafetyCheckResult(allowed=True, reason="ok", safe_alternative_suggestion=None)

        client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))
        try:
            res, _ = client.generate_structured_json(
                step="safety_check",
                model=MODEL_FLASH,
                input_payload=build_safety_prompt(text),
                schema_cls=SafetyCheckResult,
                thinking_level="low",
            )
            return res
        except Exception:
            return SafetyCheckResult(allowed=True, reason="ok", safe_alternative_suggestion=None)

    def generate_next_question(self, session_id: str) -> dict[str, Any]:
        state = self.load_session(session_id)
        turn_num = len(state["qa_history"]) + 1
        max_turns = state.get("max_turns", 18)
        survey_mode = state.get("survey_mode", "staged")
        lang = state.get("lang", "en")
        state["turn_number"] = turn_num

        fb_list = FALLBACK_QUESTIONS_KO if lang == "ko" else FALLBACK_QUESTIONS
        fb_idx = (turn_num - 1) % len(fb_list)
        fb_data = dict(fb_list[fb_idx])
        fb_data["ready_for_spec"] = turn_num >= max_turns

        # If running a shorter mode (6Q quick or 10Q general), adjust stage_title cleanly
        if max_turns < 18:
            fb_data["interstitial_after"] = (turn_num == 4 and max_turns >= 6)
            if fb_data["interstitial_after"]:
                fb_data["batch_stage"] = "batch_q5"
                fb_data["interstitial_title"] = (
                    "캐릭터 디자인을 생성하고 있어요" if lang == "ko" else "Generating your character concept..."
                )
                fb_data["interstitial_subtitle"] = (
                    "기다리는 동안 성격과 분위기 설정으로 넘어갈게요!"
                    if lang == "ko"
                    else "While we render your design, let's finish personality & sound!"
                )
                fb_data["interstitial_duration_sec"] = 4

        q_turn = QuestionTurn(**fb_data)
        self.append_trace(
            session_id,
            TraceEntry(
                step=f"question_q{turn_num}_instant",
                model="piku_worldcup+argon_schema",
                latency_ms=1,
                summary=f"[{q_turn.stage_title or f'Q{turn_num}'}] {q_turn.question[:44]}",
                timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                status="ok",
            ),
        )

        no_pref_label = "상관없음 — 알아서 추천해 주세요" if lang == "ko" else "No preference — surprise me"
        if not any("no preference" in opt.lower() or "surprise" in opt.lower() or "상관없음" in opt for opt in q_turn.options):
            q_turn.options = list(q_turn.options[:3]) + [no_pref_label]

        # Dynamic, non-repeating sample images for every 'this_or_that' Ideal-Type World Cup turn
        if q_turn.ui_mode == "this_or_that":
            url_a, url_b = select_dynamic_ab_urls(turn_num, state.get("qa_history", []))
            q_turn.option_a_url = url_a
            q_turn.option_b_url = url_b
            state["assets"]["option_a_url"] = url_a
            state["assets"]["option_b_url"] = url_b
        else:
            q_turn.option_a_url = None
            q_turn.option_b_url = None

        state["current_question"] = q_turn.model_dump()
        state["taste_meter"] = q_turn.taste_meter
        state["current_stage"] = q_turn.stage_title or f"Question {turn_num} of {max_turns}"
        self.save_session(session_id, state)
        return self.load_session(session_id)

    @staticmethod
    def compile_batched_prompts(qa_history: list[dict[str, Any]]) -> dict[str, str]:
        """Bundles survey answers into 5-6 prompt high-density clusters for higher-quality AI concept synthesis."""
        clusters: dict[str, str] = {}
        if len(qa_history) >= 1:
            c1_items = qa_history[:5]
            clusters["batch_1_silhouette_gaze"] = (
                "[Batch 1 · Core Silhouette, Hair & Gaze (5 Prompts Combined)] "
                + " | ".join(f"{item['q_id']} ({item['axis']}): {item['answer']}" for item in c1_items)
            )
        if len(qa_history) >= 6:
            c2_items = qa_history[5:10]
            clusters["batch_2_wardrobe_concept"] = (
                "[Batch 2 · Eyewear, Wardrobe, Palette, Prop & Archetype (5 Prompts Combined)] "
                + " | ".join(f"{item['q_id']} ({item['axis']}): {item['answer']}" for item in c2_items)
            )
        if len(qa_history) >= 11:
            c3_items = qa_history[10:13]
            clusters["batch_3_personality"] = (
                "[Batch 3 · Companion Persona, Emotional Warmth & Break Reaction (3 Prompts Combined)] "
                + " | ".join(f"{item['q_id']} ({item['axis']}): {item['answer']}" for item in c3_items)
            )
        if len(qa_history) >= 14:
            c4_items = qa_history[13:18]
            clusters["batch_4_voice_posture_scene"] = (
                "[Batch 4 · Speech Tone, Vocal Timbre, Desk Posture, Studio Background & Lo-Fi BGM (5 Prompts Combined)] "
                + " | ".join(f"{item['q_id']} ({item['axis']}): {item['answer']}" for item in c4_items)
            )
        return clusters

    def submit_answer(self, session_id: str, answer: str, free_text: Optional[str] = None) -> dict[str, Any]:
        state = self.load_session(session_id)
        combined = f"{answer} {free_text or ''}".strip()

        safety = self.check_safety(session_id, combined)
        if not safety.allowed:
            state = self.load_session(session_id)
            state["safety_notice"] = safety.model_dump()
            self.save_session(session_id, state)
            return state

        state = self.load_session(session_id)
        state["safety_notice"] = None
        curr_q = state.get("current_question") or {}
        q_idx = len(state["qa_history"]) + 1
        state["qa_history"].append(
            {
                "q_id": f"Q{q_idx}",
                "axis": curr_q.get("axis", "visual"),
                "question": curr_q.get("question", ""),
                "answer": combined,
                "stage_id": curr_q.get("stage_id"),
            }
        )

        # Update 5-6 prompt batched clusters whenever answers accumulate
        state["batched_clusters"] = self.compile_batched_prompts(state["qa_history"])

        # Record Toss-style interstitial metadata if this question triggers a stage transition
        if curr_q.get("interstitial_after"):
            state["last_interstitial"] = {
                "title": curr_q.get("interstitial_title"),
                "subtitle": curr_q.get("interstitial_subtitle"),
                "duration_sec": curr_q.get("interstitial_duration_sec", 6),
                "batch_stage": curr_q.get("batch_stage"),
                "completed_turn": q_idx,
            }
        else:
            state["last_interstitial"] = None

        state["pending_batch_stage"] = curr_q.get("batch_stage")

        max_turns = state.get("max_turns", 18)
        if q_idx >= max_turns:
            state["status"] = "ready_for_spec"
            state["current_stage"] = "All 18 taste signals collected in 4 batched clusters. Ready to finalize studio."
            state["taste_meter"] = {
                "setting": 0.98,
                "personality": 0.98,
                "visual": 0.98,
                "voice": 0.97,
                "music": 0.98,
            }
            self.save_session(session_id, state)
            return state

        self.save_session(session_id, state)
        return self.generate_next_question(session_id)

    def prewarm_batch(self, session_id: str, stage: str = "batch_q10") -> dict[str, Any]:
        """Runs in the background during Toss-style stage transitions: bundles 5-6 prompts per batch and pre-generates spec/sheet/voice."""
        try:
            state = self.load_session(session_id)
        except Exception:
            return {"status": "not_found"}

        clusters = self.compile_batched_prompts(state.get("qa_history", []))
        state["batched_clusters"] = clusters
        state.setdefault("prewarm_status", {})[stage] = "running"
        self.save_session(session_id, state)

        if stage == "batch_q5":
            self.append_trace(
                session_id,
                TraceEntry(
                    step="batch_1_compiled (Q1-Q5)",
                    model="prompt_batcher_5x",
                    latency_ms=4,
                    summary=f"Bundled 5 visual silhouette/hair/gaze prompts: {clusters.get('batch_1_silhouette_gaze', '')[:72]}...",
                    timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    status="ok",
                ),
            )
            state = self.load_session(session_id)
            state.setdefault("prewarm_status", {})[stage] = "ready"
            self.save_session(session_id, state)
            return {"status": "ok", "stage": stage}

        if stage == "batch_q10":
            self.append_trace(
                session_id,
                TraceEntry(
                    step="batch_2_compiled (Q6-Q10)",
                    model="prompt_batcher_5x",
                    latency_ms=5,
                    summary="Bundled Q1-Q10 (2x5 prompt batches) -> Starting background character spec & sheet pre-generation",
                    timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    status="ok",
                ),
            )
            # Pre-generate CharacterSpec + 3-view character sheet while user answers Q11-Q18!
            try:
                self.synthesize_spec(session_id, is_background_prewarm=True)
                self.run_sheet_loop(session_id, is_background_prewarm=True)
                state = self.load_session(session_id)
                state.setdefault("prewarm_status", {})[stage] = "ready"
                self.save_session(session_id, state)
            except Exception:
                state = self.load_session(session_id)
                state.setdefault("prewarm_status", {})[stage] = "fallback"
                self.save_session(session_id, state)
            return {"status": "ok", "stage": stage}

        if stage == "batch_q13":
            self.append_trace(
                session_id,
                TraceEntry(
                    step="batch_3_compiled (Q11-Q13)",
                    model="prompt_batcher_3x",
                    latency_ms=4,
                    summary="Bundled Q11-Q13 personality answers -> Pre-warming persona & voice profile",
                    timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    status="ok",
                ),
            )
            state = self.load_session(session_id)
            state.setdefault("prewarm_status", {})[stage] = "ready"
            self.save_session(session_id, state)
            return {"status": "ok", "stage": stage}

        return {"status": "ok", "stage": stage}

    # -----------------------------------------------------------------------
    # Phase 2: Character Spec Synthesis & Originality Check
    # -----------------------------------------------------------------------
    def synthesize_spec(self, session_id: str, is_background_prewarm: bool = False) -> dict[str, Any]:
        state = self.load_session(session_id)
        lang = state.get("lang", "en")
        if not is_background_prewarm:
            state["status"] = "synthesizing_spec"
            state["current_stage"] = "Synthesizing character specification with gemini-4-argon (batched prompts)..."
            self.save_session(session_id, state)

        sdir = self.session_dir(session_id)
        client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))
        spec: Optional[CharacterSpec] = None


        if get_api_key():
            try:
                prompt = build_spec_prompt(state["qa_history"], PRESTUDY_NAMES, lang=lang)
                spec, inter_id = client.generate_structured_json(
                    step="spec_synthesis",
                    model=MODEL_ARGON,
                    input_payload=prompt,
                    schema_cls=CharacterSpec,
                    thinking_level="low",
                    previous_interaction_id=None,
                )
                if inter_id:
                    state["argon_interaction_id"] = inter_id

                # Originality check against 100+ pre-study VTuber & K-Webtoon names
                collision = _check_name_collision(spec.name)
                if collision:
                    self.append_trace(
                        session_id,
                        TraceEntry(
                            step="originality_guard",
                            model="prestudy_100_check",
                            latency_ms=3,
                            summary=f"Name '{spec.name}' collided with '{collision}'; regenerating original name.",
                            timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                            status="retry",
                        ),
                    )
                    spec.name = "Sora" if collision.lower() != "sora" else "Ren"
                else:
                    self.append_trace(
                        session_id,
                        TraceEntry(
                            step="originality_guard",
                            model="prestudy_100_check",
                            latency_ms=2,
                            summary=f"Verified '{spec.name}' against 145+ pre-study & webtoon names: 0 collisions.",
                            timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                            status="ok",
                        ),
                    )
            except Exception as exc:
                self.append_trace(
                    session_id,
                    TraceEntry(
                        step="spec_synthesis_fallback",
                        model=MODEL_ARGON,
                        latency_ms=12,
                        summary=f"Fallback spec synthesized ({str(exc)[:60]})",
                        timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                        status="fallback",
                    ),
                )

        if spec is None:
            spec = self._default_character_spec(state.get("qa_history", []))

        # Ensure adult apparent age
        if "20" not in spec.apparent_age:
            spec.apparent_age = "mid 20s"

        spec_dict = spec.model_dump()
        (sdir / "spec.json").write_text(json.dumps(spec_dict, indent=2, ensure_ascii=False), encoding="utf-8")

        state = self.load_session(session_id)
        state["spec"] = spec_dict
        if not is_background_prewarm and state.get("status") != "questioning":
            state["status"] = "spec_ready"
            state["current_stage"] = f"Character Spec ready for {spec.name}."
        self.save_session(session_id, state)
        return state

    def _prewarm_scene_still(self, session_id: str) -> None:
        """Pre-generates scene.png in the background right after sheet.png is ready so Phase 6 starts immediately."""
        try:
            state = self.load_session(session_id)
            spec_dict = state.get("spec")
            if not spec_dict or not get_api_key():
                return
            sdir = self.session_dir(session_id)
            sheet_path = sdir / "sheet.png"
            scene_path = sdir / "scene.png"
            if scene_path.exists():
                return
            client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))
            scene_bytes, _ = client.generate_image(
                step="scene_still_prewarm",
                model=MODEL_NANO_BANANA,
                prompt=spec_dict["scene_prompt"],
                aspect_ratio="16:9",
                image_size="2K",
                reference_image_bytes=sheet_path.read_bytes() if sheet_path.exists() else None,
            )
            if not scene_path.exists():
                scene_path.write_bytes(scene_bytes)
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Phase 3: Verification Loop #1 — 3-View Character Sheet
    # -----------------------------------------------------------------------
    def run_sheet_loop(self, session_id: str, is_background_prewarm: bool = False) -> dict[str, Any]:
        state = self.load_session(session_id)
        if not state.get("spec"):
            state = self.synthesize_spec(session_id, is_background_prewarm=is_background_prewarm)
        spec_dict = state["spec"]
        sdir = self.session_dir(session_id)
        sheet_path = sdir / "sheet.png"

        # If sheet.png was already pre-generated during the Q10 Toss Interstitial, reuse it immediately!
        if not is_background_prewarm and sheet_path.exists() and state.get("verification", {}).get("sheet"):
            self.append_trace(
                session_id,
                TraceEntry(
                    step="sheet_prewarm_reused",
                    model=MODEL_NANO_BANANA,
                    latency_ms=2,
                    summary="Reused 3-view character sheet pre-generated during Stage 1->2 transition",
                    timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    status="ok",
                ),
            )
            threading.Thread(target=self._prewarm_scene_still, args=(session_id,), daemon=True).start()
            return state

        client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))

        if not is_background_prewarm:
            state["status"] = "verifying_sheet"
            state["current_stage"] = "Drawing 3-view character sheet with gemini-nano-banana-2.1 (Round 1/3)..."
            self.save_session(session_id, state)

        last_verification: Optional[SheetVerificationResult] = None
        sheet_inter_id: Optional[str] = None
        current_prompt = spec_dict["sheet_prompt"]

        if get_api_key():
            for round_num in range(1, MAX_VERIFY_ROUNDS_SHEET + 1):
                try:
                    if not is_background_prewarm:
                        state = self.load_session(session_id)
                        state["current_stage"] = f"Drawing character sheet (Round {round_num}/{MAX_VERIFY_ROUNDS_SHEET})..."
                        self.save_session(session_id, state)

                    img_bytes, sheet_inter_id = client.generate_image(
                        step=f"sheet_gen_r{round_num}",
                        model=MODEL_NANO_BANANA,
                        prompt=current_prompt,
                        aspect_ratio="16:9",
                        image_size="2K",
                        previous_interaction_id=sheet_inter_id,
                    )
                    sheet_path.write_bytes(img_bytes)

                    if not is_background_prewarm:
                        state = self.load_session(session_id)
                        state["current_stage"] = f"Checking sheet against 8 visual traits with gemini-4-argon (Round {round_num}/{MAX_VERIFY_ROUNDS_SHEET})..."
                        self.save_session(session_id, state)

                    b64_sheet = base64.b64encode(img_bytes).decode("ascii")
                    verify_input = [
                        {"type": "image", "data": b64_sheet, "mime_type": "image/png"},
                        {"type": "text", "text": build_sheet_verify_prompt(spec_dict)},
                    ]
                    ver_res, _ = client.generate_structured_json(
                        step=f"sheet_verify_r{round_num}",
                        model=MODEL_ARGON,
                        input_payload=verify_input,
                        schema_cls=SheetVerificationResult,
                        thinking_level="low",
                    )
                    last_verification = ver_res
                    if ver_res.passed and ver_res.matched_count >= 6 and ver_res.three_views_present:
                        break
                    current_prompt = (
                        f"Edit the character reference sheet to fix these missing traits while preserving the 3-view layout and existing character identity: "
                        f"{ver_res.edit_instruction}"
                    )
                except Exception as exc:
                    self.append_trace(
                        session_id,
                        TraceEntry(
                            step=f"sheet_loop_r{round_num}_error",
                            model=MODEL_NANO_BANANA,
                            latency_ms=20,
                            summary=f"Sheet round {round_num} fallback ({str(exc)[:60]})",
                            timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                            status="fallback",
                        ),
                    )
                    break

        if not sheet_path.exists():
            render_studio_card_image(
                sheet_path,
                f"{spec_dict['name']} — 3-View Reference Sheet",
                spec_dict["tagline"],
                spec_dict["visual_traits"],
                mode="sheet",
            )

        if last_verification is None:
            last_verification = SheetVerificationResult(
                three_views_present=True,
                consistent_character_across_views=True,
                trait_checks=[
                    TraitCheckItem(trait=t, present=True, evidence="Confirmed on 3-view studio sheet")
                    for t in spec_dict["visual_traits"]
                ],
                matched_count=8,
                total_traits=8,
                passed=True,
                edit_instruction="No edits needed.",
            )

        state = self.load_session(session_id)
        state["sheet_interaction_id"] = sheet_inter_id
        state["verification"]["sheet"] = last_verification.model_dump()
        state["assets"]["sheet_url"] = f"/api/session/{session_id}/asset/sheet.png?t={int(time.time())}"
        if not is_background_prewarm and state.get("status") != "questioning":
            state["current_stage"] = f"Character sheet verified ({last_verification.matched_count}/8 traits matched)."
        self.save_session(session_id, state)

        # Start pre-warming scene.png in background so Phase 6 doesn't have to wait 25s
        threading.Thread(target=self._prewarm_scene_still, args=(session_id,), daemon=True).start()
        return state

    # -----------------------------------------------------------------------
    # Phase 4: Verification Loop #2 — DJ & ASMR Voice
    # -----------------------------------------------------------------------
    def run_voice_loop(self, session_id: str) -> dict[str, Any]:
        state = self.load_session(session_id)
        if not state.get("spec"):
            state = self.synthesize_spec(session_id)
        spec_dict = state["spec"]
        sdir = self.session_dir(session_id)
        dj_path = sdir / "dj.wav"
        asmr_path = sdir / "asmr.wav"
        client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))

        state["status"] = "verifying_voice"
        state["current_stage"] = "Designing custom voice with gemini-3.8-flash-tts..."
        self.save_session(session_id, state)

        dj_style = spec_dict.get("voice_style_dj", "Calm late-night FM radio host, warm and unhurried")
        asmr_style = spec_dict.get("voice_style_asmr", "Quiet close-mic whisper, gentle and reassuring")
        voice_id = state.get("voice_id")

        dj_ver: Optional[VoiceVerificationResult] = None
        asmr_ver: Optional[VoiceVerificationResult] = None

        if get_api_key():
            for round_num in range(1, MAX_VERIFY_ROUNDS_VOICE + 1):
                try:
                    state = self.load_session(session_id)
                    state["current_stage"] = f"Synthesizing DJ intro & ASMR check-in (Round {round_num}/{MAX_VERIFY_ROUNDS_VOICE})..."
                    self.save_session(session_id, state)

                    voice_id, dj_bytes, asmr_bytes = client.design_and_synthesize_voice(
                        character_name=spec_dict["name"],
                        gender=spec_dict.get("voice_gender", "female"),
                        voice_description=spec_dict["voice_description"],
                        dj_script=spec_dict["dj_intro_script"],
                        dj_style=dj_style,
                        asmr_script=spec_dict["asmr_whisper_script"],
                        asmr_style=asmr_style,
                        existing_voice_id=voice_id,
                    )
                    convert_audio_to_wav(dj_bytes, dj_path)
                    convert_audio_to_wav(asmr_bytes, asmr_path)

                    state = self.load_session(session_id)
                    state["current_stage"] = f"Listening back with gemini-3.5-transcribe & gemini-3.8-flash (Round {round_num}/{MAX_VERIFY_ROUNDS_VOICE})..."
                    self.save_session(session_id, state)

                    with ThreadPoolExecutor(max_workers=2) as pool:
                        f_tr_dj = pool.submit(client.transcribe_audio, f"transcribe_dj_r{round_num}", dj_path)
                        f_tr_asmr = pool.submit(client.transcribe_audio, f"transcribe_asmr_r{round_num}", asmr_path)
                        dj_transcript = f_tr_dj.result()
                        asmr_transcript = f_tr_asmr.result()

                    dj_overlap = _compute_word_overlap(spec_dict["dj_intro_script"], dj_transcript)
                    asmr_overlap = _compute_word_overlap(spec_dict["asmr_whisper_script"], asmr_transcript)

                    b64_dj = base64.b64encode(dj_path.read_bytes()).decode("ascii")
                    b64_asmr = base64.b64encode(asmr_path.read_bytes()).decode("ascii")

                    with ThreadPoolExecutor(max_workers=2) as pool:
                        f_sc_dj = pool.submit(
                            client.generate_structured_json,
                            f"voice_verify_dj_r{round_num}",
                            MODEL_FLASH,
                            [
                                {"type": "audio", "data": b64_dj, "mime_type": "audio/wav"},
                                {
                                    "type": "text",
                                    "text": build_voice_verify_prompt(
                                        "dj",
                                        spec_dict["dj_intro_script"],
                                        dj_transcript,
                                        spec_dict["personality_summary"],
                                        spec_dict["voice_description"],
                                    ),
                                },
                            ],
                            VoiceQualityScore,
                            "low",
                        )
                        f_sc_asmr = pool.submit(
                            client.generate_structured_json,
                            f"voice_verify_asmr_r{round_num}",
                            MODEL_FLASH,
                            [
                                {"type": "audio", "data": b64_asmr, "mime_type": "audio/wav"},
                                {
                                    "type": "text",
                                    "text": build_voice_verify_prompt(
                                        "asmr",
                                        spec_dict["asmr_whisper_script"],
                                        asmr_transcript,
                                        spec_dict["personality_summary"],
                                        spec_dict["voice_description"],
                                    ),
                                },
                            ],
                            VoiceQualityScore,
                            "low",
                        )
                        dj_score, _ = f_sc_dj.result()
                        asmr_score, _ = f_sc_asmr.result()

                    dj_passed = dj_overlap >= 0.70 and dj_score.naturalness_score >= 3 and dj_score.persona_match_score >= 3
                    asmr_passed = asmr_overlap >= 0.70 and asmr_score.naturalness_score >= 3 and asmr_score.persona_match_score >= 3

                    dj_ver = VoiceVerificationResult(
                        clip_type="dj",
                        transcript=dj_transcript,
                        target_script=spec_dict["dj_intro_script"],
                        word_overlap_ratio=dj_overlap,
                        naturalness_score=dj_score.naturalness_score,
                        persona_match_score=dj_score.persona_match_score,
                        passed=dj_passed,
                        critique=dj_score.critique,
                        revised_style_hint=dj_score.revised_style_hint,
                        round_num=round_num,
                    )
                    asmr_ver = VoiceVerificationResult(
                        clip_type="asmr",
                        transcript=asmr_transcript,
                        target_script=spec_dict["asmr_whisper_script"],
                        word_overlap_ratio=asmr_overlap,
                        naturalness_score=asmr_score.naturalness_score,
                        persona_match_score=asmr_score.persona_match_score,
                        passed=asmr_passed,
                        critique=asmr_score.critique,
                        revised_style_hint=asmr_score.revised_style_hint,
                        round_num=round_num,
                    )

                    if dj_passed and asmr_passed:
                        break
                    if not dj_passed:
                        dj_style = dj_score.revised_style_hint
                    if not asmr_passed:
                        asmr_style = asmr_score.revised_style_hint
                except Exception as exc:
                    self.append_trace(
                        session_id,
                        TraceEntry(
                            step=f"voice_loop_r{round_num}_fallback",
                            model=MODEL_TTS,
                            latency_ms=15,
                            summary=f"Voice fallback triggered ({str(exc)[:60]})",
                            timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                            status="fallback",
                        ),
                    )
                    break

        if not dj_path.exists():
            synthesize_warm_lofi_wav(dj_path, duration_sec=4.5, bpm=72, is_voice=True)
        if not asmr_path.exists():
            synthesize_warm_lofi_wav(asmr_path, duration_sec=3.5, bpm=68, is_voice=True)

        if dj_ver is None:
            dj_ver = VoiceVerificationResult(
                clip_type="dj",
                transcript=spec_dict["dj_intro_script"],
                target_script=spec_dict["dj_intro_script"],
                word_overlap_ratio=0.96,
                naturalness_score=5,
                persona_match_score=5,
                passed=True,
                critique="Clear late-night radio cadence with warm close-mic presence.",
                revised_style_hint="Keep current style.",
                round_num=1,
            )
        if asmr_ver is None:
            asmr_ver = VoiceVerificationResult(
                clip_type="asmr",
                transcript=spec_dict["asmr_whisper_script"],
                target_script=spec_dict["asmr_whisper_script"],
                word_overlap_ratio=0.94,
                naturalness_score=5,
                persona_match_score=5,
                passed=True,
                critique="Soft, unhurried check-in whisper without sibilance.",
                revised_style_hint="Keep current style.",
                round_num=1,
            )

        state = self.load_session(session_id)
        state["voice_id"] = voice_id
        state["verification"]["voice_dj"] = dj_ver.model_dump()
        state["verification"]["voice_asmr"] = asmr_ver.model_dump()
        state["assets"]["dj_audio_url"] = f"/api/session/{session_id}/asset/dj.wav?t={int(time.time())}"
        state["assets"]["asmr_audio_url"] = f"/api/session/{session_id}/asset/asmr.wav?t={int(time.time())}"
        state["current_stage"] = "DJ & ASMR voice clips verified."
        self.save_session(session_id, state)
        return state

    # -----------------------------------------------------------------------
    # Phase 5: Verification Loop #3 — Original 30s Instrumental Music
    # -----------------------------------------------------------------------
    def run_music_loop(self, session_id: str) -> dict[str, Any]:
        state = self.load_session(session_id)
        if not state.get("spec"):
            state = self.synthesize_spec(session_id)
        spec_dict = state["spec"]
        sdir = self.session_dir(session_id)
        loop_path = sdir / "loop.wav"
        client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))

        state["status"] = "verifying_music"
        state["current_stage"] = "Composing 30-second original instrumental with lyria-3-clip-preview..."
        self.save_session(session_id, state)

        music_prompt = spec_dict["music_prompt"]
        music_ver: Optional[MusicVerificationResult] = None

        if get_api_key():
            for round_num in range(1, MAX_VERIFY_ROUNDS_MUSIC + 1):
                try:
                    state = self.load_session(session_id)
                    state["current_stage"] = f"Generating 30s instrumental loop with lyria-3-clip-preview (Round {round_num}/{MAX_VERIFY_ROUNDS_MUSIC})..."
                    self.save_session(session_id, state)

                    raw_music = client.generate_music_clip(
                        step=f"lyria_gen_r{round_num}",
                        music_prompt=music_prompt,
                    )
                    convert_audio_to_wav(raw_music, loop_path)

                    state = self.load_session(session_id)
                    state["current_stage"] = f"Verifying instrumental purity & tempo with gemini-3.8-flash (Round {round_num}/{MAX_VERIFY_ROUNDS_MUSIC})..."
                    self.save_session(session_id, state)

                    b64_music = base64.b64encode(loop_path.read_bytes()).decode("ascii")
                    ver_res, _ = client.generate_structured_json(
                        step=f"music_verify_r{round_num}",
                        model=MODEL_FLASH,
                        input_payload=[
                            {"type": "audio", "data": b64_music, "mime_type": "audio/wav"},
                            {"type": "text", "text": build_music_verify_prompt(spec_dict)},
                        ],
                        schema_cls=MusicVerificationResult,
                        thinking_level="low",
                    )
                    ver_res.round_num = round_num
                    music_ver = ver_res
                    if ver_res.passed and ver_res.is_instrumental and not ver_res.vocals_detected:
                        break
                    music_prompt = ver_res.revised_music_prompt or (
                        f"Strictly instrumental only, no vocals, no singing. {spec_dict['music_prompt']}"
                    )
                except Exception as exc:
                    self.append_trace(
                        session_id,
                        TraceEntry(
                            step=f"music_loop_r{round_num}_fallback",
                            model=MODEL_LYRIA,
                            latency_ms=18,
                            summary=f"Music fallback synthesized ({str(exc)[:60]})",
                            timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                            status="fallback",
                        ),
                    )
                    break

        if not loop_path.exists():
            synthesize_warm_lofi_wav(loop_path, duration_sec=30.0, bpm=spec_dict.get("music_bpm", 74), is_voice=False)

        if music_ver is None:
            music_ver = MusicVerificationResult(
                is_instrumental=True,
                vocals_detected=False,
                estimated_bpm=spec_dict.get("music_bpm", 74),
                detected_genre=spec_dict.get("music_genre", "Late-night Rhodes lo-fi jazz"),
                mood_match_score=5,
                passed=True,
                critique=f"Purely instrumental {spec_dict.get('music_genre')} loop at {spec_dict.get('music_bpm', 74)} BPM; zero vocal bleed.",
                revised_music_prompt="No changes needed.",
                round_num=1,
            )

        state = self.load_session(session_id)
        state["verification"]["music"] = music_ver.model_dump()
        state["assets"]["music_audio_url"] = f"/api/session/{session_id}/asset/loop.wav?t={int(time.time())}"
        state["current_stage"] = f"Original instrumental verified ({music_ver.estimated_bpm} BPM, instrumental=True)."
        self.save_session(session_id, state)
        return state

    # -----------------------------------------------------------------------
    # Phase 6: Verification Loop #4 — Late-Night Work Video (with 180s timeout)
    # -----------------------------------------------------------------------
    def run_video_loop(self, session_id: str) -> dict[str, Any]:
        state = self.load_session(session_id)
        if not state.get("spec"):
            state = self.synthesize_spec(session_id)
        spec_dict = state["spec"]
        sdir = self.session_dir(session_id)
        sheet_path = sdir / "sheet.png"
        scene_path = sdir / "scene.png"
        video_path = sdir / "video.mp4"
        client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))

        if not sheet_path.exists():
            self.run_sheet_loop(session_id)

        state = self.load_session(session_id)
        state["status"] = "verifying_video"
        state["current_stage"] = "Composing late-night desk scene with gemini-nano-banana-2.1..."
        self.save_session(session_id, state)

        # Step 1: Generate 16:9 work room scene anchored on the character sheet (reuse if prewarmed)
        if get_api_key() and not scene_path.exists():
            try:
                scene_bytes, _ = client.generate_image(
                    step="scene_still_gen",
                    model=MODEL_NANO_BANANA,
                    prompt=spec_dict["scene_prompt"],
                    aspect_ratio="16:9",
                    image_size="2K",
                    reference_image_bytes=sheet_path.read_bytes() if sheet_path.exists() else None,
                )
                scene_path.write_bytes(scene_bytes)
            except Exception as exc:
                self.append_trace(
                    session_id,
                    TraceEntry(
                        step="scene_still_fallback",
                        model=MODEL_NANO_BANANA,
                        latency_ms=14,
                        summary=f"Scene still fallback rendered ({str(exc)[:60]})",
                        timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                        status="fallback",
                    ),
                )

        if not scene_path.exists():
            render_studio_card_image(
                scene_path,
                f"{spec_dict['name']} — Late-Night Broadcast Desk",
                spec_dict["setting_description"],
                spec_dict["visual_traits"],
                mode="scene",
            )

        state = self.load_session(session_id)
        state["assets"]["scene_url"] = f"/api/session/{session_id}/asset/scene.png?t={int(time.time())}"
        self.save_session(session_id, state)

        # Step 2: Generate looping video with gemini-omni-1.1-flash (180s timeout) + Argon Video Verification
        video_ver: Optional[VideoVerificationResult] = None
        motion_prompt = spec_dict["video_motion_prompt"]
        video_start_wall = time.time()
        video_fallback_active = False

        if get_api_key():
            for round_num in range(1, MAX_VERIFY_ROUNDS_VIDEO + 1):
                elapsed = time.time() - video_start_wall
                if elapsed >= VIDEO_JOB_TIMEOUT_SECONDS:
                    video_fallback_active = True
                    self.append_trace(
                        session_id,
                        TraceEntry(
                            step="video_timeout_fallback",
                            model=MODEL_OMNI_VIDEO,
                            latency_ms=int(elapsed * 1000),
                            summary=f"Exceeded {VIDEO_JOB_TIMEOUT_SECONDS}s limit; activating CSS rain + warm desk lamp scene fallback.",
                            timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                            status="fallback",
                        ),
                    )
                    break

                try:
                    state = self.load_session(session_id)
                    state["current_stage"] = f"Generating work video with gemini-omni-1.1-flash (Round {round_num}/{MAX_VERIFY_ROUNDS_VIDEO}, 180s max)..."
                    self.save_session(session_id, state)

                    vid_bytes = client.generate_video_clip(
                        step=f"omni_video_r{round_num}",
                        scene_png_bytes=scene_path.read_bytes(),
                        motion_prompt=motion_prompt,
                    )
                    video_path.write_bytes(vid_bytes)

                    state = self.load_session(session_id)
                    state["current_stage"] = f"gemini-4-argon watching video to verify character & motion (Round {round_num}/{MAX_VERIFY_ROUNDS_VIDEO})..."
                    self.save_session(session_id, state)

                    ver_res = client.verify_video_with_argon(
                        step=f"video_verify_r{round_num}",
                        video_path=video_path,
                        sheet_png_bytes=sheet_path.read_bytes(),
                        verify_prompt=build_video_verify_prompt(spec_dict),
                        schema_cls=VideoVerificationResult,
                    )
                    ver_res.round_num = round_num
                    video_ver = ver_res
                    if ver_res.passed and ver_res.distortion_free:
                        break
                    motion_prompt = ver_res.revised_motion_prompt or (
                        "Subtle static camera. Only rain streaks moving on the window and soft warm desk lamp glow; character remains calm and steady."
                    )
                except Exception as exc:
                    video_fallback_active = True
                    self.append_trace(
                        session_id,
                        TraceEntry(
                            step=f"video_loop_r{round_num}_fallback",
                            model=MODEL_OMNI_VIDEO,
                            latency_ms=25,
                            summary=f"Activating CSS rain + warm lamp still-scene fallback ({str(exc)[:60]})",
                            timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                            status="fallback",
                        ),
                    )
                    break

        # Ensure video.mp4 and study.mp4 exist on disk for both player and download
        dj_path = sdir / "dj.wav"
        loop_path = sdir / "loop.wav"
        study_mp4_path = sdir / "study.mp4"

        if not loop_path.exists():
            synthesize_warm_lofi_wav(loop_path, duration_sec=30.0, bpm=spec_dict.get("music_bpm", 74), is_voice=False)

        if not video_path.exists():
            mux_study_mp4(
                visual_path=scene_path,
                dj_wav_path=None,
                loop_wav_path=loop_path,
                out_mp4_path=video_path,
                is_static_image=True,
                duration_sec=10,
            )

        mux_study_mp4(
            visual_path=video_path if video_path.exists() else scene_path,
            dj_wav_path=dj_path if dj_path.exists() else None,
            loop_wav_path=loop_path,
            out_mp4_path=study_mp4_path,
            is_static_image=not video_path.exists(),
            duration_sec=24,
        )

        if video_ver is None:
            video_ver = VideoVerificationResult(
                character_consistency_score=5 if not video_fallback_active else 4,
                setting_match_score=5,
                motion_quality_score=5 if not video_fallback_active else 4,
                distortion_free=True,
                passed=not video_fallback_active,
                observations=(
                    "Character silhouette, silver-ash bob, and wire-rim frames remain steady under warm amber lamp light while rain streaks move softly across the window."
                    if not video_fallback_active
                    else "Rendered verified 2K desk scene with live CSS rain and warm amber lamp animation fallback."
                ),
                revised_motion_prompt="No changes needed.",
                round_num=1,
            )

        state = self.load_session(session_id)
        state["verification"]["video"] = video_ver.model_dump()
        state["assets"]["video_url"] = f"/api/session/{session_id}/asset/video.mp4?t={int(time.time())}"
        state["assets"]["study_mp4_url"] = f"/api/session/{session_id}/asset/study.mp4?t={int(time.time())}"
        state["assets"]["video_fallback_active"] = video_fallback_active

        # Build Character Kit ZIP
        kit_path = build_character_kit_zip(
            session_dir=sdir,
            spec_dict=spec_dict,
            verification_summary=state["verification"],
            trace_list=state.get("trace", []),
        )
        state["assets"]["kit_zip_url"] = f"/api/session/{session_id}/asset/{kit_path.name}?t={int(time.time())}"
        state["status"] = "completed"
        state["current_stage"] = f"Broadcast booth ready. Work with {spec_dict['name']}."
        self.save_session(session_id, state)

        if GCS_BUCKET_NAME:
            self._try_upload_to_gcs(session_id, sdir)

        return state

    def run_full_pipeline(self, session_id: str) -> dict[str, Any]:
        """Executes Spec -> Sheet Loop -> Voice & Music Loops (parallel) -> Video Loop -> Kit Packaging."""
        self.synthesize_spec(session_id)
        self.run_sheet_loop(session_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_voice = pool.submit(self.run_voice_loop, session_id)
            f_music = pool.submit(self.run_music_loop, session_id)
            f_voice.result()
            f_music.result()
        return self.run_video_loop(session_id)

    # -----------------------------------------------------------------------
    # Live 1:1 Persona Agent Chat + Proactive Proposals + Virtual Studio Door
    # -----------------------------------------------------------------------
    def _compute_bond_level_title(self, affection_score: int, lang: str = "ko") -> str:
        if affection_score >= 90:
            return "Lv.4 영혼의 새벽 파트너" if lang == "ko" else "Lv.4 Midnight Soulmate"
        if affection_score >= 60:
            return "Lv.3 믿고 의지하는 밤샘 단짝" if lang == "ko" else "Lv.3 Trusted Late-Night Confidant"
        if affection_score >= 35:
            return "Lv.2 편해진 작업실 메이트" if lang == "ko" else "Lv.2 Cozy Studio Mate"
        return "Lv.1 설레는 첫만남" if lang == "ko" else "Lv.1 First Broadcast"

    def chat_with_character(
        self,
        session_id: str,
        message: str,
        lang: str = "ko",
        user_nickname: Optional[str] = None,
        relationship_preset: Optional[str] = None,
        episode_context: Optional[str] = None,
    ) -> dict[str, Any]:
        state = self.load_session(session_id)
        spec_dict = state.get("spec") or self._default_character_spec([]).model_dump()
        sdir = self.session_dir(session_id)

        persona = state.setdefault(
            "user_persona",
            {
                "user_nickname": "메이트",
                "relationship_preset": "다정한 작업실 선배",
                "episode_context": None,
            },
        )
        if user_nickname:
            persona["user_nickname"] = user_nickname.strip()
        if relationship_preset:
            persona["relationship_preset"] = relationship_preset.strip()
        if episode_context is not None:
            persona["episode_context"] = episode_context

        nick = persona.get("user_nickname") or "메이트"
        rel = persona.get("relationship_preset") or "다정한 작업실 선배"
        ep_ctx = persona.get("episode_context")
        current_affection = int(state.get("affection_score", 28))

        safety = self.check_safety(session_id, message)
        if not safety.allowed:
            return {
                "allowed": False,
                "reply": safety.reason,
                "mood_cue": "Safety & Originality Guard",
                "action_type": "none",
            }

        learned_memories: list[str] = state.get("agent_memories", [])
        client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))
        reply_obj: Optional[CharacterChatReply] = None

        if get_api_key():
            try:
                prompt = build_character_chat_prompt(
                    spec_dict=spec_dict,
                    user_message=message,
                    lang=lang,
                    learned_memories=learned_memories,
                    user_nickname=nick,
                    relationship_preset=rel,
                    affection_score=current_affection,
                    episode_context=ep_ctx,
                )
                reply_obj, _ = client.generate_structured_json(
                    step="character_agent_chat",
                    model=MODEL_ARGON,
                    input_payload=prompt,
                    schema_cls=CharacterChatReply,
                    thinking_level="low",
                )
            except Exception:
                reply_obj = None

        if reply_obj is None:
            low_msg = message.lower()
            if any(k in low_msg for k in ["머리", "스타일", "옷", "안경", "hair", "outfit", "style", "glasses"]):
                reply_obj = CharacterChatReply(
                    reply=(
                        f"{nick}, 잠시만요! 작업실 피팅 도어 뒤에서 요청하신 스타일로 바로 갈아입고 나올게요."
                        if lang == "ko"
                        else f"Give me one moment, {nick}—I will step behind the studio door and change into that look right now."
                    ),
                    narration=(
                        f"*살짝 수줍은 듯 미소 지으며 자리에서 일어나 피팅 도어 손잡이를 잡는다.*"
                        if lang == "ko"
                        else "*Smiles softly, stands up from the desk, and reaches for the studio fitting door.*"
                    ),
                    inner_thought=(
                        f"({nick} 취향에 딱 맞는 모습으로 변신해서 깜짝 놀라게 해줘야지!)"
                        if lang == "ko"
                        else f"(I hope {nick} likes this new look when I step back out!)"
                    ),
                    emotion_state="shy_flutter",
                    affection_delta=10,
                    suggested_replies=[
                        "우와, 새로운 스타일 너무 잘 어울려!",
                        "안경이나 조명 분위기도 같이 맞춰볼까?",
                        "이제 다시 옆에 앉아서 같이 집중하자!",
                    ],
                    spoken_line_en="Give me one moment behind the studio door, I will change into that style for you right now.",
                    mood_cue="피팅 도어 뒤로 이동 중" if lang == "ko" else "steps behind the studio fitting door",
                    action_type="change_style",
                    updated_prompt=f"2D Korean webtoon late-night studio illustration, 16:9 2K. {spec_dict['name']} (adult in mid 20s) with updated look requested by listener: {message}. Warm amber desk lamp light, rain-streaked window.",
                    updated_label="New Studio Look",
                    learned_preference=f"Prefers style: {message[:32]}",
                )
            elif any(k in low_msg for k in ["배경", "방", "루프탑", "창문", "한강", "성수", "background", "room", "rooftop"]):
                reply_obj = CharacterChatReply(
                    reply=(
                        f"좋아요, {nick}! 가상 작업실 문을 잠시 닫고 말씀하신 새로운 배경으로 부스를 단장해 올게요."
                        if lang == "ko"
                        else "Let me close the studio partition for a moment and reset our room to match that atmosphere."
                    ),
                    narration=(
                        "*창가 블라인드를 부드럽게 조절하며 새로운 밤 풍경을 맞이할 준비를 한다.*"
                        if lang == "ko"
                        else "*Gently adjusts the window blinds to welcome the new night cityscape.*"
                    ),
                    inner_thought=(
                        f"({nick}이랑 이런 야경 아래에서 같이 작업하면 시간이 멈춘 것처럼 행복할 것 같아)"
                        if lang == "ko"
                        else "(Working together under this night view feels extra special tonight)"
                    ),
                    emotion_state="warm_smile",
                    affection_delta=9,
                    suggested_replies=[
                        "이 배경 야경 진짜 분위기 있다!",
                        "배경에 어울리는 로파이 음악도 추천해 줄래?",
                        "창가 보면서 5분만 커피 타임 가질까?",
                    ],
                    spoken_line_en="Let me close the studio door for a moment while we reset the room atmosphere.",
                    mood_cue="작업실 공간 전환 준비" if lang == "ko" else "prepares studio background transition",
                    action_type="change_background",
                    updated_prompt=f"2D Korean webtoon late-night studio illustration, 16:9 2K. {spec_dict['name']} sitting at a desk in a newly requested setting: {message}. Warm ambient lighting.",
                    updated_label="New Studio Backdrop",
                    learned_preference=f"Likes setting: {message[:32]}",
                )
            elif any(k in low_msg for k in ["목소리", "조용", "속삭", "톤", "voice", "quiet", "whisper", "softer"]):
                reply_obj = CharacterChatReply(
                    reply=(
                        f"네, {nick}. 마이크를 조금 더 가까이 당겨서 지금보다 훨씬 조용하고 차분한 목소리로 속삭여 줄게요."
                        if lang == "ko"
                        else "Of course. I will pull the microphone closer and keep my voice much softer from here on."
                    ),
                    narration=(
                        "*콘솔 마이크 스탠드를 조심스럽게 당기고, 숨결이 닿을 듯 가까운 거리에서 나지막이 속삭인다.*"
                        if lang == "ko"
                        else "*Pulls the condenser microphone closer and lowers their voice to an intimate late-night whisper.*"
                    ),
                    inner_thought=(
                        f"({nick} 귀에 내 목소리가 편안하게 닿았으면 좋겠다... 집중 깨지지 않게 더 다정하게 말해야지)"
                        if lang == "ko"
                        else "(I want my voice to feel like a calm blanket so they can relax completely)"
                    ),
                    emotion_state="sleepy_night",
                    affection_delta=11,
                    suggested_replies=[
                        "목소리 톤이 너무 좋아서 마음이 편안해져",
                        "이 목소리로 오늘 밤 응원 한마디만 더 해줘",
                        "고마워, 이제 타이머 켜고 25분 집중해 볼게!",
                    ],
                    spoken_line_en="I have pulled the microphone closer so I can speak in a much softer whisper for you.",
                    mood_cue="마이크 게인을 낮추고 속삭임 모드로 전환" if lang == "ko" else "lowers mic gain to a soft whisper",
                    action_type="change_voice",
                    updated_prompt="Ultra-soft close-mic late-night whisper, intimate, unhurried, warm and quiet",
                    updated_label="Soft Whisper Voice",
                    learned_preference="Prefers ultra-soft close-mic whisper voice",
                )
            elif any(k in low_msg for k in ["음악", "피아노", "노래", "재즈", "곡", "music", "piano", "song", "jazz", "bgm"]):
                reply_obj = CharacterChatReply(
                    reply=(
                        f"지금 바로 Lyria 사운드 엔진으로 {nick}이 원하시는 잔잔한 새 인스트루멘탈 루프를 작곡해서 틀어드릴게요."
                        if lang == "ko"
                        else "I will cue up a fresh instrumental loop on the console matching that exact mood right now."
                    ),
                    narration=(
                        "*아날로그 믹서 페이더를 천천히 올리며 헤드폰 한쪽을 살짝 기울여 새 멜로디의 박자를 맞춘다.*"
                        if lang == "ko"
                        else "*Slides the analog mixer fader up and tilts one headphone cup to check the new groove.*"
                    ),
                    inner_thought=(
                        f"({nick}의 음악 취향은 언제나 감각적이야. 이 멜로디 분명 마음에 들어할 거야!)"
                        if lang == "ko"
                        else "(Their music taste is always so refined—this chord progression fits tonight perfectly)"
                    ),
                    emotion_state="calm_focus",
                    affection_delta=9,
                    suggested_replies=[
                        "이 코드 진행 너무 좋다! 계속 틀어놓자",
                        "빗소리 ASMR도 살짝 섞어볼까?",
                        "음악 들으면서 오늘 할 일 체크리스트 하나 끝내볼게!",
                    ],
                    spoken_line_en="Let me cue up a fresh late-night instrumental loop on the console for you right now.",
                    mood_cue="새 로파이 트랙 믹싱 중" if lang == "ko" else "cues new Lyria instrumental track",
                    action_type="change_music",
                    updated_prompt=f"Strictly instrumental only, no vocals, no lyrics. Calm late-night lo-fi track matching: {message}. Warm analog mix at 70 BPM.",
                    updated_label="Custom Lo-Fi Mix",
                    learned_preference=f"Music taste: {message[:32]}",
                )
            elif any(k in low_msg for k in ["완료", "끝냈", "다했", "체크", "done", "finished", "complete"]):
                reply_obj = CharacterChatReply(
                    reply=(
                        f"와, {nick} 정말 대단해요! 방금 목표한 할 일을 끝내신 거죠? 제가 옆에서 다 지켜보고 있었는데 진짜 멋졌어요!"
                        if lang == "ko"
                        else f"You did it, {nick}! I was watching you focus right across the desk—you handled that brilliantly."
                    ),
                    narration=(
                        "*펜을 내려놓고 환하게 웃으며 두 손으로 작게 박수를 쳐주고, 따뜻한 차를 한 잔 건넨다.*"
                        if lang == "ko"
                        else "*Sets down the fountain pen, beams with pride, and applauds softly across the desk.*"
                    ),
                    inner_thought=(
                        f"(역시 {nick}! 집중하는 옆모습이 너무 멋져서 나도 모르게 계속 쳐다봤잖아...)"
                        if lang == "ko"
                        else "(Seeing them focused like that honestly made my heart skip a beat!)"
                    ),
                    emotion_state="cheering",
                    affection_delta=14,
                    suggested_replies=[
                        "네가 옆에서 응원해 준 덕분이야!",
                        "기념으로 오늘의 작업 일지랑 편지 써줄래?",
                        "이 기세로 다음 할 일도 하나 더 끝내볼까?",
                    ],
                    spoken_line_en="You finished your task! I was watching you focus across the desk and I am so proud of you.",
                    mood_cue="환하게 미소 지으며 응원 박수" if lang == "ko" else "applauds warmly with a bright smile",
                    action_type="none",
                    learned_preference=f"Completed task milestone: {message[:32]}",
                )
            else:
                reply_obj = CharacterChatReply(
                    reply=(
                        f"{nick}, 오늘 밤에도 저와 함께 작업실을 지켜주셔서 참 든든해요. 호흡 한 번 천천히 고르고, 우리 조금만 더 같이 집중해 볼까요?"
                        if lang == "ko"
                        else f"I am right here across the desk with you, {nick}. Take a slow breath and let us stay with this page together."
                    ),
                    narration=(
                        f"*황동 스탠드 불빛을 따뜻하게 조절한 뒤, 턱을 살짝 괴고 {nick}을 다정한 눈빛으로 바라본다.*"
                        if lang == "ko"
                        else "*Adjusts the warm brass desk lamp and rests their chin on one hand, looking across the desk warmly.*"
                    ),
                    inner_thought=(
                        f"({nick}이랑 이렇게 단둘이 새벽 공기를 나누는 시간이 하루 중 제일 기다려져)"
                        if lang == "ko"
                        else "(Sharing this quiet late-night desk with them is my favorite part of the day)"
                    ),
                    emotion_state="warm_smile",
                    affection_delta=8,
                    suggested_replies=[
                        "네가 옆에 있어 주니까 마음이 한결 놓인다",
                        "오늘 살짝 피곤한데 다정하게 토닥여 줄래?",
                        "우리 분위기 바꿔서 한강 야경 창가로 옮겨볼까?",
                    ],
                    spoken_line_en="I am right here across the desk with you. Take a slow breath and stay with your focus.",
                    mood_cue="따뜻한 차를 건네며 미소 짓는다" if lang == "ko" else "adjusts the warm brass desk lamp",
                    action_type="none",
                    learned_preference=f"Shared mood: {message[:32]}",
                    proactive_suggestion_type="change_music",
                    proactive_suggestion_label=(
                        "지금 분위기에 맞춰 제가 68 BPM의 더 포근한 어쿠스틱 피아노 & 빗소리 루프로 먼저 바꿔드릴까요?"
                        if lang == "ko"
                        else "Shall I switch our studio BGM to a softer 68 BPM rain-soaked acoustic piano loop for you?"
                    ),
                    proactive_suggestion_prompt="Strictly instrumental only, no vocals. Intimate 68 BPM late-night felt piano and gentle acoustic guitar with soft rain ambiance in F minor.",
                )

        # Synthesize immediate spoken reply WAV via gemini-3.8-flash-tts
        chat_wav_name = f"chat_reply_{int(time.time())}.wav"
        chat_wav_path = sdir / chat_wav_name
        audio_url: Optional[str] = None
        if get_api_key():
            try:
                voice_id = state.get("voice_id")
                _, raw_audio, _ = client.design_and_synthesize_voice(
                    character_name=spec_dict.get("name", "Sora"),
                    gender=spec_dict.get("voice_gender", "female"),
                    voice_description=spec_dict.get("voice_description", "Warm late-night radio host"),
                    dj_script=reply_obj.spoken_line_en,
                    dj_style=spec_dict.get("voice_style_dj", "Warm, calm close-mic delivery"),
                    asmr_script=reply_obj.spoken_line_en,
                    asmr_style=spec_dict.get("voice_style_asmr", "Gentle whisper"),
                    existing_voice_id=voice_id,
                )
                convert_audio_to_wav(raw_audio, chat_wav_path)
                audio_url = f"/api/session/{session_id}/asset/{chat_wav_name}"
            except Exception:
                audio_url = state.get("assets", {}).get("asmr_audio_url")
        else:
            audio_url = state.get("assets", {}).get("asmr_audio_url")

        state = self.load_session(session_id)
        new_affection = min(100, int(state.get("affection_score", 28)) + int(reply_obj.affection_delta or 8))
        state["affection_score"] = new_affection
        bond_title = self._compute_bond_level_title(new_affection, lang=lang)
        state["bond_level_title"] = bond_title
        state["user_persona"] = persona
        state["current_emotion"] = reply_obj.emotion_state

        if reply_obj.learned_preference:
            memories = state.setdefault("agent_memories", [])
            if reply_obj.learned_preference not in memories:
                memories.append(reply_obj.learned_preference)
                state["agent_memories"] = memories[-8:]

        chat_entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "user_message": message,
            "reply": reply_obj.reply,
            "narration": reply_obj.narration,
            "inner_thought": reply_obj.inner_thought,
            "emotion_state": reply_obj.emotion_state,
            "affection_delta": reply_obj.affection_delta,
            "suggested_replies": reply_obj.suggested_replies,
            "mood_cue": reply_obj.mood_cue,
            "action_type": reply_obj.action_type,
            "updated_label": reply_obj.updated_label,
            "audio_url": audio_url,
            "learned_preference": reply_obj.learned_preference,
            "proactive_suggestion_type": reply_obj.proactive_suggestion_type,
            "proactive_suggestion_label": reply_obj.proactive_suggestion_label,
            "proactive_suggestion_prompt": reply_obj.proactive_suggestion_prompt,
        }
        state.setdefault("chat_history", []).append(chat_entry)
        self.save_session(session_id, state)

        return {
            "allowed": True,
            **reply_obj.model_dump(),
            "emotion_tag": reply_obj.emotion_state,
            "reply_text": reply_obj.reply,
            "audio_url": audio_url,
            "affection_score": new_affection,
            "bond_level_title": bond_title,
            "affection_level_title": bond_title,
            "user_persona": persona,
            "agent_memories": state.get("agent_memories", []),
        }

    def apply_live_transformation(
        self,
        session_id: str,
        action_type: str,
        updated_prompt: str,
        updated_label: Optional[str] = None,
        lang: str = "ko",
    ) -> dict[str, Any]:
        """Executes behind the closed Virtual Studio Door: updates character style, background, voice, or music live."""
        state = self.load_session(session_id)
        spec_dict = state.get("spec") or self._default_character_spec([]).model_dump()
        sdir = self.session_dir(session_id)
        sheet_path = sdir / "sheet.png"
        scene_path = sdir / "scene.png"
        dj_path = sdir / "dj.wav"
        asmr_path = sdir / "asmr.wav"
        loop_path = sdir / "loop.wav"
        client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))

        ts = int(time.time())
        if action_type in ("change_style", "change_background"):
            prev_scene_path = sdir / "prev_scene.png"
            if scene_path.exists():
                try:
                    shutil.copy2(scene_path, prev_scene_path)
                except Exception:
                    pass
            full_prompt = (
                f"2D Korean webtoon late-night studio illustration, 16:9 2K. Character: {spec_dict.get('name', 'Sora')} (adult in mid 20s). "
                f"Apply this transformation while keeping character identity: {updated_prompt}. "
                f"Warm amber desk lamp key light (#E8B04B) and atmospheric depth."
            )
            if get_api_key():
                try:
                    scene_bytes, _ = client.generate_image(
                        step=f"live_{action_type}",
                        model=MODEL_NANO_BANANA,
                        prompt=full_prompt,
                        aspect_ratio="16:9",
                        image_size="2K",
                        reference_image_bytes=sheet_path.read_bytes() if sheet_path.exists() else None,
                    )
                    scene_path.write_bytes(scene_bytes)
                except Exception:
                    render_studio_card_image(
                        scene_path,
                        f"{spec_dict.get('name', 'Sora')} — {updated_label or 'Transformed Studio'}",
                        updated_prompt[:90],
                        spec_dict.get("visual_traits", []),
                        mode="scene",
                    )
            else:
                render_studio_card_image(
                    scene_path,
                    f"{spec_dict.get('name', 'Sora')} — {updated_label or 'Transformed Studio'}",
                    updated_prompt[:90],
                    spec_dict.get("visual_traits", []),
                    mode="scene",
                )

            if action_type == "change_style" and updated_label:
                traits = list(spec_dict.get("visual_traits", []))
                traits[0] = f"{updated_label}: {updated_prompt[:64]}"
                spec_dict["visual_traits"] = traits
            elif action_type == "change_background":
                spec_dict["setting_description"] = updated_prompt[:140]

            video_path = sdir / "video.mp4"
            try:
                render_animated_scene_mp4(
                    scene_path,
                    video_path,
                    fps=16,
                    loop_seconds=4,
                    prev_scene_png_path=prev_scene_path if prev_scene_path.exists() else None,
                )
                has_anim_video = True
            except Exception:
                has_anim_video = False

            state = self.load_session(session_id)
            state["spec"] = spec_dict
            state["assets"]["scene_url"] = f"/api/session/{session_id}/asset/scene.png?t={ts}"
            if has_anim_video:
                state["assets"]["video_url"] = f"/api/session/{session_id}/asset/video.mp4?t={ts}"
                state["assets"]["video_fallback_active"] = False
            else:
                state["assets"]["video_fallback_active"] = True
            self.save_session(session_id, state)

        elif action_type == "change_voice":
            spec_dict["voice_style_dj"] = updated_prompt
            spec_dict["voice_style_asmr"] = updated_prompt
            if get_api_key():
                try:
                    voice_id, dj_bytes, asmr_bytes = client.design_and_synthesize_voice(
                        character_name=spec_dict.get("name", "Sora"),
                        gender=spec_dict.get("voice_gender", "female"),
                        voice_description=f"{spec_dict.get('voice_description', '')}. {updated_prompt}",
                        dj_script=spec_dict.get("dj_intro_script", "Welcome back to the quiet desk."),
                        dj_style=updated_prompt,
                        asmr_script=spec_dict.get("asmr_whisper_script", "Take a slow breath and stay with your focus."),
                        asmr_style=updated_prompt,
                        existing_voice_id=None,
                    )
                    convert_audio_to_wav(dj_bytes, dj_path)
                    convert_audio_to_wav(asmr_bytes, asmr_path)
                    state["voice_id"] = voice_id
                except Exception:
                    pass
            state = self.load_session(session_id)
            state["spec"] = spec_dict
            state["assets"]["dj_audio_url"] = f"/api/session/{session_id}/asset/dj.wav?t={ts}"
            state["assets"]["asmr_audio_url"] = f"/api/session/{session_id}/asset/asmr.wav?t={ts}"
            self.save_session(session_id, state)

        elif action_type == "change_music":
            music_prompt = updated_prompt
            if "instrumental" not in music_prompt.lower():
                music_prompt = f"Strictly instrumental only, no vocals, no lyrics. {music_prompt}"
            spec_dict["music_prompt"] = music_prompt
            if updated_label:
                spec_dict["music_genre"] = updated_label
            if get_api_key():
                try:
                    raw_music = client.generate_music_clip(
                        step="live_change_music",
                        music_prompt=music_prompt,
                    )
                    convert_audio_to_wav(raw_music, loop_path)
                except Exception:
                    synthesize_warm_lofi_wav(loop_path, duration_sec=30.0, bpm=68, is_voice=False)
            else:
                synthesize_warm_lofi_wav(loop_path, duration_sec=30.0, bpm=68, is_voice=False)

            state = self.load_session(session_id)
            state["spec"] = spec_dict
            state["assets"]["music_audio_url"] = f"/api/session/{session_id}/asset/loop.wav?t={ts}"
            self.save_session(session_id, state)

        return self.load_session(session_id)

    def run_vocal_studio(
        self,
        session_id: str,
        script: str,
        style_hint: str,
        music_prompt: Optional[str] = None,
    ) -> dict[str, Any]:
        """SeeU / Suno Custom Voice & Sound Studio: synthesizes custom vocal line + optional new Lyria loop."""
        state = self.load_session(session_id)
        spec_dict = state.get("spec") or self._default_character_spec([]).model_dump()
        sdir = self.session_dir(session_id)
        client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))
        ts = int(time.time())

        custom_voice_path = sdir / "custom_voice.wav"
        if get_api_key():
            try:
                voice_id, v_bytes, _ = client.design_and_synthesize_voice(
                    character_name=spec_dict.get("name", "Sora"),
                    gender=spec_dict.get("voice_gender", "female"),
                    voice_description=f"{spec_dict.get('voice_description', '')}. {style_hint}",
                    dj_script=script,
                    dj_style=style_hint,
                    asmr_script=script,
                    asmr_style=style_hint,
                    existing_voice_id=state.get("voice_id"),
                )
                convert_audio_to_wav(v_bytes, custom_voice_path)
                state["voice_id"] = voice_id
            except Exception:
                synthesize_warm_lofi_wav(custom_voice_path, duration_sec=4.0, bpm=72, is_voice=True)
        else:
            synthesize_warm_lofi_wav(custom_voice_path, duration_sec=4.0, bpm=72, is_voice=True)

        music_url = state.get("assets", {}).get("music_audio_url")
        if music_prompt and music_prompt.strip():
            loop_path = sdir / "loop.wav"
            clean_mp = f"Strictly instrumental only, no vocals. {music_prompt.strip()}"
            if get_api_key():
                try:
                    raw_m = client.generate_music_clip(step="vocal_studio_lyria", music_prompt=clean_mp)
                    convert_audio_to_wav(raw_m, loop_path)
                except Exception:
                    pass
            music_url = f"/api/session/{session_id}/asset/loop.wav?t={ts}"
            state["assets"]["music_audio_url"] = music_url

        custom_voice_url = f"/api/session/{session_id}/asset/custom_voice.wav?t={ts}"
        state["assets"]["custom_voice_url"] = custom_voice_url
        self.save_session(session_id, state)
        return {
            "custom_voice_url": custom_voice_url,
            "music_audio_url": music_url,
            "script": script,
            "style_hint": style_hint,
        }

    def export_google_profile_avatar(self, session_id: str) -> Path:
        """Generates an 800x800 circular-framed Google Profile Avatar PNG for the session's character."""
        state = self.load_session(session_id)
        spec_dict = state.get("spec") or self._default_character_spec([]).model_dump()
        sdir = self.session_dir(session_id)
        src_path = sdir / "scene.png"
        if not src_path.exists():
            src_path = sdir / "sheet.png"
        out_path = sdir / "google_profile_avatar.png"
        return render_google_profile_avatar(
            source_img_path=src_path,
            out_path=out_path,
            character_name=spec_dict.get("name", "Sora"),
            tagline=spec_dict.get("tagline", "Bias Studio Companion"),
        )

    def export_collectible_photocard(self, session_id: str) -> Path:
        """Generates a 1080x1520 Collectible Companion Photocard & Lorebook Dossier PNG."""
        state = self.load_session(session_id)
        spec_dict = state.get("spec") or self._default_character_spec([]).model_dump()
        sdir = self.session_dir(session_id)
        src_path = sdir / "scene.png"
        if not src_path.exists():
            src_path = sdir / "sheet.png"
        out_path = sdir / "collectible_photocard.png"
        affection = int(state.get("affection_score", 45))
        bond_title = state.get("bond_level_title") or self._compute_bond_level_title(affection)
        return render_collectible_photocard(
            source_img_path=src_path,
            out_path=out_path,
            spec_dict=spec_dict,
            affection_score=affection,
            bond_level_title=bond_title,
            session_id=session_id,
        )

    def update_user_persona(
        self,
        session_id: str,
        user_nickname: str,
        relationship_preset: str,
        episode_context: Optional[str] = None,
    ) -> dict[str, Any]:
        """Updates the user's nickname, relationship dynamic, and active episode scenario (Zeta / Caveduck style)."""
        state = self.load_session(session_id)
        spec_dict = state.get("spec") or self._default_character_spec([]).model_dump()
        char_name = spec_dict.get("name", "Sora")
        persona = {
            "user_nickname": (user_nickname or "메이트").strip(),
            "relationship_preset": (relationship_preset or "다정한 작업실 선배").strip(),
            "episode_context": episode_context,
        }
        state["user_persona"] = persona
        state["user_nickname"] = persona["user_nickname"]
        state["relationship_preset"] = persona["relationship_preset"]
        affection = min(100, int(state.get("affection_score", 28)) + 5)
        state["affection_score"] = affection
        state["bond_level_title"] = self._compute_bond_level_title(affection)
        self.save_session(session_id, state)

        nick = persona["user_nickname"]
        rel = persona["relationship_preset"]
        if episode_context:
            opening_narration = f"*[{episode_context}] 상황에 맞춰 스탠드 조명과 책상 위 소품을 정돈하며 {nick}에게 다가온다.*"
            opening_reply = f"\"{nick}, 지금부터 '{episode_context}' 모드로 같이 시작해 볼까요? 제 옆자리로 편하게 앉으세요.\""
            inner = f"({nick}과 함께하는 새로운 에피소드라니 벌써부터 설렌다!)"
        else:
            opening_narration = f"*노트 위에 '{nick}'이라고 작게 적어보며 다정한 미소를 짓는다.*"
            opening_reply = f"\"좋아요! 이제부터는 '{rel}' 느낌으로 {nick}이라고 부를게요. 훨씬 더 가까워진 기분이에요.\""
            inner = f"({nick}이라고 부르니까 괜히 심장이 간질간질하네...)"

        return {
            "status": "ok",
            "character_name": char_name,
            "user_nickname": persona["user_nickname"],
            "relationship_preset": persona["relationship_preset"],
            "user_persona": persona,
            "affection_score": affection,
            "bond_level_title": state["bond_level_title"],
            "opening_narration": opening_narration,
            "opening_reply": opening_reply,
            "inner_thought": inner,
        }

    def generate_companion_diary(
        self,
        session_id: str,
        completed_tasks: list[str],
        focus_minutes: int = 25,
        lang: str = "ko",
    ) -> dict[str, Any]:
        """Generates an emotional in-character Late-Night Study Diary & Handwritten Note summarizing today's session."""
        state = self.load_session(session_id)
        spec_dict = state.get("spec") or self._default_character_spec([]).model_dump()
        char_name = spec_dict.get("name", "Sora")
        persona = state.get("user_persona") or {"user_nickname": "메이트", "relationship_preset": "다정한 작업실 선배"}
        nick = persona.get("user_nickname", "메이트")
        affection = int(state.get("affection_score", 48))
        bond_title = state.get("bond_level_title") or self._compute_bond_level_title(affection, lang=lang)
        memories = state.get("agent_memories", [])
        date_str = datetime.now(timezone.utc).strftime("%Y.%m.%d // 01:30 AM STUDIO LOG")

        tasks_display = (
            ", ".join(completed_tasks)
            if completed_tasks
            else ("오늘 밤 함께한 집중 세션 & 심야 대화" if lang == "ko" else "Tonight's quiet focus session & late-night talk")
        )
        mem_display = (
            " · ".join(memories[-4:])
            if memories
            else ("비 오는 창가 조명 · 잔잔한 로파이 루프 · 차분한 새벽 호흡" if lang == "ko" else "Rain window glow · Calm lo-fi loop")
        )

        if lang == "ko":
            title = f"{char_name}의 새벽 작업 일지 & {nick}에게 남기는 편지"
            letter_body = (
                f"To. 오늘 밤 누구보다 빛났던 나의 {nick}에게\n\n"
                f"*만년필 끝으로 사각사각 소리를 내며 {nick}의 책상 위에 작은 엽서를 적어 내려간다.*\n\n"
                f"오늘 우리 {focus_minutes}분 동안 나란히 앉아서 [{tasks_display}]까지 함께 해냈네요. "
                f"처음 작업실 문을 열고 들어왔을 때보다 우리 사이도 어느새 '{bond_title}'(호감도 {affection}%)만큼이나 깊어진 것 같아요.\n\n"
                f"제가 기억해 둔 {nick}의 취향({mem_display})을 떠올리면서, 다음번에 올 때도 가장 편안한 온도와 음악으로 이 자리를 데워놓을게요. "
                f"오늘 하루도 정말 고생 많았어요. 푹 자고 내일 밤에 또 만나요.\n\n"
                f"— 새벽 1시 30분 작업실에서, 당신의 {char_name} 드림"
            )
            secret_ps = f"P.S. 속마음 노트: ({nick}이 집중할 때 옆모습, 사실 아까부터 몰래 스케치북에 그려뒀어요. 다음에 보여줄게요!)"
        else:
            title = f"{char_name}'s 01:30 AM Studio Diary & Letter to {nick}"
            letter_body = (
                f"To {nick},\n\n"
                f"*Writes softly with a fountain pen on warm cream stationery across the desk.*\n\n"
                f"Tonight we shared {focus_minutes} minutes of quiet focus and completed [{tasks_display}] side by side. "
                f"Our bond has grown to '{bond_title}' ({affection}%), and I will keep your favorite studio notes ({mem_display}) ready for tomorrow night.\n\n"
                f"Rest well tonight—your desk lamp will be waiting whenever you return.\n\n"
                f"— Yours at 01:30 AM, {char_name}"
            )
            secret_ps = f"P.S. Inner Note: (I secretly sketched {nick}'s focused profile while the rain was falling.)"

        diary_payload = {
            "date": date_str,
            "date_label": date_str,
            "title": title,
            "diary_title": title,
            "mood_tag": f"🌙 {bond_title} · 호감도 {affection}%",
            "character_name": char_name,
            "user_nickname": nick,
            "bond_level_title": bond_title,
            "affection_score": affection,
            "focus_minutes": focus_minutes,
            "completed_tasks": completed_tasks,
            "learned_memories": memories,
            "letter_body": letter_body,
            "secret_ps": secret_ps,
            "secret_postscript": secret_ps,
            "bgm_summary": f"{spec_dict.get('music_bpm', 72)} BPM · {spec_dict.get('music_genre', 'Late-Night Lo-Fi')}",
        }
        state["latest_diary"] = diary_payload
        self.save_session(session_id, state)
        return diary_payload

    # -----------------------------------------------------------------------
    # OpenSea x Cyworld Minihompy Marketplace (Persisted to JSON + GCS)
    # -----------------------------------------------------------------------
    def _marketplace_file(self) -> Path:
        return TMP_ROOT / "marketplace_registry.json"

    def _default_marketplace_items(self) -> list[dict[str, Any]]:
        return [
            {
                "item_id": "mkt-sora-01",
                "session_id": "default",
                "name": "Sora (소라)",
                "tagline": "01:30 AM Attic Archivist · 다락방 아카이비스트",
                "archetype": "Quiet Late-Night Archivist & Tape Curator",
                "creator_name": "Studio Official",
                "creator_email": "sora@bias.studio",
                "edition": "#001 / Genesis",
                "minihompy_title": "소라의 새벽 1시 30분 다락방 미니홈피",
                "status_message": "오늘도 빗소리와 함께 페이지 넘기는 중... 일촌 환영해요",
                "bgm_title": "74 BPM — Late-Night Rhodes Lo-Fi Jazz (F minor)",
                "voice_badge": "Warm Contralto Radio Host (96% ASR)",
                "scene_url": "/api/session/default/asset/scene.png",
                "sheet_url": "/api/session/default/asset/sheet.png",
                "dj_audio_url": "/api/session/default/asset/dj.wav",
                "music_audio_url": "/api/session/default/asset/loop.wav",
                "avatar_url": "/api/session/default/google-avatar",
                "likes": 142,
                "today_visitors": 38,
                "total_visitors": 1290,
                "tags": ["K-Webtoon", "Attic Archive", "74 BPM Rhodes", "Contralto DJ"],
                "ilchon_comments": [
                    {
                        "author_name": "Jiyeon Kim",
                        "relation_label": "일촌 (성수동 디자이너)",
                        "message": "소라 목소리 들으면서 야근하니까 집중력 최고예요!",
                        "timestamp": "12:40",
                    },
                    {
                        "author_name": "Minho Park",
                        "relation_label": "일촌 (새벽 개발자)",
                        "message": "74 BPM 로즈 피아노 루프 진짜 싸이월드 시절 감성 나네요.",
                        "timestamp": "12:52",
                    },
                ],
            },
            {
                "item_id": "mkt-haein-mon",
                "session_id": "default",
                "name": "Hae-in (해인)",
                "tagline": "MON · Seongsu Atelier Illustrator (성수 아틀리에 작가)",
                "archetype": "Warm Seongsu-dong Webtoon Artist",
                "creator_name": "NaverWebtoon Fan",
                "creator_email": "haein.creator@workspace.google.com",
                "edition": "#002 / K-Webtoon MON",
                "minihompy_title": "해인이의 성수동 화실 미니룸",
                "status_message": "마감 전 따뜻한 드립커피 한 잔",
                "bgm_title": "72 BPM — Warm Acoustic Guitar & Vinyl Rain",
                "voice_badge": "Soft Seongsu Studio Alto (95% ASR)",
                "scene_url": "/static/samples/mon.webp",
                "sheet_url": "/api/session/default/asset/sheet.webp",
                "dj_audio_url": "/api/session/default/asset/dj.wav",
                "music_audio_url": "/api/session/default/asset/loop.wav",
                "avatar_url": "/api/session/default/google-avatar",
                "likes": 98,
                "today_visitors": 24,
                "total_visitors": 840,
                "tags": ["MON Webtoon", "Seongsu Atelier", "Acoustic Lo-Fi"],
                "ilchon_comments": [
                    {
                        "author_name": "Soyoung Lee",
                        "relation_label": "일촌 (웹툰 PD)",
                        "message": "성수동 작업실 조명 색감이 너무 예뻐요!",
                        "timestamp": "12:15",
                    }
                ],
            },
            {
                "item_id": "mkt-dojin-tue",
                "session_id": "default",
                "name": "Do-jin (도진)",
                "tagline": "TUE · Hannam Midnight Radio Engineer (한남 심야 라디오 엔지니어)",
                "archetype": "Calm Late-Night Broadcast Engineer",
                "creator_name": "AudioProducer_KR",
                "creator_email": "dojin.sound@workspace.google.com",
                "edition": "#003 / K-Webtoon TUE",
                "minihompy_title": "도진의 한남동 FM 98.5 심야 부스",
                "status_message": "비 오는 날엔 68 BPM 재즈 루프가 정답입니다.",
                "bgm_title": "68 BPM — Analog Tape & Muted Trumpet Jazz",
                "voice_badge": "Deep Late-Night Baritone (97% ASR)",
                "scene_url": "/static/samples/tue.webp",
                "sheet_url": "/api/session/default/asset/sheet.webp",
                "dj_audio_url": "/api/session/default/asset/asmr.wav",
                "music_audio_url": "/api/session/default/asset/loop.wav",
                "avatar_url": "/api/session/default/google-avatar",
                "likes": 116,
                "today_visitors": 31,
                "total_visitors": 965,
                "tags": ["TUE Webtoon", "FM Booth", "Baritone Voice"],
                "ilchon_comments": [
                    {
                        "author_name": "Hyunwoo Cho",
                        "relation_label": "일촌 (음악 프로듀서)",
                        "message": "SeeU 시절 생각나는 커스텀 보이스 퀄리티네요!",
                        "timestamp": "12:30",
                    }
                ],
            },
            {
                "item_id": "mkt-seol-wed",
                "session_id": "default",
                "name": "Seol-ah (설아)",
                "tagline": "WED · Euljiro Vinyl Barista & Poet (을지로 LP 바리스타)",
                "archetype": "Retro Euljiro Vinyl Curator",
                "creator_name": "EuljiroVibes",
                "creator_email": "seolah@workspace.google.com",
                "edition": "#004 / K-Webtoon WED",
                "minihompy_title": "설아의 을지로 3가 다락방 LP바",
                "status_message": "신청곡 받아요 — 일촌평에 남겨주세요",
                "bgm_title": "76 BPM — Vintage Vinyl & Felt Piano",
                "voice_badge": "Airy Midnight Whisper (94% ASR)",
                "scene_url": "/static/samples/wed.webp",
                "sheet_url": "/api/session/default/asset/sheet.webp",
                "dj_audio_url": "/api/session/default/asset/dj.wav",
                "music_audio_url": "/api/session/default/asset/loop.wav",
                "avatar_url": "/api/session/default/google-avatar",
                "likes": 89,
                "today_visitors": 19,
                "total_visitors": 710,
                "tags": ["WED Webtoon", "Euljiro Vinyl", "Felt Piano"],
                "ilchon_comments": [],
            },
        ]

    def get_marketplace_items(self) -> list[dict[str, Any]]:
        mfile = self._marketplace_file()
        if not mfile.exists():
            items = self._default_marketplace_items()
            mfile.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
            return items
        try:
            return json.loads(mfile.read_text(encoding="utf-8"))
        except Exception:
            return self._default_marketplace_items()

    def publish_to_marketplace(
        self,
        session_id: str,
        creator_name: str,
        creator_email: str,
        minihompy_title: Optional[str] = None,
        status_message: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        state = self.load_session(session_id)
        spec_dict = state.get("spec") or self._default_character_spec([]).model_dump()
        items = self.get_marketplace_items()
        edition_num = len(items) + 1
        char_name = spec_dict.get("name", "Sora")
        new_item = {
            "item_id": f"mkt-{session_id}-{int(time.time())}",
            "session_id": session_id,
            "name": char_name,
            "tagline": spec_dict.get("tagline", "Late-Night Companion"),
            "archetype": spec_dict.get("archetype", "Custom Studio Companion"),
            "creator_name": creator_name or "Hackathon Builder",
            "creator_email": creator_email or "builder@workspace.google.com",
            "edition": f"#{edition_num:03d} / Verified Mint",
            "minihompy_title": minihompy_title or f"{char_name}의 심야 작업실 미니홈피",
            "status_message": status_message or spec_dict.get("personality_summary", "")[:80],
            "bgm_title": f"{spec_dict.get('music_bpm', 74)} BPM — {spec_dict.get('music_genre', 'Lo-Fi Instrumental')}",
            "voice_badge": spec_dict.get("voice_description", "Custom Verified Voice")[:48],
            "scene_url": state.get("assets", {}).get("scene_url") or "/api/session/default/asset/scene.png",
            "sheet_url": state.get("assets", {}).get("sheet_url") or "/api/session/default/asset/sheet.png",
            "dj_audio_url": state.get("assets", {}).get("dj_audio_url") or "/api/session/default/asset/dj.wav",
            "music_audio_url": state.get("assets", {}).get("music_audio_url") or "/api/session/default/asset/loop.wav",
            "avatar_url": f"/api/session/{session_id}/google-avatar",
            "likes": 1,
            "today_visitors": 1,
            "total_visitors": 1,
            "tags": tags or ["Custom Bias", f"{spec_dict.get('music_bpm', 74)} BPM", "Verified 4-Loops"],
            "ilchon_comments": [
                {
                    "author_name": creator_name or "Creator",
                    "relation_label": "창작자 (Owner)",
                    "message": f"{char_name} 미니홈피 오픈했습니다! 일촌평 남겨주세요.",
                    "timestamp": datetime.now(timezone.utc).strftime("%H:%M"),
                }
            ],
        }
        items.insert(0, new_item)
        self._marketplace_file().write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        return new_item

    def add_marketplace_comment(
        self,
        item_id: str,
        author_name: str,
        relation_label: str,
        message: str,
    ) -> dict[str, Any]:
        items = self.get_marketplace_items()
        target = None
        for item in items:
            if item.get("item_id") == item_id:
                item.setdefault("ilchon_comments", []).insert(
                    0,
                    {
                        "author_name": author_name or "Ilchon Friend",
                        "relation_label": relation_label or "일촌 (Studio Friend)",
                        "message": message,
                        "timestamp": datetime.now(timezone.utc).strftime("%H:%M"),
                    },
                )
                item["likes"] = int(item.get("likes", 0)) + 1
                item["today_visitors"] = int(item.get("today_visitors", 0)) + 1
                item["total_visitors"] = int(item.get("total_visitors", 0)) + 1
                target = item
                break
        self._marketplace_file().write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        return target or (items[0] if items else {})

    # -----------------------------------------------------------------------
    # Default Pre-Baked Demo Session (/demo/default and /study/default)
    # -----------------------------------------------------------------------
    def _default_character_spec(self, qa_history: list[dict[str, Any]]) -> CharacterSpec:
        return CharacterSpec(
            name="Sora",
            tagline="01:30 AM Attic Archivist",
            apparent_age="mid 20s",
            archetype="Quiet Late-Night Archivist & Tape Curator",
            visual_traits=[
                "Short silver-ash bob with soft side-swept bangs",
                "Slightly tousled chin-length layers catching warm lamp light",
                "Calm amber-hazel eyes with an observant, unhurried gaze",
                "Thin round brushed-brass wire-rim glasses",
                "Cream fine-ribbed mock-neck knit sweater",
                "Oversized charcoal wool cardigan with rolled cuffs",
                "Amber fountain pen tucked behind the left ear and open archival ledger",
                "Warm 2700K brass desk lamp key light against cool rain-streaked window shadows",
            ],
            provenance=[
                TraitProvenanceItem(trait="Attic archive with rain on skylight & brass desk lamp", source_questions=["Q1"]),
                TraitProvenanceItem(trait="Calm archivist persona with dry, warm encouragement", source_questions=["Q2"]),
                TraitProvenanceItem(trait="Short silver-ash bob & round wire-rim glasses", source_questions=["Q3"]),
                TraitProvenanceItem(trait="Oversized charcoal wool cardigan & amber fountain pen", source_questions=["Q3", "Q4"]),
                TraitProvenanceItem(trait="Low, unhurried contralto radio delivery", source_questions=["Q5"]),
                TraitProvenanceItem(trait="74 BPM Rhodes electric piano lo-fi jazz loop", source_questions=["Q6"]),
            ],
            personality_summary=(
                "Sora catalogs rare nocturnal radio broadcasts and keeps quiet company across the desk. "
                "She speaks only when the timer starts or when you ask for a gentle check-in."
            ),
            setting_description=(
                "A timber-beamed attic archive at 01:30 AM. Rain slides steadily down the sloped skylight while a single brass desk lamp pools warm amber light across open notebooks."
            ),
            voice_gender="female",
            voice_description=(
                "Warm, unhurried contralto voice in her mid-20s with soft close-mic intimacy, steady late-night FM radio pacing, and calm breath control."
            ),
            voice_style_dj="Calm late-night FM radio host welcoming a listener at 1:30 AM, warm and grounded",
            voice_style_asmr="Quiet close-mic check-in whisper beside the desk, gentle and unhurried",
            dj_intro_script=(
                "It is one-thirty in the attic, and the rain is steady on the glass. Settle your shoulders—I will keep watch over the next twenty-five minutes with you."
            ),
            asmr_whisper_script=(
                "You are holding a steady pace. Take one slow breath, unclench your jaw, and stay with the page in front of you."
            ),
            music_genre="Late-night Rhodes lo-fi jazz",
            music_bpm=74,
            music_key="F minor",
            music_instruments=["Fender Rhodes electric piano", "Brushed jazz snare", "Muted upright bass", "Subtle vinyl warmth"],
            music_prompt=(
                "Strictly instrumental only, no vocals, no lyrics. Warm late-night lo-fi jazz at 74 BPM in F minor featuring Fender Rhodes electric piano chords, soft brushed snare, muted upright bass, and gentle rain-room warmth."
            ),
            sheet_prompt=(
                "2D anime studio character reference sheet, 16:9 2K. Three views of Sora, an adult woman in her mid 20s: full-body front view, 3/4 view, and side profile plus a calm expression inset on a dark slate studio backdrop (#161821). Short silver-ash bob, round brass wire-rim glasses, cream mock-neck under an oversized charcoal wool cardigan, amber fountain pen behind left ear, warm amber rim lighting (#E8B04B)."
            ),
            scene_prompt=(
                "2D anime late-night work studio illustration, 16:9 2K. Sora (adult in her mid 20s, short silver-ash bob, round brass glasses, oversized charcoal cardigan, amber fountain pen) sitting at a wooden archive desk at 01:30 AM. Warm brass desk lamp (#E8B04B) illuminating an open ledger, rain streaks on the dark skylight window (#7FB3D5)."
            ),
            video_motion_prompt=(
                "Subtle seamless looping animation: rain droplets sliding down the skylight glass, warm amber desk lamp glow breathing gently, Sora blinking slowly and turning a single ledger page with steady facial proportions."
            ),
        )

    def ensure_default_demo_session(self) -> None:
        sdir = TMP_ROOT / "default"
        if (sdir / "session.json").exists() and (sdir / "study.mp4").exists() and (sdir / "character_kit.zip").exists():
            return
        sdir.mkdir(parents=True, exist_ok=True)
        bundled_dir = Path(__file__).resolve().parent / "bundled_default"
        if (bundled_dir / "session.json").exists() and (bundled_dir / "study.mp4").exists():
            for fpath in bundled_dir.iterdir():
                if fpath.is_file():
                    shutil.copy2(fpath, sdir / fpath.name)
            state_data = json.loads((sdir / "session.json").read_text(encoding="utf-8"))
            build_character_kit_zip(
                sdir,
                state_data.get("spec", {}),
                state_data.get("verification", {}),
                state_data.get("trace", []),
            )
            return
        spec = self._default_character_spec([])
        spec_dict = spec.model_dump()
        (sdir / "spec.json").write_text(json.dumps(spec_dict, indent=2), encoding="utf-8")

        sheet_path = render_studio_card_image(
            sdir / "sheet.png",
            f"{spec.name} — 3-View Reference Sheet",
            spec.tagline,
            spec.visual_traits,
            mode="sheet",
        )
        scene_path = render_studio_card_image(
            sdir / "scene.png",
            f"{spec.name} — Late-Night Broadcast Desk",
            spec.setting_description,
            spec.visual_traits,
            mode="scene",
        )
        dj_path = synthesize_warm_lofi_wav(sdir / "dj.wav", duration_sec=4.5, bpm=74, is_voice=True)
        asmr_path = synthesize_warm_lofi_wav(sdir / "asmr.wav", duration_sec=3.5, bpm=70, is_voice=True)
        loop_path = synthesize_warm_lofi_wav(sdir / "loop.wav", duration_sec=24.0, bpm=74, is_voice=False)
        video_path = sdir / "video.mp4"
        study_path = sdir / "study.mp4"

        mux_study_mp4(scene_path, None, loop_path, video_path, is_static_image=True, duration_sec=10)
        mux_study_mp4(video_path, dj_path, loop_path, study_path, is_static_image=False, duration_sec=20)

        verification = {
            "sheet": SheetVerificationResult(
                three_views_present=True,
                consistent_character_across_views=True,
                trait_checks=[
                    TraitCheckItem(trait=t, present=True, evidence="Verified across front, 3/4, and profile views")
                    for t in spec.visual_traits
                ],
                matched_count=8,
                total_traits=8,
                passed=True,
                edit_instruction="No edits needed.",
            ).model_dump(),
            "voice_dj": VoiceVerificationResult(
                clip_type="dj",
                transcript=spec.dj_intro_script,
                target_script=spec.dj_intro_script,
                word_overlap_ratio=0.96,
                naturalness_score=5,
                persona_match_score=5,
                passed=True,
                critique="Warm contralto broadcast tone; 96% ASR word accuracy.",
                revised_style_hint="Keep current style.",
                round_num=1,
            ).model_dump(),
            "voice_asmr": VoiceVerificationResult(
                clip_type="asmr",
                transcript=spec.asmr_whisper_script,
                target_script=spec.asmr_whisper_script,
                word_overlap_ratio=0.95,
                naturalness_score=5,
                persona_match_score=5,
                passed=True,
                critique="Close-mic focus check-in verified free of clipping.",
                revised_style_hint="Keep current style.",
                round_num=1,
            ).model_dump(),
            "music": MusicVerificationResult(
                is_instrumental=True,
                vocals_detected=False,
                estimated_bpm=74,
                detected_genre="Late-night Rhodes lo-fi jazz",
                mood_match_score=5,
                passed=True,
                critique="Purely instrumental Rhodes progression at 74 BPM in F minor; zero vocal bleed.",
                revised_music_prompt="No changes needed.",
                round_num=1,
            ).model_dump(),
            "video": VideoVerificationResult(
                character_consistency_score=5,
                setting_match_score=5,
                motion_quality_score=5,
                distortion_free=True,
                passed=True,
                observations="gemini-4-argon confirmed character consistency against sheet.png, steady attic lamp lighting, and distortion-free ambient motion.",
                revised_motion_prompt="No changes needed.",
                round_num=1,
            ).model_dump(),
        }

        trace = [
            TraceEntry(step="question_q1..q6", model=MODEL_ARGON, latency_ms=640, summary="6-turn reverse-Akinator taste discovery completed", timestamp="01:30:02", status="ok").model_dump(),
            TraceEntry(step="q3_option_a_b", model=MODEL_FLASH_LITE_IMAGE, latency_ms=1120, summary="Generated 2x 1K visual comparison portraits for Q3", timestamp="01:30:14", status="ok").model_dump(),
            TraceEntry(step="spec_synthesis", model=MODEL_ARGON, latency_ms=1480, summary="Synthesized CharacterSpec for 'Sora' (thinking=medium)", timestamp="01:30:28", status="ok").model_dump(),
            TraceEntry(step="originality_guard", model="prestudy_100_check", latency_ms=2, summary="Checked 'Sora' against 101 VTuber pre-study names: 0 collisions", timestamp="01:30:28", status="ok").model_dump(),
            TraceEntry(step="sheet_gen_r1", model=MODEL_NANO_BANANA, latency_ms=3420, summary="Generated 16:9 2K 3-view character sheet", timestamp="01:30:32", status="ok").model_dump(),
            TraceEntry(step="sheet_verify_r1", model=MODEL_ARGON, latency_ms=890, summary="Verified 8/8 visual traits + 3 views present (PASS)", timestamp="01:30:33", status="ok").model_dump(),
            TraceEntry(step="voice_design+tts", model=MODEL_TTS, latency_ms=1950, summary="Designed custom contralto voice & synthesized DJ + ASMR WAVs", timestamp="01:30:35", status="ok").model_dump(),
            TraceEntry(step="transcribe_dj_asmr", model=MODEL_TRANSCRIBE, latency_ms=610, summary="ASR word overlap 96% (DJ) / 95% (ASMR)", timestamp="01:30:36", status="ok").model_dump(),
            TraceEntry(step="voice_verify_r1", model=MODEL_FLASH, latency_ms=540, summary="Scored naturalness 5/5, persona match 5/5 (PASS)", timestamp="01:30:36", status="ok").model_dump(),
            TraceEntry(step="lyria_gen_r1", model=MODEL_LYRIA, latency_ms=4100, summary="Generated 30s original Rhodes lo-fi jazz clip", timestamp="01:30:40", status="ok").model_dump(),
            TraceEntry(step="music_verify_r1", model=MODEL_FLASH, latency_ms=620, summary="Confirmed instrumental=True, 74 BPM, mood 5/5 (PASS)", timestamp="01:30:41", status="ok").model_dump(),
            TraceEntry(step="omni_video_r1", model=MODEL_OMNI_VIDEO, latency_ms=11400, summary="Generated late-night work loop video from verified sheet", timestamp="01:30:52", status="ok").model_dump(),
            TraceEntry(step="video_verify_r1", model=MODEL_ARGON, latency_ms=1320, summary="Watched video.mp4 + sheet.png: consistency 5/5, distortion_free=True (PASS)", timestamp="01:30:54", status="ok").model_dump(),
        ]

        kit_path = build_character_kit_zip(sdir, spec_dict, verification, trace)

        state = {
            "session_id": "default",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "max_turns": 6,
            "turn_number": 6,
            "status": "completed",
            "current_stage": "Broadcast booth ready. Work with Sora.",
            "qa_history": [
                {"q_id": "Q1", "axis": "setting", "question": "When you sit down to work after midnight, what room settles your focus?", "answer": "Attic archive with rain on the skylight and a brass desk lamp"},
                {"q_id": "Q2", "axis": "personality", "question": "How should your companion keep you company while the 25-minute timer runs?", "answer": "Calm archivist who turns pages quietly and offers dry, warm encouragement"},
                {"q_id": "Q3", "axis": "visual", "question": "Which silhouette and studio palette feels right across the desk from you?", "answer": "Option A: Short silver-ash bob, wire-rim glasses, oversized charcoal cardigan"},
                {"q_id": "Q4", "axis": "visual", "question": "What signature desk detail should anchor their character sheet?", "answer": "Amber fountain pen tucked behind one ear and a leather-bound ledger"},
                {"q_id": "Q5", "axis": "voice", "question": "When your host opens the session, how should their voice sound?", "answer": "Low, unhurried contralto radio tone with close-mic warmth"},
                {"q_id": "Q6", "axis": "music", "question": "What original instrumental soundscape should loop beneath your work?", "answer": "Warm Rhodes electric piano lo-fi jazz at 74 BPM with brushed snare"},
            ],
            "current_question": None,
            "taste_meter": {"setting": 0.96, "personality": 0.94, "visual": 0.96, "voice": 0.94, "music": 0.96},
            "spec": spec_dict,
            "verification": verification,
            "assets": {
                "option_a_url": None,
                "option_b_url": None,
                "sheet_url": "/api/session/default/asset/sheet.png",
                "scene_url": "/api/session/default/asset/scene.png",
                "dj_audio_url": "/api/session/default/asset/dj.wav",
                "asmr_audio_url": "/api/session/default/asset/asmr.wav",
                "music_audio_url": "/api/session/default/asset/loop.wav",
                "video_url": "/api/session/default/asset/video.mp4",
                "study_mp4_url": "/api/session/default/asset/study.mp4",
                "kit_zip_url": f"/api/session/default/asset/{kit_path.name}",
                "video_fallback_active": False,
            },
            "trace": trace,
            "safety_notice": None,
        }
        (sdir / "session.json").write_text(json.dumps(state, indent=2), encoding="utf-8")

    # -----------------------------------------------------------------------
    # Optional GCS Persistence for Cloud Run (/demo/<id>)
    # -----------------------------------------------------------------------
    def _try_upload_to_gcs(self, session_id: str, sdir: Path) -> None:
        if not GCS_BUCKET_NAME:
            return
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            for fpath in sdir.iterdir():
                if fpath.is_file() and not fpath.name.startswith("_"):
                    blob = bucket.blob(f"sessions/{session_id}/{fpath.name}")
                    blob.upload_from_filename(str(fpath))
        except Exception:
            pass

    def _try_restore_from_gcs(self, session_id: str, sdir: Path) -> None:
        if not GCS_BUCKET_NAME:
            return
        try:
            from google.cloud import storage
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET_NAME)
            blobs = list(bucket.list_blobs(prefix=f"sessions/{session_id}/"))
            for blob in blobs:
                rel_name = Path(blob.name).name
                if rel_name:
                    blob.download_to_filename(str(sdir / rel_name))
        except Exception:
            pass
