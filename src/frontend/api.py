"""frontend.api — HTTP client for the apt_scrape backend."""
import os
import httpx

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# Fallback when GET /sites/{id}/areas fails; per-site to match shell scripts
DEFAULT_AREAS = [
    "bicocca", "niguarda", "precotto", "porta-venezia-indipendenza", "citta-studi",
    "lambrate", "turro", "greco-segnano", "crescenzago", "centrale", "pasteur-rovereto",
]
# Per-site defaults (match config/default_areas_{site}.txt and scrape_multiple_areas_*.sh)
DEFAULT_AREAS_BY_SITE = {
    "immobiliare": DEFAULT_AREAS,  # full list + pasteur-rovereto
    "casa": [
        "bicocca", "niguarda", "precotto", "citta-studi", "lambrate",
        "turro", "greco-segnano", "crescenzago", "centrale",
    ],
    "idealista": [
        "bicocca", "niguarda", "precotto", "loreto", "citta-studi",
        "lambrate", "turro", "greco-segnano", "crescenzago", "centrale",
    ],
    "tecnocasa": ["milano"],  # city-wide only, no sub-area support
    "gabetti": ["milano"],   # city-wide only, no sub-area support
}


def get(path: str, **kwargs) -> dict:
    with httpx.Client(base_url=BACKEND_URL, timeout=30) as client:
        resp = client.get(path, **kwargs)
        resp.raise_for_status()
        return resp.json()


def post(path: str, json=None, **kwargs) -> dict:
    with httpx.Client(base_url=BACKEND_URL, timeout=30) as client:
        resp = client.post(path, json=json, **kwargs)
        resp.raise_for_status()
        return resp.json()


def put(path: str, json=None, **kwargs) -> dict:
    with httpx.Client(base_url=BACKEND_URL, timeout=30) as client:
        resp = client.put(path, json=json, **kwargs)
        resp.raise_for_status()
        return resp.json()


def patch(path: str, **kwargs) -> dict:
    with httpx.Client(base_url=BACKEND_URL, timeout=30) as client:
        resp = client.patch(path, **kwargs)
        resp.raise_for_status()
        return resp.json()


def delete(path: str, **kwargs) -> None:
    with httpx.Client(base_url=BACKEND_URL, timeout=30) as client:
        resp = client.delete(path, **kwargs)
        resp.raise_for_status()
