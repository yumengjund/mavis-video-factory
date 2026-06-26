#!/usr/bin/env python3
"""
Trend Query Generator — V1.6
-----------------------------
Generates platform-specific search queries from city+topic templates.
Merges city templates and topic templates, deduplicates, randomizes.
"""

import random
from typing import List, Set


class TrendQueryGenerator:
    """Generate diverse search queries for real content harvesting."""

    CITY_QUERY_TEMPLATES: dict = {
        "重庆": [
            "重庆夜景", "洪崖洞", "李子坝轻轨", "重庆赛博朋克", "山城夜景",
            "重庆火锅", "解放碑", "长江索道", "重庆立交", "磁器口",
        ],
        "上海": [
            "上海外滩", "陆家嘴夜景", "上海赛博朋克", "浦江夜景", "武康路",
            "上海弄堂", "上海迪士尼", "南京路夜景", "上海天际线", "豫园",
        ],
        "成都": [
            "成都夜景", "太古里", "IFS熊猫", "成都火锅", "宽窄巷子",
            "锦里", "成都春熙路", "九眼桥", "成都夜生活", "都江堰",
        ],
        "深圳": [
            "深圳夜景", "深圳科技园", "深圳湾", "华强北", "深圳赛博朋克",
            "蛇口夜景", "深圳灯光秀", "春茧体育馆", "深圳地王", "前海",
        ],
        "北京": [
            "北京夜景", "国贸CBD", "三里屯", "故宫角楼", "北京胡同",
            "什刹海", "望京SOHO", "鸟巢夜景", "国贸大厦", "南锣鼓巷",
        ],
        "广州": [
            "广州塔", "珠江夜景", "广州赛博朋克", "北京路", "荔湾老街",
            "广州CBD", "沙面", "白云山", "广州夜宵", "琶洲",
        ],
    }

    TOPIC_TEMPLATES: dict = {
        "cyberpunk": ["赛博朋克", "霓虹灯", "城市夜景", "cyberpunk city", "未来城市"],
        "food": ["美食", "street food", "深夜食堂", "路边摊", "网红美食"],
        "city_life": ["城市生活", "city walk", "街头摄影", "urban", "夜生活"],
        "travel": ["旅行", "打卡", "必去", "攻略", "vlog"],
        "architecture": ["建筑", "architecture", "城市天际线", "地标", "高楼"],
        "nightlife": ["夜景", "night", "霓虹", "灯光秀", "不夜城"],
    }

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, city: str, topic: str, limit: int = 10) -> List[str]:
        """Merge city + topic templates, deduplicate, shuffle, return `limit`."""
        city_words = self.CITY_QUERY_TEMPLATES.get(city, [city])
        topic_words = self.TOPIC_TEMPLATES.get(
            topic, self.TOPIC_TEMPLATES.get("city_life", ["城市"])
        )

        combined: List[str] = self.combine(city_words, topic_words)

        # Remove exact duplicates while preserving order
        seen: Set[str] = set()
        unique: List[str] = []
        for q in combined:
            if q not in seen:
                seen.add(q)
                unique.append(q)

        self.rng.shuffle(unique)
        return unique[:limit]

    def combine(
        self, city_words: List[str], topic_words: List[str]
    ) -> List[str]:
        """Intelligently cross-combine city and topic terms.

        Generates:
        1. Direct city terms (standalone, e.g. "洪崖洞")
        2. City-only combinations (e.g. "重庆 立交")
        3. Cross-combinations (e.g. "重庆 赛博朋克 夜景")
        """
        results: List[str] = list(city_words)  # standalone city terms

        # City+City merges for specificity
        for i, cw1 in enumerate(city_words):
            for cw2 in city_words[i + 1 : i + 3]:
                if cw1 != cw2:
                    results.append(f"{cw1} {cw2}")

        # Cross-combine city terms with topic terms
        for cw in city_words:
            for tw in topic_words:
                results.append(f"{cw} {tw}")

        return results

    def generate_platform_specific(
        self, city: str, topic: str, platform: str, limit: int = 5
    ) -> List[str]:
        """Generate queries biased for a specific platform's style."""
        queries = self.generate(city, topic, limit=limit * 2)

        # Douyin: shorter, punchier
        if platform == "douyin":
            queries = [q for q in queries if len(q) <= 12]
        # Bilibili: longer, more descriptive
        elif platform == "bilibili":
            queries = [q for q in queries if len(q) >= 6]

        return queries[:limit]

    def expand_query(self, base_query: str, synonyms: int = 3) -> List[str]:
        """Generate synonym variants of a base query."""
        variants = [base_query]
        # Simple synonym expansion
        replacements = [
            ("夜景", "night view"),
            ("赛博朋克", "cyberpunk"),
            ("美食", "food"),
            ("打卡", "check-in"),
        ]
        for old, new in replacements:
            if old in base_query:
                variants.append(base_query.replace(old, new))
            if new in base_query:
                variants.append(base_query.replace(new, old))
        return variants[:synonyms]
