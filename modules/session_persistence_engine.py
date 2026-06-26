"""V1.5.3 Session Persistence Engine — Cookie  持久化与加密存储"""
import json
import os
import time
import base64
from datetime import datetime
from pathlib import Path

try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# 硬编码占位密钥 — 生产环境应从安全存储/环境变量注入
_PLACEHOLDER_KEY = b"harvester_v153_session_key_32b!"  # Fernet 需要 url-safe-base64-encoded 32-byte key
_FERNET_KEY = base64.urlsafe_b64encode(_PLACEHOLDER_KEY.ljust(32, b"\x00")[:32])


class SessionPersistenceEngine:
    """按平台存储 Cookie 和元数据到本地 JSON，支持 AES 加密和自动过期检测。"""

    def __init__(self, storage_dir):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(_FERNET_KEY) if CRYPTO_AVAILABLE else None

    def _platform_path(self, platform):
        return self.storage_dir / f"{platform}_session.json"

    # ---- 加密工具 -------------------------------------------------
    def _encrypt(self, plaintext):
        if self._fernet:
            return self._fernet.encrypt(plaintext.encode()).decode()
        # fallback: base64 混淆（非安全，仅防止明文泄露）
        return base64.b64encode(plaintext.encode()).decode()

    def _decrypt(self, ciphertext):
        if self._fernet:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        try:
            return base64.b64decode(ciphertext.encode()).decode()
        except Exception:
            return "{}"

    # ---- 公共接口 -------------------------------------------------
    def save(self, platform, cookies, metadata=None):
        """保存平台会话。

        Args:
            platform: 平台名 (douyin/xiaohongshu/bilibili/weibo)
            cookies: cookie 列表，每个元素为 dict(name, value, domain, ...)
            metadata: 额外元数据 (expires_at, user_agent, last_validated)
        """
        payload = {
            "platform": platform,
            "encrypted": CRYPTO_AVAILABLE,
            "cookies": self._encrypt(json.dumps(cookies)),
            "metadata": {
                **(metadata or {}),
                "saved_at": datetime.now().isoformat(),
                "user_agent": metadata.get("user_agent", "") if metadata else "",
            },
        }
        with open(self._platform_path(platform), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def load(self, platform):
        """加载平台会话。返回 (cookies, metadata) 或 (None, None)。"""
        path = self._platform_path(platform)
        if not path.exists():
            return None, None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            cookies_raw = self._decrypt(data.get("cookies", "{}"))
            cookies = json.loads(cookies_raw)
            metadata = data.get("metadata", {})
            return cookies, metadata
        except Exception:
            return None, None

    def is_expired(self, platform):
        """检查平台会话是否已过期。"""
        _, metadata = self.load(platform)
        if metadata is None:
            return True
        expires_at = metadata.get("expires_at")
        if expires_at:
            try:
                expire_dt = datetime.fromisoformat(expires_at)
                if datetime.now() > expire_dt:
                    return True
            except Exception:
                pass
        # 如果无 expires_at 字段但最近 24h 验证过 → 认为有效
        last_validated = metadata.get("last_validated", "")
        if last_validated:
            try:
                dt = datetime.fromisoformat(last_validated)
                if (datetime.now() - dt).total_seconds() > 86400:
                    return True
            except Exception:
                return True
        return False

    def mark_invalid(self, platform):
        """标记会话为失效。"""
        _, metadata = self.load(platform)
        if metadata is not None:
            metadata["last_validated"] = "1970-01-01T00:00:00"
            cookies, _ = self.load(platform)
            self.save(platform, cookies or [], metadata)

    def list_platforms(self):
        """列出所有已存储会话的平台。"""
        platforms = []
        for f in self.storage_dir.glob("*_session.json"):
            platforms.append(f.stem.replace("_session", ""))
        return platforms

    def delete(self, platform):
        """删除平台会话文件。"""
        path = self._platform_path(platform)
        if path.exists():
            path.unlink()
