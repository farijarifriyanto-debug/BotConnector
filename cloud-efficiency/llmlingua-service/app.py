from __future__ import annotations

import os
import threading
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="BotConnector Context Optimizer", version="0.1.0")

_MODEL = None
_MODEL_LOCK = threading.Lock()
_MODEL_NAME = os.getenv(
    "BOTCONNECTOR_LLMLINGUA_MODEL",
    "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
)
_DISABLED = os.getenv("BOTCONNECTOR_LLMLINGUA_DISABLED", "0").lower() in {"1", "true", "yes"}


class Segment(BaseModel):
    text: str = Field(max_length=200_000)
    compress: bool = True
    kind: Literal["history", "rag", "tool_output", "other"] = "other"


class CompressRequest(BaseModel):
    segments: list[Segment] = Field(min_length=1, max_length=64)
    rate: float = Field(default=0.5, ge=0.2, le=1.0)


def _compressor():
    global _MODEL
    if _DISABLED:
        return None
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            from llmlingua import PromptCompressor
            _MODEL = PromptCompressor(
                model_name=_MODEL_NAME,
                use_llmlingua2=True,
                device_map="cpu",
            )
    return _MODEL


@app.get("/health")
def health():
    return {"ok": True, "disabled": _DISABLED, "model": _MODEL_NAME, "loaded": _MODEL is not None}


@app.post("/v1/compress")
def compress(request: CompressRequest):
    original_chars = sum(len(segment.text) for segment in request.segments)
    if original_chars > 500_000:
        raise HTTPException(status_code=413, detail="combined input is too large")

    compressor = _compressor()
    output = []
    for segment in request.segments:
        text = segment.text
        did_compress = False
        if segment.compress and compressor is not None and text.strip():
            result = compressor.compress_prompt(text, rate=request.rate, force_tokens=["\n", "?"])
            candidate = result.get("compressed_prompt", text)
            if isinstance(candidate, str) and candidate:
                text = candidate
                did_compress = text != segment.text
            origin_tokens = result.get("origin_tokens")
            compressed_tokens = result.get("compressed_tokens")
        else:
            origin_tokens = None
            compressed_tokens = None
        output.append({
            "kind": segment.kind,
            "text": text,
            "compressed": did_compress,
            "original_chars": len(segment.text),
            "output_chars": len(text),
            "origin_tokens": origin_tokens,
            "compressed_tokens": compressed_tokens,
        })

    return {
        "model": _MODEL_NAME,
        "disabled": _DISABLED,
        "segments": output,
        "original_chars": original_chars,
        "output_chars": sum(item["output_chars"] for item in output),
    }
