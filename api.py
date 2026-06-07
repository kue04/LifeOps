from __future__ import annotations

import json
import os
import threading
import time
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from agent.graph import run_lifeops
from config import settings
from services.trace_logger import load_trace
from storage.db import get_profile, get_task_history, list_task_history, save_plan_feedback
from tools.calendar import build_ics


DEFAULT_FRONTEND_ORIGINS = ",".join([
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://192.168.0.107:5174",
    "http://192.168.195.1:5174",
    "http://192.168.10.1:5174",
])

app = FastAPI(title="LifeOps Agent API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("FRONTEND_ORIGINS", DEFAULT_FRONTEND_ORIGINS).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PlanRequest(BaseModel):
    user_input: str = Field(..., min_length=1)
    origin_location: str | None = None
    origin_city: str | None = None
    default_city: str | None = None


class ReplanRequest(BaseModel):
    user_input: str = Field(..., min_length=1)
    previous_result: dict[str, Any]
    origin_location: str | None = None
    origin_city: str | None = None
    default_city: str | None = None


class RunRequest(BaseModel):
    user_input: str = Field(..., min_length=1)
    previous_result: dict[str, Any] | None = None
    origin_location: str | None = None
    origin_city: str | None = None
    default_city: str | None = None


class ItemFeedback(BaseModel):
    place: str
    sentiment: str


class FeedbackRequest(BaseModel):
    task_id: str | None = None
    trace_id: str | None = None
    rating: int = Field(..., ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    note: str | None = None
    item_feedback: list[ItemFeedback] = Field(default_factory=list)


class CalendarExportRequest(BaseModel):
    final_plan: dict[str, Any]


class ConfirmActionRequest(BaseModel):
    plan_id: str | None = None
    trace_id: str | None = None
    action_type: str
    label: str | None = None
    items: list[Any] = Field(default_factory=list)


RUNS: dict[str, dict[str, Any]] = {}
RUNS_LOCK = threading.Lock()


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "status": "ok",
        "message": "LifeOps API is running. Open the frontend at http://localhost:5173 or call POST /runs/plan.",
        "endpoints": ["/health", "/plan", "/runs/plan", "/history", "/profile", "/feedback"],
    }


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/providers")
@app.get("/api/health/providers")
def provider_health() -> dict[str, Any]:
    providers = [
        _provider_status(
            "llm",
            settings.llm_mode,
            settings.llm_mode == "mock"
            or (settings.llm_mode == "deepseek" and bool(settings.deepseek_api_key))
            or (settings.llm_mode == "openai" and bool(settings.openai_api_key)),
            "mock 模式可用于本地演示；真实 LLM 需要配置对应 API key。",
        ),
        _provider_status(
            "weather",
            settings.weather_provider,
            settings.weather_provider in {"mock", "openmeteo"}
            or (settings.weather_provider == "openweather" and bool(settings.openweather_api_key))
            or (settings.weather_provider == "amap" and bool(settings.amap_api_key)),
            "mock/openmeteo 可直接演示；openweather/amap 需要 key。",
        ),
        _provider_status(
            "place",
            settings.place_provider,
            settings.place_provider in {"mock", "osm"}
            or (settings.place_provider == "amap" and bool(settings.amap_api_key)),
            "mock/osm 可直接演示；amap 需要 key。",
        ),
        _provider_status(
            "search",
            settings.search_provider,
            settings.search_provider in {"mock", "auto", "searchfree", "duckduckgo", "ddg", "bing", "bing_rss", "wikimedia", "wikipedia"}
            or (settings.search_provider == "bocha" and bool(settings.bocha_api_key)),
            "mock/auto/免费搜索可直接演示；bocha 需要 key 和可用额度。",
        ),
        _provider_status(
            "route",
            "amap_driving" if settings.amap_api_key else "estimated",
            True,
            "默认使用本地估算；配置 AMAP_API_KEY 后可增强驾车路由。",
        ),
    ]
    return {"status": "ok", "providers": providers}


@app.post("/plan")
@app.post("/api/plan")
def plan(request: PlanRequest) -> dict:
    return _frontend_response(run_lifeops(request.user_input, request_context=_request_context(request)))


@app.post("/replan")
@app.post("/api/replan")
def replan(request: ReplanRequest) -> dict:
    return _frontend_response(run_lifeops(request.user_input, previous_result=request.previous_result, request_context=_request_context(request)))


@app.post("/runs/plan")
@app.post("/api/runs/plan")
def start_plan_run(request: RunRequest) -> dict[str, str]:
    trace_id = uuid4().hex[:12]
    _create_run(trace_id, request.user_input)
    thread = threading.Thread(
        target=_run_plan_worker,
        args=(trace_id, request.user_input, request.previous_result, _request_context(request)),
        daemon=True,
    )
    thread.start()
    return {"trace_id": trace_id}


@app.get("/runs/{trace_id}")
@app.get("/api/runs/{trace_id}")
def run_status(trace_id: str) -> dict[str, Any]:
    with RUNS_LOCK:
        run = RUNS.get(trace_id)
        if not run:
            return {"trace_id": trace_id, "status": "unknown", "events": [], "result": None}
        return {
            "trace_id": trace_id,
            "status": run["status"],
            "events": list(run["events"]),
            "result": run.get("result"),
            "error": run.get("error"),
        }


@app.get("/runs/{trace_id}/events")
@app.get("/api/runs/{trace_id}/events")
def run_events(trace_id: str) -> StreamingResponse:
    return StreamingResponse(_event_stream(trace_id), media_type="text/event-stream")


@app.get("/trace/{trace_id}")
@app.get("/api/trace/{trace_id}")
def trace(trace_id: str) -> dict:
    return {"trace_id": trace_id, "steps": load_trace(trace_id)}


@app.get("/profile")
@app.get("/api/profile")
def profile() -> dict[str, Any]:
    return get_profile()


@app.post("/feedback")
@app.post("/api/feedback")
def feedback(request: FeedbackRequest) -> dict[str, Any]:
    return save_plan_feedback(request.model_dump())


@app.get("/history")
@app.get("/api/history")
def history(limit: int = 20) -> dict:
    return {"items": list_task_history(limit)}


@app.get("/history/{task_id}")
@app.get("/api/history/{task_id}")
def history_detail(task_id: str) -> dict[str, Any]:
    item = get_task_history(task_id)
    if not item:
        return {"found": False, "item": None, "result": None}
    final_plan = _parse_json_dict(item.get("final_plan"))
    result = _frontend_response(
        {
            "status": "success",
            "trace_id": item["task_id"],
            "final_plan": final_plan,
            "assistant_message": item.get("user_input") or "",
            "constraints": {},
            "execution_log": [],
            "tool_results": [],
        }
    )
    return {"found": True, "item": item, "result": result}


@app.post("/calendar/ics")
@app.post("/api/calendar/ics")
def calendar_ics(request: CalendarExportRequest) -> Response:
    return _ics_response(request.final_plan)


@app.get("/history/{task_id}/ics")
@app.get("/api/history/{task_id}/ics")
def history_calendar_ics(task_id: str) -> Response:
    item = get_task_history(task_id)
    if not item:
        return Response("Plan not found", status_code=404)
    return _ics_response(_parse_json_dict(item.get("final_plan")))


@app.post("/confirm-action")
@app.post("/api/confirm-action")
def confirm_action(request: ConfirmActionRequest) -> dict[str, Any]:
    return {
        "status": "confirmed",
        "execution": "not_performed",
        "requires_user_confirmation": False,
        "action_type": request.action_type,
        "label": request.label,
        "items": request.items,
        "plan_id": request.plan_id,
        "trace_id": request.trace_id,
        "message": "已记录确认。当前版本不会自动写入日历、发送消息、付款或下单。",
    }


def _create_run(trace_id: str, user_input: str) -> None:
    with RUNS_LOCK:
        RUNS[trace_id] = {
            "status": "running",
            "user_input": user_input,
            "events": [],
            "result": None,
            "error": None,
        }


def _run_plan_worker(
    trace_id: str,
    user_input: str,
    previous_result: dict[str, Any] | None,
    request_context: dict[str, Any] | None = None,
) -> None:
    try:
        result = run_lifeops(
            user_input,
            previous_result=previous_result,
            trace_id=trace_id,
            progress_callback=lambda event: _append_run_event(trace_id, event),
            request_context=request_context,
        )
        normalized = _frontend_response(result)
        with RUNS_LOCK:
            run = RUNS[trace_id]
            run["status"] = "done"
            run["result"] = normalized
    except Exception as exc:
        with RUNS_LOCK:
            if trace_id in RUNS:
                RUNS[trace_id]["status"] = "error"
                RUNS[trace_id]["error"] = str(exc)
        _append_run_event(trace_id, _run_event(trace_id, "error", "run", "执行失败", "error", {"error": str(exc)}, 100))


def _append_run_event(trace_id: str, event: dict[str, Any]) -> None:
    event = dict(event)
    if event.get("result"):
        event["result"] = _frontend_response(event["result"])
    with RUNS_LOCK:
        run = RUNS.get(trace_id)
        if not run:
            return
        run["events"].append(event)


def _run_event(
    trace_id: str,
    phase: str,
    node: str,
    summary: str,
    status: str,
    details: dict[str, Any],
    progress: int,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "trace_id": trace_id,
        "phase": phase,
        "node": node,
        "summary": summary,
        "details": details,
        "status": status,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "progress": progress,
    }
    if result is not None:
        event["result"] = result
    return event


def _event_stream(trace_id: str):
    index = 0
    while True:
        with RUNS_LOCK:
            run = RUNS.get(trace_id)
            if not run:
                yield _sse({"trace_id": trace_id, "phase": "error", "node": "run", "summary": "未找到运行任务", "status": "error", "progress": 100})
                return
            events = list(run["events"])
            done = run["status"] in {"done", "error"}

        while index < len(events):
            yield _sse(events[index])
            index += 1
        if done:
            return
        time.sleep(0.5)


def _sse(event: dict[str, Any]) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False, default=str) + "\n\n"


def _ics_response(final_plan: dict[str, Any]) -> Response:
    content = build_ics(final_plan)
    filename = _ics_filename(final_plan)
    return Response(
        content,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _ics_filename(final_plan: dict[str, Any]) -> str:
    date_text = str(final_plan.get("date") or "")[:10].replace("-", "")
    suffix = f"_{date_text}" if date_text.isdigit() else ""
    return f"lifeops_plan{suffix}.ics"


def _provider_status(name: str, provider: str, configured: bool, message: str) -> dict[str, Any]:
    if configured:
        status = "degraded" if provider in {"mock", "estimated"} else "ok"
    else:
        status = "unconfigured"
    return {
        "name": name,
        "provider": provider,
        "configured": configured,
        "status": status,
        "message": message,
    }


def _request_context(request: PlanRequest | ReplanRequest | RunRequest) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "origin_location": request.origin_location,
            "origin_city": request.origin_city,
            "default_city": request.default_city,
        }.items()
        if value
    }


def _frontend_response(result: dict[str, Any]) -> dict[str, Any]:
    final_plan = _normalize_final_plan(result.get("final_plan"), result)
    normalized = dict(result)
    normalized["constraints"] = result.get("constraints") or {}
    normalized["final_plan"] = final_plan
    normalized["assistant_message"] = result.get("assistant_message") or final_plan.get("assistant_message") or ""
    _sync_frontend_overview(final_plan, normalized["assistant_message"])
    normalized["quality_warnings"] = _normalize_quality_warnings(result)
    normalized["quality_score"] = _quality_score(final_plan, normalized["quality_warnings"], result)
    normalized["execution_log"] = _normalize_execution_log(result.get("execution_log"))
    normalized["tool_results"] = result.get("tool_results") or []
    if result.get("status") == "need_clarification":
        normalized["question"] = result.get("question")
    return normalized


def _sync_frontend_overview(final_plan: dict[str, Any], assistant_message: str) -> None:
    if not assistant_message or final_plan.get("task_type") not in {"travel", "mixed"}:
        return
    final_plan["assistant_message"] = assistant_message
    final_plan["overview"] = assistant_message
    final_plan["summary"] = assistant_message


def _parse_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_final_plan(plan: Any, result: dict[str, Any]) -> dict[str, Any]:
    plan = dict(plan or {})
    plan["travel_research"] = _normalize_travel_research(plan.get("travel_research"))
    plan["itinerary"] = [_normalize_itinerary_item(item) for item in plan.get("itinerary") or []]
    constraints = result.get("constraints") or {}
    plan["itinerary"] = _normalize_itinerary_days(plan["itinerary"], plan.get("trip_days") or constraints.get("trip_days"))
    plan["budget"] = _normalize_budget(plan.get("budget"), result.get("constraints"))
    plan["lifestyle_places"] = _normalize_lifestyle_places(plan.get("lifestyle_places"))
    plan["recommendation_basis"] = _normalize_recommendation_basis(plan.get("recommendation_basis"))
    plan.setdefault("title", "")
    plan.setdefault("goal", constraints.get("goal"))
    plan.setdefault("date", constraints.get("date_iso") or constraints.get("date"))
    plan.setdefault("weather", None)
    plan.setdefault("route", [])
    plan.setdefault("access_route", {})
    plan.setdefault("local_route", {})
    plan.setdefault("destination_validation", {})
    plan.setdefault("alternatives", [])
    plan["risks"] = plan.get("risks") or result.get("risks") or []
    plan["fallbacks"] = plan.get("fallbacks") or result.get("fallbacks") or []
    return plan


def _normalize_itinerary_item(item: Any) -> dict[str, Any]:
    item = dict(item or {})
    for key in ["time", "place", "area", "address", "reason", "cost_note"]:
        item.setdefault(key, None)
    item["day"] = _safe_day(item.get("day"))
    item["location"] = _valid_location_or_none(item.get("location"))
    item["map_url"] = _valid_url_or_none(item.get("map_url"))
    item.setdefault("play_points", [])
    item.setdefault("cost", 0)
    item["cost_known"] = bool(item.get("cost_known"))
    if not item["cost_known"] and not item.get("cost_note"):
        item["cost_note"] = "未确认票价，活动费暂不计入"
    item.setdefault("evidence", [])
    return item


def _valid_location_or_none(value: Any) -> str | None:
    if not isinstance(value, str) or "," not in value:
        return None
    lon, lat = value.split(",", 1)
    try:
        lon_value = float(lon)
        lat_value = float(lat)
    except ValueError:
        return None
    if not (-180 <= lon_value <= 180 and -90 <= lat_value <= 90):
        return None
    return f"{lon_value},{lat_value}"


def _normalize_itinerary_days(items: list[dict[str, Any]], trip_days: Any) -> list[dict[str, Any]]:
    if not items:
        return items
    if any(item.get("day") for item in items):
        for item in items:
            item["day"] = _safe_day(item.get("day")) or 1
        return items

    max_days = _safe_day(trip_days) or 1
    current_day = 1
    previous_start: int | None = None
    for index, item in enumerate(items):
        start = _time_start_minutes(item.get("time"))
        if start is not None and previous_start is not None and start + 90 < previous_start and current_day < max_days:
            current_day += 1
        elif start is None and max_days > 1:
            current_day = min(max_days, int(index * max_days / max(len(items), 1)) + 1)
        item["day"] = current_day
        if start is not None:
            previous_start = start
    return items


def _safe_day(value: Any) -> int | None:
    try:
        day = int(value)
    except (TypeError, ValueError):
        return None
    return day if day > 0 else None


def _time_start_minutes(value: Any) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    start = value.split("-", 1)[0].strip()
    parts = start.split(":", 1)
    if len(parts) != 2:
        return None
    hour_text, minute_text = parts
    try:
        return int(hour_text) * 60 + int(minute_text[:2])
    except ValueError:
        return None


def _normalize_quality_warnings(result: dict[str, Any]) -> list[str]:
    warnings = result.get("quality_warnings")
    if warnings is None:
        reflection = result.get("reflection") or {}
        if not (reflection.get("passed") is True and reflection.get("next_action") == "final"):
            warnings = reflection.get("issues") or []
    if isinstance(warnings, str):
        return [warnings]
    return [str(item) for item in (warnings or []) if item]


def _quality_score(plan: dict[str, Any], warnings: list[str], result: dict[str, Any]) -> dict[str, Any]:
    itinerary = plan.get("itinerary") or []
    sources = (plan.get("travel_research") or {}).get("sources") or []
    budget = plan.get("budget") or {}
    constraints = result.get("constraints") or {}
    text = json.dumps(plan, ensure_ascii=False)

    evidence_score = 58 + min(len(sources), 5) * 7
    if any(item.get("evidence") for item in itinerary):
        evidence_score += 10
    if not sources:
        evidence_score -= 14

    route_score = 62 + min(len(itinerary), 5) * 5
    if plan.get("local_route") or plan.get("access_route") or plan.get("route"):
        route_score += 8
    if not itinerary:
        route_score = 35

    unknown_costs = budget.get("unknown_activity_cost_items") or []
    budget_score = 72
    if budget.get("budget_limit") and budget.get("total") is not None:
        budget_score += 14 if _number_like(budget["total"]) <= _number_like(budget["budget_limit"]) else -18
    if unknown_costs:
        budget_score -= min(len(unknown_costs), 4) * 6

    weather_score = 86 if plan.get("weather") else 58
    if plan.get("fallbacks"):
        weather_score += 5

    preferences = constraints.get("preferences") or []
    if isinstance(preferences, str):
        preferences = [preferences]
    avoid = constraints.get("avoid") or []
    if isinstance(avoid, str):
        avoid = [avoid]
    hit_count = sum(1 for item in preferences if item and str(item) in text)
    avoid_count = sum(1 for item in avoid if item and str(item) in text)
    preference_score = 66 + min(hit_count, 4) * 8 - min(avoid_count, 3) * 12
    if not preferences:
        preference_score = 76

    risk_score = 68 + min(len(plan.get("fallbacks") or []), 3) * 8 + min(len(plan.get("risks") or []), 3) * 4
    if warnings:
        risk_score -= min(len(warnings), 4) * 7

    dimensions = [
        _score_dimension("evidence", "证据充分度", evidence_score, "来源、地点证据和票价依据的完整程度"),
        _score_dimension("route", "路线顺畅度", route_score, "行程点数量、路线信息和折返风险的综合估计"),
        _score_dimension("budget", "预算可信度", budget_score, "预算是否命中上限，以及未确认费用是否过多"),
        _score_dimension("weather", "天气适配", weather_score, "是否结合天气并给出对应兜底"),
        _score_dimension("preference", "偏好命中", preference_score, "是否覆盖用户偏好并避开明确排斥项"),
        _score_dimension("risk", "风险兜底", risk_score, "风险提示、备选方案和质量警告情况"),
    ]
    overall = round(sum(item["score"] for item in dimensions) / len(dimensions))
    return {"overall": overall, "dimensions": dimensions}


def _score_dimension(key: str, label: str, score: float, reason: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "score": max(0, min(round(score), 100)),
        "reason": reason,
    }


def _number_like(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _normalize_travel_research(research: Any) -> dict[str, Any]:
    research = dict(research or {})
    sources = []
    for source in research.get("sources") or []:
        url = _valid_url_or_none(source.get("url"))
        if not url:
            continue
        sources.append({
            "title": source.get("title") or url,
            "url": url,
            "content": source.get("content") or "",
        })
    research["sources"] = sources
    research.setdefault("attempts", research.get("attempts") or [])
    if not sources:
        research.setdefault("note", "当前主要基于地图和天气数据生成")
    return research


def _normalize_budget(budget: Any, constraints: Any) -> dict[str, Any]:
    budget = dict(budget or {})
    constraints = constraints or {}
    for key in ["activity_cost", "meal_budget", "transport_budget", "total"]:
        budget.setdefault(key, 0)
    budget.setdefault("budget_limit", constraints.get("budget"))
    budget.setdefault(
        "budget_usage",
        round(budget["total"] / budget["budget_limit"], 2) if budget.get("budget_limit") else None,
    )
    budget.setdefault("unknown_activity_cost_items", [])
    return budget


def _normalize_lifestyle_places(lifestyle: Any) -> dict[str, list[dict[str, Any]]]:
    lifestyle = dict(lifestyle or {})
    return {
        "foods": [_normalize_lifestyle_item(item) for item in lifestyle.get("foods") or []],
        "hotels": [_normalize_lifestyle_item(item) for item in lifestyle.get("hotels") or []],
    }


def _normalize_recommendation_basis(basis: Any) -> dict[str, Any]:
    basis = dict(basis or {})
    return {
        "answer": basis.get("answer") or "",
        "selected_places": list(basis.get("selected_places") or []),
        "top_scored_candidates": list(basis.get("top_scored_candidates") or []),
        "web_sources_count": int(_number_like(basis.get("web_sources_count"))),
        "web_query": basis.get("web_query"),
        "web_results_count": int(_number_like(basis.get("web_results_count"))),
        "food_candidates_count": int(_number_like(basis.get("food_candidates_count"))),
        "hotel_candidates_count": int(_number_like(basis.get("hotel_candidates_count"))),
    }


def _normalize_lifestyle_item(item: Any) -> dict[str, Any]:
    item = dict(item or {})
    return {
        "name": item.get("name"),
        "address": item.get("address"),
        "area": item.get("area"),
        "location": _valid_location_or_none(item.get("location")),
        "map_url": _valid_url_or_none(item.get("map_url")),
        "estimated_cost": item.get("estimated_cost"),
        "cost_known": bool(item.get("cost_known")),
        "cost_note": item.get("cost_note"),
    }


def _normalize_execution_log(log: Any) -> list[dict[str, Any]]:
    return [
        {
            "node": item.get("node"),
            "summary": item.get("summary"),
            "details": item.get("details"),
        }
        for item in (log or [])
        if isinstance(item, dict)
    ]


def _valid_url_or_none(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value.strip()
