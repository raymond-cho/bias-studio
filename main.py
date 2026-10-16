import mimetypes
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import (
    ALL_MODELS,
    BASE_DIR,
    GCP_PROJECT_ID,
    GCS_BUCKET_NAME,
    VIDEO_JOB_TIMEOUT_SECONDS,
    get_api_key,
)
from orchestrator import BiasStudioOrchestrator
from schemas import (
    AnswerSubmission,
    ChatSubmission,
    MarketplaceCommentSubmission,
    MarketplacePublishSubmission,
    TransformSubmission,
    VocalStudioSubmission,
)

app = FastAPI(
    title="Bias Studio — Your bias. Your lo-fi.",
    version="1.2.0",
    description="Late-night focus companion studio built with Gemini 4 Argon and Interactions API.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def add_cache_control_headers(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or "/asset/" in path:
        response.headers.setdefault("Cache-Control", "public, max-age=86400")
    return response


orchestrator = BiasStudioOrchestrator()


def _health_payload() -> dict:
    return {
        "status": "ok",
        "service": "bias-studio",
        "api_key_configured": bool(get_api_key()),
        "gcp_project": GCP_PROJECT_ID or "local",
        "gcs_bucket": GCS_BUCKET_NAME or None,
        "video_timeout_seconds": VIDEO_JOB_TIMEOUT_SECONDS,
        "models": ALL_MODELS,
    }


@app.get("/healthz")
def healthz() -> dict:
    return _health_payload()


@app.get("/health")
def health() -> dict:
    return _health_payload()


@app.get("/api/health")
def api_health() -> dict:
    return _health_payload()


@app.get("/", response_class=HTMLResponse)
def root_page() -> HTMLResponse:
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Bias Studio</h1>")
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.get("/about", response_class=HTMLResponse)
def about_page() -> HTMLResponse:
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Bias Studio — Architecture</h1>")
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.get("/marketplace", response_class=HTMLResponse)
def marketplace_page() -> HTMLResponse:
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Bias Studio — Marketplace</h1>")
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.get("/demo/{session_id}", response_class=HTMLResponse)
def demo_page(session_id: str) -> HTMLResponse:
    index_file = STATIC_DIR / "index.html"
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.get("/study/{session_id}", response_class=HTMLResponse)
def study_page(session_id: str) -> HTMLResponse:
    index_file = STATIC_DIR / "index.html"
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.post("/api/session/start")
def start_session(
    max_turns: int = Query(default=6, ge=4, le=30),
    survey_mode: str = Query(default="quick"),
    lang: str = Query(default="en"),
) -> JSONResponse:
    state = orchestrator.create_session(max_turns=max_turns, survey_mode=survey_mode, lang=lang)
    return JSONResponse(state)


@app.get("/api/session/{session_id}")
def get_session(session_id: str) -> JSONResponse:
    try:
        state = orchestrator.load_session(session_id)
        return JSONResponse(state)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@app.post("/api/session/{session_id}/answer")
def submit_answer(session_id: str, payload: AnswerSubmission) -> JSONResponse:
    try:
        state = orchestrator.submit_answer(
            session_id=session_id,
            answer=payload.answer,
            free_text=payload.free_text,
        )
        return JSONResponse(state)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@app.post("/api/session/{session_id}/synthesize-spec")
def synthesize_spec_endpoint(session_id: str) -> JSONResponse:
    try:
        state = orchestrator.synthesize_spec(session_id)
        return JSONResponse(state)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@app.post("/api/session/{session_id}/verify-sheet")
def verify_sheet_endpoint(session_id: str) -> JSONResponse:
    try:
        state = orchestrator.run_sheet_loop(session_id)
        return JSONResponse(state)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@app.post("/api/session/{session_id}/verify-voice")
def verify_voice_endpoint(session_id: str) -> JSONResponse:
    try:
        state = orchestrator.run_voice_loop(session_id)
        return JSONResponse(state)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@app.post("/api/session/{session_id}/verify-music")
def verify_music_endpoint(session_id: str) -> JSONResponse:
    try:
        state = orchestrator.run_music_loop(session_id)
        return JSONResponse(state)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@app.post("/api/session/{session_id}/verify-video")
def verify_video_endpoint(session_id: str) -> JSONResponse:
    try:
        state = orchestrator.run_video_loop(session_id)
        return JSONResponse(state)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@app.post("/api/session/{session_id}/run-pipeline")
def run_pipeline_async(session_id: str, background_tasks: BackgroundTasks) -> JSONResponse:
    try:
        state = orchestrator.load_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    background_tasks.add_task(orchestrator.run_full_pipeline, session_id)
    state["status"] = "running_pipeline"
    state["current_stage"] = "Starting verified multimodal pipeline..."
    orchestrator.save_session(session_id, state)
    return JSONResponse(state)


@app.post("/api/session/{session_id}/chat")
def chat_with_character_endpoint(session_id: str, payload: ChatSubmission) -> JSONResponse:
    try:
        result = orchestrator.chat_with_character(
            session_id=session_id,
            message=payload.message,
            lang=payload.lang,
        )
        return JSONResponse(result)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@app.post("/api/session/{session_id}/transform")
def transform_character_endpoint(session_id: str, payload: TransformSubmission) -> JSONResponse:
    try:
        state = orchestrator.apply_live_transformation(
            session_id=session_id,
            action_type=payload.action_type,
            updated_prompt=payload.updated_prompt,
            updated_label=payload.updated_label,
            lang=payload.lang,
        )
        return JSONResponse(state)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@app.post("/api/session/{session_id}/vocal-studio")
def vocal_studio_endpoint(session_id: str, payload: VocalStudioSubmission) -> JSONResponse:
    try:
        result = orchestrator.run_vocal_studio(
            session_id=session_id,
            script=payload.script,
            style_hint=payload.style_hint,
            music_prompt=payload.music_prompt,
        )
        return JSONResponse(result)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@app.get("/api/session/{session_id}/google-avatar")
def export_google_avatar_endpoint(session_id: str) -> FileResponse:
    try:
        avatar_path = orchestrator.export_google_profile_avatar(session_id)
        char_name = "companion"
        try:
            st = orchestrator.load_session(session_id)
            if st.get("spec") and st["spec"].get("name"):
                char_name = st["spec"]["name"].lower().replace(" ", "_")
        except Exception:
            pass
        return FileResponse(
            path=str(avatar_path),
            media_type="image/png",
            headers={"Content-Disposition": f'attachment; filename="{char_name}_google_profile_avatar.png"'},
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@app.get("/api/marketplace")
def list_marketplace_endpoint() -> JSONResponse:
    items = orchestrator.get_marketplace_items()
    return JSONResponse({"items": items})


@app.post("/api/marketplace/publish")
def publish_marketplace_endpoint(payload: MarketplacePublishSubmission) -> JSONResponse:
    try:
        item = orchestrator.publish_to_marketplace(
            session_id=payload.session_id,
            creator_name=payload.creator_name,
            creator_email=payload.creator_email,
            minihompy_title=payload.minihompy_title,
            status_message=payload.status_message,
        )
        return JSONResponse(item)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{payload.session_id}' not found")


@app.post("/api/marketplace/{item_id}/comment")
def comment_marketplace_endpoint(item_id: str, payload: MarketplaceCommentSubmission) -> JSONResponse:
    item = orchestrator.add_marketplace_comment(
        item_id=item_id,
        author_name=payload.author_name,
        relation_label=payload.relation_label,
        message=payload.message,
    )
    return JSONResponse(item)


@app.get("/api/landmarks")
def list_korean_landmarks() -> JSONResponse:
    from anime_opensource_engine import KOREAN_LANDMARK_BACKGROUNDS
    return JSONResponse({"landmarks": KOREAN_LANDMARK_BACKGROUNDS})


@app.get("/api/opensource-anime")
def get_opensource_anime_reference() -> JSONResponse:
    from anime_opensource_engine import fetch_opensource_anime_character
    return JSONResponse(fetch_opensource_anime_character())


@app.get("/api/session/{session_id}/asset/{filename}")
def get_session_asset(session_id: str, filename: str, download: Optional[int] = 0) -> FileResponse:
    safe_name = Path(filename).name
    sdir = orchestrator.session_dir(session_id)
    fpath = sdir / safe_name
    if not fpath.exists() and session_id != "default":
        orchestrator._try_restore_from_gcs(session_id, sdir)

    # Support direct .webp requests or automatic max-800px WebP preview for non-download PNG requests
    if not download and safe_name in ("sheet.png", "scene.png", "option_a.png", "option_b.png", "sheet.webp", "scene.webp", "option_a.webp", "option_b.webp"):
        stem = Path(safe_name).stem
        png_path = sdir / f"{stem}.png"
        webp_path = sdir / f"{stem}.webp"
        if png_path.exists() and (not webp_path.exists() or png_path.stat().st_mtime > webp_path.stat().st_mtime):
            try:
                from PIL import Image
                with Image.open(png_path) as im:
                    im_rgb = im.convert("RGB")
                    if im_rgb.width > 800:
                        new_h = int(im_rgb.height * (800 / im_rgb.width))
                        im_rgb = im_rgb.resize((800, new_h), Image.Resampling.LANCZOS)
                    im_rgb.save(webp_path, "WEBP", quality=82, method=4)
            except Exception:
                pass
        if webp_path.exists():
            fpath = webp_path

    if not fpath.exists():
        raise HTTPException(status_code=404, detail=f"Asset '{safe_name}' not found")

    media_type, _ = mimetypes.guess_type(str(fpath))
    if fpath.suffix.lower() == ".webp":
        media_type = "image/webp"
    headers = {"Cache-Control": "public, max-age=86400"}
    if download:
        char_name = "companion"
        try:
            st = orchestrator.load_session(session_id)
            if st.get("spec") and st["spec"].get("name"):
                char_name = st["spec"]["name"].lower().replace(" ", "_")
        except Exception:
            pass
        if safe_name == "study.mp4":
            dl_name = f"study_with_{char_name}.mp4"
        elif safe_name == "character_kit.zip":
            dl_name = f"{char_name}_character_kit_v2.zip"
        else:
            dl_name = safe_name
        headers["Content-Disposition"] = f'attachment; filename="{dl_name}"'

    return FileResponse(
        path=str(fpath),
        media_type=media_type or "application/octet-stream",
        headers=headers,
    )

