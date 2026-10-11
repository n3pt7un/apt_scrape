"""apt_scrape.analysis — LangGraph agent for per-listing AI scoring.

Scores each listing dict against a plain-text preferences file using a
single-node LangGraph StateGraph backed by Anthropic or OpenRouter. The graph
is designed with a single node now but structured for future extension
(e.g. retry-on-low-confidence, web-lookup nodes).

Env vars (Anthropic is used when ANTHROPIC_API_KEY is set, else OpenRouter):
    ANTHROPIC_API_KEY   — Anthropic API key
    ANTHROPIC_MODEL     — Anthropic model ID (default: claude-sonnet-5-5)
    OPENROUTER_API_KEY  — OpenRouter API key
    OPENROUTER_MODEL    — OpenRouter model slug (default: google/gemini-3.1-flash-lite-preview)
    ANALYSIS_CONCURRENCY — max parallel scoring calls across batch callers (runner,
                          bulk rescore; default: 5); a one-listing rescore skips the queue
    ANALYSIS_EFFORT     — reasoning effort: low | medium | high (default: low); ignored
                          by Anthropic models without effort support (e.g. Haiku 4.5)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional, TypedDict

import click
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Base class for all LLM scoring failures."""


class LLMAPIError(LLMError):
    """Raised when the LLM API call itself fails (network, HTTP, auth error).

    ``fatal`` marks errors every later call would hit too (bad key, no permission,
    unknown model), so the batch stops instead of repeating them.
    """

    def __init__(self, message: str, fatal: bool = False):
        super().__init__(message)
        self.fatal = fatal


class LLMParseError(LLMError):
    """Raised when the LLM response cannot be parsed into structured output."""


# Module-level logger — name matches caplog logger="apt_scrape.analysis" in tests
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured output model
# ---------------------------------------------------------------------------


class NotionApartmentFields(BaseModel):
    """Structured output for one apartment listing covering all Notion DB fields.

    The LLM extracts, normalises, and populates every field from the raw
    apartment data so that the Notion push step can write consistent values
    directly without any additional parsing.

    Field order is the generation order with native structured outputs: the
    reasoning (notes, ai_reason) comes before the verdict and the score, so the
    model commits to a number only after justifying it.
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
            "city, and province where available, e.g. 'Via Massarenti 10, Massarenti, Bologna, BO'."
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
            "Availability date in ISO 8601 format (YYYY-MM-DD). Resolve 'libero da subito' to "
            "today's date and a month without a year (e.g. 'disponibile da novembre') to its next "
            "occurrence, using the date given in the instructions. Return None if not mentioned."
        ),
    )

    # ---- AI analysis (reasoning first, then verdict and score) --------------
    notes: Optional[str] = Field(
        None,
        description=(
            "Any other notable information worth surfacing: extra costs, special features, "
            "red flags, or caveats not captured elsewhere. End with 'Da verificare: ...' listing "
            "the criteria the listing data cannot confirm."
        ),
    )
    ai_reason: str = Field(
        description=(
            "1–3 sentences explaining the score: the decisive known facts for and against the "
            "user's preferences, and which important criteria are non verificabile."
        ),
    )
    ai_verdict: str = Field(
        description="Match label consistent with the score: 'Strong match', 'Good match', 'Potential' or 'Skip'.",
    )
    ai_score: int = Field(
        ge=0,
        le=100,
        description="Match score 0–100 against the user's preferences, following the scoring rubric.",
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


# ---------------------------------------------------------------------------
# Listing context (shared by scoring, rescoring and the listing chat)
# ---------------------------------------------------------------------------


def _text(value: Any) -> str:
    """Stripped string for scraped scalars; None becomes ''."""
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _readable(value: Any) -> str:
    """Scraped value as plain text: lists joined, dicts as 'label: value' pairs, never a Python repr."""
    if isinstance(value, dict):
        return "; ".join(f"{_text(k)}: {r}" for k, v in value.items() if (r := _readable(v)))
    if isinstance(value, (list, tuple)):
        return ", ".join(r for v in value if (r := _readable(v)))
    if isinstance(value, bool):
        return "yes" if value else "no"
    return _text(value)


def _label_lines(mapping: dict) -> list[str]:
    """'  Label: value' lines for a scraped label -> value table, blank entries dropped."""
    return [f"  {_text(k)}: {r}" for k, v in mapping.items() if _text(k) and (r := _readable(v))]


def has_detail_data(listing: dict) -> bool:
    """True when the listing carries a usable portal detail page (title, description or facts table)."""
    detail = _as_dict(listing.get("detail"))
    return bool(
        _text(detail.get("title"))
        or _text(detail.get("description"))
        or _text(listing.get("detail_description"))
        or _label_lines(_as_dict(detail.get("extra_info")))
        or _label_lines(_as_dict(listing.get("detail_features")))
    )


# Immobiliare search cards abbreviate floors: 'Piano T', 'Piano R', 'Piano S, 2'
_CARD_FLOOR = re.compile(r"^piano\s+(.+)$", re.IGNORECASE)
_FLOOR_LEGEND = {"T": "T = piano terra", "R": "R = piano rialzato", "S": "S = seminterrato"}

# Why the portal detail page is not in the context, by enrichment status
_DETAIL_STATUS_NOTES = {
    "blocked": "blocked by the portal's anti-bot protection",
    "error": "the fetch failed",
    "empty": "the page loaded but contained no listing data",
    "skipped": "not fetched in this run",
}


def _card_floor(raw_features: list[str]) -> str:
    """The search card's 'Piano X' token, with its abbreviations spelled out."""
    for token in raw_features:
        m = _CARD_FLOOR.match(token)
        if m:
            letters = [p.strip().upper() for p in m.group(1).split(",")]
            legend = [_FLOOR_LEGEND[p] for p in dict.fromkeys(letters) if p in _FLOOR_LEGEND]
            return f"{token} ({', '.join(legend)})" if legend else token
    return ""


def _detail_page_line(listing: dict) -> str:
    """One line saying whether the portal detail page was read, and why not."""
    status = _text(listing.get("detail_status"))
    error = _text(listing.get("detail_error"))
    if has_detail_data(listing):
        if status in ("", "ok"):
            return "Portal detail page: read."
        note = _DETAIL_STATUS_NOTES.get(status, status)
        return f"Portal detail page: the data above comes from an earlier read; the latest fetch was not usable ({note})."
    if status in _DETAIL_STATUS_NOTES:
        reason = _DETAIL_STATUS_NOTES[status] + (f": {error}" if error else "")
    elif "detail" in listing:
        reason = "the stored page came back empty, most likely blocked by the portal"
    else:
        reason = "not fetched"
    return (
        f"Portal detail page: NOT read ({reason}). Only the search-results card data above is "
        "available; the next run retries the page."
    )


def format_listing_context(listing: dict) -> str:
    """Render everything known about a listing as LLM context (scoring, rescoring and chat).

    Portal detail-page data is used where it was read; the search-card data (title,
    price, size, rooms, bathrooms, card features, description excerpt) is always
    included, as a complement and as the fallback. Data that is missing is named
    explicitly, so the model never confuses "not scraped" with "the ad lacks it".
    """
    detail = _as_dict(listing.get("detail"))
    card_title = _text(listing.get("title"))
    raw_features = [r for f in (listing.get("raw_features") or []) if (r := _readable(f))] \
        if isinstance(listing.get("raw_features"), list) else []
    facts = _label_lines(_as_dict(listing.get("detail_features")) or _as_dict(detail.get("extra_info")))
    costs = _label_lines(_as_dict(listing.get("detail_costs")) or _as_dict(detail.get("costs")))
    fact_keys = " ".join(line.lower() for line in facts)

    lines: list[str] = []
    missing: list[str] = []

    def add(label: str, value: str, missing_as: str = "") -> None:
        if value:
            lines.append(f"{label}: {value}")
        elif missing_as:
            missing.append(missing_as)

    add("Apartment", _text(detail.get("title")) or card_title, "title")
    add("Price", _text(listing.get("price")) or _text(detail.get("price")), "price")
    add("Size", _text(detail.get("size")) or _text(listing.get("sqm")), "size")
    add("Rooms", _text(listing.get("rooms")), "" if "locali" in fact_keys else "number of rooms")
    add("Bathrooms", _text(listing.get("bathrooms")), "" if "bagn" in fact_keys else "bathrooms")
    floor = _text(detail.get("floor"))
    if floor:
        add("Floor", floor)
    else:
        add("Floor (search card)", _card_floor(raw_features), "" if "piano" in fact_keys else "floor")
    address = _text(listing.get("detail_address")) or _text(detail.get("address"))
    card_address = _text(listing.get("address"))
    # Immobiliare cards repeat the title as the address: the title already carries street and area
    add("Address", address or (card_address if card_address != card_title else ""))
    area = ", ".join(p for p in (_text(listing.get("_area")), _text(listing.get("_city"))) if p)
    add("Portal search area", area)
    energy = _text(listing.get("detail_energy_class")) or _text(detail.get("energy_class"))
    add("Energy class", energy, "" if "energ" in fact_keys else "energy class")
    add("Posted", _text(listing.get("post_date")) or _text(detail.get("post_date")))
    add("Agency", _text(listing.get("detail_agency")) or _text(detail.get("agency")))

    description = _text(listing.get("detail_description")) or _text(detail.get("description"))
    snippet = _text(listing.get("description_snippet"))
    if description:
        lines += ["", "Description (portal detail page):", description]
    elif snippet:
        lines += ["", "Description (excerpt from the search results page, may be truncated):", snippet]
        missing.append("full description (only the search-page excerpt above)")
    else:
        missing.append("description")

    if facts:
        lines += ["", "Portal facts (detail page):", *facts]
    else:
        missing.append("portal facts table (heating, contract, furnishing, ...)")
    if raw_features:
        lines += ["", f"Search card features: {', '.join(raw_features)}"]
    if costs:
        lines += ["", "Costs (detail page):", *costs]
    else:
        missing.append("costs (condominium fees, deposit)")

    lines += ["", "Data availability:", f"- {_detail_page_line(listing)}"]
    if missing:
        lines.append(
            f"- Missing (not scraped; this does not mean the ad lacks them): {', '.join(missing)}."
        )
    return "\n".join(lines)


# Backward-compatible name (listing chat and older callers)
_format_listing_context = format_listing_context


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------


_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"
_DEFAULT_OPENROUTER_MODEL = "google/gemini-3.1-flash-lite-preview"
# Adaptive thinking and the answer share this cap; 16k leaves thinking room.
_MAX_OUTPUT_TOKENS = 16000
# A non-streamed call sends nothing until the whole answer is generated, so its timeout
# grows with max_tokens like the Anthropic SDK's own estimate (3600 s per 128k tokens:
# 450 s at 16k). Streamed calls (listing chat) pass this floor as an idle timeout.
_REQUEST_TIMEOUT_SEC = 180
# The SDKs back off on 429/529/5xx and connection errors, timeouts included (they cannot
# be told apart), so keep it at the SDK default: each timed-out attempt is a full timeout.
_MAX_RETRIES = 2
_REASON_MAX_CHARS = 300


def _effort() -> str:
    """Return the reasoning effort for scoring calls (ANALYSIS_EFFORT, default low)."""
    return os.environ.get("ANALYSIS_EFFORT") or "low"


def _model_name() -> str:
    """Return the model the active provider will use (Anthropic wins if keyed)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ.get("ANTHROPIC_MODEL") or _DEFAULT_ANTHROPIC_MODEL
    return os.environ.get("OPENROUTER_MODEL") or _DEFAULT_OPENROUTER_MODEL


def _request_timeout(max_tokens: int) -> float:
    """Seconds a non-streamed call may take to generate *max_tokens* (never below the floor)."""
    return max(float(_REQUEST_TIMEOUT_SEC), 3600 * max_tokens / 128_000)


def _make_llm(max_tokens: int = _MAX_OUTPUT_TOKENS, *, request_timeout: float | None = None) -> BaseChatModel:
    """Build the provider's chat model; *request_timeout* defaults to the non-streamed budget."""
    timeout = request_timeout or _request_timeout(max_tokens)
    if os.environ.get("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            model=_model_name(),
            max_tokens=max_tokens,
            default_request_timeout=timeout,
            max_retries=_MAX_RETRIES,
        )
        # Some Anthropic models (e.g. Haiku 4.5) reject output_config.effort, so only
        # send it to models whose profile declares effort levels. getattr: older
        # langchain-anthropic releases have no profile and simply skip effort.
        profile = getattr(llm, "profile", None) or {}
        if _effort() in (profile.get("reasoning_effort_levels") or ()):
            llm.reasoning_effort = _effort()
        return llm

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        base_url="https://openrouter.ai/api/v1",
        model=_model_name(),
        timeout=timeout,
        max_retries=_MAX_RETRIES,
        # Sent raw: ChatOpenAI would rename max_tokens to max_completion_tokens,
        # and OpenRouter's unified reasoning control is the `reasoning` object.
        extra_body={
            "max_tokens": max_tokens,
            "reasoning": {"effort": _effort()},
        },
    )


# Module-level LLM instance (created lazily on first use via _get_llm())
_llm_instance: BaseChatModel | None = None


def _get_llm() -> BaseChatModel:
    """Return a shared LLM instance, creating it on first call."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = _make_llm()
    return _llm_instance


def _short(message: str) -> str:
    """One-line error text, short enough for ai_reason and the job log."""
    text = " ".join(str(message).split())
    return text if len(text) <= _REASON_MAX_CHARS else text[: _REASON_MAX_CHARS - 1] + "…"


def _api_error_types() -> tuple[type[BaseException], ...]:
    """Provider SDK errors raised by the call itself (HTTP status, connection, timeout)."""
    types: list[type[BaseException]] = [asyncio.TimeoutError]
    try:
        import anthropic

        types.append(anthropic.APIError)
    except ImportError:  # pragma: no cover - dependency is always installed
        pass
    try:
        import openai

        types.append(openai.APIError)
    except ImportError:  # pragma: no cover - dependency is always installed
        pass
    return tuple(types)


def _as_api_error(exc: BaseException) -> LLMAPIError:
    """Wrap a provider error; auth, permission and unknown-model errors are fatal for the batch."""
    status = getattr(exc, "status_code", None)
    label = f"{type(exc).__name__} {status}" if status else type(exc).__name__
    return LLMAPIError(_short(f"{label}: {exc}"), fatal=status in (401, 403, 404))


def _check_stop_reason(message: Any) -> None:
    """Fail (without retrying under the same cap) on a truncated or refused response."""
    meta = getattr(message, "response_metadata", None) or {}
    reason = meta.get("stop_reason") or meta.get("finish_reason")
    if reason in ("max_tokens", "length"):
        raise LLMError(f"response truncated at the {_MAX_OUTPUT_TOKENS}-token output limit")
    if reason in ("refusal", "content_filter"):
        raise LLMError("the model declined to score this listing")


def _system_prompt(preferences: str) -> str:
    """Scoring instructions; the date is computed per call (the backend runs for days)."""
    return (
        "You are an apartment-hunting assistant. "
        "Given a user's preferences and a scraped apartment listing, produce a structured output "
        "that normalises ALL fields needed for the Notion database entry and scores the listing.\n\n"
        f"Today's date is {date.today().isoformat()}. Use it to resolve relative availability "
        "phrases ('libero da subito' → today; a month without a year → its next occurrence).\n\n"
        "Extraction rules:\n"
        "- Extract numeric values from strings (prices, sizes).\n"
        "- Normalise energy class to a single letter (A–G) or null. "
        "If the 'Energy class' line is missing or garbled, check the portal facts "
        "for Italian keys like 'Classe energetica', 'Efficienza energetica', or any key "
        "containing 'energ'; extract the single letter from the value.\n"
        "- Build the most complete address possible for geocoding (the title often names the street and area).\n"
        "- Fill a field only from what the listing states (detail page, search card or description); "
        "otherwise leave it null.\n\n"
        "Scoring rubric (weigh only known facts):\n"
        "- Check every user criterion and classify it as 'soddisfatto', 'non soddisfatto' or "
        "'non verificabile' (the listing data neither confirms nor rules it out).\n"
        "- Missing data was not scraped: it does not mean the ad lacks it. A 'non verificabile' "
        "criterion is never a failure and must not lower the score. Never claim the ad has no "
        "description, features or costs when the data section says they were not scraped.\n"
        "- A confirmed deal breaker, or a clearly failed must-have, scores 0–20.\n"
        "- No confirmed problem and every must-have confirmed: 60–100, higher the more "
        "nice-to-haves are confirmed.\n"
        "- No confirmed problem but some must-haves non verificabile: 40–69, depending on how much "
        "is confirmed; the listing is worth checking, not a reject.\n"
        "- Confirmed misses on soft preferences lower the score within its band.\n"
        "- ai_verdict must match the score: 'Skip' 0–39, 'Potential' 40–59, 'Good match' 60–79, "
        "'Strong match' 80–100.\n"
        "- In ai_reason name the decisive known facts and the important unknowns; end notes with "
        "'Da verificare: ...' listing the non verificabile criteria.\n"
        "- Write ai_reason and notes in Italian; keep ai_verdict as one of the English labels above.\n\n"
        f"USER PREFERENCES:\n{preferences}"
    )


async def _analyse_node(state: AnalysisState, config: RunnableConfig) -> AnalysisState:
    """Single graph node: extract & score all Notion fields from a listing.

    API errors (auth, rate limit, server, timeout) fail the listing without a second
    call; only an unparseable answer gets one raw-JSON retry.
    """
    llm = _get_llm()
    # Claude models without forced tool use (Sonnet 5.5, Opus 5.5) would make the
    # default tool-calling method optional; native structured outputs guarantee the schema.
    method = "json_schema" if (getattr(llm, "profile", None) or {}).get("structured_output") else "function_calling"
    # include_raw: parse failures come back as data (not exceptions) and the raw
    # message carries stop_reason.
    structured_llm = llm.with_structured_output(NotionApartmentFields, method=method, include_raw=True)

    listing = state["listing"]
    system_prompt = _system_prompt(state["preferences"])
    human_prompt = f"LISTING:\n{format_listing_context(listing)}"
    api_errors = _api_error_types()

    try:
        output = await structured_llm.ainvoke(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": human_prompt}],
            config=config,
        )
    except api_errors as e:
        raise _as_api_error(e) from e

    result = output.get("parsed") if isinstance(output, dict) else None
    if isinstance(result, NotionApartmentFields):
        return {**state, "result": result}

    _check_stop_reason(output.get("raw") if isinstance(output, dict) else None)
    parse_error = output.get("parsing_error") if isinstance(output, dict) else None
    logger.info("Structured output unparseable (%s); retrying once as raw JSON", parse_error or "no result")

    detail = listing.get("detail") or {}
    fallback_title = detail.get("title") or listing.get("title") or "Untitled"
    fallback_prompt = (
        system_prompt
        + "\n\nRespond ONLY with a raw JSON object. Required keys: "
          '"title" (string), "ai_reason" (string), "ai_verdict" (string), '
          '"ai_score" (int 0-100). All other keys are optional.'
    )
    try:
        raw_response = await llm.ainvoke(
            [{"role": "system", "content": fallback_prompt},
             {"role": "user", "content": human_prompt}],
            config=config,
        )
    except api_errors as e:
        raise _as_api_error(e) from e
    _check_stop_reason(raw_response)

    try:
        text = str(getattr(raw_response, "text", "") or raw_response)
        start = text.find("{")
        end = text.rfind("}") + 1
        data = json.loads(text[start:end])
        data.setdefault("title", fallback_title)
        for short, key in (("score", "ai_score"), ("verdict", "ai_verdict"), ("reason", "ai_reason")):
            if key not in data and short in data:
                data[key] = data.pop(short)
        # A missing ai_score fails validation: never invent a 0
        result = NotionApartmentFields(**data)
    except Exception as e2:
        raise LLMParseError(_short(f"unparseable model output: {e2}")) from e2

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


# USD per 1M tokens (input, output); thinking tokens are billed as output.
# Matched exactly or by the longest prefix (dated snapshot IDs).
_PRICES_PER_1M: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def _model_prices(model: str) -> tuple[float, float] | None:
    """(input, output) USD per 1M tokens, or None when the model is not priced here."""
    name = model.removeprefix("anthropic/").replace(".", "-")
    matches = [key for key in _PRICES_PER_1M if name == key or name.startswith(key + "-")]
    return _PRICES_PER_1M[max(matches, key=len)] if matches else None


def _usage_cost(usage_by_model: dict[str, Any]) -> tuple[int, int, float]:
    """Sum real input/output tokens across models and price them (unpriced models add 0, with a warning)."""
    input_tokens = output_tokens = 0
    cost = 0.0
    for model, usage in usage_by_model.items():
        inp = int(usage.get("input_tokens") or 0)
        out = int(usage.get("output_tokens") or 0)
        input_tokens += inp
        output_tokens += out
        prices = _model_prices(model)
        if prices is None:
            logger.warning("No price known for model %s; its %d tokens are not in the AI cost", model, inp + out)
        else:
            cost += inp / 1_000_000 * prices[0] + out / 1_000_000 * prices[1]
    return input_tokens, output_tokens, round(cost, 6)


# One concurrency limit for the batch callers (runner, bulk rescore) on the loop. A one-listing
# call (the certificate's "Rivaluta") gets its own slot instead: queued behind a run's batch it
# would wait minutes, for at most one call over the cap.
_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


def _llm_semaphore() -> asyncio.Semaphore:
    global _semaphore, _semaphore_loop
    loop = asyncio.get_running_loop()
    if _semaphore is None or _semaphore_loop is not loop:
        _semaphore = asyncio.Semaphore(int(os.environ.get("ANALYSIS_CONCURRENCY", "5")))
        _semaphore_loop = loop
    return _semaphore


def _apply_result(listing: dict, result: NotionApartmentFields) -> None:
    listing["notion_fields"] = result.model_dump()
    # Backward-compatible keys consumed by notion_push and tests
    listing["ai_score"] = result.ai_score
    listing["ai_stars"] = score_to_stars(result.ai_score)
    listing["ai_verdict"] = result.ai_verdict
    listing["ai_reason"] = result.ai_reason
    listing["ai_notes"] = result.notes
    listing.pop("ai_error", None)


def _mark_failed(listing: dict, message: str) -> None:
    """Record a failed scoring attempt; the AI-extracted fields of earlier runs are left alone.

    ai_verdict='Error' / ai_score=0 / ai_reason=<message> is the legacy marker the API
    reads as ai_status='error'; the caller decides whether to keep an older valid score.
    """
    msg = _short(message) or "AI scoring failed"
    listing["ai_error"] = msg
    listing["ai_verdict"] = "Error"
    listing["ai_score"] = 0
    listing["ai_reason"] = msg


async def analyse_listings(
    listings: list[dict], preferences: str, *, semaphore: asyncio.Semaphore | None = None
) -> dict:
    """Score each listing in-place against *preferences*; never raises for a single listing.

    On success sets ai_score, ai_stars, ai_verdict, ai_reason, ai_notes and notion_fields
    (and drops any ai_error). On failure sets ai_error plus the legacy error marker
    (ai_verdict='Error', ai_score=0, ai_reason=<message>). An auth/permission/unknown-model
    error stops the batch: the remaining listings fail with the same message, uncalled.

    Returns {"tokens_used", "input_tokens", "output_tokens", "cost_usd", "scored", "failed",
    "model"}; tokens come from the providers' usage metadata (0 when unavailable) and
    cost_usd prices them per model (input and output rates; unpriced models add 0).

    *semaphore* caps the parallel calls; by default batches share the module-wide limit
    (ANALYSIS_CONCURRENCY) and a single listing gets a private slot.
    """
    graph = _get_graph()
    if semaphore is None:
        semaphore = asyncio.Semaphore(1) if len(listings) == 1 else _llm_semaphore()
    usage = UsageMetadataCallbackHandler()
    fatal_error: str | None = None

    async def _score_one(listing: dict) -> bool:
        nonlocal fatal_error
        listing_id = listing.get("url") or listing.get("title", "unknown")
        async with semaphore:
            if fatal_error is not None:
                _mark_failed(listing, fatal_error)
                return False
            try:
                output = await graph.ainvoke(
                    {"listing": listing, "preferences": preferences, "result": None},
                    config={"callbacks": [usage]},
                )
                result = output.get("result") if isinstance(output, dict) else None
                if not isinstance(result, NotionApartmentFields):
                    raise LLMParseError("no structured result")
                _apply_result(listing, result)
                return True
            except LLMAPIError as e:
                logger.warning("Listing %s skipped: LLM API failure — %s", listing_id, e)
                if e.fatal and fatal_error is None:
                    fatal_error = str(e)
                    logger.error("Stopping AI scoring: every call would fail the same way — %s", e)
                _mark_failed(listing, str(e))
            except LLMParseError as e:
                logger.warning("Listing %s skipped: LLM parse failure — %s", listing_id, e)
                _mark_failed(listing, str(e))
            except LLMError as e:
                logger.warning("Listing %s skipped: LLM failure — %s", listing_id, e)
                _mark_failed(listing, str(e))
            except Exception as e:
                # Safety net for unexpected untyped errors (e.g. plain Exception in tests)
                logger.warning("Listing %s skipped: unexpected error — %s", listing_id, e)
                _mark_failed(listing, f"{type(e).__name__}: {e}")
            return False

    total = len(listings)
    click.echo(f"Analysing {total} listings with AI...", err=True)
    outcomes = await asyncio.gather(*(_score_one(l) for l in listings), return_exceptions=True)
    for listing, outcome in zip(listings, outcomes):
        if isinstance(outcome, BaseException):  # _score_one handles everything; defence in depth
            logger.warning("Listing %s: scoring task crashed — %s", listing.get("url"), outcome)
            _mark_failed(listing, f"{type(outcome).__name__}: {outcome}")
    scored = sum(1 for o in outcomes if o is True)
    failed = total - scored

    input_tokens, output_tokens, cost_usd = _usage_cost(usage.usage_metadata)
    click.echo(f"Analysis complete: {scored} scored, {failed} failed.", err=True)
    return {
        "tokens_used": input_tokens + output_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "scored": scored,
        "failed": failed,
        "model": _model_name(),
    }
