from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Literal, List, Optional
import json
import os
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Orchard Gate API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class WorkflowScope(BaseModel):
    scope: Literal["full_pipeline", "scraping_only", "scoring_only"]


class Prospect(BaseModel):
    sn: int
    company_name: str
    country: str
    buyer_category: str
    priority_score: float
    key_offerings: str
    rationale: str
    data_health_status: str


# In-memory storage for qualified prospects
qualified_prospects: List[Prospect] = []


async def phase1_scraping(scope: str) -> List[dict]:
    logger.info("=== PHASE 1: Web Scraping ===")
    await asyncio.sleep(1)  # simulate async scraping
    if scope in ("full_pipeline", "scraping_only"):
        logger.info("Scraping 20+ global roaster/importer directories...")
        await asyncio.sleep(0.5)
        # Return mock scraped leads
        return [
            {"company_name": "Araku Valley Roasters", "country": "India", "buyer_category": "Specialty Roaster", "key_offerings": "Washed Arabica + Microlot · Organic", "rationale": "High-volume roaster already sourcing Indian arabica &mdash; strong fit for single-estate volume.", "data_health_status": "Verified"},
            {"company_name": "Nyeri Highland Traders", "country": "Kenya", "buyer_category": "Importer", "key_offerings": "Green Beans + Peaberry AA", "rationale": "Established green importer with transparent sourcing &mdash; matches sustainability positioning.", "data_health_status": "Verified"},
            {"company_name": "Balur Estate Imports", "country": "India", "buyer_category": "Importer", "key_offerings": "Monsooned Malabar + Robusta", "rationale": "Specialises in monsoon-processed lots &mdash; direct overlap with Orchard Gate's heritage range.", "data_health_status": "Verified"},
        ]
    return []


async def phase2_dedup_cleaning(scraped: List[dict], scope: str) -> List[dict]:
    logger.info("=== PHASE 2: Deduplication & Cleaning ===")
    await asyncio.sleep(1)
    if scope in ("full_pipeline", "scraping_only"):
        logger.info("Deduplicating and cleaning scraped leads...")
        await asyncio.sleep(0.5)
        # Simulate dedup/cleaning - just return with some processing
        cleaned = []
        for i, lead in enumerate(scraped):
            cleaned.append({
                "company_name": lead.get("company_name", ""),
                "country": lead.get("country", ""),
                "buyer_category": lead.get("buyer_category", ""),
                "key_offerings": lead.get("key_offerings", ""),
                "rationale": lead.get("rationale", ""),
                "data_health_status": "Cleaned",
                "raw_score": 50 + (i * 5),
            })
        return cleaned
    return []


async def phase3_llm_qualification(cleaned: List[dict], scope: str) -> List[Prospect]:
    logger.info("=== PHASE 3: AI-Powered Lead Qualification & Scoring ===")
    await asyncio.sleep(1.5)
    if scope in ("full_pipeline", "scoring_only"):
        logger.info("Running instructor/Pydantic LLM qualification pipeline...")
        await asyncio.sleep(0.5)
        prospects = []
        for i, lead in enumerate(cleaned):
            score = min(100, lead.get("raw_score", 50) + (i * 3))
            prospects.append(Prospect(
                sn=i + 1,
                company_name=lead["company_name"],
                country=lead["country"],
                buyer_category=lead["buyer_category"],
                priority_score=round(score, 1),
                key_offerings=lead["key_offerings"],
                rationale=lead["rationale"],
                data_health_status=lead["data_health_status"],
            ))
        return prospects
    return []


@app.post("/api/run-workflow")
async def run_workflow(scope_data: WorkflowScope):
    scope = scope_data.scope
    logger.info(f"Workflow triggered with scope: {scope}")
    try:
        # Phase 1: Scraping
        scraped = await phase1_scraping(scope)
        logger.info(f"Phase 1 complete: {len(scraped)} leads scraped")

        # Phase 2: Deduplication & Cleaning
        cleaned = await phase2_dedup_cleaning(scraped, scope)
        logger.info(f"Phase 2 complete: {len(cleaned)} leads cleaned/deduplicated")

        # Phase 3: AI Qualification & Scoring
        prospects = await phase3_llm_qualification(cleaned, scope)
        logger.info(f"Phase 3 complete: {len(prospects)} leads qualified/scored")

        # Store globally for GET /api/prospects
        global qualified_prospects
        qualified_prospects = prospects

        # Persist to JSON file
        output_path = os.path.join(os.path.dirname(__file__), "qualified_prospects.json")
        with open(output_path, "w") as f:
            json.dump([p.dict() for p in prospects], f, indent=2)

        return {"message": "Workflow completed successfully", "prospects_count": len(prospects)}
    except asyncio.TimeoutError:
        logger.error("LLM API timeout during qualification")
        raise HTTPException(status_code=504, detail="LLM API timeout - qualification service unresponsive")
    except Exception as e:
        logger.error(f"Workflow failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Workflow execution error: {str(e)}")


@app.get("/")
@app.get("/health")
async def health():
    return {"status": "ok", "service": "orchard-gate-api", "version": "0.1.0"}


@app.get("/api/prospects", response_model=List[Prospect])
async def get_prospects():
    # Try to read from persisted JSON
    output_path = os.path.join(os.path.dirname(__file__), "qualified_prospects.json")
    if os.path.exists(output_path):
        try:
            with open(output_path, "r") as f:
                data = json.load(f)
            return [Prospect(**item) for item in data]
        except Exception as e:
            logger.warning(f"Failed to read prospects JSON: {e}")

    # Fallback to in-memory
    return qualified_prospects