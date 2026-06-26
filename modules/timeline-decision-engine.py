#!/usr/bin/env python3
"""
Timeline Decision Engine — V1.5.6
----------------------------------
Input:  V1.5.5 retention_ranked_clips[] (scored by RetentionIntelligenceEngine)
Output: execution_timeline[] + timeline_decision_report

Clip selection, narrative structure assignment, transition decisions,
and timeline quality scoring — all metadata-driven (no pixel access,
no external API).

Pipeline insertion point:
    after  V1.5.5 retention-intelligence-engine
    before renderer / video composer
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


# ---------------------------------------------------------------------------
# Narrative structure constants
# ---------------------------------------------------------------------------

SEGMENT_DEFS = {
    "HOOK":       {"start": 0,  "end": 3,  "pct": 0.10},
    "BUILDUP":    {"start": 3,  "end": 10, "pct": 0.233},
    "ESCALATION": {"start": 10, "end": 20, "pct": 0.333},
    "PAYOFF":     {"start": 20, "end": 30, "pct": 0.333},
}

SEGMENT_ORDER = ["HOOK", "BUILDUP", "ESCALATION", "PAYOFF"]

# Per-segment clip allocation ratios (normalised across 4 segments)
SEGMENT_CLIP_RATIOS = {
    "HOOK":       1.0,
    "BUILDUP":    2.2,
    "ESCALATION": 3.3,
    "PAYOFF":     3.3,
}

# Default transition per segment boundary
BOUNDARY_TRANSITIONS = {
    ("HOOK",       "BUILDUP"):    "zoom",
    ("BUILDUP",    "ESCALATION"): "dissolve",
    ("ESCALATION", "PAYOFF"):     "dissolve",
}


# ---------------------------------------------------------------------------
# TimelineDecisionEngine
# ---------------------------------------------------------------------------

class TimelineDecisionEngine:
    """Clips → selection → narrative structure → transitions → timeline."""

    def __init__(self, total_duration: float = 30, seed: int = 42) -> None:
        self.total_duration = float(total_duration)
        self.rng = np.random.default_rng(seed)

        # selection thresholds
        self.retention_threshold = 75.0
        self.hook_survival_threshold = 80.0

    # -- 1. select_clips ----------------------------------------------------

    def select_clips(self,
                     retention_clips: List[Dict[str, Any]]
                     ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Select clips where:
            retention_score >= 75  OR  hook_survival_score >= 80
        Returns (selected, rejected).
        """
        selected: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []

        for c in retention_clips:
            rs = float(c.get("retention_score", 0))
            hs = float(c.get("hook_survival_score", 0))
            if rs >= self.retention_threshold or hs >= self.hook_survival_threshold:
                selected.append(c)
            else:
                rejected.append(c)

        # stable: keep input order within each bucket
        return selected, rejected

    # -- 2. build_narrative_structure ---------------------------------------

    def build_narrative_structure(self) -> Dict[str, Dict[str, Any]]:
        """
        Generate 4-segment narrative structure for total_duration seconds.

        HOOK:       0s  – 3s    (10%)
        BUILDUP:    3s  – 10s   (~23.3%)
        ESCALATION: 10s – 20s   (~33.3%)
        PAYOFF:     20s – 30s   (~33.3%)
        """
        td = self.total_duration
        return {
            seg: {
                "range": f"{d['start']}-{d['end']}s",
                "start_s": d["start"],
                "end_s": d["end"],
                "duration_s": d["end"] - d["start"],
                "pct": round(d["pct"] * 100, 1),
            }
            for seg, d in SEGMENT_DEFS.items()
        }

    # -- 3. assign_clips_to_segments ----------------------------------------

    def assign_clips_to_segments(
            self,
            selected_clips: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Assign selected clips to the 4 narrative segments.

        Constraints:
          - HOOK: MUST contain the clip with the highest hook_survival_score.
          - BUILDUP: hook_score second-highest, gradually increasing.
          - ESCALATION: emotion_intensity strictly increasing.
          - PAYOFF: spike_strength highest clip must be in the last 30%.

        Returns dict mapping segment name → list of clip dicts (ordered within segment).
        """
        n = len(selected_clips)
        if n == 0:
            return {
                "HOOK": [], "BUILDUP": [], "ESCALATION": [], "PAYOFF": [],
                "_meta": {"total_clips": 0},
            }

        # --- Determine per-segment clip counts (proportional to ratios) ---
        total_ratio = sum(SEGMENT_CLIP_RATIOS.values())
        raw_counts = {
            seg: max(1, round(n * SEGMENT_CLIP_RATIOS[seg] / total_ratio))
            for seg in SEGMENT_ORDER
        }

        # Adjust to match n exactly
        diff = n - sum(raw_counts.values())
        # distribute diff (add/subtract starting from last segment)
        idx = len(SEGMENT_ORDER) - 1
        while diff != 0:
            seg = SEGMENT_ORDER[idx % len(SEGMENT_ORDER)]
            if diff > 0 and raw_counts[seg] < n:
                raw_counts[seg] += 1
                diff -= 1
            elif diff < 0 and raw_counts[seg] > 1:
                raw_counts[seg] -= 1
                diff += 1
            idx -= 1

        # --- Build candidate pools ---
        # HOOK: highest hook_survival_score
        hook_clip = max(selected_clips, key=lambda c: c.get("hook_survival_score", 0))
        remaining = [c for c in selected_clips if c["asset_id"] != hook_clip["asset_id"]]

        # PAYOFF: highest spike_strength must be in last 30%
        payoff_candidate = max(remaining, key=lambda c: c.get("spike_strength", 0))
        remaining = [c for c in remaining if c["asset_id"] != payoff_candidate["asset_id"]]

        # BUILDUP: sort by hook_score DESC for "second highest → gradually increasing"
        buildup_pool = sorted(remaining, key=lambda c: c.get("hook_score", 0), reverse=True)

        # ESCALATION: sort by emotion_intensity ASC for strict increasing
        escalation_pool = sorted(remaining, key=lambda c: c.get("emotion_intensity", 0))

        # --- Assign ---
        assignments: Dict[str, List[Dict[str, Any]]] = {
            "HOOK":       [hook_clip],
            "BUILDUP":    [],
            "ESCALATION": [],
            "PAYOFF":     [],
        }

        # BUILDUP: take from buildup_pool (highest hook_score first)
        buildup_available = [c for c in buildup_pool
                             if c["asset_id"] not in {hook_clip["asset_id"], payoff_candidate["asset_id"]}]
        buildup_count = raw_counts["BUILDUP"]
        assignments["BUILDUP"] = buildup_available[:buildup_count] if buildup_count <= len(buildup_available) else buildup_available

        # Remaining for ESCALATION + PAYOFF
        used_ids = {hook_clip["asset_id"], payoff_candidate["asset_id"]}
        used_ids.update(c["asset_id"] for c in assignments["BUILDUP"])
        remaining_all = [c for c in remaining if c["asset_id"] not in used_ids]
        # but also ensure payoff_candidate is in PAYOFF
        remaining_all = [c for c in remaining_all if c["asset_id"] != payoff_candidate["asset_id"]]

        # ESCALATION: emotion_intensity increasing
        escalation_pool_final = sorted(remaining_all,
                                       key=lambda c: c.get("emotion_intensity", 0))
        escalation_count = raw_counts["ESCALATION"]
        assignments["ESCALATION"] = escalation_pool_final[:escalation_count] if escalation_count <= len(escalation_pool_final) else escalation_pool_final

        # PAYOFF: remaining + payoff_candidate
        used_ids.update(c["asset_id"] for c in assignments["ESCALATION"])
        payoff_pool = [c for c in remaining
                       if c["asset_id"] not in used_ids and c["asset_id"] != payoff_candidate["asset_id"]]
        payoff_pool.sort(key=lambda c: c.get("spike_strength", 0), reverse=True)
        # Ensure payoff_candidate is placed last in PAYOFF
        payoff_others = payoff_pool[:raw_counts["PAYOFF"] - 1] if raw_counts["PAYOFF"] > 1 else []
        assignments["PAYOFF"] = payoff_others + [payoff_candidate]

        # If any segment is empty (edge case with very few clips), redistribute
        for seg in SEGMENT_ORDER:
            if not assignments[seg] and n >= len(SEGMENT_ORDER):
                # borrow from adjacent segment
                for donor in SEGMENT_ORDER:
                    if len(assignments.get(donor, [])) > 1:
                        moved = assignments[donor].pop(-1)
                        assignments[seg].append(moved)
                        break

        total_assigned = sum(len(assignments[s]) for s in SEGMENT_ORDER)
        return {
            **assignments,
            "_meta": {
                "total_clips": n,
                "total_assigned": total_assigned,
                "segment_counts": {s: len(assignments[s]) for s in SEGMENT_ORDER},
            },
        }

    # -- 4. decide_transition -----------------------------------------------

    def decide_transition(self,
                          from_clip: Dict[str, Any],
                          to_clip: Dict[str, Any],
                          from_segment: str,
                          to_segment: str) -> str:
        """
        Transition decision based on motion + emotion + scene_gap.

        Rules:
          - Same segment: cut
          - Cross-segment (HOOK→BUILDUP): zoom
          - Cross-segment (BUILDUP→ESCALATION): dissolve or speed_ramp
          - Cross-segment (ESCALATION→PAYOFF): dissolve or motion_blur
          - Emotion gap >= 30: motion_blur (overrides above)
          - Otherwise: segment default
        """
        emotion_gap = abs(
            float(to_clip.get("emotion_intensity", 50))
            - float(from_clip.get("emotion_intensity", 50))
        )

        if emotion_gap >= 30:
            return "motion_blur"

        if from_segment == to_segment:
            return "cut"

        pair = (from_segment, to_segment)
        if pair in BOUNDARY_TRANSITIONS:
            default = BOUNDARY_TRANSITIONS[pair]
        else:
            default = "dissolve"

        # For BUILDUP→ESCALATION: dissolve or speed_ramp (coin flip)
        if pair == ("BUILDUP", "ESCALATION"):
            return "speed_ramp" if self.rng.random() < 0.5 else "dissolve"

        # For ESCALATION→PAYOFF: dissolve or motion_blur
        if pair == ("ESCALATION", "PAYOFF"):
            return "motion_blur" if self.rng.random() < 0.5 else "dissolve"

        return default

    # -- 5. build_timeline --------------------------------------------------

    def build_timeline(self,
                       assigned_segments: Dict[str, Any]) -> Dict[str, Any]:
        """Build complete 30-second timeline from assigned segments."""
        timeline: List[Dict[str, Any]] = []
        seg_meta = assigned_segments.get("_meta", {})

        # Sort clips within each segment according to narrative rules
        for seg_name in SEGMENT_ORDER:
            clips = assigned_segments.get(seg_name, [])
            seg_def = SEGMENT_DEFS[seg_name]
            seg_start = seg_def["start"]
            seg_end = seg_def["end"]
            seg_dur = seg_end - seg_start

            if not clips:
                continue

            n = len(clips)
            # Distribute segment duration equally among clips
            per_clip_dur = seg_dur / n

            for i, clip in enumerate(clips):
                start_t = round(seg_start + i * per_clip_dur, 2)
                end_t = round(seg_start + (i + 1) * per_clip_dur, 2)
                # last clip stretches to segment boundary
                if i == n - 1:
                    end_t = round(float(seg_end), 2)

                timeline.append({
                    "start": start_t,
                    "end": end_t,
                    "clip_id": clip.get("asset_id", "unknown"),
                    "role": seg_name,
                    "transition_in": "cut",   # placeholder, set below
                    "transition_out": "cut",  # placeholder, set below
                    "score": clip.get("retention_score", 0),
                    "hook_survival": clip.get("hook_survival_score", 0),
                    "emotion_intensity": clip.get("emotion_intensity", 0),
                    "spike_strength": clip.get("spike_strength", 0),
                })

        # Sort timeline by start time
        timeline.sort(key=lambda e: float(e["start"]))

        # Assign transitions
        for i in range(len(timeline)):
            entry = timeline[i]
            if i == 0:
                entry["transition_in"] = "cut"
            else:
                prev = timeline[i - 1]
                entry["transition_in"] = self.decide_transition(
                    prev, entry,
                    prev["role"], entry["role"],
                )

            if i < len(timeline) - 1:
                nxt = timeline[i + 1]
                entry["transition_out"] = self.decide_transition(
                    entry, nxt,
                    entry["role"], nxt["role"],
                )
            else:
                entry["transition_out"] = "cut"

        return {
            "duration": self.total_duration,
            "timeline": timeline,
            "total_entries": len(timeline),
        }

    # -- 6. compute_timeline_score ------------------------------------------

    def compute_timeline_score(self,
                               timeline_result: Dict[str, Any],
                               clips: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Timeline quality score:
        0.4 * avg_retention + 0.3 * narrative_flow
        + 0.2 * transition_smoothness + 0.1 * hook_strength
        """
        tline = timeline_result.get("timeline", [])
        if not tline:
            return {
                "timeline_score": 0.0,
                "avg_retention": 0.0,
                "narrative_flow": 0.0,
                "transition_smoothness": 0.0,
                "hook_strength": 0.0,
            }

        # avg_retention (0-100)
        scores = [e.get("score", 0) for e in tline]
        avg_retention = round(float(np.mean(scores)) if scores else 0.0, 2)

        # narrative_flow (0-100): check emotion increasing across segments
        # Segments in order: HOOK → BUILDUP → ESCALATION → PAYOFF
        segment_emotions: Dict[str, List[float]] = {}
        for e in tline:
            role = e.get("role", "")
            segment_emotions.setdefault(role, []).append(
                float(e.get("emotion_intensity", 0))
            )

        flow_score = 100.0
        prev_avg = -1.0
        emotion_order = ["HOOK", "BUILDUP", "ESCALATION", "PAYOFF"]
        for seg in emotion_order:
            vals = segment_emotions.get(seg, [])
            if vals:
                cur_avg = float(np.mean(vals))
                if cur_avg <= prev_avg and prev_avg >= 0:
                    flow_score -= 15.0
                # Check ESCALATION strict increasing within segment
                if seg == "ESCALATION" and len(vals) > 1:
                    for j in range(1, len(vals)):
                        if vals[j] <= vals[j - 1]:
                            flow_score -= 5.0
                prev_avg = cur_avg

        narrative_flow = round(clamp(flow_score, 0, 100), 2)

        # transition_smoothness (0-100)
        smooth_score = 100.0
        for i in range(len(tline) - 1):
            curr_out = tline[i].get("transition_out", "")
            nxt_in = tline[i + 1].get("transition_in", "")
            # Consistency check
            if curr_out != nxt_in:
                smooth_score -= 3.0
            # Intra-segment: cut is optimal
            if tline[i]["role"] == tline[i + 1]["role"]:
                if curr_out != "cut" or nxt_in != "cut":
                    smooth_score -= 2.0
            else:
                # Cross-segment: reasonable transitions
                good_set = {"dissolve", "zoom", "speed_ramp", "motion_blur"}
                if curr_out not in good_set:
                    smooth_score -= 2.0

        transition_smoothness = round(clamp(smooth_score, 0, 100), 2)

        # hook_strength (0-100): HOOK clip hook_survival / 100
        hook_entries = [e for e in tline if e.get("role") == "HOOK"]
        if hook_entries:
            hook_strength = clamp(hook_entries[0].get("hook_survival", 0), 0, 100)
        else:
            hook_strength = 0.0

        # composite
        timeline_score = round(
            0.4 * avg_retention
            + 0.3 * narrative_flow
            + 0.2 * transition_smoothness
            + 0.1 * hook_strength,
            2,
        )

        return {
            "timeline_score": timeline_score,
            "avg_retention": avg_retention,
            "narrative_flow": narrative_flow,
            "transition_smoothness": transition_smoothness,
            "hook_strength": hook_strength,
        }

    # -- 7. execute (main entry) ---------------------------------------------

    def execute(self,
                retention_clips: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Main entry: select → assign → build → score."""

        selected, rejected = self.select_clips(retention_clips)

        narrative = self.build_narrative_structure()

        assigned = self.assign_clips_to_segments(selected)

        timeline_result = self.build_timeline(assigned)

        # Build clip lookup for scoring
        clip_lookup = {c["asset_id"]: c for c in retention_clips}
        score_breakdown = self.compute_timeline_score(timeline_result, selected)

        # Transition distribution
        trans_dist: Dict[str, int] = {
            "cut": 0, "dissolve": 0, "zoom": 0,
            "speed_ramp": 0, "motion_blur": 0,
        }
        for e in timeline_result.get("timeline", []):
            for k in ("transition_in", "transition_out"):
                t = e.get(k, "")
                if t in trans_dist:
                    trans_dist[t] += 1

        # Constraints check
        tline = timeline_result.get("timeline", [])
        hook_entries = [e for e in tline if e.get("role") == "HOOK"]
        hook_is_highest = True
        if hook_entries and len(tline) > 1:
            hook_hs = hook_entries[0].get("hook_survival", 0)
            for e in tline:
                if e.get("role") != "HOOK" and e.get("hook_survival", 0) > hook_hs:
                    hook_is_highest = False
                    break

        escalation_entries = [e for e in tline if e.get("role") == "ESCALATION"]
        escalation_increasing = True
        esc_emo = [e.get("emotion_intensity", 0) for e in escalation_entries]
        for j in range(1, len(esc_emo)):
            if esc_emo[j] <= esc_emo[j - 1]:
                escalation_increasing = False
                break

        payoff_entries = [e for e in tline if e.get("role") == "PAYOFF"]
        payoff_has_highest_spike = True
        if payoff_entries and len(tline) > 1:
            payoff_max = max(e.get("spike_strength", 0) for e in payoff_entries)
            non_payoff_max = max(
                (e.get("spike_strength", 0) for e in tline if e.get("role") != "PAYOFF"),
                default=0,
            )
            if non_payoff_max > payoff_max:
                payoff_has_highest_spike = False

        all_above_threshold = all(
            (c.get("retention_score", 0) >= self.retention_threshold
             or c.get("hook_survival_score", 0) >= self.hook_survival_threshold)
            for c in selected
        )

        return {
            "selected_clips": selected,
            "rejected_clips": rejected,
            "selected_count": len(selected),
            "rejected_count": len(rejected),
            "narrative_structure": narrative,
            "assigned_segments": assigned,
            "timeline_result": timeline_result,
            "score_breakdown": score_breakdown,
            "transition_distribution": trans_dist,
            "constraints_check": {
                "hook_is_highest_survival": hook_is_highest,
                "escalation_emotion_increasing": escalation_increasing,
                "payoff_has_highest_spike": payoff_has_highest_spike,
                "all_clips_above_threshold": all_above_threshold,
            },
        }

    # -- 8. generate_report --------------------------------------------------

    def generate_report(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Generate timeline_decision_report."""
        ns = result["narrative_structure"]
        nseg = {}
        for seg_name in SEGMENT_ORDER:
            clip_list = result["assigned_segments"].get(seg_name, [])
            nseg[seg_name] = {
                "range": ns[seg_name]["range"],
                "clips": len(clip_list),
            }

        return {
            "version": "1.5.6",
            "engine": "timeline-decision-engine",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pipeline_insertion_point": (
                "after V1.5.5 retention-intelligence-engine, "
                "before renderer"
            ),
            "upstream": "V1.5.5 retention_ranked_clips",
            "downstream": "renderer / video composer",
            "total_input_clips": (
                result["selected_count"] + result["rejected_count"]
            ),
            "selected_clips": result["selected_count"],
            "rejected_clips": result["rejected_count"],
            "narrative_structure": nseg,
            "timeline_score": result["score_breakdown"]["timeline_score"],
            "timeline_score_breakdown": {
                "avg_retention": result["score_breakdown"]["avg_retention"],
                "narrative_flow": result["score_breakdown"]["narrative_flow"],
                "transition_smoothness": result["score_breakdown"][
                    "transition_smoothness"
                ],
                "hook_strength": result["score_breakdown"]["hook_strength"],
            },
            "execution_timeline": result["timeline_result"]["timeline"],
            "transition_distribution": result["transition_distribution"],
            "constraints_check": result["constraints_check"],
            "test_keywords": [
                "Shanghai Night Cyberpunk",
                "Street Food",
                "Crowd Reaction",
            ],
            "status": "success",
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import importlib.util

    _here = os.path.dirname(os.path.abspath(__file__))

    # Import ContentIntelligenceEngine from sibling module
    _cie_path = os.path.join(_here, "content-intelligence-engine.py")
    _spec_cie = importlib.util.spec_from_file_location(
        "content_intelligence_engine", _cie_path,
    )
    cie_mod = importlib.util.module_from_spec(_spec_cie)
    _spec_cie.loader.exec_module(cie_mod)
    ContentIntelligenceEngine = cie_mod.ContentIntelligenceEngine
    generate_mock_assets = cie_mod.generate_mock_assets

    # Import RetentionIntelligenceEngine from sibling module
    _rie_path = os.path.join(_here, "retention-intelligence-engine.py")
    _spec_rie = importlib.util.spec_from_file_location(
        "retention_intelligence_engine", _rie_path,
    )
    rie_mod = importlib.util.module_from_spec(_spec_rie)
    _spec_rie.loader.exec_module(rie_mod)
    RetentionIntelligenceEngine = rie_mod.RetentionIntelligenceEngine

    # 1. Simulate full pipeline
    print("[Timeline-Engine] Generating mock assets via V1.5.4 CIE ...")
    assets = generate_mock_assets(120)
    cie = ContentIntelligenceEngine()
    cie_scored = cie.score_batch(assets)
    cie_ranked = cie.rank(cie_scored, min_score=70)
    print(f"[Timeline-Engine] V1.5.4 produced {len(cie_ranked)} ranked clips "
          f"(from {len(assets)} assets).")

    print("[Timeline-Engine] Running V1.5.5 retention intelligence ...")
    engine_v5 = RetentionIntelligenceEngine()
    v5_scored = engine_v5.score_batch(cie_ranked)
    v5_result = engine_v5.rank_and_filter(v5_scored)
    retention_ranked = v5_result["filtered"]
    print(f"[Timeline-Engine] V1.5.5 produced {len(retention_ranked)} "
          f"retention-ranked clips.")

    # 2. Timeline decision
    print("[Timeline-Engine] Running timeline decision engine ...")
    tde = TimelineDecisionEngine(total_duration=30)
    result = tde.execute(retention_ranked)
    report = tde.generate_report(result)

    # 3. Output report
    out_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "output",
    )
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, "timeline_decision_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 4. Print summary
    print(f"\n{'='*60}")
    print(f"  Timeline Decision Engine — V{report['version']}")
    print(f"{'='*60}")
    print(f"  Selected clips:        {report['selected_clips']}")
    print(f"  Rejected clips:        {report['rejected_clips']}")
    print(f"  Timeline score:        {report['timeline_score']}")
    print(f"  Score breakdown:       {report['timeline_score_breakdown']}")
    print(f"  Transition dist:       {report['transition_distribution']}")
    print(f"  Constraints:           {report['constraints_check']}")
    print(f"  Status:                {report['status']}")
    print(f"{'='*60}")
    print(f"\n[Timeline-Engine] Report written → {report_path}")
