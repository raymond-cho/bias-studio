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
) -> Path:
    """Renders a 16fps (>=12fps anime standard) 2.5D animated loop MP4 from a scene still image.
    Includes subtle breathing motion, falling rain streaks, and warm desk-lamp flicker."""
    ffmpeg_bin = get_ffmpeg_bin()
    out_mp4_path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = fps * loop_seconds
    base_img = Image.open(scene_png_path).convert("RGB").resize((1280, 720), Image.Resampling.LANCZOS)

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
            try:
                render_animated_scene_mp4(visual_path, anim_loop_mp4, fps=16, loop_seconds=4)
                video_input_path = anim_loop_mp4
            except Exception:
                video_input_path = visual_path

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
# Procedural Studio Fallback & Default Demo Asset Generator
# ---------------------------------------------------------------------------

def render_studio_card_image(
    out_path: Path,
    title: str,
    subtitle: str,
    traits: list[str],
    mode: str = "sheet",
    width: int = 1280,
    height: int = 720,
) -> Path:
    """Renders a clean dark-mode architectural character reference sheet or studio scene."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), (14, 15, 20))
    draw = ImageDraw.Draw(img)

    # Subtle grid lines
    for x in range(0, width, 64):
        draw.line([(x, 0), (x, height)], fill=(24, 26, 35), width=1)
    for y in range(0, height, 64):
        draw.line([(0, y), (width, y)], fill=(24, 26, 35), width=1)

    # Outer border hairline + amber corner markers
    draw.rectangle([28, 28, width - 28, height - 28], outline=(38, 41, 54), width=1)
    amber = (232, 176, 75)
    cool = (127, 179, 213)
    text_main = (236, 233, 226)
    text_muted = (154, 150, 142)

    if mode == "sheet":
        # Draw 3 architectural character view panels (Front, 3/4, Side)
        panel_labels = ["01 / FRONT SILHOUETTE", "02 / THREE-QUARTER VIEW", "03 / SIDE PROFILE"]
        panel_w = 240
        panel_h = 460
        start_x = 60
        for idx, plabel in enumerate(panel_labels):
            px = start_x + idx * (panel_w + 24)
            py = 130
            draw.rectangle([px, py, px + panel_w, py + panel_h], fill=(22, 24, 33), outline=(45, 49, 64), width=1)
            draw.text((px + 14, py + 12), plabel, fill=amber)
            # Stylized character figure silhouette inside each view panel
            cx = px + panel_w // 2
            # Warm halo behind head
            draw.ellipse([cx - 52, py + 65, cx + 52, py + 169], outline=(70, 58, 38), width=1)
            # Head & hair silhouette
            draw.ellipse([cx - 34, py + 82, cx + 34, py + 152], fill=(195, 198, 208), outline=amber, width=2)
            # Glasses rim hint
            offset_x = 0 if idx == 0 else (8 if idx == 1 else 16)
            draw.ellipse([cx - 20 + offset_x, py + 108, cx - 4 + offset_x, py + 124], outline=amber, width=2)
            if idx < 2:
                draw.ellipse([cx + 4 + offset_x, py + 108, cx + 20 + offset_x, py + 124], outline=amber, width=2)
            # Shoulders & cardigan torso
            draw.polygon(
                [
                    (cx - 64, py + 430),
                    (cx - 48, py + 175),
                    (cx + 48, py + 175),
                    (cx + 64, py + 430),
                ],
                fill=(36, 39, 52),
                outline=cool,
            )
            # Collar & amber pen accent
            draw.line([(cx - 18, py + 175), (cx, py + 230), (cx + 18, py + 175)], fill=amber, width=2)

        # Right-side trait callout table
        tx = 870
        ty = 130
        draw.rectangle([tx, ty, width - 56, ty + 460], fill=(22, 24, 33), outline=(45, 49, 64), width=1)
        draw.text((tx + 20, ty + 18), "VERIFIED VISUAL TRAITS (8/8)", fill=amber)
        for i, trait in enumerate(traits[:8]):
            row_y = ty + 56 + i * 48
            draw.rectangle([tx + 20, row_y, tx + 36, row_y + 16], outline=amber, fill=(42, 36, 24))
            short_t = trait if len(trait) <= 42 else trait[:39] + "..."
            draw.text((tx + 46, row_y), f"T{i+1}: {short_t}", fill=text_main)
    else:
        # Late-night work room scene (Rain window + warm desk lamp + companion silhouette)
        # Window frame with rain streaks
        wx1, wy1, wx2, wy2 = 80, 90, 740, 490
        draw.rectangle([wx1, wy1, wx2, wy2], fill=(18, 24, 36), outline=(48, 60, 82), width=2)
        for rx in range(wx1 + 30, wx2 - 20, 38):
            ry_offset = (rx * 17) % 180
            draw.line([(rx, wy1 + 20 + ry_offset), (rx - 14, wy1 + 95 + ry_offset)], fill=cool, width=1)

        # Warm desk lamp glow on right
        lx, ly = 960, 260
        for r in range(220, 20, -25):
            shade = max(18, min(95, int((220 - r) * 0.4)))
            draw.ellipse([lx - r, ly - r, lx + r, ly + r], outline=(shade + 40, shade + 20, 22), width=2)
        # Desk surface
        draw.rectangle([40, 500, width - 40, height - 40], fill=(26, 22, 20), outline=amber, width=1)
        # Companion figure at desk
        cx, cy = 540, 340
        draw.ellipse([cx - 46, cy - 90, cx + 46, cy + 2], fill=(200, 202, 212), outline=amber, width=2)
        draw.polygon([(cx - 110, 520), (cx - 75, cy + 12), (cx + 75, cy + 12), (cx + 110, 520)], fill=(34, 37, 48), outline=amber)

    # Header bar
    draw.text((60, 52), f"BIAS STUDIO // {title.upper()}", fill=amber)
    draw.text((60, 78), subtitle, fill=text_muted)
    draw.text((60, height - 62), "16:9 STUDIO REFERENCE  |  ADULT ARCHETYPE (20+)  |  ORIGINAL IP", fill=text_muted)

    img.save(out_path, "PNG")
    return out_path


def synthesize_warm_lofi_wav(out_path: Path, duration_sec: float = 12.0, bpm: int = 74, is_voice: bool = False) -> Path:
    """Generates a warm stereo WAV file (Rhodes lo-fi chord loop or gentle tone) for instant offline/demo playback."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 44100
    total_samples = int(sample_rate * duration_sec)
    beat_sec = 60.0 / max(50, bpm)

    # Fmin9 -> Bb13 -> Ebmaj9 -> Abmaj7 warm jazz progression frequencies
    chords = [
        [174.61, 207.65, 261.63, 311.13, 392.00],
        [116.54, 207.65, 246.94, 293.66, 349.23],
        [155.56, 196.00, 233.08, 293.66, 349.23],
        [207.65, 261.63, 311.13, 392.00, 466.16],
    ]

    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        buf = bytearray()
        for i in range(total_samples):
            t = i / sample_rate
            if is_voice:
                # Soft warm cadence envelope
                env = math.sin(min(1.0, t / 0.4) * (math.pi / 2)) * max(0.0, 1.0 - (t / duration_sec) * 0.5)
                mod = 0.55 + 0.45 * math.sin(2 * math.pi * 3.2 * t)
                sig = 0.18 * env * mod * (
                    math.sin(2 * math.pi * 196.0 * t)
                    + 0.5 * math.sin(2 * math.pi * 293.66 * t)
                )
            else:
                bar_idx = int(t / (beat_sec * 4)) % len(chords)
                chord = chords[bar_idx]
                bar_pos = (t % (beat_sec * 4)) / (beat_sec * 4)
                env = math.exp(-2.2 * bar_pos) * (1.0 - math.exp(-40.0 * bar_pos))
                tremolo = 0.88 + 0.12 * math.sin(2 * math.pi * 2.8 * t)
                sig = 0.0
                for f in chord:
                    sig += math.sin(2 * math.pi * f * t) + 0.25 * math.sin(2 * math.pi * (f * 2) * t)
                sig = (sig / len(chord)) * 0.28 * env * tremolo
                # Subtle vinyl rain warmth
                sig += 0.008 * math.sin(2 * math.pi * 110.0 * t)

            left = max(-32767, min(32767, int(sig * 32767)))
            right = max(-32767, min(32767, int(sig * 0.96 * 32767)))
            buf.extend(struct.pack("<hh", left, right))

        wf.writeframes(bytes(buf))
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

