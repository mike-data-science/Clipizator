from fastapi.testclient import TestClient

from backend import server


def test_creator_source_list_api_returns_normalized_records(monkeypatch):
    monkeypatch.setattr(server.creator_sources, "list_creators", lambda: [{
        "id": 7, "platform": "youtube", "external_creator_id": "UCstable", "handle": "creator",
        "display_name": "Creator", "canonical_channel_url": "https://www.youtube.com/@creator",
        "thumbnail_url": None, "subscriber_count": 12, "first_seen_at": 1.0,
        "last_refreshed_at": 2.0, "video_count": 3,
    }])
    response = TestClient(server.app).get("/api/analyzer/sources")
    assert response.status_code == 200
    assert response.json()[0]["external_creator_id"] == "UCstable"
    assert response.json()[0]["video_count"] == 3


def test_creator_reference_api_returns_updated_normalized_video(monkeypatch):
    monkeypatch.setattr(server.creator_sources, "set_references", lambda video_id, reference, editing_reference: {
        "id": video_id, "platform": "youtube", "performance_label": "weak",
        "is_reference": reference, "is_editing_reference": editing_reference,
    })
    response = TestClient(server.app).put("/api/analyzer/source-videos/19/references", json={"reference": True})
    assert response.status_code == 200
    assert response.json() == {"id": 19, "platform": "youtube", "performance_label": "weak", "is_reference": True, "is_editing_reference": None}


def test_creator_selection_api_returns_creator_detail(monkeypatch):
    expected = {"id": 7, "videos": [], "selection_summary": {"selected": 0, "strong": 0, "average": 0, "weak": 0, "manual_reference": 0}}
    monkeypatch.setattr(server.creator_sources, "set_selection", lambda creator_id, video_ids, selected, reason: expected)
    response = TestClient(server.app).put("/api/analyzer/sources/7/selection", json={"video_ids": [19], "selected": True, "reason": "manual"})
    assert response.status_code == 200
    assert response.json() == expected
