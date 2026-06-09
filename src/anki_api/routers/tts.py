"""Text-to-speech [blocker for reviewer parity].

Browsers cannot reproduce Anki's TTS voices, so `{{tts:}}` fields are unplayable
unless the server synthesizes them. Voices come from the backend's installed TTS
engines; synthesis renders a voice+text to an audio file we stream back.
"""

from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from ..collection_handle import CollectionHandle
from ..deps import get_handle

router = APIRouter(prefix="/media/tts", tags=["tts"])


class Synthesize(BaseModel):
    text: str
    voice_id: str
    speed: float = Field(default=1.0, gt=0)


def _voice_dict(voice) -> dict:
    return {f.name: getattr(voice, f.name) for f in voice.DESCRIPTOR.fields}


@router.get("/voices")
def list_voices(validate: bool = False, handle: CollectionHandle = Depends(get_handle)) -> list[dict]:
    with handle.locked() as col:
        return [_voice_dict(v) for v in col._backend.all_tts_voices(validate=validate)]


@router.post("/synthesize")
def synthesize(body: Synthesize, handle: CollectionHandle = Depends(get_handle)) -> FileResponse:
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="anki-tts-")
    os.close(fd)
    with handle.locked() as col:
        col._backend.write_tts_stream(
            path=path, voice_id=body.voice_id, speed=body.speed, text=body.text
        )
    return FileResponse(
        path,
        media_type="audio/wav",
        filename="tts.wav",
        background=BackgroundTask(os.unlink, path),
    )
