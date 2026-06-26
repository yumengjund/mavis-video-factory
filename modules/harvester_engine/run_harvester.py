"""V1.5.3 统一采集执行器"""
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from browser_core import BrowserCore, PLAYWRIGHT_AVAILABLE
from douyin_adapter import DouyinAdapter
from xiaohongshu_adapter import XiaohongshuAdapter
from bilibili_adapter import BilibiliAdapter
from weibo_adapter import WeiboAdapter
from video_downloader import VideoDownloader
from watermark_cleaner import WatermarkCleaner
from content_normalizer_v3 import ContentNormalizerV3
from proxy_manager import ProxyManager


def run_harvester(keyword, platforms=None, limit=10, headless=True, proxy=None):
    """
    统一采集入口

    Args:
        keyword: 搜索关键词
        platforms: 平台列表，默认全部 ["douyin", "xiaohongshu", "bilibili", "weibo"]
        limit: 每个平台最大抓取数
        headless: 是否无头模式
        proxy: 代理地址

    Returns:
        list[dict]: 标准化后的 asset_v3 列表
    """
    if not PLAYWRIGHT_AVAILABLE:
        return [{"error": "Playwright not installed", "status": "blocked"}]

    ADAPTERS = {
        "douyin": DouyinAdapter(),
        "xiaohongshu": XiaohongshuAdapter(),
        "bilibili": BilibiliAdapter(),
        "weibo": WeiboAdapter(),
    }

    if platforms is None:
        platforms = list(ADAPTERS.keys())

    downloader = VideoDownloader()
    cleaner = WatermarkCleaner()
    normalizer = ContentNormalizerV3()
    proxy_mgr = ProxyManager()

    all_results = []

    with BrowserCore(headless=headless, proxy=proxy) as browser:
        page = browser.new_page()
        for platform_name in platforms:
            adapter = ADAPTERS.get(platform_name)
            if not adapter:
                continue
            try:
                adapter.search(page, keyword)
                urls = adapter.extract(page, limit=limit) if hasattr(adapter, "extract") else adapter.extract_video_urls(page, limit=limit)
                metadata_list = adapter.extract_metadata(page, limit=limit) if hasattr(adapter, "extract_metadata") else []
                for i, url in enumerate(urls):
                    try:
                        path = downloader.download(url)
                        if not path:
                            continue
                        cleaned = cleaner.crop_edges(path)
                        watermark_score = cleaner.compute_watermark_score(cleaned)
                        meta = metadata_list[i] if i < len(metadata_list) else {}
                        asset = normalizer.normalize({
                            "platform": platform_name,
                            "url": url,
                            "path": cleaned,
                            "title": meta.get("title", ""),
                            "watermark_score": watermark_score,
                            "trend_score": 85,
                            "download_method": "direct"
                        })
                        all_results.append(asset)
                    except Exception as e:
                        all_results.append({"platform": platform_name, "url": url, "status": "download_failed", "error": str(e)})
            except Exception as e:
                all_results.append({"platform": platform_name, "status": "search_failed", "error": str(e)})
            time.sleep(2)

    if all_results:
        approved = [a for a in all_results if a.get("status") == "approved"]
        if approved:
            manifest_path = normalizer.save_manifest(approved)
            print(f"[Harvester] Manifest saved: {manifest_path}")
        print(f"[Harvester] Total: {len(all_results)}, Approved: {len(approved)}")

    return all_results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="V1.5.3 Real Content Harvester")
    parser.add_argument("keyword", help="搜索关键词")
    parser.add_argument("--platforms", nargs="+", default=None, help="平台列表")
    parser.add_argument("--limit", type=int, default=10, help="每个平台最大抓取数")
    parser.add_argument("--no-headless", action="store_true", help="禁用无头模式")
    parser.add_argument("--proxy", default=None, help="代理地址")
    args = parser.parse_args()

    results = run_harvester(
        keyword=args.keyword,
        platforms=args.platforms,
        limit=args.limit,
        headless=not args.no_headless,
        proxy=args.proxy
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
