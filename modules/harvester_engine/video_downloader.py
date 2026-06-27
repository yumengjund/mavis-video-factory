"""V1.5.3 视频下载器"""
import os
import hashlib
import requests
from pathlib import Path

MIN_VIDEO_SIZE = 100 * 1024  # 100 KB minimum for valid video

class VideoDownloader:
    def __init__(self, output_dir="output/raw_ingestion", min_size=MIN_VIDEO_SIZE):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.min_size = min_size

    def download(self, url, filename=None, max_retries=3):
        if filename is None:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
            filename = f"{url_hash}.mp4"
        output_path = self.output_dir / filename
        for attempt in range(max_retries):
            try:
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Referer": "https://www.bilibili.com/",
                }
                r = requests.get(url, headers=headers, stream=True, timeout=60)
                r.raise_for_status()

                # Check content-type
                ct = r.headers.get("Content-Type", "").lower()
                if ct and not any(v in ct for v in ("video/", "application/octet-stream")):
                    print(f"[Downloader] Skipping non-video content-type: {ct} for {url[:60]}")
                    return None

                with open(output_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                file_size = output_path.stat().st_size
                if file_size >= self.min_size:
                    return str(output_path)
                else:
                    print(f"[Downloader] File too small ({file_size}B), discarding: {url[:60]}")
                    output_path.unlink()
                    return None
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
        return None

    def download_batch(self, urls):
        results = []
        for i, url in enumerate(urls):
            try:
                path = self.download(url, filename=f"video_{i:04d}.mp4")
                if path:
                    results.append({"url": url, "path": path, "status": "downloaded"})
                else:
                    results.append({"url": url, "path": None, "status": "failed"})
            except Exception as e:
                results.append({"url": url, "path": None, "status": f"error: {str(e)}"})
        return results
