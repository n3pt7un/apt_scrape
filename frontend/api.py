"""frontend.api — HTTP client for the apt_scrape backend."""
import os
import httpx

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


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
