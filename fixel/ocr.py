"""On-device text recognition with macOS Vision. Nothing leaves the Mac."""

from __future__ import annotations

import asyncio
from pathlib import Path


def recognize_text(path: Path) -> str:
    """All text Vision finds in the image, one line per observation. Empty on any failure:
    memory is a bonus, so unreadable screenshots must never block a question."""
    try:
        import Vision
        from Foundation import NSURL

        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(False)  # keep error messages and code verbatim
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(path)), None)
        ok, _error = handler.performRequests_error_([request], None)
        if not ok:
            return ""
        lines = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if candidates:
                lines.append(str(candidates[0].string()))
        return "\n".join(lines)
    except Exception:
        return ""


async def recognize_text_async(path: Path) -> str:
    return await asyncio.to_thread(recognize_text, path)
