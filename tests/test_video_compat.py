"""
Tarayıcıda oynatılabilir video regresyon testleri.

Hata: Galeri oynatıcısında ses çalıyor ama görüntü görünmüyordu. İki ayrı neden:
  1. Arayüz: uzun metadata modalı taşırınca overflow:hidden oynatıcı kutusu 0 piksele
     küçülüyordu (GalleryView.jsx ModalPlayer; tarayıcıda ölçülerek düzeltildi).
  2. Biçim: ComfyUI bazı biçimlerde (ör. 10-bit H.264, MPEG-4) MP4 yazabilir; tarayıcı
     video izini çözemeyince hata vermeden yalnızca sesi çalar. Bu dosya o güvenceyi test eder.
"""

import asyncio
import json
import os
import shutil
import threading
from fractions import Fraction
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest

av = pytest.importorskip("av")

import config.settings as settings
from app.backend import video_compat as vc

W, H, FPS, N, SR = 160, 90, 24, 12, 48000


def _make_clip(path, codec="libx264", pix_fmt="yuv420p", width=W, height=H, audio="aac"):
    with av.open(str(path), "w") as out:
        vs = out.add_stream(codec, rate=FPS)
        vs.width, vs.height, vs.pix_fmt = width, height, pix_fmt
        aud = None
        if audio:
            aud = out.add_stream(audio, rate=SR)
            aud.layout = "stereo"
        for i in range(N):
            rgb = np.full((height, width, 3), (i * 20) % 255, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(rgb, format="rgb24").reformat(format=pix_fmt)
            for pkt in vs.encode(frame):
                out.mux(pkt)
        for pkt in vs.encode():
            out.mux(pkt)
        if aud is not None:
            total = int(SR * N / FPS)
            tone = (0.1 * np.sin(2 * np.pi * 440 * np.arange(total) / SR)).astype(np.float32)
            pts = 0
            chunk = aud.codec_context.frame_size or 1024
            for s in range(0, total, chunk):
                part = np.ascontiguousarray(np.stack([tone[s:s + chunk]] * 2))
                af = av.AudioFrame.from_ndarray(part, format="fltp", layout="stereo")
                af.sample_rate, af.pts, af.time_base = SR, pts, Fraction(1, SR)
                pts += part.shape[1]
                for pkt in aud.encode(af):
                    out.mux(pkt)
            for pkt in aud.encode():
                out.mux(pkt)
    return str(path)


def _count(path):
    with av.open(path) as c:
        frames = sum(1 for _ in c.decode(c.streams.video[0]))
    samples = 0
    with av.open(path) as c:
        if c.streams.audio:
            samples = sum(f.samples for f in c.decode(c.streams.audio[0]))
    return frames, samples


@pytest.fixture(autouse=True)
def _clear_cache():
    vc._cache.clear()
    yield
    vc._cache.clear()


# ----------------------------------------------------------------------------
# Sınıflandırma
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("codec, pix_fmt, expected", [
    ("libx264", "yuv420p", True),
    ("libx264", "yuv420p10le", False),
    ("libx264", "yuv444p", False),
    ("mpeg4", "yuv420p", False),
])
def test_browser_playable_classification(tmp_path, codec, pix_fmt, expected):
    path = _make_clip(tmp_path / "clip.mp4", codec=codec, pix_fmt=pix_fmt)
    assert vc.is_browser_playable(vc.probe(path)) is expected


def test_probe_unreadable_file_returns_none(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"STUB_MP4")
    assert vc.probe(str(bad)) is None
    assert vc.is_browser_playable(None) is False


# ----------------------------------------------------------------------------
# Dönüştürme
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("codec, pix_fmt", [
    ("libx264", "yuv420p10le"),
    ("libx264", "yuv444p"),
    ("mpeg4", "yuv420p"),
])
def test_unplayable_video_converted_preserving_frames_and_audio(tmp_path, codec, pix_fmt):
    path = _make_clip(tmp_path / "clip.mp4", codec=codec, pix_fmt=pix_fmt)
    frames_before, samples_before = _count(path)

    info = asyncio.run(vc.ensure_playable(path))

    assert info["transcoded"] is True
    assert info["browser_playable"] is True
    assert info["original"]["pix_fmt"] == pix_fmt
    final = vc.probe(path)
    assert final["video_codec"] == "h264" and final["pix_fmt"] == "yuv420p"
    assert (final["width"], final["height"]) == (W, H)
    frames_after, samples_after = _count(path)
    assert frames_after == frames_before
    assert samples_after == samples_before  # AAC ses yeniden kodlanmadan kopyalanır
    assert not os.path.exists(path + ".part")


def test_playable_video_left_untouched(tmp_path):
    path = _make_clip(tmp_path / "clip.mp4")
    before = open(path, "rb").read()
    info = asyncio.run(vc.ensure_playable(path))
    assert info["transcoded"] is False and info["browser_playable"] is True
    assert open(path, "rb").read() == before


def test_odd_dimensions_become_even(tmp_path):
    path = _make_clip(tmp_path / "odd.mp4", pix_fmt="yuv444p", width=161, height=91)
    asyncio.run(vc.ensure_playable(path))
    final = vc.probe(path)
    assert (final["width"], final["height"]) == (160, 90)
    assert vc.is_browser_playable(final)


def test_unreadable_file_is_not_modified(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"STUB_MP4")
    assert asyncio.run(vc.ensure_playable(str(bad))) == {"checked": False}
    assert bad.read_bytes() == b"STUB_MP4"


def test_concurrent_requests_transcode_once(tmp_path, monkeypatch):
    """Galeri kartı ve modal aynı videoyu aynı anda isteyince tek dönüştürme yapılmalı."""
    path = _make_clip(tmp_path / "clip.mp4", pix_fmt="yuv420p10le")
    calls = []
    real = vc._ensure_sync

    def counting(p, probed):
        calls.append(p)
        return real(p, probed)

    monkeypatch.setattr(vc, "_ensure_sync", counting)

    async def many():
        return await asyncio.gather(*[vc.ensure_playable(path) for _ in range(5)])

    results = asyncio.run(many())
    assert len(calls) == 1
    assert all(r["transcoded"] and r["browser_playable"] for r in results)


# ----------------------------------------------------------------------------
# Yayın ucu: bu düzeltmeden önce üretilmiş videolar ilk açılışta düzelir
# ----------------------------------------------------------------------------
def test_stream_endpoint_fixes_existing_gallery_video(tmp_path):
    from fastapi.testclient import TestClient
    from app.backend.main import app
    from app.backend.queue_manager import queue_manager

    job_id = "vid_20260914_compat1"
    job_dir = os.path.join(settings.LOCAL_JOBS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    local = os.path.join(job_dir, "output.mp4")
    shutil.copy(_make_clip(tmp_path / "old.mp4", codec="mpeg4"), local)
    queue_manager.jobs[job_id] = {"id": job_id, "status": "completed", "created_at": "2026-09-14T00:00:00"}

    try:
        resp = TestClient(app).get(f"/api/videos/{job_id}/stream")
        assert resp.status_code == 200
        served = tmp_path / "served.mp4"
        served.write_bytes(resp.content)
        assert vc.is_browser_playable(vc.probe(str(served)))

        info = queue_manager.jobs[job_id]["video_info"]
        assert info["transcoded"] is True
        assert info["original"]["video_codec"] == "mpeg4"
    finally:
        queue_manager.jobs.pop(job_id, None)
        shutil.rmtree(job_dir, ignore_errors=True)


# ----------------------------------------------------------------------------
# İş akışı: yeni üretimler galeriye tarayıcı dostu konur, ComfyUI çıktısı korunur
# ----------------------------------------------------------------------------
OUTPUT_NAME = "OzzyVision_compat_test_00001.mp4"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/history/"):
            pid = self.path.rsplit("/", 1)[-1]
            return self._json({pid: {"status": {"status_str": "success"},
                                     "outputs": {"17": {"videos": [{"filename": OUTPUT_NAME, "subfolder": ""}]}}}})
        if self.path == "/system_stats":
            return self._json({"system": {}, "devices": []})
        if self.path == "/queue":
            return self._json({"queue_running": [], "queue_pending": []})
        # /object_info dahil bilinmeyen yollar 404: şema doğrulaması atlanır
        return self._json({}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        return self._json({"prompt_id": "stub-1"} if self.path == "/prompt" else {})


def _clear_object_info_cache():
    from app.backend.engines import base as engine_base
    engine_base._OBJECT_INFO_CACHE["data"] = None
    engine_base._OBJECT_INFO_CACHE["ts"] = 0.0


def test_new_job_output_is_browser_playable(tmp_path):
    from app.backend.queue_manager import QueueManager

    _clear_object_info_cache()

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    keys = ("COMFYUI_URL", "COMFY_POLL_INTERVAL", "FREE_VRAM_SETTLE_SECONDS")
    saved = {k: getattr(settings, k) for k in keys}
    settings.COMFYUI_URL = "http://127.0.0.1:%d" % server.server_address[1]
    settings.COMFY_POLL_INTERVAL = 0.05
    settings.FREE_VRAM_SETTLE_SECONDS = 0

    comfy_out = os.path.join(settings.COMFYUI_DIR, "output")
    os.makedirs(comfy_out, exist_ok=True)
    comfy_file = os.path.join(comfy_out, OUTPUT_NAME)
    shutil.copy(_make_clip(tmp_path / "ten.mp4", pix_fmt="yuv420p10le"), comfy_file)

    qm = QueueManager()
    qm.jobs.clear()
    qm.queue.clear()
    job = None
    try:
        async def go():
            j = qm.create_job({"model": "minimax_h3", "prompt": "uyumluluk", "duration": 4})
            qm.queue.remove(j["id"])  # işi test yürütür; arka plan işçisi ikinci kez çalıştırmasın
            await qm._execute_job(j)
            return j

        job = asyncio.run(go())
        assert job["status"] == "completed", job.get("error")
        assert job["video_info"]["transcoded"] is True
        assert vc.is_browser_playable(vc.probe(job["local_video_path"]))
        # ComfyUI'nin kendi çıktısına dokunulmamalı
        assert vc.probe(comfy_file)["pix_fmt"] == "yuv420p10le"
    finally:
        _clear_object_info_cache()
        for k, v in saved.items():
            setattr(settings, k, v)
        server.shutdown()
        server.server_close()
        if os.path.exists(comfy_file):
            os.remove(comfy_file)
        if job:
            shutil.rmtree(os.path.join(settings.LOCAL_JOBS_DIR, job["id"]), ignore_errors=True)
