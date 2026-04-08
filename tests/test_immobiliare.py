#!/usr/bin/env python3
"""Immobiliare adapter test suite.

Sections
--------
1.  URL-builder unit tests  (no network)
    — Verify every SearchFilter field produces the correct query-string params.

2.  Live integration tests  (1 page each, exits early when no listings found)
    — Verify that filters round-trip through the real site and return listings.

Usage
-----
    python tests/test_immobiliare.py              # unit + live
    python tests/test_immobiliare.py --unit-only  # URL tests only (no network)
    python tests/test_immobiliare.py --live-only  # live tests only
"""

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Ensure the project root is on sys.path so ``apt_scrape`` is importable when
# the test file is invoked directly (e.g. ``python tests/test_immobiliare.py``).
sys.path.insert(0, str(Path(__file__).parent.parent))

from apt_scrape.server import fetcher
from apt_scrape.sites import SearchFilters, get_adapter


# ─────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
WARN = "\033[33m⚠\033[0m"
INFO = "\033[36m·\033[0m"


def _qs(url: str) -> dict:
    """Return a ``{param: [value, …]}`` dict for the query string of *url*."""
    return parse_qs(urlparse(url).query)


def _path(url: str) -> str:
    """Return the path component of *url*."""
    return urlparse(url).path


def _assert(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  {PASS}  {label}")
    else:
        print(f"  {FAIL}  {label}" + (f"  ({detail})" if detail else ""))
    return cond


# ─────────────────────────────────────────────────
# 1. URL-builder unit tests
# ─────────────────────────────────────────────────


def run_url_tests(adapter) -> tuple[int, int]:
    """Run all URL-builder unit tests and return ``(passed, failed)``."""
    passed = failed = 0

    def check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal passed, failed
        ok = _assert(label, cond, detail)
        if ok:
            passed += 1
        else:
            failed += 1

    print("\n── URL-builder unit tests ────────────────────────────────")

    # ── operation_map ─────────────────────────────
    print("\n  [operation_map]")
    for op_in, op_out in [("affitto", "affitto"), ("vendita", "vendita")]:
        f = SearchFilters(city="milano", operation=op_in, property_type="appartamenti")
        url = adapter.build_search_url(f)
        check(
            f"operation={op_in} -> path contains /{op_out}-",
            f"/{op_out}-" in _path(url),
            _path(url),
        )

    # ── property_type_map ─────────────────────────
    print("\n  [property_type_map]")
    for pt in [
        "case",
        "appartamenti",
        "attici",
        "case-indipendenti",
        "loft",
        "rustici",
        "ville",
        "villette",
    ]:
        f = SearchFilters(city="milano", operation="affitto", property_type=pt)
        url = adapter.build_search_url(f)
        check(
            f"property_type={pt} -> path contains -{pt}/",
            f"-{pt}/" in _path(url),
            _path(url),
        )

    # ── city / area path ──────────────────────────
    print("\n  [city + area path]")
    f = SearchFilters(city="milano", operation="affitto", property_type="appartamenti")
    url = adapter.build_search_url(f)
    check(
        "city alone -> /affitto-appartamenti/milano/",
        "/affitto-appartamenti/milano/" in url,
        url,
    )

    f = SearchFilters(
        city="milano", area="niguarda", operation="affitto", property_type="appartamenti"
    )
    url = adapter.build_search_url(f)
    check(
        "city+area -> /affitto-appartamenti/milano/niguarda/",
        "/affitto-appartamenti/milano/niguarda/" in url,
        url,
    )

    f = SearchFilters(
        city="roma", area="prati", operation="affitto", property_type="case"
    )
    url = adapter.build_search_url(f)
    check(
        "different city+area -> /affitto-case/roma/prati/",
        "/affitto-case/roma/prati/" in url,
        url,
    )

    # ── numeric filters ───────────────────────────
    print("\n  [numeric filters — query params]")
    numeric_cases = [
        ("min_price", 500, "prezzoMinimo", "500"),
        ("max_price", 1200, "prezzoMassimo", "1200"),
        ("min_sqm", 50, "superficieMinima", "50"),
        ("max_sqm", 120, "superficieMassima", "120"),
        ("min_rooms", 2, "localiMinimo", "2"),
        ("max_rooms", 5, "localiMassimo", "5"),
    ]
    for field_name, value, param, expected_str in numeric_cases:
        f = SearchFilters(city="milano", **{field_name: value})
        url = adapter.build_search_url(f)
        qs = _qs(url)
        check(
            f"{field_name}={value} -> ?{param}={expected_str}",
            qs.get(param, [None])[0] == expected_str,
            f"got {qs.get(param)}",
        )

    f = SearchFilters(
        city="milano",
        min_price=600,
        max_price=1200,
        min_sqm=50,
        max_sqm=120,
        min_rooms=2,
        max_rooms=4,
    )
    url = adapter.build_search_url(f)
    qs = _qs(url)
    all_present = all(
        p in qs
        for p in [
            "prezzoMinimo",
            "prezzoMassimo",
            "superficieMinima",
            "superficieMassima",
            "localiMinimo",
            "localiMassimo",
        ]
    )
    check("all six numeric filters combined are present in URL", all_present, str(qs.keys()))

    # ── published_within ──────────────────────────
    print("\n  [published_within]")
    for days in ["1", "3", "7", "14", "30"]:
        f = SearchFilters(city="milano", published_within=days)
        url = adapter.build_search_url(f)
        qs = _qs(url)
        check(
            f"published_within={days} -> ?giorniPubblicazione={days}",
            qs.get("giorniPubblicazione", [None])[0] == days,
            str(qs.get("giorniPubblicazione")),
        )

    f = SearchFilters(city="milano")
    url = adapter.build_search_url(f)
    check(
        "published_within=None -> giorniPubblicazione absent",
        "giorniPubblicazione" not in _qs(url),
    )

    # ── sort ──────────────────────────────────────
    print("\n  [sort]")
    for sort_val in ["piu-recenti", "recenti", "data", "newest", "latest"]:
        f = SearchFilters(city="milano", sort=sort_val)
        url = adapter.build_search_url(f)
        qs = _qs(url)
        check(
            f"sort={sort_val!r} -> criterio=data + ordine=desc",
            qs.get("criterio", [None])[0] == "data"
            and qs.get("ordine", [None])[0] == "desc",
            str({k: qs[k] for k in ("criterio", "ordine") if k in qs}),
        )

    f = SearchFilters(city="milano", sort="rilevanza")
    url = adapter.build_search_url(f)
    qs = _qs(url)
    check(
        "sort=rilevanza -> criterio/ordine absent",
        "criterio" not in qs and "ordine" not in qs,
        str({k: qs[k] for k in ("criterio", "ordine") if k in qs}),
    )

    # ── page param ────────────────────────────────
    print("\n  [pagination]")
    for page_num in [1, 2, 5, 10]:
        f = SearchFilters(city="milano", page=page_num)
        url = adapter.build_search_url(f)
        qs = _qs(url)
        check(
            f"page={page_num} -> ?pag={page_num}",
            qs.get("pag", [None])[0] == str(page_num),
            str(qs.get("pag")),
        )

    return passed, failed


# ─────────────────────────────────────────────────
# 2. Live integration tests
# ─────────────────────────────────────────────────

LIVE_CASES = [
    (
        "baseline – no filters",
        dict(city="milano", operation="affitto", property_type="appartamenti"),
    ),
    (
        "operation=vendita",
        dict(city="milano", operation="vendita", property_type="appartamenti"),
    ),
    (
        "with area (niguarda)",
        dict(
            city="milano",
            area="niguarda",
            operation="affitto",
            property_type="appartamenti",
        ),
    ),
    (
        "property_type=attici",
        dict(city="milano", operation="affitto", property_type="attici"),
    ),
    (
        "property_type=ville",
        dict(city="milano", operation="affitto", property_type="ville"),
    ),
    (
        "max_price filter (<=1200)",
        dict(
            city="milano",
            operation="affitto",
            property_type="appartamenti",
            max_price=1200,
        ),
    ),
    (
        "min_price + max_price (800-1500)",
        dict(
            city="milano",
            operation="affitto",
            property_type="appartamenti",
            min_price=800,
            max_price=1500,
        ),
    ),
    (
        "min_sqm=50",
        dict(
            city="milano",
            operation="affitto",
            property_type="appartamenti",
            min_sqm=50,
        ),
    ),
    (
        "min_rooms=2",
        dict(
            city="milano",
            operation="affitto",
            property_type="appartamenti",
            min_rooms=2,
        ),
    ),
    (
        "min_rooms=3 + max_price=1800",
        dict(
            city="milano",
            operation="affitto",
            property_type="appartamenti",
            min_rooms=3,
            max_price=1800,
        ),
    ),
    (
        "published_within=7",
        dict(
            city="milano",
            operation="affitto",
            property_type="appartamenti",
            published_within="7",
        ),
    ),
    (
        "published_within=30",
        dict(
            city="milano",
            operation="affitto",
            property_type="appartamenti",
            published_within="30",
        ),
    ),
    (
        "sort=piu-recenti",
        dict(
            city="milano",
            operation="affitto",
            property_type="appartamenti",
            sort="piu-recenti",
        ),
    ),
    (
        "sort=rilevanza (default)",
        dict(
            city="milano",
            operation="affitto",
            property_type="appartamenti",
            sort="rilevanza",
        ),
    ),
    (
        "combined: area+price+sqm+rooms+sort",
        dict(
            city="milano",
            area="bicocca",
            operation="affitto",
            property_type="appartamenti",
            max_price=1400,
            min_sqm=50,
            min_rooms=2,
            sort="piu-recenti",
        ),
    ),
    (
        "page=2",
        dict(city="milano", operation="affitto", property_type="appartamenti", page=2),
    ),
]


async def run_live_tests(adapter) -> tuple[int, int]:
    """Run each live integration test and return ``(passed, failed)``."""
    passed = failed = 0
    total = len(LIVE_CASES)

    print(f"\n── Live integration tests ({total} cases, page 1 each) ─────────")

    for idx, (label, kwargs) in enumerate(LIVE_CASES, 1):
        f = SearchFilters(**kwargs)
        url = adapter.build_search_url(f)
        print(f"\n  [{idx:02d}/{total}] {label}")
        print(f"       {INFO} URL: {url}")

        try:
            html = await fetcher.fetch_with_retry(
                url,
                wait_selector=adapter.config.search_wait_selector,
                wait_timeout=adapter.config.search_wait_timeout / 1000,
            )
            listings = adapter.parse_search(html)
            count = len(listings)

            ok = count > 0
            symbol = PASS if ok else WARN
            print(f"       {symbol} {count} listings parsed")

            if ok:
                passed += 1
                first = listings[0]
                has_url = bool(first.url)
                has_title = bool(first.title)
                has_price = bool(first.price)
                _assert("  first listing has url", has_url, first.url)
                _assert("  first listing has title", has_title, first.title)
                _assert("  first listing has price", has_price, first.price)
                print(f"         title: {first.title[:70]!r}")
                print(f"         price: {first.price}")
                print(f"         sqm:   {first.sqm}  rooms: {first.rooms}")
                print(f"         url:   {first.url[:80]}")
            else:
                print(f"       {WARN} Zero listings returned (may be a valid empty result set)")
                failed += 1

        except Exception as exc:
            print(f"       {FAIL} Exception: {exc}")
            failed += 1

    return passed, failed


# ─────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────


async def _main(unit_only: bool, live_only: bool) -> int:
    """Run selected test sections and return the number of failures."""
    adapter = get_adapter("immobiliare")
    total_passed = total_failed = 0

    if not live_only:
        p, f = run_url_tests(adapter)
        total_passed += p
        total_failed += f
        print(f"\n  URL-builder: {p} passed, {f} failed")

    if not unit_only:
        p, f = await run_live_tests(adapter)
        total_passed += p
        total_failed += f
        print(f"\n  Live tests:  {p} passed, {f} failed")

    print("\n" + "=" * 56)
    print(f"  TOTAL: {total_passed} passed, {total_failed} failed")
    if total_failed:
        print(f"  {FAIL} Some tests failed — review output above.")
    else:
        print(f"  {PASS} All tests passed.")
    print("=" * 56)

    return total_failed


def main() -> None:
    """Parse arguments and run the test suite."""
    ap = argparse.ArgumentParser(description="Immobiliare adapter test suite")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--unit-only", action="store_true", help="Run URL-builder tests only")
    g.add_argument("--live-only", action="store_true", help="Run live integration tests only")
    args = ap.parse_args()

    failed = asyncio.run(_main(args.unit_only, args.live_only))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
