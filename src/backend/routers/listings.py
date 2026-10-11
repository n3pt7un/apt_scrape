"""backend.routers.listings — Listing queries, triage, AI chat/rescore, geocoding and Notion push.

Route order matters: static paths (/seen, /rescore, /geocode, /notion-push) are
declared before the int-typed /{listing_id} routes.
"""
import json as _json_mod
import logging
import os
from datetime import datetime, timezone
from typing import Any, Literal, Optional, get_args

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, or_, update
from sqlmodel import Session, select

from backend import geocoding, listing_chat
from backend.db import Job, Listing, SearchConfig, get_session
from backend.parsing import (
    as_dict, clean_str, detail_facts, detail_status_of, listing_address, load_raw, parse_price,
    parse_rooms, parse_sqm, scraped_available_from, scraped_bathrooms, scraped_floor,
    scraped_furnished,
)
from apt_scrape.notion_push import mark_notion_duplicates, push_listings
from apt_scrape.sites.base import clean_agency_name

router = APIRouter()
logger = logging.getLogger(__name__)

TriageStatus = Literal["preferito", "scartato", "contattato"]
TRIAGE_STATUSES: tuple[str, ...] = get_args(TriageStatus)
AiStatus = Literal["ok", "error", "none"]


def _utcnow() -> datetime:
    """Naive UTC timestamp, matching the other datetime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _number(value: Any) -> Optional[float]:
    """Accept only real numbers (AI-extracted fields may hold anything)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def ai_status_of(ai_score: Optional[int], ai_verdict: Optional[str]) -> str:
    """'error' when the last scoring failed, 'ok' when scored, 'none' when never scored."""
    if ai_verdict == "Error":
        return "error"
    if ai_score is not None:
        return "ok"
    return "none"


def listing_summary(lst: Listing, config_name: str = "", raw: Optional[dict] = None) -> dict:
    """Listing row -> API dict: every column except raw_json, plus fields derived from raw_json.

    Run attribution: job_id / scraped_at = the run that first found the listing,
    last_job_id / last_seen_at = the latest run that saw it again. Rows saved before
    2026-10-11 hold the last run that saw them in job_id / scraped_at instead (the old
    upsert rewrote both): first_seen_exact is False for them.
    """
    if raw is None:
        raw = load_raw(lst.raw_json)
    fields = as_dict(raw.get("notion_fields"))
    detail = as_dict(raw.get("detail"))
    detail_status = detail_status_of(raw)

    d = lst.model_dump()
    d.pop("raw_json", None)
    d["config_name"] = config_name

    price_eur = parse_price(lst.price or "") or _number(fields.get("rent_per_month"))
    sqm_num = (
        parse_sqm(lst.sqm or "")
        or parse_sqm(clean_str(detail.get("size")) or "")
        or _number(fields.get("size_sqm"))
    )
    rooms_num = parse_rooms(lst.rooms or "") or parse_rooms(clean_str(fields.get("rooms")) or "")
    photos = detail.get("photos") if isinstance(detail.get("photos"), list) else []
    first_photo = next((p for p in photos if isinstance(p, str) and p.strip()), None)
    features = raw.get("raw_features")
    description = clean_str(raw.get("description_snippet"))
    if description is None and clean_str(raw.get("detail_description")):
        description = clean_str(raw.get("detail_description"))[:300]
    # Portal facts beat the AI's reading for floor/furnished (the AI often guessed them from
    # the title); the AI value fills in when the portal says nothing.
    furnished = scraped_furnished(raw)
    if furnished is None and isinstance(fields.get("furnished"), bool):
        furnished = fields["furnished"]

    d.update({
        "source": clean_str(raw.get("source")) or clean_str(detail.get("source")),
        "thumbnail": clean_str(raw.get("thumbnail")) or first_photo,
        "address": listing_address(raw),
        "description_snippet": description,
        "price_eur": price_eur if price_eur and price_eur > 0 else None,
        "sqm_num": sqm_num if sqm_num and sqm_num > 0 else None,
        "rooms_num": rooms_num,
        "price_per_sqm": (
            round(price_eur / sqm_num, 1) if price_eur and sqm_num and price_eur > 0 and sqm_num > 0 else None
        ),
        "ai_status": ai_status_of(lst.ai_score, lst.ai_verdict),
        "ai_reason": clean_str(raw.get("ai_reason")) or clean_str(fields.get("ai_reason")),
        "ai_notes": clean_str(fields.get("notes")),
        "energy_class": (
            clean_str(raw.get("detail_energy_class"))
            or clean_str(fields.get("energy_class"))
            or clean_str(detail.get("energy_class"))
        ),
        "furnished": furnished,
        "available_from": clean_str(fields.get("available_from")) or scraped_available_from(raw),
        "floor": scraped_floor(raw) or clean_str(fields.get("floor")),
        "bathrooms": scraped_bathrooms(raw),
        # Older scrapes glued UI labels into the name ("AgenziaBologna ImmobiliareMostra Telefono")
        "agency": clean_agency_name(
            clean_str(raw.get("detail_agency")) or clean_str(detail.get("agency")) or ""
        ) or None,
        "facts": [{"label": k, "value": v} for k, v in detail_facts(raw).items()],
        "features": [str(f) for f in features if f] if isinstance(features, list) else [],
        "post_date": clean_str(raw.get("post_date")) or clean_str(detail.get("post_date")),
        "detail_status": detail_status,
        "detail_error": clean_str(raw.get("detail_error")) if detail_status != "ok" else None,
        "first_seen_at": lst.scraped_at,
        "first_seen_exact": bool(lst.first_seen_exact),
        "last_seen_at": d.get("last_seen_at") or lst.scraped_at,
        "last_job_id": d.get("last_job_id") or lst.job_id,
    })
    return d


def _config_names(session: Session, config_ids: set[int]) -> dict[int, str]:
    if not config_ids:
        return {}
    return {
        c.id: c.name
        for c in session.exec(select(SearchConfig).where(SearchConfig.id.in_(config_ids))).all()
    }


def _summary_for(session: Session, lst: Listing, raw: Optional[dict] = None) -> dict:
    cfg = session.get(SearchConfig, lst.config_id)
    return listing_summary(lst, cfg.name if cfg else "", raw)


def _get_listing_or_404(session: Session, listing_id: int) -> Listing:
    lst = session.get(Listing, listing_id)
    if not lst:
        raise HTTPException(404, "Listing not found")
    return lst


def _raw_with_row_fallbacks(lst: Listing) -> dict:
    """Parsed raw_json with the row's core columns filled in where raw is missing them.

    This is the LLM input (chat and rescore, both rendered by
    analysis.format_listing_context): never write it back as the row's raw_json.
    """
    raw = load_raw(lst.raw_json)
    for key in ("url", "title", "price", "sqm", "rooms"):
        if not raw.get(key) and getattr(lst, key):
            raw[key] = getattr(lst, key)
    return raw


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def _triage_condition(triage: str):
    """'preferito,none' -> triage_status IN ('preferito') OR triage_status IS NULL."""
    tokens = {t.strip().lower() for t in triage.split(",") if t.strip()}
    invalid = tokens - {*TRIAGE_STATUSES, "none"}
    if invalid:
        raise HTTPException(422, f"Invalid triage value(s): {sorted(invalid)}. "
                                 f"Allowed: {[*TRIAGE_STATUSES, 'none']}")
    conds = []
    statuses = sorted(tokens - {"none"})
    if statuses:
        conds.append(Listing.triage_status.in_(statuses))
    if "none" in tokens:
        conds.append(Listing.triage_status.is_(None))
    return or_(*conds) if conds else None


def _ai_status_condition(ai_status: str):
    not_error = or_(Listing.ai_verdict.is_(None), Listing.ai_verdict != "Error")
    if ai_status == "error":
        return Listing.ai_verdict == "Error"
    if ai_status == "ok":
        return and_(Listing.ai_score.is_not(None), not_error)
    return and_(Listing.ai_score.is_(None), not_error)


@router.get("")
def list_listings(
    config_id: Optional[int] = Query(None),
    job_id: Optional[int] = Query(None, description="Listings this run found first"),
    run: Optional[int] = Query(None, description="A run's listings as the SPA's run filter shows them: "
                                                  "found first by it, or last seen by it"),
    min_score: Optional[int] = Query(None),
    max_score: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    triage: Optional[str] = Query(None, description="Comma list of triage statuses; 'none' = untriaged"),
    unseen: Optional[bool] = Query(None, description="true: never opened; false: opened at least once"),
    ai_status: Optional[AiStatus] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    # id breaks scraped_at ties so offset pagination is stable
    stmt = select(Listing).order_by(Listing.scraped_at.desc(), Listing.id.desc())
    if config_id is not None:
        stmt = stmt.where(Listing.config_id == config_id)
    if job_id is not None:
        stmt = stmt.where(Listing.job_id == job_id)
    if run is not None:
        stmt = stmt.where(or_(Listing.job_id == run, Listing.last_job_id == run))
    if min_score is not None:
        stmt = stmt.where(Listing.ai_score >= min_score)
    if max_score is not None:
        stmt = stmt.where(Listing.ai_score <= max_score)
    if search:
        q = f"%{search}%"
        stmt = stmt.where(
            or_(
                Listing.title.like(q),
                Listing.area.like(q),
                Listing.city.like(q),
            )
        )
    if triage:
        cond = _triage_condition(triage)
        if cond is not None:
            stmt = stmt.where(cond)
    if unseen is not None:
        stmt = stmt.where(Listing.seen_at.is_(None) if unseen else Listing.seen_at.is_not(None))
    if ai_status is not None:
        stmt = stmt.where(_ai_status_condition(ai_status))
    stmt = stmt.offset(offset).limit(limit)
    listings = session.exec(stmt).all()

    configs = _config_names(session, {lst.config_id for lst in listings})
    return [listing_summary(lst, configs.get(lst.config_id, "")) for lst in listings]


class NotionPushRequest(BaseModel):
    listing_ids: list[int]


@router.post("/notion-push")
async def notion_push(
    body: NotionPushRequest,
    session: Session = Depends(get_session),
):
    if not body.listing_ids:
        raise HTTPException(status_code=400, detail="listing_ids must not be empty")

    api_key = os.environ.get("NOTION_API_KEY", "")
    apartments_db_id = os.environ.get("NOTION_APARTMENTS_DB_ID", "")
    if not api_key or not apartments_db_id:
        raise HTTPException(status_code=503, detail="Notion credentials not configured")

    # Fetch DB records
    records = {
        lst.id: lst
        for lst in session.exec(
            select(Listing).where(Listing.id.in_(body.listing_ids))
        ).all()
    }

    # Reconstruct full dicts from raw_json, overlay live DB fields
    listing_dicts = []
    for lid in body.listing_ids:
        rec = records.get(lid)
        if rec is None:
            continue
        try:
            d = _json_mod.loads(rec.raw_json or "{}")
        except Exception:
            d = {}
        d["ai_score"] = rec.ai_score
        d["ai_verdict"] = rec.ai_verdict
        d["notion_page_id"] = rec.notion_page_id
        # Coordinates the backend already geocoded: push_listings skips Nominatim for them
        d["lat"], d["lon"] = rec.lat, rec.lon
        d["_db_id"] = rec.id  # carry DB id for write-back
        listing_dicts.append(d)

    if not listing_dicts:
        return {"pushed": 0, "skipped": 0, "errors": []}

    # 1. Dedup check
    await mark_notion_duplicates(listing_dicts)

    # 2. Push non-skipped
    to_push = [d for d in listing_dicts if not d.get("notion_skipped")]
    errors: list[str] = []
    # errors captures only a top-level push failure (push_listings raises on error).
    # Per-listing failures inside push_listings are handled internally by that function.
    if to_push:
        try:
            await push_listings(to_push)
        except Exception as exc:
            errors.append(str(exc))

    # 3. Write notion_page_id back to DB (newly pushed + backfill for skipped-but-null)
    for d in listing_dicts:
        page_id = d.get("notion_page_id")
        if not page_id:
            continue
        db_id = d.get("_db_id")
        rec = records.get(db_id)
        if rec and rec.notion_page_id != page_id:
            rec.notion_page_id = page_id
            session.add(rec)
    session.commit()

    pushed = sum(
        1 for d in listing_dicts
        if not d.get("notion_skipped") and d.get("notion_page_id")
    )
    skipped = sum(1 for d in listing_dicts if d.get("notion_skipped"))

    return {"pushed": pushed, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Bulk / static routes (must stay above the /{listing_id} routes)
# ---------------------------------------------------------------------------


class SeenBulkRequest(BaseModel):
    ids: list[int] = Field(default_factory=list)
    all: bool = False


@router.post("/seen")
def mark_seen_bulk(body: SeenBulkRequest, session: Session = Depends(get_session)):
    """Mark many listings as seen (only those never seen before)."""
    if not body.all and not body.ids:
        return {"updated": 0}
    stmt = update(Listing).where(Listing.seen_at.is_(None)).values(seen_at=_utcnow())
    if not body.all:
        stmt = stmt.where(Listing.id.in_(body.ids))
    result = session.exec(stmt)
    session.commit()
    return {"updated": result.rowcount}


class RescoreRequest(BaseModel):
    ids: list[int]


def _require_ai_key() -> None:
    if not listing_chat.has_ai_key():
        raise HTTPException(503, listing_chat.NO_AI_KEY_DETAIL)


# raw_json keys owned by analysis.analyse_listings: a rescore writes back only these.
_AI_KEYS = ("notion_fields", "ai_score", "ai_stars", "ai_verdict", "ai_reason", "ai_notes", "ai_error")


def _has_valid_score(lst: Listing) -> bool:
    return lst.ai_score is not None and lst.ai_verdict != "Error"


def _scoring_error(scored: dict) -> Optional[str]:
    """The failure message analyse_listings left on *scored*, or None when it succeeded."""
    if not scored.get("ai_error") and scored.get("ai_verdict") != "Error":
        return None
    return clean_str(scored.get("ai_error")) or clean_str(scored.get("ai_reason")) or "errore sconosciuto"


async def _rescore(session: Session, rows: list[Listing]) -> dict[int, str]:
    """Re-run AI scoring for *rows* in one batch and merge the results into the stored rows.

    Returns {listing_id: error message} for the listings whose scoring failed. A failure
    never replaces a valid previous score: those rows are left untouched (rows that had
    no valid score get the error marker, so ai_status='error' still finds them).
    """
    from apt_scrape import analysis

    try:
        preferences = analysis.load_preferences()
    except FileNotFoundError:
        raise HTTPException(503, "File delle preferenze non trovato")

    ids = [lst.id for lst in rows]
    scored = {lst.id: _raw_with_row_fallbacks(lst) for lst in rows}
    try:
        await analysis.analyse_listings(list(scored.values()), preferences)
    except Exception as exc:
        logger.exception("Rescore of %d listing(s) failed", len(ids))
        raise HTTPException(502, f"Valutazione AI non riuscita: {exc}")

    # The LLM call can take minutes: re-read the rows so a run that upserted them
    # meanwhile is not rolled back, then merge only the AI keys into the fresh raw_json.
    session.expire_all()
    fresh = session.exec(select(Listing).where(Listing.id.in_(ids))).all()

    failures: dict[int, str] = {}
    for lst in fresh:
        result = scored[lst.id]
        error = _scoring_error(result)
        if error:
            failures[lst.id] = error
            if _has_valid_score(lst):
                continue
        merged = load_raw(lst.raw_json)
        for key in _AI_KEYS:
            if key in result:
                merged[key] = result[key]
            else:
                merged.pop(key, None)
        if not error:
            # A run's earlier failed attempt, and the rescore it still owed (backend.runner)
            merged.pop("ai_last_error", None)
            merged.pop("ai_rescore_pending", None)
        lst.ai_score = result.get("ai_score")
        lst.ai_verdict = result.get("ai_verdict")
        lst.raw_json = _json_mod.dumps(merged, ensure_ascii=False)
        session.add(lst)
    session.commit()
    return failures


@router.post("/rescore")
async def rescore_bulk(body: RescoreRequest, session: Session = Depends(get_session)):
    """Re-score many listings in a single analyse_listings call."""
    _require_ai_key()
    rows = session.exec(select(Listing).where(Listing.id.in_(body.ids))).all() if body.ids else []
    if not rows:
        return {"updated": 0, "errors": 0}
    failures = await _rescore(session, list(rows))
    return {"updated": len(rows), "errors": len(failures)}


@router.post("/geocode")
async def start_geocoding(retry_failed: bool = Query(False)):
    """Start background geocoding (no-op if already running); returns the current status."""
    geocoding.start(retry_failed=retry_failed)
    return geocoding.status()


@router.get("/geocode/status")
def geocoding_status():
    return geocoding.status()


# ---------------------------------------------------------------------------
# Single-listing routes
# ---------------------------------------------------------------------------


@router.get("/{listing_id}")
def get_listing(listing_id: int, session: Session = Depends(get_session)):
    """Summary plus the full parsed raw_json and the job that first found it."""
    lst = _get_listing_or_404(session, listing_id)
    raw = load_raw(lst.raw_json)
    d = _summary_for(session, lst, raw)
    d["raw"] = raw
    job = session.get(Job, lst.job_id)
    d["job"] = (
        {"id": job.id, "status": job.status, "started_at": job.started_at, "finished_at": job.finished_at}
        if job else None
    )
    return d


class TriageRequest(BaseModel):
    status: Optional[TriageStatus] = None
    note: Optional[str] = None


@router.patch("/{listing_id}/triage")
def update_triage(listing_id: int, body: TriageRequest, session: Session = Depends(get_session)):
    """Partial update: only the fields present in the request body are changed."""
    lst = _get_listing_or_404(session, listing_id)
    fields = body.model_fields_set
    if "status" in fields:
        lst.triage_status = body.status
    if "note" in fields:
        lst.triage_note = clean_str(body.note)
    if fields:
        lst.triage_updated_at = _utcnow()
        session.add(lst)
        session.commit()
        session.refresh(lst)
    return _summary_for(session, lst)


@router.post("/{listing_id}/seen")
def mark_seen(listing_id: int, session: Session = Depends(get_session)):
    """Record the first time the owner opened this listing (later calls are no-ops)."""
    lst = _get_listing_or_404(session, listing_id)
    if lst.seen_at is None:
        lst.seen_at = _utcnow()
        session.add(lst)
        session.commit()
        session.refresh(lst)
    return _summary_for(session, lst)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    # "Pensaci bene": raise reasoning effort for this one question (Claude models with effort only).
    effort: Optional[Literal["low", "medium", "high", "xhigh", "max"]] = None

    @model_validator(mode="after")
    def _last_message_from_user(self) -> "ChatRequest":
        last = self.messages[-1]
        if last.role != "user" or not last.content.strip():
            raise ValueError("the last message must be a non-empty user message")
        return self


@router.post("/{listing_id}/chat")
async def chat_about_listing(listing_id: int, body: ChatRequest, session: Session = Depends(get_session)):
    """Stream (text/plain) an Italian answer about this listing, grounded in its data and the preferences."""
    lst = _get_listing_or_404(session, listing_id)
    _require_ai_key()
    raw = _raw_with_row_fallbacks(lst)
    summary = _summary_for(session, lst, raw)
    messages = listing_chat.build_messages(raw, summary, [m.model_dump() for m in body.messages])
    try:
        llm = listing_chat._chat_llm()
    except Exception as exc:
        raise HTTPException(503, f"Impossibile inizializzare il modello AI: {exc}")
    return StreamingResponse(
        listing_chat.stream_answer(llm, messages),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{listing_id}/chat/events")
async def chat_events_about_listing(listing_id: int, body: ChatRequest, session: Session = Depends(get_session)):
    """Same conversation as /chat, streamed as NDJSON events (status, thinking summary, text, done)."""
    lst = _get_listing_or_404(session, listing_id)
    _require_ai_key()
    raw = _raw_with_row_fallbacks(lst)
    summary = _summary_for(session, lst, raw)
    deep = body.effort in ("high", "xhigh", "max")
    messages = listing_chat.build_messages(raw, summary, [m.model_dump() for m in body.messages], deep=deep)
    try:
        llm = listing_chat.with_thinking_summaries(listing_chat._chat_llm(), effort=body.effort)
    except Exception as exc:
        raise HTTPException(503, f"Impossibile inizializzare il modello AI: {exc}")
    return StreamingResponse(
        listing_chat.stream_events(llm, messages),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{listing_id}/rescore")
async def rescore_listing(listing_id: int, session: Session = Depends(get_session)):
    """Re-run AI scoring for one listing and return its updated summary."""
    lst = _get_listing_or_404(session, listing_id)
    _require_ai_key()
    failures = await _rescore(session, [lst])
    lst = _get_listing_or_404(session, listing_id)
    if listing_id in failures and _has_valid_score(lst):  # failed, previous score kept
        raise HTTPException(502, f"Valutazione AI non riuscita, resta quella precedente: {failures[listing_id]}")
    return _summary_for(session, lst)
