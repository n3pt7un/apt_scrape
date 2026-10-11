"""backend.listing_chat — Streaming Q&A about a single listing with the configured LLM.

The model is built fresh per request through ``_chat_llm()`` (tests swap it for
a fake). Answers are streamed as plain-text chunks; thinking/reasoning blocks
are dropped so only the visible answer reaches the client.
"""

import json
import logging
import os
import time
from datetime import date
from typing import Any, AsyncIterator, Optional

from backend.parsing import clean_str

logger = logging.getLogger(__name__)

NO_AI_KEY_DETAIL = "Nessuna chiave API AI configurata"
ERROR_MARKER = "\n\n[[ERRORE]] "
# Streamed answers: adaptive thinking and the visible text share this cap
CHAT_MAX_OUTPUT_TOKENS = 32000
TRUNCATED_NOTE = "\n\n_(Risposta troncata: ho raggiunto il limite di lunghezza. Chiedimi di continuare.)_"
REFUSED_NOTE = "\n\n_(Il modello ha interrotto la risposta e non può continuare su questo punto.)_"


def has_ai_key() -> bool:
    """True when either supported LLM provider is configured."""
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENROUTER_API_KEY"))


def _chat_llm():
    """Build a fresh chat model (not the cached scoring singleton), with room for long answers."""
    from apt_scrape.analysis import _REQUEST_TIMEOUT_SEC, _make_llm
    # Streamed: the timeout is the gap allowed between events, not the whole answer
    return _make_llm(max_tokens=CHAT_MAX_OUTPUT_TOKENS, request_timeout=_REQUEST_TIMEOUT_SEC)


def with_thinking_summaries(llm: Any, effort: Optional[str] = None) -> Any:
    """Ask Claude models with adaptive thinking to stream a readable summary of their reasoning.

    Models whose profile declares effort levels (Claude 4.6 and later) take adaptive thinking;
    anything else (Haiku 4.5, OpenRouter, test doubles) is returned unchanged. `effort`
    overrides ANALYSIS_EFFORT for this request: at low effort the model often answers
    without thinking, so the UI's "Pensaci bene" asks for high.
    """
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:  # pragma: no cover - dependency is always installed
        return llm
    levels = (llm.profile or {}).get("reasoning_effort_levels") if isinstance(llm, ChatAnthropic) else None
    if levels:
        llm.thinking = {"type": "adaptive", "display": "summarized"}
        if effort in levels:
            llm.reasoning_effort = effort
    return llm


def _load_preferences() -> Optional[str]:
    from apt_scrape.analysis import load_preferences
    try:
        return load_preferences()
    except FileNotFoundError:
        return None


def _prior_analysis(summary: dict[str, Any], detail_missing: bool = False) -> str:
    """Describe the previous AI scoring run for the system prompt."""
    status = summary.get("ai_status")
    if status == "none":
        return "Nessuna analisi AI disponibile per questo annuncio."
    if status == "error":
        return "L'analisi AI precedente non è riuscita: non ci sono punteggio né giudizio affidabili."
    lines = [
        "Attenzione: è stata calcolata senza la pagina di dettaglio del portale, su dati incompleti; "
        "se dice che mancano informazioni che compaiono nell'annuncio qui sopra, valgono i dati dell'annuncio."
    ] if detail_missing else []
    lines += [
        f"Punteggio: {summary.get('ai_score')}/100",
        f"Giudizio: {summary.get('ai_verdict') or '-'}",
        f"Motivazione: {summary.get('ai_reason') or '-'}",
    ]
    if summary.get("ai_notes"):
        lines.append(f"Note: {summary['ai_notes']}")
    return "\n".join(lines)


def build_system_prompt(raw: dict[str, Any], summary: dict[str, Any]) -> str:
    """Assemble the Italian system prompt: role, rules, preferences, listing data, prior analysis.

    The listing block is the same context the scorer sees (analysis.format_listing_context),
    so chat and score never disagree on what the listing says.
    """
    from apt_scrape.analysis import format_listing_context, has_detail_data

    preferences = _load_preferences() or "(nessuna preferenza fornita)"
    url = clean_str(summary.get("url")) or clean_str(raw.get("url")) or "-"
    prompt = (
        "Sei Milhouse, l'assistente di MilHouse per la ricerca casa: l'amico leale, entusiasta "
        "e un filo ansioso che legge ogni annuncio due volte. L'utente sta valutando l'annuncio "
        "immobiliare riportato qui sotto e ti fa domande su di esso. Hai personalità, ma la "
        "precisione viene prima: al massimo una battuta breve per risposta, mai al posto di un dato.\n\n"
        "Regole:\n"
        "- Rispondi sempre in italiano, in modo conciso (poche frasi o un breve elenco puntato).\n"
        "- Usa solo i dati dell'annuncio e le preferenze dell'utente riportati qui sotto; "
        "non inventare informazioni.\n"
        "- Se un'informazione non è presente nell'annuncio, dillo esplicitamente e suggerisci "
        "cosa chiedere all'agenzia o al proprietario.\n"
        "- I dati possono essere incompleti: la sezione 'Data availability' dice cosa non è stato "
        "raccolto. Un dato non raccolto non significa che l'annuncio non lo abbia: il requisito è "
        "'non verificabile dall'annuncio', non 'non soddisfatto'.\n"
        "- Se l'analisi AI precedente contraddice i dati dell'annuncio, valgono i dati dell'annuncio.\n"
        "- Quando è utile, confronta l'annuncio con le preferenze dell'utente.\n"
        "- Quando valuti un requisito, classificalo con una sola etichetta: "
        "'soddisfatto', 'non soddisfatto' oppure 'non verificabile dall'annuncio'. "
        "Un dato assente non è mai 'soddisfatto'.\n"
        "- Niente emoji; usa elenchi puntati in Markdown e il grassetto solo per le etichette.\n"
        "- Ragiona sempre in italiano, anche nei pensieri prima della risposta: "
        "l'utente può leggerli.\n\n"
        f"Data odierna: {date.today().isoformat()}\n\n"
        f"PREFERENZE DELL'UTENTE:\n{preferences}\n\n"
        f"ANNUNCIO:\nURL: {url}\n{format_listing_context(raw)}\n\n"
        f"ANALISI AI PRECEDENTE:\n{_prior_analysis(summary, detail_missing=not has_detail_data(raw))}"
    )
    if summary.get("triage_note"):
        prompt += f"\n\nNOTA PERSONALE DELL'UTENTE:\n{summary['triage_note']}"
    return prompt


DEEP_INSTRUCTION = (
    "\n\nL'utente ha chiesto di pensarci bene: prima di rispondere ragiona con calma su ogni "
    "criterio, sui dati mancanti e sui rischi (prezzo, spese, contratto, stato dell'immobile), "
    "poi dai una risposta più completa del solito."
)


def build_messages(
    raw: dict[str, Any], summary: dict[str, Any], history: list[dict[str, str]], deep: bool = False
) -> list[dict[str, str]]:
    """System prompt followed by the conversation (blank turns dropped: providers reject them)."""
    system = build_system_prompt(raw, summary) + (DEEP_INSTRUCTION if deep else "")
    messages = [{"role": "system", "content": system}]
    messages += [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if (m.get("content") or "").strip()
    ]
    return messages


def _chunk_text(content: Any) -> str:
    """Extract visible text from a streamed chunk's content (str or list of content blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
            # thinking / reasoning / tool blocks are intentionally skipped
        return "".join(parts)
    return ""


def _chunk_parts(content: Any) -> list[tuple[str, str]]:
    """Split a streamed chunk into ("thinking" | "text", piece) pairs, in order."""
    if isinstance(content, str):
        return [("text", content)] if content else []
    parts: list[tuple[str, str]] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append(("text", block))
            elif isinstance(block, dict):
                if block.get("type") == "text" and block.get("text"):
                    parts.append(("text", block["text"]))
                elif block.get("type") == "thinking" and block.get("thinking"):
                    parts.append(("thinking", block["thinking"]))
    return parts


def _event(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _stop_reason(chunk: Any, current: Optional[str]) -> Optional[str]:
    """Normalised stop reason from a streamed chunk ('max_tokens' | 'refusal' | other), else *current*."""
    meta = getattr(chunk, "response_metadata", None) or {}
    reason = meta.get("stop_reason") or meta.get("finish_reason")
    if reason == "length":
        return "max_tokens"
    if reason == "content_filter":
        return "refusal"
    return reason or current


async def stream_events(llm: Any, messages: list[dict[str, str]]) -> AsyncIterator[str]:
    """Yield the answer as NDJSON events, so the UI can show what the model is doing.

    Events, one JSON object per line:
      {"type": "status", "stage": "reading" | "thinking" | "writing"}
      {"type": "thinking", "delta": str}   readable summary of the reasoning (when the model has one)
      {"type": "text", "delta": str}       the answer itself
      {"type": "done", "elapsed_ms": int, "thinking_ms": int | null, "truncated"?: true}
      {"type": "error", "message": str}

    A response cut at max_tokens keeps its partial text plus a visible note (and
    "truncated": true on done); one that produced no text at all is an error.
    """
    start = time.monotonic()
    thinking_started: float | None = None
    thinking_ms: int | None = None
    stage = "reading"
    stop_reason: Optional[str] = None
    yield _event({"type": "status", "stage": stage})
    try:
        async for chunk in llm.astream(messages):
            stop_reason = _stop_reason(chunk, stop_reason)
            for kind, piece in _chunk_parts(getattr(chunk, "content", chunk)):
                if kind == "thinking":
                    if stage != "thinking" and stage != "writing":
                        stage = "thinking"
                        thinking_started = time.monotonic()
                        yield _event({"type": "status", "stage": stage})
                    if stage == "thinking":
                        yield _event({"type": "thinking", "delta": piece})
                else:
                    if stage != "writing":
                        if thinking_started is not None:
                            thinking_ms = int((time.monotonic() - thinking_started) * 1000)
                        stage = "writing"
                        yield _event({"type": "status", "stage": stage})
                    yield _event({"type": "text", "delta": piece})
    except Exception as exc:
        logger.warning("Listing chat event stream failed: %s", exc)
        yield _event({"type": "error", "message": str(exc)})
        return
    done: dict[str, Any] = {
        "type": "done",
        "elapsed_ms": int((time.monotonic() - start) * 1000),
        "thinking_ms": thinking_ms,
    }
    if stop_reason in ("max_tokens", "refusal"):
        logger.warning("Listing chat answer stopped early: %s", stop_reason)
        if stage != "writing":
            yield _event({"type": "error", "message": (
                "Il modello ha esaurito il limite di lunghezza mentre ragionava, senza rispondere. Riprova."
                if stop_reason == "max_tokens" else
                "Il modello non ha voluto rispondere a questa domanda."
            )})
            return
        yield _event({"type": "text", "delta": TRUNCATED_NOTE if stop_reason == "max_tokens" else REFUSED_NOTE})
        done["truncated"] = True
    yield _event(done)


async def stream_answer(llm: Any, messages: list[dict[str, str]]) -> AsyncIterator[str]:
    """Yield the assistant's answer token by token; on failure yield an error marker and stop."""
    stop_reason: Optional[str] = None
    try:
        async for chunk in llm.astream(messages):
            stop_reason = _stop_reason(chunk, stop_reason)
            text = _chunk_text(getattr(chunk, "content", chunk))
            if text:
                yield text
    except Exception as exc:
        logger.warning("Listing chat stream failed: %s", exc)
        yield ERROR_MARKER + str(exc)
        return
    if stop_reason == "max_tokens":
        yield TRUNCATED_NOTE
    elif stop_reason == "refusal":
        yield REFUSED_NOTE
