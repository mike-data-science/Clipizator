"""Human review feedback should affect only matching campaign moments."""

from publikclip_pipeline.campaigns import learning


def test_feedback_adjustment_matches_video_and_overlap(monkeypatch):
    monkeypatch.setattr(
        learning.store,
        "campaign_feedback",
        lambda campaign_id: [
            {"video_url": "video-a", "start_sec": 10, "end_sec": 20, "label": "approved"},
            {"video_url": "video-a", "start_sec": 40, "end_sec": 50, "label": "rejected"},
        ],
    )

    assert learning.feedback_adjustment(
        "campaign", {"video_url": "video-a", "start_sec": 12, "end_sec": 18}
    ) == 1.0
    assert learning.feedback_adjustment(
        "campaign", {"video_url": "video-a", "start_sec": 42, "end_sec": 48}
    ) == -1.0
    assert learning.feedback_adjustment(
        "campaign", {"video_url": "video-b", "start_sec": 12, "end_sec": 18}
    ) == 0.0


def test_latest_feedback_replaces_older_decision():
    rows = [
        {"job_id": "job", "clip_index": 2, "label": "approved", "created_at": 1},
        {"job_id": "job", "clip_index": 2, "label": "rejected", "created_at": 2},
    ]

    latest = learning._latest_feedback(rows)

    assert len(latest) == 1
    assert latest[0]["label"] == "rejected"


def test_feedback_summary_counts_latest_decisions(monkeypatch):
    monkeypatch.setattr(
        learning.store,
        "campaign_feedback",
        lambda campaign_id: [
            {"job_id": "job", "clip_index": 1, "label": "approved", "created_at": 1},
            {"job_id": "job", "clip_index": 1, "label": "rejected", "created_at": 2},
            {"job_id": "job", "clip_index": 2, "label": "approved", "created_at": 3},
        ],
    )

    assert learning.feedback_summary("campaign") == {
        "total": 2, "approvals": 1, "rejections": 1, "net": 0,
    }