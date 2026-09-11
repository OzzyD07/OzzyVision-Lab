"""
Job Queue and Execution Manager
FIFO kuyruk mantığıyla tekil GPU (A100) üzerinde işleri sıralı yürütür.
Gerçek zamanlı durum değişimlerini ve yüzdeyi WebSocket üzerinden yayınlar.
"""

import asyncio
import datetime
import os
import time
import uuid
import shutil
import json
from typing import Dict, Any, List, Optional, Set, Tuple
from fastapi import WebSocket
import websockets

from app.backend.storage import storage, safe_copy
from app.backend.engines import get_engine
import app.backend.lora_manager as lora_manager
import config.settings as settings


def read_comfyui_log_tail(num_lines: int = 40) -> str:
    """ComfyUI log dosyasının son satırlarını güvenli bir şekilde okur."""
    candidates = [
        "/content/comfyui.log",
        os.path.join(getattr(settings, "COMFYUI_DIR", ""), "comfyui.log"),
        os.path.expanduser("~/comfyui.log"),
        os.path.join(os.getcwd(), "comfyui.log"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    return "".join(lines[-num_lines:])
            except Exception:
                pass
    return ""


def extract_relevant_error(log_text: str) -> Optional[str]:
    """Log metninden Traceback veya belirgin hata mesajlarını ayıklar."""
    if not log_text:
        return None
    lines = [line.strip() for line in log_text.splitlines() if line.strip()]
    for line in reversed(lines):
        if any(keyword in line for keyword in ["Error:", "Exception:", "OutOfMemoryError", "CUDA out of memory", "Killed", "FileNotFoundError", "ModuleNotFoundError"]):
            return line
    return None


OOM_MARKERS = (
    "out of memory",
    "outofmemoryerror",
    "cuda error",
    "not enough memory",
    "alloc failed",
    "torch.cuda.outofmemory",
)


def _is_oom_error(message: str) -> bool:
    """Hata metninin bellek yetersizliği kaynaklı olup olmadığını anlar."""
    low = (message or "").lower()
    return any(marker in low for marker in OOM_MARKERS)


def is_prompt_in_queue(queue_data: dict, prompt_id: str) -> Tuple[bool, bool]:
    """ComfyUI /queue verisinde prompt_id'nin durumunu (running, pending) döner."""
    running = False
    pending = False
    if not isinstance(queue_data, dict):
        return False, False
    for item in queue_data.get("queue_running", []):
        if isinstance(item, list) and len(item) > 1 and item[1] == prompt_id:
            running = True
            break
    for item in queue_data.get("queue_pending", []):
        if isinstance(item, list) and len(item) > 1 and item[1] == prompt_id:
            pending = True
            break
    return running, pending


NODE_STAGE_INFO = {
    "UNETLoader": ("Model Ağırlıkları Yükleniyor (Diffusion UNET)...", 20),
    "UnetLoaderGGUF": ("GGUF Model Ağırlıkları Yükleniyor...", 20),
    "CLIPLoader": ("Metin Kodlayıcı Yükleniyor (Qwen / CLIP)...", 35),
    "DualCLIPLoader": ("Metin Kodlayıcı Yükleniyor (Gemma / CLIP)...", 35),
    "CLIPLoaderGGUF": ("GGUF Metin Kodlayıcı Yükleniyor...", 35),
    "VAELoader": ("VAE Modelleri Yükleniyor...", 42),
    "MiniMaxH3ReferenceToVideo": ("Referanslar ve Koşullandırma Hazırlanıyor...", 48),
    "MiniMaxH3ImageToVideo": ("Görsel Referansı Hazırlanıyor...", 48),
    "LTXVConditioning": ("Kamera ve Prompt Koşullandırması...", 48),
    "KSampler": ("Video Kareleri Üretiliyor (Sampling)...", 50),
    "VAEDecode": ("Video Kareleri Çözümleniyor (VAE Decode)...", 88),
    "VAEDecodeAudio": ("Ses Dalgaları Çözümleniyor (Audio VAE)...", 89),
    "CreateVideo": ("Video ve Ses Birleştiriliyor (CreateVideo)...", 92),
    "SaveVideo": ("MP4 Video Dosyası Kaydediliyor (SaveVideo)...", 94),
    "VHS_VideoCombine": ("MP4 Video Dosyası Kodlanıyor (Video Combine)...", 94),
    "LoraLoaderModelOnly": ("LoRA Ağırlıkları Uygulanıyor...", 25),
    "LoraLoader": ("LoRA Ağırlıkları Uygulanıyor...", 25),
    "LoadImage": ("Referans Görsel Okunuyor...", 45),
    "LoadVideo": ("Referans Video Okunuyor...", 45),
    "LoadAudio": ("Referans Ses Okunuyor...", 45),
    "CLIPTextEncode": ("Prompt Kodlanıyor (Text Encode)...", 46),
    "LTXVImgToVideo": ("Referans Görsel Latent'e Dönüştürülüyor...", 47),
    "LTXVEmptyLatentAudio": ("Ses Latent Uzayı Hazırlanıyor...", 47),
    "LTXVConcatAVLatent": ("Video ve Ses Latentleri Birleştiriliyor...", 48),
    "KSamplerSelect": ("Örnekleyici Seçiliyor...", 48),
    "BasicScheduler": ("Gürültü Programı (Sigmas) Hesaplanıyor...", 48),
    "RandomNoise": ("Başlangıç Gürültüsü Üretiliyor...", 49),
    "BasicGuider": ("Koşullandırma Uygulanıyor...", 49),
    "SamplerCustomAdvanced": ("Video Kareleri Üretiliyor (Sampling)...", 50),
    "LTXVSeparateAVLatent": ("Video ve Ses Latentleri Ayrıştırılıyor...", 87),
    "LTXVAudioVAEDecode": ("Ses Dalgaları Çözümleniyor (Audio VAE)...", 89)
}

# Örnekleme düğümleri: ilerleme yüzdesi adım bildirimlerinden (progress) gelir,
# düğüm bildiriminden gelen sabit yüzde ile ezilmemelidir.
SAMPLER_NODE_TYPES = {"KSampler", "KSamplerAdvanced", "SamplerCustomAdvanced", "SamplerCustom"}


class JobCancelled(Exception):
    """Kullanıcı tarafından istenen iptal (gerçek asyncio iptalinden ayrıştırılır)."""
    pass


class JobStatus:
    QUEUED = "queued"
    PREPARING = "preparing"
    GENERATING = "generating"
    UPSCALING = "upscaling"
    ENCODING = "encoding"
    SAVING = "saving"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QueueManager:
    """Tek GPU için asenkron sıralı iş kuyruğu yöneticisi"""

    def __init__(self):
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.queue: List[str] = []
        self.active_job_id: Optional[str] = None
        self.is_running = False
        self.ws_clients: Set[WebSocket] = set()
        self.worker_task: Optional[asyncio.Task] = None

        # Aktif ComfyUI promptu (iptal edebilmek için)
        self.active_prompt_id: Optional[str] = None
        self._cancel_requested: Set[str] = set()

        # ComfyUI'de o an yüklü olan model/LoRA kombinasyonunun imzası.
        # Kombinasyon değiştiğinde VRAM boşaltılır, aksi halde ComfyUI eski
        # ağırlıkları bellekte tutup yenisini yüklemeye çalışır ve OOM olur.
        self._loaded_signature: Optional[str] = None

        # İlerleme yazımlarını kısıtlamak için son kalıcılaştırma zamanı
        self._last_persist_ts: Dict[str, float] = {}

        # Worker döngüsünü uyandırma sinyali (kuyruk boşken kapanma yarışını önler)
        self._wakeup: asyncio.Event = asyncio.Event()

        # Başlangıçta kalıcı depodan geçmiş işleri belleğe yükle
        self._rehydrate_from_storage()

    def _rehydrate_from_storage(self):
        """Drive veya yerel depodaki geçmiş job'ları yükler."""
        loaded = storage.load_all_jobs()
        for j in loaded:
            self.jobs[j["id"]] = j
            # Eğer sistem aniden kapanmışsa ve yarım kalan 'generating' iş varsa durumunu failed yap
            if j.get("status") in [JobStatus.PREPARING, JobStatus.GENERATING, JobStatus.UPSCALING]:
                j["status"] = JobStatus.FAILED
                j["error"] = "Sistem yeniden başlatıldı; iş yarıda kaldı."
                storage.save_job(j)

    def _persist(self, job: Dict[str, Any], force: bool = True):
        """
        job.json'u diske/Drive'a yazar.

        `force=False` yalnızca ilerleme yüzdesi güncellemelerinde kullanılır:
        Google Drive'a saniyede bir yazmak üretimi belirgin şekilde yavaşlattığı
        için bu tür güncellemeler PROGRESS_PERSIST_INTERVAL ile kısıtlanır.
        """
        job_id = job.get("id")
        if not force:
            interval = float(getattr(settings, "PROGRESS_PERSIST_INTERVAL", 10))
            now = time.time()
            last = self._last_persist_ts.get(job_id, 0.0)
            if (now - last) < interval:
                return
            self._last_persist_ts[job_id] = now
        else:
            self._last_persist_ts[job_id] = time.time()
        storage.save_job(job)

    @staticmethod
    def _model_signature(job: Dict[str, Any]) -> str:
        """
        İşin ComfyUI'de yükleyeceği ağırlık kombinasyonunu tanımlayan imza.
        Model veya LoRA seti değiştiğinde imza değişir.
        """
        loras = job.get("loras") or []
        lora_sig = ",".join(
            sorted(
                f"{(l.get('name') if isinstance(l, dict) else str(l))}"
                f"@{(l.get('strength', 1.0) if isinstance(l, dict) else 1.0)}"
                f"/{(l.get('strength_clip') if isinstance(l, dict) else None)}"
                for l in loras
            )
        )
        return f"{job.get('model', 'ltx25')}|{job.get('type', '')}|{lora_sig}"

    async def _free_comfy_vram(self, engine, reason: str):
        """ComfyUI'nin VRAM'deki model kopyalarını boşaltır (OOM önleme)."""
        try:
            ok = await asyncio.to_thread(engine.free_memory, True)
        except Exception as e:
            print(f"[QueueManager] VRAM boşaltma çağrısı başarısız: {e}")
            return
        if ok:
            print(f"[QueueManager] ComfyUI VRAM boşaltıldı ({reason}).")
            settle = float(getattr(settings, "FREE_VRAM_SETTLE_SECONDS", 2.5))
            if settle > 0:
                await asyncio.sleep(settle)

    async def register_websocket(self, websocket: WebSocket):
        """Yeni WebSocket istemcisini kaydeder."""
        await websocket.accept()
        self.ws_clients.add(websocket)
        # Bağlanır bağlanmaz mevcut durum özetini gönder
        await self.broadcast_state()

    def unregister_websocket(self, websocket: WebSocket):
        """Kapanan WebSocket istemcisini siler."""
        self.ws_clients.discard(websocket)

    async def broadcast_state(self, specific_job: Optional[Dict[str, Any]] = None):
        """Tüm bağlı UI istemcilerine güncel kuyruk ve iş durumunu iletir."""
        payload = {
            "type": "state_update",
            "active_job_id": self.active_job_id,
            "queue_length": len(self.queue),
            "queue_ids": self.queue,
            "updated_job": specific_job
        }
        dead_clients = set()
        for client in self.ws_clients:
            try:
                await client.send_json(payload)
            except Exception:
                dead_clients.add(client)
        for dead in dead_clients:
            self.ws_clients.discard(dead)

    def create_job(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Yeni bir video üretim işi oluşturur ve kuyruğa ekler."""
        job_id = f"vid_{datetime.datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"
        model = params.get("model", "ltx25")
        is_i2v = params.get("mode") == "image_to_video" or bool(params.get("asset_id")) or bool(params.get("image_filename"))

        ref_images = params.get("ref_images") or []
        ref_videos = params.get("ref_videos") or []
        ref_audios = params.get("ref_audios") or []

        job = {
            "id": job_id,
            "model": model,
            "type": "reference_to_video" if model == "minimax_h3" else ("image_to_video" if is_i2v else "text_to_video"),
            "status": JobStatus.QUEUED,
            "progress": 0,
            "current_stage": "Kuyrukta Bekliyor",
            "prompt": params.get("prompt") or "",
            "negative_prompt": params.get("negative_prompt") or "",
            "camera": params.get("camera", "static"),
            "motion_strength": params.get("motion_strength", "medium"),
            "image_fidelity": float(params.get("image_fidelity", settings.DEFAULT_IMAGE_FIDELITY)),
            "aspect_ratio": params.get("aspect_ratio", "16:9"),
            "duration": int(params.get("duration", settings.MINIMAX_DEFAULT_DURATION if model == "minimax_h3" else 5)),
            "quality": params.get("quality", "standard"),
            "fps": int(params.get("fps", 24)),
            "seed": int(params.get("seed", -1)),
            "enhance_prompt": bool(params.get("enhance_prompt", False)),
            "audio": bool(params.get("audio", True)),
            "asset_id": params.get("asset_id"),
            "image_filename": params.get("image_filename"),
            "ref_images": ref_images,
            "ref_videos": ref_videos,
            "ref_audios": ref_audios,
            "ref_image_size": params.get("ref_image_size", "match"),
            "loras": params.get("loras") or [],
            "created_at": datetime.datetime.now().isoformat(),
            "updated_at": datetime.datetime.now().isoformat(),
            "output_video": None,
            "thumbnail": None,
            "error": None
        }

        self.jobs[job_id] = job
        self.queue.append(job_id)
        self._persist(job)

        # Arka plan işleyicisini tetikle
        self._wakeup.set()
        self.ensure_worker_running()
        return job


    def ensure_worker_running(self):
        """Worker döngüsünün aktif olduğundan emin olur."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # Çalışan event loop yok (ör. senkron test/CLI bağlamı); iş kuyrukta bekler.
            return
        if not self.worker_task or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker_loop())
        else:
            # Döngü kapanma aşamasındaysa uyandır
            self._wakeup.set()

    def reset_loaded_signature(self):
        """VRAM harici olarak boşaltıldığında yüklü model imzasını sıfırlar."""
        self._loaded_signature = None

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.jobs.get(job_id)

    def list_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        job_list = list(self.jobs.values())
        job_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return job_list[:limit]

    def list_gallery(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Tamamlanmis videolari tamamlanma zamanina gore (yeniden eskiye) doner.

        Once suzulur, sonra siralanip kirpilir: aksi halde daha yeni basarisiz/iptal
        isler pencereyi doldurup tamamlanmis videolari gizler. Siralama created_at
        yerine completed_at ile yapilir; boylece "Yeniden Dene" ile sonradan biten
        eski bir is de galerinin en ustunde gorunur.
        """
        completed = [j for j in self.jobs.values() if j.get("status") == JobStatus.COMPLETED]
        completed.sort(
            key=lambda j: j.get("completed_at") or j.get("updated_at") or j.get("created_at") or "",
            reverse=True
        )
        return completed[:limit]

    def cancel_job(self, job_id: str) -> bool:
        """
        Kuyruktaki veya çalışmakta olan işi iptal eder.
        Çalışan iş için ComfyUI'ye /interrupt gönderilir; aksi halde iş
        "iptal edildi" görünüp arka planda GPU'yu meşgul etmeye devam ederdi.
        """
        if job_id in self.queue:
            self.queue.remove(job_id)
        if job_id not in self.jobs:
            return False

        self._cancel_requested.add(job_id)
        job = self.jobs[job_id]

        if self.active_job_id == job_id:
            # Çalışan işi ComfyUI tarafında da durdur
            engine = get_engine(job.get("model", "ltx25"))
            prompt_id = self.active_prompt_id
            try:
                if prompt_id:
                    engine.delete_from_queue(prompt_id)
                engine.interrupt()
            except Exception as e:
                print(f"[QueueManager] ComfyUI interrupt uyarısı: {e}")

        job["status"] = JobStatus.CANCELLED
        job["current_stage"] = "İptal Edildi"
        job["updated_at"] = datetime.datetime.now().isoformat()
        self._persist(job)
        self._schedule_broadcast(job)
        return True

    def _schedule_broadcast(self, job: Optional[Dict[str, Any]] = None):
        """Çalışan bir event loop varsa yayın görevini planlar (test/senkron çağrılarda güvenli)."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        asyncio.create_task(self.broadcast_state(job))

    def retry_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Başarısız olmuş veya iptal edilmiş işi yeniden kuyruğa ekler."""
        job = self.jobs.get(job_id)
        if not job:
            return None
        job["status"] = JobStatus.QUEUED
        job["progress"] = 0
        job["error"] = None
        job["current_stage"] = "Yeniden Sıraya Alındı"
        job["updated_at"] = datetime.datetime.now().isoformat()
        if job_id not in self.queue:
            self.queue.append(job_id)
        self._cancel_requested.discard(job_id)
        self._persist(job)
        self.ensure_worker_running()
        self._schedule_broadcast(job)
        return job

    def reorder_queue(self, job_id: str, direction: str) -> bool:
        """Kuyrukta beklemedeki işi yukarı veya aşağı taşır."""
        if job_id not in self.queue:
            return False
        idx = self.queue.index(job_id)
        if direction == "up" and idx > 0:
            self.queue[idx], self.queue[idx - 1] = self.queue[idx - 1], self.queue[idx]
            self._schedule_broadcast()
            return True
        elif direction == "down" and idx < len(self.queue) - 1:
            self.queue[idx], self.queue[idx + 1] = self.queue[idx + 1], self.queue[idx]
            self._schedule_broadcast()
            return True
        return False

    def delete_job(self, job_id: str) -> bool:
        """İşi sistemden ve bellekten kaldırır."""
        if job_id in self.queue:
            self.queue.remove(job_id)
        if job_id in self.jobs:
            del self.jobs[job_id]
            self._cancel_requested.discard(job_id)
            self._last_persist_ts.pop(job_id, None)
            self._schedule_broadcast()
            return True
        return False

    async def _worker_loop(self):
        """
        Sırayla işleri yürüten tekil GPU yürütme döngüsü.

        Kuyruk boşaldığında hemen kapanmak yerine kısa bir süre bekler: aksi halde
        döngünün `while self.queue` kontrolü ile görevin gerçekten bitmesi arasında
        eklenen bir iş, `ensure_worker_running` "görev hâlâ çalışıyor" gördüğü için
        hiç başlatılmadan kuyrukta asılı kalıyordu.
        """
        self.is_running = True
        idle_grace_seconds = 5.0
        try:
            while True:
                if not self.queue:
                    self._wakeup.clear()
                    try:
                        await asyncio.wait_for(self._wakeup.wait(), timeout=idle_grace_seconds)
                    except asyncio.TimeoutError:
                        if not self.queue:
                            break
                    continue

                job_id = self.queue.pop(0)
                job = self.jobs.get(job_id)
                if not job or job["status"] == JobStatus.CANCELLED or job_id in self._cancel_requested:
                    self._cancel_requested.discard(job_id)
                    continue

                self.active_job_id = job_id
                try:
                    await self._execute_job(job)
                finally:
                    self.active_job_id = None
                    self.active_prompt_id = None
                await self.broadcast_state()

        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[QueueManager] Worker loop hatası: {e}")
        finally:
            self.is_running = False
            self.active_job_id = None
            self.active_prompt_id = None


    async def _comfy_ws_listener(
        self,
        client_id: str,
        prompt_id: str,
        workflow: Dict[str, Any],
        job: Dict[str, Any],
        shared_state: Dict[str, Any]
    ):
        """ComfyUI WebSocket'ini dinleyerek anlık adım, düğüm ve hata bilgilerini yakalar."""
        ws_url = f"{settings.COMFYUI_URL.replace('http://', 'ws://').replace('https://', 'wss://')}/ws?clientId={client_id}"
        try:
            async with websockets.connect(ws_url, ping_interval=10, ping_timeout=10) as ws:
                shared_state["ws_connected"] = True
                while not shared_state.get("done", False):
                    try:
                        msg_raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        break

                    if not isinstance(msg_raw, str):
                        continue

                    try:
                        payload = json.loads(msg_raw)
                    except Exception:
                        continue

                    msg_type = payload.get("type")
                    data = payload.get("data", {})

                    # 1. Hata bildirimi (ComfyUI Execution Error - Anında yakalama)
                    if msg_type == "execution_error":
                        if data.get("prompt_id") == prompt_id:
                            node_type = data.get("node_type", "ComfyNode")
                            exc_msg = data.get("exception_message") or "Bilinmeyen hata"
                            shared_state["error"] = f"ComfyUI [{node_type}]: {exc_msg}"
                            shared_state["done"] = True
                            break

                    # 2. Çalışan Düğüm Bildirimi (Executing)
                    elif msg_type == "executing":
                        if data.get("prompt_id") == prompt_id:
                            node_id = data.get("node")
                            if node_id is None:
                                shared_state["nodes_finished"] = True
                            else:
                                node_conf = workflow.get(str(node_id), {})
                                cls_type = node_conf.get("class_type", "İşlem")
                                stage_label, base_pct = NODE_STAGE_INFO.get(cls_type, (f"{cls_type} Çalıştırılıyor...", job.get("progress", 20)))
                                shared_state["last_node"] = cls_type
                                shared_state["last_activity_time"] = time.time()

                                if base_pct > job.get("progress", 0) and cls_type not in SAMPLER_NODE_TYPES:
                                    job["progress"] = base_pct
                                job["current_stage"] = stage_label
                                self._persist(job, force=False)
                                await self.broadcast_state(job)

                    # 3. Örnekleme Adım Bildirimi (Sampling Steps)
                    elif msg_type == "progress":
                        # Bazı ComfyUI sürümleri progress mesajında prompt_id göndermez;
                        # bu durumda tek GPU kuyruğunda mesaj bu işe aittir.
                        if data.get("prompt_id") in (prompt_id, None):
                            val = data.get("value", 0)
                            max_val = data.get("max", 1)
                            if max_val > 0:
                                step_pct = 50 + int((val / max_val) * 36)  # %50 -> %86 gerçek adım
                                job["progress"] = min(86, step_pct)
                                job["current_stage"] = f"Video Üretiliyor (Adım {val}/{max_val})..."
                                shared_state["last_activity_time"] = time.time()
                                self._persist(job, force=False)
                                await self.broadcast_state(job)

        except Exception as e:
            # WebSocket kurulamasa dahi ana döngüde HTTP kuyruk denetimi devam eder
            print(f"[QueueManager] ComfyUI WebSocket dinleme uyarısı (HTTP denetimine geçildi): {e}")

    async def _execute_job(self, job: Dict[str, Any]):
        """Belirtilen işi ComfyUI üzerinden adım adım yürütür."""
        job_id = job["id"]
        model_name = job.get("model", "ltx25")
        engine = get_engine(model_name)

        try:
            # 1. Hazırlık Aşaması
            job["status"] = JobStatus.PREPARING
            job["current_stage"] = f"{'MiniMax H3 Ref2VA' if model_name == 'minimax_h3' else 'LTX-2.5 Distilled'} Hazırlanıyor..."
            job["progress"] = 5
            job["updated_at"] = datetime.datetime.now().isoformat()
            self._persist(job)
            await self.broadcast_state(job)

            comfy_input = os.path.join(settings.COMFYUI_DIR, "input")
            os.makedirs(comfy_input, exist_ok=True)

            is_i2v = job.get("type") in ["image_to_video", "reference_to_video"]

            def _sync_reference(item: str) -> Optional[str]:
                """Referans dosyayı ComfyUI input dizinine kopyalar; bulunamazsa None döner."""
                path = storage.get_asset_path(item)
                if not path and os.path.isfile(item):
                    path = item
                if not path or not os.path.exists(path):
                    return None
                fn = os.path.basename(path)
                safe_copy(path, os.path.join(comfy_input, fn))
                return fn

            missing_refs: List[str] = []

            # LTX-2.5 tekli referans görsel senkronizasyonu
            if model_name == "ltx25" and is_i2v:
                asset_id = job.get("asset_id")
                if asset_id:
                    filename = _sync_reference(asset_id)
                    if filename:
                        job["image_filename"] = filename
                    else:
                        missing_refs.append(str(asset_id))
                elif not job.get("image_filename"):
                    raise ValueError(
                        "Görselden video (I2V) modu için bir referans görsel yüklemeniz gerekir."
                    )

            # MiniMax H3 çoklu referans senkronizasyonu (Görseller, Videolar, Sesler)
            elif model_name == "minimax_h3":
                for key in ("ref_images", "ref_videos", "ref_audios"):
                    resolved = []
                    for item in job.get(key, []):
                        fn = _sync_reference(item)
                        if fn:
                            resolved.append(fn)
                        else:
                            missing_refs.append(str(item))
                    job[key] = resolved

            if missing_refs:
                # Eksik referansları ComfyUI'ye göndermek "LoadImage: file not found"
                # gibi anlaşılmaz bir hataya dönüşüyordu.
                raise FileNotFoundError(
                    "Referans dosyalar bulunamadı: " + ", ".join(missing_refs) +
                    ". Dosyalar silinmiş olabilir; lütfen yeniden yükleyin."
                )

            # 1b. LoRA Hazırlığı
            # ComfyUI yalnızca kendi models/loras arama yolundaki dosyaları tanır.
            # Drive'daki LoRA'ları oraya bağla ve eksik olanı önceden, anlaşılır
            # bir hata ile bildir (aksi halde ComfyUI "value not in list" der).
            requested_loras = [
                (l.get("name") if isinstance(l, dict) else str(l))
                for l in (job.get("loras") or [])
            ]
            requested_loras = [n for n in requested_loras if n]
            if requested_loras:
                job["current_stage"] = "LoRA Ağırlıkları Hazırlanıyor..."
                await self.broadcast_state(job)
                sync_result = await asyncio.to_thread(lora_manager.ensure_loras_available, requested_loras)
                if not sync_result["ok"]:
                    available = [l["name"] for l in lora_manager.list_available_loras()][:8]
                    raise FileNotFoundError(
                        f"LoRA dosyaları bulunamadı: {', '.join(sync_result['missing'])}. "
                        f"Kütüphanedeki modeller: {', '.join(available) if available else 'yok'}"
                    )
                # ComfyUI'nin gördüğü gerçek dosya adlarını kullan
                for lora in (job.get("loras") or []):
                    if isinstance(lora, dict) and lora.get("name") in sync_result["resolved"]:
                        lora["name"] = sync_result["resolved"][lora["name"]]

            # 1c. VRAM Yönetimi (CUDA OOM Önleme)
            # ComfyUI, model veya LoRA kombinasyonu değiştiğinde eski ağırlıkları
            # VRAM'de tutup yenisini de yüklemeye çalışır. Tek GPU'da bu doğrudan
            # "CUDA out of memory" demektir. Kombinasyon değiştiyse önce boşalt.
            signature = self._model_signature(job)
            needs_free = False
            free_reason = ""
            if self._loaded_signature is not None and self._loaded_signature != signature:
                if getattr(settings, "FREE_VRAM_ON_MODEL_SWITCH", True):
                    needs_free = True
                    free_reason = "model/LoRA kombinasyonu değişti"
            elif requested_loras and self._loaded_signature is None:
                if getattr(settings, "FREE_VRAM_BEFORE_LORA_JOB", True):
                    needs_free = True
                    free_reason = "LoRA'lı ilk iş"

            if needs_free:
                job["current_stage"] = "GPU Belleği Boşaltılıyor (VRAM Temizliği)..."
                job["progress"] = 10
                await self.broadcast_state(job)
                await self._free_comfy_vram(engine, free_reason)

            self._loaded_signature = signature

            # 2. Workflow JSON Oluştur
            built = engine.build_workflow(job, is_i2v=is_i2v)
            workflow = built["prompt"]
            job["final_prompt"] = built["metadata"]["final_prompt"]
            job["seed"] = built["metadata"]["seed"]
            job["dimensions"] = built["metadata"].get("dimensions")
            job["steps"] = built["metadata"].get("steps")
            job["cfg"] = built["metadata"].get("cfg")
            job["sampler"] = built["metadata"].get("sampler")
            job["engine_loaders"] = built["metadata"].get("loaders")
            # Motorun gercekte uyguladigi LoRA listesi (cozumlenmis dosya adlari)
            if built["metadata"].get("loras") is not None:
                job["applied_loras"] = built["metadata"]["loras"]

            # 2b. Workflow'u ComfyUI'nin gerçek düğüm şemasına göre doğrula.
            # Eksik custom node'ları ve uyumsuz girdileri, ComfyUI'nin şifreli
            # HTTP 400 hatasına dönüşmeden önce yakalar.
            workflow, wf_warnings = await asyncio.to_thread(engine.validate_workflow, workflow)
            for w in wf_warnings:
                print(f"[QueueManager] Workflow uyarısı: {w}")

            # 3. Üretim Aşaması (Generating)
            job["status"] = JobStatus.GENERATING
            job["current_stage"] = f"{'MiniMax H3 Omni' if model_name == 'minimax_h3' else 'LTX-2.5 Distilled'} Çıkarımı Başlatılıyor..."
            job["progress"] = 15
            self._persist(job)
            await self.broadcast_state(job)

            # ComfyUI'ye gönder
            if job_id in self._cancel_requested:
                raise JobCancelled()

            client_id = str(uuid.uuid4())
            prompt_id = await asyncio.to_thread(engine.queue_prompt, workflow, client_id)
            self.active_prompt_id = prompt_id

            if not prompt_id:
                if settings.IS_COLAB or not getattr(settings, "DEV_MOCK_MODE", False):
                    raise RuntimeError("ComfyUI sunucusuna erişilemedi veya prompt kuyruğa alınamadı.")
                # Yalnızca yerel test/mock modunda simülasyon yap
                print(f"[QueueManager] ComfyUI henüz yanıt vermiyor veya offline. Simüle ediliyor...")
                for p in range(20, 95, 15):
                    await asyncio.sleep(1.0)
                    job["progress"] = p
                    job["current_stage"] = f"Video Frame'leri Üretiliyor (%{p})..."
                    await self.broadcast_state(job)

                # Mock boş mp4 üretimi (test amaçlı)
                test_dir = os.path.join(settings.LOCAL_JOBS_DIR, job_id)
                os.makedirs(test_dir, exist_ok=True)
                mock_mp4 = os.path.join(test_dir, "output.mp4")
                if not os.path.exists(mock_mp4):
                    with open(mock_mp4, "wb") as f:
                        f.write(b"MOCK_MP4_CONTENT")
                out_info = storage.save_job_output(job_id, mock_mp4)
            else:
                # Gerçek ComfyUI çalıştırma: WebSocket + HTTP kuyruk ve liveness denetimi
                shared_state = {
                    "done": False,
                    "nodes_finished": False,
                    "error": None,
                    "ws_connected": False,
                    "last_activity_time": time.time(),
                    "last_node": None
                }
                ws_task = asyncio.create_task(
                    self._comfy_ws_listener(client_id, prompt_id, workflow, job, shared_state)
                )

                max_wait_seconds = getattr(settings, "COMFYUI_MAX_WAIT_SECONDS", 1800)
                stall_timeout = 900  # 15 dakika hareketsizlik kontrolü
                start_time = time.time()
                completed = False
                history = None

                try:
                    while (time.time() - start_time) < max_wait_seconds:
                        await asyncio.sleep(2.0)

                        # 0. Kullanıcı iptali
                        if job_id in self._cancel_requested:
                            raise JobCancelled()

                        # 1. WebSocket üzerinden anında yakalanan hata kontrolü
                        if shared_state.get("error"):
                            raise RuntimeError(shared_state["error"])

                        # 2. History kontrolü
                        history = await asyncio.to_thread(engine.get_history, prompt_id)
                        if history and prompt_id in history:
                            prompt_hist = history[prompt_id]
                            status = prompt_hist.get("status", {})
                            if status.get("status_str") == "error":
                                messages = status.get("messages", [])
                                err_msg = "ComfyUI işlemi hata ile sonuçlandı."
                                for msg in messages:
                                    if isinstance(msg, list) and len(msg) > 1 and isinstance(msg[1], dict):
                                        node_err = msg[1].get("exception_message") or msg[1].get("error")
                                        node_type = msg[1].get("node_type", "ComfyNode")
                                        if node_err:
                                            err_msg = f"ComfyUI [{node_type}]: {node_err}"
                                            break
                                raise RuntimeError(err_msg)

                            completed = True
                            break

                        # 3. ComfyUI /queue durum denetimi
                        queue_info = await asyncio.to_thread(engine.get_queue)
                        if queue_info:
                            is_running, is_pending = is_prompt_in_queue(queue_info, prompt_id)
                            if is_running or is_pending:
                                shared_state["last_activity_time"] = time.time()
                                # KSampler başlamadan önce model Google Drive'dan okunurken
                                # ilerleme çubuğunu düzenli ve gerçekçi ilerlet (%15 - %45)
                                if job.get("progress", 0) < 45:
                                    elapsed_loading = time.time() - start_time
                                    job["progress"] = min(45, 15 + int(elapsed_loading / 8))
                                    if not shared_state.get("last_node"):
                                        job["current_stage"] = "Model Ağırlıkları Yükleniyor (Lütfen Bekleyin)..."
                                    self._persist(job, force=False)
                                    await self.broadcast_state(job)
                            else:
                                # Prompt kuyrukta görünmüyor, history'ye geçmiş olabilir mi?
                                await asyncio.sleep(1.0)
                                history = await asyncio.to_thread(engine.get_history, prompt_id)
                                if history and prompt_id in history:
                                    completed = True
                                    break
                                else:
                                    # Ne kuyrukta ne history'de! ComfyUI işlemi düşürdü veya çöktü
                                    log_tail = read_comfyui_log_tail(30)
                                    rel_err = extract_relevant_error(log_tail)
                                    err_msg = f"ComfyUI işlemi kuyruktan düştü veya sonlandı. {rel_err or log_tail[-300:]}"
                                    raise RuntimeError(err_msg)

                        # 4. Sunucu Sağlık / Çökme Kontrolü (15 sn sonra başlar)
                        if (time.time() - start_time) > 15:
                            stats = await asyncio.to_thread(engine.get_system_stats)
                            if stats is None:
                                log_tail = read_comfyui_log_tail(30)
                                rel_err = extract_relevant_error(log_tail)
                                raise RuntimeError(f"ComfyUI sunucusu kapandı veya çöktü (Muhtemelen OOM bellek yetersizliği). {rel_err or ''}")

                        # 5. Stall (Hareketsizlik) Kontrolü
                        if (time.time() - shared_state["last_activity_time"]) > stall_timeout:
                            log_tail = read_comfyui_log_tail(30)
                            rel_err = extract_relevant_error(log_tail)
                            raise TimeoutError(f"ComfyUI 15 dakikadır yanıt vermiyor (Stall). Son Durum: {rel_err or log_tail[-250:]}")

                finally:
                    shared_state["done"] = True
                    ws_task.cancel()

                if not completed:
                    log_tail = read_comfyui_log_tail(30)
                    rel_err = extract_relevant_error(log_tail)
                    raise TimeoutError(f"ComfyUI maksimum işlem süresini ({max_wait_seconds // 60} dakika) aştı. Son Log: {rel_err or log_tail[-250:]}")

                # Çıktı dosyasını ComfyUI history ve output klasöründen bul
                comfy_output_dir = os.path.join(settings.COMFYUI_DIR, "output")
                found_video = None

                prompt_hist = (history or {}).get(prompt_id, {})
                outputs = prompt_hist.get("outputs", {})
                for node_id, node_out in outputs.items():
                    media_list = node_out.get("gifs", []) or node_out.get("images", []) or node_out.get("videos", [])
                    for item in media_list:
                        fn = item.get("filename", "")
                        if fn.endswith(".mp4") or fn.endswith(".webm"):
                            subfolder = item.get("subfolder", "")
                            cand = os.path.join(comfy_output_dir, subfolder, fn)
                            if os.path.exists(cand):
                                found_video = cand
                                break
                    if found_video:
                        break

                # Eğer history outputs'ta bulunamadıysa SADECE bu job_id'ye ait dosyayı ara
                if not found_video and os.path.exists(comfy_output_dir):
                    candidate_videos = []
                    for root, _, files in os.walk(comfy_output_dir):
                        for f in files:
                            if any(f.endswith(ext) for ext in [".mp4", ".webm", ".mkv", ".mov"]) and job_id in f:
                                candidate_videos.append(os.path.join(root, f))
                    if candidate_videos:
                        candidate_videos.sort(key=os.path.getmtime, reverse=True)
                        found_video = candidate_videos[0]

                if not found_video:
                    raise FileNotFoundError(f"ComfyUI çıktısı video dosyası bulunamadı (Job ID: {job_id}).")

                # 4. Kaydetme & Senkronizasyon (Saving)
                job["status"] = JobStatus.SAVING
                job["current_stage"] = "Video Google Drive'a Kaydediliyor..."
                job["progress"] = 95
                await self.broadcast_state(job)

                out_info = storage.save_job_output(job_id, found_video)

            # 5. Tamamlandı (Completed)
            job["status"] = JobStatus.COMPLETED
            job["current_stage"] = "Tamamlandı"
            job["progress"] = 100
            job["output_video"] = f"/api/videos/{job_id}/stream"
            job["local_video_path"] = out_info["local_video_path"]
            job["drive_video_path"] = out_info.get("drive_video_path")
            job["completed_at"] = datetime.datetime.now().isoformat()
            job["updated_at"] = datetime.datetime.now().isoformat()

            self._persist(job)
            await self.broadcast_state(job)

        except JobCancelled:
            print(f"[QueueManager] Job {job_id} kullanıcı tarafından iptal edildi.")
            job["status"] = JobStatus.CANCELLED
            job["current_stage"] = "İptal Edildi"
            job["updated_at"] = datetime.datetime.now().isoformat()
            self._persist(job)
            await self.broadcast_state(job)
            # İptal sonrası ComfyUI'de yarım kalmış ağırlıklar kalabilir
            self._loaded_signature = None
            await self._free_comfy_vram(engine, "iş iptal edildi")

        except Exception as e:
            print(f"[QueueManager] Job {job_id} başarısız oldu: {e}")
            err_str = str(e)
            if "ComfyUI" in err_str and len(err_str) < 60:
                log_tail = read_comfyui_log_tail(15)
                rel_err = extract_relevant_error(log_tail)
                if rel_err and rel_err not in err_str:
                    err_str += f" | {rel_err}"

            # Bellek yetersizliğinde kullanıcıya ne yapacağını söyle ve VRAM'i boşalt
            if _is_oom_error(err_str):
                self._loaded_signature = None
                await self._free_comfy_vram(engine, "OOM sonrası temizlik")
                err_str += (
                    " | ÇÖZÜM ÖNERİSİ: Süreyi veya çözünürlüğü düşürün (Draft kalitesi), "
                    "aynı anda kullanılan LoRA sayısını azaltın ve ComfyUI'yi --highvram olmadan başlatın."
                )

            job["status"] = JobStatus.FAILED
            job["current_stage"] = f"Hata: {err_str[:180]}"
            job["error"] = err_str
            job["updated_at"] = datetime.datetime.now().isoformat()
            self._persist(job)
            await self.broadcast_state(job)

        finally:
            self._cancel_requested.discard(job_id)
            self.active_prompt_id = None


# Singleton instance
queue_manager = QueueManager()
