"""V1.5.3 Harvest Strategy V2 — 统一采集策略（会话 + 认证 + 解锁 + 采集）"""
import sys
import json
import time
from datetime import datetime
from pathlib import Path

# 确保可以 import 同目录下模块
_MODULE_DIR = Path(__file__).parent
sys.path.insert(0, str(_MODULE_DIR))

from session_persistence_engine import SessionPersistenceEngine
from auth_login_engine import AuthLoginEngine
from browser_persistence import PersistentBrowserFactory
from content_unlock_detector import ContentUnlockDetector

# 复用已有 V1.5.3 adapter/downloader/normalizer
from harvester_engine.douyin_adapter import DouyinAdapter
from harvester_engine.xiaohongshu_adapter import XiaohongshuAdapter
from harvester_engine.bilibili_adapter import BilibiliAdapter
from harvester_engine.weibo_adapter import WeiboAdapter
from harvester_engine.video_downloader import VideoDownloader
from harvester_engine.watermark_cleaner import WatermarkCleaner
from harvester_engine.content_normalizer_v3 import ContentNormalizerV3


# 平台适配器映射
ADAPTERS = {
    "douyin": DouyinAdapter(),
    "xiaohongshu": XiaohongshuAdapter(),
    "bilibili": BilibiliAdapter(),
    "weibo": WeiboAdapter(),
}


def harvest_with_auth(keyword, platforms=None, limit=10, headless=True,
                      session_dir=None, profile_dir=None):
    """
    V1.5.3 + Auth Layer — 完整采集流程。

    流程：
    1. 加载持久化会话
    2. 为每个平台创建持久化浏览器上下文
    3. 检测内容是否被锁定
    4. 如锁定，尝试自动恢复会话或提示手动登录
    5. 提取内容 + 下载视频 + 标准化

    Args:
        keyword: 搜索关键词
        platforms: 平台列表（默认全部）
        limit: 每个平台最大抓取数
        headless: 无头模式
        session_dir: 会话持久化存储目录
        profile_dir: 浏览器 profile 根目录

    Returns:
        dict: {
            "assets": list[dict],      # 标准化 asset_v3 列表
            "auth_report": dict,        # 各平台认证状态
            "summary": dict,            # 总体统计
        }
    """
    # 默认路径
    workspace_root = Path(__file__).parent.parent
    if session_dir is None:
        session_dir = str(workspace_root / "output" / "sessions")
    if profile_dir is None:
        profile_dir = str(workspace_root / "output" / "browser_profiles")

    if platforms is None:
        platforms = list(ADAPTERS.keys())

    # 初始化各组件
    session_engine = SessionPersistenceEngine(session_dir)
    auth_engine = AuthLoginEngine(session_engine)
    browser_factory = PersistentBrowserFactory(profile_dir)
    unlock_detector = ContentUnlockDetector()
    downloader = VideoDownloader()
    cleaner = WatermarkCleaner()
    normalizer = ContentNormalizerV3()

    all_assets = []
    auth_report = {}

    for platform in platforms:
        adapter = ADAPTERS.get(platform)
        if not adapter:
            auth_report[platform] = {"status": "skipped", "reason": "no_adapter"}
            continue

        platform_result = {
            "platform": platform,
            "status": "pending",
            "auth_method": "none",
            "videos_found": 0,
            "assets_normalized": 0,
            "errors": [],
        }

        context = None
        page = None

        try:
            # Step 1: 创建持久化上下文
            context, page = browser_factory.create_context(platform, headless=headless)

            # Step 2: 恢复会话
            restored = auth_engine.restore_session(page, platform)
            if restored:
                page.reload(wait_until="domcontentloaded")
                time.sleep(2)
                platform_result["auth_method"] = "session_restore"

            # Step 3: 检测内容解锁状态
            unlock_status = unlock_detector.is_content_locked(page, platform)
            platform_result["unlock_status"] = unlock_status

            if not unlock_status["unlocked"]:
                # Step 4: 尝试自动登录
                login_result = auth_engine.auto_login(page, platform)
                platform_result["auth_method"] = login_result.get("method", "auto_login_failed")
                if login_result.get("success"):
                    # 重试解锁检测
                    time.sleep(2)
                    unlock_status = unlock_detector.is_content_locked(page, platform)
                    platform_result["unlock_status"] = unlock_status
                else:
                    platform_result["status"] = "auth_required"
                    platform_result["errors"].append(login_result.get("message", ""))
                    auth_report[platform] = platform_result
                    continue

            # Step 5: 搜索并提取视频 URL
            adapter.search(page, keyword)
            urls = (adapter.extract(page, limit=limit)
                    if hasattr(adapter, "extract")
                    else adapter.extract_video_urls(page, limit=limit))

            metadata_list = (adapter.extract_metadata(page, limit=limit)
                             if hasattr(adapter, "extract_metadata") else [])

            platform_result["videos_found"] = len(urls)

            # Step 6: 下载 + 去水印 + 标准化
            for i, url in enumerate(urls):
                try:
                    video_path = downloader.download(url)
                    if not video_path:
                        continue
                    cleaned_path = cleaner.crop_edges(video_path)
                    watermark_score = cleaner.compute_watermark_score(cleaned_path)
                    meta = metadata_list[i] if i < len(metadata_list) else {}
                    asset = normalizer.normalize({
                        "platform": platform,
                        "url": url,
                        "path": cleaned_path,
                        "title": meta.get("title", ""),
                        "watermark_score": watermark_score,
                        "trend_score": 85,
                        "download_method": "direct"
                    })
                    all_assets.append(asset)
                    platform_result["assets_normalized"] += 1
                except Exception as e:
                    platform_result["errors"].append(f"download_error: {str(e)[:100]}")

            # Step 7: 捕获并保存会话
            cookies, metadata = auth_engine.capture_session(page, platform)
            if cookies:
                session_engine.save(platform, cookies, metadata)

            # Step 8: 保存 storage state
            browser_factory.save_storage_state(platform)

            platform_result["status"] = "completed"

        except Exception as e:
            platform_result["status"] = "failed"
            platform_result["errors"].append(f"platform_error: {str(e)[:200]}")
        finally:
            if context:
                try:
                    browser_factory.close_platform(platform)
                except Exception:
                    pass

        auth_report[platform] = platform_result

    # 汇总
    summary = {
        "keyword": keyword,
        "platforms_attempted": len(platforms),
        "total_assets": len(all_assets),
        "approved_assets": sum(1 for a in all_assets if a.get("status") == "approved"),
        "rejected_assets": sum(1 for a in all_assets if a.get("status") != "approved"),
        "completed_platforms": sum(1 for v in auth_report.values() if v.get("status") == "completed"),
        "auth_required_platforms": sum(1 for v in auth_report.values() if v.get("status") == "auth_required"),
        "timestamp": datetime.now().isoformat(),
    }

    # 保存 manifest
    if all_assets:
        approved = [a for a in all_assets if a.get("status") == "approved"]
        if approved:
            manifest_path = normalizer.save_manifest(approved)
            summary["manifest"] = str(manifest_path)

    return {
        "assets": all_assets,
        "auth_report": auth_report,
        "summary": summary,
    }


# ---- CLI 入口 ----------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="V1.5.3 Harvester V2 — with Auth Layer")
    parser.add_argument("keyword", help="搜索关键词")
    parser.add_argument("--platforms", nargs="+", default=None, help="平台列表")
    parser.add_argument("--limit", type=int, default=10, help="每个平台最大抓取数")
    parser.add_argument("--no-headless", action="store_true", help="禁用无头模式")
    parser.add_argument("--session-dir", default=None, help="会话存储目录")
    parser.add_argument("--profile-dir", default=None, help="浏览器 profile 目录")
    args = parser.parse_args()

    result = harvest_with_auth(
        keyword=args.keyword,
        platforms=args.platforms,
        limit=args.limit,
        headless=not args.no_headless,
        session_dir=args.session_dir,
        profile_dir=args.profile_dir,
    )

    # 输出汇总
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print("\n--- Auth Report ---")
    for plat, report in result["auth_report"].items():
        print(f"  [{plat}] status={report['status']} "
              f"videos={report.get('videos_found', 0)} "
              f"assets={report.get('assets_normalized', 0)}")
