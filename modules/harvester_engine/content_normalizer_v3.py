"""V1.5.3 内容标准化器 - 输出统一 asset_v3 格式对接 V1.5.2 Pipeline"""
import hashlib
import json
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

class ContentNormalizerV3:
    def __init__(self, output_dir="output/normalized_assets"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _probe_video(self, video_path):
        """获取视频元数据"""
        info = {"duration": 0, "resolution": "unknown", "fps": 0, "codec": "unknown"}
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries",
                   "stream=duration,width,height,r_frame_rate,codec_name",
                   "-of", "json", str(video_path)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for stream in data.get("streams", []):
                    if stream.get("codec_type") == "video":
                        info["resolution"] = f"{stream.get('width',0)}x{stream.get('height',0)}"
                        fps_str = stream.get("r_frame_rate", "0/1")
                        try:
                            num, den = fps_str.split("/")
                            info["fps"] = round(int(num) / int(den), 2)
                        except Exception:
                            info["fps"] = 0
                        info["codec"] = stream.get("codec_name", "unknown")
                        info["duration"] = float(stream.get("duration", 0))
                        break
        except Exception:
            pass
        return info

    def _generate_asset_id(self, source, url):
        raw = f"{source}_{url}_{uuid.uuid4().hex[:8]}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def normalize(self, raw_video):
        """将原始视频标准化为 asset_v3 格式"""
        video_path = raw_video.get("path", raw_video.get("video_path", ""))
        probe = self._probe_video(video_path) if video_path else {}
        asset_id = self._generate_asset_id(
            raw_video.get("platform", raw_video.get("source", "unknown")),
            raw_video.get("url", "")
        )
        return {
            "asset_id": asset_id,
            "source_platform": raw_video.get("platform", raw_video.get("source", "unknown")),
            "source_url": raw_video.get("url", ""),
            "title": raw_video.get("title", ""),
            "video_path": video_path,
            "duration": probe.get("duration", raw_video.get("duration", 0)),
            "resolution": probe.get("resolution", "1080x1920"),
            "fps": probe.get("fps", 30),
            "codec": probe.get("codec", "h264"),
            "watermark_score": raw_video.get("watermark_score", 15),
            "trend_score": raw_video.get("trend_score", raw_video.get("trend", 80)),
            "engagement_score": raw_video.get("engagement_score", 0),
            "license_risk": raw_video.get("license_risk", 40),
            "download_method": raw_video.get("download_method", "direct"),
            "status": "approved" if raw_video.get("watermark_score", 15) < 30 else "rejected",
            "normalized_at": datetime.now().isoformat(),
            "ready_for_pipeline": True,
            "provenance_chain": [{"platform": raw_video.get("platform", "unknown"), "fetch_timestamp": datetime.now().isoformat()}]
        }

    def normalize_batch(self, raw_videos):
        return [self.normalize(v) for v in raw_videos]

    def save_manifest(self, normalized_assets, filename=None):
        if filename is None:
            filename = f"asset_manifest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_path = self.output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"version": "asset_v3", "generated_at": datetime.now().isoformat(), "total": len(normalized_assets), "assets": normalized_assets}, f, ensure_ascii=False, indent=2)
        return str(output_path)
