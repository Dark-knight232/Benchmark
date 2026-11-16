# Orchard Gate — Full-Stack Integration

## Backend (FastAPI)

### Install & Run

```bash
cd "C:\Users\suraj\Downloads\orchard gate"
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The API will be available at:
- **Swagger UI**: http://localhost:8000/docs
- **POST /api/run-workflow** — triggers the full pipeline (scraping → dedup → LLM scoring)
- **GET /api/prospects** — returns qualified prospects as JSON

### Workflow Scopes

| Scope | Description |
|-------|-------------|
| `full_pipeline` | Run all 3 phases (default) |
| `scraping_only` | Phase 1 only (web scraping) |
| `scoring_only` | Phase 3 only (LLM qualification) |

## Frontend

Open `coffee_dashboard.html` in a browser **after starting the API server**, or serve it via any static server:

```bash
# Option 1: Python built-in server
python -m http.server 5500
# Then open http://localhost:5500/coffee_dashboard.html

# Option 2: VS Code Live Server extension (right-click → "Open with Live Server")
```

### Integration Flow

1. Select scope from dropdown (Full Pipeline Run / Phase 1 Only / Phase 2 Only / Refresh Leads)
2. Click **"Initiate Prospecting Workflow"** — button shows loading state
3. Backend executes selected phases sequentially with progress logging
4. On completion, frontend fetches `/api/prospects` and re-renders the table with:
   - Company Name, Country, Buyer Category
   - Priority Score (0–100, gold highlight ≥ 85)
   - Key Offerings, AI Rationale
   - Data Health Status (Verified / Partial badges)
5. Summary stats (Leads, Avg Score, Verified) update automatically

## Error Handling

- Backend returns structured JSON errors (`{ "detail": "..." }`) with appropriate HTTP codes
- Frontend catches network/timeouts and displays inline error on the button
- Backend logs pipeline steps to console with `logging.INFO`