# LifeOps API

Base URL: `http://localhost:8000`

## Health

`GET /health`

Returns:

```json
{"status": "ok"}
```

## Start Async Plan Run

`POST /runs/plan`

Request:

```json
{
  "user_input": "这周六杭州轻松玩一天，预算 500",
  "previous_result": null,
  "origin_location": null,
  "origin_city": null,
  "default_city": "杭州"
}
```

Returns:

```json
{"trace_id": "abc123"}
```

## Run Status

`GET /runs/{trace_id}`

Returns run status, accumulated events, final result when available, and error when failed.

## Run Events

`GET /runs/{trace_id}/events`

Server-sent events stream. Each event is JSON in `data:`.

Important fields:

- `phase`: `run`, `node`, `tool`, `result`, or `error`
- `node`: current node name
- `summary`: user-readable progress text
- `status`: `running`, `done`, or `error`
- `progress`: 0-100
- `result`: final plan response on completion

## Sync Plan

`POST /plan`

Synchronous planning endpoint. Useful for tests and simple scripts.

## Replan

`POST /replan`

Request includes `user_input` and `previous_result`.

## History

`GET /history?limit=20`

Returns recent saved plans.

`GET /history/{task_id}`

Returns a saved plan detail snapshot.

## Profile

`GET /profile`

Returns learned preferences, feedback stats, and recent memory events.

## Feedback

`POST /feedback`

Request:

```json
{
  "task_id": "202606010001",
  "trace_id": "abc123",
  "rating": 4,
  "tags": ["路线顺"],
  "note": "节奏合适",
  "item_feedback": [
    {"place": "西湖", "sentiment": "like"}
  ]
}
```

Returns learned preferences written to the local profile.
