import json

from publikclip_pipeline.source_analysis.story import build_story_semantics, semantic_windows


class SemanticClient:
    def __init__(self, malformed=False):
        self.calls = 0
        self.malformed = malformed

    def generate_json(self, prompt, schema):
        self.calls += 1
        if self.malformed:
            return {"wrong": []}
        evidence = json.loads(prompt.split("Evidence JSON: ", 1)[1])
        annotations = []
        for item in evidence:
            text = item["text"].lower()
            if "why" in text or "?" in text:
                role = "question"
            elif "because" in text:
                role = "explanation"
            elif "answer" in text or "revealed" in text:
                role = "payoff"
            elif "new topic" in text:
                role = "hook"
            else:
                role = "development"
            annotations.append({
                "input_index": item["input_index"], "summary": item["text"],
                "topic": "second idea" if "new topic" in text else "first idea",
                "primary_role": role, "secondary_roles": [],
                "relation_to_previous": "new_idea" if "new topic" in text else "continuation",
                "hook_types": ["question"] if role == "question" else [], "confidence": .84,
            })
        return {"annotations": annotations}


def _segment(start, end, text, speaker=0):
    return {"start": start, "end": end, "text": text, "speaker": speaker, "words": []}


def _build(segments, *, client=None, source_editing=None):
    return build_story_semantics(
        duration=max((item["end"] for item in segments), default=0), transcript_segments=segments,
        source_editing=source_editing or {}, visual_units=[], caption_tracks=[],
        emphasis_events=[], title_hooks=[], audio_events=[], llm_client=client,
    )


def test_semantic_unit_schema_and_ids_are_stable_when_unrelated_input_is_added():
    segment = _segment(2, 4, "Why does this happen?", speaker=3)
    first = _build([segment], client=SemanticClient())
    second = _build([_segment(0, 1, "Earlier intro."), segment], client=SemanticClient())
    left = first["semantic_units"][0]
    right = second["semantic_units"][1]
    assert left["semantic_unit_id"] == right["semantic_unit_id"]
    assert left["semantic_unit_id"].startswith("semantic_unit_000002000_")
    assert left["speaker_ids"] == ["speaker-3"]
    assert left["source"] == "llm"
    assert left["status"] == "interpreted"
    assert left["primary_story_role"] == "question"


def test_story_id_does_not_depend_on_mutable_summary_wording():
    class TopicClient(SemanticClient):
        def __init__(self, topic):
            super().__init__()
            self.topic = topic

        def generate_json(self, prompt, schema):
            payload = super().generate_json(prompt, schema)
            for annotation in payload["annotations"]:
                annotation["topic"] = self.topic
                annotation["summary"] = f"Summary for {self.topic}"
            return payload

    segments = [_segment(0, 1, "Why now?"), _segment(1.1, 2, "Because timing matters.")]
    first = _build(segments, client=TopicClient("timing"))
    second = _build(segments, client=TopicClient("schedule"))
    assert first["story_segments"][0]["story_id"] == second["story_segments"][0]["story_id"]


def test_story_boundary_closure_next_topic_and_payoff_linkage():
    result = _build([
        _segment(0, 2, "Why does the system fail?"),
        _segment(2.1, 4, "Because the old path drops state."),
        _segment(4.1, 6, "The answer is to preserve state."),
        _segment(6.4, 8, "New topic: pricing changed."),
        _segment(8.1, 10, "Here is the supporting detail."),
    ], client=SemanticClient())
    assert len(result["story_segments"]) == 2
    idea_a, idea_b = result["story_segments"]
    assert idea_a["end_ms"] == 6000
    assert idea_a["completeness"] == {
        "setup_complete": True, "claim_complete": True, "payoff_present": True,
        "conclusion_present": False, "unresolved": False, "next_topic_started": True,
        "likely_semantic_end_ms": 6000,
    }
    assert idea_b["start_ms"] == 6400
    assert idea_b["start_reason"] == "new_idea"
    relation = result["payoff_relationships"][0]
    assert relation["story_id"] == idea_a["story_id"]
    assert relation["payoff_unit_id"] == idea_a["semantic_unit_ids"][2]
    assert idea_a["semantic_unit_ids"][0] in relation["setup_unit_ids"]


def test_semantic_units_reference_existing_source_editing_ids_only():
    editing = {
        "cuts": [{"id": "edit_cut_000000800", "start_ms": 800, "end_ms": 800}],
        "pattern_interrupts": [{"id": "edit_pattern_interrupt_000000900_x", "start_ms": 900, "end_ms": 900}],
    }
    result = _build([_segment(0, 1, "Why now?")], client=SemanticClient(), source_editing=editing)
    references = result["semantic_units"][0]["references"]["source_editing_event_ids"]
    assert references == ["edit_cut_000000800", "edit_pattern_interrupt_000000900_x"]
    assert result["evidence"]["source_editing_ids_reused"] == references


def test_direct_cross_speaker_answer_can_resolve_question_as_payoff():
    result = _build([
        _segment(0, 1, "How much revenue are you making?", speaker=1),
        _segment(1.4, 2.5, "We're making 43 million per year.", speaker=0),
    ], client=SemanticClient())
    answer = result["semantic_units"][1]
    assert answer["primary_story_role"] == "claim"
    assert "payoff" in answer["secondary_roles"]
    assert answer["evidence"]["response_to_unit_id"] == result["semantic_units"][0]["semantic_unit_id"]
    assert result["story_segments"][0]["completeness"]["payoff_present"] is True
    assert result["payoff_relationships"][0]["payoff_unit_id"] == answer["semantic_unit_id"]


def test_malformed_llm_output_falls_back_without_failing():
    result = _build([_segment(0, 1, "What happened?")], client=SemanticClient(malformed=True))
    assert result["status"] == "limited"
    assert result["semantic_units"][0]["source"] == "derived"
    assert result["semantic_units"][0]["primary_story_role"] == "question"
    assert result["provenance"]["llm_call_count"] == 1
    assert result["provenance"]["llm_failure_count"] == 1


def test_chunk_overlap_preserves_one_continuing_story_across_window_boundary():
    segments = [_segment(index, index + .8, f"Supporting detail {index}.") for index in range(31)]
    client = SemanticClient()
    result = _build(segments, client=client)
    assert client.calls == 2
    assert result["provenance"]["window_overlap_units"] == 3
    assert len(result["story_segments"]) == 1
    assert len(result["story_segments"][0]["semantic_unit_ids"]) == 31


def test_window_builder_overlaps_without_using_fixed_story_boundaries():
    inputs = [{"input_index": index, "text": f"unit {index}"} for index in range(7)]
    windows = semantic_windows(inputs, max_words=20, max_units=4, overlap_units=2)
    assert [[item["input_index"] for item in window] for window in windows] == [[0, 1, 2, 3], [2, 3, 4, 5], [4, 5, 6]]


def test_direct_interviewer_prompt_starts_new_idea_despite_uncertain_speaker():
    result = _build([
        _segment(0, 2, "Welcome back to the show.", speaker=0),
        _segment(2.2, 4, "You're fresh off a meeting with the team.", speaker=0),
        _segment(4.1, 5.5, "Tell me, what happened?", speaker=0),
        _segment(5.7, 8, "We agreed to work together.", speaker=1),
    ])
    stories = result["story_segments"]
    assert len(stories) == 2
    assert stories[1]["start_ms"] == 2200
    assert stories[1]["semantic_unit_ids"] == [
        result["semantic_units"][1]["semantic_unit_id"],
        result["semantic_units"][2]["semantic_unit_id"],
        result["semantic_units"][3]["semantic_unit_id"],
    ]


def test_missing_transcript_is_explicitly_unavailable():
    result = _build([])
    assert result["status"] == "unavailable"
    assert result["semantic_units"] == []
    assert "No timestamped transcript" in result["limitations"][0]
