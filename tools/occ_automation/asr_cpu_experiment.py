#!/usr/bin/env python3
"""Optional CPU ASR experiment.

faster-whisper is imported only when a real operator-run experiment is requested.
It is not a bot runtime dependency and CI uses injected test doubles only.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
from importlib import metadata
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def transcribe(
    *,
    input_path: Path,
    output_path: Path,
    model_name: str = "small",
    language: str = "ru",
    word_timestamps: bool = False,
    model_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    audio = input_path.expanduser().resolve(strict=True)
    output = output_path.expanduser().absolute()
    if not audio.is_file():
        raise ValueError("INPUT_NOT_FILE")
    if output.exists() or output.is_symlink():
        raise ValueError("OUTPUT_ALREADY_EXISTS")
    before = file_digest(audio)
    if model_factory is None:
        from faster_whisper import WhisperModel

        model_factory = WhisperModel
    loaded = time.perf_counter()
    model = model_factory(
        model_name,
        device="cpu",
        compute_type="int8",
    )
    load_seconds = time.perf_counter() - loaded
    started = time.perf_counter()
    segments, info = model.transcribe(
        audio.as_posix(),
        language=None if language == "auto" else language,
        vad_filter=True,
        word_timestamps=word_timestamps,
    )
    rows = []
    for segment in segments:
        row = {
            "id": segment.id,
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
        }
        if word_timestamps:
            row["words"] = [
                {
                    "start": word.start,
                    "end": word.end,
                    "word": word.word,
                }
                for word in (segment.words or [])
            ]
        rows.append(row)
    elapsed = time.perf_counter() - started
    if file_digest(audio) != before:
        raise ValueError("INPUT_CHANGED_DURING_TRANSCRIPTION")
    duration = float(info.duration)
    package_version = (
        metadata.version("faster-whisper")
        if getattr(model_factory, "__module__", "").startswith("faster_whisper")
        else "injected-test-double"
    )
    receipt = {
        "schema_version": "asr.cpu-experiment.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "input_sha256": before,
        "model": model_name,
        "package_version": package_version,
        "device": "cpu",
        "compute_type": "int8",
        "language": info.language,
        "audio_duration_seconds": duration,
        "model_load_seconds": load_seconds,
        "transcribe_seconds": elapsed,
        "real_time_factor": elapsed / duration if duration else None,
        "speaker_diarization_performed": False,
        "quality_evaluated": False,
        "segments": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(
            receipt,
            stream,
            ensure_ascii=False,
            indent=2,
        )
        stream.write("\n")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default="ru")
    parser.add_argument("--word-timestamps", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = transcribe(
            input_path=args.input,
            output_path=args.output,
            model_name=args.model,
            language=args.language,
            word_timestamps=args.word_timestamps,
        )
        print(
            json.dumps(
                {
                    "state": "COMPLETE",
                    "segments": len(receipt["segments"]),
                    "output": str(args.output.absolute()),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "state": "BLOCKED",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
