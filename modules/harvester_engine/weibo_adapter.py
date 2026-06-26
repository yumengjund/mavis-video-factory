"""V1.5.3 微博采集适配器 - 辅助源"""
import time

class WeiboAdapter:
    PLATFORM = "weibo"
    SEARCH_URL = "https://s.weibo.com/weibo?q={}"

    def search(self, page, keyword, max_scroll=3):
        url = self.SEARCH_URL.format(keyword)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        for _ in range(max_scroll):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

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
