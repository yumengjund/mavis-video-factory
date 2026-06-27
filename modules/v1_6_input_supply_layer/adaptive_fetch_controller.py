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

    def __init__(self, session_pool=None, anti_block_engine=None, test_mode=True):
        self.session_pool = session_pool
        self.anti_block_engine = anti_block_engine
        self.test_mode = test_mode
        self._ua_index: int = 0
        self._fetch_history: Dict[str, list] = {}  # platform -> [timestamps]
        self._browser = None
        self._adapters = {}


    def _ensure_browser(self):
        """Lazy-init Playwright browser for real fetching."""
        if self._browser is None:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
            from modules.harvester_engine.browser_core import BrowserCore
            self._browser = BrowserCore(headless=True)

    def _get_adapter(self, platform: str):
        """Lazy-load platform adapter."""
        if platform not in self._adapters:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
            if platform == "bilibili":
                from modules.harvester_engine.bilibili_adapter import BilibiliAdapter
                self._adapters[platform] = BilibiliAdapter()
            elif platform == "douyin":
                from modules.harvester_engine.douyin_adapter import DouyinAdapter
                self._adapters[platform] = DouyinAdapter()
            elif platform == "xiaohongshu":
                from modules.harvester_engine.xiaohongshu_adapter import XiaohongshuAdapter
                self._adapters[platform] = XiaohongshuAdapter()
            elif platform == "weibo":
                from modules.harvester_engine.weibo_adapter import WeiboAdapter
                self._adapters[platform] = WeiboAdapter()
            else:
                return None
        return self._adapters[platform]

    def close(self):
        """Clean up browser resources."""
        if self._browser:
            self._browser.close()
            self._browser = None

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

        # ---- Real or Synthetic fetch ----
        if self.test_mode:
            return self._synthetic_fetch(
                platform, query, rewritten_query, target_count, ua, session
            )
        else:
            return self._real_fetch(
                platform, query, rewritten_query, target_count, ua, session
            )

    def _synthetic_fetch(self, platform, query, rewritten_query,
                         target_count, ua, session):
        """Generate fake assets for testing."""
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

    def _real_fetch(self, platform, query, rewritten_query,
                    target_count, ua, session):
        """Fetch real video URLs via Playwright + platform adapters.

        For B站: two-step flow: search page → BV links → video pages → stream URLs.
        For other platforms: use adapter's search+extract.
        """
        assets: List[Dict[str, Any]] = []

        if platform == "bilibili":
            return self._real_fetch_bilibili(
                rewritten_query, target_count, ua, session
            )

        self._ensure_browser()

        # Generic flow for other platforms
        adapter = self._get_adapter(platform)
        if adapter is None:
            print(f"[Fetch] No adapter for platform: {platform}")
            return assets

        try:
            page = self._browser.new_page()
            try:
                adapter.search(page, rewritten_query, max_scroll=2)
                urls = adapter.extract(page, limit=target_count)
                for i, url in enumerate(urls):
                    if not url or not url.startswith("http"):
                        continue
                    assets.append({
                        "asset_id": f"{platform}_real_{i:03d}_{int(time.time())}",
                        "source": platform,
                        "url": url,
                        "title": f"{rewritten_query} #{i+1}",
                        "duration": 0,
                        "resolution": self._platform_resolution(platform),
                        "author": "",
                        "query": rewritten_query,
                        "fetch_ua": ua[:50],
                        "has_session": session is not None,
                        "timestamp": time.time(),
                    })
            finally:
                page.close()
        except Exception as e:
            print(f"[Fetch] Real fetch failed for {platform}: {e}")

        return assets

    def _real_fetch_bilibili(self, query, target_count, ua, session):
        """B站专用采集：REST API 搜索 → 获取视频播放地址."""
        assets: List[Dict[str, Any]] = []
        urls = self._bilibili_api_search(query, target_count)
        for i, info in enumerate(urls):
            assets.append({
                "asset_id": f"bilibili_api_{info.get('bvid','')}_{i}",
                "source": "bilibili",
                "url": info.get("url", ""),
                "title": info.get("title", "")[:100],
                "duration": info.get("duration", 30),
                "resolution": "1920x1080",
                "author": info.get("author", ""),
                "query": query,
                "fetch_ua": ua[:50],
                "has_session": session is not None,
                "timestamp": time.time(),
            })
        return assets

    def _bilibili_api_search(self, keyword, limit=3):
        """Use B站 REST API to search and get video play URLs.

        Returns list of {bvid, title, url, duration, author}.
        """
        results = []
        try:
            import urllib.request
            import urllib.parse
            import json

            # Step 1: Search API
            encoded = urllib.parse.quote(keyword)
            search_url = (
                f"https://api.bilibili.com/x/web-interface/search/all/v2"
                f"?keyword={encoded}&page=1&page_size={limit + 5}"
            )
            req = urllib.request.Request(search_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.bilibili.com/",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("code") != 0:
                print(f"[Fetch] Bilibili API error: {data.get('message','')}")
                return results

            video_items = data.get("data", {}).get("result", [])
            # result is a list of {result_type, data[]}
            for section in video_items:
                if section.get("result_type") != "video":
                    continue
                for item in section.get("data", [])[:limit]:
                    bvid = item.get("bvid", "")
                    title = item.get("title", "").replace('<em class="keyword">', '').replace('</em>', '')
                    author = item.get("author", "")
                    duration_str = item.get("duration", "0:00")
                    # Parse duration "MM:SS" to seconds
                    try:
                        parts = duration_str.split(":")
                        dur = int(parts[0]) * 60 + int(parts[1])
                    except Exception:
                        dur = 30

                    # Step 2: Get video playback URL
                    play_url = self._bilibili_get_play_url(bvid)
                    if play_url:
                        results.append({
                            "bvid": bvid,
                            "title": title,
                            "url": play_url,
                            "duration": dur,
                            "author": author,
                        })
                        print(f"[Fetch] Bilibili API: {bvid} {title[:30]}...")

        except Exception as e:
            print(f"[Fetch] Bilibili API search failed: {e}")

        return results

    def _bilibili_get_play_url(self, bvid):
        """Get video stream URL for a B站 BV ID.

        First fetch video info to get cid, then request play URL.
        """
        import urllib.request
        import json

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": f"https://www.bilibili.com/video/{bvid}",
        }

        try:
            # Step 1: Get cid from video info API
            info_api = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            req = urllib.request.Request(info_api, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                info = json.loads(resp.read().decode("utf-8"))
            if info.get("code") != 0:
                print(f"[Fetch] Bilibili info API error for {bvid}: {info.get('message','')}")
                return None
            cid = info.get("data", {}).get("cid", 0)
            if not cid:
                return None

            # Step 2: Get play URL
            play_api = (
                f"https://api.bilibili.com/x/player/playurl"
                f"?bvid={bvid}&cid={cid}&qn=80&fnval=1&fourk=1"
            )
            req2 = urllib.request.Request(play_api, headers=headers)
            with urllib.request.urlopen(req2, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("code") != 0:
                print(f"[Fetch] Bilibili play API error for {bvid}: {data.get('message','')}")
                return None

            durl = data.get("data", {}).get("durl", [])
            if durl and durl[0].get("url"):
                return durl[0]["url"]
            return None

        except Exception as e:
            print(f"[Fetch] Bilibili play API failed for {bvid}: {e}")
            return None

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
