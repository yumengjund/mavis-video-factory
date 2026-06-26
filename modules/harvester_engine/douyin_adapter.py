"""V1.5.3 抖音采集适配器"""
import time
import re

class DouyinAdapter:
    PLATFORM = "douyin"
    SEARCH_URL = "https://www.douyin.com/search/{}"

    def search(self, page, keyword, max_scroll=3):
        url = self.SEARCH_URL.format(keyword)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        for _ in range(max_scroll):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

    def extract_video_urls(self, page, limit=10):
        urls = []
        try:
            videos = page.query_selector_all("video")
            for v in videos:
                src = v.get_attribute("src")
                if src and src not in urls:
                    urls.append(src)
                if len(urls) >= limit:
                    break
        except Exception:
            pass
        try:
            sources = page.query_selector_all("source")
            for s in sources:
                src = s.get_attribute("src")
                if src and src not in urls:
                    urls.append(src)
                if len(urls) >= limit:
                    break
        except Exception:
            pass
        return urls

    def extract_metadata(self, page, limit=10):
        results = []
        try:
            cards = page.query_selector_all("[data-e2e='search-card']")
            for card in cards[:limit]:
                try:
                    title_el = card.query_selector("[data-e2e='search-card-title']")
                    title = title_el.inner_text() if title_el else ""
                    results.append({"title": title, "platform": self.PLATFORM})
                except Exception:
                    continue
        except Exception:
            pass
        return results
