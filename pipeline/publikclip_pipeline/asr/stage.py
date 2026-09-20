"""ASR + forced alignment via whisperX (BSD-2-Clause, pinned 3.8.6).

Word-level timestamps are the substrate for everything downstream: captions,
[laughs] tag placement, prosodic emphasis, long-pause detection, ducking,
and sentence-snapped candidate boundaries.

Model choice: large-v3-turbo int8 by default — near-parity accuracy with
large-v3 at a fraction of the compute, which is what makes local-first
viable on Apple Silicon. Silero VAD (MIT) instead of whisperX's bundled
pyannote VAD checkpoint, whose license the research flagged as unresolved.

The stage records wall-clock + realtime factor into its checkpoint — the M1
gate's Apple Silicon benchmark comes from real runs, not synthetic tests.
"""

from __future__ import annotations

import gc
import os
import sys
import re
import time
from pathlib import Path

from .. import config
from ..jobs.queue import Stage, StageContext, StageError

ASR_MODEL = "large-v3-turbo"
COMPUTE_TYPE = "int8"
BATCH_SIZE = 8


def _point_caches_at_home() -> None:
    """All model caches live under PUBLIKCLIP_HOME so 'delete the app data
    dir' is a complete uninstall."""
    hf_home = config.models_dir() / "hf"
    hf_home.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(hf_home))
    os.environ.setdefault("TORCH_HOME", str(config.models_dir() / "torch"))


class _ProgressStdWrapper:
    def __init__(self, original_stream, ctx):
        self.original_stream = original_stream
        self.ctx = ctx
        self.last_pct = -1
        self._emitting = False

    def write(self, s):
        self.original_stream.write(s)
        if self._emitting:
            return
        match = re.search(r'(\d+(?:\.\d+)?)%', s)
        if match:
            pct = int(float(match.group(1)))
            if pct != self.last_pct:
                self.last_pct = pct
                self._emitting = True
                try:
                    self.ctx.emit(pct / 100.0, f"Transcribing ({pct}%)…")
                finally:
                    self._emitting = False

    def flush(self):
        self.original_stream.flush()


class AsrStage(Stage):
    name = "asr"
    schema_version = 1

    def run(self, ctx: StageContext) -> dict:
        ingest = ctx.prior.get("ingest") if ctx.prior else None
        if not ingest:
            raise StageError("ASR needs the ingest stage output.")
            
        audio_str = ingest.get("audio_path", "").replace("\\", "/")
        audio_path = Path(audio_str)
        if not audio_path.exists():
            audio_path = ctx.job_dir / Path(audio_str).name

        if not audio_path.exists():
            raise StageError("Analysis audio missing — re-run ingest.")

        _point_caches_at_home()
        ctx.emit(-1, "Loading speech model (downloads ~1.6 GB on first run)…")
        import torch  # deferred: heavy import
        import whisperx

        device = "cpu"  # ctranslate2 has no MPS backend; int8 CPU is the local path
        compute_type = COMPUTE_TYPE
        if torch.cuda.is_available():
            device = "cuda"
            compute_type = "float16"

        t0 = time.monotonic()
        asr_model_name = getattr(ctx.settings, "asr_model", ASR_MODEL)
        model = whisperx.load_model(
            asr_model_name, device, compute_type=compute_type, vad_method="silero", language="en"
        )
        audio = whisperx.load_audio(str(audio_path))
        duration = float(len(audio)) / 16000.0

        ctx.emit(-1, "Transcribing…")
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = _ProgressStdWrapper(original_stdout, ctx)
        sys.stderr = _ProgressStdWrapper(original_stderr, ctx)
        try:
            result = model.transcribe(audio, batch_size=BATCH_SIZE, language="en", print_progress=True)
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            
        language = result.get("language", "en")
        transcribe_secs = time.monotonic() - t0

        # Free ASR weights before loading the alignment model — peak RSS on a
        # 24 GB machine matters more than reload cost.
        del model
        gc.collect()

        ctx.emit(-1, "Aligning words…")
        t1 = time.monotonic()
        align_model, align_meta = whisperx.load_align_model(language_code=language, device=device)
        aligned = whisperx.align(
            result["segments"], align_model, align_meta, audio, device,
            return_char_alignments=False,
        )
        align_secs = time.monotonic() - t1
        del align_model
        gc.collect()
        if hasattr(torch, "mps") and torch.backends.mps.is_available():
            torch.mps.empty_cache()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        segments = []
        for seg in aligned["segments"]:
            words = [
                {
                    "word": w.get("word", "").strip(),
                    "start": round(float(w["start"]), 3),
                    "end": round(float(w["end"]), 3),
                    "score": round(float(w.get("score", 0.0)), 3),
                }
                for w in seg.get("words", [])
                if "start" in w and "end" in w
            ]
            segments.append(
                {
                    "start": round(float(seg["start"]), 3),
                    "end": round(float(seg["end"]), 3),
                    "text": seg.get("text", "").strip(),
                    "words": words,
                }
            )

        word_count = sum(len(s["words"]) for s in segments)
        if word_count == 0:
            raise StageError(
                "No speech was found in this video. publikclip needs dialogue to find moments."
            )

        total = transcribe_secs + align_secs
        return {
            "language": language,
            "model": asr_model_name,
            "compute_type": compute_type,
            "device": device,
            "segments": segments,
            "word_count": word_count,
            "benchmark": {
                "audio_sec": round(duration, 1),
                "transcribe_sec": round(transcribe_secs, 1),
                "align_sec": round(align_secs, 1),
                "realtime_factor": round(duration / total, 2) if total > 0 else None,
            },
        }
