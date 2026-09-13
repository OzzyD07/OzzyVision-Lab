"""
Uçtan uca entegrasyon testi.

Sahte (stub) bir ComfyUI HTTP sunucusu ayağa kaldırıp gerçek iş akışını doğrular:
  - LoRA'lı işlerde LoRA dosyasının ComfyUI arama yoluna senkronlanması
  - Model / LoRA kombinasyonu değiştiğinde VRAM'in (/free) boşaltılması -> CUDA OOM önlemi
  - Gönderilen workflow'un LoraLoaderModelOnly kullanması (CLIP patchlenmemesi)
  - İşin tamamlanıp çıktının kalıcı depoya yazılması
  - Eksik LoRA'nın anlaşılır hata ile reddedilmesi
  - İptalin ComfyUI tarafında da /interrupt ile uygulanması
"""

import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import config.settings as settings


class StubComfyState:
    def __init__(self):
        self.free_calls = []
        self.submitted_workflows = []
        self.interrupts = 0
        self.output_filename = "stub_output.mp4"
        # /object_info yalnızca doğrulama testlerinde etkinleştirilir;
        # None iken ComfyUI "şema bilinmiyor" kabul edilir ve doğrulama atlanır.
        self.object_info = None


STATE = StubComfyState()


class StubComfyHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # sessiz test çıktısı
        pass

    def _json(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/object_info":
            if STATE.object_info is None:
                self._json({}, 404)
            else:
                self._json(STATE.object_info)
        elif self.path == "/system_stats":
            self._json({"system": {"comfyui_version": "stub"}, "devices": []})
        elif self.path == "/queue":
            self._json({"queue_running": [], "queue_pending": []})
        elif self.path.startswith("/history/"):
            prompt_id = self.path.rsplit("/", 1)[-1]
            self._json({
                prompt_id: {
                    "status": {"status_str": "success", "completed": True, "messages": []},
                    "outputs": {"11": {"gifs": [{"filename": STATE.output_filename, "subfolder": ""}]}}
                }
            })
        else:
            self._json({}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = {}

        if self.path == "/prompt":
            STATE.submitted_workflows.append(payload.get("prompt", {}))
            self._json({"prompt_id": "stub-%d" % len(STATE.submitted_workflows)})
        elif self.path == "/free":
            STATE.free_calls.append(payload)
            self._json({})
        elif self.path == "/interrupt":
            STATE.interrupts += 1
            self._json({})
        elif self.path == "/queue":
            self._json({})
        else:
            self._json({}, 404)


@pytest.fixture(scope="module")
def stub_comfy():
    server = HTTPServer(("127.0.0.1", 0), StubComfyHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    original_url = settings.COMFYUI_URL
    original_settle = settings.FREE_VRAM_SETTLE_SECONDS
    settings.COMFYUI_URL = "http://127.0.0.1:%d" % port
    settings.FREE_VRAM_SETTLE_SECONDS = 0.0

    # Sahte çıktı videosunu ComfyUI output dizinine yerleştir
    out_dir = os.path.join(settings.COMFYUI_DIR, "output")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, STATE.output_filename)
    with open(out_file, "wb") as f:
        f.write(b"STUB_MP4")

    yield STATE

    settings.COMFYUI_URL = original_url
    settings.FREE_VRAM_SETTLE_SECONDS = original_settle
    server.shutdown()
    server.server_close()
    if os.path.exists(out_file):
        os.remove(out_file)


def _fresh_queue_manager():
    """Testler arasında izole bir QueueManager örneği üretir."""
    from app.backend.queue_manager import QueueManager
    qm = QueueManager()
    qm.jobs.clear()
    qm.queue.clear()
    return qm


def _make_lora(name="integration_lora.safetensors"):
    os.makedirs(settings.ACTIVE_LORAS_DIR, exist_ok=True)
    path = os.path.join(settings.ACTIVE_LORAS_DIR, name)
    with open(path, "wb") as f:
        f.write(b"L" * 8192)
    return name, path


def test_lora_job_frees_vram_and_uses_model_only(stub_comfy):
    """LoRA'lı iş: VRAM boşaltılmalı, model-only LoRA düğümü gönderilmeli, iş tamamlanmalı."""
    lora_name, lora_path = _make_lora()
    stub_comfy.free_calls.clear()
    stub_comfy.submitted_workflows.clear()

    qm = _fresh_queue_manager()

    async def run():
        job = qm.create_job({
            "model": "ltx25",
            "prompt": "entegrasyon testi sahnesi",
            "duration": 2,
            "loras": [{"name": lora_name, "strength": 0.75}]
        })
        qm.queue.remove(job["id"])  # işi test yürütür; arka plan işçisi ikinci kez çalıştırmasın
        await qm._execute_job(job)
        return job

    job = asyncio.run(run())

    try:
        assert job["status"] == "completed", job.get("error")
        assert job["progress"] == 100
        assert os.path.exists(job["local_video_path"])

        # VRAM, LoRA'lı ilk iş öncesinde boşaltılmış olmalı (OOM önlemi)
        assert stub_comfy.free_calls, "LoRA'li is oncesi /free cagrilmadi"
        assert stub_comfy.free_calls[-1]["unload_models"] is True

        # Gönderilen workflow CLIP'i patchlememeli
        wf = stub_comfy.submitted_workflows[-1]
        lora_nodes = [n for n in wf.values() if "Lora" in n.get("class_type", "")]
        assert len(lora_nodes) == 1
        assert lora_nodes[0]["class_type"] == "LoraLoaderModelOnly"
        assert "clip" not in lora_nodes[0]["inputs"]
        assert wf["4"]["inputs"]["clip"] == ["2", 0]
    finally:
        for p in (lora_path, os.path.join(settings.COMFYUI_LORAS_DIR, lora_name)):
            if os.path.lexists(p):
                os.remove(p)


def test_engine_switch_frees_vram(stub_comfy):
    """LTX-2.5 -> MiniMax H3 geçişinde VRAM boşaltılmalı (iki dev model aynı anda yüklenmemeli)."""
    stub_comfy.free_calls.clear()
    qm = _fresh_queue_manager()

    async def run():
        first = qm.create_job({"model": "ltx25", "prompt": "ilk sahne", "duration": 2})
        qm.queue.remove(first["id"])  # işi test yürütür; arka plan işçisi ikinci kez çalıştırmasın
        await qm._execute_job(first)
        free_after_first = len(stub_comfy.free_calls)

        second = qm.create_job({"model": "minimax_h3", "prompt": "ikinci sahne", "duration": 4})
        qm.queue.remove(second["id"])  # işi test yürütür; arka plan işçisi ikinci kez çalıştırmasın
        await qm._execute_job(second)
        return first, second, free_after_first

    first, second, free_after_first = asyncio.run(run())

    assert first["status"] == "completed", first.get("error")
    # LoRA'sız ilk iş için gereksiz boşaltma yapılmamalı
    assert free_after_first == 0
    # Motor değişiminde mutlaka boşaltılmalı
    assert len(stub_comfy.free_calls) > free_after_first, "Model gecisinde /free cagrilmadi"


def test_missing_lora_fails_with_clear_message(stub_comfy):
    """Olmayan bir LoRA, ComfyUI'nin şifreli hatası yerine anlaşılır mesajla reddedilmeli."""
    qm = _fresh_queue_manager()

    async def run():
        job = qm.create_job({
            "model": "ltx25",
            "prompt": "eksik lora testi",
            "duration": 2,
            "loras": [{"name": "bu_lora_yok_9999.safetensors", "strength": 1.0}]
        })
        qm.queue.remove(job["id"])  # işi test yürütür; arka plan işçisi ikinci kez çalıştırmasın
        await qm._execute_job(job)
        return job

    job = asyncio.run(run())
    assert job["status"] == "failed"
    assert "bu_lora_yok_9999.safetensors" in job["error"]
    assert "bulunamad" in job["error"].lower()


def test_cancel_interrupts_comfyui(stub_comfy):
    """Çalışan iş iptal edildiğinde ComfyUI'ye /interrupt gönderilmeli."""
    qm = _fresh_queue_manager()
    before = stub_comfy.interrupts

    job = qm.create_job({"model": "ltx25", "prompt": "iptal", "duration": 2})
    qm.active_job_id = job["id"]
    qm.active_prompt_id = "stub-999"

    assert qm.cancel_job(job["id"]) is True
    assert stub_comfy.interrupts > before
    assert job["status"] == "cancelled"
    qm.active_job_id = None


# ----------------------------------------------------------------------
# Workflow şema doğrulaması (eksik custom node / uyumsuz girdi)
# ----------------------------------------------------------------------
def _clear_object_info_cache():
    from app.backend.engines import base as engine_base
    engine_base._OBJECT_INFO_CACHE["data"] = None
    engine_base._OBJECT_INFO_CACHE["ts"] = 0.0


def test_missing_custom_node_gives_actionable_error(stub_comfy):
    """Eksik custom node, ComfyUI HTTP 400'ü yerine kurulum ipucu içeren hata vermeli."""
    from app.backend.engines import get_engine

    # ComfyUI'de yalnızca çekirdek düğümler kurulu; GGUF/VHS eklentileri yok
    stub_comfy.object_info = {
        "CLIPLoader": {"input": {"required": {"clip_name": [[]], "type": [[]]}}},
    }
    _clear_object_info_cache()
    try:
        engine = get_engine("ltx25")
        workflow = {
            "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "x.gguf"}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "c.safetensors", "type": "ltxv"}},
            "11": {"class_type": "VHS_VideoCombine", "inputs": {}},
        }
        with pytest.raises(RuntimeError) as exc:
            engine.validate_workflow(workflow)

        message = str(exc.value)
        assert "UnetLoaderGGUF" in message
        assert "ComfyUI-GGUF" in message
        assert "VHS_VideoCombine" in message
        assert "VideoHelperSuite" in message
    finally:
        stub_comfy.object_info = None
        _clear_object_info_cache()


def test_unsupported_optional_input_is_pruned(stub_comfy):
    """Düğümün kabul etmediği isteğe bağlı girdiler (ör. audio_vae) sessizce kaldırılmalı."""
    from app.backend.engines import get_engine

    stub_comfy.object_info = {
        "MiniMaxH3ImageToVideo": {
            "input": {
                "required": {"clip": [[]], "vae": [[]], "prompt": [[]],
                             "width": [[]], "height": [[]], "length": [[]]}
            }
        }
    }
    _clear_object_info_cache()
    try:
        engine = get_engine("minimax_h3")
        workflow = {
            "8": {
                "class_type": "MiniMaxH3ImageToVideo",
                "inputs": {
                    "clip": ["2", 0], "vae": ["3", 0], "audio_vae": ["4", 0],
                    "prompt": "x", "width": 1344, "height": 768, "length": 124
                }
            }
        }
        cleaned, warnings = engine.validate_workflow(workflow)
        assert "audio_vae" not in cleaned["8"]["inputs"]
        assert cleaned["8"]["inputs"]["vae"] == ["3", 0]
        assert any("audio_vae" in w for w in warnings)
    finally:
        stub_comfy.object_info = None
        _clear_object_info_cache()


def test_dynamic_reference_inputs_are_preserved(stub_comfy):
    """Çoklu referans için üretilen dinamik girdiler (ref_images.ref_image_0) korunmalı."""
    from app.backend.engines import get_engine

    stub_comfy.object_info = {
        "MiniMaxH3ReferenceToVideo": {
            "input": {"required": {"clip": [[]], "vae": [[]], "prompt": [[]]}}
        }
    }
    _clear_object_info_cache()
    try:
        engine = get_engine("minimax_h3")
        workflow = {
            "8": {
                "class_type": "MiniMaxH3ReferenceToVideo",
                "inputs": {
                    "clip": ["2", 0], "vae": ["3", 0], "prompt": "x",
                    "ref_images.ref_image_0": ["101", 0]
                }
            }
        }
        cleaned, _ = engine.validate_workflow(workflow)
        assert cleaned["8"]["inputs"]["ref_images.ref_image_0"] == ["101", 0]
    finally:
        stub_comfy.object_info = None
        _clear_object_info_cache()
