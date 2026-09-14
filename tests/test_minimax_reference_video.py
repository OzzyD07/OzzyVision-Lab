"""
MiniMax H3 video referansı regresyon testleri.

Hata: video referansı ComfyUI'ye hiç doğru ulaşmıyordu.
  - LoadVideo'nun girdisi "file"; iş akışı "video" gönderiyordu (gerekli girdi eksik).
  - MiniMaxH3ReferenceToVideo.ref_videos IMAGE (24 fps kareler) bekler; LoadVideo'nun
    VIDEO çıktısı doğrudan bağlanıyordu (tip uyuşmazlığı).
  - Referans videonun sesi için ref_video_audios yuvası hiç bağlanmıyordu.
  - 30/60 fps videolar 24 fps'e çevrilmeden gönderiliyordu.

Şemalar ComfyUI kaynağından alınmıştır:
  comfy_extras/nodes_minimax_h3.py, comfy_extras/nodes_video.py, comfy_extras/nodes_audio.py
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
from app.backend.engines.minimax_h3.engine import MiniMaxH3Engine

SR = 48000

# ----------------------------------------------------------------------------
# ComfyUI düğüm şemaları (yalnızca referans zinciri için gerekenler)
# ----------------------------------------------------------------------------
SCHEMAS = {
    "LoadImage": {"required": {"image": "COMBO"}, "outputs": ["IMAGE", "MASK"]},
    "LoadVideo": {"required": {"file": "COMBO"}, "outputs": ["VIDEO"]},
    "LoadAudio": {"required": {"audio": "COMBO"}, "outputs": ["AUDIO"]},
    "GetVideoComponents": {
        "required": {"video": "VIDEO"},
        "outputs": ["IMAGE", "AUDIO", "FLOAT", "COMBO", "COMBO"],
    },
    "MiniMaxH3ReferenceToVideo": {
        "required": {"clip": "CLIP", "prompt": "STRING", "width": "INT", "height": "INT",
                     "length": "INT", "ref_image_size": "COMBO"},
        "optional": {"vae": "VAE", "audio_vae": "VAE"},
        "dynamic": {"ref_images.ref_image_": "IMAGE", "ref_videos.ref_video_": "IMAGE",
                    "ref_video_audios.ref_video_audio_": "AUDIO", "ref_audios.ref_audio_": "AUDIO"},
        "outputs": ["CONDITIONING", "LATENT"],
    },
}
# Referans zinciri dışında kalan düğümler için yalnızca çıktı tipleri
EXTERNAL_OUTPUTS = {"CLIPLoader": ["CLIP"], "VAELoader": ["VAE"]}


def type_check_reference_chain(workflow):
    """ComfyUI'nin bağlantı doğrulamasını referans zinciri için taklit eder; hata listesi döner."""
    errors = []

    def output_type(link):
        src_id, idx = link
        cls = workflow[src_id]["class_type"]
        outs = SCHEMAS.get(cls, {}).get("outputs") or EXTERNAL_OUTPUTS.get(cls)
        if outs is None or idx >= len(outs):
            return None
        return outs[idx]

    for node_id, node in workflow.items():
        schema = SCHEMAS.get(node["class_type"])
        if not schema:
            continue
        inputs = node.get("inputs", {})
        for name in schema.get("required", {}):
            if name not in inputs:
                errors.append(f"{node_id} {node['class_type']}: gerekli girdi eksik '{name}'")
        known = {**schema.get("required", {}), **schema.get("optional", {})}
        for name, value in inputs.items():
            expected = known.get(name)
            if expected is None:
                expected = next((t for prefix, t in schema.get("dynamic", {}).items()
                                 if name.startswith(prefix)), None)
            if expected is None:
                errors.append(f"{node_id} {node['class_type']}: bilinmeyen girdi '{name}'")
                continue
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                got = output_type(value)
                if got is not None and got != expected:
                    errors.append(f"{node_id}.{name}: {got} bağlanmış, {expected} bekleniyor")
    return errors


# ----------------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------------
def make_video(path, fps, seconds, audio=True, w=160, h=90):
    n = int(round(fps * seconds))
    with av.open(str(path), "w") as out:
        vs = out.add_stream("libx264", rate=fps)
        vs.width, vs.height, vs.pix_fmt = w, h, "yuv420p"
        aud = None
        if audio:
            aud = out.add_stream("aac", rate=SR)
            aud.layout = "stereo"
        for i in range(n):
            val = int(min(255, i * 255 / max(1, n - 1)))
            fr = av.VideoFrame.from_ndarray(np.full((h, w, 3), val, np.uint8), format="rgb24").reformat(format="yuv420p")
            for p in vs.encode(fr):
                out.mux(p)
        for p in vs.encode():
            out.mux(p)
        if aud:
            total = int(SR * seconds)
            tone = (0.1 * np.sin(2 * np.pi * 440 * np.arange(total) / SR)).astype(np.float32)
            pts = 0
            for s in range(0, total, 1024):
                part = np.ascontiguousarray(np.stack([tone[s:s + 1024]] * 2))
                af = av.AudioFrame.from_ndarray(part, format="fltp", layout="stereo")
                af.sample_rate, af.pts, af.time_base = SR, pts, Fraction(1, SR)
                pts += part.shape[1]
                for p in aud.encode(af):
                    out.mux(p)
            for p in aud.encode():
                out.mux(p)
    return str(path)


def video_stats(path):
    with av.open(path) as c:
        v = c.streams.video[0]
        frames = [f for f in c.decode(v)]
        rate = float(v.average_rate)
    times = [f.time for f in frames]
    lum = [int(f.to_ndarray(format="gray")[0, 0]) for f in frames]
    audio_seconds = 0.0
    with av.open(path) as c:
        if c.streams.audio:
            audio_seconds = sum(f.samples for f in c.decode(c.streams.audio[0])) / SR
    return {"rate": rate, "frames": len(frames), "last": times[-1],
            "min_step": min(b - a for a, b in zip(times, times[1:])), "lum": lum, "audio_s": audio_seconds}


# ----------------------------------------------------------------------------
# İş akışı bağlantıları
# ----------------------------------------------------------------------------
def test_reference_video_chain_type_checks():
    engine = MiniMaxH3Engine()
    built = engine.build_workflow({
        "prompt": "<Video 1> hareketini <Picture 1> karakterine uygula",
        "duration": 6,
        "ref_images": ["asset_img_a.png"],
        "ref_videos": ["asset_vid_a.mp4", "asset_vid_b.mp4"],
        "ref_videos_prepared": [
            {"file": "asset_vid_a_ref24.mp4", "has_audio": True},
            {"file": "asset_vid_b_ref24.mp4", "has_audio": False},
        ],
        "ref_audios": ["asset_aud_a.wav"],
    })
    wf = built["prompt"]

    assert wf["8"]["class_type"] == "MiniMaxH3ReferenceToVideo"
    assert type_check_reference_chain(wf) == []

    # Video 0: LoadVideo(file) -> GetVideoComponents; kareler ve ses aynı numaralı yuvalara
    frames_link = wf["8"]["inputs"]["ref_videos.ref_video_0"]
    split = wf[frames_link[0]]
    assert split["class_type"] == "GetVideoComponents" and frames_link[1] == 0
    load = wf[split["inputs"]["video"][0]]
    assert load == {"class_type": "LoadVideo", "inputs": {"file": "asset_vid_a_ref24.mp4"}}
    assert wf["8"]["inputs"]["ref_video_audios.ref_video_audio_0"] == [frames_link[0], 1]

    # Video 1 sessiz: ses yuvası bağlanmamalı
    assert "ref_videos.ref_video_1" in wf["8"]["inputs"]
    assert "ref_video_audios.ref_video_audio_1" not in wf["8"]["inputs"]

    counts = built["metadata"]["reference_counts"]
    assert counts["videos"] == 2 and counts["video_audios"] == 1


def test_type_checker_rejects_old_wiring():
    """Denetleyicinin gerçekten yakaladığını göster: eski bağlantı biçimi reddedilmeli."""
    old = {
        "2": {"class_type": "CLIPLoader", "inputs": {}},
        "201": {"class_type": "LoadVideo", "inputs": {"video": "asset_vid_a.mp4"}},
        "8": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["2", 0], "prompt": "x", "width": 1344, "height": 768, "length": 124,
            "ref_image_size": "match", "ref_videos.ref_video_0": ["201", 0]}},
    }
    errors = type_check_reference_chain(old)
    assert any("gerekli girdi eksik 'file'" in e for e in errors), errors
    assert any("VIDEO bağlanmış, IMAGE bekleniyor" in e for e in errors), errors


def test_engine_detects_audio_from_comfy_input_when_not_prepared(tmp_path, monkeypatch):
    """Kuyruk dışı kullanımda (MCP/test) ses izi ComfyUI input dosyasından tespit edilir."""
    comfy_dir = tmp_path / "ComfyUI"
    (comfy_dir / "input").mkdir(parents=True)
    make_video(comfy_dir / "input" / "sesli.mp4", 24, 1.0, audio=True)
    make_video(comfy_dir / "input" / "sessiz.mp4", 24, 1.0, audio=False)
    monkeypatch.setattr(settings, "COMFYUI_DIR", str(comfy_dir))

    wf = MiniMaxH3Engine().build_workflow({
        "prompt": "x", "duration": 6, "ref_videos": ["sesli.mp4", "sessiz.mp4"],
    })["prompt"]

    assert "ref_video_audios.ref_video_audio_0" in wf["8"]["inputs"]
    assert "ref_video_audios.ref_video_audio_1" not in wf["8"]["inputs"]
    assert type_check_reference_chain(wf) == []


# ----------------------------------------------------------------------------
# 24 fps hazırlığı
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("src_fps, seconds, expected_frames, trimmed", [
    (30, 3.0, 72, False),
    (60, 2.0, 48, False),
    (24, 20.0, 360, True),   # 15 sn'ye kırpılır
])
def test_prepare_reference_video_to_24fps(tmp_path, src_fps, seconds, expected_frames, trimmed):
    src = make_video(tmp_path / "src.mp4", src_fps, seconds)
    src_bytes = open(src, "rb").read()
    dst = str(tmp_path / "src_ref24.mp4")

    meta = vc.prepare_reference_video(src, dst)

    st = video_stats(dst)
    assert meta["converted"] is True and meta["trimmed"] is trimmed and meta["has_audio"] is True
    assert st["rate"] == pytest.approx(24)
    assert abs(st["frames"] - expected_frames) <= 1
    # Gerçek hareket: kareler zamana yayılmış ve sırası korunmuş olmalı
    assert st["last"] == pytest.approx((expected_frames - 1) / 24, abs=0.1)
    assert st["min_step"] > 0
    assert all(b >= a - 2 for a, b in zip(st["lum"], st["lum"][1:]))
    assert st["audio_s"] == pytest.approx(min(seconds, 15.0), abs=0.05)
    assert open(src, "rb").read() == src_bytes  # kaynağa dokunulmaz


def test_prepare_reference_video_copies_compliant_video(tmp_path):
    src = make_video(tmp_path / "ok.mp4", 24, 3.0)
    dst = str(tmp_path / "ok_ref24.mp4")
    meta = vc.prepare_reference_video(src, dst)
    assert meta["converted"] is False
    assert open(dst, "rb").read() == open(src, "rb").read()


def test_prepare_reference_video_without_audio(tmp_path):
    src = make_video(tmp_path / "mute.mp4", 30, 2.0, audio=False)
    meta = vc.prepare_reference_video(src, str(tmp_path / "mute_ref24.mp4"))
    assert meta["has_audio"] is False
    assert vc.probe(str(tmp_path / "mute_ref24.mp4"))["audio_codec"] is None


def test_prepare_reference_video_rejects_too_short(tmp_path):
    src = make_video(tmp_path / "short.mp4", 30, 0.1)
    dst = tmp_path / "short_ref24.mp4"
    with pytest.raises(ValueError, match="çok kısa"):
        vc.prepare_reference_video(src, str(dst))
    assert not os.path.exists(str(dst) + ".part")


# ----------------------------------------------------------------------------
# Uçtan uca: kuyruk referansı hazırlar, ComfyUI'ye doğru zincir gider
# ----------------------------------------------------------------------------
class _State:
    submitted = None


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
            # İş hemen hata ile sonlansın: yalnızca gönderilen workflow'u inceliyoruz
            pid = self.path.rsplit("/", 1)[-1]
            return self._json({pid: {"status": {"status_str": "error", "messages": [[
                "execution_error", {"node_type": "Test", "exception_message": "test sonu"}]]}, "outputs": {}}})
        if self.path == "/system_stats":
            return self._json({"system": {}, "devices": []})
        if self.path == "/queue":
            return self._json({"queue_running": [], "queue_pending": []})
        return self._json({}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/prompt":
            _State.submitted = body.get("prompt")
            return self._json({"prompt_id": "stub-1"})
        return self._json({})


def test_queue_prepares_reference_video_and_submits_valid_chain(tmp_path):
    from app.backend.engines import base as engine_base
    from app.backend.queue_manager import QueueManager

    engine_base._OBJECT_INFO_CACHE.update(data=None, ts=0.0)
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    keys = ("COMFYUI_URL", "COMFY_POLL_INTERVAL", "FREE_VRAM_SETTLE_SECONDS")
    saved = {k: getattr(settings, k) for k in keys}
    settings.COMFYUI_URL = "http://127.0.0.1:%d" % server.server_address[1]
    settings.COMFY_POLL_INTERVAL = 0.05
    settings.FREE_VRAM_SETTLE_SECONDS = 0

    asset_name = "asset_vid_reftest30.mp4"
    asset_path = os.path.join(settings.LOCAL_ASSETS_DIR, asset_name)
    os.makedirs(settings.LOCAL_ASSETS_DIR, exist_ok=True)
    shutil.copy(make_video(tmp_path / "src.mp4", 30, 3.0), asset_path)
    prepared_path = os.path.join(settings.COMFYUI_DIR, "input", "asset_vid_reftest30_ref24.mp4")
    job = None
    try:
        qm = QueueManager()
        qm.jobs.clear()
        qm.queue.clear()

        async def go():
            j = qm.create_job({"model": "minimax_h3", "prompt": "<Video 1> hareketi", "duration": 4,
                               "ref_videos": ["asset_vid_reftest30"]})
            qm.queue.remove(j["id"])  # işi test yürütür; arka plan işçisi ikinci kez çalıştırmasın
            await qm._execute_job(j)
            return j

        job = asyncio.run(go())

        wf = _State.submitted
        assert wf is not None, job.get("error")
        assert type_check_reference_chain(wf) == []
        split_id = wf["8"]["inputs"]["ref_videos.ref_video_0"][0]
        load_id = wf[split_id]["inputs"]["video"][0]
        assert wf[load_id]["inputs"]["file"] == "asset_vid_reftest30_ref24.mp4"
        assert wf["8"]["inputs"]["ref_video_audios.ref_video_audio_0"] == [split_id, 1]

        # ComfyUI'ye giden kopya 24 fps; iş kaydında orijinal referans adı kalır
        st = video_stats(prepared_path)
        assert st["rate"] == pytest.approx(24) and abs(st["frames"] - 72) <= 1
        assert job["ref_videos"] == [asset_name]
        assert job["ref_videos_prepared"][0]["has_audio"] is True
    finally:
        engine_base._OBJECT_INFO_CACHE.update(data=None, ts=0.0)
        for k, v in saved.items():
            setattr(settings, k, v)
        server.shutdown()
        server.server_close()
        for p in (asset_path, prepared_path):
            if os.path.exists(p):
                os.remove(p)
        if job:
            shutil.rmtree(os.path.join(settings.LOCAL_JOBS_DIR, job["id"]), ignore_errors=True)
