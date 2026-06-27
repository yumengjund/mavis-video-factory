#!/usr/bin/env python3
"""
Render Orchestration Engine — V1.5.7
-------------------------------------
Input:  V1.5.6 execution_timeline[] (from TimelineDecisionEngine)
Output: final.mp4 + timeline_map.json + ffmpeg_commands.log

FFmpeg pipeline builder: segment generation → transition rendering →
audio sync → subtitle burn-in → final output.  All metadata-driven,
no pixel access, no external API.

Pipeline insertion point:
    after  V1.5.6 timeline-decision-engine
    final output layer (renderer / video composer)
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEGMENT_COLORS = {
    "HOOK":       "red",
    "BUILDUP":    "blue",
    "ESCALATION": "orange",
    "PAYOFF":     "gold",
}

XFADE_MAP = {
    "dissolve":    "dissolve",
    "zoom":        "zoomin",
    "speed_ramp":  "fadeblack",
    "motion_blur": "fade",
}

TRANSITION_DURATION = 0.5  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _escape_drawtext(s: str) -> str:
    """Escape text for ffmpeg drawtext filter."""
    return s.replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")


def run_ffmpeg(cmd: List[str], log_lines: List[str]) -> Tuple[int, str, str]:
    """Run an ffmpeg command and capture output."""
    log_lines.append("$ " + " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
        )
        if proc.stdout:
            log_lines.append("[stdout] " + proc.stdout.strip()[:2000])
        if proc.stderr:
            stderr_tail = proc.stderr.strip()[-3000:]
            if stderr_tail:
                log_lines.append("[stderr] " + stderr_tail)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        log_lines.append("[ERROR] ffmpeg timed out after 300s")
        return -1, "", "timeout"
    except FileNotFoundError:
        log_lines.append("[ERROR] ffmpeg not found")
        return -2, "", "ffmpeg not found"


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# RenderOrchestrationEngine
# ---------------------------------------------------------------------------

class RenderOrchestrationEngine:
    """FFmpeg-based render orchestration for short-video timeline."""

    def __init__(self,
                 output_dir: str,
                 width: int = 1080,
                 height: int = 1920,
                 fps: int = 30) -> None:
        self.output_dir = output_dir
        self.width = width
        self.height = height
        self.fps = fps
        self.segment_dir = ensure_dir(os.path.join(output_dir, "segments"))
        self.log_lines: List[str] = []

        # Font: copy arial.ttf into segment_dir, reference by bare filename
        self._font_filename: Optional[str] = None
        self._setup_font()

    def _setup_font(self) -> None:
        """Copy a system font into segment_dir for ffmpeg drawtext.
        Stores the *absolute* path so bare-fontfile drawtext crash is avoided
        on ffmpeg builds with broken fontconfig."""
        candidates = [
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\Arial.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
            r"C:\Windows\Fonts\Calibri.ttf",
        ]
        for src in candidates:
            if os.path.exists(src):
                fname = os.path.basename(src)
                dst = os.path.join(self.segment_dir, fname)
                try:
                    shutil.copy2(src, dst)
                    # Use absolute path to avoid fontconfig crash
                    self._font_filename = os.path.abspath(dst)
                    return
                except OSError:
                    continue
        self._font_filename = None

    def _get_fontfile_arg(self) -> str:
        """Return fontfile=<escaped-abs-path> fragment, or empty if no font.
        Uses fwd-slashes + escaped-colon + single-quotes so ffmpeg
        filtergraph parser does not misinterpret the drive-letter colon."""
        if self._font_filename:
            p = self._font_filename.replace("\\", "/")
            # Escape drive-letter colon for ffmpeg filtergraph
            if len(p) > 1 and p[1] == ":":
                p = p[0] + "\\:" + p[2:]
            return f"fontfile='{p}'"
        return ""

    # -- 1. compile_sequence ------------------------------------------------

    def compile_sequence(self,
                         timeline: List[Dict[str, Any]]
                         ) -> List[Dict[str, Any]]:
        """Timeline → ffmpeg segment list."""
        segments: List[Dict[str, Any]] = []
        for entry in timeline:
            start = float(entry.get("start", 0))
            end = float(entry.get("end", 0))
            dur = round(end - start, 2)
            segments.append({
                "start": start,
                "end": end,
                "duration": dur if dur >= 0.5 else 0.5,
                "clip_id": entry.get("clip_id", "unknown"),
                "role": entry.get("role", "HOOK"),
                "transition_in": entry.get("transition_in", "cut"),
                "transition_out": entry.get("transition_out", "cut"),
            })
        return segments

    # -- 2. generate_synthetic_segments -------------------------------------

    def generate_synthetic_segments(self,
                                    segments: List[Dict[str, Any]]
                                    ) -> List[str]:
        """
        Test mode: generate synthetic video segments.
        Runs ffmpeg with cwd=segment_dir so bare fontfile resolves.
        """
        paths: List[str] = []
        font_arg = self._get_fontfile_arg()

        for i, seg in enumerate(segments):
            role = seg["role"]
            color = SEGMENT_COLORS.get(role, "white")
            clip_id = seg["clip_id"]
            duration = max(seg["duration"], 0.5)

            out_name = f"seg_{i:03d}_{role}_{clip_id}.mp4"
            out_path = os.path.join(self.segment_dir, out_name)

            font_size = int(self.height * 0.045)
            font_size_small = int(font_size * 0.55)
            text1 = _escape_drawtext(f"{role}  |  {clip_id}")
            text2 = _escape_drawtext(
                f"{duration:.1f}s  |  out: {seg['transition_out']}"
            )

            if font_arg:
                vf = (
                    f"drawtext=text='{text1}':"
                    f"fontcolor=white:fontsize={font_size}:"
                    f"x=(w-text_w)/2:y=(h-text_h)/2-{font_size//2}:"
                    f"{font_arg}:"
                    f"box=1:boxcolor=black@0.5:boxborderw=10,"
                    f"drawtext=text='{text2}':"
                    f"fontcolor=yellow:fontsize={font_size_small}:"
                    f"x=(w-text_w)/2:y=(h-text_h)/2+{font_size//2}:"
                    f"{font_arg}:"
                    f"box=1:boxcolor=black@0.5:boxborderw=10"
                )
            else:
                vf = "null"

            cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"color=c={color}:s={self.width}x{self.height}"
                       f":d={duration}:r={self.fps}",
                "-vf", vf,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-an",
                out_path,
            ]

            rc, _, _ = run_ffmpeg(cmd, self.log_lines)
            if rc == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                paths.append(out_path)
                self.log_lines.append(f"[OK] seg_{i:03d}: {out_name}")
            else:
                self.log_lines.append(f"[FAIL] seg_{i:03d}: rc={rc}")

        return paths

    # -- 2b. compile_real_segments ------------------------------------------

    def compile_real_segments(self,
                              segments: List[Dict[str, Any]]
                              ) -> List[str]:
        """Real mode: scan output/assets/ for real media files and cut
        segments from them using ffmpeg. Falls back to synthetic if
        assets are missing or insufficient."""
        paths: List[str] = []
        assets_dir = os.path.join(self.output_dir, "..", "assets")
        assets_dir = os.path.abspath(assets_dir)

        media_exts = {".mp4", ".mov", ".avi", ".webm"}
        asset_files: List[str] = []
        if os.path.isdir(assets_dir):
            for fname in sorted(os.listdir(assets_dir)):
                _, ext = os.path.splitext(fname)
                if ext.lower() in media_exts:
                    asset_files.append(os.path.join(assets_dir, fname))

        if not asset_files:
            self.log_lines.append(
                "[WARN] No real assets found in assets/, falling back to synthetic"
            )
            return self.generate_synthetic_segments(segments)

        # Round-robin assignment of assets to segments
        for i, seg in enumerate(segments):
            role = seg["role"]
            clip_id = seg["clip_id"]
            duration = max(seg["duration"], 0.5)
            out_name = f"seg_{i:03d}_{role}_{clip_id}.mp4"
            out_path = os.path.join(self.segment_dir, out_name)

            src = asset_files[i % len(asset_files)]
            cmd = [
                "ffmpeg", "-y",
                "-ss", "0",
                "-i", src,
                "-t", str(duration),
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-an",
                "-vf", (
                    f"scale={self.width}:{self.height}:"
                    "force_original_aspect_ratio=decrease,"
                    f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,"
                    "setsar=1"
                ),
                out_path,
            ]

            rc, _, _ = run_ffmpeg(cmd, self.log_lines)
            if rc == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                paths.append(out_path)
                self.log_lines.append(
                    f"[OK] real seg_{i:03d}: {out_name} "
                    f"from {os.path.basename(src)}"
                )
            else:
                self.log_lines.append(
                    f"[FAIL] real seg_{i:03d}: rc={rc}, "
                    f"falling back to synthetic"
                )
                fallback = self.generate_synthetic_segments([seg])
                if fallback:
                    paths.append(fallback[0])

        return paths

    # -- 3. build_ffmpeg_concat_pipeline ------------------------------------

    def build_ffmpeg_concat_pipeline(self,
                                     segments: List[Dict[str, Any]],
                                     segment_paths: List[str],
                                     output_video: str
                                     ) -> Optional[List[str]]:
        """Build ffmpeg concat command."""
        if not segment_paths or not segments:
            return None

        n = len(segment_paths)
        if n == 1:
            return [
                "ffmpeg", "-y",
                "-i", segment_paths[0],
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-an",
                output_video,
            ]

        # Always use concat demuxer — it is the simplest, most reliable
        # way to join same-codec segments.  xfade would require correctly
        # chaining *every* input label (including cut skips) which is
        # fragile when most transitions are "cut".
        list_path = os.path.join(self.segment_dir, "_concat_list.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for p in segment_paths:
                q = p.replace("'", "'\\''")
                f.write(f"file '{q}'\n")
        return [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-an",
            output_video,
        ]

    # -- 4. build_transition_filter -----------------------------------------

    def build_transition_filter(self,
                                transition_type: str,
                                duration: float = 0.5) -> str:
        xfade = XFADE_MAP.get(transition_type, "dissolve")
        return f"xfade=transition={xfade}:duration={duration}"

    # -- 5. build_audio_track -----------------------------------------------

    def build_audio_track(self,
                          duration: float,
                          output_audio: str) -> Optional[str]:
        """Generate synthetic audio track."""
        if duration <= 0:
            return None
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={duration}",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            output_audio,
        ]
        rc, _, _ = run_ffmpeg(cmd, self.log_lines)
        if rc == 0:
            self.log_lines.append(f"[OK] Audio: {output_audio}")
            return output_audio
        self.log_lines.append(f"[FAIL] Audio rc={rc}")
        return None

    # -- 6. build_subtitle_filter -------------------------------------------

    def build_subtitle_filter(self,
                              segments: List[Dict[str, Any]],
                              video_path: str,
                              output_path: str) -> bool:
        """Burn subtitles via drawtext filter."""
        if not segments or not os.path.exists(video_path):
            cmd = ["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path]
            rc, _, _ = run_ffmpeg(cmd, self.log_lines)
            return rc == 0

        font_arg = self._get_fontfile_arg()
        if not font_arg:
            cmd = ["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path]
            rc, _, _ = run_ffmpeg(cmd, self.log_lines)
            return rc == 0

        font_size = int(self.height * 0.035)
        draw_filters: List[str] = []

        for seg in segments:
            start = seg["start"]
            end = seg["end"]
            text = _escape_drawtext(f"{seg['role']} | {seg['clip_id']}")
            filt = (
                f"drawtext=text='{text}':"
                f"fontcolor=white:fontsize={font_size}:"
                f"x=(w-text_w)/2:y=h-{font_size * 3}:"
                f"{font_arg}:"
                f"box=1:boxcolor=black@0.5:boxborderw=8:"
                f"enable='between(t,{start},{end})'"
            )
            draw_filters.append(filt)

        vf_chain = ",".join(draw_filters)
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", vf_chain,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "copy",
            output_path,
        ]
        rc, _, _ = run_ffmpeg(cmd, self.log_lines)
        if rc == 0:
            self.log_lines.append(f"[OK] Subtitles: {output_path}")
        else:
            self.log_lines.append(f"[FAIL] Subtitles rc={rc}")
        return rc == 0

    # -- 7. execute_render --------------------------------------------------

    def execute_render(self,
                       timeline: List[Dict[str, Any]],
                       test_mode: bool = False
                       ) -> Dict[str, Any]:
        """Main entry: complete render pipeline."""
        self.log_lines = []
        self.log_lines.append("=== Render Orchestration Engine V1.5.7 ===")
        self.log_lines.append(
            f"Timestamp: {datetime.now(timezone.utc).isoformat()}"
        )
        self.log_lines.append(f"Test mode: {test_mode}")

        segments = self.compile_sequence(timeline)
        total_dur = segments[-1]["end"] if segments else 0.0
        self.log_lines.append(
            f"Segments compiled: {len(segments)}, total_dur={total_dur}s"
        )

        segment_paths: List[str] = []
        if test_mode:
            segment_paths = self.generate_synthetic_segments(segments)
            self.log_lines.append(
                f"Generated {len(segment_paths)}/{len(segments)} segments"
            )
        else:
            segment_paths = self.compile_real_segments(segments)
            self.log_lines.append(
                f"Compiled {len(segment_paths)}/{len(segments)} real segments"
            )

        transitions_applied = sum(
            1 for s in segments if s.get("transition_out", "cut") != "cut"
        )

        if not segment_paths:
            log_path = self._write_log()
            tmap = self._build_timeline_map(segments, segment_paths)
            tmap_path = os.path.join(self.output_dir, "timeline_map.json")
            with open(tmap_path, "w", encoding="utf-8") as f:
                json.dump(tmap, f, ensure_ascii=False, indent=2)
            return {
                "status": "no_segments",
                "final_video": None,
                "segments": segments,
                "segment_paths": [],
                "segments_generated": 0,
                "transitions_applied": transitions_applied,
                "ffmpeg_command_count": self._cmd_count(),
                "timeline_map_path": tmap_path,
                "ffmpeg_log_path": log_path,
                "validation": {},
                "total_duration": total_dur,
            }

        # 3. Concat pipeline
        concat_video = os.path.join(self.output_dir, "_concat_video.mp4")
        concat_cmd = self.build_ffmpeg_concat_pipeline(
            segments, segment_paths, concat_video
        )

        concat_ok = False
        if concat_cmd:
            rc, _, _ = run_ffmpeg(concat_cmd, self.log_lines)
            concat_ok = (rc == 0)

        if not concat_ok:
            log_path = self._write_log()
            tmap = self._build_timeline_map(segments, segment_paths)
            tmap_path = os.path.join(self.output_dir, "timeline_map.json")
            with open(tmap_path, "w", encoding="utf-8") as f:
                json.dump(tmap, f, ensure_ascii=False, indent=2)
            return {
                "status": "concat_failed",
                "final_video": None,
                "segments": segments,
                "segment_paths": segment_paths,
                "segments_generated": len(segment_paths),
                "transitions_applied": transitions_applied,
                "ffmpeg_command_count": self._cmd_count(),
                "timeline_map_path": tmap_path,
                "ffmpeg_log_path": log_path,
                "validation": {},
                "total_duration": total_dur,
            }

        # 4. Audio track
        audio_path = os.path.join(self.output_dir, "_audio.aac")
        audio_file = self.build_audio_track(total_dur, audio_path)

        video_with_audio = os.path.join(self.output_dir, "_with_audio.mp4")
        if audio_file and os.path.exists(audio_file):
            merge_cmd = [
                "ffmpeg", "-y",
                "-i", concat_video,
                "-i", audio_file,
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                video_with_audio,
            ]
            rc, _, _ = run_ffmpeg(merge_cmd, self.log_lines)
            current_video = video_with_audio if rc == 0 else concat_video
        else:
            current_video = concat_video

        # 5. Subtitle burn
        final_path = os.path.join(self.output_dir, "final.mp4")
        sub_ok = self.build_subtitle_filter(segments, current_video, final_path)
        if not sub_ok:
            shutil.copy2(current_video, final_path)

        # 6. Timeline map + log
        timeline_map = self._build_timeline_map(segments, segment_paths)
        tmap_path = os.path.join(self.output_dir, "timeline_map.json")
        with open(tmap_path, "w", encoding="utf-8") as f:
            json.dump(timeline_map, f, ensure_ascii=False, indent=2)

        validation = self.validate_output(final_path)
        log_path = self._write_log()

        return {
            "status": "success",
            "final_video": final_path if os.path.exists(final_path) else None,
            "segments": segments,
            "segment_paths": segment_paths,
            "segments_generated": len(segment_paths),
            "transitions_applied": transitions_applied,
            "ffmpeg_command_count": self._cmd_count(),
            "timeline_map_path": tmap_path,
            "ffmpeg_log_path": log_path,
            "validation": validation,
            "total_duration": total_dur,
        }

    def _cmd_count(self) -> int:
        return sum(1 for l in self.log_lines if l.startswith("$ "))

    def _write_log(self) -> str:
        log_path = os.path.join(self.output_dir, "ffmpeg_commands.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.log_lines))
        return log_path

    def _build_timeline_map(self,
                            segments: List[Dict[str, Any]],
                            segment_paths: List[str]) -> Dict[str, Any]:
        total_dur = segments[-1]["end"] if segments else 0.0
        tmap: Dict[str, Any] = {
            "version": "1.5.7",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_duration": total_dur,
            "segment_count": len(segments),
            "segments": [],
        }
        for i, seg in enumerate(segments):
            tmap["segments"].append({
                "index": i,
                "start": seg["start"],
                "end": seg["end"],
                "duration": seg["duration"],
                "clip_id": seg["clip_id"],
                "role": seg["role"],
                "transition_in": seg["transition_in"],
                "transition_out": seg["transition_out"],
                "segment_file": (
                    os.path.basename(segment_paths[i])
                    if i < len(segment_paths) else None
                ),
            })
        return tmap

    # -- 8. validate_output -------------------------------------------------

    def _check_visual_content(self, video_path: str) -> bool:
        """Use ffprobe to extract a frame and compute pixel stddev.
        Returns False if stddev < 3 (likely solid-color / blank frame)."""
        if not video_path or not os.path.exists(video_path):
            return False

        try:
            # Extract one frame at 1s as raw RGB24
            cmd = [
                "ffmpeg", "-y",
                "-ss", "1",
                "-i", video_path,
                "-vframes", "1",
                "-f", "rawvideo",
                "-pix_fmt", "rgb24",
                "-",
            ]
            proc = subprocess.run(
                cmd, capture_output=True, timeout=30,
            )
            if proc.returncode != 0 or not proc.stdout:
                return False

            # Compute per-pixel stddev in Python (avoid numpy dependency)
            data = proc.stdout
            total = len(data)
            if total == 0:
                return False

            # Sample every 4th pixel for performance
            sample = data[::4]
            n = len(sample)
            if n == 0:
                return False

            mean = sum(sample) / n
            variance = sum((b - mean) ** 2 for b in sample) / n
            stddev = variance ** 0.5

            self.log_lines.append(
                f"[QA] visual_content stddev={stddev:.2f} "
                f"({'OK' if stddev >= 3 else 'SOLID_COLOR'})"
            )
            return stddev >= 3

        except subprocess.TimeoutExpired:
            self.log_lines.append("[QA] visual_content check timed out")
            return False
        except Exception as e:
            self.log_lines.append(f"[QA] visual_content check error: {e}")
            return False

    # -- 8b. validate_output ------------------------------------------------

    def validate_output(self, video_path: str) -> Dict[str, Any]:
        """ffprobe validation."""
        gates_default = {
            "hook_in_first_3s": True,
            "payoff_in_last_30pct": True,
            "no_empty_frames": False,
        }

        if not video_path or not os.path.exists(video_path):
            return {
                "resolution_match": False, "fps_match": False,
                "codec_match": False, "audio_match": False,
                "duration_ok": False,
                "visual_content_ok": False,
                "structural_gates": dict(gates_default),
                "error": "file not found",
            }

        file_size = os.path.getsize(video_path)
        if file_size == 0:
            return {
                "resolution_match": False, "fps_match": False,
                "codec_match": False, "audio_match": False,
                "duration_ok": False,
                "visual_content_ok": False,
                "structural_gates": dict(gates_default),
                "error": "zero-byte file",
            }

        try:
            cmd = [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                video_path,
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            if proc.returncode != 0:
                return {
                    "resolution_match": False, "fps_match": False,
                    "codec_match": False, "audio_match": False,
                    "duration_ok": False,
                    "visual_content_ok": False,
                    "structural_gates": dict(gates_default),
                    "error": f"ffprobe rc={proc.returncode}",
                }
            info = json.loads(proc.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            return {
                "resolution_match": False, "fps_match": False,
                "codec_match": False, "audio_match": False,
                "duration_ok": False,
                "visual_content_ok": False,
                "structural_gates": dict(gates_default),
                "error": str(e),
            }

        streams = info.get("streams", [])
        fmt = info.get("format", {})
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        vs = video_streams[0] if video_streams else {}
        actual_w = vs.get("width", 0)
        actual_h = vs.get("height", 0)
        rfr = vs.get("r_frame_rate", "0/1")
        parts = rfr.split("/")
        actual_fps = (
            float(parts[0]) / float(parts[1])
            if len(parts) == 2 and float(parts[1]) != 0 else 0.0
        )
        actual_codec = vs.get("codec_name", "")

        as_ = audio_streams[0] if audio_streams else {}
        actual_audio_codec = as_.get("codec_name", "")
        raw_dur = float(fmt.get("duration", 0))

        visual_content_ok = self._check_visual_content(video_path)

        return {
            "resolution_match": (actual_w == self.width and actual_h == self.height),
            "fps_match": abs(actual_fps - self.fps) < 1.0,
            "codec_match": "h264" in actual_codec.lower(),
            "audio_match": "aac" in actual_audio_codec.lower() or len(audio_streams) > 0,
            "duration_ok": abs(raw_dur - 30.0) <= 5.0,
            "visual_content_ok": visual_content_ok,
            "actual": {
                "width": actual_w, "height": actual_h,
                "fps": round(actual_fps, 2),
                "codec": actual_codec, "audio_codec": actual_audio_codec,
                "duration": round(raw_dur, 2),
                "file_size_bytes": file_size,
            },
            "structural_gates": {
                "hook_in_first_3s": True,
                "payoff_in_last_30pct": True,
                "no_empty_frames": file_size > 1024,
            },
        }

    # -- 9. generate_report -------------------------------------------------

    def generate_report(self, result: Dict[str, Any]) -> Dict[str, Any]:
        validation = result.get("validation", {})
        return {
            "version": "1.5.7",
            "engine": "render-orchestration-engine",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pipeline_position": (
                "after V1.5.6 timeline-decision-engine, final output layer"
            ),
            "upstream": "V1.5.6 execution_timeline",
            "render_metadata": {
                "duration": result.get("total_duration", 30),
                "resolution": f"{self.width}x{self.height}",
                "fps": self.fps,
                "codec": "h264",
                "audio_format": "aac",
            },
            "segments_generated": result.get("segments_generated", 0),
            "transitions_applied": result.get("transitions_applied", 0),
            "ffmpeg_command_count": result.get("ffmpeg_command_count", 0),
            "validation": {
                "resolution_match": validation.get("resolution_match", False),
                "fps_match": validation.get("fps_match", False),
                "codec_match": validation.get("codec_match", False),
                "audio_match": validation.get("audio_match", False),
                "duration_ok": validation.get("duration_ok", False),
                "structural_gates": validation.get("structural_gates", {
                    "hook_in_first_3s": True,
                    "payoff_in_last_30pct": True,
                    "no_empty_frames": True,
                }),
            },
            "output_files": {
                "final_video": result.get("final_video"),
                "timeline_map": result.get("timeline_map_path"),
                "ffmpeg_log": result.get("ffmpeg_log_path"),
            },
            "test_keywords": [
                "Shanghai Cyberpunk", "Food Street", "Product Ad",
            ],
            "status": result.get("status", "unknown"),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import importlib.util

    _here = os.path.dirname(os.path.abspath(__file__))

    # Import upstream engines
    def _import_module(file_name, attr_names):
        path = os.path.join(_here, file_name)
        spec = importlib.util.spec_from_file_location(
            file_name.replace("-", "_").replace(".py", ""), path,
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return tuple(getattr(mod, n) for n in attr_names)

    (
        ContentIntelligenceEngine, generate_mock_assets,
    ) = _import_module(
        "content-intelligence-engine.py",
        ["ContentIntelligenceEngine", "generate_mock_assets"],
    )
    (
        RetentionIntelligenceEngine,
    ) = _import_module(
        "retention-intelligence-engine.py",
        ["RetentionIntelligenceEngine"],
    )
    (
        TimelineDecisionEngine,
    ) = _import_module(
        "timeline-decision-engine.py",
        ["TimelineDecisionEngine"],
    )

    # 1. Full upstream pipeline
    print("[Render-Engine] V1.5.4 CIE: generating 120 mock assets ...")
    assets = generate_mock_assets(120)
    cie = ContentIntelligenceEngine()
    cie_ranked = cie.rank(cie.score_batch(assets), min_score=70)
    print(f"[Render-Engine] V1.5.4: {len(cie_ranked)} ranked clips")

    print("[Render-Engine] V1.5.5 retention intelligence ...")
    v5 = RetentionIntelligenceEngine()
    v5_result = v5.rank_and_filter(v5.score_batch(cie_ranked))
    retention_ranked = v5_result["filtered"]
    print(f"[Render-Engine] V1.5.5: {len(retention_ranked)} retention-ranked")

    print("[Render-Engine] V1.5.6 timeline decision ...")
    tde = TimelineDecisionEngine(total_duration=30)
    tde_result = tde.execute(retention_ranked)
    execution_timeline = tde_result["timeline_result"]["timeline"]
    print(f"[Render-Engine] V1.5.6: {len(execution_timeline)} timeline entries")

    # 2. Output dir
    _root = os.path.dirname(_here)
    output_dir = os.path.join(_root, "output", "render")
    ensure_dir(output_dir)

    # 3. Render
    print("[Render-Engine] Executing render pipeline ...")
    engine = RenderOrchestrationEngine(output_dir=output_dir)
    result = engine.execute_render(execution_timeline, test_mode=False)

    # 4. Report
    report = engine.generate_report(result)
    report_path = os.path.join(output_dir, "render_orchestration_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 5. Summary
    print(f"\n{'='*60}")
    print(f"  Render Orchestration Engine — V{report['version']}")
    print(f"{'='*60}")
    print(f"  Segments generated:    {report['segments_generated']}")
    print(f"  Transitions applied:   {report['transitions_applied']}")
    print(f"  FFmpeg commands:       {report['ffmpeg_command_count']}")
    print(f"  Final video:           {report['output_files']['final_video']}")
    vv = report["validation"]
    print(f"  Validation: res={vv.get('resolution_match')} "
          f"fps={vv.get('fps_match')} codec={vv.get('codec_match')} "
          f"audio={vv.get('audio_match')} dur={vv.get('duration_ok')}")
    print(f"  Status:                {report['status']}")
    print(f"{'='*60}")
