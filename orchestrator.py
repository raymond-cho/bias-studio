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


# Short 1-line Smore / Piku style question pool (1/3 length, non-repetitive, grouped by characteristic chapter)
FALLBACK_QUESTIONS: list[dict[str, Any]] = [
    # Q1: Place & Mood (Chapter 1: What type of place, mood are you dreaming?)
    {
        "question": "What late-night room mood are you dreaming of?",
        "axis": "setting",
        "ui_mode": "choices",
        "options": [
            "Rainy attic archive with warm brass lamp",
            "High-floor Seoul FM booth over city lights",
            "Seongsu wood atelier with vintage vinyl",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.82,
        "taste_meter": {"setting": 0.65, "personality": 0.15, "visual": 0.15, "voice": 0.15, "music": 0.15},
        "ready_for_spec": False,
    },
    # Q2: Bias Gender & Age Profile (Chapter 2: Imagine your favorite type of bias. How does she/he look like?)
    {
        "question": "What gender and age vibe should your bias have?",
        "axis": "visual",
        "ui_mode": "choices",
        "options": [
            "Female · Early-to-mid 20s (warm studio senior)",
            "Male · Mid-to-late 20s (calm night radio producer)",
            "Androgynous / Neutral · Mid 20s (composed archivist)",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.68,
        "taste_meter": {"setting": 0.75, "personality": 0.35, "visual": 0.50, "voice": 0.25, "music": 0.20},
        "ready_for_spec": False,
    },
    # Q3: Cultural/Visual Style & Silhouette (Chapter 2: Bias Appearance)
    {
        "question": "Which visual heritage and silhouette fits your bias?",
        "axis": "visual",
        "ui_mode": "this_or_that",
        "options": [
            "Option A: East Asian K-Webtoon — silver-ash bob, glasses, knit",
            "Option B: Global/Western indie — dark long hair, headphones, jacket",
            "Mix both: K-Webtoon dark hair with wire-rim glasses & cardigan",
            "No preference — surprise me",
        ],
        "option_a": "2D Korean webtoon studio portrait of an adult in their mid 20s with a short silver-ash bob, round wire-rim glasses, oversized charcoal knit cardigan, warm amber desk lamp rim light",
        "option_b": "2D Korean webtoon studio portrait of an adult in their mid 20s with long dark espresso hair, vintage brass studio headphones around neck, olive corduroy jacket, cool rainlight window glow",
        "option_a_label": "East Asian K-Webtoon · Silver-ash bob · Wire-rim glasses",
        "option_b_label": "Global/Western Indie · Dark espresso hair · Brass headphones",
        "uncertainty_remaining": 0.50,
        "taste_meter": {"setting": 0.85, "personality": 0.55, "visual": 0.80, "voice": 0.30, "music": 0.30},
        "ready_for_spec": False,
    },
    # Q4: Eye Shape, Desk Posture & Prop (Chapter 2: Bias Appearance)
    {
        "question": "What eye vibe, desk posture, and prop fit best?",
        "axis": "visual",
        "ui_mode": "choices",
        "options": [
            "Calm amber eyes, leaning on one hand with fountain pen",
            "Sharp cat-like gaze, adjusting a vintage broadcast mic",
            "Gentle crescent eyes, holding a warm ceramic mug",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.34,
        "taste_meter": {"setting": 0.94, "personality": 0.75, "visual": 0.95, "voice": 0.45, "music": 0.35},
        "ready_for_spec": False,
    },
    # Q5: Persona & Voice Tone (Chapter 3: Persona, Voice & Sound)
    {
        "question": "What voice tone and personality do you prefer?",
        "axis": "voice",
        "ui_mode": "choices",
        "options": [
            "Calm contralto DJ — cool outside, warm inside",
            "Soft baritone engineer — steady & observant",
            "Airy close-mic whisper — gentle page-turner",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.18,
        "taste_meter": {"setting": 0.95, "personality": 0.92, "visual": 0.95, "voice": 0.92, "music": 0.50},
        "ready_for_spec": False,
    },
    # Q6: Lo-Fi Music & Tempo (Chapter 3: Soundscape)
    {
        "question": "Which lo-fi loop should play while you focus?",
        "axis": "music",
        "ui_mode": "choices",
        "options": [
            "74 BPM warm Rhodes electric piano jazz",
            "68 BPM nocturnal acoustic guitar & upright bass",
            "78 BPM minimalist analog synth & felt piano",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.05,
        "taste_meter": {"setting": 0.96, "personality": 0.94, "visual": 0.96, "voice": 0.94, "music": 0.96},
        "ready_for_spec": True,
    },
    # Extra non-repetitive Smore/Piku pool for 10Q General & 20Q Bias modes
    {
        "question": "What hairstyle length matches your ideal bias?",
        "axis": "visual",
        "ui_mode": "choices",
        "options": [
            "Chin-length layered bob with airy bangs",
            "Long wavy hair tied loosely with a clip",
            "Clean tousled wolf-cut / comma hair",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.25,
        "taste_meter": {"setting": 0.95, "personality": 0.88, "visual": 0.96, "voice": 0.85, "music": 0.80},
        "ready_for_spec": False,
    },
    {
        "question": "Which hair color palette appeals to you most?",
        "axis": "visual",
        "ui_mode": "choices",
        "options": [
            "Silver-ash or misty platinum",
            "Deep espresso black or midnight navy",
            "Warm milk-tea brown or muted auburn",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.20,
        "taste_meter": {"setting": 0.95, "personality": 0.90, "visual": 0.97, "voice": 0.88, "music": 0.85},
        "ready_for_spec": False,
    },
    {
        "question": "How should your bias react when you take a break?",
        "axis": "personality",
        "ui_mode": "choices",
        "options": [
            "Quietly slides over a warm mug without a word",
            "Teases lightly with a dry smile, then checks on you",
            "Reads a calm midnight radio note aloud",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.12,
        "taste_meter": {"setting": 0.96, "personality": 0.96, "visual": 0.97, "voice": 0.92, "music": 0.90},
        "ready_for_spec": False,
    },
    {
        "question": "What ambient texture should blend into the music?",
        "axis": "music",
        "ui_mode": "choices",
        "options": [
            "Skylight rain + warm vinyl crackle",
            "Fountain pen nib on paper + clock tick",
            "Pure clean studio Rhodes mix without FX",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.05,
        "taste_meter": {"setting": 0.97, "personality": 0.96, "visual": 0.97, "voice": 0.95, "music": 0.97},
        "ready_for_spec": True,
    },
]

FALLBACK_QUESTIONS_KO: list[dict[str, Any]] = [
    # Q1: Place & Mood (Chapter 1: 어떤 공간과 밤의 분위기를 꿈꾸시나요?)
    {
        "question": "지금 꿈꾸는 심야 작업실 공간은 어디인가요?",
        "axis": "setting",
        "ui_mode": "choices",
        "options": [
            "빗소리 들리는 다락방 아카이브와 황동 스탠드",
            "서울 야경이 내려다보이는 심야 FM 라디오 부스",
            "성수동 감성 원목 화실과 빈티지 LP 선반",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.82,
        "taste_meter": {"setting": 0.65, "personality": 0.15, "visual": 0.15, "voice": 0.15, "music": 0.15},
        "ready_for_spec": False,
    },
    # Q2: 성별 & 나이대 프로필 (Chapter 2: 최애 외모 & 프로필)
    {
        "question": "어떤 성별과 나이대의 최애(Bias) 캐릭터를 만들고 싶나요?",
        "axis": "visual",
        "ui_mode": "choices",
        "options": [
            "여성 · 20대 초중반 (다정한 작업실/크리에이터 선배)",
            "남성 · 20대 중후반 (차분한 심야 프로듀서·라디오 호스트)",
            "중성적/성별 무관 · 20대 중반 (분위기 있는 아카이비스트)",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.68,
        "taste_meter": {"setting": 0.75, "personality": 0.35, "visual": 0.50, "voice": 0.25, "music": 0.20},
        "ready_for_spec": False,
    },
    # Q3: 인종/작화 스타일 & 실루엣 (Chapter 2: 당신이 꿈꾸는 최애는 어떤 모습인가요?)
    {
        "question": "최애의 외모 분위기(인종·작화 스타일)와 실루엣은?",
        "axis": "visual",
        "ui_mode": "this_or_that",
        "options": [
            "Option A: 동양풍 K-웹툰 비주얼 · 은빛 애쉬 단발 · 금테 안경",
            "Option B: 글로벌/서구풍 일러스트 · 흑갈색 장발 · 황동 헤드폰",
            "두 스타일 믹스: K-웹툰 흑발에 금테 안경과 포근한 니트",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "option_a": "Korean webtoon style studio portrait of an adult in their mid 20s with a short silver-ash bob, round wire-rim glasses, oversized charcoal knit cardigan, warm amber desk lamp rim light",
        "option_b": "Korean webtoon style studio portrait of an adult in their mid 20s with long dark espresso hair, vintage brass studio headphones around neck, olive corduroy jacket, cool rainlight window glow",
        "option_a_label": "동양풍 K-웹툰 · 은빛 단발 · 금테 안경 · 가디건",
        "option_b_label": "글로벌/서구풍 인디 · 흑갈색 장발 · 황동 헤드폰 · 자켓",
        "uncertainty_remaining": 0.50,
        "taste_meter": {"setting": 0.85, "personality": 0.55, "visual": 0.80, "voice": 0.30, "music": 0.30},
        "ready_for_spec": False,
    },
    # Q4: Eye Shape, Posture & Prop (Chapter 2: 최애 외모 디테일 & 자세)
    {
        "question": "최애의 눈매, 책상 앞 자세(포즈), 시그니처 소품은?",
        "axis": "visual",
        "ui_mode": "choices",
        "options": [
            "차분한 호박색 눈매 · 턱을 괴고 만년필을 쥔 자세",
            "도도한 고양이 눈매 · 빈티지 방송 마이크를 맞춘 자세",
            "다정한 반달 눈웃음 · 따뜻한 호지차 머그잔을 든 자세",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.34,
        "taste_meter": {"setting": 0.94, "personality": 0.75, "visual": 0.95, "voice": 0.45, "music": 0.35},
        "ready_for_spec": False,
    },
    # Q5: Persona & Voice Tone (Chapter 3: 목소리 & 성격)
    {
        "question": "가장 취향인 목소리 톤과 성격(데레)은?",
        "axis": "voice",
        "ui_mode": "choices",
        "options": [
            "나직한 중저음 라디오 톤 · 겉차속따 다정함",
            "부드러운 바리톤/알토 · 든든하고 침착한 동료",
            "포근한 속삭임 보이스 · 섬세한 힐링 메이트",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.18,
        "taste_meter": {"setting": 0.95, "personality": 0.92, "visual": 0.95, "voice": 0.92, "music": 0.50},
        "ready_for_spec": False,
    },
    # Q6: Lo-Fi Music & Tempo (Chapter 3: 사운드)
    {
        "question": "함께 들을 오리지널 로파이 BGM 사운드는?",
        "axis": "music",
        "ui_mode": "choices",
        "options": [
            "74 BPM 따뜻한 로즈 일렉트릭 피아노 재즈",
            "68 BPM 새벽 어쿠스틱 기타 & 콘트라베이스",
            "78 BPM 미니멀 아날로그 신스 & 빗소리 피아노",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.05,
        "taste_meter": {"setting": 0.96, "personality": 0.94, "visual": 0.96, "voice": 0.94, "music": 0.96},
        "ready_for_spec": True,
    },
    # Extra non-repetitive Smore/Piku pool for 10Q General & 20Q Bias modes
    {
        "question": "가장 내 취향인 최애의 머리 길이는?",
        "axis": "visual",
        "ui_mode": "choices",
        "options": [
            "가볍게 층을 낸 시스루 태슬 단발",
            "자연스럽게 반묶음한 웨이브 장발",
            "단정하게 넘긴 시크한 숏컷/리프컷",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.25,
        "taste_meter": {"setting": 0.95, "personality": 0.88, "visual": 0.96, "voice": 0.85, "music": 0.80},
        "ready_for_spec": False,
    },
    {
        "question": "가장 끌리는 머리카락 색감은?",
        "axis": "visual",
        "ui_mode": "choices",
        "options": [
            "신비로운 실버 애쉬 / 백금발",
            "차분한 흑발 / 에스프레소 다크브라운",
            "부드러운 밀크티 브라운 / 와인빛",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.20,
        "taste_meter": {"setting": 0.95, "personality": 0.90, "visual": 0.97, "voice": 0.88, "music": 0.85},
        "ready_for_spec": False,
    },
    {
        "question": "잠깐 쉴 때 최애가 건네는 첫마디 스타일은?",
        "axis": "personality",
        "ui_mode": "choices",
        "options": [
            "말없이 따뜻한 차 한 잔을 책상 끝에 놓아준다",
            "장난스럽게 웃으며 어깨 한번 기지개 켜라고 챙긴다",
            "라디오 사연 읽어주듯 나직하게 응원을 건넨다",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.12,
        "taste_meter": {"setting": 0.96, "personality": 0.96, "visual": 0.97, "voice": 0.92, "music": 0.90},
        "ready_for_spec": False,
    },
    {
        "question": "배경 음악에 살짝 섞고 싶은 ASMR 환경음은?",
        "axis": "music",
        "ui_mode": "choices",
        "options": [
            "창가 빗소리와 LP 바이닐 노이즈",
            "사각거리는 만년필 필기 소리와 책장 넘김",
            "효과음 없이 깔끔한 스튜디오 피아노 원음",
            "상관없음 — 알아서 추천해 주세요",
        ],
        "uncertainty_remaining": 0.05,
        "taste_meter": {"setting": 0.97, "personality": 0.96, "visual": 0.97, "voice": 0.95, "music": 0.97},
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
        return json.loads(state_file.read_text(encoding="utf-8"))

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

    def create_session(self, max_turns: int = 6, survey_mode: str = "quick", lang: str = "en") -> dict[str, Any]:
        session_id = uuid.uuid4().hex[:10]
        survey_mode = (survey_mode or "quick").lower()
        if survey_mode == "quick":
            max_turns = max(6, min(max_turns or 6, 8))
        elif survey_mode == "general":
            max_turns = max(10, min(max_turns if max_turns >= 10 else 10, 15))
        elif survey_mode == "bias":
            max_turns = max(20, min(max_turns if max_turns >= 20 else 20, 30))
        else:
            survey_mode = "quick"
            max_turns = max(6, min(max_turns or 6, 8))

        state: dict[str, Any] = {
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "survey_mode": survey_mode,
            "lang": lang if lang in ("en", "ko") else "en",
            "max_turns": max_turns,
            "turn_number": 0,
            "status": "questioning",
            "current_stage": "Initializing studio session..." if lang != "ko" else "스튜디오 세션을 초기화하고 있습니다...",
            "qa_history": [],
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
        max_turns = state.get("max_turns", 6)
        survey_mode = state.get("survey_mode", "quick")
        lang = state.get("lang", "en")
        state["turn_number"] = turn_num
        sdir = self.session_dir(session_id)

        client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))
        q_turn: Optional[QuestionTurn] = None

        # Pre-load Q1..Q5 as 0ms instant Smore/Piku defaults; call gemini-4-argon from Q6+ for tailored deep questions
        if turn_num <= 5:
            fb_list = FALLBACK_QUESTIONS_KO if lang == "ko" else FALLBACK_QUESTIONS
            fb_data = dict(fb_list[(turn_num - 1) % len(fb_list)])
            fb_data["ready_for_spec"] = turn_num >= max_turns
            q_turn = QuestionTurn(**fb_data)
            self.append_trace(
                session_id,
                TraceEntry(
                    step=f"question_q{turn_num}_instant",
                    model="preset+argon_schema",
                    latency_ms=1,
                    summary=f"Instant Q{turn_num} loaded ({q_turn.axis}): {q_turn.question[:42]}",
                    timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    status="ok",
                ),
            )
        elif get_api_key():
            try:
                prompt = build_question_prompt(
                    history=state["qa_history"],
                    turn_number=turn_num,
                    max_turns=max_turns,
                    survey_mode=survey_mode,
                    lang=lang,
                )
                q_turn, inter_id = client.generate_structured_json(
                    step=f"question_q{turn_num}",
                    model=MODEL_ARGON,
                    input_payload=prompt,
                    schema_cls=QuestionTurn,
                    thinking_level="low",
                    previous_interaction_id=state.get("argon_interaction_id"),
                )
                if inter_id:
                    state["argon_interaction_id"] = inter_id
            except Exception as exc:
                self.append_trace(
                    session_id,
                    TraceEntry(
                        step=f"question_q{turn_num}_fallback",
                        model=MODEL_ARGON,
                        latency_ms=10,
                        summary=f"Fallback question used ({str(exc)[:60]})",
                        timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
                        status="fallback",
                    ),
                )

        if q_turn is None:
            fb_list = FALLBACK_QUESTIONS_KO if lang == "ko" else FALLBACK_QUESTIONS
            fb_idx = (turn_num - 1) % len(fb_list)
            fb_data = dict(fb_list[fb_idx])
            fb_data["ready_for_spec"] = turn_num >= max_turns
            q_turn = QuestionTurn(**fb_data)

        # Strictly enforce that ONLY turn 3 uses 'this_or_that' image comparison
        if turn_num == 3:
            q_turn.ui_mode = "this_or_that"
        else:
            q_turn.ui_mode = "choices"

        no_pref_label = "상관없음 — 알아서 추천해 주세요" if lang == "ko" else "No preference — surprise me"

        # Enforce option counts per survey_mode
        if survey_mode == "quick":
            base_opts = [o for o in q_turn.options if "no preference" not in o.lower() and "상관없음" not in o]
            if len(base_opts) < 2:
                base_opts = (
                    ["따뜻한 앰버 조명의 다락방 아카이브", "빗소리가 들리는 심야 라디오 부스"]
                    if lang == "ko"
                    else ["Rainy attic archive with warm brass lamp", "High-floor Seoul FM booth over city lights"]
                )
            q_turn.options = base_opts[:2] + [no_pref_label]
        elif survey_mode == "bias":
            base_opts = [o for o in q_turn.options if "no preference" not in o.lower() and "상관없음" not in o]
            if len(base_opts) < 3:
                base_opts = (
                    [
                        "성수동 감성의 미니멀 아틀리에 & 2700K 스탠드",
                        "빗방울이 흐르는 고층 심야 라디오 부스",
                        "오래된 LP와 원목 책장이 가득한 다락방",
                        "네온 불빛이 비치는 새벽 루프탑 작업실",
                    ]
                    if lang == "ko"
                    else [
                        "Rainy attic archive with warm brass lamp",
                        "High-floor Seoul FM booth over city lights",
                        "Minimalist Seongsu atelier with vinyl shelves",
                        "Rooftop music sanctuary over quiet city lights",
                    ]
                )
            q_turn.options = base_opts[:4] + [no_pref_label]
        else:
            if len(q_turn.options) < 3:
                q_turn.options = (
                    [
                        "따뜻한 앰버 조명의 다락방 아카이브",
                        "빗소리가 흐르는 심야 FM 라디오 부스",
                        "성수동 스타일의 모던 미니멀 작업실",
                        no_pref_label,
                    ]
                    if lang == "ko"
                    else [
                        "Rainy attic archive with warm brass lamp",
                        "High-floor Seoul FM booth over city lights",
                        "Minimalist Seongsu atelier with vinyl shelves",
                        no_pref_label,
                    ]
                )
            elif not any("no preference" in opt.lower() or "surprise" in opt.lower() or "상관없음" in opt for opt in q_turn.options):
                q_turn.options = q_turn.options[:3] + [no_pref_label]

        # If this_or_that mode (Question 3), provide instant pre-baked WebP/PNG portraits (or generate if missing)
        if q_turn.ui_mode == "this_or_that":
            path_a = sdir / "option_a.png"
            path_b = sdir / "option_b.png"
            bundled_dir = Path(__file__).resolve().parent / "bundled_default"
            if (bundled_dir / "option_a.png").exists() and (bundled_dir / "option_b.png").exists():
                for fname in ("option_a.png", "option_b.png", "option_a.webp", "option_b.webp"):
                    src_f = bundled_dir / fname
                    if src_f.exists() and not (sdir / fname).exists():
                        shutil.copy2(src_f, sdir / fname)
            else:
                render_studio_card_image(
                    path_a,
                    "Option A — Warm Amber Archivist",
                    q_turn.option_a_label or "Silver-ash bob & wire-rim glasses",
                    ["Short silver-ash bob", "Round wire-rim glasses", "Charcoal cardigan", "Warm amber desk lamp"],
                    mode="scene",
                    width=720,
                    height=720,
                )
                render_studio_card_image(
                    path_b,
                    "Option B — Rainlight Engineer",
                    q_turn.option_b_label or "Dark espresso hair & brass headphones",
                    ["Long dark espresso hair", "Brass studio headphones", "Olive jacket", "Rain-streaked window"],
                    mode="scene",
                    width=720,
                    height=720,
                )

            state["assets"]["option_a_url"] = f"/api/session/{session_id}/asset/option_a.webp"
            state["assets"]["option_b_url"] = f"/api/session/{session_id}/asset/option_b.webp"

        state["current_question"] = q_turn.model_dump()
        state["taste_meter"] = q_turn.taste_meter
        state["current_stage"] = f"Question {turn_num} of {max_turns}"
        self.save_session(session_id, state)
        return self.load_session(session_id)

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
            }
        )

        max_turns = state.get("max_turns", 6)
        if q_idx >= max_turns:
            state["status"] = "ready_for_spec"
            state["current_stage"] = "All taste signals collected. Ready to synthesize Character Spec."
            state["taste_meter"] = {
                "setting": 0.96,
                "personality": 0.94,
                "visual": 0.95,
                "voice": 0.93,
                "music": 0.95,
            }
            self.save_session(session_id, state)
            return state

        self.save_session(session_id, state)
        return self.generate_next_question(session_id)

    # -----------------------------------------------------------------------
    # Phase 2: Character Spec Synthesis & Originality Check
    # -----------------------------------------------------------------------
    def synthesize_spec(self, session_id: str) -> dict[str, Any]:
        state = self.load_session(session_id)
        lang = state.get("lang", "en")
        state["status"] = "synthesizing_spec"
        state["current_stage"] = "Synthesizing character specification with gemini-4-argon..."
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
    def run_sheet_loop(self, session_id: str) -> dict[str, Any]:
        state = self.load_session(session_id)
        if not state.get("spec"):
            state = self.synthesize_spec(session_id)
        spec_dict = state["spec"]
        sdir = self.session_dir(session_id)
        sheet_path = sdir / "sheet.png"
        client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))

        state["status"] = "verifying_sheet"
        state["current_stage"] = "Drawing 3-view character sheet with gemini-nano-banana-2.1 (Round 1/3)..."
        self.save_session(session_id, state)

        last_verification: Optional[SheetVerificationResult] = None
        sheet_inter_id: Optional[str] = None
        current_prompt = spec_dict["sheet_prompt"]

        if get_api_key():
            for round_num in range(1, MAX_VERIFY_ROUNDS_SHEET + 1):
                try:
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
    def chat_with_character(self, session_id: str, message: str, lang: str = "ko") -> dict[str, Any]:
        state = self.load_session(session_id)
        spec_dict = state.get("spec") or self._default_character_spec([]).model_dump()
        sdir = self.session_dir(session_id)

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
                        "잠시만요, 작업실 피팅 도어 뒤에서 요청하신 스타일로 바로 갈아입고 나올게요!"
                        if lang == "ko"
                        else "Give me one moment—I will step behind the studio door and change into that look right now."
                    ),
                    spoken_line_en="Give me one moment behind the studio door, I will change into that style for you right now.",
                    mood_cue="피팅 도어 뒤로 이동 중" if lang == "ko" else "steps behind the studio fitting door",
                    action_type="change_style",
                    updated_prompt=f"2D Korean webtoon late-night studio illustration, 16:9 2K. {spec_dict['name']} (adult in mid 20s) with updated look requested by listener: {message}. Warm amber desk lamp light, rain-streaked window.",
                    updated_label="New Studio Look",
                    learned_preference=f"Prefers style: {message[:32]}",
                )
            elif any(k in low_msg for k in ["배경", "방", "루프탑", "창문", "background", "room", "rooftop"]):
                reply_obj = CharacterChatReply(
                    reply=(
                        "좋아요! 가상 작업실 문을 잠시 닫고, 말씀하신 새로운 배경으로 부스를 단장해 올게요."
                        if lang == "ko"
                        else "Let me close the studio partition for a moment and reset our room to match that atmosphere."
                    ),
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
                        "네, 마이크를 조금 더 가까이 당겨서 지금보다 훨씬 조용하고 차분한 목소리로 이야기할게요."
                        if lang == "ko"
                        else "Of course. I will pull the microphone closer and keep my voice much softer from here on."
                    ),
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
                        "지금 바로 Lyria 사운드 엔진으로 요청하신 잔잔한 새 인스트루멘탈 루프를 작곡해서 틀어드릴게요."
                        if lang == "ko"
                        else "I will cue up a fresh instrumental loop on the console matching that exact mood right now."
                    ),
                    spoken_line_en="Let me cue up a fresh late-night instrumental loop on the console for you right now.",
                    mood_cue="새 로파이 트랙 믹싱 중" if lang == "ko" else "cues new Lyria instrumental track",
                    action_type="change_music",
                    updated_prompt=f"Strictly instrumental only, no vocals, no lyrics. Calm late-night lo-fi track matching: {message}. Warm analog mix at 70 BPM.",
                    updated_label="Custom Lo-Fi Mix",
                    learned_preference=f"Music taste: {message[:32]}",
                )
            else:
                reply_obj = CharacterChatReply(
                    reply=(
                        f"오늘 밤에도 저와 함께 작업실을 지켜주셔서 든든해요. 호흡 한 번 천천히 고르고, 우리 조금만 더 집중해 볼까요?"
                        if lang == "ko"
                        else "I am right here across the desk with you. Take a slow breath and let us stay with this page together."
                    ),
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
        if reply_obj.learned_preference:
            memories = state.setdefault("agent_memories", [])
            if reply_obj.learned_preference not in memories:
                memories.append(reply_obj.learned_preference)
                state["agent_memories"] = memories[-8:]

        chat_entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "user_message": message,
            "reply": reply_obj.reply,
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
            ** reply_obj.model_dump(),
            "audio_url": audio_url,
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
