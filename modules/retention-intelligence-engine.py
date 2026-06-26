#!/usr/bin/env python3
"""
Retention Intelligence Engine — V1.5.5
---------------------------------------
Input:  V1.5.4 ranked_clips[] (scored by ContentIntelligenceEngine)
Output: retention_ranked_clips[] + retention_intelligence_report

Behaviour-prediction module: forecasts scroll-stop probability,
retention curves, viral spikes, and hook survival — all metadata-driven
(no pixel access, no external API).

Pipeline insertion point:
    after  V1.5.4 content-intelligence-engine
    before timeline compiler / asset pipeline
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

def clamp01(value: float) -> float:
    """Clamp to [0, 1]."""
    return max(0.0, min(1.0, value))


def clamp100(value: float) -> float:
    """Clamp to [0, 100]."""
    return max(0.0, min(100.0, value))


def clamp_generic(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# RetentionIntelligenceEngine
# ---------------------------------------------------------------------------

class RetentionIntelligenceEngine:
    """Metadata-driven behaviour prediction for short-video retention."""

    def __init__(self, seed: int = 77) -> None:
        self.rng = np.random.default_rng(seed)

    # ---- 1. scroll_stop_probability (0-1) ----------------------------------

    def compute_scroll_stop_probability(self, clip: Dict[str, Any]) -> float:
        """
        clamp(hook_score/100 * 0.6 + emotion_intensity/100 * 0.4
              + random(-0.05, +0.10), 0, 1)
        """
        hook = float(clip.get("hook_score", 50))
        emotion = float(clip.get("emotion_intensity", 50))
        jitter = self.rng.uniform(-0.05, 0.10)
        raw = (hook / 100.0) * 0.60 + (emotion / 100.0) * 0.40 + jitter
        return round(clamp01(raw), 4)

    # ---- 2. retention_curve (3-second) -------------------------------------

    def compute_retention_curve(self, clip: Dict[str, Any]) -> Dict[str, float]:
        """
        t0 = 1.0
        t1 = max(0.3, hook_score/100 * 0.85)
        t2 = max(0.15, t1 * 0.70)
        t3 = max(0.05, t2 * 0.60)
        """
        hook = float(clip.get("hook_score", 50))
        t1 = round(max(0.30, (hook / 100.0) * 0.85), 4)
        t2 = round(max(0.15, t1 * 0.70), 4)
        t3 = round(max(0.05, t2 * 0.60), 4)
        return {"t0": 1.0, "t1": t1, "t2": t2, "t3": t3}

    # ---- 3. viral spike detection ------------------------------------------

    def detect_viral_spikes(self, clip: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate 1-5 virtual spike points within clip duration.
        spike_strength = clamp(hook*0.5 + emotion*0.3 + viral*0.2, 0, 100)

        Number of spikes is proportional to content intensity:
          - high overall_score → more spikes
        """
        hook = float(clip.get("hook_score", 50))
        emotion = float(clip.get("emotion_intensity", 50))
        viral = float(clip.get("viral_probability", 50))
        overall = float(clip.get("overall_score", 50))
        duration = float(clip.get("duration", 30))

        # spike strength (global for this clip)
        spike_strength = round(clamp100(hook * 0.50 + emotion * 0.30 + viral * 0.20), 2)

        # number of spikes: 1-5, proportional to overall_score
        if overall >= 90:
            num_spikes = self.rng.integers(3, 6)   # 3-5
        elif overall >= 80:
            num_spikes = self.rng.integers(2, 5)   # 2-4
        elif overall >= 70:
            num_spikes = self.rng.integers(1, 4)   # 1-3
        else:
            num_spikes = self.rng.integers(1, 3)   # 1-2

        num_spikes = int(num_spikes)  # ensure int

        # distribute spike points across duration
        spike_types = [
            "emotion_peak",
            "scene_switch",
            "conflict_point",
            "tempo_shift",
            "highlight_moment",
        ]

        spikes = []
        for i in range(num_spikes):
            # virtual timestamp within [0, duration)
            t = round(self.rng.uniform(0.1, max(0.5, duration - 0.5)), 2)
            # individual spike magnitude (decaying across the clip)
            mag = round(spike_strength * (1.0 - i * 0.15), 2)
            mag = max(5.0, mag)
            spike_type = spike_types[i % len(spike_types)]
            spikes.append({
                "timestamp": t,
                "type": spike_type,
                "magnitude": mag,
            })

        return {
            "spike_strength": spike_strength,
            "spike_count": num_spikes,
            "spike_points": spikes,
        }

    # ---- 4. hook_survival_score (0-100) ------------------------------------

    def compute_hook_survival_score(self, clip: Dict[str, Any],
                                     spike_strength: float) -> float:
        """
        (hook_score * 0.40 + emotion_intensity * 0.25
         + spike_strength * 0.20 + first_3_seconds_score * 0.15)
        → clamped to 0-100
        """
        hook = float(clip.get("hook_score", 50))
        emotion = float(clip.get("emotion_intensity", 50))
        first3s = float(clip.get("first_3_seconds_score", 50))

        raw = (hook * 0.40
               + emotion * 0.25
               + spike_strength * 0.20
               + first3s * 0.15)
        return round(clamp100(raw), 2)

    # ---- 5. retention_score (0-100) ----------------------------------------

    def compute_retention_score(self, scroll_stop: float,
                                 hook_survival: float,
                                 spike_strength: float,
                                 editability: float) -> float:
        """
        (ScrollStop * 35) + (HookSurvival * 0.35)
        + (SpikeStrength * 0.20) + (EditabilityBoost * 0.10)

        ScrollStop is 0-1, multiplied by 35 → 0-35 contribution
        HookSurvival is 0-100, * 0.35 → 0-35
        SpikeStrength is 0-100, * 0.20 → 0-20
        Editability is 0-100, /100 * 10 → 0-10
        Total range: 0-100
        """
        edit_boost = (editability / 100.0) * 10.0
        score = (scroll_stop * 35.0
                 + hook_survival * 0.35
                 + spike_strength * 0.20
                 + edit_boost)
        return round(clamp100(score), 2)

    # ---- 6. score_clip — full pipeline for one clip ------------------------

    def score_clip(self, clip: Dict[str, Any]) -> Dict[str, Any]:
        """Complete retention scoring pipeline for a single clip."""
        scroll_stop = self.compute_scroll_stop_probability(clip)
        retention_curve = self.compute_retention_curve(clip)
        spike_data = self.detect_viral_spikes(clip)
        spike_strength = spike_data["spike_strength"]
        hook_survival = self.compute_hook_survival_score(clip, spike_strength)
        editability = float(clip.get("editability_score", 50))
        retention_score = self.compute_retention_score(
            scroll_stop, hook_survival, spike_strength, editability,
        )

        result = dict(clip)
        result.update({
            "scroll_stop_probability": scroll_stop,
            "retention_curve": retention_curve,
            "spike_strength": spike_strength,
            "spike_count": spike_data["spike_count"],
            "spike_points": spike_data["spike_points"],
            "hook_survival_score": hook_survival,
            "retention_score": retention_score,
        })
        return result

    # ---- 7. score_batch ----------------------------------------------------

    def score_batch(self, ranked_clips: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Batch retention scoring."""
        return [self.score_clip(c) for c in ranked_clips]

    # ---- 8. rank_and_filter ------------------------------------------------

    def rank_and_filter(self,
                        scored: List[Dict[str, Any]],
                        min_scroll_stop: float = 0.6,
                        min_hook_survival: float = 65.0) -> Dict[str, Any]:
        """
        Sort DESC by retention_score.
        Filter out clips below min_scroll_stop OR below min_hook_survival.
        Return top 25 (or fewer if not enough).
        """
        filtered = [
            c for c in scored
            if c["scroll_stop_probability"] >= min_scroll_stop
            and c["hook_survival_score"] >= min_hook_survival
        ]
        filtered.sort(key=lambda c: c["retention_score"], reverse=True)

        return {
            "all_scored": scored,
            "filtered": filtered,
            "filtered_count": len(filtered),
            "filtered_out": len(scored) - len(filtered),
        }

    # ---- 9. generate_report ------------------------------------------------

    def generate_report(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Generate retention_intelligence_report."""
        all_scored = result["all_scored"]
        filtered = result["filtered"]
        total_inputs = len(all_scored)
        after_filter = len(filtered)
        top_count = min(25, after_filter)
        top_clips = filtered[:min(20, after_filter)]

        # avg retention score (on filtered)
        if after_filter > 0:
            avg_ret = round(
                float(np.mean([c["retention_score"] for c in filtered])), 2,
            )
        else:
            avg_ret = 0.0

        # score distribution (on filtered)
        score_dist = {"90-100": 0, "80-89": 0, "70-79": 0, "below_70": 0}
        for c in filtered:
            s = c["retention_score"]
            if s >= 90:
                score_dist["90-100"] += 1
            elif s >= 80:
                score_dist["80-89"] += 1
            elif s >= 70:
                score_dist["70-79"] += 1
            else:
                score_dist["below_70"] += 1

        # scroll_stop distribution (on filtered)
        ss_dist = {"0.9-1.0": 0, "0.8-0.89": 0, "0.7-0.79": 0, "0.6-0.69": 0}
        for c in filtered:
            ss = c["scroll_stop_probability"]
            if ss >= 0.9:
                ss_dist["0.9-1.0"] += 1
            elif ss >= 0.8:
                ss_dist["0.8-0.89"] += 1
            elif ss >= 0.7:
                ss_dist["0.7-0.79"] += 1
            else:
                ss_dist["0.6-0.69"] += 1

        # hook_survival distribution (on filtered)
        hs_dist = {"90-100": 0, "80-89": 0, "70-79": 0, "65-69": 0}
        for c in filtered:
            hs = c["hook_survival_score"]
            if hs >= 90:
                hs_dist["90-100"] += 1
            elif hs >= 80:
                hs_dist["80-89"] += 1
            elif hs >= 70:
                hs_dist["70-79"] += 1
            else:
                hs_dist["65-69"] += 1

        # spike analysis
        spike_strengths = [c["spike_strength"] for c in filtered]
        spike_counts = [c["spike_count"] for c in filtered]
        clips_with_spikes = sum(1 for c in filtered if c["spike_count"] > 0)

        spike_analysis = {
            "avg_spike_strength": round(float(np.mean(spike_strengths)), 2)
                if spike_strengths else 0.0,
            "avg_spike_count": round(float(np.mean(spike_counts)), 2)
                if spike_counts else 0.0,
            "clips_with_spikes": clips_with_spikes,
        }

        return {
            "version": "1.5.5",
            "engine": "retention-intelligence-engine",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pipeline_insertion_point": (
                "after V1.5.4 content-intelligence-engine, "
                "before timeline compiler"
            ),
            "upstream": "V1.5.4 ranked_clips",
            "downstream": "timeline compiler / asset pipeline",
            "total_inputs": total_inputs,
            "after_filter": after_filter,
            "filtered_out": total_inputs - after_filter,
            "top_clips_count": top_count,
            "avg_retention_score": avg_ret,
            "score_distribution": score_dist,
            "scroll_stop_distribution": ss_dist,
            "hook_survival_distribution": hs_dist,
            "top_clips": top_clips,
            "spike_analysis": spike_analysis,
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
    # Import from sibling module (both in modules/) via file path
    import importlib.util

    _here = os.path.dirname(os.path.abspath(__file__))
    _cie_path = os.path.join(_here, "content-intelligence-engine.py")
    _spec = importlib.util.spec_from_file_location(
        "content_intelligence_engine", _cie_path,
    )
    cie = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(cie)
    ContentIntelligenceEngine = cie.ContentIntelligenceEngine
    generate_mock_assets = cie.generate_mock_assets

    # 1. Generate mock data simulating V1.5.4 output
    print("[Retention-Engine] Generating 120 mock assets via V1.5.4 CIE ...")
    assets = generate_mock_assets(120)
    cie = ContentIntelligenceEngine()
    scored = cie.score_batch(assets)
    ranked = cie.rank(scored, min_score=70)
    print(f"[Retention-Engine] V1.5.4 produced {len(ranked)} ranked clips "
          f"(filtered from {len(assets)}).")

    # 2. Retention scoring
    print("[Retention-Engine] Running retention intelligence pipeline ...")
    engine = RetentionIntelligenceEngine()
    retention_scored = engine.score_batch(ranked)
    result = engine.rank_and_filter(retention_scored)

    # 3. Generate report
    report = engine.generate_report(result)

    # 4. Write report to output/
    out_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "output",
    )
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, "retention_intelligence_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 5. Print summary
    print(f"\n{'='*60}")
    print(f"  Retention Intelligence Engine — V{report['version']}")
    print(f"{'='*60}")
    print(f"  Total inputs:          {report['total_inputs']}")
    print(f"  After filter:          {report['after_filter']}")
    print(f"  Filtered out:          {report['filtered_out']}")
    print(f"  Top clips (max 25):    {report['top_clips_count']}")
    print(f"  Avg retention score:   {report['avg_retention_score']}")
    print(f"  Status:                {report['status']}")
    print(f"{'='*60}")
    print(f"  Score distribution:    {report['score_distribution']}")
    print(f"  Scroll-stop dist:      {report['scroll_stop_distribution']}")
    print(f"  Hook-survival dist:    {report['hook_survival_distribution']}")
    print(f"  Spike analysis:        {report['spike_analysis']}")
    print(f"{'='*60}")
    print(f"\n[Retention-Engine] Report written → {report_path}")
