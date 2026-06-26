#!/usr/bin/env python3
"""
Content Intelligence Engine — V1.5.4
-------------------------------------
Input:  asset_v3[] (list of dicts)
Output: ranked_clips[] + intelligence_report

Scoring dimensions (6, each 0-100):
  1. hook_score          — first 3 seconds impact
  2. emotion_intensity   — scene complexity / dynamics
  3. viral_probability   — weighted composite of hook, emotion, retention_est, novelty
  4. first_3_seconds_score — retention estimate
  5. editability_score   — resolution / fps / codec / duration
  6. platform_fit        — douyin / tiktok / youtube_shorts suitability

overall_score = hook*0.30 + emotion*0.20 + viral*0.25 + first3s*0.10 + editability*0.15

All scoring is metadata-driven (heuristic), no external API, no pixel access.
"""

import json
import math
import os
import random
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RANK_WEIGHTS = {
    "hook": 0.30,
    "emotion": 0.20,
    "viral": 0.25,
    "first3s": 0.10,
    "editability": 0.15,
}

PLATFORM_PRESETS: Dict[str, Dict[str, Any]] = {
    "douyin":         {"hook_bias": 1.15, "emotion_bias": 1.10, "preferred_duration": 30, "aspect": "9:16"},
    "tiktok":         {"hook_bias": 1.15, "emotion_bias": 1.10, "preferred_duration": 30, "aspect": "9:16"},
    "youtube_shorts": {"hook_bias": 1.00, "emotion_bias": 0.95, "preferred_duration": 60, "aspect": "16:9"},
    "bilibili":       {"hook_bias": 1.10, "emotion_bias": 1.05, "preferred_duration": 120, "aspect": "16:9"},
    "xiaohongshu":    {"hook_bias": 0.95, "emotion_bias": 0.90, "preferred_duration": 60, "aspect": "3:4"},
    "weibo":          {"hook_bias": 0.90, "emotion_bias": 0.95, "preferred_duration": 60, "aspect": "16:9"},
}

COMMON_CODECS = {"h264", "h265", "hevc", "vp9", "av1", "prores"}
HIGH_QUALITY_CODECS = {"h265", "hevc", "vp9", "av1", "prores"}


# ---------------------------------------------------------------------------
# Helper: clamp & rescale
# ---------------------------------------------------------------------------

def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def rescale(value: float, in_low: float, in_high: float, out_low: float = 0.0, out_high: float = 100.0) -> float:
    if math.isclose(in_high, in_low):
        return out_low
    ratio = (value - in_low) / (in_high - in_low)
    return clamp(out_low + ratio * (out_high - out_low))


# ---------------------------------------------------------------------------
# ContentIntelligenceEngine
# ---------------------------------------------------------------------------

class ContentIntelligenceEngine:
    """Metadata-driven content quality scorer for short-video assets."""

    def __init__(self, seed: int = 42) -> None:
        self.rng = np.random.default_rng(seed)

    # ---- dimension 1: hook_score (0-100) -----------------------------------

    def _hook_score(self, asset: Dict[str, Any]) -> float:
        """
        Based on duration, platform hook_bias, trend_score.
        Shorter clips get higher hook potential; high trend_score lifts hook.
        """
        platform = str(asset.get("source_platform", "")).lower()
        duration = float(asset.get("duration", 30))
        trend = float(asset.get("trend_score", 50))

        preset = PLATFORM_PRESETS.get(platform, {"hook_bias": 1.0})

        # shorter → higher base
        if duration <= 15:
            base = 80
        elif duration <= 30:
            base = 70
        elif duration <= 60:
            base = 55
        elif duration <= 120:
            base = 40
        else:
            base = 25

        # trend boost
        trend_boost = (trend - 50) * 0.30
        # platform bias
        platform_boost = (preset["hook_bias"] - 1.0) * 60
        # small jitter
        noise = self.rng.uniform(-5, 5)

        return clamp(base + trend_boost + platform_boost + noise)

    # ---- dimension 2: emotion_intensity (0-100) ----------------------------

    def _emotion_intensity(self, asset: Dict[str, Any]) -> float:
        """
        Inverse watermark_score (cleaner = more native = higher emotion),
        plus trend_score boost and platform emotion bias.
        """
        platform = str(asset.get("source_platform", "")).lower()
        watermark = float(asset.get("watermark_score", 50))
        trend = float(asset.get("trend_score", 50))

        preset = PLATFORM_PRESETS.get(platform, {"emotion_bias": 1.0})

        # lower watermark → more organic → higher emotion baseline
        base = 100 - watermark * 0.6
        trend_boost = (trend - 50) * 0.25
        platform_boost = (preset["emotion_bias"] - 1.0) * 50
        noise = self.rng.uniform(-6, 6)

        return clamp(base + trend_boost + platform_boost + noise)

    # ---- dimension 3: viral_probability (0-100) ----------------------------

    def _viral_probability(self, asset: Dict[str, Any],
                           hook: float, emotion: float) -> float:
        """
        viral = hook*0.40 + emotion*0.25 + retention_est*0.20 + novelty*0.15
        retention_est proxied by trend_score.
        novelty randomized 50-90 (no content understanding available).
        """
        trend = float(asset.get("trend_score", 50))
        retention_est = trend  # proxy
        novelty = self.rng.uniform(50, 90)

        viral = (hook * 0.40
                 + emotion * 0.25
                 + retention_est * 0.20
                 + novelty * 0.15)
        return clamp(viral)

    # ---- dimension 4: first_3_seconds_score (0-100) ------------------------

    def _first_3_seconds_score(self, hook: float) -> float:
        """Highly correlated with hook_score + small jitter."""
        noise = self.rng.uniform(-10, 10)
        return clamp(hook * 0.85 + noise)

    # ---- dimension 5: editability_score (0-100) ----------------------------

    def _editability_score(self, asset: Dict[str, Any]) -> float:
        """
        Based on resolution, fps, codec, duration.
        Standard res + 60fps + common codec + reasonable duration = high.
        """
        resolution = str(asset.get("resolution", "1920x1080")).lower()
        fps = float(asset.get("fps", 30))
        codec = str(asset.get("codec", "h264")).lower()
        duration = float(asset.get("duration", 30))

        score = 50.0

        # resolution
        try:
            w, h = map(int, resolution.split("x"))
            pixels = w * h
            if pixels >= 3840 * 2160:
                score += 15
            elif pixels >= 1920 * 1080:
                score += 10
            elif pixels >= 1280 * 720:
                score += 5
            elif pixels >= 720 * 480:
                score += 0
            else:
                score -= 10
        except (ValueError, AttributeError):
            score += 5  # unknown → assume HD

        # fps
        if fps >= 60:
            score += 15
        elif fps >= 30:
            score += 10
        elif fps >= 24:
            score += 5
        else:
            score -= 5

        # codec (editable if common)
        if codec in HIGH_QUALITY_CODECS:
            score += 5
        elif codec in COMMON_CODECS:
            score += 0
        else:
            score -= 5

        # duration reasonableness
        if 5 <= duration <= 120:
            score += 5
        elif duration < 5:
            score -= 5
        else:
            score -= 3

        return clamp(score)

    # ---- dimension 6: platform_fit (0-100) ---------------------------------

    def _platform_fit(self, asset: Dict[str, Any], hook: float,
                      editability: float) -> float:
        """
        Platform-specific suitability:
        - douyin/tiktok: short (<30s) + vertical + high hook
        - youtube_shorts: <60s + 16:9 or 1:1 + high editability
        - bilibili: medium duration + balanced
        - xiaohongshu: 3:4 + medium
        - weibo: broad
        """
        platform = str(asset.get("source_platform", "")).lower()
        duration = float(asset.get("duration", 30))
        resolution = str(asset.get("resolution", "1920x1080")).lower()

        preset = PLATFORM_PRESETS.get(platform, {"preferred_duration": 60, "aspect": "16:9"})
        preferred_dur = float(preset.get("preferred_duration", 60))
        aspect = preset.get("aspect", "16:9")

        base = 60.0

        # duration fit
        if duration <= preferred_dur * 0.5:
            base += 20
        elif duration <= preferred_dur:
            base += 10
        elif duration <= preferred_dur * 2:
            base += 0
        else:
            base -= 15

        # aspect ratio fit
        try:
            w, h = map(int, resolution.split("x"))
            ratio = w / h if h != 0 else 1.0
            if aspect == "9:16":
                if ratio < 0.7:
                    base += 10
                elif ratio < 1.2:
                    base += 0
                else:
                    base -= 10
            elif aspect == "16:9":
                if ratio > 1.5:
                    base += 10
                elif ratio > 1.0:
                    base += 5
                else:
                    base -= 5
            elif aspect == "3:4":
                if 0.7 <= ratio <= 0.85:
                    base += 10
                elif 0.6 <= ratio <= 1.0:
                    base += 0
                else:
                    base -= 10
            else:
                base += 5  # unknown aspect → neutral
        except (ValueError, AttributeError):
            base += 5

        # hook boost for short-video platforms
        if platform in ("douyin", "tiktok"):
            base += (hook - 50) * 0.25
        elif platform == "youtube_shorts":
            base += (editability - 50) * 0.20

        return clamp(base)

    # ---- overall score -----------------------------------------------------

    def _overall_score(self, dims: Dict[str, float]) -> float:
        return (
            dims["hook_score"] * RANK_WEIGHTS["hook"]
            + dims["emotion_intensity"] * RANK_WEIGHTS["emotion"]
            + dims["viral_probability"] * RANK_WEIGHTS["viral"]
            + dims["first_3_seconds_score"] * RANK_WEIGHTS["first3s"]
            + dims["editability_score"] * RANK_WEIGHTS["editability"]
        )

    # ---- public API --------------------------------------------------------

    def score_asset(self, asset: Dict[str, Any]) -> Dict[str, Any]:
        """Score a single asset and return asset with scores merged."""
        hook = self._hook_score(asset)
        emotion = self._emotion_intensity(asset)
        viral = self._viral_probability(asset, hook, emotion)
        first3s = self._first_3_seconds_score(hook)
        editability = self._editability_score(asset)
        platform_fit = self._platform_fit(asset, hook, editability)

        dims = {
            "hook_score": round(hook, 2),
            "emotion_intensity": round(emotion, 2),
            "viral_probability": round(viral, 2),
            "first_3_seconds_score": round(first3s, 2),
            "editability_score": round(editability, 2),
            "platform_fit": round(platform_fit, 2),
        }
        overall = round(self._overall_score(dims), 2)

        result = dict(asset)
        result.update(dims)
        result["overall_score"] = overall
        return result

    def score_batch(self, assets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Batch-score all assets."""
        return [self.score_asset(a) for a in assets]

    def rank(self, scored: List[Dict[str, Any]],
             min_score: float = 70) -> List[Dict[str, Any]]:
        """Sort descending by overall_score, filter below min_score."""
        qualified = [a for a in scored if a["overall_score"] >= min_score]
        qualified.sort(key=lambda a: a["overall_score"], reverse=True)
        return qualified

    def generate_report(self, ranked: List[Dict[str, Any]],
                        total: int) -> Dict[str, Any]:
        """Generate summary report dict."""
        rejected = total - len(ranked)

        # score distribution
        distribution = {"90-100": 0, "80-89": 0, "70-79": 0, "below_70": 0}
        for a in ranked:
            s = a["overall_score"]
            if s >= 90:
                distribution["90-100"] += 1
            elif s >= 80:
                distribution["80-89"] += 1
            else:
                distribution["70-79"] += 1
        distribution["below_70"] = rejected

        # platform breakdown
        pb: Dict[str, Dict[str, Any]] = {}
        for a in ranked:
            plat = a.get("source_platform", "unknown")
            pb.setdefault(plat, {"scores": [], "total": 0})
            pb[plat]["scores"].append(a["overall_score"])
            pb[plat]["total"] += 1

        platform_breakdown: Dict[str, Dict[str, Any]] = {}
        # include all 4 platforms even if some have 0 qualified
        for plat in ["douyin", "bilibili", "xiaohongshu", "weibo"]:
            entry = pb.get(plat, {"scores": [], "total": 0})
            scores = entry["scores"]
            platform_breakdown[plat] = {
                "total": entry["total"],
                "qualified": len(scores),
                "avg_score": round(float(np.mean(scores)), 2) if scores else 0.0,
            }

        return {
            "version": "1.5.4",
            "engine": "content-intelligence-engine",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pipeline_insertion_point": "after asset_v3 normalization, before timeline compiler",
            "total_assets": total,
            "qualified_assets": len(ranked),
            "rejected_assets": rejected,
            "score_distribution": distribution,
            "top_assets": ranked[:20],
            "platform_breakdown": platform_breakdown,
            "test_keywords": ["Shanghai Night", "Cyberpunk City", "Street Food Clips"],
            "status": "success",
        }


# ---------------------------------------------------------------------------
# Mock data generator
# ---------------------------------------------------------------------------

def generate_mock_assets(count: int = 120) -> List[Dict[str, Any]]:
    """Generate mock asset_v3 entries covering 4 platforms."""
    rng = np.random.default_rng(12345)

    platforms = ["douyin", "bilibili", "xiaohongshu", "weibo"]
    resolutions = ["1080x1920", "1920x1080", "720x1280", "1280x720",
                   "1080x1440", "2160x3840", "640x360", "480x854"]
    codecs = ["h264", "h265", "vp9", "av1", "prores"]
    fps_values = [24, 30, 60, 120]

    # platform-specific resolution weights to ensure mixed quality
    platform_res_weights = {
        "douyin":      [0.50, 0.10, 0.20, 0.05, 0.10, 0.03, 0.01, 0.01],
        "bilibili":    [0.05, 0.50, 0.05, 0.10, 0.05, 0.20, 0.01, 0.04],
        "xiaohongshu": [0.05, 0.05, 0.10, 0.05, 0.50, 0.05, 0.05, 0.15],
        "weibo":       [0.15, 0.30, 0.15, 0.15, 0.05, 0.10, 0.05, 0.05],
    }

    def pick_weighted(options, weights):
        return options[rng.choice(len(options), p=weights)]

    assets = []
    for i in range(count):
        platform = platforms[i % len(platforms)]
        res_weights = platform_res_weights[platform]
        resolution = pick_weighted(resolutions, res_weights)

        # ensure mix of quality
        if i < 20:  # high quality
            trend = rng.uniform(70, 95)
            watermark = rng.uniform(5, 25)
            duration = rng.uniform(8, 30)
            fps = 60
            codec = rng.choice(["h265", "vp9", "av1"])
        elif i < 60:  # medium
            trend = rng.uniform(40, 75)
            watermark = rng.uniform(20, 50)
            duration = rng.uniform(15, 90)
            fps = rng.choice([30, 60])
            codec = rng.choice(["h264", "h265"])
        else:  # low quality — some should fall below 70
            trend = rng.uniform(10, 50)
            watermark = rng.uniform(40, 90)
            duration = rng.uniform(60, 300)
            fps = rng.choice([24, 30])
            codec = rng.choice(["h264", "unknown"])

        asset = {
            "asset_id": f"asset_v3_{i:04d}",
            "source_platform": platform,
            "title": f"Mock Clip {i:04d} — {rng.choice(['Cooking', 'Dance', 'Tech Review', 'Travel', 'Comedy', 'Fitness', 'Music', 'Pets'])}",
            "url": f"https://{platform}.com/video/mock_{i:04d}",
            "duration": float(round(duration, 1)),
            "resolution": str(resolution),
            "fps": int(fps),
            "codec": str(codec),
            "watermark_score": float(round(watermark, 1)),
            "trend_score": float(round(trend, 1)),
            "file_size_bytes": int(rng.integers(5_000_000, 200_000_000)),
            "bitrate_kbps": int(rng.integers(500, 15_000)),
            "has_audio": bool(rng.choice([True, False], p=[0.9, 0.1])),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        assets.append(asset)

    return assets


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_intelligence(assets: List[Dict[str, Any]],
                     min_score: float = 70) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Main entry: score → rank → report."""
    engine = ContentIntelligenceEngine()
    scored = engine.score_batch(assets)
    ranked = engine.rank(scored, min_score=min_score)
    report = engine.generate_report(ranked, len(assets))
    return ranked, report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1:
        input_path = sys.argv[1]
        with open(input_path, "r", encoding="utf-8") as f:
            assets = json.load(f)
    else:
        print("[CI-Engine] No input file provided — generating 120 mock assets for test.")
        assets = generate_mock_assets(120)

    ranked, report = run_intelligence(assets)

    # print summary to stdout
    print(json.dumps({
        "ranked_count": len(ranked),
        "top_5_overall": [a["overall_score"] for a in ranked[:5]],
        "report": report,
    }, ensure_ascii=False, indent=2))

    # write report to output/
    out_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "output",
    )
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, "content_intelligence_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n[CI-Engine] Report written → {report_path}")
    print(f"[CI-Engine] Qualified: {report['qualified_assets']} / {report['total_assets']}")
    print(f"[CI-Engine] Rejected:  {report['rejected_assets']}")
