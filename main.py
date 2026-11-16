"""
Orchard Gate - FastAPI service
==============================

Serves the qualified international coffee prospects produced by the Orchard
Gate pipeline (scrape -> clean -> LLM qualify).

The heavy pipeline (orchard_gate.py, clean.py, qualify.py) runs offline and
writes `prospect_data.json`, which is committed with the repo. The API reads
that file, so it starts instantly and needs no scraper, browser, or LLM API
key at runtime.

Endpoints:
    GET  /                 -> service health
    GET  /health           -> service health
    GET  /api/prospects    -> all qualified prospects, highest score first
    GET  /api/stats        -> aggregate counts
    POST /api/run-workflow -> reload the dataset from disk

Run locally:
    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchard_gate.api")

app = FastAPI(title="Orchard Gate API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "prospect_data.json")


class WorkflowScope(BaseModel):
    scope: Literal["full_pipeline", "scraping_only", "scoring_only"] = "full_pipeline"


class Prospect(BaseModel):
    sn: int
    company_name: str
    country: str
    buyer_category: str
    priority_score: float
    key_offerings: str
    rationale: str
    data_health_status: str
    website: Optional[str] = None
    priority_tier: Optional[str] = None


def load_prospects() -> List[Prospect]:
    """Read the committed dataset and validate it into Prospect models."""
    if not os.path.exists(DATA_FILE):
        logger.warning("Dataset not found at %s", DATA_FILE)
        return []

    with open(DATA_FILE, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    prospects: List[Prospect] = []
    for item in raw:
        try:
            prospects.append(Prospect(**item))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping malformed record: %s", exc)

    prospects.sort(key=lambda p: p.priority_score, reverse=True)
    return prospects


@app.get("/")
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "orchard-gate-api",
        "version": "1.0.0",
        "dataset": os.path.basename(DATA_FILE),
    }


@app.get("/api/prospects", response_model=List[Prospect])
async def get_prospects():
    prospects = load_prospects()
    if not prospects:
        raise HTTPException(
            status_code=503,
            detail="Prospect dataset is empty or unavailable.",
        )
    return prospects


@app.get("/api/stats")
async def get_stats():
    prospects = load_prospects()
    if not prospects:
        return {"leads": 0, "average_score": 0.0, "verified": 0, "top_score": 0.0}

    scores = [p.priority_score for p in prospects]
    tiers: dict[str, int] = {}
    for prospect in prospects:
        key = prospect.priority_tier or "D"
        tiers[key] = tiers.get(key, 0) + 1

    return {
        "leads": len(prospects),
        "average_score": round(sum(scores) / len(scores), 1),
        "top_score": max(scores),
        "verified": sum(1 for p in prospects if p.data_health_status == "Verified"),
        "tiers": tiers,
    }


@app.post("/api/run-workflow")
async def run_workflow(scope_data: WorkflowScope):
    """Reload the qualified dataset from disk.

    The scrape/qualify stages run offline (they need a browser, directory
    access, and LLM credits). This endpoint refreshes the served data so the
    dashboard can be reloaded without a redeploy.
    """
    logger.info("Workflow requested with scope: %s", scope_data.scope)

    if not os.path.exists(DATA_FILE):
        raise HTTPException(
            status_code=503,
            detail=f"Dataset missing on server: {os.path.basename(DATA_FILE)}",
        )

    prospects = load_prospects()
    logger.info("Loaded %d qualified prospects", len(prospects))

    return {
        "message": "Dataset reloaded successfully",
        "scope": scope_data.scope,
        "prospects_count": len(prospects),
    }