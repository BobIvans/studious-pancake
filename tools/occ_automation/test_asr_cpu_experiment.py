from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import asr_cpu_experiment as asr


class Segment:
    id = 1
    start = 0.0
    end = 1.0
    text = "hello"
    words = []


class FakeModel:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, path, **kwargs):
        return iter([Segment()]), SimpleNamespace(
            duration=1.0,
            language="en",
        )


class AsrTests(unittest.TestCase):
    def test_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audio = root / "a.wav"
            audio.write_bytes(b"audio")
            output = root / "r.json"
            output.write_text("existing")
            with self.assertRaisesRegex(
                ValueError,
                "OUTPUT_ALREADY_EXISTS",
            ):
                asr.transcribe(
                    input_path=audio,
                    output_path=output,
                    model_factory=FakeModel,
                )

    def test_detects_changed_input(self):
        class MutatingModel(FakeModel):
            def transcribe(self, path, **kwargs):
                Path(path).write_bytes(b"changed")
                return super().transcribe(path, **kwargs)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audio = root / "a.wav"
            audio.write_bytes(b"audio")
            with self.assertRaisesRegex(
                ValueError,
                "INPUT_CHANGED_DURING_TRANSCRIPTION",
            ):
                asr.transcribe(
                    input_path=audio,
                    output_path=root / "r.json",
                    model_factory=MutatingModel,
                )

    def test_injected_model_writes_bounded_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audio = root / "a.wav"
            audio.write_bytes(b"audio")
            output = root / "r.json"
            receipt = asr.transcribe(
                input_path=audio,
                output_path=output,
                model_factory=FakeModel,
            )
            self.assertTrue(output.is_file())
            self.assertFalse(receipt["quality_evaluated"])
            self.assertFalse(
                receipt["speaker_diarization_performed"]
            )


if __name__ == "__main__":
    unittest.main()
