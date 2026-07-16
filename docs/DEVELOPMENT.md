# LifeOps Development

## Local Startup

Backend:

```powershell
cd D:\llm\LifeOps
$env:LIFEOPS_LLM_MODE="mock"
$env:WEATHER_PROVIDER="mock"
$env:PLACE_PROVIDER="mock"
$env:SEARCH_PROVIDER="mock"
python -m uvicorn api:app --reload
```

Frontend:

```powershell
cd D:\llm\lifeops-front
$env:VITE_LIFEOPS_API_BASE="http://localhost:8000"
npm run dev -- --host 127.0.0.1 --port 5173
```

One-command local startup:

```powershell
cd D:\llm\LifeOps
.\scripts\dev.ps1
```

Open:

- API: http://localhost:8000
- Frontend: http://localhost:5173

If these ports are already occupied, use a paired alternate port:

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

## Docker Startup

Docker is optional for local development. After Docker Desktop is installed:

```powershell
cd D:\llm\LifeOps
docker compose up --build
```

The compose setup expects the frontend folder at `D:\llm\lifeops-front`.

## Configuration

Copy `.env.example` to `.env` in `D:\llm\LifeOps`.

Important values:

- `LIFEOPS_DB_PATH`: SQLite file path. Defaults to `lifeops.sqlite3`.
- `LIFEOPS_LLM_MODE`: `mock`, `deepseek`, or `openai`.
- `WEATHER_PROVIDER`: `mock`, `openmeteo`, `openweather`, or `amap`.
- `PLACE_PROVIDER`: `mock`, `osm`, or `amap`.
- `SEARCH_PROVIDER`: `mock`, `auto`, `searchfree`, `duckduckgo`, `wikimedia`, or `bocha`.
- `FRONTEND_ORIGINS`: allowed browser origins for FastAPI CORS.

Frontend config lives in `D:\llm\lifeops-front\.env`:

```env
VITE_LIFEOPS_API_BASE=http://localhost:8000
```

## Lightweight Checks

Backend:

```powershell
$env:LIFEOPS_LLM_MODE="mock"
$env:WEATHER_PROVIDER="mock"
$env:PLACE_PROVIDER="mock"
$env:SEARCH_PROVIDER="mock"
python -m unittest discover -s tests
```

Frontend:

```powershell
npm run build
```

## Notes

- `app.py` is still the Streamlit debug console.
- The production-like UI is the React app in `D:\llm\lifeops-front`.
- External search and map providers can be slow or unavailable; use `mock` providers for fast demos.
- Main API contracts live under `/app/*`; legacy routes are compatibility aliases.
