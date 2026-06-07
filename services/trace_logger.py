from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from storage.db import connect, init_db


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def record_trace(
    trace_id: str,
    step_index: int,
    node_name: str,
    input_data: Any,
    output_data: Any,
    latency_ms: int,
    status: str = "success",
) -> None:
    init_db()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_trace (
              trace_id, step_index, node_name, input_json, output_json,
              latency_ms, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                step_index,
                node_name,
                _json(input_data),
                _json(output_data),
                latency_ms,
                status,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


@contextmanager
def traced(
    trace_id: str,
    step_index: int,
    node_name: str,
    input_data: Any,
) -> Iterator[dict[str, Any]]:
    start = time.perf_counter()
    holder: dict[str, Any] = {}
    try:
        yield holder
        output = holder.get("output")
        status = holder.get("status", "success")
    except Exception as exc:
        output = {"error": str(exc)}
        status = "error"
        raise
    finally:
        latency_ms = int((time.perf_counter() - start) * 1000)
        record_trace(trace_id, step_index, node_name, input_data, output, latency_ms, status)


def load_trace(trace_id: str) -> list[dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT step_index, node_name, input_json, output_json, latency_ms, status, created_at
            FROM agent_trace
            WHERE trace_id = ?
            ORDER BY step_index
            """,
            (trace_id,),
        ).fetchall()
    return [dict(row) for row in rows]

