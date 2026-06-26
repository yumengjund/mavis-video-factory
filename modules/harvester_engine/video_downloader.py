"""V1.5.3 视频下载器"""
import os
import hashlib
import requests
from pathlib import Path

class VideoDownloader:
    def __init__(self, output_dir="output/raw_ingestion"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def download(self, url, filename=None, max_retries=3):
        if filename is None:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
            filename = f"{url_hash}.mp4"
        output_path = self.output_dir / filename
        for attempt in range(max_retries):
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                r = requests.get(url, headers=headers, stream=True, timeout=60)
                r.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                if output_path.stat().st_size > 1024:
                    return str(output_path)
                else:
                    output_path.unlink()
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
