#!/usr/bin/env python3
"""
Anti-Block Strategy Engine — V1.6
----------------------------------
Detects anti-scraping signals and executes counter-strategies.
Works with SessionPoolManager for session rotation on block.
"""

import time
from typing import Any, Dict, Optional, Tuple


class AntiBlockStrategyEngine:
    """Detect and respond to platform anti-scraping measures."""

    BLOCK_SIGNATURES: Dict[str, list] = {
        "captcha_triggered": [
            "验证码", "captcha", "滑块验证", "请完成验证",
        ],
        "rate_limited": [
            "访问过于频繁", "请稍后再试", "操作太频繁",
            "too many requests", "rate limit exceeded",
        ],
        "ip_blocked": [
            "IP已被限制", "网络异常", "访问被拒绝",
            "ip blocked", "access denied",
        ],
        "session_expired": [
            "登录已过期", "请重新登录", "session timeout",
            "please log in again", "token expired",
        ],
        "content_restricted": [
            "内容不可见", "该内容已被删除", "权限不足",
            "content unavailable", "not found",
        ],
    }

    STRATEGY_COOLDOWNS: Dict[str, Dict[str, float]] = {
        "captcha_triggered": {"pause": 30, "cooldown": 120},
        "rate_limited": {"pause": 60, "cooldown": 180},
        "ip_blocked": {"pause": 120, "cooldown": 300},
        "session_expired": {"pause": 5, "cooldown": 10},
        "content_restricted": {"pause": 3, "cooldown": 30},
    }

    BLOCK_SEVERITY: Dict[str, str] = {
        "captcha_triggered": "high",
        "rate_limited": "medium",
        "ip_blocked": "high",
        "session_expired": "medium",
        "content_restricted": "low",
    }

    def __init__(self, session_pool=None):
        self.session_pool = session_pool
        self._block_history: Dict[str, list] = {}  # platform -> [(timestamp, type)]
        self._cooldown_until: Dict[str, float] = {}  # platform -> epoch

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_block(
        self, response_html: str, status_code: int
    ) -> Dict[str, Any]:
        """Analyze response for block signals.

        Returns:
            {"blocked": bool, "type": str|None, "severity": str|None}
        """
        if 200 <= status_code < 300 and not response_html:
            return {"blocked": False, "type": None, "severity": None}

        # Check status code signals
        if status_code == 429:
            return {
                "blocked": True,
                "type": "rate_limited",
                "severity": "medium",
            }
        if status_code == 403:
            return {
                "blocked": True,
                "type": "ip_blocked",
                "severity": "high",
            }
        if status_code == 401:
            return {
                "blocked": True,
                "type": "session_expired",
                "severity": "medium",
            }

        # Pattern match in response body
        html_lower = response_html.lower()
        for block_type, signatures in self.BLOCK_SIGNATURES.items():
            for sig in signatures:
                if sig.lower() in html_lower:
                    return {
                        "blocked": True,
                        "type": block_type,
                        "severity": self.BLOCK_SEVERITY.get(
                            block_type, "low"
                        ),
                    }

        return {"blocked": False, "type": None, "severity": None}

    def execute_strategy(
        self, block_type: str, platform: str
    ) -> Dict[str, Any]:
        """Execute counter-strategy for a detected block.

        Returns:
            {"action": str, "success": bool, "recommendation": str}
        """
        self._record_block(platform, block_type)

        cfg = self.STRATEGY_COOLDOWNS.get(block_type, {"pause": 15, "cooldown": 60})

        actions: Dict[str, str] = {
            "captcha_triggered": f"pause {cfg['pause']}s + switch session + UA",
            "rate_limited": f"exponential backoff {cfg['pause']}s/{cfg['cooldown']}s",
            "ip_blocked": f"pause {cfg['pause']}s + switch session + proxy hint",
            "session_expired": "mark failed + switch session",
            "content_restricted": "rewrite query + retry 1x",
        }

        # Execute session rotation if pool available
        success = True
        if self.session_pool and block_type in (
            "captcha_triggered",
            "session_expired",
            "ip_blocked",
        ):
            current = self.session_pool.get_active_session(platform)
            if current:
                self.session_pool.mark_failed(current["session_id"])
            self.session_pool.rotate_session(platform)

        # Set cooldown
        self._cooldown_until[platform] = time.time() + cfg["pause"]

        return {
            "action": actions.get(block_type, f"pause {cfg['pause']}s"),
            "success": success,
            "recommendation": (
                f"Platform {platform} blocked ({block_type}). "
                f"Applied: {actions.get(block_type, 'pause')}"
            ),
        }

    def should_abort(self, platform: str) -> bool:
        """Check if platform should be skipped this cycle.

        Abort if:
        - 3+ consecutive high-severity blocks in last 5 minutes
        - Currently in cooldown
        """
        # Cooldown check
        cooldown = self._cooldown_until.get(platform, 0)
        if time.time() < cooldown:
            return True

        # Consecutive high-severity block check (last 5 min)
        history = self._block_history.get(platform, [])
        cutoff = time.time() - 300
        recent = [
            h
            for h in history
            if h[0] > cutoff
            and self.BLOCK_SEVERITY.get(h[1], "low") == "high"
        ]
        return len(recent) >= 3

    def reset_platform(self, platform: str) -> None:
        """Clear block history and cooldown for a platform."""
        self._block_history.pop(platform, None)
        self._cooldown_until.pop(platform, None)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _record_block(self, platform: str, block_type: str) -> None:
        """Record a block event in history."""
        self._block_history.setdefault(platform, []).append(
            (time.time(), block_type)
        )
        # Trim old entries
        cutoff = time.time() - 600
        self._block_history[platform] = [
            h
            for h in self._block_history[platform]
            if h[0] > cutoff
        ]
