from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from config import settings


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "storage" / "schema.sql"


def _db_path() -> Path:
    configured = Path(settings.db_path).expanduser()
    if configured.is_absolute():
        return configured
    return ROOT / configured


DB_PATH = _db_path()


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def save_task_history(user_input: str, final_plan: dict[str, Any] | None, user_id: str = "default") -> str:
    init_db()
    task_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO task_history (task_id, user_id, user_input, final_plan, feedback, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                user_id,
                user_input,
                json.dumps(final_plan or {}, ensure_ascii=False),
                None,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    return task_id


def save_app_run_context(
    trace_id: str,
    user_id: str,
    role: str,
    task_id: str | None = None,
    status: str = "running",
    scenario: str | None = None,
) -> None:
    init_db()
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO app_run_context (
              trace_id, task_id, user_id, role, status, scenario, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trace_id) DO UPDATE SET
              task_id = COALESCE(excluded.task_id, app_run_context.task_id),
              user_id = excluded.user_id,
              role = excluded.role,
              status = excluded.status,
              scenario = COALESCE(excluded.scenario, app_run_context.scenario),
              updated_at = excluded.updated_at
            """,
            (trace_id, task_id, user_id, role, status, scenario, now, now),
        )


def record_app_confirmation(
    user_id: str,
    action_type: str,
    status: str,
    trace_id: str | None = None,
    task_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    init_db()
    confirmation_id = uuid4().hex[:12]
    created_at = datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO app_confirmations (
              confirmation_id, trace_id, task_id, user_id, action_type, status, details, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                confirmation_id,
                trace_id,
                task_id,
                user_id,
                action_type,
                status,
                json.dumps(details or {}, ensure_ascii=False),
                created_at,
            ),
        )
    return {"confirmation_id": confirmation_id, "status": status, "created_at": created_at}


def has_app_confirmation(user_id: str, confirmation_id: str | None, action_type: str) -> bool:
    if not confirmation_id:
        return False
    init_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT confirmation_id
            FROM app_confirmations
            WHERE confirmation_id = ?
              AND user_id = ?
              AND action_type = ?
              AND status = 'confirmed'
            """,
            (confirmation_id, user_id, action_type),
        ).fetchone()
    return row is not None


def record_app_audit(
    actor_user_id: str,
    actor_role: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    init_db()
    audit_id = uuid4().hex[:12]
    created_at = datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO app_audit_log (
              audit_id, actor_user_id, actor_role, action,
              resource_type, resource_id, details, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                actor_user_id,
                actor_role,
                action,
                resource_type,
                resource_id,
                json.dumps(details or {}, ensure_ascii=False),
                created_at,
            ),
        )
    return {"audit_id": audit_id, "created_at": created_at}


def list_app_audit_logs(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    safe_limit = max(1, min(int(limit), 200))
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
              audit_id,
              actor_user_id,
              actor_role,
              action,
              resource_type,
              resource_id,
              details,
              created_at
            FROM app_audit_log
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_task_history(
    limit: int = 20,
    user_id: str | None = None,
    role: str = "user",
) -> list[dict[str, Any]]:
    init_db()
    where = ""
    params: list[Any] = []
    if user_id:
        if role in {"operator_admin", "admin"}:
            where = ""
        else:
            where = "WHERE task_history.user_id = ?"
            params.append(user_id)
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
              task_history.task_id,
              task_history.user_id,
              task_history.user_input,
              task_history.final_plan,
              task_history.feedback,
              task_history.created_at,
              app_run_context.status AS app_status,
              CASE WHEN plan_feedback.feedback_id IS NULL THEN 0 ELSE 1 END AS has_feedback
            FROM task_history
            LEFT JOIN plan_feedback
              ON plan_feedback.task_id = task_history.task_id
            LEFT JOIN app_run_context
              ON app_run_context.task_id = task_history.task_id
            {where}
            GROUP BY task_history.task_id
            ORDER BY task_history.created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def save_plan_feedback(
    payload: dict[str, Any],
    user_id: str = "default",
) -> dict[str, Any]:
    init_db()
    feedback_id = uuid4().hex[:12]
    tags = [str(tag) for tag in payload.get("tags") or [] if tag]
    item_feedback = [
        item for item in payload.get("item_feedback") or []
        if isinstance(item, dict)
    ]
    learned = _learn_from_feedback(tags, item_feedback, payload.get("rating"))
    created_at = datetime.now().isoformat(timespec="seconds")
    task_id = str(payload.get("task_id") or "")
    trace_id = str(payload.get("trace_id") or "")

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO plan_feedback (
              feedback_id, task_id, trace_id, user_id, rating, tags, note,
              item_feedback, learned_preferences, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feedback_id,
                task_id,
                trace_id,
                user_id,
                _safe_int(payload.get("rating")),
                json.dumps(tags, ensure_ascii=False),
                str(payload.get("note") or ""),
                json.dumps(item_feedback, ensure_ascii=False),
                json.dumps(learned, ensure_ascii=False),
                created_at,
            ),
        )
        for event in learned:
            conn.execute(
                """
                INSERT INTO memory_events (
                  event_id, user_id, source_task_id, source_trace_id,
                  event_type, content, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex[:12],
                    user_id,
                    task_id,
                    trace_id,
                    event["type"],
                    event["content"],
                    created_at,
                ),
            )
        _update_user_profile(conn, user_id, learned, created_at)

    return {
        "feedback_id": feedback_id,
        "learned_preferences": learned,
        "created_at": created_at,
    }


def get_profile(user_id: str = "default") -> dict[str, Any]:
    init_db()
    with connect() as conn:
        profile = _read_profile(conn, user_id)
        feedback_rows = conn.execute(
            """
            SELECT rating, tags, item_feedback, created_at
            FROM plan_feedback
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()
        memory_rows = conn.execute(
            """
            SELECT event_type, content, source_task_id, source_trace_id, created_at
            FROM memory_events
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 12
            """,
            (user_id,),
        ).fetchall()
        history_rows = conn.execute(
            """
            SELECT user_input, final_plan, created_at
            FROM task_history
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 120
            """,
            (user_id,),
        ).fetchall()

    return {
        "user_id": user_id,
        "profile": profile,
        "stats": _profile_stats(feedback_rows, history_rows),
        "recent_memory": [dict(row) for row in memory_rows],
    }


def feedback_status_map() -> dict[str, bool]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT task_id, trace_id
            FROM plan_feedback
            """
        ).fetchall()
    status: dict[str, bool] = {}
    for row in rows:
        if row["task_id"]:
            status[row["task_id"]] = True
        if row["trace_id"]:
            status[row["trace_id"]] = True
    return status


def _learn_from_feedback(tags: list[str], item_feedback: list[dict[str, Any]], rating: Any) -> list[dict[str, str]]:
    learned: list[dict[str, str]] = []
    tag_set = set(tags)
    if "太赶" in tag_set:
        learned.append({"type": "dislike", "content": "太赶的路线"})
        learned.append({"type": "pace", "content": "轻松"})
    if "太贵" in tag_set:
        learned.append({"type": "budget_style", "content": "省钱"})
    if "路线顺" in tag_set:
        learned.append({"type": "like", "content": "顺路少折返"})
    if "证据不足" in tag_set:
        learned.append({"type": "dislike", "content": "缺少依据的推荐"})
    if _safe_int(rating) and _safe_int(rating) >= 4:
        learned.append({"type": "like", "content": "高匹配度计划"})

    for item in item_feedback:
        place = str(item.get("place") or "").strip()
        sentiment = str(item.get("sentiment") or "").strip()
        if not place:
            continue
        if sentiment == "like":
            learned.append({"type": "like", "content": place})
        elif sentiment == "dislike":
            learned.append({"type": "dislike", "content": place})

    deduped: list[dict[str, str]] = []
    seen = set()
    for item in learned:
        key = (item["type"], item["content"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _update_user_profile(
    conn: sqlite3.Connection,
    user_id: str,
    learned: list[dict[str, str]],
    updated_at: str,
) -> None:
    profile = _read_profile(conn, user_id)
    likes = list(profile["likes"])
    dislikes = list(profile["dislikes"])
    pace = profile["pace"]
    budget_style = profile["budget_style"]

    for item in learned:
        content = item["content"]
        if item["type"] == "like" and content not in likes:
            likes.append(content)
        elif item["type"] == "dislike" and content not in dislikes:
            dislikes.append(content)
        elif item["type"] == "pace":
            pace = content
        elif item["type"] == "budget_style":
            budget_style = content

    conn.execute(
        """
        INSERT INTO user_profile (user_id, likes, dislikes, pace, budget_style, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
          likes = excluded.likes,
          dislikes = excluded.dislikes,
          pace = excluded.pace,
          budget_style = excluded.budget_style,
          updated_at = excluded.updated_at
        """,
        (
            user_id,
            json.dumps(likes[-24:], ensure_ascii=False),
            json.dumps(dislikes[-24:], ensure_ascii=False),
            pace,
            budget_style,
            updated_at,
        ),
    )


def _read_profile(conn: sqlite3.Connection, user_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM user_profile WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return {
            "user_id": user_id,
            "likes": [],
            "dislikes": [],
            "pace": "轻松",
            "budget_style": "中等",
            "updated_at": None,
        }
    return {
        "user_id": row["user_id"],
        "likes": _json_list(row["likes"]),
        "dislikes": _json_list(row["dislikes"]),
        "pace": row["pace"],
        "budget_style": row["budget_style"],
        "updated_at": row["updated_at"],
    }


def _profile_stats(feedback_rows: list[sqlite3.Row], history_rows: list[sqlite3.Row]) -> dict[str, Any]:
    ratings = [_safe_int(row["rating"]) for row in feedback_rows if _safe_int(row["rating"]) is not None]
    tag_counts: dict[str, int] = {}
    for row in feedback_rows:
        for tag in _json_list(row["tags"]):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    city_counts: dict[str, int] = {}
    plan_type_counts: dict[str, int] = {}
    for row in history_rows:
        text = f"{row['user_input']} {row['final_plan'] or ''}"
        city = _extract_city(text)
        if city:
            city_counts[city] = city_counts.get(city, 0) + 1
        plan_type = _classify_plan_type(text)
        plan_type_counts[plan_type] = plan_type_counts.get(plan_type, 0) + 1

    return {
        "feedback_count": len(feedback_rows),
        "average_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "tag_counts": _top_counts(tag_counts),
        "common_cities": _top_counts(city_counts),
        "plan_types": _top_counts(plan_type_counts),
    }


def _top_counts(counts: dict[str, int], limit: int = 8) -> list[dict[str, Any]]:
    return [
        {"label": label, "count": count}
        for label, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def _extract_city(text: str) -> str | None:
    for city in ["北京", "上海", "杭州", "苏州", "南京", "广州", "深圳", "成都", "重庆", "厦门", "福州", "武汉", "西安", "长沙", "青岛", "宁波"]:
        if city in text:
            return city
    return None


def _classify_plan_type(text: str) -> str:
    if any(word in text for word in ["旅行", "一日游", "景点", "玩一天", "半日"]):
        return "旅行"
    if any(word in text for word in ["快递", "买", "办", "取", "采购"]):
        return "办事"
    if any(word in text for word in ["约会", "生日", "礼物"]):
        return "约会"
    if any(word in text for word in ["学习", "读书", "课程"]):
        return "学习"
    return "日常"


def _json_list(value: Any) -> list[str]:
    try:
        data = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in data if item]


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_task_history(
    task_id: str,
    user_id: str | None = None,
    role: str = "user",
) -> dict[str, Any] | None:
    init_db()
    where = "WHERE task_history.task_id = ?"
    params: list[Any] = [task_id]
    if user_id:
        if role in {"operator_admin", "admin"}:
            pass
        else:
            where += " AND task_history.user_id = ?"
            params.append(user_id)
    with connect() as conn:
        row = conn.execute(
            f"""
            SELECT
              task_history.task_id,
              task_history.user_id,
              task_history.user_input,
              task_history.final_plan,
              task_history.feedback,
              task_history.created_at,
              app_run_context.status AS app_status,
              CASE WHEN plan_feedback.feedback_id IS NULL THEN 0 ELSE 1 END AS has_feedback
            FROM task_history
            LEFT JOIN plan_feedback
              ON plan_feedback.task_id = task_history.task_id
            LEFT JOIN app_run_context
              ON app_run_context.task_id = task_history.task_id
            {where}
            GROUP BY task_history.task_id
            """,
            params,
        ).fetchone()
    return dict(row) if row else None
