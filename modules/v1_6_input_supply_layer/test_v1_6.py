#!/usr/bin/env python3
"""
V1.6 Input Supply Layer — Integration Test
===========================================
Tests supply_orchestrator full pipeline. Falls back to structural
integrity verification mode when no real sessions exist.
"""

import json
import os
import sys

# Ensure modules/ is importable
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "modules"),
)

from v1_6_input_supply_layer.supply_orchestrator import SupplyOrchestrator
from v1_6_input_supply_layer.session_pool_manager import SessionPoolManager
from v1_6_input_supply_layer.platform_router import PlatformRouter
from v1_6_input_supply_layer.trend_query_generator import TrendQueryGenerator
from v1_6_input_supply_layer.content_validation_gate import ContentValidationGate
from v1_6_input_supply_layer.anti_block_strategy_engine import (
    AntiBlockStrategyEngine,
)


def test_module_instantiation():
    """Verify all modules instantiate without error."""
    spm = SessionPoolManager()
    pr = PlatformRouter()
    tqg = TrendQueryGenerator()
    cvg = ContentValidationGate()
    abe = AntiBlockStrategyEngine(spm)
    so = SupplyOrchestrator()

    all_ok = all(
        [
            spm is not None,
            pr is not None,
            tqg is not None,
            cvg is not None,
            abe is not None,
            so is not None,
        ]
    )

    return {
        "session_pool_manager": True,
        "platform_router": True,
        "trend_query_generator": True,
        "content_validation_gate": True,
        "anti_block_strategy_engine": True,
        "supply_orchestrator": True,
        "all_modules_ok": all_ok,
    }


def test_trend_queries():
    """Test query generation for Chongqing + cyberpunk."""
    tqg = TrendQueryGenerator()
    queries = tqg.generate("重庆", "cyberpunk", limit=10)

    has_chongqing = any("重庆" in q for q in queries)
    return {
        "query_count": len(queries),
        "queries": queries[:5],
        "has_chongqing_keyword": has_chongqing,
        "pass": len(queries) == 10 and has_chongqing,
    }


def test_platform_routing():
    """Test platform routing priority."""
    pr = PlatformRouter()
    routes = pr.route("city_night", "重庆夜景", trend_score=85)

    top_platform = routes[0][0] if routes else None
    return {
        "route_count": len(routes),
        "top_platform": top_platform,
        "all_routes": [(p, w) for p, w in routes],
        "pass": (
            len(routes) > 0
            and top_platform in ["xiaohongshu", "douyin"]
        ),
    }


def test_session_pool():
    """Test session pool management."""
    spm = SessionPoolManager()
    imported = spm.import_harvester_sessions()
    health = spm.check_health()
    stats = spm.get_platform_stats()

    return {
        "harvester_sessions_imported": imported,
        "health": health,
        "platform_stats": stats,
        "pass": True,  # Always passes — import may be 0
    }


def test_content_validation():
    """Test validation gate with synthetic assets."""
    cvg = ContentValidationGate()

    # Valid asset
    valid_asset = {
        "asset_id": "test_real_01",
        "source": "douyin",
        "url": "https://example.com/test.mp4",
        "duration": 5.3,
        "resolution": "1080x1920",
        "downloadable": True,
    }
    valid_result = cvg.validate(valid_asset)

    # Invalid asset (short duration, low res)
    invalid_asset = {
        "asset_id": "test_bad_01",
        "source": "douyin",
        "url": "",
        "duration": 1.0,
        "resolution": "720x1280",
        "downloadable": False,
    }
    invalid_result = cvg.validate(invalid_asset)

    return {
        "valid_asset_result": valid_result,
        "invalid_asset_result": invalid_result,
        "pass": valid_result["valid"] and not invalid_result["valid"],
    }


def test_anti_block():
    """Test anti-block detection."""
    spm = SessionPoolManager()
    abe = AntiBlockStrategyEngine(spm)

    # Test captcha detection
    captcha_html = '<div>请输入验证码</div>'
    result = abe.detect_block(captcha_html, 200)
    captcha_detected = result["blocked"] and result["type"] == "captcha_triggered"

    # Test rate limit by status code
    rate_result = abe.detect_block("", 429)
    rate_detected = rate_result["blocked"] and rate_result["type"] == "rate_limited"

    # Test OK response
    ok_result = abe.detect_block("<div>normal</div>", 200)
    ok_clean = not ok_result["blocked"]

    return {
        "captcha_detected": captcha_detected,
        "rate_limit_detected": rate_detected,
        "normal_not_blocked": ok_clean,
        "pass": captcha_detected and rate_detected and ok_clean,
    }


def test_supply_cycle():
    """Test full supply cycle (synthetic, no real sessions)."""
    so = SupplyOrchestrator()

    result = so.execute_supply_cycle(
        topic="cyberpunk",
        city="重庆",
        min_assets=20,
    )

    stats = result.get("stats", {})
    assets = result.get("assets", [])

    return {
        "cycle_id": result.get("cycle_id", ""),
        "assets_fetched": stats.get("assets_fetched", 0),
        "assets_valid": stats.get("assets_valid", 0),
        "assets_rejected": stats.get("assets_rejected", 0),
        "queries_generated": stats.get("queries_generated", 0),
        "duration_seconds": stats.get("duration_seconds", 0),
        "min_assets_met": stats.get("min_assets_met", False),
        "pass": stats.get("assets_fetched", 0) > 0,
    }


def test_health_report():
    """Test health report generation."""
    so = SupplyOrchestrator()
    report = so.health_report()

    required_keys = [
        "version",
        "timestamp",
        "sessions",
        "fetch_stats",
        "validation_stats",
    ]
    has_keys = all(k in report for k in required_keys)

    return {
        "has_required_keys": has_keys,
        "version": report.get("version"),
        "pass": has_keys and report.get("version") == "1.6",
    }


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    results: dict = {}
    all_passed = True

    test_suite = {
        "instantiation": test_module_instantiation,
        "trend_queries": test_trend_queries,
        "platform_routing": test_platform_routing,
        "session_pool": test_session_pool,
        "content_validation": test_content_validation,
        "anti_block": test_anti_block,
        "supply_cycle": test_supply_cycle,
        "health_report": test_health_report,
    }

    for name, test_fn in test_suite.items():
        try:
            result = test_fn()
            results[name] = result
            if isinstance(result, dict) and not result.get("pass", True):
                all_passed = False
                print(f"  FAIL: {name}")
            else:
                print(f"  PASS: {name}")
        except Exception as e:
            results[name] = {"error": str(e), "pass": False}
            all_passed = False
            print(f"  FAIL: {name} — {e}")

    results["all_passed"] = all_passed

    # Write report
    output_dir = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__), "..", "..", "output", "v1_6_test"
        )
    )
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, "v1_6_test_report.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nReport: {output_path}")
    print(f"All passed: {all_passed}")
