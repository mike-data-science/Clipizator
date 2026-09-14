import subprocess

import pytest

from publikclip_pipeline.render import ffmpeg_bin, preview, renderer


def test_preview_cache_invalidates_after_source_change(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"first render")
    initial = preview.preview_path(source)
    source.write_bytes(b"a different longer render")
    assert preview.preview_path(source) != initial


def test_existing_preview_reused_without_encoding(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"original")
    cached = preview.preview_path(source)
    cached.parent.mkdir()
    cached.write_bytes(b"complete preview")
    monkeypatch.setattr(renderer, "_run_ffmpeg", lambda *args, **kwargs: pytest.fail("must use cache"))
    assert preview.ensure_preview(source, 1) == cached
    assert source.read_bytes() == b"original"


def test_failed_preview_is_not_published(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"original")
    monkeypatch.setattr(renderer, "nvenc_available", lambda: False)
    def fail(*args, **kwargs):
        raise RuntimeError("encoder failed")
    monkeypatch.setattr(renderer, "_run_ffmpeg", fail)
    with pytest.raises(RuntimeError, match="encoder failed"):
        preview.ensure_preview(source, 1)
    assert list((tmp_path / ".previews").iterdir()) == []
    assert source.read_bytes() == b"original"


@pytest.mark.slow
def test_real_preview_is_seekable_and_preserves_original(tmp_path):
    source = tmp_path / "clip.mp4"
    subprocess.run([
        ffmpeg_bin.ffmpeg(), "-nostdin", "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(source),
    ], check=True, timeout=30)
    original = source.read_bytes()
    result = preview.ensure_preview(source, 2)
    check = renderer.verify_output(result, 2)
    assert check["ok"], check
    assert (check["width"], check["height"]) == (720, 1280)
    encoded = result.read_bytes()
    assert encoded.index(b"moov") < encoded.index(b"mdat")
    assert source.read_bytes() == original
    assert preview.ensure_preview(source, 2) == result
