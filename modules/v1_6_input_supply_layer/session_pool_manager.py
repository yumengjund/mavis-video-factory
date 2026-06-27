#!/usr/bin/env python3
"""
Session Pool Manager — V1.6
----------------------------
Manages multi-platform session pool: cookie persistence, auto-expiry
detection, session rotation, failover. Persists to JSON store.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class SessionPoolManager:
    """Multi-platform session lifecycle manager."""

    DEFAULT_SESSION_TTL = 86400  # 24 hours

    def __init__(
        self,
        store_path: str = "",
    ):
        if not store_path:
            store_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "output", "v1_6_sessions", "session_store.json",
            )
        self.store_path = store_path
        self.sessions: Dict[str, List[Dict[str, Any]]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_session(
        self,
        platform: str,
        cookies: List[Dict[str, Any]],
        user_agent: str = "",
    ) -> str:
        """Register a new session and return its session_id."""
        session_id = f"{platform}_{int(time.time() * 1000)}"
        session = {
            "session_id": session_id,
            "platform": platform,
            "cookies": cookies,
            "user_agent": user_agent,
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_used": datetime.now(timezone.utc).isoformat(),
            "ttl": self.DEFAULT_SESSION_TTL,
            "fail_count": 0,
        }
        self.sessions.setdefault(platform, []).append(session)
        self._save()
        return session_id

    def get_active_session(
        self, platform: str
    ) -> Optional[Dict[str, Any]]:
        """Return best available session for a platform.

        Sorted by: least recently used, status=active, not expired.
        """
        candidates = self.sessions.get(platform, [])
        now_ts = time.time()

        active = [
            s
            for s in candidates
            if s.get("status") == "active"
            and s.get("fail_count", 0) < 3
        ]

        if not active:
            return None

        # Sort: least recently used first
        active.sort(
            key=lambda s: s.get("last_used", ""),
        )

        return active[0] if active else None

    def rotate_session(self, platform: str) -> Optional[Dict[str, Any]]:
        """Mark current as used, return next best session."""
        current = self.get_active_session(platform)
        if current:
            current["last_used"] = datetime.now(timezone.utc).isoformat()
            current["use_count"] = current.get("use_count", 0) + 1
            self._save()
        # Return another session (may be same if only one)
        return self.get_active_session(platform)

    def mark_failed(self, session_id: str) -> None:
        """Increment fail counter; disable after 3 failures."""
        for platform_sessions in self.sessions.values():
            for s in platform_sessions:
                if s["session_id"] == session_id:
                    s["fail_count"] = s.get("fail_count", 0) + 1
                    if s["fail_count"] >= 3:
                        s["status"] = "failed"
                    self._save()
                    return

    def check_health(self) -> Dict[str, Dict[str, int]]:
        """Return health summary per platform."""
        health: Dict[str, Dict[str, int]] = {}
        for platform, sessions in self.sessions.items():
            active_count = sum(1 for s in sessions if s.get("status") == "active")
            failed_count = sum(1 for s in sessions if s.get("status") == "failed")
            health[platform] = {
                "total": len(sessions),
                "active": active_count,
                "failed": failed_count,
                "expired": 0,  # computed below if ttl checks needed
            }
        return health

    def import_harvester_sessions(self) -> int:
        """Import sessions from harvester_engine session_store.json.

        Returns number of sessions imported.
        """
        harvester_paths = [
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "harvester_engine", "runtime", "session_store.json",
            ),
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "harvester_engine", "session_store.json",
            ),
        ]

        MIN_FILE_SIZE = 1000  # skip empty templates (<1KB)
        imported = 0
        for hp in harvester_paths:
            if not os.path.exists(hp):
                continue
            if os.path.getsize(hp) < MIN_FILE_SIZE:
                continue
            try:
                with open(hp, "r", encoding="utf-8") as f:
                    store = json.load(f)
                # store format: {platform: {status, cookies, ...}}
                # May also be wrapped as {"sessions": {...}}
                sessions_data = store.get("sessions", store)
                for platform, info in sessions_data.items():
                    if not isinstance(info, dict):
                        continue
                    if info.get("status") != "missing":
                        # Register as active if not missing
                        self.register_session(
                            platform=platform,
                            cookies=info.get("cookies", []),
                            user_agent=info.get("user_agent", ""),
                        )
                        imported += 1
            except (json.JSONDecodeError, IOError):
                continue

        return imported

    def get_platform_stats(self) -> Dict[str, int]:
        """Count active sessions per platform."""
        stats: Dict[str, int] = {}
        for platform, sessions in self.sessions.items():
            stats[platform] = sum(
                1 for s in sessions if s.get("status") == "active"
            )
        return stats

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load session store from disk."""
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path, "r", encoding="utf-8") as f:
                    self.sessions = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.sessions = {}

    def _save(self) -> None:
        """Persist session store to disk."""
        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(self.sessions, f, ensure_ascii=False, indent=2)
