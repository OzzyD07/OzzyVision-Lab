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
from app.backend import resources
from app.backend import video_compat
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


def _is_oom_error(message: str) -> bool:
    """Hata metni GPU veya sistem belleği yetersizliğinden mi kaynaklanıyor?"""
    return resources.classify_failure(message) in (resources.GPU_OOM, resources.RAM_OOM)


class ComfyUnavailable(RuntimeError):
    """ComfyUI süreci yanıt vermiyor (kapandı veya işletim sistemi tarafından öldürüldü)."""
    pass


def queue_presence_counts_as_activity(is_running: bool, is_pending: bool, ws_connected: bool) -> bool:
    """
    ComfyUI kuyruğunda görünmek donma sayacını sıfırlamalı mı?

    - Başka işlerin arkasında beklemek (pending) donma değildir.
    - Çalışırken asıl canlılık işareti WebSocket düğüm/adım bildirimleridir. Kuyrukta
      "çalışıyor" görünmek, gerçekten takılmış bir düğümü de gizlerdi.
    - WebSocket bağlanamadıysa bildirim gelemez; o durumda kuyruk varlığına güvenilir.
    """
    return is_pending or (is_running and not ws_connected)


class StepTimer:
    """ComfyUI adım bildirimlerinden saniye/adım ve kalan süre hesaplar."""

    def __init__(self):
        self._key = None
        self._first = None  # (adım, zaman)

    def update(self, node: Any, value: int, maximum: int, now: float) -> Tuple[Optional[float], Optional[float]]:
        key = (node, maximum)
        if key != self._key or self._first is None or value < self._first[0]:
            self._key = key
            self._first = (value, now)
            return None, None
        done = value - self._first[0]
        if done <= 0:
            return None, None
        per_step = (now - self._first[1]) / done
        return per_step, per_step * max(0, maximum - value)


def _format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} sn"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} dk {sec} sn" if sec and minutes < 10 else f"{minutes} dk"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} sa {minutes} dk"


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

        # ComfyUI'den alınan son GPU/RAM ölçümü (arayüze canlı yayınlanır)
        self._last_sample: Optional[Dict[str, Any]] = None
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

    def _record_sample(self, job: Dict[str, Any], sample: Dict[str, Any], node: Optional[str]):
        """Son ölçümü saklar ve işin tepe VRAM/RAM kullanımını günceller."""
        self._last_sample = sample
        peak = job.setdefault("resource_peak", {})
        if sample.get("vram_used_gb") is not None and sample["vram_used_gb"] >= peak.get("vram_used_gb", -1):
            peak["vram_used_gb"] = sample["vram_used_gb"]
            peak["vram_total_gb"] = sample.get("vram_total_gb")
            peak["vram_node"] = node
        if sample.get("ram_used_gb") is not None and sample["ram_used_gb"] >= peak.get("ram_used_gb", -1):
            peak["ram_used_gb"] = sample["ram_used_gb"]
            peak["ram_total_gb"] = sample.get("ram_total_gb")
            peak["ram_node"] = node

    @staticmethod
    def _format_peak(peak: Optional[Dict[str, Any]]) -> str:
        if not peak:
            return ""
        parts = []
        if peak.get("vram_total_gb"):
            node = f" ({peak['vram_node']})" if peak.get("vram_node") else ""
            parts.append(f"VRAM {peak['vram_used_gb']}/{peak['vram_total_gb']} GB{node}")
        if peak.get("ram_total_gb"):
            node = f" ({peak['ram_node']})" if peak.get("ram_node") else ""
            parts.append(f"RAM {peak['ram_used_gb']}/{peak['ram_total_gb']} GB{node}")
        return "Tepe kullanım: " + " · ".join(parts) if parts else ""

    async def _abandon_prompt(self, engine, prompt_id: Optional[str]):
        """
        Backend'in vazgeçtiği promptu ComfyUI'de de durdurur.

        Aksi halde ComfyUI "başarısız" işi arka planda bitirmeye devam eder ve
        sıradaki iş onun arkasında bekler. Yalnızca BU prompt çalışıyorsa interrupt
        gönderilir; başka bir işin çalışmasını kesmemek için bekleyen prompt kuyruktan silinir.
        """
        if not prompt_id:
            return
        try:
            queue_info = await asyncio.to_thread(engine.get_queue)
            if not queue_info:
                return
            is_running, is_pending = is_prompt_in_queue(queue_info, prompt_id)
            if is_running:
                await asyncio.to_thread(engine.interrupt)
                print(f"[QueueManager] Vazgeçilen prompt ComfyUI'de kesildi: {prompt_id}")
            elif is_pending:
                await asyncio.to_thread(engine.delete_from_queue, prompt_id)
                print(f"[QueueManager] Vazgeçilen prompt ComfyUI kuyruğundan silindi: {prompt_id}")
        except Exception as e:
            print(f"[QueueManager] Prompt durdurma uyarısı: {e}")

    @staticmethod
    def _job_context(job: Dict[str, Any]) -> str:
        """Hata mesajı için iş özeti: motor, çözünürlük, kare, adım ve ölçülen hız."""
        dims = job.get("dimensions") or {}
        parts = [{"ltx25": "LTX-2.5", "minimax_h3": "MiniMax H3"}.get(job.get("model"), job.get("model") or "?")]
        if dims.get("width"):
            parts.append(f"{dims['width']}×{dims['height']}")
        if dims.get("frames"):
            parts.append(f"{dims['frames']} kare")
        if job.get("steps"):
            parts.append(f"{job['steps']} adım")
        if job.get("step_seconds"):
            parts.append(f"{_format_duration(job['step_seconds'])}/adım")
        return "İş: " + " · ".join(parts)

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
            "updated_job": specific_job,
            "resources": self._last_sample
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
                                now = time.time()
                                step_pct = 50 + int((val / max_val) * 36)  # %50 -> %86 gerçek adım
                                job["progress"] = min(86, step_pct)
                                per_step, remaining = shared_state["step_timer"].update(
                                    data.get("node"), val, max_val, now
                                )
                                stage = f"Video Üretiliyor (Adım {val}/{max_val}"
                                if per_step:
                                    job["step_seconds"] = round(per_step, 1)
                                    stage += f" · {_format_duration(per_step)}/adım · ~{_format_duration(remaining)} kaldı"
                                job["current_stage"] = stage + ")"
                                shared_state["last_activity_time"] = now
                                self._persist(job, force=False)
                                await self.broadcast_state(job)

        except Exception as e:
            # WebSocket kurulamasa dahi ana döngüde HTTP kuyruk denetimi devam eder
            print(f"[QueueManager] ComfyUI WebSocket dinleme uyarısı (HTTP denetimine geçildi): {e}")
        finally:
            # Bağlantı koptuysa bildirim gelmez; donma tespiti kuyruk varlığına geri dönmeli
            shared_state["ws_connected"] = False

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

            def _resolve_reference(item: str) -> Optional[str]:
                path = storage.get_asset_path(item)
                if not path and os.path.isfile(item):
                    path = item
                if not path or not os.path.exists(path):
                    return None
                return path

            def _sync_reference(item: str) -> Optional[str]:
                """Referans dosyayı ComfyUI input dizinine kopyalar; bulunamazsa None döner."""
                path = _resolve_reference(item)
                if not path:
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
                for key in ("ref_images", "ref_audios"):
                    resolved = []
                    for item in job.get(key, []):
                        fn = _sync_reference(item)
                        if fn:
                            resolved.append(fn)
                        else:
                            missing_refs.append(str(item))
                    job[key] = resolved

                # Referans videolar: düğüm 24 fps kare bekler. Hazırlanan kopya ComfyUI'ye verilir;
                # iş kaydında orijinal dosya adı kalır (galeri önizlemesi ve yeniden deneme için).
                resolved_videos, prepared_videos = [], []
                for item in job.get("ref_videos", []):
                    path = _resolve_reference(item)
                    if not path:
                        missing_refs.append(str(item))
                        continue
                    stem = os.path.splitext(os.path.basename(path))[0]
                    dest = os.path.join(comfy_input, f"{stem}_ref24.mp4")
                    job["current_stage"] = "Referans videolar 24 fps'e hazırlanıyor..."
                    await self.broadcast_state(job)
                    try:
                        meta = await asyncio.to_thread(video_compat.prepare_reference_video, path, dest)
                    except ValueError as ve:
                        raise ValueError(f"Referans video '{os.path.basename(path)}': {ve}")
                    resolved_videos.append(os.path.basename(path))
                    prepared_videos.append(meta)
                job["ref_videos"] = resolved_videos
                job["ref_videos_prepared"] = prepared_videos

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
                    "last_node": None,
                    "step_timer": StepTimer()
                }
                ws_task = asyncio.create_task(
                    self._comfy_ws_listener(client_id, prompt_id, workflow, job, shared_state)
                )

                max_wait_seconds = getattr(settings, "COMFYUI_MAX_WAIT_SECONDS", 1800)
                poll_interval = float(getattr(settings, "COMFY_POLL_INTERVAL", 2.0))
                crash_grace = float(getattr(settings, "COMFY_CRASH_GRACE_SECONDS", 15))
                health_failures = 0
                stall_timeout = float(getattr(settings, "COMFY_STALL_SECONDS", 1800))
                start_time = time.time()
                completed = False
                history = None

                try:
                    while (time.time() - start_time) < max_wait_seconds:
                        await asyncio.sleep(poll_interval)

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
                                if queue_presence_counts_as_activity(
                                    is_running, is_pending, shared_state.get("ws_connected", False)
                                ):
                                    shared_state["last_activity_time"] = time.time()

                                if is_pending:
                                    # Başka bir prompt GPU'yu kullanıyor; hiçbir şey yüklenmiyor.
                                    waiting = "ComfyUI kuyruğunda bekliyor (önceki işlem sürüyor)..."
                                    if job.get("current_stage") != waiting:
                                        job["current_stage"] = waiting
                                        self._persist(job, force=False)
                                        await self.broadcast_state(job)
                                elif job.get("progress", 0) < 45:
                                    # Çalışıyor ama henüz düğüm bildirimi yok: modeller yükleniyor
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

                        # 4. Bellek ölçümü ve sunucu sağlık kontrolü
                        stats = await asyncio.to_thread(engine.get_system_stats)
                        if stats is not None:
                            health_failures = 0
                            sample = resources.parse_comfy_stats(stats)
                            if sample:
                                self._record_sample(job, sample, shared_state.get("last_node"))
                        else:
                            # Yoğun model yüklemesinde tek bir zaman aşımı olabilir;
                            # iki ardışık yanıtsızlık ve başlangıç payı sonrası çökmüş say.
                            health_failures += 1
                            if health_failures >= 2 and (time.time() - start_time) > crash_grace:
                                log_tail = read_comfyui_log_tail(30)
                                rel_err = extract_relevant_error(log_tail)
                                raise ComfyUnavailable(rel_err or "ComfyUI yanıt vermiyor.")

                        # 5. Stall (Hareketsizlik) Kontrolü
                        if (time.time() - shared_state["last_activity_time"]) > stall_timeout:
                            log_tail = read_comfyui_log_tail(30)
                            rel_err = extract_relevant_error(log_tail)
                            raise TimeoutError(
                                f"ComfyUI {_format_duration(stall_timeout)} boyunca hiçbir düğüm veya adım bildirimi göndermedi (donma). "
                                f"Son durum: {rel_err or log_tail[-250:]}"
                            )

                finally:
                    shared_state["done"] = True
                    ws_task.cancel()

                if not completed:
                    log_tail = read_comfyui_log_tail(30)
                    rel_err = extract_relevant_error(log_tail)
                    raise TimeoutError(
                        f"İş mutlak süre sınırını ({_format_duration(max_wait_seconds)}) aştı. "
                        f"Son log: {rel_err or log_tail[-250:]}"
                    )

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

                # 4. Tarayıcı uyumluluğu + Kaydetme & Senkronizasyon (Saving)
                job["status"] = JobStatus.SAVING
                job["current_stage"] = "Video tarayıcı için hazırlanıyor..."
                job["progress"] = 93
                await self.broadcast_state(job)

                # ComfyUI'nin orijinal dosyasına dokunmadan iş klasöründeki kopyayı hazırla
                local_mp4 = os.path.join(settings.LOCAL_JOBS_DIR, job_id, "output.mp4")
                safe_copy(found_video, local_mp4)
                job["video_info"] = await video_compat.ensure_playable(local_mp4)

                job["current_stage"] = "Video Google Drive'a Kaydediliyor..."
                job["progress"] = 95
                await self.broadcast_state(job)

                out_info = storage.save_job_output(job_id, local_mp4)

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
            raw_error = str(e)
            comfy_alive = not isinstance(e, ComfyUnavailable)

            if comfy_alive and "ComfyUI" in raw_error and len(raw_error) < 60:
                rel_err = extract_relevant_error(read_comfyui_log_tail(15))
                if rel_err and rel_err not in raw_error:
                    raw_error += f" | {rel_err}"

            if comfy_alive:
                await self._abandon_prompt(engine, self.active_prompt_id)

            kind = resources.classify_failure(raw_error, comfy_alive, self._last_sample)
            peak_text = self._format_peak(job.get("resource_peak"))

            if kind == resources.GPU_OOM:
                wanted, free = resources.parse_allocation(raw_error)
                summary = "GPU belleği (VRAM) yetmedi"
                if wanted:
                    summary += f": {wanted} istendi" + (f", {free} boştu" if free else "")
                advice = "Süreyi veya çözünürlüğü düşürün ya da Taslak kalitesini deneyin."
                self._loaded_signature = None
                await self._free_comfy_vram(engine, "GPU OOM sonrası temizlik")
            elif kind == resources.RAM_OOM:
                summary = "Sistem RAM'i doldu ve ComfyUI süreci kapatıldı (sorun VRAM değil)"
                advice = (
                    "Notebook'ta COMFY_LOW_RAM = True yapıp 6. adımı yeniden çalıştırın. "
                    "Aynı oturumda iki motoru dönüşümlü kullanmak RAM'de iki model ailesini birden tutar."
                )
                self._loaded_signature = None
            elif kind == resources.CRASH:
                summary = "ComfyUI süreci beklenmedik şekilde kapandı"
                advice = "6. adımı çalıştırıp ComfyUI'yi yeniden başlatın; ayrıntı için ComfyUI loguna bakın."
                self._loaded_signature = None
            else:
                summary = raw_error
                advice = ""

            parts = [summary]
            if kind != resources.OTHER and raw_error and raw_error not in summary:
                parts.append(f"Ayrıntı: {raw_error}")
            if job.get("dimensions"):
                parts.append(self._job_context(job))
            if peak_text:
                parts.append(peak_text)
            if advice:
                parts.append(f"Öneri: {advice}")
            err_str = " | ".join(parts)

            job["status"] = JobStatus.FAILED
            job["failure_kind"] = kind
            job["current_stage"] = f"Hata: {summary[:180]}"
            job["error"] = err_str
            job["updated_at"] = datetime.datetime.now().isoformat()
            self._persist(job)
            await self.broadcast_state(job)

        finally:
            self._cancel_requested.discard(job_id)
            self.active_prompt_id = None


# Singleton instance
queue_manager = QueueManager()
