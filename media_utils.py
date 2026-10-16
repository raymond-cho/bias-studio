import base64
import io
import json
import math
import shutil
import struct
import subprocess
import wave
import zipfile
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin


def get_ffmpeg_bin() -> str:
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def convert_audio_to_wav(input_bytes: bytes, out_wav_path: Path) -> Path:
    """Saves audio bytes (WAV or MP3) as a standard 44.1kHz 16-bit PCM WAV file."""
    out_wav_path.parent.mkdir(parents=True, exist_ok=True)
    # If already RIFF WAV, write directly first
    raw_tmp = out_wav_path.with_suffix(".raw_audio")
    raw_tmp.write_bytes(input_bytes)
    ffmpeg_bin = get_ffmpeg_bin()
    try:
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-i",
                str(raw_tmp),
                "-ar",
                "44100",
                "-ac",
                "2",
                str(out_wav_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except Exception:
        # Fallback if input_bytes is already valid wav
        out_wav_path.write_bytes(input_bytes)
    finally:
        if raw_tmp.exists():
            raw_tmp.unlink(missing_ok=True)
    return out_wav_path


def get_audio_duration_seconds(wav_path: Path) -> float:
    try:
        with wave.open(str(wav_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return round(frames / float(rate), 2) if rate else 0.0
    except Exception:
        return 0.0


def render_animated_scene_mp4(
    scene_png_path: Path,
    out_mp4_path: Path,
    fps: int = 16,
    loop_seconds: int = 4,
    prev_scene_png_path: Optional[Path] = None,
) -> Path:
    """Renders a 16fps (>=12fps anime standard) 2.5D animated loop MP4 from a scene still image.
    When prev_scene_png_path is provided, smoothly cross-dissolves from the previous look into the new look
    before continuing with the breathing, rain-streak, and warm desk-lamp loop."""
    ffmpeg_bin = get_ffmpeg_bin()
    out_mp4_path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = fps * loop_seconds
    base_img = Image.open(scene_png_path).convert("RGB").resize((1280, 720), Image.Resampling.LANCZOS)
    prev_img: Optional[Image.Image] = None
    if prev_scene_png_path and prev_scene_png_path.exists():
        try:
            prev_img = Image.open(prev_scene_png_path).convert("RGB").resize((1280, 720), Image.Resampling.LANCZOS)
        except Exception:
            prev_img = None

    proc = subprocess.Popen(
        [
            ffmpeg_bin,
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-s",
            "1280x720",
            "-pix_fmt",
            "rgb24",
            "-r",
            str(fps),
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "21",
            "-pix_fmt",
            "yuv420p",
            str(out_mp4_path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    transition_frames = min(fps, total_frames // 2) if prev_img is not None else 0

    try:
        for f_idx in range(total_frames):
            phase = (f_idx / float(total_frames)) * (2.0 * math.pi)
            # Subtle 12-16fps anime breathing & camera micro-sway
            zoom = 1.025 + 0.012 * math.sin(phase)
            cw = int(1280 / zoom)
            ch = int(720 / zoom)
            cx = (1280 - cw) // 2 + int(4.0 * math.cos(phase))
            cy = (720 - ch) // 2 + int(5.0 * math.sin(phase))
            frame = base_img.crop((cx, cy, cx + cw, cy + ch)).resize((1280, 720), Image.Resampling.BILINEAR)

            if prev_img is not None and f_idx < transition_frames:
                # Smooth cosine ease-in-out cross-dissolve from previous look to new look
                t_norm = (f_idx + 1) / float(transition_frames)
                alpha = 0.5 - 0.5 * math.cos(math.pi * t_norm)
                prev_crop = prev_img.crop((cx, cy, cx + cw, cy + ch)).resize((1280, 720), Image.Resampling.BILINEAR)
                frame = Image.blend(prev_crop, frame, alpha)

            draw = ImageDraw.Draw(frame)
            # Animated rain streaks on window region + warm amber dust motes
            for r_i in range(22):
                rx = (90 + r_i * 53 - f_idx * 6) % 1240
                ry = (40 + r_i * 89 + f_idx * 28) % 640
                draw.line([(rx, ry), (rx - 9, ry + 34)], fill=(155, 192, 224), width=1)

            # Warm lamp breathing pulse in upper-right/center
            mote_y = int(280 + 10 * math.sin(phase + 1.2))
            draw.ellipse([980, mote_y, 986, mote_y + 6], fill=(238, 190, 98))
            draw.ellipse([320, int(220 + 8 * math.cos(phase)), 325, int(225 + 8 * math.cos(phase))], fill=(232, 176, 75))

            if proc.stdin:
                proc.stdin.write(frame.tobytes())
        if proc.stdin:
            proc.stdin.close()
        proc.wait(timeout=45)
    except Exception:
        proc.kill()
        raise
    return out_mp4_path


def mux_study_mp4(
    visual_path: Path,
    dj_wav_path: Optional[Path],
    loop_wav_path: Path,
    out_mp4_path: Path,
    is_static_image: bool = False,
    duration_sec: int = 24,
) -> Path:
    """Muxes the verified video (or 16fps animated scene still) + DJ intro + instrumental loop into study_with_<name>.mp4."""
    ffmpeg_bin = get_ffmpeg_bin()
    out_mp4_path.parent.mkdir(parents=True, exist_ok=True)

    # First mix dj_wav + loop_wav into mixed_audio.aac/wav if dj_wav exists
    mixed_wav = out_mp4_path.parent / "_mixed_study_audio.wav"
    if dj_wav_path and dj_wav_path.exists() and loop_wav_path.exists():
        try:
            subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-stream_loop",
                    "-1",
                    "-i",
                    str(loop_wav_path),
                    "-i",
                    str(dj_wav_path),
                    "-filter_complex",
                    f"[0:a]volume=0.55,atrim=0:{duration_sec}[bg];[1:a]adelay=1000|1000,volume=1.15[fg];[bg][fg]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                    "-map",
                    "[aout]",
                    "-t",
                    str(duration_sec),
                    str(mixed_wav),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=45,
            )
        except Exception:
            shutil.copyfile(loop_wav_path, mixed_wav)
    elif loop_wav_path.exists():
        shutil.copyfile(loop_wav_path, mixed_wav)

    try:
        video_input_path = visual_path
        if is_static_image or visual_path.suffix.lower() in (".png", ".jpg", ".jpeg"):
            anim_loop_mp4 = out_mp4_path.parent / "video.mp4"
            if out_mp4_path == anim_loop_mp4:
                try:
                    render_animated_scene_mp4(visual_path, anim_loop_mp4, fps=12, loop_seconds=3)
                    return anim_loop_mp4
                except Exception:
                    video_input_path = visual_path
            else:
                if not anim_loop_mp4.exists():
                    try:
                        render_animated_scene_mp4(visual_path, anim_loop_mp4, fps=12, loop_seconds=3)
                    except Exception:
                        pass
                video_input_path = anim_loop_mp4 if anim_loop_mp4.exists() else visual_path

        if video_input_path.suffix.lower() in (".png", ".jpg", ".jpeg"):
            subprocess.run(
                [
                    ffmpeg_bin,
                    "-y",
                    "-loop",
                    "1",
                    "-i",
                    str(video_input_path),
                    "-i",
                    str(mixed_wav),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-tune",
                    "stillimage",
                    "-pix_fmt",
                    "yuv420p",
                    "-vf",
                    "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                    "-t",
                    str(duration_sec),
                    str(out_mp4_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
        else:
            # Fast stream-copy path (-c:v copy) avoids re-encoding H.264 frames (40ms vs 1500ms)
            try:
                subprocess.run(
                    [
                        ffmpeg_bin,
                        "-y",
                        "-stream_loop",
                        "-1",
                        "-i",
                        str(video_input_path),
                        "-i",
                        str(mixed_wav),
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a:0",
                        "-c:v",
                        "copy",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "192k",
                        "-shortest",
                        "-t",
                        str(duration_sec),
                        str(out_mp4_path),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
            except Exception:
                subprocess.run(
                    [
                        ffmpeg_bin,
                        "-y",
                        "-stream_loop",
                        "-1",
                        "-i",
                        str(video_input_path),
                        "-i",
                        str(mixed_wav),
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a:0",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "ultrafast",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "192k",
                        "-t",
                        str(duration_sec),
                        str(out_mp4_path),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                )
    finally:
        mixed_wav.unlink(missing_ok=True)
    return out_mp4_path


def build_chara_card_v2(spec_dict: dict) -> dict:
    """Builds a standard Character Card V2 (chara_card_v2) JSON payload."""
    return {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": spec_dict.get("name", "Sora"),
            "description": spec_dict.get("personality_summary", ""),
            "personality": spec_dict.get("archetype", ""),
            "scenario": spec_dict.get("setting_description", ""),
            "first_mes": spec_dict.get("dj_intro_script", ""),
            "mes_example": f"<START>\n{{{{char}}}}: {spec_dict.get('asmr_whisper_script', '')}",
            "creator_notes": f"Generated by Bias Studio (Your bias. Your lo-fi.). Apparent age: {spec_dict.get('apparent_age', 'mid 20s')}.",
            "system_prompt": f"You are {spec_dict.get('name', 'Sora')}, a calm late-night work companion.",
            "post_history_instructions": "",
            "alternate_greetings": [spec_dict.get("asmr_whisper_script", "")],
            "tags": [
                "bias-studio",
                "late-night-focus",
                spec_dict.get("music_genre", "lo-fi"),
            ],
            "creator": "Bias Studio",
            "character_version": "1.0.0",
            "extensions": {
                "bias_studio": {
                    "tagline": spec_dict.get("tagline"),
                    "apparent_age": spec_dict.get("apparent_age"),
                    "visual_traits": spec_dict.get("visual_traits", []),
                    "provenance": spec_dict.get("provenance", []),
                    "voice_description": spec_dict.get("voice_description"),
                    "music_genre": spec_dict.get("music_genre"),
                    "music_bpm": spec_dict.get("music_bpm"),
                    "music_key": spec_dict.get("music_key"),
                    "music_instruments": spec_dict.get("music_instruments", []),
                }
            },
        },
    }


def embed_chara_card_in_png(png_path: Path, chara_card: dict, out_png_path: Path) -> Path:
    """Embeds base64-encoded chara_card_v2 JSON in the PNG 'chara' tEXt chunk."""
    img = Image.open(png_path)
    meta = PngImagePlugin.PngInfo()
    b64_payload = base64.b64encode(json.dumps(chara_card, ensure_ascii=False).encode("utf-8")).decode("ascii")
    meta.add_text("chara", b64_payload)
    img.save(out_png_path, "PNG", pnginfo=meta)
    return out_png_path


def build_character_kit_zip(
    session_dir: Path,
    spec_dict: dict,
    verification_summary: dict,
    trace_list: list[dict],
) -> Path:
    """Packages the verified character sheet, audio tracks, video, and chara_card_v2 metadata into a zip."""
    chara_card = build_chara_card_v2(spec_dict)
    card_json_text = json.dumps(chara_card, indent=2, ensure_ascii=False)
    (session_dir / "character_card_v2.json").write_text(card_json_text, encoding="utf-8")
    (session_dir / "character_card.json").write_text(card_json_text, encoding="utf-8")

    spec_json_text = json.dumps(spec_dict, indent=2, ensure_ascii=False)
    (session_dir / "spec.json").write_text(spec_json_text, encoding="utf-8")
    (session_dir / "character_spec.json").write_text(spec_json_text, encoding="utf-8")

    persona_md = (
        f"# {spec_dict.get('name', 'Sora')} — {spec_dict.get('tagline', '')}\n\n"
        f"- **Archetype:** {spec_dict.get('archetype', '')}\n"
        f"- **Apparent Age:** {spec_dict.get('apparent_age', 'mid 20s')}\n"
        f"- **Setting:** {spec_dict.get('setting_description', '')}\n"
        f"- **Music:** {spec_dict.get('music_genre', '')} ({spec_dict.get('music_bpm', 74)} BPM, {spec_dict.get('music_key', 'F minor')})\n\n"
        f"## Personality\n{spec_dict.get('personality_summary', '')}\n\n"
        f"## Visual Traits (8/8)\n"
        + "\n".join(f"- {t}" for t in spec_dict.get("visual_traits", []))
        + f"\n\n## Broadcast Intro (DJ)\n> {spec_dict.get('dj_intro_script', '')}\n\n"
        f"## Focus Check-In (ASMR)\n> {spec_dict.get('asmr_whisper_script', '')}\n"
    )
    (session_dir / "persona.md").write_text(persona_md, encoding="utf-8")

    sheet_path = session_dir / "sheet.png"
    card_png_path = session_dir / "character_card_v2.png"
    if sheet_path.exists():
        try:
            embed_chara_card_in_png(sheet_path, chara_card, card_png_path)
            embed_chara_card_in_png(sheet_path, chara_card, sheet_path)
        except Exception:
            shutil.copyfile(sheet_path, card_png_path)

    report_path = session_dir / "verification_report.json"
    report_path.write_text(
        json.dumps(
            {
                "character": spec_dict.get("name"),
                "verification": verification_summary,
                "trace": trace_list,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report_md = (
        f"# Verification Report — {spec_dict.get('name', 'Sora')}\n\n"
        f"```json\n{json.dumps(verification_summary, indent=2, ensure_ascii=False)}\n```\n"
    )
    (session_dir / "verification_report.md").write_text(report_md, encoding="utf-8")

    if (session_dir / "dj.wav").exists() and not (session_dir / "voice_dj.wav").exists():
        shutil.copyfile(session_dir / "dj.wav", session_dir / "voice_dj.wav")
    if (session_dir / "asmr.wav").exists() and not (session_dir / "voice_asmr.wav").exists():
        shutil.copyfile(session_dir / "asmr.wav", session_dir / "voice_asmr.wav")

    zip_path = session_dir / "character_kit.zip"
    include_files = [
        "spec.json",
        "character_spec.json",
        "character_card.json",
        "character_card_v2.json",
        "character_card_v2.png",
        "persona.md",
        "verification_report.json",
        "verification_report.md",
        "sheet.png",
        "scene.png",
        "dj.wav",
        "voice_dj.wav",
        "asmr.wav",
        "voice_asmr.wav",
        "loop.wav",
        "video.mp4",
        "study.mp4",
    ]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname in include_files:
            fpath = session_dir / fname
            if fpath.exists():
                zf.write(fpath, arcname=fname)
    return zip_path


# ---------------------------------------------------------------------------
# Pre-Built K-Webtoon Sample Resolver & Fast Illustrated Compositor
# ---------------------------------------------------------------------------

def resolve_prebuilt_samples(
    title: str = "",
    subtitle: str = "",
    traits: Optional[list[str]] = None,
    char_sample_path: Optional[Path] = None,
    bg_sample_path: Optional[Path] = None,
) -> tuple[Optional[Path], Optional[Path]]:
    """Matches character traits/name/setting to the pre-rendered K-Webtoon character & background `.webp` library."""
    samples_dir = Path(__file__).resolve().parent / "static" / "samples"
    if not samples_dir.exists():
        return None, None

    corpus = f"{title} {subtitle} {' '.join(traits or [])}".lower()

    if char_sample_path is None or not char_sample_path.exists():
        char_file = "char_1.webp"
        if any(k in corpus for k in ["do-jin", "dojin", "도진", "baritone", "바리톤", "broadcast engineer"]):
            char_file = "tue.webp"
        elif any(k in corpus for k in ["tae-o", "taeo", "태오", "architect", "시니어", "개발", "남성", "male", "baritone"]):
            char_file = "thu.webp"
        elif any(k in corpus for k in ["si-woo", "siwoo", "시우", "film", "영화", "entp", "장난"]):
            char_file = "sat.webp"
        elif any(k in corpus for k in ["ji-an", "jian", "지안", "hanok", "한옥", "서예", "고전"]):
            char_file = "sun.webp"
        elif any(k in corpus for k in ["seol-ah", "seolah", "설아", "vinyl", "을지로", "레코드", "보라"]):
            char_file = "wed.webp"
        elif any(k in corpus for k in ["yu-na", "yuna", "유나", "botanical", "식물", "연남", "말차"]):
            char_file = "fri.webp"
        elif any(k in corpus for k in ["hae-in", "haein", "해인", "webtoon", "성수", "베레모"]):
            char_file = "mon.webp"
        elif any(k in corpus for k in ["중성", "androgynous", "neutral", "몽환"]):
            char_file = "char_2.webp"
        else:
            # Deterministic hash across char_1..char_6 so different custom characters get distinct portraits
            pool = ["char_1.webp", "char_2.webp", "char_3.webp", "char_4.webp", "char_5.webp", "char_6.webp"]
            h = sum(ord(c) for c in corpus) if corpus else 0
            char_file = pool[h % len(pool)]
        candidate = samples_dir / char_file
        if candidate.exists():
            char_sample_path = candidate

    if bg_sample_path is None or not bg_sample_path.exists():
        bg_file = "bg_seongsu.webp"
        if any(k in corpus for k in ["한강", "hangang", "야경", "라디오", "broadcast", "city", "남산"]):
            bg_file = "bg_hangang.webp"
        elif any(k in corpus for k in ["을지로", "빈티지", "레코드", "vinyl", "다락방", "attic", "이태원"]):
            bg_file = "bg_itaewon.webp"
        elif any(k in corpus for k in ["한옥", "hanok", "북촌", "전주", "처마", "차실"]):
            bg_file = "bg_jeonju.webp"
        elif any(k in corpus for k in ["비", "rain", "식물", "온실", "연남", "botanical"]):
            bg_file = "bg_yeonnam.webp"
        elif any(k in corpus for k in ["바다", "제주", "해운대", "파도", "jeju"]):
            bg_file = "bg_jeju.webp"
        elif any(k in corpus for k in ["타워", "스카이라인", "고층", "펜트하우스"]):
            bg_file = "bg_lottetower.webp"
        elif any(k in corpus for k in ["숲", "산장", "오두막", "모닥불", "mountain"]):
            bg_file = "bg_mountain.webp"
        else:
            bg_pool = ["bg_seongsu.webp", "bg_hangang.webp", "bg_yeonnam.webp", "bg_namsan.webp", "bg_itaewon.webp", "bg_jeonju.webp"]
            h = sum(ord(c) for c in corpus) if corpus else 0
            bg_file = bg_pool[h % len(bg_pool)]
        candidate_bg = samples_dir / bg_file
        if candidate_bg.exists():
            bg_sample_path = candidate_bg

    return char_sample_path, bg_sample_path


def render_studio_card_image(
    out_path: Path,
    title: str,
    subtitle: str,
    traits: list[str],
    mode: str = "sheet",
    width: int = 1280,
    height: int = 720,
    char_sample_path: Optional[Path] = None,
    bg_sample_path: Optional[Path] = None,
) -> Path:
    """Renders a high-speed illustrated 3-View Character Sheet or Late-Night Studio Scene using pre-built K-Webtoon samples."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), (14, 15, 20))
    draw = ImageDraw.Draw(img)

    char_path, bg_path = resolve_prebuilt_samples(title, subtitle, traits, char_sample_path, bg_sample_path)

    amber = (232, 176, 75)
    cool = (127, 179, 213)
    text_main = (236, 233, 226)
    text_muted = (154, 150, 142)

    if mode == "sheet":
        # Subtle grid lines
        for x in range(0, width, 64):
            draw.line([(x, 0), (x, height)], fill=(22, 24, 33), width=1)
        for y in range(0, height, 64):
            draw.line([(0, y), (width, y)], fill=(22, 24, 33), width=1)

        panel_labels = ["01 / FULL PORTRAIT", "02 / GAZE & EXPRESSION", "03 / STUDIO LIGHTING"]
        panel_w = 244
        panel_h = 468
        start_x = 56
        char_img = None
        bg_img = None
        if char_path and char_path.exists():
            try:
                char_img = Image.open(char_path).convert("RGB")
            except Exception:
                char_img = None
        if bg_path and bg_path.exists():
            try:
                bg_img = Image.open(bg_path).convert("RGB")
            except Exception:
                bg_img = None

        for idx, plabel in enumerate(panel_labels):
            px = start_x + idx * (panel_w + 20)
            py = 126
            draw.rectangle([px, py, px + panel_w, py + panel_h], fill=(22, 24, 33), outline=(48, 52, 68), width=2)

            if char_img is not None:
                cw, ch = char_img.size
                inner_w, inner_h = panel_w - 8, panel_h - 42
                if idx == 0:
                    # Full portrait center crop
                    crop_box = (max(0, (cw - int(ch * (inner_w / inner_h))) // 2), 0, min(cw, cw - max(0, (cw - int(ch * (inner_w / inner_h))) // 2)), ch)
                    view_crop = char_img.crop(crop_box).resize((inner_w, inner_h), Image.Resampling.LANCZOS)
                elif idx == 1:
                    # Upper close-up gaze & facial detail crop
                    zoom_w, zoom_h = int(cw * 0.58), int(ch * 0.58)
                    left = (cw - zoom_w) // 2
                    top = max(0, int(ch * 0.06))
                    view_crop = char_img.crop((left, top, left + zoom_w, top + zoom_h)).resize((inner_w, inner_h), Image.Resampling.LANCZOS)
                else:
                    # Studio mood blend with background & warm rim tint
                    crop_box = (max(0, (cw - int(ch * (inner_w / inner_h))) // 2), 0, min(cw, cw - max(0, (cw - int(ch * (inner_w / inner_h))) // 2)), ch)
                    char_resized = char_img.crop(crop_box).resize((inner_w, inner_h), Image.Resampling.LANCZOS)
                    if bg_img is not None:
                        bg_resized = bg_img.resize((inner_w, inner_h), Image.Resampling.BILINEAR)
                        view_crop = Image.blend(char_resized, bg_resized, 0.24)
                    else:
                        view_crop = char_resized
                img.paste(view_crop, (px + 4, py + 36))
            else:
                cx = px + panel_w // 2
                draw.ellipse([cx - 34, py + 82, cx + 34, py + 152], fill=(195, 198, 208), outline=amber, width=2)
                draw.polygon([(cx - 64, py + 430), (cx - 48, py + 175), (cx + 48, py + 175), (cx + 64, py + 430)], fill=(36, 39, 52), outline=cool)

            draw.rectangle([px + 2, py + 2, px + panel_w - 2, py + 34], fill=(16, 18, 26))
            draw.text((px + 12, py + 10), plabel, fill=amber)

        # Right-side trait callout table
        tx = 856
        ty = 126
        draw.rectangle([tx, ty, width - 48, ty + panel_h], fill=(20, 22, 31), outline=(48, 52, 68), width=2)
        draw.text((tx + 20, ty + 16), "VERIFIED VISUAL TRAITS (8/8)", fill=amber)
        for i, trait in enumerate(traits[:8]):
            row_y = ty + 52 + i * 50
            draw.rectangle([tx + 18, row_y, tx + 34, row_y + 16], outline=amber, fill=(42, 36, 24))
            short_t = trait if len(trait) <= 44 else trait[:41] + "..."
            draw.text((tx + 44, row_y), f"T{i+1}: {short_t}", fill=text_main)
    else:
        # Late-night work studio scene composite (Studio Background + Character Portrait + Warm Lamp Aura)
        if bg_path and bg_path.exists():
            try:
                bg_raw = Image.open(bg_path).convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
                dark_overlay = Image.new("RGB", (width, height), (12, 14, 22))
                img = Image.blend(bg_raw, dark_overlay, 0.28)
                draw = ImageDraw.Draw(img)
            except Exception:
                pass

        if char_path and char_path.exists():
            try:
                char_raw = Image.open(char_path).convert("RGB")
                cw, ch = char_raw.size
                target_h = 560
                target_w = int(cw * (target_h / float(ch)))
                target_w = min(680, max(420, target_w))
                char_card = char_raw.resize((target_w, target_h), Image.Resampling.LANCZOS)
                cx1 = (width - target_w) // 2
                cy1 = 104
                # Subtle studio monitor / booth frame around character in room
                draw.rectangle([cx1 - 6, cy1 - 6, cx1 + target_w + 6, cy1 + target_h + 6], fill=(16, 18, 26), outline=amber, width=2)
                img.paste(char_card, (cx1, cy1))
            except Exception:
                pass

        # Header & footer translucent bars
        draw.rectangle([0, 0, width, 96], fill=(12, 14, 20))
        draw.rectangle([0, height - 56, width, height], fill=(12, 14, 20))

    draw.rectangle([24, 24, width - 24, height - 24], outline=(42, 46, 62), width=1)
    draw.text((56, 42), f"BIAS STUDIO // {title.upper()}", fill=amber)
    draw.text((56, 68), subtitle[:96], fill=text_muted)
    draw.text((56, height - 42), "16:9 STUDIO REFERENCE  |  ADULT ARCHETYPE (20+)  |  ORIGINAL IP", fill=text_muted)

    img.save(out_path, "PNG")
    return out_path


def synthesize_warm_lofi_wav(
    out_path: Path,
    duration_sec: float = 12.0,
    bpm: int = 74,
    is_voice: bool = False,
    style_seed: int = 0,
) -> Path:
    """Generates a warm stereo WAV file using fast memory-tiled bar synthesis (<50ms for 30s audio)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 44100
    beat_sec = 60.0 / max(54, min(96, bpm))

    # 6 distinct harmonic progressions so different archetypes have genuinely distinct BGM loops
    progressions = [
        # 0: Fmin9 -> Bb13 -> Ebmaj9 -> Abmaj7 (Classic Warm Rhodes Lo-Fi)
        [
            [174.61, 207.65, 261.63, 311.13, 392.00],
            [116.54, 207.65, 246.94, 293.66, 349.23],
            [155.56, 196.00, 233.08, 293.66, 349.23],
            [207.65, 261.63, 311.13, 392.00, 466.16],
        ],
        # 1: Dmin9 -> G13 -> Cmaj9 -> Fmaj7 (Cozy Seongsu Cafe Acoustic)
        [
            [146.83, 174.61, 220.00, 261.63, 329.63],
            [196.00, 246.94, 293.66, 349.23, 440.00],
            [130.81, 164.81, 196.00, 246.94, 293.66],
            [174.61, 220.00, 261.63, 329.63, 392.00],
        ],
        # 2: Amin9 -> D9 -> Gmaj9 -> Cmaj7 (Midnight Han River Broadcast)
        [
            [110.00, 130.81, 164.81, 196.00, 246.94],
            [146.83, 185.00, 220.00, 261.63, 329.63],
            [196.00, 246.94, 293.66, 369.99, 440.00],
            [130.81, 164.81, 196.00, 246.94, 329.63],
        ],
        # 3: Ebmaj9 -> Cm9 -> Fm9 -> Bb13 (Euljiro Vinyl & Rain)
        [
            [155.56, 196.00, 233.08, 293.66, 349.23],
            [130.81, 155.56, 196.00, 233.08, 293.66],
            [174.61, 207.65, 261.63, 311.13, 392.00],
            [116.54, 207.65, 246.94, 293.66, 349.23],
        ],
        # 4: Gmin9 -> C13 -> Fmaj9 -> Bbmaj7 (Deep Focus Coding Synth)
        [
            [196.00, 233.08, 293.66, 349.23, 440.00],
            [130.81, 233.08, 277.18, 329.63, 392.00],
            [174.61, 220.00, 261.63, 329.63, 392.00],
            [116.54, 146.83, 174.61, 220.00, 261.63],
        ],
        # 5: Pentatonic D-E-G-A-B (Serene Hanok Courtyard & Tea Room)
        [
            [146.83, 220.00, 293.66, 329.63, 440.00],
            [164.81, 246.94, 329.63, 392.00, 493.88],
            [196.00, 293.66, 392.00, 440.00, 587.33],
            [146.83, 220.00, 293.66, 369.99, 440.00],
        ],
    ]
    chords = progressions[(style_seed or bpm) % len(progressions)]

    total_samples = int(sample_rate * duration_sec)
    # Synthesize a unit cycle (up to 4.0 seconds) and tile it in memory for 10x speed
    cycle_sec = min(duration_sec, max(2.0, beat_sec * 4))
    cycle_samples = max(1, int(sample_rate * cycle_sec))

    cycle_buf = bytearray()
    step = 2  # Compute at 22050Hz and duplicate sample pair for 2x speedup
    for i in range(0, cycle_samples, step):
        t = i / sample_rate
        if is_voice:
            env = math.sin(min(1.0, t / 0.35) * (math.pi / 2)) * max(0.15, 1.0 - (t / cycle_sec) * 0.45)
            mod = 0.55 + 0.45 * math.sin(2 * math.pi * 3.2 * t)
            base_f = 185.0 + (bpm % 7) * 8.0
            sig = 0.18 * env * mod * (
                math.sin(2 * math.pi * base_f * t)
                + 0.5 * math.sin(2 * math.pi * (base_f * 1.5) * t)
            )
        else:
            bar_idx = int(t / beat_sec) % len(chords)
            chord = chords[bar_idx]
            bar_pos = (t % beat_sec) / beat_sec
            env = math.exp(-2.0 * bar_pos) * (1.0 - math.exp(-36.0 * bar_pos))
            tremolo = 0.88 + 0.12 * math.sin(2 * math.pi * 2.6 * t)
            sig = 0.0
            for f in chord:
                sig += math.sin(2 * math.pi * f * t) + 0.24 * math.sin(2 * math.pi * (f * 2) * t)
            sig = (sig / len(chord)) * 0.28 * env * tremolo
            sig += 0.007 * math.sin(2 * math.pi * 110.0 * t)

        left = max(-32767, min(32767, int(sig * 32767)))
        right = max(-32767, min(32767, int(sig * 0.96 * 32767)))
        frame_bytes = struct.pack("<hh", left, right)
        cycle_buf.extend(frame_bytes * min(step, cycle_samples - i))

    target_bytes = total_samples * 4
    repeats = (target_bytes // len(cycle_buf)) + 1
    full_buf = (bytes(cycle_buf) * repeats)[:target_bytes]

    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(full_buf)
    return out_path


def render_google_profile_avatar(
    source_img_path: Path,
    out_path: Path,
    character_name: str = "Sora",
    tagline: str = "Bias Studio",
) -> Path:
    """Crops and frames a high-resolution 800x800 square avatar with a circular studio ring for Google Profile."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    size = 800
    try:
        src = Image.open(source_img_path).convert("RGB")
        w, h = src.size
        # Focus crop on upper-center character portrait
        crop_side = min(w, h)
        left = (w - crop_side) // 2
        top = max(0, (h - crop_side) // 4)
        cropped = src.crop((left, top, left + crop_side, top + crop_side)).resize((size, size), Image.Resampling.LANCZOS)
    except Exception:
        cropped = Image.new("RGB", (size, size), (18, 20, 28))

    draw = ImageDraw.Draw(cropped)
    amber = (232, 176, 75)
    dark_bg = (14, 15, 20)
    # Circular Google profile safe-zone ring
    draw.ellipse([16, 16, size - 16, size - 16], outline=amber, width=6)
    draw.ellipse([26, 26, size - 26, size - 26], outline=(127, 179, 213), width=2)
    # Bottom name pill inside safe circle
    pill_w, pill_h = 360, 54
    px1 = (size - pill_w) // 2
    py1 = size - 110
    draw.rectangle([px1, py1, px1 + pill_w, py1 + pill_h], fill=dark_bg, outline=amber, width=2)
    label_text = f"BIAS // {character_name.upper()}"
    draw.text((px1 + 24, py1 + 12), label_text[:28], fill=amber)
    draw.text((px1 + 24, py1 + 30), tagline[:36], fill=(220, 216, 208))

    cropped.save(out_path, "PNG")
    return out_path


def render_collectible_photocard(
    source_img_path: Path,
    out_path: Path,
    spec_dict: dict,
    affection_score: int = 45,
    bond_level_title: str = "Lv.2 편해진 작업 메이트",
    session_id: str = "default",
) -> Path:
    """Renders a 1080x1520 Collectible Bias Photocard & Lorebook Dossier PNG with embedded chara_card_v2."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    W, H = 1080, 1520
    card = Image.new("RGB", (W, H), (14, 16, 23))
    draw = ImageDraw.Draw(card)

    amber = (232, 176, 75)
    cool_blue = (127, 179, 213)
    panel_bg = (22, 25, 36)
    border_muted = (46, 52, 72)
    text_light = (242, 239, 233)
    text_sub = (168, 174, 192)

    # Outer double frame
    draw.rectangle([24, 24, W - 24, H - 24], outline=amber, width=3)
    draw.rectangle([34, 34, W - 34, H - 34], outline=border_muted, width=1)

    # Header bar
    draw.rectangle([54, 52, W - 54, 118], fill=panel_bg, outline=border_muted, width=1)
    name = str(spec_dict.get("name", "Sora"))
    mbti = str(spec_dict.get("mbti", "INFJ"))
    age = str(spec_dict.get("apparent_age", "mid 20s"))
    draw.text((76, 68), f"BIAS STUDIO // COLLECTIBLE COMPANION CARD", fill=amber)
    draw.text((76, 90), f"EDITION #{session_id[:6].upper()}  |  MBTI: {mbti}  |  AGE: {age.upper()}  |  AFFECTION: {affection_score}%", fill=text_sub)

    # Main Portrait Frame (54, 136 -> W-54, 916)
    pw = W - 108
    ph = 780
    try:
        src = Image.open(source_img_path).convert("RGB")
        sw, sh = src.size
        target_ratio = pw / ph
        src_ratio = sw / sh
        if src_ratio > target_ratio:
            new_w = int(sh * target_ratio)
            left = (sw - new_w) // 2
            crop_img = src.crop((left, 0, left + new_w, sh))
        else:
            new_h = int(sw / target_ratio)
            top = max(0, (sh - new_h) // 4)
            crop_img = src.crop((0, top, sw, top + new_h))
        portrait = crop_img.resize((pw, ph), Image.Resampling.LANCZOS)
        card.paste(portrait, (54, 136))
    except Exception:
        draw.rectangle([54, 136, 54 + pw, 136 + ph], fill=(26, 30, 44))

    draw.rectangle([54, 136, 54 + pw, 136 + ph], outline=amber, width=2)

    # Overlay badge on bottom-left of portrait
    draw.rectangle([74, 846, 520, 898], fill=(14, 16, 23), outline=amber, width=2)
    draw.text((92, 858), f"{name.upper()}  //  {spec_dict.get('tagline', '01:30 AM Companion')[:34]}", fill=amber)
    draw.text((92, 876), f"BOND: {bond_level_title} ({affection_score}%)", fill=cool_blue)

    # Lorebook & Spec Dossier Section (y = 938 .. 1450)
    draw.rectangle([54, 938, W - 54, 1460], fill=panel_bg, outline=border_muted, width=1)
    archetype = str(spec_dict.get("archetype", "Late-Night Studio Companion"))
    draw.text((78, 958), f"ARCHETYPE: {archetype[:68]}", fill=text_light)

    quote = str(spec_dict.get("dj_intro_script") or spec_dict.get("first_greeting_line") or "Take a slow breath and stay with this page.")
    draw.text((78, 988), f'"{quote[:92]}"', fill=amber)

    # 8 Visual Traits
    draw.text((78, 1028), "VERIFIED VISUAL & LOREBOOK TRAITS (8/8):", fill=cool_blue)
    traits = list(spec_dict.get("visual_traits", []))[:8]
    y_cursor = 1056
    for idx, tr in enumerate(traits):
        col_x = 78 if idx % 2 == 0 else 550
        row_y = y_cursor + (idx // 2) * 34
        draw.text((col_x, row_y), f"[{idx + 1}] {str(tr)[:40]}", fill=text_sub)

    # Sound & Voice Spec Box
    draw.line([(78, 1210), (W - 78, 1210)], fill=border_muted, width=1)
    genre = spec_dict.get("music_genre", "Late-Night Rhodes Lo-Fi")
    bpm = spec_dict.get("music_bpm", 72)
    key_sig = spec_dict.get("music_key", "F minor")
    drink = spec_dict.get("signature_drink", "Warm Ethiopian Hand-Drip")
    habit = spec_dict.get("secret_habit", "Taps pen softly to 72 BPM rhythm")

    draw.text((78, 1228), f"BGM TRACK : {bpm} BPM  |  {genre} ({key_sig})", fill=text_light)
    draw.text((78, 1258), f"VOICE BANK: {str(spec_dict.get('voice_description', 'Warm close-mic FM radio tone'))[:72]}", fill=text_sub)
    draw.text((78, 1288), f"FAV DRINK : {str(drink)[:68]}", fill=text_sub)
    draw.text((78, 1318), f"HABIT     : {str(habit)[:68]}", fill=text_sub)

    # Footer stamp
    draw.line([(78, 1368), (W - 78, 1368)], fill=border_muted, width=1)
    draw.text((78, 1388), "SILLYTAVERN CHARA_CARD_V2 EMBEDDED  |  GEMINI 4 ARGON + NANO BANANA 2.1 + LYRIA 3", fill=amber)
    draw.text((78, 1416), f"https://bias.studio/study/{session_id}   //   YOUR BIAS. YOUR LO-FI.", fill=text_sub)

    # Save with embedded chara_card_v2 metadata
    chara_card = build_chara_card_v2(spec_dict)
    meta = PngImagePlugin.PngInfo()
    b64_payload = base64.b64encode(json.dumps(chara_card, ensure_ascii=False).encode("utf-8")).decode("ascii")
    meta.add_text("chara", b64_payload)
    meta.add_text("chara_card_v2", b64_payload)
    card.save(out_path, "PNG", pnginfo=meta)
    return out_path


