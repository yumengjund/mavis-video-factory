"""
Copywriter Engine — V1.6.1
---------------------------
Input:  topic string (e.g. "杭州")
Output: 30s voiceover narration text (~80-120 Chinese characters),
        structured as HOOK → BUILDUP → ESCALATION → PAYOFF

P0-1: Narration generation for video voiceover track.
"""

from typing import Dict, Any

# ---------------------------------------------------------------------------
# Per-topic narration templates
# ---------------------------------------------------------------------------

TOPIC_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "杭州": {
        "narration": (
            "有人说，杭州是一座被时光偏爱的城市。"
            "西湖的水波里藏着千年的诗句，钱塘江的潮声激荡着江南的脉搏。"
            "品一杯龙井，听灵隐的钟声穿透晨雾；"
            "登雷峰塔眺望，在南宋御街触摸八百年前的繁华。"
            "杭州，一半是山水，一半是人间。"
        ),
        "keywords": [
            "西湖", "钱塘江", "龙井茶", "雷峰塔", "灵隐寺", "南宋御街",
        ],
    },
    "成都": {
        "narration": (
            "走进成都，就像走进一首慢下来的诗。"
            "宽窄巷子的青砖灰瓦，火锅沸腾的市井烟火；"
            "太古里的潮流碰撞，杜甫草堂的千年文脉。"
            "都江堰的水流了两千年，熊猫在竹林里打了个盹。"
            "成都，是一座来了就不想走的城市。"
        ),
        "keywords": [
            "宽窄巷子", "火锅", "太古里", "杜甫草堂", "都江堰", "大熊猫",
        ],
    },
    "上海": {
        "narration": (
            "黄浦江畔，一座永不落幕的舞台。"
            "陆家嘴的摩天楼与石库门的弄堂，隔着百年时光对望。"
            "外滩的钟声唤醒晨曦，新天地在夜色中绽放。"
            "上海的魔力，是把昨天和明天折叠进同一个瞬间。"
            "东方巴黎，从不缺少故事。"
        ),
        "keywords": [
            "黄浦江", "陆家嘴", "石库门", "外滩", "新天地",
        ],
    },
    "重庆": {
        "narration": (
            "山在城中，城在山上——这就是重庆。"
            "洪崖洞的灯火坠入长江，轻轨从楼宇间穿堂而过。"
            "一顿老火锅，辣出了这座城市的性格；"
            "解放碑下，朝天门码头，看两江交汇奔流不息。"
            "重庆，一座立体生长的魔幻都市。"
        ),
        "keywords": [
            "洪崖洞", "长江", "轻轨", "火锅", "解放碑", "朝天门",
        ],
    },
}


# Default fallback template for unknown topics
_DEFAULT_TEMPLATE = (
    "这是一座充满故事的城市。"
    "清晨的阳光穿过林立的高楼，夜晚的霓虹点亮街头巷尾。"
    "古老的街巷藏着岁月的痕迹，现代的节奏书写崭新的篇章。"
    "这里，过去与未来交织，烟火与梦想共存。"
    "一座城市，千万种可能。"
)


class CopywriterEngine:
    """Generates 30-second narration text for a given topic."""

    def __init__(self):
        self.version = "1.6.1"

    def generate(self, topic: str) -> Dict[str, Any]:
        """Generate narration text for a topic.

        Args:
            topic: City/theme name (e.g. "杭州", "成都", "上海")

        Returns:
            Dict with 'narration', 'char_count', 'keywords', 'topic', 'source'
        """
        topic = topic.strip()
        template = TOPIC_TEMPLATES.get(topic)

        if template:
            narration = template["narration"]
            keywords = template["keywords"]
            source = "template"
        else:
            narration = _DEFAULT_TEMPLATE
            keywords = []
            source = "default"

        # Strip leading/trailing whitespace from narration
        narration = narration.strip()

        return {
            "topic": topic,
            "narration": narration,
            "char_count": len(narration),
            "keywords": keywords,
            "source": source,
            "version": self.version,
        }

    def generate_narration_only(self, topic: str) -> str:
        """Convenience: return narration string only."""
        return self.generate(topic)["narration"]


# ---------------------------------------------------------------------------
# Module-level shortcut
# ---------------------------------------------------------------------------


def generate_copy(topic: str) -> str:
    """Generate narration text for the given topic."""
    engine = CopywriterEngine()
    return engine.generate_narration_only(topic)


if __name__ == "__main__":
    import sys

    topic = sys.argv[1] if len(sys.argv) > 1 else "杭州"
    engine = CopywriterEngine()
    result = engine.generate(topic)
    print(f"Topic: {result['topic']}")
    print(f"Source: {result['source']}")
    print(f"Characters: {result['char_count']}")
    print(f"Keywords: {', '.join(result['keywords'])}")
    print(f"\nNarration:\n{result['narration']}")
