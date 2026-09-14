import json
from types import SimpleNamespace

from backend.studio_jobs import list_rendered_jobs


def job(tmp_path, name, title="media", source="https://youtube.com/watch?v=abc"):
    directory = tmp_path / name
    directory.mkdir()
    return SimpleNamespace(id=name, dir=directory, title=title, source=source, source_type="url")


def checkpoint(item, stage, data):
    (item.dir / f"{stage}.json").write_text(json.dumps({"data": data}))


def rendered(item):
    clips = item.dir / "clips"
    clips.mkdir()
    clip = clips / "clip_00.mp4"
    clip.write_bytes(b"rendered clip fixture")
    checkpoint(item, "render", {"outputs": [{"path": str(clip)}]})


def test_only_sessions_with_finished_clips_are_listed(tmp_path):
    download = job(tmp_path, "01-download")
    checkpoint(download, "ingest", {"title": "Downloaded video"})
    transcript = job(tmp_path, "02-transcript")
    checkpoint(transcript, "asr", {"segments": []})
    done = job(tmp_path, "03-done", title="A finished video")
    rendered(done)
    result = list_rendered_jobs([download, transcript, done])
    assert [r["id"] for r in result] == [done.id]
    assert result[0]["clip_count"] == 1
    assert result[0]["rendered"] is True


def test_missing_empty_and_malformed_renders_are_hidden(tmp_path):
    items = [job(tmp_path, str(i)) for i in range(5)]
    checkpoint(items[0], "render", {"outputs": []})
    checkpoint(items[1], "render", {"outputs": [{"path": "/missing/clip.mp4"}]})
    (items[2].dir / "render.json").write_text("{unfinished")
    checkpoint(items[3], "render", ["invalid data"])
    checkpoint(items[4], "render", {"outputs": "invalid outputs"})
    assert list_rendered_jobs(items) == []


def test_url_fragments_use_local_ingest_title(tmp_path):
    item = job(tmp_path, "01", title="watch?v=abc")
    rendered(item)
    checkpoint(item, "ingest", {"title": "The actual podcast title"})
    assert list_rendered_jobs([item])[0]["title"] == "The actual podcast title"


def test_local_metadata_and_campaign_titles(tmp_path):
    item = job(tmp_path, "01")
    rendered(item)
    (item.dir / "media.info.json").write_text(json.dumps({"title": "Local metadata title"}))
    assert list_rendered_jobs([item])[0]["title"] == "Local metadata title"
    assert list_rendered_jobs([item], {item.id: "Campaign title"})[0]["title"] == "Campaign title"


def test_urls_without_metadata_never_become_watch_titles(tmp_path):
    item = job(tmp_path, "01", title="watch?v=abc")
    rendered(item)
    assert list_rendered_jobs([item])[0]["title"] == "Clipped video · 01"


def test_relocated_clips_and_newest_first(tmp_path):
    older, newer = job(tmp_path, "01"), job(tmp_path, "02")
    rendered(older)
    rendered(newer)
    checkpoint(newer, "render", {"outputs": [{"path": "C:\\old\\clips\\clip_00.mp4"}]})
    assert [r["id"] for r in list_rendered_jobs([older, newer])] == ["02", "01"]
