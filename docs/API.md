# LifeOps API

Base URL: `http://localhost:8000`

主接口使用 `/app/*`。旧的 `/plan`、`/runs/*`、`/history/*` 等路径仅作为兼容入口保留。

## Headers

MVP 使用请求头模拟用户身份：

- `X-User-Id`: 默认 `demo.user`
- `X-User-Role`: `user` 或 `operator_admin`
- `X-User-Name`: 可选展示名

## Health

`GET /health`

```json
{"status": "ok"}
```

## User Context

`GET /app/me`

返回当前用户、角色和能力开关。

## Start Async Plan Run

`POST /app/runs/plan`

```json
{
  "user_input": "这周六杭州轻松玩一天，预算 500",
  "previous_result": null,
  "origin_location": null,
  "origin_city": null,
  "default_city": "杭州"
}
```

```json
{"trace_id": "abc123"}
```

## Run Status And Events

`GET /app/runs/{trace_id}`

返回运行状态、事件、最终结果或错误。

`GET /app/runs/{trace_id}/events`

SSE 事件流。核心字段：

- `phase`: `run`、`node`、`tool`、`result` 或 `error`
- `node`: 当前节点名
- `summary`: 用户可读进度
- `status`: `running`、`done` 或 `error`
- `progress`: 0-100
- `result`: 完成时的最终计划响应

## Sync Plan And Replan

`POST /app/plan`

同步规划接口，适合测试和简单脚本。

`POST /app/replan`

请求包含 `user_input` 和 `previous_result`。

## History And Profile

`GET /app/history?limit=20`

只返回当前用户的历史计划。

`GET /app/history/{task_id}`

返回当前用户可访问的计划详情。

`GET /app/profile`

返回当前用户偏好、反馈统计和近期记忆事件。

## Feedback

`POST /app/feedback`

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

返回写入的反馈和学习到的偏好。

## Confirmation And Calendar Export

导出日历必须先确认：

`POST /app/confirm-action`

```json
{
  "action_type": "export_calendar",
  "items": []
}
```

返回 `confirmation_id`。

`POST /app/calendar/ics`

```json
{
  "final_plan": {},
  "confirmation_id": "abc123"
}
```

未提供当前用户有效确认时返回 `403`。

## Audit

`GET /app/audit?limit=50`

仅 `operator_admin` 可访问；普通用户返回 `403`。
