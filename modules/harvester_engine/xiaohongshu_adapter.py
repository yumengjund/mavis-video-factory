"""V1.5.3 小红书采集适配器"""
import time

class XiaohongshuAdapter:
    PLATFORM = "xiaohongshu"
    SEARCH_URL = "https://www.xiaohongshu.com/search_result?keyword={}"

    def search(self, page, keyword, max_scroll=3):
        url = self.SEARCH_URL.format(keyword)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)
        for _ in range(max_scroll):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(3)

    def extract(self, page, limit=10):
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
        return urls

    def extract_metadata(self, page, limit=10):
        results = []
        try:
            notes = page.query_selector_all(".note-item")
            for note in notes[:limit]:
                try:
                    title_el = note.query_selector(".title")
                    title = title_el.inner_text() if title_el else ""
                    results.append({"title": title, "platform": self.PLATFORM})
                except Exception:
                    continue
        except Exception:
            pass
        return results
