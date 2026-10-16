import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Official Model IDs — NEVER silently substitute
MODEL_ARGON = "gemini-4-argon"
MODEL_FLASH_LITE_IMAGE = "gemini-3.1-flash-lite-image"
MODEL_NANO_BANANA = "gemini-nano-banana-2.1"
MODEL_FLASH = "gemini-3.8-flash"
MODEL_TTS = "gemini-3.8-flash-tts"
MODEL_TRANSCRIBE = "gemini-3.5-transcribe"
MODEL_LYRIA = "lyria-3-clip-preview"
MODEL_OMNI_VIDEO = "gemini-omni-1.1-flash"

ALL_MODELS = [
    MODEL_ARGON,
    MODEL_FLASH_LITE_IMAGE,
    MODEL_NANO_BANANA,
    MODEL_FLASH,
    MODEL_TTS,
    MODEL_TRANSCRIBE,
    MODEL_LYRIA,
    MODEL_OMNI_VIDEO,
]

# Timeouts & verification loop bounds (180s per PM specification)
VIDEO_JOB_TIMEOUT_SECONDS = int(os.getenv("VIDEO_JOB_TIMEOUT_SECONDS", "180"))
MAX_VERIFY_ROUNDS_SHEET = 3
MAX_VERIFY_ROUNDS_VOICE = 2
MAX_VERIFY_ROUNDS_MUSIC = 2
MAX_VERIFY_ROUNDS_VIDEO = 2

# Storage paths
TMP_ROOT = Path(os.getenv("BIAS_TMP_DIR", "/tmp/bias"))
TMP_ROOT.mkdir(parents=True, exist_ok=True)

GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "").strip()
GCS_BUCKET_NAME = os.getenv(
    "GCS_BUCKET_NAME",
    f"{GCP_PROJECT_ID}-bias-studio" if GCP_PROJECT_ID else "",
).strip()


def get_api_key() -> str:
    """Reloads .env if needed so key updates take effect without server restart."""
    load_dotenv(BASE_DIR / ".env", override=True)
    return (
        os.getenv("GEMINI_API_KEY", "").strip()
        or os.getenv("GOOGLE_API_KEY", "").strip()
    )


def load_prestudy_names() -> list[str]:
    names_file = BASE_DIR / "prestudy_names.txt"
    if not names_file.exists():
        return ["Hatsune Miku", "Lofi Girl", "Gawr Gura", "Mori Calliope", "Ironmouse", "Kizuna AI"]
    with open(names_file, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


PRESTUDY_NAMES = load_prestudy_names()

# Blocked real-person / existing-IP / unsafe patterns
BLOCKED_PATTERNS = [
    "hatsune miku",
    "lofi girl",
    "gawr gura",
    "mori calliope",
    "ironmouse",
    "kizuna ai",
    "usada pekora",
    "hoshimachi suisei",
    "seeu",
    "plave",
    "isegye idol",
    "go eunhyuk",
    "baek dohwa",
    "sung jinwoo",
    "cheongmyeong",
    "lloyd frontera",
    "kim dokja",
    "yoo joonghyuk",
    "taylor swift",
    "iu ",
    "karina",
    "jang wonyoung",
    "jungkook",
    "newjeans",
    "aespa",
    "blackpink",
    "bts",
    "cover of ",
    "nsfw",
    "nude",
    "explicit",
    "under 18",
    "child",
    "middle school",
    "high schooler in romantic",
]

# Deterministic TEST_SCRIPT used by automated verification and quick demo seeding
TEST_SCRIPT = [
    {
        "q_index": 1,
        "axis": "setting",
        "question": "When you sit down to focus late at night, what kind of room settles your mind?",
        "answer": "Quiet attic archive with rain on the skylight and a single warm brass desk lamp",
    },
    {
        "q_index": 2,
        "axis": "personality",
        "question": "How should your work companion keep you company while the clock runs?",
        "answer": "Calm late-night archivist who turns pages quietly and offers dry, warm encouragement",
    },
    {
        "q_index": 3,
        "axis": "visual",
        "question": "Which visual silhouette and palette feels right across the desk from you?",
        "answer": "Option A: Short silver-ash bob, round wire-rim glasses, oversized charcoal knit cardigan",
    },
    {
        "q_index": 4,
        "axis": "visual",
        "question": "What signature detail should anchor the character sheet?",
        "answer": "Amber fountain pen tucked behind one ear and a brass studio headphones resting on the collar",
    },
    {
        "q_index": 5,
        "axis": "voice",
        "question": "When your host speaks at the start of a 25-minute block, how should the voice sound?",
        "answer": "Low, unhurried contralto radio tone with soft page-turn cadence and close-mic warmth",
    },
    {
        "q_index": 6,
        "axis": "music",
        "question": "What instrumental soundscape should loop beneath your focus session?",
        "answer": "Late-night Rhodes electric piano lo-fi jazz at 74 BPM with brushed snare and upright bass",
    },
]
