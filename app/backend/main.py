"""
OzzyVision-Lab - FastAPI Main Application
REST API, WebSocket gerçek zamanlı ilerleme ve Claude Remote MCP sunucusu.
"""

import os
import shutil
import urllib.request
import json
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import torch
except ImportError:  # torch yalnızca GPU raporlaması için gerekli
    torch = None

from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.backend.queue_manager import queue_manager, read_comfyui_log_tail
from app.backend.storage import storage, safe_copy, is_safe_id
from app.backend.camera_presets import get_all_presets
from app.backend.prompt_enhancer import enhance_prompt
import app.backend.lora_manager as lora_manager
from app.mcp.server import mcp_router
import config.settings as settings

app = FastAPI(
    title="OzzyVision-Lab API",
    description="LTX-2.5 ve MiniMax H3 video üretim API'si",
    version="1.0.0"
)

# CORS ayarları (React UI ve harici erişim için)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Remote MCP Router'ını dahil et (/mcp)
app.include_router(mcp_router)


# ==========================================
# 1. SİSTEM DURUMU (STATUS)
# ==========================================
@app.get("/api/status")
async def get_system_status():
    """GPU, ComfyUI ve Google Drive bağlantı durumunu döner."""
    # GPU Tespiti
    has_cuda = bool(torch and torch.cuda.is_available())
    gpu_name = "CPU (Simülasyon)"
    gpu_memory_gb = 0
    gpu_used_gb = 0
    if has_cuda:
        try:
            props = torch.cuda.get_device_properties(0)
            gpu_name = props.name
            gpu_memory_gb = round(props.total_memory / (1024**3), 1)
            free_bytes, total_bytes = torch.cuda.mem_get_info()
            gpu_used_gb = round((total_bytes - free_bytes) / (1024**3), 1)
        except Exception:
            has_cuda = False

    # ComfyUI Kontrolü
    comfy_online = False
    try:
        req = urllib.request.Request(f"{settings.COMFYUI_URL}/system_stats", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                comfy_online = True
    except Exception:
        comfy_online = False

    # Drive Kontrolü
    drive_connected = os.path.exists(settings.DRIVE_PROJECT_ROOT) or os.path.exists(settings.GOOGLE_DRIVE_MOUNT_PATH)

    jobs = queue_manager.list_jobs(limit=100)
    completed_count = sum(1 for j in jobs if j.get("status") == "completed")

    return {
        "status": "online",
        "models": [
            {
                "id": "ltx25",
                "name": "LTX-2.5 Distilled 22B",
                "badge": "Hızlı",
                "description": "Hızlı metin/görselden video, dahili ambiyans sesi (8 adım)",
                "max_duration": 8,
                "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "21:9"]
            },
            {
                "id": "minimax_h3",
                "name": "MiniMax H3 Omni Ref2VA",
                "badge": "Çoklu Referans",
                "description": "9 görsel, 3 video, 3 ses referansı; 32 kHz stereo ve dudak senkronu",
                "max_duration": 15,
                "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]
            }
        ],
        "gpu": {
            "available": has_cuda,
            "name": gpu_name,
            "vram_gb": gpu_memory_gb,
            "vram_used_gb": gpu_used_gb,
            "target": "A100 80GB"
        },
        "comfyui": {
            "online": comfy_online,
            "url": settings.COMFYUI_URL
        },
        "storage": {
            "drive_connected": drive_connected,
            "drive_root": settings.DRIVE_PROJECT_ROOT,
            "local_cache": settings.LOCAL_RUNTIME_DIR
        },
        "queue": {
            "active_job_id": queue_manager.active_job_id,
            "queue_length": len(queue_manager.queue),
            "completed_total": completed_count
        }
    }


@app.post("/api/system/free_vram")
async def free_vram():
    """
    ComfyUI'nin VRAM'de tuttuğu tüm model ağırlıklarını boşaltır.
    Model veya LoRA değiştirdikten sonra "CUDA out of memory" alındığında
    ComfyUI'yi yeniden başlatmaya gerek kalmadan belleği temizler.
    """
    from app.backend.engines import get_engine
    engine = get_engine("ltx25")
    ok = engine.free_memory(unload_models=True)
    queue_manager.reset_loaded_signature()
    return {
        "success": ok,
        "message": "GPU belleği boşaltıldı." if ok else "ComfyUI'ye ulaşılamadı; bellek boşaltılamadı."
    }


@app.get("/api/system/comfy_logs")
async def get_comfy_logs(lines: int = 80):
    """ComfyUI son console log çıktılarını döner."""
    tail = read_comfyui_log_tail(lines)
    return {
        "available": bool(tail),
        "lines": [l.rstrip() for l in tail.splitlines()],
        "raw": tail
    }


# ==========================================
# 2. İŞ KUYRUĞU (JOBS) API
# ==========================================
@app.post("/api/jobs")
async def create_generation_job(payload: Dict[str, Any]):
    """Yeni bir video üretim işi başlatır."""
    job = queue_manager.create_job(payload)
    return {"status": "success", "job": job}


@app.get("/api/jobs")
async def list_jobs(limit: int = 50):
    """Mevcut ve geçmiş işleri listeler."""
    return {"jobs": queue_manager.list_jobs(limit=limit)}


@app.get("/api/jobs/{job_id}")
async def get_job_detail(job_id: str):
    """Tekil bir işin detaylarını döner."""
    job = queue_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="İş bulunamadı.")
    return {"job": job}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """İşi iptal eder."""
    success = queue_manager.cancel_job(job_id)
    return {"success": success}


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str):
    """Başarısız işi tekrar sıraya alır."""
    retried = queue_manager.retry_job(job_id)
    if not retried:
        raise HTTPException(status_code=400, detail="İş yeniden başlatılamadı.")
    return {"job": retried}


@app.post("/api/jobs/{job_id}/reorder")
async def reorder_job(job_id: str, direction: str = Form(...)):
    """Kuyruktaki işin sırasını değiştirir (up / down)."""
    success = queue_manager.reorder_queue(job_id, direction)
    return {"success": success}


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """İşi siler."""
    success = queue_manager.delete_job(job_id)
    return {"success": success}


# ==========================================
# 3. ÇOK KİPLİ ASSET YÖNETİMİ (ASSETS)
# ==========================================
@app.post("/api/assets/upload")
async def upload_asset(file: UploadFile = File(...)):
    """Kullanıcının yüklediği referans görseli, videoyu veya sesi saklar ve asset_id döner."""
    content = await file.read()
    asset_info = storage.save_asset(content, file.filename)
    return {
        "status": "success",
        "asset_id": asset_info["asset_id"],
        "filename": asset_info["filename"],
        "media_type": asset_info.get("media_type", "image"),
        "preview_url": f"/api/assets/{asset_info['asset_id']}"
    }


@app.get("/api/assets")
async def list_assets():
    """Tüm yüklü referans dosyaları ve ID'lerini listeler."""
    return {"assets": storage.list_assets()}


@app.get("/api/assets/{asset_id}")
async def get_asset_preview(asset_id: str):
    """Yüklenen referans medyayı (görsel/video/ses) servis eder."""
    path = storage.get_asset_path(asset_id)
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Referans dosya bulunamadı.")
    
    ext = os.path.splitext(path)[1].lower()
    media_type_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
        ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".aac": "audio/aac"
    }
    content_type = media_type_map.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=content_type)



# ==========================================
# 4. GALERİ VE VİDEO YAYINI (MEDIA)
# ==========================================
@app.get("/api/gallery")
async def get_gallery(limit: int = 50):
    """Tamamlanmış videoları galeri kartları halinde döner."""
    all_jobs = queue_manager.list_jobs(limit=100)
    completed = [j for j in all_jobs if j.get("status") == "completed"]
    return {"videos": completed[:limit]}


@app.get("/api/videos/{job_id}/stream")
async def stream_video(job_id: str):
    """Üretilen MP4 videosunu video/mp4 formatında yayınlar."""
    if not is_safe_id(job_id):
        raise HTTPException(status_code=400, detail="Geçersiz iş kimliği.")

    local_path = os.path.join(settings.LOCAL_JOBS_DIR, job_id, "output.mp4")

    if not os.path.exists(local_path):
        # Drive bağlıysa Drive'dan yerel önbelleğe kopyala
        drive_path = os.path.join(settings.DRIVE_JOBS_DIR, job_id, "output.mp4")
        if os.path.exists(drive_path):
            safe_copy(drive_path, local_path)
        else:
            raise HTTPException(status_code=404, detail="Video dosyası bulunamadı.")

    return FileResponse(local_path, media_type="video/mp4", filename=f"{job_id}.mp4")


# ==========================================
# 5. KAMERA PRESETLERİ VE PROMPT GELİŞTİRİCİ
# ==========================================
@app.get("/api/presets/camera")
async def list_camera_presets():
    """Tüm kamera hareketi presetlerini döner."""
    return {"presets": [p.model_dump() for p in get_all_presets()]}


@app.post("/api/prompt/enhance")
async def enhance_user_prompt(payload: Dict[str, str]):
    """Basit bir promptu LTX-2.5 için optimize eder."""
    prompt = payload.get("prompt", "")
    enhanced = enhance_prompt(prompt)
    return {"original": prompt, "enhanced": enhanced}


# ==========================================
# 6. LORA YÖNETİMİ VE HIZLI İNDİRME (COLAB İNTERNETİ)
# ==========================================
@app.get("/api/loras")
async def get_loras():
    """Sistemde kayıtlı ve kullanıma hazır tüm LoRA modellerini listeler."""
    return {"loras": lora_manager.list_available_loras()}


@app.post("/api/loras/download")
async def download_lora(payload: Dict[str, Any]):
    """
    Colab'in yüksek hızlı internetini kullanarak Hugging Face veya Civitai üzerinden
    doğrudan Google Drive ve ComfyUI'ye LoRA modeli indirir.
    """
    url = payload.get("url")
    filename = payload.get("filename")
    hf_repo = payload.get("hf_repo")
    hf_file = payload.get("hf_file")

    if not url and not (hf_repo and hf_file):
        raise HTTPException(status_code=400, detail="Bir 'url' veya ('hf_repo' ve 'hf_file') sağlanmalıdır.")

    task = lora_manager.start_lora_download(
        url=url,
        filename=filename,
        hf_repo=hf_repo,
        hf_file=hf_file
    )
    return {"task": task}


@app.get("/api/loras/downloads")
async def get_lora_downloads():
    """Tüm aktif ve tamamlanmış LoRA indirme işlemlerinin durumunu döner."""
    return {"downloads": lora_manager.get_all_downloads()}


@app.get("/api/loras/downloads/{task_id}")
async def get_lora_download_progress(task_id: str):
    """Belirli bir LoRA indirme görevinin canlı ilerleme durumunu döner."""
    task = lora_manager.get_download_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"İndirme görevi '{task_id}' bulunamadı.")
    return {"task": task}


@app.delete("/api/loras/{filename}")
async def delete_lora_model(filename: str):
    """Belirtilen LoRA dosyasını sistemden siler."""
    deleted = lora_manager.delete_lora(filename)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"LoRA '{filename}' bulunamadı veya silinemedi.")
    return {"message": f"LoRA '{filename}' başarıyla silindi."}


# ==========================================
# 7. GERÇEK ZAMANLI WEBSOCKET (PROGRESS)
# ==========================================
@app.websocket("/ws/jobs")
async def websocket_endpoint(websocket: WebSocket):
    """UI'ın canlı ilerleme ve render yüzdesini (%0 - %100) dinlemesi için socket."""
    await queue_manager.register_websocket(websocket)
    try:
        while True:
            # İstemciden gelen ping/mesajları dinle (bağlantıyı canlı tutar)
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WebSocket] Bağlantı hatası: {e}")
    finally:
        queue_manager.unregister_websocket(websocket)


# ==========================================
# 7. REACT WEB UI STATİK DOSYALARI
# ==========================================
frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
else:
    @app.get("/")
    async def index_fallback():
        return {
            "message": "OzzyVision-Lab API çalışıyor.",
            "frontend_status": "React frontend henüz derlenmedi veya geliştirme sunucusunda (npm run dev) çalışıyor.",
            "studio_api_docs": "/docs",
            "mcp_endpoint": "/mcp"
        }
