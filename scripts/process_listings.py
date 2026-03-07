#!/usr/bin/env python3
"""Process a listings JSON file and export a filtered CSV.

Reads the JSON output produced by ``apt_scrape.cli search`` and applies
basic filters (price and sqm), then writes a CSV with extra derived columns
for independent heating and pet-friendliness detected from the description.

Usage::

    python scripts/process_listings.py listings.json -o filtered.csv \\
        --max-price 1000 --min-sqm 50
"""

import argparse
import csv
import json
import re
import sys


def extract_price(price_str: str) -> float:
    """Parse a numeric price from a formatted Italian price string.

    Args:
        price_str: Price string such as ``"€ 1.000/mese"``.

    Returns:
        Numeric price, or ``0`` when no number can be parsed.
    """
    match = re.search(r"(\d+(?:\.\d+)?)", price_str.replace(".", ""))
    return float(match.group(1)) if match else 0


def extract_sqm(sqm_str: str) -> int:
    """Parse a numeric square-metre value from a feature string.

    Args:
        sqm_str: Feature string such as ``"65 m²"``.

    Returns:
        Integer value, or ``0`` when no number can be parsed.
    """
    match = re.search(r"(\d+)", sqm_str)
    return int(match.group(1)) if match else 0


def check_heating(description: str) -> bool:
    """Return ``True`` when *description* mentions independent heating.

    Args:
        description: Listing description text.

    Returns:
        ``True`` if any Italian keyword for independent heating is found.
    """
    keywords = ["riscaldamento autonomo", "autonomo", "riscaldamento indipendente"]
    text = description.lower()
    return any(kw in text for kw in keywords)


def check_pets(description: str) -> bool:
    """Return ``True`` when *description* indicates pets are allowed.

    Args:
        description: Listing description text.

    Returns:
        ``True`` if any Italian keyword for pets is found.
    """
    keywords = ["animali", "pet", "cani", "gatti", "domestici"]
    text = description.lower()
    return any(kw in text for kw in keywords)


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser.

    Returns:
        Configured ``ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(
        description="Filter a listings JSON file and export a CSV."
    )
    parser.add_argument(
        "input",
        metavar="INPUT",
        help="Path to the listings JSON file (output of apt_scrape.cli search).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help=(
            "Path for the output CSV file. "
            "Defaults to the input filename with a .csv extension."
        ),
    )
    parser.add_argument(
        "--max-price",
        type=float,
        default=1000,
        help="Exclude listings with price > this value (default: 1000).",
    )
    parser.add_argument(
        "--min-sqm",
        type=int,
        default=50,
        help="Exclude listings with sqm < this value (default: 50).",
    )
    return parser


def main() -> None:
    """Parse arguments, filter listings, and write the output CSV."""
    parser = build_parser()
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as fh:
        data = json.load(fh)

    output_path = args.output or args.input.rsplit(".", 1)[0] + ".csv"

    filtered: list[dict] = []
    for listing in data.get("listings", []):
        price = extract_price(listing.get("price", ""))
        sqm = extract_sqm(listing.get("sqm", ""))

        if price > args.max_price or sqm < args.min_sqm:
            continue

        description = listing.get("description_snippet", "")
        filtered.append(
            {
                "title": listing.get("title", ""),
                "url": listing.get("url", ""),
                "price": price,
                "sqm": sqm,
                "rooms": listing.get("rooms", ""),
                "bathrooms": listing.get("bathrooms", ""),
                "has_independent_heating": check_heating(description),
                "pet_friendly": check_pets(description),
                "features": ", ".join(listing.get("raw_features", [])),
                "description_snippet": description[:200] + ("..." if len(description) > 200 else ""),
            }
        )

    fieldnames = [
        "title",
        "url",
        "price",
        "sqm",
        "rooms",
        "bathrooms",
        "has_independent_heating",
        "pet_friendly",
        "features",
        "description_snippet",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(filtered)

    print(f"Processed {len(filtered)} listings -> {output_path}")


if __name__ == "__main__":
    main()
