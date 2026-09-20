import io
import sys

from publikclip_pipeline.asr.stage import _ProgressStdWrapper


def test_progress_wrapper_does_not_recurse_when_callback_prints(monkeypatch):
    output = io.StringIO()
    calls = []

    class PrintingContext:
        def emit(self, fraction, message):
            calls.append((fraction, message))
            print(f"nested progress: {message}")

    wrapper = _ProgressStdWrapper(output, PrintingContext())
    monkeypatch.setattr(sys, "stdout", wrapper)

    print("Progress: 12.5%")

    assert calls == [(0.12, "Transcribing (12%)…")]
    assert output.getvalue() == (
        "Progress: 12.5%"
        "nested progress: Transcribing (12%)…\n\n"
    )
