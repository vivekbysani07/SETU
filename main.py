"""
Setu backend — FastAPI + SQLAlchemy.

Run locally:
    pip install -r requirements.txt
    python seed_data.py        # creates setu.db and seeds region data
    uvicorn main:app --reload

Deploy: see Dockerfile / README.md for Cloud Run instructions.
"""
import os

# Load .env into the real process environment BEFORE any local module reads
# os.getenv() at import time (ai_client.py reads GEMINI_API_KEY, database.py
# reads DATABASE_URL, both as soon as they're imported below). Without this
# call, a .env file is silently ignored and everything falls back to
# offline-mock mode even with a correct key in .env — this was a real bug,
# not something you did wrong.
from dotenv import load_dotenv
load_dotenv()

from datetime import datetime
from typing import Optional, List

import secrets
from fastapi import FastAPI, Depends, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import Base, engine, get_db, DATABASE_URL
from models import Region, CitizenRequest
import ai_client
from seed_data import COUNTRIES, seed

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

Base.metadata.create_all(bind=engine)
seed()  # no-op if already seeded

app = FastAPI(title="Setu API", description="Citizen demand → national priority, across BRICS nations.")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def serve_frontend():
    """Running `python main.py` (or `uvicorn main:app`) and opening this URL
    gets you the full app — frontend included, no separate step needed."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/health")
def health():
    """Lets the frontend (and you) confirm at a glance whether requests are
    being classified by a real Gemini API key or the offline mock, and which
    database is currently active."""
    return {
        "status": "ok",
        "ai_mode": "live (Gemini)" if ai_client.GEMINI_API_KEY else "offline mock — set GEMINI_API_KEY",
        "database": "sqlite (local file)" if DATABASE_URL.startswith("sqlite") else "postgres / cloud sql",
    }


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Admin login (policymaker portal). Set ADMIN_ID / ADMIN_PASSWORD in the environment.
# ---------------------------------------------------------------------------
ADMIN_ID = os.getenv("ADMIN_ID", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "setu@123")
if not os.getenv("ADMIN_PASSWORD"):
    print("WARNING: using the default admin password — set ADMIN_ID and ADMIN_PASSWORD before deploying.")
_admin_tokens = set()


class LoginRequest(BaseModel):
    user_id: str
    password: str


@app.post("/api/admin/login")
def admin_login(p: LoginRequest):
    ok_id = secrets.compare_digest(p.user_id.encode(), ADMIN_ID.encode())
    ok_pw = secrets.compare_digest(p.password.encode(), ADMIN_PASSWORD.encode())
    if not (ok_id and ok_pw):
        raise HTTPException(401, "Invalid user ID or password")
    token = secrets.token_urlsafe(32)
    _admin_tokens.add(token)
    return {"token": token}


def require_admin(authorization: Optional[str] = Header(None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token not in _admin_tokens:
        raise HTTPException(401, "Admin login required")


class SubmitRequest(BaseModel):
    country_code: str
    region: str
    citizen_id: str
    channel: str = "Text / web form"
    text: str


class BriefRequest(BaseModel):
    country_code: str
    region: str
    sector: str


# ---------------------------------------------------------------------------
# Scoring helpers (mirrors the frontend's formula so both stay consistent)
# ---------------------------------------------------------------------------

def region_lookup(db: Session, country_code: str):
    regions = db.query(Region).filter(Region.country_code == country_code).all()
    return {r.name: r for r in regions}


def compute_groups(requests: List[CitizenRequest], regions: dict):
    groups = {}
    for r in requests:
        key = (r.region, r.sector)
        groups.setdefault(key, []).append(r)

    scored = []
    for (region, sector), items in groups.items():
        count = len(items)
        avg_severity = sum(i.severity for i in items) / count
        m = regions.get(region)
        poverty, infra, investment = (m.poverty_index, m.infra_score, m.investment_level) if m else (0.3, 0.5, 0.4)
        raw = count * avg_severity * (1 + poverty) * (1 + (1 - infra)) * (1 + (1 - investment))
        scored.append({
            "region": region, "sector": sector, "count": count,
            "avg_severity": round(avg_severity, 2), "raw": raw,
            "poverty": poverty, "infra": infra, "investment": investment,
            "sample_summaries": [i.summary for i in items[:3]],
        })
    max_raw = max([s["raw"] for s in scored], default=1) or 1
    for s in scored:
        s["score"] = round(s["raw"] / max_raw * 100)
    scored.sort(key=lambda s: -s["score"])
    return scored


def compute_hotspots(requests: List[CitizenRequest], regions: dict):
    by_region = {}
    for r in requests:
        by_region.setdefault(r.region, []).append(r)

    hotspots = []
    for name, m in regions.items():
        items = by_region.get(name, [])
        count = len(items)
        avg_severity = (sum(i.severity for i in items) / count) if count else 0
        raw = count * avg_severity * (1 + m.poverty_index) * (1 + (1 - m.infra_score)) * (1 + (1 - m.investment_level)) if count else 0
        hotspots.append({"region": name, "count": count, "raw": raw})
    max_raw = max([h["raw"] for h in hotspots], default=1) or 1
    for h in hotspots:
        h["intensity"] = round(h["raw"] / max_raw * 100)
    hotspots.sort(key=lambda h: -h["intensity"])
    return hotspots


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/countries")
def list_countries():
    return [{"code": code, "label": label} for code, label in COUNTRIES.items()]


@app.get("/api/regions")
def list_regions(country_code: str = Query(...), db: Session = Depends(get_db)):
    regions = db.query(Region).filter(Region.country_code == country_code).all()
    if not regions:
        raise HTTPException(404, f"Unknown country_code '{country_code}'")
    return [
        {"name": r.name, "poverty_index": r.poverty_index, "infra_score": r.infra_score,
         "investment_level": r.investment_level}
        for r in regions
    ]


@app.post("/api/requests")
def submit_request(payload: SubmitRequest, db: Session = Depends(get_db)):
    if not payload.text.strip():
        raise HTTPException(400, "text must not be empty")
    if not db.query(Region).filter(
        Region.country_code == payload.country_code, Region.name == payload.region
    ).first():
        raise HTTPException(400, f"Unknown region '{payload.region}' for country '{payload.country_code}'")

    try:
        classified = ai_client.classify_request(payload.text)
    except Exception as e:
        raise HTTPException(502, f"AI classification failed: {e}")

    record = CitizenRequest(
        country_code=payload.country_code,
        region=payload.region,
        citizen_id=payload.citizen_id,
        channel=payload.channel,
        original_text=payload.text,
        detected_language=classified.get("detected_language", "Unknown"),
        translated_text=classified.get("translated_english", payload.text),
        sector=classified.get("sector", "Other"),
        severity=classified.get("severity", 3),
        severity_reason=classified.get("severity_reason", ""),
        summary=classified.get("summary", payload.text[:140]),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _serialize(record)


@app.get("/api/requests", dependencies=[Depends(require_admin)])
def list_requests(country_code: str = Query(...), db: Session = Depends(get_db)):
    rows = (
        db.query(CitizenRequest)
        .filter(CitizenRequest.country_code == country_code)
        .order_by(CitizenRequest.created_at.desc())
        .all()
    )
    return [_serialize(r) for r in rows]


@app.get("/api/my-requests")
def my_requests(country_code: str = Query(...), citizen_id: str = Query(...), db: Session = Depends(get_db)):
    rows = (
        db.query(CitizenRequest)
        .filter(CitizenRequest.country_code == country_code, CitizenRequest.citizen_id == citizen_id)
        .order_by(CitizenRequest.created_at.desc())
        .all()
    )
    if not rows:
        return []

    all_rows = db.query(CitizenRequest).filter(CitizenRequest.country_code == country_code).all()
    regions = region_lookup(db, country_code)
    scored = compute_groups(all_rows, regions)
    rank_index = {(g["region"], g["sector"]): i for i, g in enumerate(scored)}
    group_count = {(g["region"], g["sector"]): g["count"] for g in scored}

    out = []
    for r in rows:
        key = (r.region, r.sector)
        idx = rank_index.get(key, -1)
        if 0 <= idx < 3:
            status = "Flagged as high priority"
        elif group_count.get(key, 0) >= 2:
            status = "Under review — gaining traction"
        else:
            status = "Logged, awaiting more reports"
        item = _serialize(r)
        item["status"] = status
        out.append(item)
    return out


@app.get("/api/dashboard", dependencies=[Depends(require_admin)])
def dashboard(country_code: str = Query(...), db: Session = Depends(get_db)):
    regions = region_lookup(db, country_code)
    if not regions:
        raise HTTPException(404, f"Unknown country_code '{country_code}'")
    rows = db.query(CitizenRequest).filter(CitizenRequest.country_code == country_code).all()

    sector_totals = {}
    channel_totals = {}
    for r in rows:
        sector_totals[r.sector] = sector_totals.get(r.sector, 0) + 1
        channel_totals[r.channel] = channel_totals.get(r.channel, 0) + 1

    return {
        "country_code": country_code,
        "total_requests": len(rows),
        "regions_reporting": len({r.region for r in rows}),
        "top_sector": max(sector_totals, key=sector_totals.get) if sector_totals else None,
        "sector_totals": sector_totals,
        "channel_totals": channel_totals,
        "hotspots": compute_hotspots(rows, regions),
        "ranked_projects": compute_groups(rows, regions)[:6],
    }


@app.post("/api/brief", dependencies=[Depends(require_admin)])
def brief(payload: BriefRequest, db: Session = Depends(get_db)):
    regions = region_lookup(db, payload.country_code)
    m = regions.get(payload.region)
    if not m:
        raise HTTPException(404, "Unknown region")
    rows = (
        db.query(CitizenRequest)
        .filter(
            CitizenRequest.country_code == payload.country_code,
            CitizenRequest.region == payload.region,
            CitizenRequest.sector == payload.sector,
        )
        .all()
    )
    if not rows:
        raise HTTPException(404, "No requests found for this region/sector")
    avg_severity = sum(r.severity for r in rows) / len(rows)
    try:
        return ai_client.generate_brief(
            payload.region, payload.sector, len(rows), avg_severity,
            m.poverty_index, m.infra_score, m.investment_level,
            [r.summary for r in rows[:3]],
        )
    except Exception as e:
        raise HTTPException(502, f"Brief generation failed: {e}")


@app.delete("/api/requests", dependencies=[Depends(require_admin)])
def reset_requests(country_code: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(CitizenRequest)
    if country_code:
        q = q.filter(CitizenRequest.country_code == country_code)
    deleted = q.delete()
    db.commit()
    return {"deleted": deleted}


def _e(v):
    """Neutralise < and > so free text can never inject markup into the dashboard."""
    return v.replace("<", "&lt;").replace(">", "&gt;") if isinstance(v, str) else v


def _serialize(r: CitizenRequest):
    return {
        "id": r.id, "country_code": r.country_code, "region": r.region,
        "citizen_id": r.citizen_id, "channel": _e(r.channel),
        "original_text": _e(r.original_text), "detected_language": _e(r.detected_language),
        "translated_text": _e(r.translated_text), "sector": r.sector,
        "severity": r.severity, "severity_reason": _e(r.severity_reason),
        "summary": _e(r.summary), "created_at": r.created_at.isoformat(),
    }


if __name__ == "__main__":
    # This is the "run the main program" entry point: `python main.py`
    # starts the API, serves the frontend at the same address, and uses
    # whatever GEMINI_API_KEY / DATABASE_URL are set in the environment.
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"\nSetu running at http://127.0.0.1:{port}  (open this in your browser)")
    print(f"API docs at      http://127.0.0.1:{port}/docs\n")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
