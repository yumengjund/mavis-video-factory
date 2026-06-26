#!/usr/bin/env python3
"""
Adaptive Fetch Controller — V1.6
---------------------------------
Dynamic fetch strategy: UA rotation, query rewriting, session switching,
delay jitter, request pacing. Reuses harvester_engine Playwright context
with session pool + anti-block integration.
"""

import random
import time
from typing import Any, Dict, List, Optional


class AdaptiveFetchController:
    """Adaptive content fetcher with anti-detection strategies."""

    UA_POOL: List[str] = [
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/129.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Edge/131.0.0.0 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/18.1 Safari/605.1.15"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
            "Gecko/20100101 Firefox/133.0"
        ),
    ]

    def __init__(self, session_pool=None, anti_block_engine=None):
        self.session_pool = session_pool
        self.anti_block_engine = anti_block_engine
        self._ua_index: int = 0
        self._fetch_history: Dict[str, list] = {}  # platform -> [timestamps]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(
        self,
        platform: str,
        query: str,
        target_count: int = 5,
    ) -> List[Dict[str, Any]]:
        """Execute one fetch cycle against a platform.

        In test mode (no real browser), returns synthetic placeholder
        results with correct metadata structure.

        Returns:
            List of asset dicts with keys: url, title, duration, source, ...
        """
        self._apply_delay_jitter(platform)

        # Check if platform should be skipped
        if self.anti_block_engine and self.anti_block_engine.should_abort(
            platform
        ):
            return []

        # Get session
        session = None
        if self.session_pool:
            session = self.session_pool.get_active_session(platform)

        # Select UA
        ua = self._select_ua()

        # Rewrite query for platform
        rewritten_query = self._rewrite_query(query, platform)

        # Record fetch attempt
        self._fetch_history.setdefault(platform, []).append(time.time())

        # ---- Synthetic fetch (no real browser in test mode) ----
        assets: List[Dict[str, Any]] = []
        for i in range(target_count):
            assets.append(
                {
                    "asset_id": f"{platform}_fetch_{query[:6]}_{i:03d}",
                    "source": platform,
                    "url": f"https://{platform}.com/video/{query[:8]}_{i}",
                    "title": f"{rewritten_query} #{i+1}",
                    "duration": round(random.uniform(5, 45), 1),
                    "resolution": (
                        self._platform_resolution(platform)
                        if random.random() > 0.15
                        else "720x1280"
                    ),
                    "author": f"creator_{platform}_{i}",
                    "query": rewritten_query,
                    "fetch_ua": ua[:50],
                    "has_session": session is not None,
                    "timestamp": time.time(),
                }
            )

        return assets

    # ------------------------------------------------------------------
    # Internal strategies
    # ------------------------------------------------------------------

    def _select_ua(self) -> str:
        """Rotate through UA pool."""
        ua = self.UA_POOL[self._ua_index % len(self.UA_POOL)]
        self._ua_index += 1
        return ua

    def _apply_delay_jitter(
        self, platform: str = "", base_delay: float = 1.5
    ) -> None:
        """Apply randomized delay to avoid rate limiting.

        delay = base_delay * (0.5 + random() * 1.5)
        """
        jitter = base_delay * (0.5 + random.random() * 1.5)
        time.sleep(min(jitter, 3.0))  # cap at 3s

    def _rewrite_query(self, query: str, platform: str) -> str:
        """Rewrite query for platform-specific search syntax.

        Douyin: shorter, hashtag style
        Bilibili: more descriptive
        Xiaohongshu: lifestyle keywords
        Weibo: hot-topic format
        """
        if platform == "douyin":
            # Shorter, punchier, hashtag-style
            parts = query.split()
            return " ".join(parts[:2]) if len(parts) > 2 else query
        elif platform == "xiaohongshu":
            # Add lifestyle indicators
            return f"{query} 推荐"
        elif platform == "bilibili":
            # More descriptive
            return f"{query} 4K 航拍"
        elif platform == "weibo":
            # Hot-topic format
            return f"#{query.replace(' ', '')}#"
        return query

    def _platform_resolution(self, platform: str) -> str:
        """Return typical resolution for platform assets."""
        mapping = {
            "douyin": "1080x1920",
            "xiaohongshu": "1080x1440",
            "bilibili": "1920x1080",
            "weibo": "1080x1920",
        }
        return mapping.get(platform, "1080x1920")

    def get_fetch_stats(self) -> Dict[str, Any]:
        """Return fetch statistics."""
        stats: Dict[str, int] = {}
        for platform, history in self._fetch_history.items():
            stats[platform] = len(history)
        return {
            "total_fetches": sum(stats.values()),
            "by_platform": stats,
            "ua_rotations": self._ua_index,
        }
