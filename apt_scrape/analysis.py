"""apt_scrape.analysis — LangGraph agent for per-listing AI scoring.

Scores each listing dict against a plain-text preferences file using a
single-node LangGraph StateGraph backed by OpenRouter. The graph is
designed with a single node now but structured for future extension
(e.g. retry-on-low-confidence, web-lookup nodes).

Required env vars:
    OPENROUTER_API_KEY  — OpenRouter API key
    OPENROUTER_MODEL    — OpenRouter model slug (default: google/gemini-3.1-flash-lite-preview)
    ANALYSIS_CONCURRENCY — max parallel LLM calls (default: 5)
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Optional, TypedDict

import click
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Structured output model
# ---------------------------------------------------------------------------


class NotionApartmentFields(BaseModel):
    """Structured output for one apartment listing covering all Notion DB fields.

    The LLM extracts, normalises, and populates every field from the raw
    apartment data so that the Notion push step can write consistent values
    directly without any additional parsing.
    """

    # ---- Core identification -----------------------------------------------
    title: str = Field(description="Clean, concise apartment title.")

    # ---- Pricing & size (numeric values extracted from raw strings) ---------
    rent_per_month: Optional[float] = Field(
        None,
        description="Monthly rent in EUR as a plain number. Extract from price string (e.g. '€ 1.200/mese' → 1200.0).",
    )
    size_sqm: Optional[float] = Field(
        None,
        description="Apartment size in m² as a plain number (e.g. '65 m²' → 65.0).",
    )

    # ---- Apartment characteristics -----------------------------------------
    rooms: Optional[str] = Field(
        None,
        description="Number of rooms as a short normalised string, e.g. '2' or '2 locali'.",
    )
    floor: Optional[str] = Field(
        None,
        description="Floor number or label, e.g. '3', 'piano terra', 'ultimo piano'.",
    )
    address: Optional[str] = Field(
        None,
        description=(
            "Full, geocodable address string. Include street, number, neighbourhood, "
            "city, and province where available, e.g. 'Via Roma 10, Bicocca, Milano, MI'."
        ),
    )
    energy_class: Optional[str] = Field(
        None,
        description=(
            "Energy performance class as a SINGLE letter only: A, B, C, D, E, F, or G. "
            "Extract the letter from longer feature strings; return None if not mentioned."
        ),
    )
    furnished: Optional[bool] = Field(
        None,
        description="True if furnished, False if unfurnished, None if not mentioned.",
    )
    available_from: Optional[str] = Field(
        None,
        description=(
            "Availability date in ISO 8601 format (YYYY-MM-DD), e.g. '2025-06-01'. "
            "Infer from phrases like 'libero da subito' (use today's date) or 'disponibile da luglio 2025'. "
            "Return None if not mentioned."
        ),
    )

    # ---- AI analysis --------------------------------------------------------
    ai_score: int = Field(
        ge=0,
        le=100,
        description="Match score 0–100 against the user's preferences (0 = terrible fit, 100 = perfect fit).",
    )
    ai_verdict: str = Field(
        description="Short match label, e.g. 'Strong match', 'Good match', 'Potential', 'Skip'.",
    )
    ai_reason: str = Field(
        description="1–2 sentence explanation of the score relative to the user's preferences.",
    )
    notes: Optional[str] = Field(
        None,
        description=(
            "Any other notable information worth surfacing: extra costs, special features, "
            "red flags, or caveats not captured elsewhere."
        ),
    )


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------


class AnalysisState(TypedDict):
    listing: dict
    preferences: str
    result: NotionApartmentFields | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def score_to_stars(score: int) -> str:
    """Map a 0–100 integer score to a star-emoji string."""
    if score < 20:
        return "⭐"
    if score < 40:
        return "⭐⭐"
    if score < 60:
        return "⭐⭐⭐"
    if score < 80:
        return "⭐⭐⭐⭐"
    return "⭐⭐⭐⭐⭐"


def load_preferences(path: str | None = None) -> str:
    """Load preferences from *path* (or PREFERENCES_FILE env var, or preferences.txt).

    Raises:
        FileNotFoundError: if the resolved path does not exist.
    """
    resolved = path or os.environ.get("PREFERENCES_FILE") or "preferences.txt"
    p = Path(resolved)
    if not p.exists():
        raise FileNotFoundError(f"Preferences file not found: {resolved}")
    return p.read_text(encoding="utf-8").strip()


def _format_listing_context(listing: dict) -> str:
    """Format key listing fields into a structured prompt context string."""
    detail = listing.get("detail") or {}
    title = detail.get("title") or listing.get("title", "")
    size = detail.get("size") or listing.get("sqm", "")
    floor = detail.get("floor", "")
    price = listing.get("price", "")
    rooms = listing.get("rooms", "")
    address = listing.get("detail_address") or listing.get("address", "")
    description = listing.get("detail_description", "")
    features = listing.get("detail_features") or {}
    costs = listing.get("detail_costs") or {}
    energy = listing.get("detail_energy_class", "")

    features_str = "\n".join(f"  {k}: {v}" for k, v in features.items()) if features else "  (none)"
    costs_str = "\n".join(f"  {k}: {v}" for k, v in costs.items()) if costs else "  (none)"

    return f"""Apartment: {title}
Price: {price}
Size: {size}
Rooms: {rooms}
Floor: {floor}
Address: {address}
Energy class: {energy}

Description:
{description}

Features:
{features_str}

Costs:
{costs_str}"""


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------


def _make_llm() -> ChatOpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    model = os.environ.get("OPENROUTER_MODEL", "google/gemini-3.1-flash-lite-preview")
    return ChatOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        model=model,
    )


# Module-level LLM instance (created lazily on first use via _get_llm())
_llm_instance: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    """Return a shared LLM instance, creating it on first call."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = _make_llm()
    return _llm_instance


async def _analyse_node(state: AnalysisState) -> AnalysisState:
    """Single graph node: extract & score all Notion fields from a listing."""
    llm = _get_llm()
    structured_llm = llm.with_structured_output(NotionApartmentFields)

    listing = state["listing"]
    system_prompt = (
        "You are an apartment-hunting assistant. "
        "Given a user's preferences and a raw apartment listing, produce a structured output "
        "that normalises ALL fields needed for the Notion database entry.\n\n"
        "Rules:\n"
        "- Extract numeric values from strings (prices, sizes).\n"
        "- Normalise energy class to a single letter (A–G) or null. "
        "If the 'Energy class' field is empty or garbled, check the Features section "
        "for Italian keys like 'Classe energetica', 'Efficienza energetica', or any key "
        "containing 'energ'; extract the single letter from the value.\n"
        "- Build the most complete address possible for geocoding.\n"
        "- Score the listing 0–100 against the user preferences.\n"
        "- Today's date for relative availability phrases: use the current ISO date.\n\n"
        f"USER PREFERENCES:\n{state['preferences']}"
    )
    human_prompt = f"LISTING:\n{_format_listing_context(listing)}"

    try:
        result: NotionApartmentFields = await structured_llm.ainvoke(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": human_prompt}]
        )
    except Exception:
        # Fallback: ask for raw JSON covering at minimum the required fields
        detail = listing.get("detail") or {}
        fallback_title = detail.get("title") or listing.get("title", "Untitled")
        fallback_prompt = (
            system_prompt
            + "\n\nRespond ONLY with a raw JSON object. Required keys: "
              '"title" (string), "ai_score" (int 0-100), "ai_verdict" (string), '
              '"ai_reason" (string). All other keys are optional.'
        )
        try:
            raw_response = await _get_llm().ainvoke(
                [{"role": "system", "content": fallback_prompt},
                 {"role": "user", "content": human_prompt}]
            )
            text = raw_response.content if hasattr(raw_response, "content") else str(raw_response)
            start = text.find("{")
            end = text.rfind("}") + 1
            data = json.loads(text[start:end])
            # Ensure required fields have values
            data.setdefault("title", fallback_title)
            data.setdefault("ai_score", data.pop("score", 0))
            data.setdefault("ai_verdict", data.pop("verdict", "Error"))
            data.setdefault("ai_reason", data.pop("reason", ""))
            result = NotionApartmentFields(**data)
        except Exception as e2:
            result = NotionApartmentFields(
                title=fallback_title,
                ai_score=0,
                ai_verdict="Error",
                ai_reason=str(e2),
            )

    return {**state, "result": result}


# ---------------------------------------------------------------------------
# Compiled graph (cached singleton)
# ---------------------------------------------------------------------------

_graph_instance = None


def _get_graph():
    global _graph_instance
    if _graph_instance is None:
        builder = StateGraph(AnalysisState)
        builder.add_node("analyse_listing", _analyse_node)
        builder.add_edge(START, "analyse_listing")
        builder.add_edge("analyse_listing", END)
        _graph_instance = builder.compile()
    return _graph_instance


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _model_cost_per_1m_tokens(model: str) -> float:
    """Return approximate blended cost per 1M tokens for common OpenRouter models."""
    _COSTS: dict[str, float] = {
        "google/gemini-3.1-flash-lite-preview": 0.10,
        "google/gemini-flash-1.5": 0.35,
        "google/gemini-flash-1.5-8b": 0.175,
        "openai/gpt-4o-mini": 0.30,
        "openai/gpt-4o": 7.50,
        "anthropic/claude-3-haiku": 0.50,
        "anthropic/claude-3.5-sonnet": 9.00,
        "meta-llama/llama-3.1-8b-instruct": 0.10,
    }
    for key, cost in _COSTS.items():
        if key in model:
            return cost
    return 0.50  # conservative default


async def analyse_listings(listings: list[dict], preferences: str) -> dict:
    """Score each listing in-place against *preferences*.

    Adds ai_score, ai_stars, ai_verdict, ai_reason to each listing dict.
    Runs with bounded concurrency (ANALYSIS_CONCURRENCY env var, default 5).

    Returns {"tokens_used": int, "cost_usd": float} with usage estimates.
    """
    concurrency = int(os.environ.get("ANALYSIS_CONCURRENCY", "5"))
    semaphore = asyncio.Semaphore(concurrency)
    graph = _get_graph()
    total_tokens = 0
    token_lock = asyncio.Lock()

    async def _score_one(listing: dict) -> None:
        nonlocal total_tokens
        async with semaphore:
            try:
                output = await graph.ainvoke(
                    {"listing": listing, "preferences": preferences, "result": None}
                )
                result: NotionApartmentFields = output["result"]
            except Exception as e:
                result = NotionApartmentFields(
                    title=(listing.get("detail", {}) or {}).get("title") or listing.get("title", "Untitled"),
                    ai_score=0,
                    ai_verdict="Error",
                    ai_reason=str(e),
                )

            listing["notion_fields"] = result.model_dump()
            # Backward-compatible keys consumed by notion_push and tests
            listing["ai_score"] = result.ai_score
            listing["ai_stars"] = score_to_stars(result.ai_score)
            listing["ai_verdict"] = result.ai_verdict
            listing["ai_reason"] = result.ai_reason

            # Approximate token usage: ~800 input + ~200 output per listing
            async with token_lock:
                total_tokens += 1000

    total = len(listings)
    click.echo(f"Analysing {total} listings with AI...", err=True)
    await asyncio.gather(*(_score_one(l) for l in listings))
    click.echo(f"Analysis complete.", err=True)

    model = os.environ.get("OPENROUTER_MODEL", "google/gemini-3.1-flash-lite-preview")
    cost_usd = round((total_tokens / 1_000_000) * _model_cost_per_1m_tokens(model), 6)
    return {"tokens_used": total_tokens, "cost_usd": cost_usd}
