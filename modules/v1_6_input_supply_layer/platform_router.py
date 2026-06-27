#!/usr/bin/env python3
"""
Platform Router — V1.6
-----------------------
Routes content queries to optimal platforms based on content type
and trend score. Returns priority-ordered platform list.
"""

from typing import Any, Dict, List, Tuple


class PlatformRouter:
    """Decide which social platforms to query for a given content type."""

    ROUTE_TABLE: Dict[str, List[str]] = {
        "city_night": ["bilibili", "xiaohongshu", "weibo"],
        "street_food": ["bilibili", "xiaohongshu", "douyin"],
        "product_review": ["bilibili", "xiaohongshu", "douyin"],
        "hot_trend": ["weibo", "bilibili", "douyin"],
        "travel_vlog": ["xiaohongshu", "bilibili"],
        "nightlife": ["bilibili", "xiaohongshu", "weibo"],
        "architecture": ["xiaohongshu", "bilibili"],
    }

    PLATFORM_CONFIG: Dict[str, Dict[str, Any]] = {
        "douyin": {
            "preferred_resolution": "1080x1920",
            "max_duration": 60,
            "content_type": "short_video",
        },
        "xiaohongshu": {
            "preferred_resolution": "1080x1440",
            "max_duration": 300,
            "content_type": "image_video_mix",
        },
        "bilibili": {
            "preferred_resolution": "1920x1080",
            "max_duration": 600,
            "content_type": "long_video",
        },
        "weibo": {
            "preferred_resolution": "1080x1920",
            "max_duration": 180,
            "content_type": "short_video",
        },
    }

    DEFAULT_ROUTE: List[str] = ["douyin", "xiaohongshu", "bilibili", "weibo"]

    def route(
        self, video_type: str, topic: str = "", trend_score: float = 0.0
    ) -> List[Tuple[str, float]]:
        """Return priority-ordered platform list with weights.

        Args:
            video_type: content category (e.g. 'city_night', 'street_food')
            topic: specific search topic (used for fine-tuning)
            trend_score: viral trend score 0-100, higher = prefer hot platforms

        Returns:
            List of (platform_name, priority_weight) sorted descending
        """
        platforms = self.ROUTE_TABLE.get(video_type, self.DEFAULT_ROUTE)

        result: List[Tuple[str, float]] = []
        n = len(platforms)
        for idx, platform in enumerate(platforms):
            weight = float(n - idx) / float(n)  # descending weights

            # Boost weibo for high trend score
            if trend_score > 70 and platform == "weibo":
                weight *= 1.3

            # Boost xiaohongshu for travel/architecture topics
            if "travel" in topic.lower() or "vlog" in topic.lower():
                if platform == "xiaohongshu":
                    weight *= 1.2

            result.append((platform, round(weight, 2)))

        result.sort(key=lambda x: x[1], reverse=True)
        return result

    def get_platform_config(self, platform: str) -> Dict[str, Any]:
        """Return platform-specific configuration."""
        return self.PLATFORM_CONFIG.get(platform, {}).copy()

    def get_resolution_constraints(
        self, platform: str
    ) -> Tuple[str, str]:
        """Return (width, height) string tuple for the platform."""
        cfg = self.PLATFORM_CONFIG.get(platform, {})
        res = cfg.get("preferred_resolution", "1080x1920")
        parts = res.split("x")
        return (parts[0], parts[1])

    def all_platforms(self) -> List[str]:
        """Return list of all supported platforms."""
        return list(self.PLATFORM_CONFIG.keys())
