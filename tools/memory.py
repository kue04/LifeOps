from __future__ import annotations

import json
from datetime import datetime

from storage.db import connect, init_db


DEFAULT_PROFILE = {
    "user_id": "default",
    "likes": ["咖啡", "展览", "夜景"],
    "dislikes": ["爬山", "排队", "太赶"],
    "pace": "轻松",
    "budget_style": "中等",
}


def load_user_profile(user_id: str = "default") -> dict:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM user_profile WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            return {
                "user_id": row["user_id"],
                "likes": json.loads(row["likes"]),
                "dislikes": json.loads(row["dislikes"]),
                "pace": row["pace"],
                "budget_style": row["budget_style"],
            }
        conn.execute(
            """
            INSERT INTO user_profile (user_id, likes, dislikes, pace, budget_style, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                json.dumps(DEFAULT_PROFILE["likes"], ensure_ascii=False),
                json.dumps(DEFAULT_PROFILE["dislikes"], ensure_ascii=False),
                DEFAULT_PROFILE["pace"],
                DEFAULT_PROFILE["budget_style"],
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    return DEFAULT_PROFILE.copy()
