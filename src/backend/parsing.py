"""backend.parsing — Small parsers for scraped listing strings and raw_json blobs.

Shared by the jobs stats endpoints and the listing serializers.
"""

import json
import re
from typing import Any, Optional

# A '.' or ',' between a digit and exactly three digits is a thousands separator
# ('1.200', '1,200'); any other ',' is a decimal comma ('1.200,50', '12,50').
_THOUSANDS_SEP = re.compile(r"(?<=\d)[.,](?=\d{3}(?!\d))")


def _first_number(text: str) -> Optional[float]:
    """First number in *text*, reading Italian and English thousands/decimal separators."""
    cleaned = _THOUSANDS_SEP.sub("", text).replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", cleaned)
    return float(m.group(0)) if m else None


def parse_price(price_str: str) -> Optional[float]:
    """Extract a numeric price from '€ 1.200/mese', '1.200,50 €', 'da 900' or '€ 800 - 1.000'.

    Ranges and 'da X' yield the first (lowest) figure; 'Prezzo su richiesta' yields None.
    """
    if not price_str:
        return None
    return _first_number(price_str)


def parse_sqm(sqm_str: str) -> Optional[float]:
    """Extract the surface from strings like '70 m²' or '1.250 m²' (Italian thousands dot)."""
    if not sqm_str:
        return None
    return _first_number(sqm_str)


def parse_rooms(rooms_str: str) -> Optional[int]:
    """Extract the room count from strings like '2 locali', '1 locale' or '5+ locali'."""
    if not rooms_str:
        return None
    m = re.search(r"(\d+)", rooms_str)
    return int(m.group(1)) if m else None


def load_raw(raw_json: Optional[str]) -> dict[str, Any]:
    """Parse a listing's raw_json, returning {} for missing, garbled or non-object JSON."""
    try:
        data = json.loads(raw_json or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def as_dict(value: Any) -> dict[str, Any]:
    """Return *value* if it is a dict, else {} (raw_json sub-objects can be missing or garbled)."""
    return value if isinstance(value, dict) else {}


def clean_str(value: Any) -> Optional[str]:
    """Strip strings and map empty/missing values to None; non-strings are str()-ed."""
    if value is None:
        return None
    text = value.strip() if isinstance(value, str) else str(value)
    return text or None


def listing_address(raw: dict[str, Any]) -> Optional[str]:
    """Best address for a listing: detail_address, then the AI-normalised address, then the card address."""
    fields = as_dict(raw.get("notion_fields"))
    return (
        clean_str(raw.get("detail_address"))
        or clean_str(fields.get("address"))
        or clean_str(raw.get("address"))
    )


# ---------------------------------------------------------------------------
# Detail page status and scraped facts
# ---------------------------------------------------------------------------

DETAIL_STATUSES = ("ok", "blocked", "error", "empty", "missing")


def detail_status_of(raw: dict[str, Any]) -> str:
    """'ok' | 'blocked' | 'error' | 'empty' | 'missing' for the listing's detail page.

    Uses the status the enrichment step stored; rows scraped before it existed are
    derived from the legacy ``detail`` dict ('empty' = fetched but blank, e.g. a
    captcha page). 'skipped' (never fetched after repeated blocks) reads as 'missing'.
    """
    stored = clean_str(raw.get("detail_status"))
    if stored == "skipped":
        return "missing"
    if stored in DETAIL_STATUSES:
        return stored
    detail = raw.get("detail")
    if not isinstance(detail, dict):
        return "missing"
    extra = as_dict(detail.get("extra_info"))
    has_content = (
        clean_str(detail.get("title"))
        or clean_str(detail.get("description"))
        or any(clean_str(v) for v in extra.values())
    )
    return "ok" if has_content else "empty"


def detail_facts(raw: dict[str, Any]) -> dict[str, str]:
    """The portal's own feature table (label -> value, Italian labels as scraped).

    ``detail_features`` first, else ``detail.extra_info``; blank or non-scalar values are dropped.
    """
    source = as_dict(raw.get("detail_features")) or as_dict(as_dict(raw.get("detail")).get("extra_info"))
    facts: dict[str, str] = {}
    for label, value in source.items():
        if isinstance(value, (dict, list)):
            continue
        label_s, value_s = clean_str(label), clean_str(value)
        if label_s and value_s:
            facts[label_s] = value_s
    return facts


def _fact(facts: dict[str, str], *labels: str) -> Optional[str]:
    """Case-insensitive lookup of the first matching label."""
    wanted = {label.lower() for label in labels}
    return next((v for k, v in facts.items() if k.lower() in wanted), None)


def _card_tokens(raw: dict[str, Any]) -> list[str]:
    features = raw.get("raw_features")
    if not isinstance(features, list):
        return []
    return [t for f in features if (t := clean_str(f))]


# Immobiliare card abbreviations: 'Piano T', 'Piano R', 'Piano S, 1'
_FLOOR_ABBREV = {"t": "piano terra", "r": "piano rialzato", "s": "seminterrato"}


def scraped_floor(raw: dict[str, Any]) -> Optional[str]:
    """Floor as the portal states it: feature table 'Piano', then detail.floor, then the card's 'Piano X'."""
    floor = _fact(detail_facts(raw), "Piano") or clean_str(as_dict(raw.get("detail")).get("floor"))
    if floor:
        return floor
    for token in _card_tokens(raw):
        m = re.match(r"piano\s+(.+)$", token, re.IGNORECASE)
        if m:
            parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
            text = ", ".join(_FLOOR_ABBREV.get(p.lower(), p) for p in parts)
            return text[:1].upper() + text[1:] if text else None
    return None


def scraped_furnished(raw: dict[str, Any]) -> Optional[bool]:
    """True/False only when the portal says so outright; None when unknown or partial.

    'Parzialmente arredato' and 'Solo cucina arredata' are not a yes, and a missing
    card token is not a no (cards only list positive features).
    """
    value = _fact(detail_facts(raw), "Arredato")
    if value:
        v = value.lower()
        if v in ("sì", "si", "yes"):
            return True
        if v == "no":
            return False
    tokens = {t.lower() for t in _card_tokens(raw)}
    if "arredato" in tokens:
        return True
    if "non arredato" in tokens:
        return False
    return None


def scraped_bathrooms(raw: dict[str, Any]) -> Optional[str]:
    """'1 bagno' from the search card, else the feature table's 'Bagni' count."""
    card = clean_str(raw.get("bathrooms"))
    if card:
        return card
    value = _fact(detail_facts(raw), "Bagni", "Bagno")
    if value and value.isdigit():
        return f"{value} bagno" if value == "1" else f"{value} bagni"
    return value


def scraped_available_from(raw: dict[str, Any]) -> Optional[str]:
    """The feature table's availability line ('Libero', 'Disponibile dal ...'), if any."""
    return _fact(detail_facts(raw), "Disponibilità", "Disponibilita", "Disponibile dal", "Disponibile da")
