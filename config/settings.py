"""
OzzyVision-Lab - Global Configuration & Settings
Google Drive yolları şablon olarak burada toplanmıştır.
Gerçek yollar belirlendiğinde sadece bu dosyadaki değerleri veya çevre değişkenlerini (ENV) güncellemek yeterlidir.
"""

import os
from pathlib import Path

# ==========================================
# 1. GOOGLE DRIVE YOLLARI (ŞABLON / PLACEHOLDER)
# ==========================================
# Kullanıcı gerçek yolları bildirdiğinde burayı değiştirebilir.
GOOGLE_DRIVE_MOUNT_PATH = os.getenv("GOOGLE_DRIVE_MOUNT_PATH", "/content/drive/MyDrive")
DRIVE_PROJECT_ROOT = os.getenv("DRIVE_PROJECT_ROOT", f"{GOOGLE_DRIVE_MOUNT_PATH}/OzzyVision-Lab")

# Drive Kalıcı Depo Alt Dizinleri
DRIVE_MODELS_DIR = os.getenv("DRIVE_MODELS_DIR", f"{DRIVE_PROJECT_ROOT}/models")
DRIVE_LORAS_DIR = os.getenv("DRIVE_LORAS_DIR", f"{DRIVE_MODELS_DIR}/loras")
DRIVE_JOBS_DIR = os.getenv("DRIVE_JOBS_DIR", f"{DRIVE_PROJECT_ROOT}/jobs")
DRIVE_GALLERY_DIR = os.getenv("DRIVE_GALLERY_DIR", f"{DRIVE_PROJECT_ROOT}/gallery")
DRIVE_PRESETS_DIR = os.getenv("DRIVE_PRESETS_DIR", f"{DRIVE_PROJECT_ROOT}/presets")
DRIVE_ASSETS_DIR = os.getenv("DRIVE_ASSETS_DIR", f"{DRIVE_PROJECT_ROOT}/assets")
DRIVE_CONFIG_DIR = os.getenv("DRIVE_CONFIG_DIR", f"{DRIVE_PROJECT_ROOT}/config")

# ==========================================
# 2. RUNTIME VE YEREL ÖNBELLEK (LOCAL CACHE)
# ==========================================
# Colab üzerinde Drive'daki modeller ComfyUI'ye symlink edilir.
# Windows/Local geliştirme ortamında proje kök dizini kullanılır.
IS_COLAB = os.path.exists("/content")

if IS_COLAB:
    LOCAL_RUNTIME_DIR = "/content/OzzyVision-Lab"
    LOCAL_MODELS_CACHE = f"{DRIVE_PROJECT_ROOT}/models"
    COMFYUI_DIR = "/content/ComfyUI"
    ACTIVE_LORAS_DIR = DRIVE_LORAS_DIR
    COMFYUI_LORAS_DIR = f"{COMFYUI_DIR}/models/loras"
else:
    # Yerel geliştirme (Windows / Linux)
    _BASE_DIR = Path(__file__).resolve().parent.parent
    LOCAL_RUNTIME_DIR = str(_BASE_DIR / "local_storage")
    LOCAL_MODELS_CACHE = str(_BASE_DIR / "local_storage" / "models")
    COMFYUI_DIR = str(_BASE_DIR / "ComfyUI")
    ACTIVE_LORAS_DIR = str(_BASE_DIR / "local_storage" / "models" / "loras")
    COMFYUI_LORAS_DIR = str(_BASE_DIR / "ComfyUI" / "models" / "loras")

# Yerel çalışma dizinleri
LOCAL_JOBS_DIR = f"{LOCAL_RUNTIME_DIR}/jobs"
LOCAL_ASSETS_DIR = f"{LOCAL_RUNTIME_DIR}/assets"
LOCAL_OUTPUT_DIR = f"{LOCAL_RUNTIME_DIR}/outputs"

# ==========================================
# 3. COMFYUI VE SUNUCU AYARLARI
# ==========================================
COMFYUI_HOST = os.getenv("COMFYUI_HOST", "127.0.0.1")
COMFYUI_PORT = int(os.getenv("COMFYUI_PORT", "8188"))
COMFYUI_URL = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"
COMFYUI_MAX_WAIT_SECONDS = int(os.getenv("COMFYUI_MAX_WAIT_SECONDS", "1800"))  # 30 dakika maksimum süre

# ==========================================
# 3b. VRAM YÖNETİMİ (OOM ÖNLEME)
# ==========================================
# ComfyUI tek GPU üzerinde LTX-2.5 ve MiniMax H3 gibi çok büyük modelleri barındırır.
# Model/LoRA kombinasyonu değiştiğinde ComfyUI eski ağırlıkları VRAM'de tutmaya devam
# eder ve yeni kombinasyonu yüklemeye çalışırken CUDA OOM alınır.
# Aşağıdaki bayraklar bu geçişlerde /free çağrısı yaparak VRAM'i güvenle boşaltır.
FREE_VRAM_ON_MODEL_SWITCH = os.getenv("FREE_VRAM_ON_MODEL_SWITCH", "1") == "1"
FREE_VRAM_BEFORE_LORA_JOB = os.getenv("FREE_VRAM_BEFORE_LORA_JOB", "1") == "1"
# /free çağrısından sonra ComfyUI'nin belleği gerçekten iade etmesi için kısa bekleme
FREE_VRAM_SETTLE_SECONDS = float(os.getenv("FREE_VRAM_SETTLE_SECONDS", "2.5"))

# LoRA'lar varsayılan olarak SADECE diffusion modeline uygulanır.
# CLIP (Gemma 4 12B / Qwen3-VL 32B) patch'lemek dev metin kodlayıcıyı da VRAM'e
# çekip klonladığı için neredeyse her zaman OOM'a yol açar ve video LoRA'larında
# text-encoder ağırlığı bulunmadığı için hiçbir faydası yoktur.
LORA_APPLY_TO_CLIP = os.getenv("LORA_APPLY_TO_CLIP", "0") == "1"

# Yerel geliştirme: ComfyUI yokken sahte (mock) çıktı üretilsin mi?
DEV_MOCK_MODE = os.getenv("DEV_MOCK_MODE", "0") == "1"

# İlerleme (progress) güncellemelerinin diske/Drive'a yazılma sıklığı (saniye).
# Drive I/O yavaş olduğu için her tick'te job.json yazmak üretimi yavaşlatır.
PROGRESS_PERSIST_INTERVAL = float(os.getenv("PROGRESS_PERSIST_INTERVAL", "10"))

BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

# Ngrok Tünel Ayarları
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTHTOKEN") or os.getenv("NGROK_AUTH_TOKEN", "")
NGROK_DOMAIN = os.getenv("NGROK_DOMAIN", "")  # Free plan rezerve domain (opsiyonel)
HF_TOKEN = os.getenv("HF_TOKEN", "")
CIVITAI_TOKEN = os.getenv("CIVITAI_TOKEN", "")

# ==========================================
# 4. MODEL DOSYA ADLARI (LTX-2.5 & MINIMAX-H3)
# ==========================================
# LTX-2.5 Modeli (Lightricks/LTX-2.5 - 22B Distilled)
# Resmi Comfy int8 safetensors varsayilandir; GGUF varyanti da desteklenir.
# Motor, ComfyUI diffusion_models dizininde hangisi varsa onu ve dogru
# yukleyici dugumunu (UNETLoader / UnetLoaderGGUF) otomatik secer.
MODEL_DIFFUSION = os.getenv(
    "MODEL_DIFFUSION",
    "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
)
# Motorun tercih sirasiyla arayacagi LTX-2.5 diffusion dosyalari
MODEL_DIFFUSION_CANDIDATES = [
    MODEL_DIFFUSION,
    "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
    "ltx-2.5-22b-distilled-transformer-nvfp4.safetensors",
    "ltx-2.5-22b-distilled-transformer-Q8_0.gguf",
    "ltx-2.5-22b-distilled-transformer-Q6_K.gguf",
    "ltx-2.5-22b-distilled-transformer-Q5_K_M.gguf",
    "ltx-2.5-22b-distilled-transformer-bf16.safetensors",
    "ltx-2.5-22b-dev-transformer-comfy-int8-convrot.safetensors",
]
MODEL_DIFFUSION_GGUF = MODEL_DIFFUSION  # Geriye donuk uyumluluk
MODEL_TEXT_ENCODER = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
MODEL_VIDEO_VAE = "ltx-2.5-video-vae-bf16.safetensors"
MODEL_AUDIO_VAE = "ltx-2.5-audio-vae-bf16.safetensors"
MODEL_SPATIAL_UPSCALER = "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"
MODEL_TEMPORAL_UPSCALER = "ltx-2.5-latent-temporal-upscaler-x2-bf16-1.0.safetensors"

# MiniMax H3 Omni Modeli (Resmi Comfy-Org Safetensors & Native CLIP)
MINIMAX_DIFFUSION_MODEL = os.getenv("MINIMAX_DIFFUSION_MODEL", "minimax_h3_ref2va_pruned_fp8_scaled.safetensors")
MINIMAX_DIFFUSION_GGUF = MINIMAX_DIFFUSION_MODEL  # Geriye dönük uyumluluk
MINIMAX_TEXT_ENCODER = os.getenv("MINIMAX_TEXT_ENCODER", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")
MINIMAX_TEXT_ENCODER_GGUF = MINIMAX_TEXT_ENCODER  # Geriye dönük uyumluluk
MINIMAX_VIDEO_VAE = os.getenv("MINIMAX_VIDEO_VAE", "minimax_h3_video_vae_fp16.safetensors")
MINIMAX_AUDIO_VAE = os.getenv("MINIMAX_AUDIO_VAE", "minimax_h3_audio_vae_fp32.safetensors")

# ==========================================
# 5. DİĞER VARSAYILANLAR
# ==========================================
DEFAULT_FPS = 24
DEFAULT_STEPS = 8  # Distilled model için 8 adım optimize
DEFAULT_CFG = 1.0  # Distilled model için CFG = 1.0
DEFAULT_IMAGE_FIDELITY = 0.95  # Referans görsel koruma kuvveti

MINIMAX_DEFAULT_STEPS = 8
MINIMAX_DEFAULT_CFG = 1.0
MINIMAX_DEFAULT_DURATION = 8
MINIMAX_MAX_IMAGES = 9
MINIMAX_MAX_VIDEOS = 3
MINIMAX_MAX_AUDIOS = 3
MINIMAX_MAX_TOTAL_REFERENCES = 12
MAX_LORAS_PER_JOB = int(os.getenv("MAX_LORAS_PER_JOB", "3"))

