"""
Copywriter Engine — V1.6.3
---------------------------
Input:  topic string (e.g. "杭州")
Output: 30s voiceover narration with segmented timeline,
        compact 80-100 chars for short-video pacing (180-220 chars/min).

V1.6.3: Compact text + punctuation-based segmentation with timestamps.
"""

import re
from typing import Dict, Any, List


# ---------------------------------------------------------------------------
# Per-topic narration templates (compact 80-100 chars)
# ---------------------------------------------------------------------------

TOPIC_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "杭州": {
        "narration": (
            "杭州，一座被时光偏爱的城市。西湖水波藏着千年诗句，"
            "钱塘潮声激荡江南脉搏。品龙井，听灵隐钟声穿透晨雾，"
            "登雷峰塔，在南宋御街触摸八百年前的繁华。一半山水一半人间。"
        ),
        "keywords": [
            "西湖", "钱塘江", "龙井茶", "雷峰塔", "灵隐寺", "南宋御街",
        ],
    },
    "成都": {
        "narration": (
            "走进成都，像走进一首慢下来的诗。宽窄巷子的青砖灰瓦，"
            "火锅沸腾的市井烟火。太古里的潮流碰撞，杜甫草堂的千年文脉。"
            "来了就不想走的城市。"
        ),
        "keywords": [
            "宽窄巷子", "火锅", "太古里", "杜甫草堂", "都江堰", "大熊猫",
        ],
    },
    "上海": {
        "narration": (
            "黄浦江畔，永不落幕的舞台。陆家嘴摩天楼与石库门弄堂，"
            "隔着百年时光对望。外滩钟声唤醒晨曦，新天地在夜色中绽放。"
            "昨天和明天折叠进同一个瞬间。东方巴黎，从不缺少故事。"
        ),
        "keywords": [
            "黄浦江", "陆家嘴", "石库门", "外滩", "新天地",
        ],
    },
    "重庆": {
        "narration": (
            "山在城中，城在山上。洪崖洞的灯火坠入长江，"
            "轻轨从楼宇间穿堂而过。一顿老火锅，辣出了这座城市的性格。"
            "解放碑下，朝天门码头，看两江交汇奔流。立体生长的魔幻都市。"
        ),
        "keywords": [
            "洪崖洞", "长江", "轻轨", "火锅", "解放碑", "朝天门",
        ],
    },
}

_DEFAULT_TEMPLATE = (
    "这是一座充满故事的城市。清晨阳光穿过林立高楼，"
    "夜晚霓虹点亮街头巷尾。古老街巷藏着岁月痕迹，"
    "现代节奏书写崭新篇章。过去与未来交织，烟火与梦想共存。"
)

# Punctuation that indicates a breath/pause point
_BREAK_PUNCT = re.compile(r'[，。,\.！!？?；;、]')

# Gap durations (seconds)
_COMMA_GAP = 0.15
_PERIOD_GAP = 0.40

# Narration speed target (chars per second at normal gTTS rate ~3.5)
_CHARS_PER_SEC_NORMAL = 3.5


class CopywriterEngine:
    """Generates segmented 30s narration for short-video voiceover."""

    def __init__(self):
        self.version = "1.6.3"

    def generate(self, topic: str) -> Dict[str, Any]:
        topic = topic.strip()
        template = TOPIC_TEMPLATES.get(topic)
        if template:
            narration = template["narration"].strip()
            keywords = template["keywords"]
            source = "template"
        else:
            narration = _DEFAULT_TEMPLATE.strip()
            keywords = []
            source = "default"

        char_count = len(narration)
        segments = self._split_to_segments(narration)
        total_dur = self._compute_duration(segments)

        return {
            "topic": topic,
            "narration": narration,
            "char_count": char_count,
            "keywords": keywords,
            "source": source,
            "version": self.version,
            "segments": segments,
            "total_duration": round(total_dur, 2),
        }

    def generate_narration_only(self, topic: str) -> str:
        return self.generate(topic)["narration"]

    def _split_to_segments(self, text: str) -> List[Dict[str, Any]]:
        segments: List[Dict[str, Any]] = []
        current_time = 0.0
        current_text = ""

        for ch in text:
            current_text += ch
            if _BREAK_PUNCT.match(ch):
                if current_text.strip():
                    seg_len = len(current_text)
                    seg_dur = seg_len / _CHARS_PER_SEC_NORMAL
                    gap = _PERIOD_GAP if ch in '。.!！?？' else _COMMA_GAP
                    segments.append({
                        "text": current_text,
                        "char_count": seg_len,
                        "start": round(current_time, 2),
                        "end": round(current_time + seg_dur, 2),
                        "duration": round(seg_dur, 2),
                        "gap_after": gap,
                    })
                    current_time += seg_dur + gap
                    current_text = ""

        if current_text.strip():
            seg_len = len(current_text)
            seg_dur = seg_len / _CHARS_PER_SEC_NORMAL
            segments.append({
                "text": current_text.strip(),
                "char_count": seg_len,
                "start": round(current_time, 2),
                "end": round(current_time + seg_dur, 2),
                "duration": round(seg_dur, 2),
                "gap_after": 0.0,
            })

        return segments

    def _compute_duration(self, segments: List[Dict[str, Any]]) -> float:
        if not segments:
            return 0.0
        return segments[-1]["end"]

    def get_speed_factor(self, topic: str = "杭州") -> float:
        result = self.generate(topic)
        raw_dur = result["total_duration"]
        if raw_dur <= 0:
            return 1.0
        target = 28.0
        factor = raw_dur / target
        return round(max(0.75, min(2.0, factor)), 2)


def generate_copy(topic: str) -> str:
    engine = CopywriterEngine()
    return engine.generate_narration_only(topic)


if __name__ == "__main__":
    import sys
    topic = sys.argv[1] if len(sys.argv) > 1 else "杭州"
    engine = CopywriterEngine()
    result = engine.generate(topic)
    print(f"Topic: {result['topic']}  |  Source: {result['source']}")
    print(f"Characters: {result['char_count']}  |  Raw dur: {result['total_duration']}s")
    print(f"Speed factor: {engine.get_speed_factor(topic)}x")
    print(f"\nSegmented ({len(result['segments'])} segments):")
    for i, seg in enumerate(result["segments"]):
        print(f"  [{seg['start']:5.1f}s - {seg['end']:5.1f}s] "
              f"gap={seg['gap_after']:.2f}s | {seg['text']}")
