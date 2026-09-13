"""
Bellek teşhisi regresyon testleri.

Hata: ComfyUI süreci işletim sistemi tarafından (sistem RAM'i dolunca) öldürüldüğünde
iş "Muhtemelen OOM" diye raporlanıp VRAM önerileri veriliyordu; VRAM ise hiç dolmamıştı.
Ayrıca "cuda error" içeren her hata OOM sayılıyordu.
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import config.settings as settings
from app.backend import resources
from app.backend.queue_manager import QueueManager, _is_oom_error

GIB = 1024 ** 3


# ----------------------------------------------------------------------------
# Saf birim testleri
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("message, expected", [
    ("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB.", resources.GPU_OOM),
    ("Allocation on device 0 would exceed allowed memory. (out of memory)", resources.GPU_OOM),
    ("DefaultCPUAllocator: not enough memory: you tried to allocate 400 bytes.", resources.RAM_OOM),
    ("MemoryError", resources.RAM_OOM),
    # Bellekle ilgisiz CUDA hataları OOM sayılmamalı (eskiden "cuda error" işaretiyle sayılıyordu)
    ("CUDA error: an illegal memory access was encountered", resources.OTHER),
    ("CUDA error: no kernel image is available for execution on the device", resources.OTHER),
    ("Düğüm 1 (UNETLoader): Value not in list", resources.OTHER),
])
def test_classify_failure_messages(message, expected):
    assert resources.classify_failure(message) == expected


def test_out_of_memory_error_is_gpu_not_ram():
    """'OutOfMemoryError' içinde 'memoryerror' geçer; yine de GPU hatası sayılmalı."""
    assert resources.classify_failure("OutOfMemoryError") == resources.GPU_OOM


def test_dead_process_classified_by_ram_pressure():
    high = {"ram_used_gb": 80.1, "ram_total_gb": 83.5}
    low = {"ram_used_gb": 30.0, "ram_total_gb": 83.5}
    assert resources.classify_failure("yanıt yok", comfy_alive=False, last_sample=high) == resources.RAM_OOM
    assert resources.classify_failure("yanıt yok", comfy_alive=False, last_sample=low) == resources.CRASH
    assert resources.classify_failure("yanıt yok", comfy_alive=False, last_sample=None) == resources.CRASH


def test_is_oom_error_compat():
    assert _is_oom_error("CUDA out of memory")
    assert _is_oom_error("DefaultCPUAllocator: can't allocate memory")
    assert not _is_oom_error("CUDA error: an illegal memory access was encountered")


@pytest.mark.parametrize("message, wanted, free", [
    ("CUDA out of memory. Tried to allocate 2.00 GiB. GPU 0 has a total capacity of 79.15 GiB "
     "of which 1.25 GiB is free.", "2.00 GiB", "1.25 GiB"),
    # cudaMallocAsync: "Requested : X GiB Free (...)" sırası genel deseni yanıltabilir
    ("Allocation on device 0 would exceed allowed memory. (out of memory) "
     "Requested : 12.00 GiB Free (according to CUDA): 1.25 GiB", "12.00 GiB", "1.25 GiB"),
    ("başka bir hata", None, None),
])
def test_parse_allocation(message, wanted, free):
    assert resources.parse_allocation(message) == (wanted, free)


def test_parse_comfy_stats_real_shape():
    stats = {
        "system": {"ram_total": 83.5 * GIB, "ram_free": 20.0 * GIB, "comfyui_version": "x"},
        "devices": [{
            "name": "cuda:0 NVIDIA A100-SXM4-80GB : cudaMallocAsync",
            "type": "cuda", "index": 0,
            "vram_total": 79.2 * GIB, "vram_free": 49.2 * GIB,
        }],
    }
    sample = resources.parse_comfy_stats(stats)
    assert sample == {
        "ram_total_gb": 83.5, "ram_used_gb": 63.5,
        "gpu_name": "NVIDIA A100-SXM4-80GB",
        "vram_total_gb": 79.2, "vram_used_gb": 30.0,
    }
    assert resources.parse_comfy_stats(None) is None
    assert resources.parse_comfy_stats({"system": {}, "devices": []}) is None


def test_backend_does_not_import_torch():
    """torch.cuda çağrıları API sürecinde CUDA bağlamı açıp VRAM + RAM tüketiyordu."""
    import subprocess
    import sys
    code = "import sys, app.backend.main, app.mcp.server; print('torch' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "False"


# ----------------------------------------------------------------------------
# Sahte ComfyUI ile uçtan uca senaryolar
# ----------------------------------------------------------------------------
class Stub:
    def __init__(self):
        self.reset("ok")

    def reset(self, scenario):
        self.scenario = scenario
        self.stats_calls = 0
        self.dead = False
        self.free_calls = 0
        self.ram_used_gb = 40.0


STUB = Stub()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if STUB.dead:
            return self._json({}, 500)

        if self.path == "/system_stats":
            STUB.stats_calls += 1
            if STUB.scenario == "ram_oom":
                # RAM her ölçümde artar; 3. ölçümden sonra süreç "öldürülür"
                STUB.ram_used_gb = min(81.5, 60.0 + STUB.stats_calls * 10)
                if STUB.stats_calls >= 3:
                    STUB.dead = True
            return self._json({
                "system": {"ram_total": 83.5 * GIB, "ram_free": (83.5 - STUB.ram_used_gb) * GIB},
                "devices": [{"name": "cuda:0 NVIDIA A100-SXM4-80GB", "type": "cuda",
                             "vram_total": 79.2 * GIB, "vram_free": 45.0 * GIB}],
            })

        if self.path == "/queue":
            return self._json({"queue_running": [[0, "stub-1"]], "queue_pending": []})

        if self.path.startswith("/history/"):
            pid = self.path.rsplit("/", 1)[-1]
            if STUB.scenario == "gpu_oom" and STUB.stats_calls >= 1:
                return self._json({pid: {
                    "status": {"status_str": "error", "messages": [["execution_error", {
                        "node_type": "KSampler",
                        "exception_message": "CUDA out of memory. Tried to allocate 14.00 GiB. "
                                             "GPU 0 has a total capacity of 79.15 GiB of which 3.10 GiB is free.",
                    }]]},
                    "outputs": {},
                }})
            return self._json({})

        return self._json({}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if STUB.dead:
            return self._json({}, 500)
        if self.path == "/prompt":
            return self._json({"prompt_id": "stub-1"})
        if self.path == "/free":
            STUB.free_calls += 1
            return self._json({})
        return self._json({})


@pytest.fixture(scope="module")
def comfy():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    saved = {k: getattr(settings, k) for k in (
        "COMFYUI_URL", "COMFY_POLL_INTERVAL", "COMFY_CRASH_GRACE_SECONDS", "FREE_VRAM_SETTLE_SECONDS")}
    settings.COMFYUI_URL = "http://127.0.0.1:%d" % server.server_address[1]
    settings.COMFY_POLL_INTERVAL = 0.05
    settings.COMFY_CRASH_GRACE_SECONDS = 0
    settings.FREE_VRAM_SETTLE_SECONDS = 0

    yield STUB

    for k, v in saved.items():
        setattr(settings, k, v)
    server.shutdown()
    server.server_close()


def _run(scenario):
    STUB.reset(scenario)
    qm = QueueManager()
    qm.jobs.clear()
    qm.queue.clear()

    async def go():
        job = qm.create_job({"model": "ltx25", "prompt": f"bellek testi {scenario}", "duration": 2})
        await qm._execute_job(job)
        return job

    return qm, asyncio.run(go())


def test_ram_exhaustion_reported_as_ram_not_vram(comfy):
    qm, job = _run("ram_oom")

    assert job["status"] == "failed"
    assert job["failure_kind"] == resources.RAM_OOM
    assert "Sistem RAM" in job["error"]
    assert "VRAM değil" in job["error"]
    # Tepe ölçüm hatada görünmeli: VRAM dolu değil, RAM dolu
    peak = job["resource_peak"]
    assert peak["vram_used_gb"] < peak["vram_total_gb"] * 0.5
    assert peak["ram_used_gb"] / peak["ram_total_gb"] >= resources.RAM_PRESSURE_RATIO
    assert "Tepe kullanım" in job["error"]
    assert "COMFY_LOW_RAM" in job["error"]
    # Eski yanıltıcı metin bir daha çıkmamalı
    assert "Muhtemelen OOM" not in job["error"]


def test_gpu_oom_reported_with_allocation_numbers(comfy):
    qm, job = _run("gpu_oom")

    assert job["status"] == "failed"
    assert job["failure_kind"] == resources.GPU_OOM
    assert "14.00 GiB istendi" in job["error"]
    assert "3.10 GiB boştu" in job["error"]
    # GPU OOM sonrası VRAM boşaltılmalı (ComfyUI hâlâ ayakta)
    assert comfy.free_calls >= 1


def test_live_resources_broadcast_during_job(comfy):
    """Arayüzdeki gösterge iş sırasında ComfyUI ölçümünü canlı almalı."""
    qm, _ = _run("ram_oom")
    sent = []

    class FakeWS:
        async def send_json(self, payload):
            sent.append(payload)

    qm.ws_clients.add(FakeWS())
    asyncio.run(qm.broadcast_state())

    resources_payload = sent[-1]["resources"]
    assert resources_payload["ram_total_gb"] == 83.5
    assert resources_payload["vram_total_gb"] == 79.2
