"""V1.5.3 Content Unlock Detector — 内容解锁检测器"""
import time


class ContentUnlockDetector:
    """检测各平台内容是否被登录墙/验证码/CAPTCHA 锁定。

    返回统一格式: {"unlocked": bool, "video_count": int, "issues": list, "suggested_action": str}
    """

    # 各平台锁特征
    LOCK_PATTERNS = {
        "bilibili": {
            "login_wall_selectors": [
                ".login-tip", ".bili-mini-login", ".login-panel-pop",
                '[class*="login"]', ".bpx-player-video-area .bpx-player-login-tip",
            ],
            "captcha_selectors": [
                ".geetest_panel", ".yidun_popup", ".captcha-verify-image",
            ],
            "passport_redirect": "passport.bilibili.com",
        },
        "douyin": {
            "login_wall_selectors": [
                ".login-modal", ".web-login-container", '[class*="login-mask"]',
            ],
            "captcha_selectors": [
                ".captcha_verify_container", ".verify-bar", ".security-verify",
            ],
            "passport_redirect": "",
        },
        "xiaohongshu": {
            "login_wall_selectors": [
                ".login-container", ".login-mask", ".reds-login",
                ".login-modal", '[class*="login-box"]',
            ],
            "captcha_selectors": [
                ".captcha-container", ".verify-code", ".slide-verify",
            ],
            "passport_redirect": "",
        },
        "weibo": {
            "login_wall_selectors": [
                ".W_login_form", ".login-box", ".login_form",
                ".layer_login", "#pl_login_form",
            ],
            "captcha_selectors": [
                ".yidun_popup", ".geetest_panel", ".verify-code-box",
            ],
            "passport_redirect": "login.sina.com.cn",
        },
    }

    def __init__(self):
        pass

    # ---- 检测方法 -------------------------------------------------
    def is_content_locked(self, page, platform):
        """综合检测：判断当前页面内容是否被锁定。

        Args:
            page: Playwright Page 实例
            platform: 平台名

        Returns:
            dict: {"unlocked": bool, "video_count": int, "issues": list, "suggested_action": str}
        """
        video_count = self.get_video_count(page, platform)
        issues = []
        locked = False

        # 1. 检测登录墙
        if self.detect_login_wall(page, platform):
            issues.append("login_wall_detected")
            locked = True

        # 2. 检测验证码/CAPTCHA
        if self._detect_captcha(page, platform):
            issues.append("captcha_detected")

        # 3. 检测页面重定向到登录页
        if self._detect_passport_redirect(page, platform):
            issues.append("redirected_to_login")
            locked = True

        # 4. 综合判断：有视频但被锁定 → 部分解锁
        if video_count > 0 and not locked:
            pass  # 已解锁
        elif video_count == 0 and locked:
            pass  # 确认锁定
        elif video_count == 0 and not locked:
            issues.append("no_videos_found")

        suggested_action = self._suggested_action(issues, video_count, platform)

        return {
            "unlocked": not locked and video_count > 0,
            "video_count": video_count,
            "issues": issues,
            "suggested_action": suggested_action,
        }

    def get_unlock_status(self, page, platform):
        """get_unlock_status 别名 → 调用 is_content_locked。"""
        return self.is_content_locked(page, platform)

    def detect_login_wall(self, page, platform=None):
        """检测是否存在登录墙。

        如果 platform 为 None，尝试在所有平台特征中检测。
        """
        if platform and platform in self.LOCK_PATTERNS:
            return self._check_selectors(page, self.LOCK_PATTERNS[platform]["login_wall_selectors"])

        # 如果没指定平台，逐一检查
        for plat, patterns in self.LOCK_PATTERNS.items():
            if self._check_selectors(page, patterns["login_wall_selectors"]):
                return True
        return False

    # ---- 视频计数 -------------------------------------------------
    def get_video_count(self, page, platform=None):
        """获取当前页面可见的视频元素数量。"""
        try:
            videos = page.query_selector_all("video")
            return len(videos)
        except Exception:
            return 0

    # ---- 内部工具 -------------------------------------------------
    def _check_selectors(self, page, selectors):
        """检查页面中是否存在任一指定的 CSS 选择器。"""
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    return True
            except Exception:
                continue
        return False

    def _detect_captcha(self, page, platform):
        """检测验证码/CAPTCHA。"""
        if platform not in self.LOCK_PATTERNS:
            return False
        return self._check_selectors(page, self.LOCK_PATTERNS[platform]["captcha_selectors"])

    def _detect_passport_redirect(self, page, platform):
        """检测页面是否被重定向到登录/验证页面。"""
        if platform not in self.LOCK_PATTERNS:
            return False
        target = self.LOCK_PATTERNS[platform].get("passport_redirect", "")
        if not target:
            return False
        try:
            current_url = page.url
            return target in current_url.lower()
        except Exception:
            return False

    def _suggested_action(self, issues, video_count, platform):
        """根据检测结果生成建议操作。"""
        if not issues:
            return "content_accessible"

        actions = []
        if "login_wall_detected" in issues:
            actions.append(f"需要登录 {platform}")
        if "captcha_detected" in issues:
            actions.append("遇到验证码，建议等待或切换 IP")
        if "redirected_to_login" in issues:
            actions.append(f"已被重定向到登录页，需恢复会话")
        if "no_videos_found" in issues and "login_wall_detected" not in issues:
            actions.append("未找到视频内容，可能是搜索无结果或页面结构已变更")

        if not actions:
            return "retry_with_auth"
        return "; ".join(actions)
