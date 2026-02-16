"""
OCR module for Memex screen capture.

Uses Apple Vision framework on macOS (zero external dependencies).
Falls back to Tesseract on Linux/Windows.
"""

import logging
import platform
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image

logger = logging.getLogger(__name__)

# Track which OCR backend is active
_ocr_backend: Optional[str] = None


def _try_apple_vision() -> bool:
    """Check if Apple Vision framework is available (macOS only)."""
    if platform.system() != "Darwin":
        return False
    try:
        import objc  # noqa: F401
        from Vision import VNRecognizeTextRequest  # noqa: F401
        return True
    except ImportError:
        return False


def _try_tesseract() -> bool:
    """Check if Tesseract is available."""
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _ocr_apple_vision(image: Image.Image) -> str:
    """Extract text using Apple Vision framework (macOS)."""
    import objc
    from Foundation import NSURL
    from Vision import (
        VNRecognizeTextRequest,
        VNImageRequestHandler,
    )

    # Vision framework needs a file path — write temp PNG
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
        image.save(tmp_path, format="PNG")

    try:
        image_url = NSURL.fileURLWithPath_(tmp_path)
        handler = VNImageRequestHandler.alloc().initWithURL_options_(
            image_url, None
        )

        request = VNRecognizeTextRequest.alloc().init()
        # 1 = accurate, 0 = fast
        request.setRecognitionLevel_(1)
        request.setUsesLanguageCorrection_(True)

        success, error = handler.performRequests_error_([request], None)
        if not success or error:
            err_msg = str(error) if error else "unknown error"
            logger.warning(f"Apple Vision OCR failed: {err_msg}")
            return ""

        results = request.results()
        if not results:
            return ""

        lines = []
        for observation in results:
            candidates = observation.topCandidates_(1)
            if candidates and len(candidates) > 0:
                lines.append(candidates[0].string())

        return "\n".join(lines)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _ocr_tesseract(image: Image.Image) -> str:
    """Extract text using Tesseract OCR."""
    import pytesseract

    if image.mode != "RGB":
        image = image.convert("RGB")

    text = pytesseract.image_to_string(image, lang="eng")
    return text.strip()


def detect_backend() -> str:
    """Detect and return the best available OCR backend.

    Returns 'apple_vision', 'tesseract', or raises RuntimeError.
    """
    global _ocr_backend

    if _ocr_backend is not None:
        return _ocr_backend

    if _try_apple_vision():
        _ocr_backend = "apple_vision"
        logger.info("OCR backend: Apple Vision (native macOS — no Tesseract needed)")
        return _ocr_backend

    if _try_tesseract():
        _ocr_backend = "tesseract"
        logger.info("OCR backend: Tesseract")
        return _ocr_backend

    raise RuntimeError(
        "No OCR backend available. "
        "On macOS: install pyobjc-framework-Vision (pip install pyobjc-framework-Vision). "
        "On Linux/Windows: install Tesseract (brew install tesseract / apt install tesseract-ocr)."
    )


def extract_text(image: Image.Image) -> str:
    """Extract text from a PIL Image using the best available OCR backend.

    On macOS: uses Apple Vision framework (built-in, high quality, no external deps).
    On Linux/Windows: uses Tesseract OCR.
    """
    backend = detect_backend()

    if backend == "apple_vision":
        return _ocr_apple_vision(image)
    elif backend == "tesseract":
        return _ocr_tesseract(image)
    else:
        raise RuntimeError(f"Unknown OCR backend: {backend}")


def get_backend_info() -> dict:
    """Return info about the active OCR backend for diagnostics."""
    try:
        backend = detect_backend()
    except RuntimeError:
        backend = "none"

    info = {"backend": backend, "platform": platform.system()}

    if backend == "apple_vision":
        info["description"] = "Apple Vision (native macOS)"
        info["requires_install"] = False
    elif backend == "tesseract":
        import pytesseract
        info["description"] = f"Tesseract {pytesseract.get_tesseract_version()}"
        info["requires_install"] = True
    else:
        info["description"] = "No OCR backend available"
        info["requires_install"] = True

    return info
