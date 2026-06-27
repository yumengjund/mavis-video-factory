#!/usr/bin/env python3
"""
Supply Orchestrator — V1.6
---------------------------
Master controller of the V1.6 Input Supply Layer.
Schedules all sub-modules, controls harvest rhythm, outputs unified
asset stream to keep the pipeline continuously fed.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .trend_query_generator import TrendQueryGenerator
from .platform_router import PlatformRouter
from .session_pool_manager import SessionPoolManager
from .adaptive_fetch_controller import AdaptiveFetchController
from .anti_block_strategy_engine import AntiBlockStrategyEngine
from .content_validation_gate import ContentValidationGate


class SupplyOrchestrator:
    """V1.6 Input Supply Layer master controller."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

        # Determine output base path
        self.workspace_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        self.assets_dir = os.path.join(
            self.workspace_root, "output", "v1_6_assets"
        )
        sessions_dir = os.path.join(
            self.workspace_root, "output", "v1_6_sessions"
        )

        # Initialize sub-modules
        self.query_generator = TrendQueryGenerator()
        self.platform_router = PlatformRouter()
        self.session_pool = SessionPoolManager(
            store_path=os.path.join(sessions_dir, "session_store.json")
        )
        self.anti_block = AntiBlockStrategyEngine(
            session_pool=self.session_pool
        )
        self.fetch_controller = AdaptiveFetchController(
            session_pool=self.session_pool,
            anti_block_engine=self.anti_block,
        )
        self.validation_gate = ContentValidationGate()

        # Import existing harvester sessions
        imported = self.session_pool.import_harvester_sessions()
        if imported > 0:
            print(f"[SupplyOrchestrator] Imported {imported} harvester sessions")

        self._cycle_counter: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_supply_cycle(
        self, topic: str, city: str = "", min_assets: int = 20
    ) -> Dict[str, Any]:
        """Run one complete supply cycle.

        Workflow:
        1. Generate trend queries
        2. Route queries to platforms
        3. Get sessions from pool
        4. Adaptive fetch
        5. Handle blocks via anti-block engine
        6. Validate assets
        7. Persist to ValidatedAssetStore

        Returns:
            {cycle_id, assets: [...], stats: {...}}
        """
        self._cycle_counter += 1
        cycle_id = (
            f"v1_6_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        )
        stats = {
            "cycle_id": cycle_id,
            "topic": topic,
            "city": city,
            "queries_generated": 0,
            "platforms_queried": [],
            "fetches_attempted": 0,
            "assets_fetched": 0,
            "assets_valid": 0,
            "assets_rejected": 0,
            "blocks_encountered": 0,
            "blocks_handled": 0,
            "duration_seconds": 0.0,
        }

        t_start = time.time()

        # ---- Step 1: Generate queries ----
        city_key = city or topic  # fallback
        queries = self.query_generator.generate(city_key, topic, limit=15)
        stats["queries_generated"] = len(queries)

        # ---- Step 2-4: Route + Fetch per platform ----
        all_assets: List[Dict[str, Any]] = []
        video_type = self._infer_video_type(topic, city)

        for query in queries[:10]:  # limit queries per cycle
            routes = self.platform_router.route(video_type, query)
            if not routes:
                continue

            platform, weight = routes[0]  # use top platform per query
            if platform not in stats["platforms_queried"]:
                stats["platforms_queried"].append(platform)

            # Check anti-block status
            if self.anti_block.should_abort(platform):
                continue

            # Fetch
            stats["fetches_attempted"] += 1
            try:
                fetched = self.fetch_controller.fetch(
                    platform=platform,
                    query=query,
                    target_count=3,
                )
                all_assets.extend(fetched)
            except Exception:
                # Simulate block detection for test mode
                block = self.anti_block.detect_block("rate_limited", 429)
                if block["blocked"]:
                    stats["blocks_encountered"] += 1
                    strategy = self.anti_block.execute_strategy(
                        block["type"], platform
                    )
                    if strategy["success"]:
                        stats["blocks_handled"] += 1

        stats["assets_fetched"] = len(all_assets)

        # ---- Step 6: Validate ----
        validation = self.validation_gate.validate_batch(all_assets)
        stats["assets_valid"] = validation["stats"]["valid"]
        stats["assets_rejected"] = validation["stats"]["rejected"]

        # ---- Step 6.5: Download videos ----
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        from modules.harvester_engine.video_downloader import VideoDownloader

        downloader = VideoDownloader(output_dir=self.assets_dir)
        downloaded_count = 0

        for asset in validation["valid"]:
            asset_data = asset["asset"]
            url = asset_data.get("url", "")
            asset_id = asset_data.get("asset_id", "")
            if url and asset_id:
                try:
                    path = downloader.download(url, filename=f"{asset_id}.mp4")
                    if path:
                        asset_data["filepath"] = path
                        downloaded_count += 1
                except Exception as e:
                    print(f"[WARN] Download failed: {asset_id} - {e}")

        print(f"[Supply] Downloaded {downloaded_count}/{len(validation['valid'])} videos")

        # ---- Step 7: Persist ----
        os.makedirs(self.assets_dir, exist_ok=True)
        asset_path = os.path.join(
            self.assets_dir, f"supply_{cycle_id}.json"
        )
        with open(asset_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "cycle_id": cycle_id,
                    "topic": topic,
                    "city": city,
                    "valid_assets": validation["valid"],
                    "rejected_assets": validation["rejected"],
                    "stats": stats,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        stats["duration_seconds"] = round(time.time() - t_start, 2)
        stats["min_assets_met"] = stats["assets_valid"] >= min_assets

        return {
            "cycle_id": cycle_id,
            "assets": validation["valid"],
            "stats": stats,
            "asset_file": asset_path,
        }

    def run_continuous(
        self, topics_list: List[Dict[str, str]], interval_seconds: int = 300
    ) -> List[Dict[str, Any]]:
        """Run continuous supply cycles.

        Args:
            topics_list: [{"topic": "cyberpunk", "city": "重庆"}, ...]
            interval_seconds: pause between cycles

        Returns:
            List of cycle results (accumulated).
        """
        results: List[Dict[str, Any]] = []
        # Run one cycle per topic pair (non-blocking in test mode)
        for item in topics_list:
            result = self.execute_supply_cycle(
                topic=item.get("topic", ""),
                city=item.get("city", ""),
            )
            results.append(result)
        return results

    def health_report(self) -> Dict[str, Any]:
        """Generate comprehensive health report."""
        session_health = self.session_pool.check_health()
        fetch_stats = self.fetch_controller.get_fetch_stats()
        validation_stats = self.validation_gate.get_stats()
        platform_stats = self.session_pool.get_platform_stats()

        return {
            "version": "1.6",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycles_completed": self._cycle_counter,
            "sessions": session_health,
            "platform_stats": platform_stats,
            "fetch_stats": fetch_stats,
            "validation_stats": validation_stats,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _infer_video_type(self, topic: str, city: str = "") -> str:
        """Map topic/city to video_type for platform routing."""
        topic_lower = topic.lower()
        city_lower = city.lower() if city else ""

        if "cyberpunk" in topic_lower or "night" in topic_lower:
            return "city_night"
        if "food" in topic_lower or "火锅" in topic:
            return "street_food"
        if "travel" in topic_lower or "vlog" in topic_lower:
            return "travel_vlog"
        if "night" in topic_lower or "夜景" in topic:
            return "nightlife"
        if "architecture" in topic_lower or "建筑" in topic:
            return "architecture"
        if any(kw in topic for kw in ["评测", "推荐", "review"]):
            return "product_review"
        if "trend" in topic_lower or "热门" in topic:
            return "hot_trend"
        return "city_night"
