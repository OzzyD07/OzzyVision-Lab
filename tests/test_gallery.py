"""
Galeri listesi regresyon testleri.

Hata: /api/gallery önce HER durumdaki en yeni 100 işi alıp sonra tamamlananları
süzüyordu. Başarısız/iptal işler pencereyi doldurunca tamamlanmış videolar
galeriden kayboluyordu. Ayrıca sıralama created_at'e göre olduğu için
"Yeniden Dene" ile sonradan tamamlanan eski bir iş listenin dibine düşüyordu.
"""

import datetime

from fastapi.testclient import TestClient

from app.backend.main import app
from app.backend.queue_manager import queue_manager

client = TestClient(app)


def _ts(minutes_ago: int) -> str:
    return (datetime.datetime(2026, 9, 11, 12, 0, 0)
            - datetime.timedelta(minutes=minutes_ago)).isoformat()


def _job(job_id, status, created_min_ago, completed_min_ago=None):
    job = {
        "id": job_id,
        "model": "ltx25",
        "type": "text_to_video",
        "status": status,
        "prompt": job_id,
        "created_at": _ts(created_min_ago),
        "updated_at": _ts(completed_min_ago if completed_min_ago is not None else created_min_ago),
    }
    if completed_min_ago is not None:
        job["completed_at"] = _ts(completed_min_ago)
    return job


def _gallery_ids(limit=50):
    resp = client.get(f"/api/gallery?limit={limit}")
    assert resp.status_code == 200
    return [v["id"] for v in resp.json()["videos"]]


def test_completed_video_not_hidden_by_newer_failed_jobs(monkeypatch):
    """Tamamlanmış bir video, ondan yeni 150 başarısız işin arkasında kaybolmamalı."""
    jobs = {"done_old": _job("done_old", "completed", created_min_ago=500, completed_min_ago=499)}
    for i in range(150):
        jid = f"failed_{i}"
        jobs[jid] = _job(jid, "failed", created_min_ago=i)
    monkeypatch.setattr(queue_manager, "jobs", jobs)

    assert _gallery_ids() == ["done_old"]


def test_retried_job_appears_at_top_of_gallery(monkeypatch):
    """Eski tarihli olup yeniden denenerek ŞİMDİ tamamlanan video galerinin en üstünde olmalı."""
    jobs = {
        # 10 gün önce oluşturulmuş, az önce tamamlanmış (retry)
        "retried": _job("retried", "completed", created_min_ago=14400, completed_min_ago=1),
        # Daha yeni oluşturulmuş ama daha önce tamamlanmış
        "recent": _job("recent", "completed", created_min_ago=30, completed_min_ago=20),
    }
    for i in range(120):
        jid = f"cancelled_{i}"
        jobs[jid] = _job(jid, "cancelled", created_min_ago=40 + i)
    monkeypatch.setattr(queue_manager, "jobs", jobs)

    ids = _gallery_ids()
    assert ids[0] == "retried", ids
    assert ids == ["retried", "recent"]


def test_gallery_sorted_by_completion_and_limited(monkeypatch):
    """Galeri tamamlanma zamanına göre yeniden eskiye sıralı olmalı ve limite uymalı."""
    jobs = {}
    for i in range(80):
        jid = f"done_{i:02d}"
        jobs[jid] = _job(jid, "completed", created_min_ago=1000 + i, completed_min_ago=i)
    monkeypatch.setattr(queue_manager, "jobs", jobs)

    ids = _gallery_ids(limit=60)
    assert len(ids) == 60
    assert ids[0] == "done_00"
    assert ids[:3] == ["done_00", "done_01", "done_02"]


def test_gallery_handles_legacy_jobs_without_completed_at(monkeypatch):
    """completed_at alanı olmayan eski kayıtlar da galeride gösterilmeli."""
    legacy = _job("legacy", "completed", created_min_ago=10)
    legacy.pop("completed_at", None)
    monkeypatch.setattr(queue_manager, "jobs", {"legacy": legacy})

    assert _gallery_ids() == ["legacy"]
