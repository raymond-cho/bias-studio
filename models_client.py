import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Type, TypeVar

from google import genai
from pydantic import BaseModel

from config import (
    MODEL_ARGON,
    MODEL_FLASH,
    MODEL_FLASH_LITE_IMAGE,
    MODEL_LYRIA,
    MODEL_NANO_BANANA,
    MODEL_OMNI_VIDEO,
    MODEL_TRANSCRIBE,
    MODEL_TTS,
    VIDEO_JOB_TIMEOUT_SECONDS,
    get_api_key,
)
from schemas import TraceEntry

T = TypeVar("T", bound=BaseModel)


class ModelUnavailableError(RuntimeError):
    """Raised when an official required model ID is unavailable on the project."""


class GeminiStudioClient:
    """Interactions API client wrapper with automatic trace logging and strict Pydantic parsing."""

    def __init__(self, trace_callback: Optional[Callable[[TraceEntry], None]] = None):
        self.trace_callback = trace_callback

    def _get_client(self) -> genai.Client:
        api_key = get_api_key()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured in app/.env")
        return genai.Client(api_key=api_key)

    def _record_trace(
        self,
        step: str,
        model: str,
        start_time: float,
        summary: str,
        status: str = "ok",
    ) -> None:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        entry = TraceEntry(
            step=step,
            model=model,
            latency_ms=latency_ms,
            summary=summary,
            timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
            status=status,  # type: ignore[arg-type]
        )
        if self.trace_callback:
            self.trace_callback(entry)

    def generate_structured_json(
        self,
        *,
        step: str,
        model: str,
        input_payload: Any,
        schema_cls: Type[T],
        thinking_level: str = "low",
        previous_interaction_id: Optional[str] = None,
    ) -> tuple[T, Optional[str]]:
        """Calls gemini-4-argon or gemini-3.8-flash via Interactions API with strict JSON schema."""
        t0 = time.perf_counter()
        client = self._get_client()

        kwargs: dict[str, Any] = {
            "model": model,
            "input": input_payload,
            "generation_config": {"thinking_level": thinking_level},
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": schema_cls.model_json_schema(),
            },
        }
        if previous_interaction_id:
            kwargs["previous_interaction_id"] = previous_interaction_id

        interaction = client.interactions.create(**kwargs)
        raw_text = getattr(interaction, "output_text", None) or ""
        if not raw_text and getattr(interaction, "steps", None):
            # Extract text from interaction steps if output_text is nested
            for s in reversed(interaction.steps):
                if getattr(s, "output_text", None):
                    raw_text = s.output_text
                    break
        parsed = schema_cls.model_validate_json(raw_text)
        inter_id = getattr(interaction, "id", None)
        self._record_trace(
            step=step,
            model=model,
            start_time=t0,
            summary=f"Structured {schema_cls.__name__} (thinking={thinking_level})",
        )
        return parsed, inter_id

    def generate_image(
        self,
        *,
        step: str,
        model: str,
        prompt: str,
        aspect_ratio: str = "16:9",
        image_size: str = "2K",
        reference_image_bytes: Optional[bytes] = None,
        previous_interaction_id: Optional[str] = None,
    ) -> tuple[bytes, Optional[str]]:
        """Generates or multi-turn edits an image with gemini-nano-banana-2.1 or gemini-3.1-flash-lite-image."""
        t0 = time.perf_counter()
        client = self._get_client()

        # gemini-3.1-flash-lite-image only supports 1K resolution
        if model == MODEL_FLASH_LITE_IMAGE:
            image_size = "1K"

        if reference_image_bytes:
            b64_img = base64.b64encode(reference_image_bytes).decode("ascii")
            input_payload: Any = [
                {"type": "image", "data": b64_img, "mime_type": "image/png"},
                {"type": "text", "text": prompt},
            ]
        else:
            input_payload = prompt

        kwargs: dict[str, Any] = {
            "model": model,
            "input": input_payload,
            "response_format": {
                "type": "image",
                "mime_type": "image/jpeg",
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
            },
        }
        if previous_interaction_id:
            kwargs["previous_interaction_id"] = previous_interaction_id

        interaction = client.interactions.create(**kwargs)
        out_img = getattr(interaction, "output_image", None)
        if not out_img or not getattr(out_img, "data", None):
            raise RuntimeError(f"Model {model} returned no output_image data")

        raw_bytes = base64.b64decode(out_img.data)
        try:
            import io
            from PIL import Image
            im = Image.open(io.BytesIO(raw_bytes))
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            img_bytes = buf.getvalue()
        except Exception:
            img_bytes = raw_bytes
        inter_id = getattr(interaction, "id", None)
        self._record_trace(
            step=step,
            model=model,
            start_time=t0,
            summary=f"Generated {aspect_ratio} {image_size} image ({len(img_bytes) // 1024} KB)",
        )
        return img_bytes, inter_id

    def design_and_synthesize_voice(
        self,
        *,
        character_name: str,
        gender: str,
        voice_description: str,
        dj_script: str,
        dj_style: str,
        asmr_script: str,
        asmr_style: str,
        existing_voice_id: Optional[str] = None,
    ) -> tuple[str, bytes, bytes]:
        """Creates a custom voice with gemini-3.8-flash-tts and synthesizes DJ + ASMR WAVs."""
        client = self._get_client()
        voice_id = existing_voice_id

        if not voice_id:
            t0 = time.perf_counter()
            voice_gender = gender if gender in ("female", "male", "neutral") else "female"
            created_voice = client.voices.create(
                store=True,
                voice={
                    "model": MODEL_TTS,
                    "type": "prompted",
                    "display_name": f"BiasStudio_{character_name[:18]}",
                    "gender": voice_gender,
                    "language_code": "en-US",
                    "prompted": {"input": voice_description},
                },
            )
            voice_id = getattr(created_voice, "id", None) or getattr(created_voice, "name", None)
            self._record_trace(
                step="voice_design",
                model=MODEL_TTS,
                start_time=t0,
                summary=f"Designed custom voice id={voice_id}",
            )

        dj_bytes = self.synthesize_single_line(
            step="tts_dj_intro",
            voice_id=str(voice_id),
            text=dj_script,
            style_hint=dj_style,
        )
        asmr_bytes = self.synthesize_single_line(
            step="tts_asmr_whisper",
            voice_id=str(voice_id),
            text=asmr_script,
            style_hint=asmr_style,
        )
        return str(voice_id), dj_bytes, asmr_bytes

    def synthesize_single_line(
        self,
        *,
        step: str,
        voice_id: str,
        text: str,
        style_hint: str,
    ) -> bytes:
        t0 = time.perf_counter()
        client = self._get_client()
        interaction = client.interactions.create(
            model=MODEL_TTS,
            input=[
                {
                    "type": "user_input",
                    "content": [
                        {
                            "type": "text",
                            "text": text,
                            "annotations": [{"type": "speech_metadata", "style": style_hint}],
                        }
                    ],
                }
            ],
            response_format={"type": "audio"},
            generation_config={"speech_config": [{"voice": voice_id}]},
        )
        out_audio = getattr(interaction, "output_audio", None)
        if not out_audio or not getattr(out_audio, "data", None):
            raise RuntimeError("gemini-3.8-flash-tts returned no output_audio data")
        audio_bytes = base64.b64decode(out_audio.data)
        self._record_trace(
            step=step,
            model=MODEL_TTS,
            start_time=t0,
            summary=f"Synthesized speech ({len(audio_bytes) // 1024} KB)",
        )
        return audio_bytes

    def transcribe_audio(self, *, step: str, wav_path: Path) -> str:
        """Transcribes speech audio using gemini-3.5-transcribe."""
        t0 = time.perf_counter()
        client = self._get_client()
        b64_audio = base64.b64encode(wav_path.read_bytes()).decode("ascii")
        interaction = client.interactions.create(
            model=MODEL_TRANSCRIBE,
            input=[
                {"type": "audio", "data": b64_audio, "mime_type": "audio/wav"},
                {"type": "text", "text": "Transcribe the spoken words accurately."},
            ],
        )
        transcript = (getattr(interaction, "output_text", None) or "").strip()
        self._record_trace(
            step=step,
            model=MODEL_TRANSCRIBE,
            start_time=t0,
            summary=f"ASR transcript: '{transcript[:48]}...'",
        )
        return transcript

    def generate_music_clip(self, *, step: str, music_prompt: str) -> bytes:
        """Generates a 30-second original instrumental clip using lyria-3-clip-preview."""
        t0 = time.perf_counter()
        client = self._get_client()
        interaction = client.interactions.create(
            model=MODEL_LYRIA,
            input=music_prompt,
        )
        out_audio = getattr(interaction, "output_audio", None)
        if not out_audio or not getattr(out_audio, "data", None):
            raise RuntimeError("lyria-3-clip-preview returned no output_audio data")
        audio_bytes = base64.b64decode(out_audio.data)
        self._record_trace(
            step=step,
            model=MODEL_LYRIA,
            start_time=t0,
            summary=f"Generated 30s original instrumental ({len(audio_bytes) // 1024} KB)",
        )
        return audio_bytes

    def generate_video_clip(
        self,
        *,
        step: str,
        scene_png_bytes: bytes,
        motion_prompt: str,
    ) -> bytes:
        """Generates a late-night work video clip using gemini-omni-1.1-flash with 180s timeout."""
        t0 = time.perf_counter()
        client = self._get_client()
        b64_scene = base64.b64encode(scene_png_bytes).decode("ascii")
        interaction = client.interactions.create(
            model=MODEL_OMNI_VIDEO,
            input=[
                {"type": "image", "data": b64_scene, "mime_type": "image/png"},
                {"type": "text", "text": motion_prompt},
            ],
            timeout=float(VIDEO_JOB_TIMEOUT_SECONDS),
        )
        out_video = getattr(interaction, "output_video", None)
        if not out_video or not getattr(out_video, "data", None):
            raise RuntimeError("gemini-omni-1.1-flash returned no output_video data")
        video_bytes = base64.b64decode(out_video.data)
        self._record_trace(
            step=step,
            model=MODEL_OMNI_VIDEO,
            start_time=t0,
            summary=f"Generated work loop video ({len(video_bytes) // 1024} KB)",
        )
        return video_bytes

    def verify_video_with_argon(
        self,
        *,
        step: str,
        video_path: Path,
        sheet_png_bytes: bytes,
        verify_prompt: str,
        schema_cls: Type[T],
    ) -> T:
        """Uploads video.mp4 via Files API and has gemini-4-argon watch it alongside sheet.png."""
        t0 = time.perf_counter()
        client = self._get_client()
        uploaded_video = client.files.upload(file=str(video_path))
        # Wait briefly if file state is PROCESSING
        poll_start = time.time()
        while getattr(getattr(uploaded_video, "state", None), "name", "") == "PROCESSING":
            if time.time() - poll_start > 45:
                break
            time.sleep(2)
            uploaded_video = client.files.get(name=uploaded_video.name)

        b64_sheet = base64.b64encode(sheet_png_bytes).decode("ascii")
        video_uri = getattr(uploaded_video, "uri", None)
        video_mime = getattr(uploaded_video, "mime_type", None) or "video/mp4"

        input_items: list[dict[str, Any]] = []
        if video_uri:
            input_items.append({"type": "video", "uri": video_uri, "mime_type": video_mime})
        else:
            b64_vid = base64.b64encode(video_path.read_bytes()).decode("ascii")
            input_items.append({"type": "video", "data": b64_vid, "mime_type": "video/mp4"})

        input_items.append({"type": "image", "data": b64_sheet, "mime_type": "image/png"})
        input_items.append({"type": "text", "text": verify_prompt})

        parsed, _ = self.generate_structured_json(
            step=step,
            model=MODEL_ARGON,
            input_payload=input_items,
            schema_cls=schema_cls,
            thinking_level="low",
        )
        return parsed
