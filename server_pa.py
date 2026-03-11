#!/usr/bin/env python3
"""
Zeabur-ready FastAPI backend for Edit Banana.

- POST /convert : upload image/pdf and return remote downloadable URLs
- GET  /api/files : secure file download from output directory
"""

import os
import sys
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import uvicorn

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

DEFAULT_ALLOWED_ROOT = "/app/output"


def _resolve_output_root() -> str:
    env_root = os.getenv("EDIT_BANANA_ALLOWED_ROOT", "").strip()
    candidate = env_root or DEFAULT_ALLOWED_ROOT
    return os.path.realpath(candidate)


def _ensure_in_allowed_root(raw_path: str) -> str:
    real = os.path.realpath(raw_path)
    root = _resolve_output_root()
    if not real.startswith(root):
        raise HTTPException(403, "forbidden path")
    return real


def _build_public_url(file_path: str) -> str | None:
    base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/api/files?path={quote(file_path)}"


def _derive_editable_files(result_path: str) -> tuple[str | None, str | None]:
    dirname = os.path.dirname(result_path)
    basename = os.path.basename(result_path)
    stem = os.path.splitext(basename)[0]
    candidates = [
        os.path.join(dirname, f"{stem}.drawio"),
        os.path.join(dirname, f"{stem}.xml"),
        os.path.join(dirname, f"{stem}.pptx"),
    ]
    existing = [p for p in candidates if os.path.exists(p)]
    drawio = next((p for p in existing if p.endswith(".drawio") or p.endswith(".xml")), None)
    pptx = next((p for p in existing if p.endswith(".pptx")), None)
    return drawio, pptx


_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
}


def _guess_media_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return _MEDIA_TYPES.get(ext, "application/octet-stream")


app = FastAPI(
    title="Edit Banana API",
    description="Universal Content Re-Editor — image/PDF to editable DrawIO or PPTX",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"service": "Edit Banana", "docs": "/docs"}


@app.get("/api/files")
def get_output_file(path: str = Query(..., description="Absolute path of generated output file")):
    safe = _ensure_in_allowed_root(path)
    if not os.path.exists(safe):
        raise HTTPException(404, "file not found")
    filename = os.path.basename(safe)
    return FileResponse(safe, filename=filename)


@app.get("/api/preview/{image_name}")
def get_preview_image(image_name: str):
    """Serve the preview image for a processed result by image stem name.

    This provides a stable, predictable URL for frontend image previews
    without requiring the client to know the absolute file path.
    """
    root = _resolve_output_root()
    # Search for preview file in the output subdirectory
    img_dir = os.path.join(root, image_name)
    if not os.path.isdir(img_dir):
        raise HTTPException(404, "image not found")

    # Look for preview files (saved during /convert)
    for candidate in ("preview.png", "preview.jpg", "preview.jpeg",
                       "preview.webp", "preview.bmp", "preview.tiff"):
        preview_path = os.path.join(img_dir, candidate)
        if os.path.exists(preview_path):
            safe = _ensure_in_allowed_root(preview_path)
            return FileResponse(safe, media_type=_guess_media_type(candidate))

    # Fallback: serve sam3 visualization
    sam3_path = os.path.join(img_dir, "sam3_extraction.png")
    if os.path.exists(sam3_path):
        safe = _ensure_in_allowed_root(sam3_path)
        return FileResponse(safe, media_type="image/png")

    raise HTTPException(404, "preview not found")


@app.post("/convert")
async def convert(file: UploadFile = File(...)):
    """Upload image/pdf and return editable output URLs."""
    name = file.filename or ""
    ext = Path(name).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".pdf", ".bmp", ".tiff", ".webp"}:
        raise HTTPException(400, "Unsupported format. Use image or PDF.")

    config_path = os.path.join(PROJECT_ROOT, "config", "config.yaml")
    if not os.path.exists(config_path):
        raise HTTPException(503, "Server not configured (missing config/config.yaml)")

    try:
        from main import Pipeline, load_config
        import shutil
        import tempfile

        config = load_config()
        output_dir = config.get("paths", {}).get("output_dir", DEFAULT_ALLOWED_ROOT)
        os.makedirs(output_dir, exist_ok=True)

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        try:
            pipeline = Pipeline(config)

            # Save original uploaded image to output dir for preview
            img_stem = Path(name).stem
            img_output_dir = os.path.join(output_dir, img_stem)
            os.makedirs(img_output_dir, exist_ok=True)
            preview_path = os.path.join(img_output_dir, f"preview{ext}")
            shutil.copy2(tmp_path, preview_path)

            result_path = pipeline.process_image(
                tmp_path,
                output_dir=output_dir,
                with_refinement=False,
                with_text=True,
            )
            if not result_path or not os.path.exists(result_path):
                raise HTTPException(500, "Conversion failed")

            safe_output_path = _ensure_in_allowed_root(result_path)
            drawio_file, pptx_file = _derive_editable_files(safe_output_path)

            drawio_url = _build_public_url(drawio_file) if drawio_file else None
            pptx_url = _build_public_url(pptx_file) if pptx_file else None

            # Build preview image URL (original image saved in output dir)
            preview_url = _build_public_url(preview_path) if os.path.exists(preview_path) else None

            # Also check for sam3 visualization as a fallback
            sam3_vis_path = os.path.join(img_output_dir, "sam3_extraction.png")
            sam3_vis_url = _build_public_url(sam3_vis_path) if os.path.exists(sam3_vis_path) else None

            return {
                "success": True,
                "output_path": safe_output_path,
                "preview_url": preview_url,
                "sam3_visualization_url": sam3_vis_url,
                "editable": {
                    "drawio_url": drawio_url,
                    "xml_url": drawio_url,
                    "pptx_url": pptx_url,
                },
            }
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


def main():
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
