# Release Checklist

## Scope

This checklist is for the ordinary-user travel and life-route planning MVP. It does not include internal workflow systems, external transactions, or automatic external message sending.

## Required Checks

- PRD and API docs describe `/app/*` as the main contract.
- Backend starts with mock providers and returns `200` from `/health`.
- Frontend starts with `VITE_LIFEOPS_API_BASE` pointing to the backend.
- `/app/plan` returns `status`, `task_summary`, `plan`, `tool_sources`, `risks`, and `confirmations`.
- `/app/calendar/ics` returns `403` before confirmation.
- `/app/confirm-action` returns a `confirmation_id`.
- `/app/calendar/ics` returns an ICS file after confirmation.
- `/app/audit` returns `403` for `user`.
- `/app/audit` returns audit items for `operator_admin`.
- User history and profile are scoped by `X-User-Id`.
- Test suite passes with mock providers.
- Frontend production build passes.
- No API keys or private data are committed.

## Commands

Backend:

```powershell
$env:PYTHONUTF8="1"
$env:LIFEOPS_LLM_MODE="mock"
$env:WEATHER_PROVIDER="mock"
$env:PLACE_PROVIDER="mock"
$env:SEARCH_PROVIDER="mock"
$env:AMAP_API_KEY=""
python -m unittest discover -s tests
```

Frontend:

```powershell
cd D:\llm\lifeops-front
npm run build
```

Local smoke:

```powershell
cd D:\llm\LifeOps
$env:LIFEOPS_LLM_MODE="mock"
$env:WEATHER_PROVIDER="mock"
$env:PLACE_PROVIDER="mock"
$env:SEARCH_PROVIDER="mock"
python -m uvicorn api:app --host 127.0.0.1 --port 8010

cd D:\llm\lifeops-front
$env:VITE_LIFEOPS_API_BASE="http://127.0.0.1:8010"
npm run dev -- --host 127.0.0.1 --port 5174
```
