"""
Zaman aşımı ve donma tespiti regresyon testleri.

Hatalar:
  1. Sabit 30 dakika sınırı, düzenli ilerleyen bir işi (8/10. adım) öldürüyordu.
  2. Donma tespiti çalışmıyordu: prompt ComfyUI kuyruğunda "çalışıyor" göründükçe sayaç sıfırlanıyordu.
  3. Backend vazgeçtiği promptu ComfyUI'de durdurmuyordu; iş arka planda sürüyor,
     sıradaki iş onun arkasında bekliyordu.
  4. Beklerken arayüz "Model Ağırlıkları Yükleniyor" yazıyordu (yeniden yükleme gibi görünüyordu).
"""

import asyncio
import json
import threading
import time

import pytest
from aiohttp import web

import config.settings as settings
from app.backend.queue_manager import (
    QueueManager,
    StepTimer,
    queue_presence_counts_as_activity,
)


# ----------------------------------------------------------------------------
# Birim testleri
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("running, pending, ws, expected", [
    (False, True, True, True),    # başka işin arkasında beklemek donma değildir
    (False, True, False, True),
    (True, False, True, False),   # çalışırken canlılık = WS bildirimi, kuyruk varlığı değil
    (True, False, False, True),   # WS yoksa bildirim gelemez; kuyruğa güven
    (False, False, True, False),
])
def test_queue_presence_counts_as_activity(running, pending, ws, expected):
    assert queue_presence_counts_as_activity(running, pending, ws) is expected


def test_step_timer_with_reported_numbers():
    """Kullanıcının logundaki gerçek hız: 142.5 sn/adım, 10 adım."""
    timer = StepTimer()
    t0 = 1000.0
    assert timer.update("9", 4, 10, t0) == (None, None)
    per_step, remaining = timer.update("9", 8, 10, t0 + 4 * 142.5)
    assert per_step == pytest.approx(142.5)
    assert remaining == pytest.approx(285.0)


def test_step_timer_resets_on_new_node_or_total():
    timer = StepTimer()
    timer.update("9", 1, 10, 0.0)
    timer.update("9", 5, 10, 40.0)
    # VAE decode gibi başka bir düğümün ilerlemesi eski hızla karışmamalı
    assert timer.update("14", 3, 20, 50.0) == (None, None)
    per_step, _ = timer.update("14", 5, 20, 54.0)
    assert per_step == pytest.approx(2.0)


# ----------------------------------------------------------------------------
# Sahte ComfyUI (HTTP + WebSocket aynı portta)
# ----------------------------------------------------------------------------
class ComfyState:
    def reset(self, scenario):
        self.scenario = scenario
        self.interrupts = 0
        self.deleted = []
        self.progress_steps = 0


STATE = ComfyState()
STATE.reset("running")


async def system_stats(request):
    return web.json_response({"system": {}, "devices": []})


async def queue_get(request):
    if STATE.scenario == "pending":
        return web.json_response({"queue_running": [[0, "other-99"]], "queue_pending": [[1, "stub-1"]]})
    return web.json_response({"queue_running": [[0, "stub-1"]], "queue_pending": []})


async def queue_post(request):
    body = await request.json()
    STATE.deleted.extend(body.get("delete", []))
    return web.json_response({})


async def history(request):
    return web.json_response({})


async def prompt(request):
    await request.read()
    return web.json_response({"prompt_id": "stub-1"})


async def interrupt(request):
    STATE.interrupts += 1
    return web.json_response({})


async def free(request):
    return web.json_response({})


async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    if STATE.scenario == "progress":
        # Düzenli ilerleme: her adım bildirimi arasında kısa süre
        await ws.send_str(json.dumps({"type": "executing", "data": {"node": "9", "prompt_id": "stub-1"}}))
        for step in range(1, 11):
            await asyncio.sleep(0.05)
            STATE.progress_steps = step
            await ws.send_str(json.dumps({"type": "progress", "data": {
                "value": step, "max": 10, "node": "9", "prompt_id": "stub-1"}}))
    # "running" senaryosu: bağlantı açık kalır ama hiçbir bildirim gelmez (takılmış düğüm)
    async for _ in ws:
        pass
    return ws


@pytest.fixture(scope="module")
def comfy():
    app = web.Application()
    app.router.add_get("/system_stats", system_stats)
    app.router.add_get("/queue", queue_get)
    app.router.add_post("/queue", queue_post)
    app.router.add_get("/history/{pid}", history)
    app.router.add_post("/prompt", prompt)
    app.router.add_post("/interrupt", interrupt)
    app.router.add_post("/free", free)
    app.router.add_get("/ws", ws_handler)

    loop = asyncio.new_event_loop()
    runner = web.AppRunner(app)
    started = threading.Event()
    port_box = {}

    def serve():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, "127.0.0.1", 0)
        loop.run_until_complete(site.start())
        port_box["port"] = site._server.sockets[0].getsockname()[1]
        started.set()
        loop.run_forever()

    threading.Thread(target=serve, daemon=True).start()
    assert started.wait(10)

    keys = ("COMFYUI_URL", "COMFY_POLL_INTERVAL", "COMFY_CRASH_GRACE_SECONDS",
            "FREE_VRAM_SETTLE_SECONDS", "COMFYUI_MAX_WAIT_SECONDS", "COMFY_STALL_SECONDS")
    saved = {k: getattr(settings, k) for k in keys}
    settings.COMFYUI_URL = "http://127.0.0.1:%d" % port_box["port"]
    settings.COMFY_POLL_INTERVAL = 0.05
    settings.COMFY_CRASH_GRACE_SECONDS = 0
    settings.FREE_VRAM_SETTLE_SECONDS = 0

    yield STATE

    for k, v in saved.items():
        setattr(settings, k, v)
    asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(10)
    loop.call_soon_threadsafe(loop.stop)


def _run_job(scenario, max_wait, stall, observe=None):
    STATE.reset(scenario)
    settings.COMFYUI_MAX_WAIT_SECONDS = max_wait
    settings.COMFY_STALL_SECONDS = stall

    qm = QueueManager()
    qm.jobs.clear()
    qm.queue.clear()
    seen_stages = []

    async def go():
        job = qm.create_job({"model": "ltx25", "prompt": f"zaman aşımı testi {scenario}", "duration": 2})
        qm.queue.remove(job["id"])  # işi test yürütür; arka plan işçisi ikinci kez çalıştırmasın
        task = asyncio.create_task(qm._execute_job(job))
        while not task.done():
            seen_stages.append(job.get("current_stage"))
            await asyncio.sleep(0.02)
        await task
        return job

    t0 = time.time()
    job = asyncio.run(go())
    return job, seen_stages, time.time() - t0


def test_stalled_running_job_detected_by_missing_events(comfy):
    """Kuyrukta 'çalışıyor' görünse de bildirim gelmiyorsa donma tespit edilmeli."""
    job, _, elapsed = _run_job("running", max_wait=60, stall=1)

    assert job["status"] == "failed"
    assert "donma" in job["error"]
    # Mutlak sınır (60 sn) değil donma sınırı (1 sn) tetiklemeli
    assert elapsed < 30, elapsed
    # Vazgeçilen prompt ComfyUI'de de kesilmeli
    assert comfy.interrupts == 1
    assert comfy.deleted == []


def test_timeout_interrupts_running_prompt_and_reports_context(comfy):
    job, _, _ = _run_job("running", max_wait=1, stall=60)

    assert job["status"] == "failed"
    assert "mutlak süre sınırını" in job["error"]
    assert comfy.interrupts == 1
    # Hata mesajı teşhis için işin kendisini de özetlemeli
    assert "İş: LTX-2.5" in job["error"]
    assert "adım" in job["error"]


def test_pending_prompt_is_labelled_waiting_and_removed_not_interrupted(comfy):
    """Başka işin arkasında bekleyen prompt 'yükleniyor' diye gösterilmemeli; başkasının işi kesilmemeli."""
    job, stages, _ = _run_job("pending", max_wait=1, stall=60)

    assert any(s and "kuyruğunda bekliyor" in s for s in stages), stages[-5:]
    assert not any(s and "Model Ağırlıkları Yükleniyor" in s for s in stages)
    # Yalnızca kendi bekleyen promptumuz silinmeli; çalışan başka işe interrupt gönderilmemeli
    assert comfy.deleted == ["stub-1"]
    assert comfy.interrupts == 0


def test_progress_reports_step_speed_and_eta(comfy):
    """Adım bildirimleri geldikçe arayüzde hız ve kalan süre görünmeli."""
    job, stages, _ = _run_job("progress", max_wait=2, stall=60)

    assert comfy.progress_steps == 10
    assert any(s and "/adım" in s and "kaldı" in s for s in stages), stages[-5:]
    assert job.get("step_seconds") is not None
