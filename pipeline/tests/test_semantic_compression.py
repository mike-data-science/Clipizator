from publikclip_pipeline.semantic_compression import build_plan

def word(text, start, end, speaker=0):
    return {"word": text, "start": start / 1000, "end": end / 1000, "speaker": speaker}

def fixture(texts, gaps=None, roles=None, protected=None):
    gaps = gaps or [0] * max(0, len(texts)-1)
    units=[]; words=[]; cursor=0
    for i, text in enumerate(texts):
        start=cursor; bits=text.split(); duration=max(300, len(bits)*300); end=start+duration
        units.append({"semantic_unit_id": f"u{i}", "start_ms": start, "end_ms": end, "transcript": text, "primary_story_role": (roles or ["claim"]*len(texts))[i], "secondary_roles": [], "evidence": {}})
        for j, bit in enumerate(bits): words.append(word(bit, start+j*300, start+(j+1)*300))
        cursor=end+(gaps[i] if i < len(gaps) else 0)
    story={"story_segments":[{"story_id":"s1","semantic_units":units}],"semantic_units":units}
    candidate={"candidate_id":"c1","story_id":"s1","semantic_unit_ids":[u["semantic_unit_id"] for u in units],"start_ms":0,"end_ms":cursor,"setup_context_unit_ids":[],"payoff_reveal_unit_ids":[],"hook_unit_id":None}
    if protected: candidate["setup_context_unit_ids"]=[protected]
    return build_plan(candidates=[candidate],segments=[{"words":words}],story_semantics=story)["candidates"][0]

def test_tiny_intra_sentence_filler_becomes_optional_and_like_semantic_preserved():
    plan=fixture(["I uh like boxing"]); reasons=[d["reason"] for d in plan["decisions"]]
    assert "filler" in reasons
    assert any(d["reason"] == "filler" and d["action"] == "optional_keep" for d in plan["decisions"])
    assert not any(d["action"] == "remove" and "like" in [w["text"].casefold() for w in d["affected_transcript_tokens"]] for d in plan["decisions"])

def test_false_start_and_stable_ids():
    a=fixture(["I had I had a dog"]); b=fixture(["I had I had a dog"])
    assert any(d["reason"] == "false_start" and d["action"] == "remove" for d in a["decisions"])
    assert [d["decision_id"] for d in a["decisions"]] == [d["decision_id"] for d in b["decisions"]]

def test_dramatic_reveal_pause_and_speaker_handoff_are_kept():
    plan=fixture(["The truth is", "the dog saved me"], gaps=[1200], roles=["question", "reveal"])
    assert any(d["reason"] == "reveal_pause" and d["action"] == "keep" for d in plan["decisions"])

def test_required_context_and_legacy_plan_shape():
    plan=fixture(["The setup", "the payoff"], roles=["context", "payoff"], protected="u0")
    assert plan["protected_ranges"]
    assert "metrics" in plan and "retained_ranges" in plan


def test_dead_air_is_removed_but_source_highlight_is_conservative():
    plan=fixture(["The answer", "is clear"], gaps=[1500])
    assert any(d["reason"] == "dead_air" and d["action"] == "remove" for d in plan["decisions"])
    # The same candidate's already-edited origin is advisory-only and keeps the gap.
    from publikclip_pipeline.semantic_compression import build_plan
    candidate={"candidate_id":"tight","story_id":"s1","semantic_unit_ids":["u0","u1"],"start_ms":0,"end_ms":4400,"source_highlight_origin":True,"source_preedited_likelihood":.9}
    story={"story_segments":[{"story_id":"s1","semantic_units":[{"semantic_unit_id":"u0","start_ms":0,"end_ms":1800,"primary_story_role":"claim"},{"semantic_unit_id":"u1","start_ms":3300,"end_ms":4400,"primary_story_role":"claim"}]}],"semantic_units":[]}
    words=[word("The",0,300),word("answer",300,600),word("is",3300,3600),word("clear",3600,3900)]
    result=build_plan(candidates=[candidate],segments=[{"words":words}],story_semantics=story)["candidates"][0]
    assert not any(d["action"] == "remove" and d["reason"] == "dead_air" for d in result["decisions"])


def test_terminal_removal_has_no_right_join_range():
    plan = fixture(["The answer uh"])
    terminal_filler = next(d for d in plan["decisions"] if d["reason"] == "filler")
    assert terminal_filler["join_risk"]["right_retained_range"] is None


def test_clustered_micro_fillers_are_suppressed():
    plan = fixture(["You know and you know we agree"])
    fillers = [d for d in plan["decisions"] if d["reason"] == "filler"]
    assert len(fillers) == 2
    assert all(d["action"] == "optional_keep" for d in fillers)
    assert all(d["micro_cut_suppressed"] and d["suppression_reason"] == "clustered_small_fillers" for d in fillers)


def test_high_risk_filler_join_is_downgraded():
    candidate = {"candidate_id":"c1","story_id":"s1","semantic_unit_ids":["u0"],"start_ms":0,"end_ms":900}
    story = {"story_segments":[{"story_id":"s1","semantic_units":[{"semantic_unit_id":"u0","start_ms":0,"end_ms":900,"primary_story_role":"claim"}]}]}
    words = [word("Well",0,300,0), word("uh",300,600,0), word("okay",600,900,1)]
    plan = build_plan(candidates=[candidate],segments=[{"words":words}],story_semantics=story)["candidates"][0]
    filler = next(d for d in plan["decisions"] if d["reason"] == "filler")
    assert filler["action"] == "optional_keep"
    assert filler["cut_risk"] == "high"


def test_natural_speech_with_filler_can_remain_unchanged():
    plan = fixture(["I think you know we can do this"])
    assert not plan["removed_ranges"]
    filler = next(d for d in plan["decisions"] if d["reason"] == "filler")
    assert filler["action"] == "optional_keep"
