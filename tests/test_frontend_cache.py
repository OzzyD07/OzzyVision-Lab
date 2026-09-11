"""
Arayuz onbellek regresyon testleri.

Hata: index.html Cache-Control olmadan sunuluyordu; tarayici onu onbellekten
kullanip guncellenen arayuz yerine eski JS paketini calistirmaya devam ediyordu.
"""

import pytest
from fastapi.testclient import TestClient

from app.backend.main import app, frontend_dist

client = TestClient(app)

pytestmark = pytest.mark.skipif(
    not (frontend_dist / "index.html").exists(),
    reason="frontend derlenmemis (npm run build)"
)


def test_index_html_is_revalidated_on_every_load():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.headers.get("cache-control") == "no-cache"


def test_hashed_assets_stay_cacheable():
    js = next((frontend_dist / "assets").glob("*.js"))
    resp = client.get(f"/assets/{js.name}")
    assert resp.status_code == 200
    assert "no-cache" not in (resp.headers.get("cache-control") or "")


def test_api_responses_unaffected():
    resp = client.get("/api/presets/camera")
    assert resp.status_code == 200
    assert "no-cache" not in (resp.headers.get("cache-control") or "")
