#!/usr/bin/env python3
"""
Content Validation Gate — V1.6
-------------------------------
All harvested assets must pass validation before entering the pipeline.
Checks: playable, resolution, duration, corruption, downloadable, watermark.
"""

from typing import Any, Dict, List, Tuple


class ContentValidationGate:
    """Quality gate for content assets before pipeline ingestion."""

    MIN_RESOLUTION: Tuple[int, int] = (1080, 1920)
    MIN_DURATION: float = 3.0
    BLOCKED_WATERMARKS: List[str] = [
        "douyin_logo_overlay",
        "kuaishou_mark",
        "miaopai_badge",
    ]

    # Scoring weights for each check
    CHECK_WEIGHTS: Dict[str, float] = {
        "playable": 0.25,
        "resolution": 0.20,
        "duration": 0.15,
        "corruption": 0.20,
        "downloadable": 0.10,
        "watermark": 0.10,
    }

    def __init__(self):
        self.valid_count: int = 0
        self.rejected_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, asset: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a single asset.

        Returns:
            {"valid": bool, "score": int, "reasons": [str], "checks": {...}}
        """
        checks: Dict[str, bool] = {}
        reasons: List[str] = []

        # Run all checks
        checks["playable"] = self._check_playable(asset)
        checks["resolution"] = self._check_resolution(asset)
        checks["duration"] = self._check_duration(asset)
        checks["corruption"] = self._check_corruption(asset)
        checks["downloadable"] = self._check_downloadable(asset)
        checks["watermark"] = self._check_watermark(asset)

        # Build reasons
        if not checks["playable"]:
            reasons.append("not_playable")
        if not checks["resolution"]:
            reasons.append("resolution_below_minimum")
        if not checks["duration"]:
            reasons.append("duration_too_short")
        if not checks["corruption"]:
            reasons.append("file_corrupted")
        if not checks["downloadable"]:
            reasons.append("not_downloadable")
        if not checks["watermark"]:
            reasons.append("blocked_watermark")

        all_passed = all(checks.values())

        # Weighted score
        score = 0
        if all_passed:
            score = 100
        else:
            for check_name, weight in self.CHECK_WEIGHTS.items():
                if checks.get(check_name, False):
                    score += int(weight * 100)

        # Track stats
        if all_passed:
            self.valid_count += 1
        else:
            self.rejected_count += 1

        return {
            "valid": all_passed,
            "score": score,
            "reasons": reasons,
            "checks": checks,
        }

    def validate_batch(
        self, assets: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Batch validate and split into valid/rejected.

        Returns:
            {"valid": [...], "rejected": [...], "stats": {...}}
        """
        valid: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []

        for asset in assets:
            result = self.validate(asset)
            if result["valid"]:
                valid.append({"asset": asset, "score": result["score"]})
            else:
                rejected.append(
                    {
                        "asset": asset,
                        "score": result["score"],
                        "reasons": result["reasons"],
                    }
                )

        return {
            "valid": valid,
            "rejected": rejected,
            "stats": {
                "total": len(assets),
                "valid": len(valid),
                "rejected": len(rejected),
                "pass_rate": (
                    round(len(valid) / len(assets), 3) if assets else 0.0
                ),
            },
        }

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_playable(self, asset: Dict[str, Any]) -> bool:
        """Asset URL or path exists and is accessible."""
        url = asset.get("url", "")
        filepath = asset.get("filepath", "")
        return bool(url) or bool(filepath)

    def _check_resolution(self, asset: Dict[str, Any]) -> bool:
        """Resolution meets minimum threshold."""
        res_str = asset.get("resolution", "")
        if not res_str:
            return True  # Can't verify, pass through

        try:
            parts = res_str.lower().replace("x", " ").split()
            w = int(parts[0])
            return w >= self.MIN_RESOLUTION[0]
        except (ValueError, IndexError):
            return True  # Unparseable, pass through

    def _check_duration(self, asset: Dict[str, Any]) -> bool:
        """Duration meets minimum threshold."""
        duration = asset.get("duration", 0)
        if isinstance(duration, (int, float)):
            return float(duration) >= self.MIN_DURATION
        return True  # Unknown, pass through

    def _check_corruption(self, asset: Dict[str, Any]) -> bool:
        """Check for file corruption markers."""
        # Check metadata for corruption flags
        if asset.get("corrupted", False):
            return False
        if asset.get("status") == "corrupted":
            return False
        # Check file size if explicitly provided as 0 (absent = unknown, pass)
        has_size = "size" in asset or "file_size" in asset
        if has_size:
            size = asset.get("size", asset.get("file_size", -1))
            if isinstance(size, (int, float)) and size == 0:
                return False
        return True

    def _check_downloadable(self, asset: Dict[str, Any]) -> bool:
        """Asset can be downloaded."""
        # If already has local filepath, considered downloadable
        if asset.get("filepath"):
            return True
        # If URL is present and no explicit block
        url = asset.get("url", "")
        if url and not asset.get("download_blocked", False):
            return True
        # Explicit downloadable flag
        if asset.get("downloadable", False):
            return True
        return bool(url)

    def _check_watermark(self, asset: Dict[str, Any]) -> bool:
        """Asset has no blocked watermark."""
        watermark = asset.get("watermark", "")
        if watermark in self.BLOCKED_WATERMARKS:
            return False
        watermark_score = asset.get("watermark_score", 0)
        if isinstance(watermark_score, (int, float)) and watermark_score > 30:
            return False
        return True

    def get_stats(self) -> Dict[str, int]:
        """Return accumulated validation statistics."""
        return {
            "valid_count": self.valid_count,
            "rejected_count": self.rejected_count,
            "total": self.valid_count + self.rejected_count,
        }
