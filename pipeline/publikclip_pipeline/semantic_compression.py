"""Conservative semantic compression plans for Clip Selection v2."""
from __future__ import annotations
import hashlib, time
from typing import Any

SCHEMA_VERSION = 1
FILLERS = {"uh", "um", "er", "erm", "eh", "äh", "ah", "hmm"}
REASONS = {"filler", "hesitation", "false_start", "repeated_phrase", "self_correction", "redundant_sentence", "dead_air", "low_information_bridge", "tangent", "repeated_context", "optional_detail", "dramatic_pause", "reveal_pause", "reaction", "speaker_handoff", "meaning_required", "payoff_required", "hook_required", "uncertain"}

def _id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha1(value.encode()).hexdigest()[:12]}"

def _words(segments: list[dict[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    out=[]
    for seg in segments:
        for w in seg.get("words") or []:
            text=str(w.get("word") or w.get("text") or "").strip()
            if not text: continue
            ws=round(float(w.get("start_ms", (w.get("start") or 0)*1000))); we=round(float(w.get("end_ms", (w.get("end") or w.get("start") or 0)*1000)))
            if we<=ws or we<start or ws>end: continue
            out.append({"text":text,"norm":text.casefold().strip(".,!?;:"),"start_ms":max(start,ws),"end_ms":min(end,we),"speaker":w.get("speaker",seg.get("speaker"))})
    return out

def _at(units, t):
    return next((u for u in units if int(u.get("start_ms",0))<=t<=int(u.get("end_ms",0))), None)

def _merge(spans):
    out=[]
    for a,b in sorted(spans):
        if not out or a>out[-1][1]: out.append((a,b))
        else: out[-1]=(out[-1][0],max(out[-1][1],b))
    return out

def _decision(cid,start,end,action,reason,confidence,evidence,units,words,risk=None):
    return {"decision_id":_id("decision",f"{cid}:{start}:{end}:{action}:{reason}"),"start_ms":start,"end_ms":end,"action":action,"reason":reason,"confidence":round(confidence,4),"evidence":evidence,"affected_semantic_unit_ids":list(dict.fromkeys(units)),"affected_transcript_tokens":[{"text":w["text"],"start_ms":w["start_ms"],"end_ms":w["end_ms"]} for w in words],"risk_flags":list(dict.fromkeys(risk or [])),"join_risk":{}}

def _join(left,right,editing):
    same=not left or not right or left.get("speaker")==right.get("speaker")
    visual=any(abs(int(e.get("timestamp_ms",e.get("start_ms",0)) or 0)-(left or {}).get("end_ms",0))<=250 for k in ("cuts","transitions","pattern_interrupts","reframes","zooms") for e in editing.get(k) or [])
    sentence=bool(left and right and left["text"][-1:] not in ".?!" and right["text"][:1].islower())
    return {"semantic_join_quality":"high" if same and not sentence else "medium" if same else "low","audio_join_risk":"low" if same else "high","visual_jump_risk":"medium" if visual else "low","speaker_consistency":same,"sentence_join_risk":sentence,"requires_visual_cover":bool(visual or not same),"requires_audio_crossfade":not same,"left_retained_range":[left["start_ms"],left["end_ms"]] if left else None,"right_retained_range":[right["start_ms"],right["end_ms"] if right else None],"speaker_before":left.get("speaker") if left else None,"speaker_after":right.get("speaker") if right else None}

def _pause(left,right,units,candidate):
    if left.get("speaker")!=right.get("speaker"): return "keep","speaker_handoff",.96
    before,after=_at(units,left["end_ms"]),_at(units,right["start_ms"]); protected=set(candidate.get("payoff_reveal_unit_ids") or [])|{candidate.get("hook_unit_id")}
    if after and (after.get("semantic_unit_id") in protected or after.get("primary_story_role") in {"reveal","payoff"}): return "keep","reveal_pause",.9
    if (before and before.get("primary_story_role") in {"hook","question","conflict","surprise"}) or (after and after.get("primary_story_role") in {"reveal","payoff","reaction"}): return "keep","dramatic_pause",.84
    return ("remove","dead_air",.72) if right["start_ms"]-left["end_ms"]>=900 else ("optional_keep","hesitation",.58)

def _candidate(candidate,segments,story,editing):
    start,end=int(candidate["start_ms"]),int(candidate["end_ms"]); wanted=set(candidate.get("semantic_unit_ids") or []); units=[u for u in story.get("semantic_units") or [] if u.get("semantic_unit_id") in wanted]
    protected=set(candidate.get("setup_context_unit_ids") or [])|set(candidate.get("payoff_reveal_unit_ids") or [])|({candidate["hook_unit_id"]} if candidate.get("hook_unit_id") else set())|{u["semantic_unit_id"] for u in units if u.get("primary_story_role") in {"hook","payoff","reveal"}}
    words=_words(segments,start,end); decisions=[]; remove=[]
    conservative=bool(candidate.get("source_highlight_origin") or float(candidate.get("source_preedited_likelihood") or 0) >= .6)
    for i,w in enumerate(words):
        span=[w]; filler=w["norm"] in FILLERS
        if w["norm"]=="you" and i+1<len(words) and words[i+1]["norm"]=="know": filler=True; span=words[i:i+2]
        if not filler: continue
        unit=_at(units,w["start_ms"]); guarded=bool(unit and unit.get("semantic_unit_id") in protected); action,reason,conf=("optional_keep","meaning_required",.68) if guarded else ("remove","filler",.9)
        if action=="remove": remove.append((span[0]["start_ms"],span[-1]["end_ms"]))
        decisions.append(_decision(candidate["candidate_id"],span[0]["start_ms"],span[-1]["end_ms"],action,reason,conf,[{"detector":"filler_lexicon","text":" ".join(x["text"] for x in span)}],[unit["semantic_unit_id"]] if unit else [],span,["protected_unit"] if guarded else []))
    for i,w in enumerate(words):
        if w["norm"]!="like" or i==0 or i+1>=len(words) or words[i+1]["norm"] in {"boxing","this","that","it","you","music","him","her"}: continue
        if words[i-1]["norm"] in {"and","so","but","well"} and words[i+1]["norm"] in {"i","we","you","the","a"}:
            unit=_at(units,w["start_ms"])
            if unit and unit.get("semantic_unit_id") not in protected:
                remove.append((w["start_ms"],w["end_ms"])); decisions.append(_decision(candidate["candidate_id"],w["start_ms"],w["end_ms"],"remove","filler",.74,[{"detector":"discourse_marker_context"}],[unit["semantic_unit_id"]],[w]))
    norms=[w["norm"] for w in words]
    for n in (3,2):
        found=False
        for i in range(len(norms)-2*n+1):
            if norms[i:i+n]!=norms[i+n:i+2*n]: continue
            first,second=words[i:i+n],words[i+n:i+2*n]; unit=_at(units,first[0]["start_ms"])
            if second[0]["start_ms"]-first[-1]["end_ms"]>1200 or (unit and unit.get("semantic_unit_id") in protected): continue
            remove.append((first[0]["start_ms"],first[-1]["end_ms"])); decisions.append(_decision(candidate["candidate_id"],first[0]["start_ms"],first[-1]["end_ms"],"remove","false_start",.83,[{"detector":"adjacent_ngram_repeat","n":n}],[unit["semantic_unit_id"]] if unit else [],first)); found=True; break
        if found: break
    for left,right in zip(words,words[1:]):
        if right["start_ms"]-left["end_ms"]<350: continue
        action,reason,conf=_pause(left,right,units,candidate)
        if conservative and action=="remove": action, reason, conf = "optional_keep", "hesitation", .62
        if action=="remove": remove.append((left["end_ms"],right["start_ms"]))
        decisions.append(_decision(candidate["candidate_id"],left["end_ms"],right["start_ms"],action,reason,conf,[{"detector":"asr_gap","duration_ms":right["start_ms"]-left["end_ms"]}],[u["semantic_unit_id"] for u in units if u["start_ms"]<=right["start_ms"] and u["end_ms"]>=left["end_ms"]],[left,right],["timing_function_possible"] if action!="remove" else []))
    for unit in units:
        if conservative or unit["semantic_unit_id"] in protected or unit.get("evidence",{}).get("relation_to_previous")!="tangent": continue
        uw=[w for w in words if unit["start_ms"]<=w["start_ms"]<=unit["end_ms"]]; decisions.append(_decision(candidate["candidate_id"],unit["start_ms"],unit["end_ms"],"remove","tangent",.8,[{"detector":"story_relation","relationship":"tangent"}],[unit["semantic_unit_id"]],uw,["verify_payoff_context"])); remove.append((unit["start_ms"],unit["end_ms"]))
    decisions.sort(key=lambda d:(d["start_ms"],d["end_ms"],d["decision_id"])); removed=_merge(remove); retained=[]; cursor=start
    for a,b in removed:
        if cursor<a: retained.append((cursor,a))
        cursor=max(cursor,b)
    if cursor<end: retained.append((cursor,end))
    for d in decisions:
        if d["action"]!="remove": continue
        left=next((w for w in reversed(words) if w["end_ms"]<=d["start_ms"]),None); right=next((w for w in words if w["start_ms"]>=d["end_ms"]),None); join=_join(left,right,editing); d["join_risk"]=join; d.update({"desired_semantic_cut_ms":d["start_ms"],"nearest_word_boundary":{"before_ms":left["end_ms"] if left else start,"after_ms":right["start_ms"] if right else end},"speech_active_at_cut":bool(left and right),"visual_change_near_cut":join["visual_jump_risk"]!="low","source_cut_nearby":join["visual_jump_risk"]=="medium","recommended_cut_window_ms":[max(start,d["start_ms"]-80),min(end,d["end_ms"]+80)],"cut_risk":"high" if join["semantic_join_quality"]=="low" else "medium" if join["semantic_join_quality"]!="high" else "low"})
    original=max(0,end-start); removed_ms=sum(b-a for a,b in removed); reason_ms={r:sum(d["end_ms"]-d["start_ms"] for d in decisions if d["action"]=="remove" and d["reason"]==r) for r in REASONS}; protected_ms=sum(max(0,int(u["end_ms"])-int(u["start_ms"])) for u in units if u["semantic_unit_id"] in protected)
    return {"candidate_id":candidate["candidate_id"],"original_start_ms":start,"original_end_ms":end,"decisions":decisions,"retained_ranges":[{"start_ms":a,"end_ms":b} for a,b in retained],"removed_ranges":[{"start_ms":a,"end_ms":b} for a,b in removed],"protected_ranges":[{"start_ms":u["start_ms"],"end_ms":u["end_ms"],"semantic_unit_id":u["semantic_unit_id"],"reason":"meaning_required"} for u in units if u["semantic_unit_id"] in protected],"estimated_original_duration_ms":original,"estimated_compressed_duration_ms":original-removed_ms,"compression_ratio":round((original-removed_ms)/max(1,original),4),"semantic_integrity_status":"needs_review" if any(d.get("join_risk",{}).get("sentence_join_risk") or d.get("cut_risk")=="high" for d in decisions) else "preserved","confidence":round(sum(d["confidence"] for d in decisions)/len(decisions),4) if decisions else .96,"limitations":["Source media was not rendered; join quality is advisory.","Ambiguous redundancy remains KEEP or OPTIONAL_KEEP."],"metrics":{"original_duration":original,"retained_duration":original-removed_ms,"removed_duration":removed_ms,"compression_ratio":round((original-removed_ms)/max(1,original),4),"filler_removed_ms":reason_ms.get("filler",0),"pause_removed_ms":reason_ms.get("dead_air",0)+reason_ms.get("hesitation",0),"redundancy_removed_ms":reason_ms.get("false_start",0)+reason_ms.get("repeated_phrase",0)+reason_ms.get("redundant_sentence",0),"tangent_removed_ms":reason_ms.get("tangent",0),"internal_cut_count":len(removed),"high_risk_cut_count":sum(d.get("cut_risk")=="high" for d in decisions),"protected_content_ratio":round(protected_ms/max(1,original),4)}}

def build_plan(*,candidates,segments,story_semantics,source_editing=None):
    started=time.monotonic(); stories={s.get("story_id"):s for s in story_semantics.get("story_segments") or []}; plans=[_candidate(c,segments,stories.get(c.get("story_id"),story_semantics),source_editing or {}) for c in candidates]; original=sum(p["metrics"]["original_duration"] for p in plans); retained=sum(p["metrics"]["retained_duration"] for p in plans)
    return {"semantic_compression_version":"semantic-compression-v1","schema_version":SCHEMA_VERSION,"status":"available","candidate_count":len(plans),"candidates":plans,"metrics":{"candidate_count":len(plans),"original_duration":original,"retained_duration":retained,"removed_duration":original-retained,"compression_ratio":round(retained/max(1,original),4),"internal_cut_count":sum(p["metrics"]["internal_cut_count"] for p in plans),"high_risk_cut_count":sum(p["metrics"]["high_risk_cut_count"] for p in plans)},"provenance":{"method":"deterministic-transcript-story-rules-v1","llm_used":False,"runtime_sec":round(time.monotonic()-started,4)},"limitations":["No rendering, crossfades, J/L cuts, or visual cover execution is performed.","Ambiguous redundancy and semantic joins remain KEEP or OPTIONAL_KEEP."]}
