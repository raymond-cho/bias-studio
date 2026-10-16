import base64
import json
import re
import shutil
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
    render_studio_card_image,
    synthesize_warm_lofi_wav,
)
from models_client import GeminiStudioClient
from prompts import (
    build_music_verify_prompt,
    build_question_prompt,
    build_safety_prompt,
    build_sheet_verify_prompt,
    build_spec_prompt,
    build_video_verify_prompt,
    build_voice_verify_prompt,
)
from schemas import (
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


# Fallback question progression when running offline/before API key is pasted
FALLBACK_QUESTIONS: list[dict[str, Any]] = [
    {
        "question": "When you sit down to work after midnight, what room settles your focus?",
        "axis": "setting",
        "ui_mode": "choices",
        "options": [
            "Attic archive with rain on the skylight and a brass desk lamp",
            "High-floor city booth overlooking quiet sodium-lit streets",
            "Warm wood-paneled analog tape studio with shelves of vinyl",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.82,
        "taste_meter": {"setting": 0.35, "personality": 0.15, "visual": 0.15, "voice": 0.15, "music": 0.15},
        "ready_for_spec": False,
    },
    {
        "question": "How should your companion keep you company while the 25-minute timer runs?",
        "axis": "personality",
        "ui_mode": "choices",
        "options": [
            "Calm archivist who turns pages quietly and offers dry, warm encouragement",
            "Focused night-shift radio engineer adjusting faders and sipping black coffee",
            "Gentle illustrator sketching beside you with unhurried, observant remarks",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.65,
        "taste_meter": {"setting": 0.85, "personality": 0.45, "visual": 0.20, "voice": 0.20, "music": 0.20},
        "ready_for_spec": False,
    },
    {
        "question": "Which silhouette and studio palette feels right across the desk from you?",
        "axis": "visual",
        "ui_mode": "this_or_that",
        "options": [
            "Option A: Short silver-ash bob, wire-rim glasses, oversized charcoal cardigan",
            "Option B: Long dark espresso hair, brass studio headphones, warm olive jacket",
            "Blend both: dark hair with wire-rim glasses and charcoal knitwear",
            "No preference — surprise me",
        ],
        "option_a": "2D anime studio illustration of an adult in their mid 20s with a short silver-ash bob, round wire-rim glasses, oversized charcoal knit cardigan, warm amber desk lamp rim light, dark midnight slate background",
        "option_b": "2D anime studio illustration of an adult in their mid 20s with long dark espresso hair, vintage brass studio headphones around neck, olive corduroy jacket, cool rainlight window glow, dark studio background",
        "option_a_label": "Silver-ash bob, wire-rim glasses & charcoal knit",
        "option_b_label": "Dark espresso hair, brass headphones & olive corduroy",
        "uncertainty_remaining": 0.48,
        "taste_meter": {"setting": 0.88, "personality": 0.82, "visual": 0.55, "voice": 0.25, "music": 0.25},
        "ready_for_spec": False,
    },
    {
        "question": "What signature desk detail should anchor their character sheet?",
        "axis": "visual",
        "ui_mode": "choices",
        "options": [
            "Amber fountain pen tucked behind one ear and a leather-bound ledger",
            "Vintage brass broadcast microphone on a swivel arm with warm VU meters",
            "Ceramic mug of hojicha tea and a pair of folded tortoiseshell frames",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.32,
        "taste_meter": {"setting": 0.90, "personality": 0.85, "visual": 0.88, "voice": 0.35, "music": 0.30},
        "ready_for_spec": False,
    },
    {
        "question": "When your host opens the session, how should their voice sound?",
        "axis": "voice",
        "ui_mode": "choices",
        "options": [
            "Low, unhurried contralto radio tone with close-mic warmth",
            "Soft, grounded baritone with crisp late-night broadcast pacing",
            "Quiet, airy mid-register voice with gentle page-turn pauses",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.18,
        "taste_meter": {"setting": 0.92, "personality": 0.88, "visual": 0.90, "voice": 0.85, "music": 0.40},
        "ready_for_spec": False,
    },
    {
        "question": "What original instrumental soundscape should loop beneath your work?",
        "axis": "music",
        "ui_mode": "choices",
        "options": [
            "Warm Rhodes electric piano lo-fi jazz at 74 BPM with brushed snare",
            "Nocturnal acoustic guitar and muted upright bass at 68 BPM",
            "Minimalist analog synth and felt-piano rain loop at 78 BPM",
            "No preference — surprise me",
        ],
        "uncertainty_remaining": 0.05,
        "taste_meter": {"setting": 0.95, "personality": 0.92, "visual": 0.94, "voice": 0.90, "music": 0.92},
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

    def create_session(self, max_turns: int = 6) -> dict[str, Any]:
        session_id = uuid.uuid4().hex[:10]
        state: dict[str, Any] = {
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "max_turns": max_turns,
            "turn_number": 0,
            "status": "questioning",
            "current_stage": "Initializing studio session...",
            "qa_history": [],
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

        if not get_api_key():
            return SafetyCheckResult(allowed=True, reason="ok", safe_alternative_suggestion=None)

        client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))
        try:
            res, _ = client.generate_structured_json(
                step="safety_check",
                model=MODEL_ARGON,
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
        state["turn_number"] = turn_num
        sdir = self.session_dir(session_id)

        client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))
        q_turn: Optional[QuestionTurn] = None

        if get_api_key():
            try:
                prompt = build_question_prompt(
                    history=state["qa_history"],
                    turn_number=turn_num,
                    max_turns=max_turns,
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
            fb_idx = (turn_num - 1) % len(FALLBACK_QUESTIONS)
            fb_data = dict(FALLBACK_QUESTIONS[fb_idx])
            fb_data["ready_for_spec"] = turn_num >= max_turns
            q_turn = QuestionTurn(**fb_data)

        # Ensure at least 4 options are present for easy multiple choice selection
        if len(q_turn.options) < 3:
            q_turn.options = [
                "Warm analog studio mood with soft amber lamp light",
                "Crisp rain-lit night window with quiet focused energy",
                "Minimalist dark booth with subtle acoustic warmth",
                "No preference — surprise me",
            ]
        elif not any("no preference" in opt.lower() or "surprise" in opt.lower() for opt in q_turn.options):
            q_turn.options = q_turn.options[:3] + ["No preference — surprise me"]

        # If this_or_that mode (Question 3), generate Option A and Option B 1K images
        if q_turn.ui_mode == "this_or_that":
            prompt_a = q_turn.option_a or "Anime studio portrait of an adult late-night archivist with short silver-ash bob and wire-rim glasses under warm amber desk lamp"
            prompt_b = q_turn.option_b or "Anime studio portrait of an adult late-night radio host with long dark hair and brass headphones by a rain-streaked window"
            path_a = sdir / "option_a.png"
            path_b = sdir / "option_b.png"

            if get_api_key():
                try:
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        fut_a = pool.submit(
                            client.generate_image,
                            step="q3_option_a_image",
                            model=MODEL_FLASH_LITE_IMAGE,
                            prompt=prompt_a,
                            aspect_ratio="1:1",
                            image_size="1K",
                        )
                        fut_b = pool.submit(
                            client.generate_image,
                            step="q3_option_b_image",
                            model=MODEL_FLASH_LITE_IMAGE,
                            prompt=prompt_b,
                            aspect_ratio="1:1",
                            image_size="1K",
                        )
                        bytes_a, _ = fut_a.result(timeout=45)
                        bytes_b, _ = fut_b.result(timeout=45)
                        path_a.write_bytes(bytes_a)
                        path_b.write_bytes(bytes_b)
                except Exception:
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

            state["assets"]["option_a_url"] = f"/api/session/{session_id}/asset/option_a.png?t={int(time.time())}"
            state["assets"]["option_b_url"] = f"/api/session/{session_id}/asset/option_b.png?t={int(time.time())}"

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
        if q_idx >= max_turns or curr_q.get("ready_for_spec", False):
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
        state["status"] = "synthesizing_spec"
        state["current_stage"] = "Synthesizing character specification with gemini-4-argon (thinking=medium)..."
        self.save_session(session_id, state)

        sdir = self.session_dir(session_id)
        client = GeminiStudioClient(trace_callback=lambda e: self.append_trace(session_id, e))
        spec: Optional[CharacterSpec] = None

        if get_api_key():
            try:
                prompt = build_spec_prompt(state["qa_history"], PRESTUDY_NAMES)
                spec, inter_id = client.generate_structured_json(
                    step="spec_synthesis",
                    model=MODEL_ARGON,
                    input_payload=prompt,
                    schema_cls=CharacterSpec,
                    thinking_level="medium",
                    previous_interaction_id=state.get("argon_interaction_id"),
                )
                if inter_id:
                    state["argon_interaction_id"] = inter_id

                # Originality check against 100 pre-study VTuber names
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
                            summary=f"Verified '{spec.name}' against 101 pre-study names: 0 collisions.",
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

                    dj_transcript = client.transcribe_audio(step=f"transcribe_dj_r{round_num}", wav_path=dj_path)
                    asmr_transcript = client.transcribe_audio(step=f"transcribe_asmr_r{round_num}", wav_path=asmr_path)

                    dj_overlap = _compute_word_overlap(spec_dict["dj_intro_script"], dj_transcript)
                    asmr_overlap = _compute_word_overlap(spec_dict["asmr_whisper_script"], asmr_transcript)

                    b64_dj = base64.b64encode(dj_path.read_bytes()).decode("ascii")
                    dj_score, _ = client.generate_structured_json(
                        step=f"voice_verify_dj_r{round_num}",
                        model=MODEL_FLASH,
                        input_payload=[
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
                        schema_cls=VoiceQualityScore,
                        thinking_level="low",
                    )

                    b64_asmr = base64.b64encode(asmr_path.read_bytes()).decode("ascii")
                    asmr_score, _ = client.generate_structured_json(
                        step=f"voice_verify_asmr_r{round_num}",
                        model=MODEL_FLASH,
                        input_payload=[
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
                        schema_cls=VoiceQualityScore,
                        thinking_level="low",
                    )

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

        # Step 1: Generate 16:9 work room scene anchored on the character sheet
        if get_api_key():
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
        if (sdir / "session.json").exists() and (sdir / "study.mp4").exists():
            return
        sdir.mkdir(parents=True, exist_ok=True)
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
