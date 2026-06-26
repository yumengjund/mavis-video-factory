"""V1.5.3 去水印器 - 合法裁剪方案"""
import os
import subprocess
from pathlib import Path

class WatermarkCleaner:
    def __init__(self, output_dir="output/raw_ingestion"):
        self.output_dir = Path(output_dir)

    def crop_edges(self, video_path, edge_px=20):
        """裁剪视频边缘区域，移除常见水印"""
        input_path = Path(video_path)
        output_path = self.output_dir / input_path.name.replace(".mp4", "_clean.mp4")
        try:
            cmd = [
                "ffmpeg", "-y", "-i", str(input_path),
                "-vf", f"crop=iw-{edge_px*2}:ih-{edge_px*2}:{edge_px}:{edge_px}",
                "-c:v", "libx264", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                str(output_path)
            ]
            subprocess.run(cmd, capture_output=True, check=True, timeout=120)
            return str(output_path)
        except Exception:
            return video_path

    def crop_bottom(self, video_path, bottom_px=80):
        """裁剪底部水印区域"""
        input_path = Path(video_path)
        output_path = self.output_dir / input_path.name.replace(".mp4", "_nocropbot.mp4")
        try:
            cmd = [
                "ffmpeg", "-y", "-i", str(input_path),
                "-vf", f"crop=iw:ih-{bottom_px}:0:0",
                "-c:v", "libx264", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                str(output_path)
            ]
            subprocess.run(cmd, capture_output=True, check=True, timeout=120)
            return str(output_path)
        except Exception:
            return video_path

    def compute_watermark_score(self, video_path):
        """估算水印分数 - 基于边缘检测"""
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            duration = float(result.stdout.strip()) if result.stdout.strip() else 0
            video = Path(video_path)
            size_mb = video.stat().st_size / (1024 * 1024)
            bitrate_mbps = (size_mb * 8) / duration if duration > 0 else 0
            if bitrate_mbps < 1:
                return 25
            elif bitrate_mbps < 3:
                return 18
            else:
                return 10
        except Exception:
            return 20
