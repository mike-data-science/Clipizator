from publikclip_pipeline import creator_sources


def catalog(*entries):
    return {
        "channel_id": "UCstableCreator", "uploader_id": "CreatorHandle", "channel": "Creator Name",
        "channel_url": "https://www.youtube.com/@CreatorHandle", "channel_follower_count": 120000,
        "thumbnail": "https://example.test/avatar.jpg", "entries": list(entries),
    }


def video(video_id, views, uploaded="20240101"):
    return {"id": video_id, "title": f"Video {video_id}", "duration": 42, "view_count": views,
            "like_count": 10, "comment_count": 2, "upload_date": uploaded, "thumbnail": f"https://example.test/{video_id}.jpg"}


def fetch(raw):
    return lambda url, progress: raw


def tab_fetch(videos=None, shorts=None):
    def go(url, progress):
        if url.endswith("/videos"):
            if isinstance(videos, Exception):
                raise videos
            return videos if videos is not None else catalog()
        if isinstance(shorts, Exception):
            raise shorts
        return shorts if shorts is not None else catalog()
    return go


def test_normalizes_youtube_handles_and_channel_urls():
    assert creator_sources.normalize_youtube_creator("@Creator.Handle")["fetch_url"] == "https://www.youtube.com/@Creator.Handle/videos"
    assert creator_sources.normalize_youtube_creator("youtube.com/channel/UCabc_123")["canonical_channel_url"] == "https://www.youtube.com/channel/UCabc_123"
    assert creator_sources.normalize_youtube_creator("https://www.youtube.com/@Creator/videos")["handle"] == "Creator"


def test_rejects_individual_youtube_video_url():
    try:
        creator_sources.normalize_youtube_creator("https://youtube.com/watch?v=abc12345678")
    except creator_sources.CreatorSourceError:
        pass
    else:
        raise AssertionError("video URL was accepted as a creator")


def test_creator_refresh_dedupes_videos_and_preserves_first_seen(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path))
    initial = creator_sources.refresh_creator("@CreatorHandle", fetch(catalog(video("abc12345678", 100))))
    video_id = initial["videos"][0]["id"]
    first_seen = initial["videos"][0]["first_seen_at"]
    refreshed = creator_sources.refresh_creator("https://youtube.com/@CreatorHandle", fetch(catalog(video("abc12345678", 250))))
    assert refreshed["id"] == initial["id"]
    assert len(refreshed["videos"]) == 1
    assert refreshed["videos"][0]["id"] == video_id
    assert refreshed["videos"][0]["views"] == 250
    assert refreshed["videos"][0]["first_seen_at"] == first_seen


def test_relative_classification_uses_creator_catalog(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path))
    values = [20, 50, 100, 200, 800]
    detail = creator_sources.refresh_creator("@CreatorHandle", fetch(catalog(*(video(f"id{i:09d}", views) for i, views in enumerate(values)))))
    labels = {item["views"]: item["derived_performance_label"] for item in detail["videos"]}
    assert labels[800] == "strong"
    assert labels[20] == "weak"
    assert labels[100] == "average"


def test_manual_override_and_reference_flags_persist(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path))
    detail = creator_sources.refresh_creator("@CreatorHandle", fetch(catalog(video("abc12345678", 100))))
    video_id = detail["videos"][0]["id"]
    changed = creator_sources.set_manual_label(video_id, "strong")
    assert changed["performance_label"] == "strong"
    changed = creator_sources.set_references(video_id, reference=True, editing_reference=True)
    assert changed["is_reference"] is True
    assert changed["is_editing_reference"] is True
    persisted = creator_sources.creator_detail(detail["id"])["videos"][0]
    assert persisted["manual_performance_label"] == "strong"
    assert persisted["is_reference"] is True


def test_shorts_only_channel_imports_when_videos_tab_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path))
    detail = creator_sources.refresh_creator("@CreatorHandle", tab_fetch(
        videos=creator_sources.CreatorSourceError("This channel does not have a videos tab"),
        shorts=catalog(video("short000001", 100)),
    ))
    assert [item["external_video_id"] for item in detail["videos"]] == ["short000001"]
    assert detail["videos"][0]["tab_origin"] == "shorts"
    assert detail["videos"][0]["content_type"] == "short"


def test_videos_only_channel_imports_when_shorts_tab_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path))
    detail = creator_sources.refresh_creator("@CreatorHandle", tab_fetch(
        videos=catalog(video("video000001", 100)),
        shorts=creator_sources.CreatorSourceError("This channel does not have a shorts tab"),
    ))
    assert [item["external_video_id"] for item in detail["videos"]] == ["video000001"]
    assert detail["videos"][0]["tab_origin"] == "videos"
    assert detail["videos"][0]["content_type"] == "video"


def test_both_tabs_are_merged_and_duplicate_video_id_is_not_reinserted(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path))
    detail = creator_sources.refresh_creator("@CreatorHandle", tab_fetch(
        videos=catalog(video("shared00001", 100), video("video000001", 200)),
        shorts=catalog(video("shared00001", 100), video("short000001", 300)),
    ))
    by_external_id = {item["external_video_id"]: item for item in detail["videos"]}
    assert len(by_external_id) == 3
    assert by_external_id["shared00001"]["tab_origin"] == "videos,shorts"
    assert by_external_id["shared00001"]["content_type"] is None


def test_missing_tab_is_expected_only_when_another_tab_succeeds(monkeypatch, tmp_path):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path))
    detail = creator_sources.refresh_creator("@CreatorHandle", tab_fetch(
        videos=creator_sources.CreatorSourceError("This channel does not have a videos tab"),
        shorts=catalog(),
    ))
    assert detail["videos"] == []


def _selection_catalog(monkeypatch, tmp_path, groups: dict[str, int]):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path))
    entries = []
    labels = []
    index = 0
    for label, count in groups.items():
        for _ in range(count):
            entries.append(video(f"select{index:06d}", 10_000 - index * 100))
            labels.append(label)
            index += 1
    detail = creator_sources.refresh_creator("@CreatorHandle", fetch(catalog(*entries)))
    for item, label in zip(detail["videos"], labels, strict=True):
        creator_sources.set_manual_label(item["id"], label)
    return creator_sources.creator_detail(detail["id"])


def test_selection_persists_across_catalog_refresh(monkeypatch, tmp_path):
    detail = _selection_catalog(monkeypatch, tmp_path, {"strong": 1})
    video_id = detail["videos"][0]["id"]
    selected = creator_sources.set_selection(detail["id"], [video_id], True, "manual")
    assert selected["selection_summary"] == {"selected": 1, "strong": 0, "average": 0, "weak": 0, "manual_reference": 1}
    refreshed = creator_sources.refresh_creator("@CreatorHandle", fetch(catalog(video("select000000", 20_000))))
    persisted = refreshed["videos"][0]
    assert persisted["selected_for_analysis"] is True
    assert persisted["selected_at"] is not None
    assert persisted["selection_reason"] == "manual"


def test_clear_selection_removes_all_selection_state(monkeypatch, tmp_path):
    detail = _selection_catalog(monkeypatch, tmp_path, {"strong": 2})
    selected = creator_sources.set_selection(detail["id"], [item["id"] for item in detail["videos"]], True, "manual")
    cleared = creator_sources.clear_selection(selected["id"])
    assert cleared["selection_summary"]["selected"] == 0
    assert all(not item["selected_for_analysis"] and item["selected_at"] is None and item["selection_reason"] is None for item in cleared["videos"])


def test_auto_selects_requested_group_counts_without_duplicates(monkeypatch, tmp_path):
    detail = _selection_catalog(monkeypatch, tmp_path, {"strong": 6, "average": 4, "weak": 4, "unclassified": 1})
    selected = creator_sources.auto_select_sample(detail["id"])
    assert selected["selection_summary"] == {"selected": 11, "strong": 5, "average": 3, "weak": 3, "manual_reference": 0}
    selected_ids = [item["id"] for item in selected["videos"] if item["selected_for_analysis"]]
    assert len(selected_ids) == len(set(selected_ids)) == 11
    strong_views = sorted((item["views"] for item in selected["videos"] if item["selection_reason"] == "creator_relative_strong"), reverse=True)
    assert strong_views == [10_000, 9_900, 9_800, 9_700, 9_600]


def test_auto_select_uses_only_available_videos(monkeypatch, tmp_path):
    detail = _selection_catalog(monkeypatch, tmp_path, {"strong": 2, "average": 1, "weak": 0})
    selected = creator_sources.auto_select_sample(detail["id"])
    assert selected["selection_summary"] == {"selected": 3, "strong": 2, "average": 1, "weak": 0, "manual_reference": 0}


def test_manual_selection_is_separate_from_editing_reference(monkeypatch, tmp_path):
    detail = _selection_catalog(monkeypatch, tmp_path, {"weak": 1})
    video_id = detail["videos"][0]["id"]
    creator_sources.set_references(video_id, editing_reference=True)
    unselected = creator_sources.creator_detail(detail["id"])["videos"][0]
    assert unselected["is_editing_reference"] is True
    assert unselected["selected_for_analysis"] is False
    selected = creator_sources.set_selection(detail["id"], [video_id], True, "manual")
    item = selected["videos"][0]
    assert item["is_editing_reference"] is True
    assert item["selection_reason"] == "manual"
