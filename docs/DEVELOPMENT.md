# LifeOps Development

## Local Startup

Backend:

```powershell
cd D:\llm\LifeOps
python -m uvicorn api:app --reload
```

Frontend:

```powershell
cd D:\llm\lifeops-front
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
python -m py_compile api.py agent\graph.py agent\langgraph_app.py agent\nodes.py storage\db.py
python -m unittest tests.test_api_imports tests.test_geocoder_weather
```

Frontend:

```powershell
npm run build
```

## Notes

- `app.py` is still the Streamlit debug console.
- The production-like UI is the React app in `D:\llm\lifeops-front`.
- External search and map providers can be slow or unavailable; use `mock` providers for fast demos.
