"""Pure classification rules for supplied social-post patrol results."""
from __future__ import annotations

from typing import Any, Mapping


BUYING_WORDS = ("買", "購屋", "購買", "找房", "看房", "想住", "自住", "預算")
AGENT_WORDS = ("房仲", "仲介", "委託", "物件出售", "歡迎來電", "我是業務")
AD_WORDS = ("限時優惠", "團購", "課程", "抽獎", "招商", "廣告")
REPLY_WORDS = ("私訊", "留言", "方便", "請問", "想了解", "有興趣")


def classify_post(post: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one supplied post; never performs a reply, DM, or follow."""
    post_id = str(post.get("post_id", "")).strip()
    text = str(post.get("text", "")).strip()
    if not post_id or not text:
        raise ValueError("post requires post_id and text")
    if any(word in text for word in AD_WORDS):
        category = "advertisement"
    elif any(word in text for word in AGENT_WORDS):
        category = "industry"
    elif any(word in text for word in BUYING_WORDS):
        category = "buyer-intent"
    else:
        category = "irrelevant"
    signals = [word for word in BUYING_WORDS + REPLY_WORDS if word in text]
    follow_up = "人工確認後提供符合條件的物件摘要" if category == "buyer-intent" else "不主動聯絡"
    return {
        "post_id": post_id,
        "category": category,
        "signals": signals,
        "summary": text[:160],
        "follow_up": follow_up,
        "requires_human_review": True,
        "external_action": "none",
    }


def classify_posts(posts: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [classify_post(post) for post in posts]
