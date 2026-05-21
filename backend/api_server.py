from __future__ import annotations

import asyncio
import json
import shutil
import sys
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analyzers.judo_analyzer import REPORTS_DIR, VIDEO_EXT, VIDEO_OUT_DIR, analyze


UPLOADS_DIR = ROOT / "videos" / "uploads"

app = FastAPI(title="JudoIQ Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8080",
        "http://localhost:8080",
        "http://127.0.0.1:8081",
        "http://localhost:8081",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VIDEO_OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/videos", StaticFiles(directory=str(VIDEO_OUT_DIR)), name="videos")
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/analyze")
async def analyze_video(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VIDEO_EXT:
        raise HTTPException(status_code=400, detail="Unsupported video format")

    safe_stem = Path(file.filename or "clip").stem.replace(" ", "_")
    upload_path = UPLOADS_DIR / f"{safe_stem}_{uuid.uuid4().hex[:8]}{suffix}"

    with upload_path.open("wb") as output:
        shutil.copyfileobj(file.file, output)

    try:
        result = analyze(upload_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    annotated_name = Path(result["annotatedVideoPath"]).name
    report_name = Path(result["reportPath"]).name

    result["annotatedVideoUrl"] = f"/videos/{annotated_name}"
    result["reportUrl"] = f"/reports/{report_name}"
    return result


def _enrich_result(result: dict) -> dict:
    annotated_name = Path(result["annotatedVideoPath"]).name
    report_name = Path(result["reportPath"]).name
    result["annotatedVideoUrl"] = f"/videos/{annotated_name}"
    result["reportUrl"] = f"/reports/{report_name}"
    return result


@app.post("/analyze/stream")
async def analyze_video_stream(file: UploadFile = File(...)) -> StreamingResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VIDEO_EXT:
        raise HTTPException(status_code=400, detail="Unsupported video format")

    safe_stem = Path(file.filename or "clip").stem.replace(" ", "_")
    upload_path = UPLOADS_DIR / f"{safe_stem}_{uuid.uuid4().hex[:8]}{suffix}"

    with upload_path.open("wb") as output:
        shutil.copyfileobj(file.file, output)

    async def event_stream():
        queue: asyncio.Queue[dict] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_progress(payload: dict) -> None:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "progress", **payload},
            )

        def worker() -> None:
            try:
                result = analyze(upload_path, on_progress=on_progress)
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "result", "data": _enrich_result(result)},
                )
            except Exception as exc:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "error", "message": str(exc)},
                )

        threading.Thread(target=worker, daemon=True).start()
        yield json.dumps({"type": "progress", "phase": "upload", "percent": 1.0}) + "\n"

        while True:
            item = await queue.get()
            yield json.dumps(item, default=str) + "\n"
            if item.get("type") in {"result", "error"}:
                break

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
