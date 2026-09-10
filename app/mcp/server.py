"""
OzzyVision-Lab - Claude Remote MCP Sunucusu
Claude Custom Connector ve Model Context Protocol (MCP) uyumlu sunucu.
Tümleşik medya yükleme (dosya yolu, URL, base64), MiniMax H3 Omni-Reference üretimi,
LTX-2.5 üretimi ve tam stüdyo yönetimi araçları sunar.
"""

import os
import base64
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List, Optional
try:
    import torch
except ImportError:  # torch yalnızca GPU raporlaması için gerekli
    torch = None

import json
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.backend.queue_manager import queue_manager
from app.backend.camera_presets import get_all_presets
from app.backend.storage import storage
from app.backend.prompt_enhancer import enhance_prompt
import app.backend.lora_manager as lora_manager
import config.settings as settings

mcp_router = APIRouter(prefix="/mcp", tags=["MCP"])


def resolve_media_item(item: str, expected_type: str = "image") -> str:
    """
    Verilen girdiyi akıllıca çözümler:
    1. Zaten mevcut bir asset_id veya dosya adı ise onu döner.
    2. HTTP/HTTPS URL ise dosyayı indirir ve depoya kaydedip yeni asset_id döner.
    3. Yerel dosya sistemi yolu ise dosyayı okur ve depoya kaydedip yeni asset_id döner.
    """
    if not item or not isinstance(item, str):
        return item

    # 1. Zaten mevcut asset mi?
    existing_path = storage.get_asset_path(item)
    if existing_path and os.path.exists(existing_path):
        return item

    # 2. HTTP/HTTPS URL mi?
    if item.startswith(("http://", "https://")):
        try:
            parsed = urllib.parse.urlparse(item)
            filename = os.path.basename(parsed.path) or f"downloaded_{expected_type}"
            req = urllib.request.Request(item, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=20) as resp:
                content = resp.read()
            asset = storage.save_asset(content, filename)
            return asset["asset_id"]
        except Exception as e:
            print(f"[MCP resolve_media_item URL Error] {e}")
            return item

    # 3. Yerel dosya yolu mu? (örn: C:/path/to/file.png veya relative)
    if os.path.isfile(item):
        try:
            with open(item, "rb") as f:
                content = f.read()
            filename = os.path.basename(item)
            asset = storage.save_asset(content, filename)
            return asset["asset_id"]
        except Exception as e:
            print(f"[MCP resolve_media_item File Error] {e}")
            return item

    return item


# MCP Araç Tanımları (JSON Schema)
MCP_TOOLS = [
    {
        "name": "upload_asset",
        "description": "Stüdyoya yeni bir görsel, video veya ses dosyası yükler. Yerel dosya yolu (file_path), internet URL'si (url) veya base64 verisi (base64_data) kabul eder. Üretim araçlarında kullanılabilecek benzersiz bir asset_id döner.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Bilgisayarınızdaki veya sunucudaki yerel dosya yolu (ör. 'C:/Users/foto.png' veya '/content/clip.mp4')."},
                "url": {"type": "string", "description": "İndirilecek medya dosyasının doğrudan web URL'si (http/https)."},
                "base64_data": {"type": "string", "description": "Base64 ile kodlanmış dosya ikili verisi."},
                "filename": {"type": "string", "description": "Kaydedilecek dosya adı (ör. 'karakter_yuzu.png'). Belirtilmezse otomatik atanır."},
                "media_type": {"type": "string", "enum": ["image", "video", "audio"], "description": "Medya türü (belirtilmezse uzantıdan otomatik tespit edilir)."}
            }
        }
    },
    {
        "name": "generate_omni_video",
        "description": "MiniMax H3 Omni (Q8_0 GGUF) modelini kullanarak çoklu referanslı video ve doğal 32 kHz stereo ses üretir. 9 adede kadar görsel (<Picture 1>...), 3 video (<Video 1>...) ve 3 ses (<Audio 1>...) referansı kabul eder. Dudak senkronlu konuşma için prompt içine `<d>[Turkish] Konuşma metni</d>` etiketleri eklenebilir.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Sahne betimlemesi, diyaloglar (<d>[Lang] ...</d>) ve referans etiketleri (<Picture 1>, <Video 1>, <Audio 1>)."},
                "negative_prompt": {"type": "string", "default": "worst quality, low quality, deformed, blurry, flickering, artifacts, distorted, static, jittery"},
                "images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Karakter, ortam veya stil için referans görseller listesi (En fazla 9 adet). Her eleman asset_id, yerel dosya yolu veya web URL'si olabilir.",
                    "default": []
                },
                "videos": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Kamera hareketi veya fiziksel hareket referansı için video klipleri listesi (En fazla 3 adet, her biri 2–15 sn). asset_id, yerel dosya yolu veya URL olabilir.",
                    "default": []
                },
                "audios": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Karakter ses tonu (timbre) veya fon müziği için referans sesler listesi (En fazla 3 adet, her biri 2–15 sn). asset_id, yerel dosya yolu veya URL olabilir.",
                    "default": []
                },
                "ref_image_size": {
                    "type": "string",
                    "enum": ["match", "max"],
                    "default": "match",
                    "description": "'match' hedef çözünürlüğe ölçekler (daha hızlı); 'max' 2048px'e kadar detayı korur (yüksek karakter sadakati)."
                },
                "aspect_ratio": {
                    "type": "string",
                    "enum": ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"],
                    "default": "16:9",
                    "description": "Çıktı en-boy oranı (768p tabanlı: 16:9 -> 1344x768)."
                },
                "duration": {
                    "type": "integer",
                    "minimum": 4,
                    "maximum": 15,
                    "default": 8,
                    "description": "Video süresi saniye cinsinden (4 ile 15 saniye arasında)."
                },
                "quality": {
                    "type": "string",
                    "enum": ["draft", "standard", "high"],
                    "default": "standard"
                },
                "seed": {
                    "type": "integer",
                    "default": -1,
                    "description": "Rastgelelik tohumu (-1 rastgele demektir)."
                },
                "enhance_prompt": {
                    "type": "boolean",
                    "default": False,
                    "description": "Promptu otomatik zenginleştir (diyalog etiketleri korunur)."
                },
                "loras": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"name": {"type": "string"}, "strength": {"type": "number"}}},
                    "description": "Kullanılacak LoRA modelleri ve ağırlıkları (ör. [{'name': 'stil.safetensors', 'strength': 0.8}]).",
                    "default": []
                }
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "generate_video_from_image",
        "description": "Mevcut veya yeni bir referans görselden video üretir (LTX-2.5 Image-to-Video). Doğrudan yerel görsel dosya yolu (image_path), web URL'si (image_url) veya kayıtlı bir asset_id verilebilir.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Bilgisayardaki görselin doğrudan yerel yolu (ör. 'C:/Users/foto.png'). Otomatik yüklenir."},
                "image_url": {"type": "string", "description": "Görselin doğrudan web bağlantısı (http/https). Otomatik indirilir."},
                "asset_id": {"type": "string", "description": "Daha önce yüklenmiş referans görsel ID'si veya dosya adı."},
                "prompt": {"type": "string", "description": "Görselin nasıl canlandırılacağını anlatan prompt."},
                "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16", "1:1", "4:3", "21:9"], "default": "16:9"},
                "duration": {"type": "integer", "minimum": 3, "maximum": 8, "default": 5, "description": "Video süresi (3 ile 8 saniye arasında)."},
                "camera": {"type": "string", "description": "Kamera hareketi preset'i (ör. auto, static, dolly_in, orbit_left, pan_right).", "default": "auto"},
                "motion_strength": {"type": "string", "enum": ["low", "medium", "high"], "default": "medium"},
                "image_fidelity": {"type": "number", "minimum": 0.5, "maximum": 1.0, "default": 0.95, "description": "Referans görseli koruma oranı (0.95 varsayılandır)."},
                "quality": {"type": "string", "enum": ["draft", "standard", "high"], "default": "standard"},
                "fps": {"type": "integer", "default": 24},
                "seed": {"type": "integer", "default": -1},
                "enhance_prompt": {"type": "boolean", "default": True},
                "audio": {"type": "boolean", "default": True, "description": "Doğal ambiyans ve ses efekti üret (LTX Audio VAE)."},
                "loras": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"name": {"type": "string"}, "strength": {"type": "number"}}},
                    "description": "Kullanılacak LoRA modelleri ve ağırlıkları (ör. [{'name': 'stil.safetensors', 'strength': 0.8}]).",
                    "default": []
                }
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "generate_video",
        "description": "Saf metinden video üretir (Text-to-Video). LTX-2.5 modelini kullanarak sinematik video oluşturup kuyruğa ekler.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Üretilecek videonun detaylı açıklaması."},
                "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16", "1:1", "4:3", "21:9"], "default": "16:9"},
                "duration": {"type": "integer", "minimum": 3, "maximum": 8, "default": 5},
                "camera": {"type": "string", "description": "Kamera hareketi preset'i (ör. auto, static, dolly_in, dolly_out, orbit_left, handheld, fpv, crane_up).", "default": "auto"},
                "quality": {"type": "string", "enum": ["draft", "standard", "high"], "default": "standard"},
                "fps": {"type": "integer", "default": 24},
                "seed": {"type": "integer", "default": -1},
                "enhance_prompt": {"type": "boolean", "default": True},
                "audio": {"type": "boolean", "default": True},
                "loras": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"name": {"type": "string"}, "strength": {"type": "number"}}},
                    "description": "Kullanılacak LoRA modelleri ve ağırlıkları (ör. [{'name': 'stil.safetensors', 'strength': 0.8}]).",
                    "default": []
                }
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "list_loras",
        "description": "Stüdyoda yüklü ve kullanıma hazır tüm LoRA modellerini listeler. Boyut, dosya adı ve değiştirilme tarihlerini gösterir.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "download_lora",
        "description": "Google Colab'in gigabit hızındaki internetini kullanarak Hugging Face veya Civitai üzerinden doğrudan sunucuya (Google Drive) yeni bir LoRA modeli (.safetensors) indirir.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Hugging Face doğrudan indirme URL'si veya Civitai indirme linki."},
                "filename": {"type": "string", "description": "İsteğe bağlı özel dosya adı (ör. 'my_character.safetensors')."},
                "hf_repo": {"type": "string", "description": "Hugging Face repo ID'si (ör. 'user/lora-repo')."},
                "hf_file": {"type": "string", "description": "Hugging Face dosya adı (ör. 'lora.safetensors')."}
            }
        }
    },

    {
        "name": "get_system_status",
        "description": "Stüdyonun genel donanım ve çalışma durumunu kontrol eder: GPU (VRAM), ComfyUI bağlantısı, Google Drive, aktif kuyruk ve yüklü modeller (LTX-2.5, MiniMax H3).",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "enhance_prompt",
        "description": "Kullanıcının yazdığı basit bir promptu sinematik anahtar kelimeler ve kamera direktifleriyle yapay zeka için otomatik zenginleştirir.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Zenginleştirilecek ham prompt."}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "list_assets",
        "description": "Stüdyoya yüklenmiş tüm referans medyaları (görsel, video, ses) listeler. Asset ID'lerini, dosya adlarını ve medya tiplerini döner.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "list_jobs",
        "description": "Kuyruktaki, üretilmekte olan ve tamamlanan tüm video işlerini listeler.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "description": "Getirilecek maksimum iş sayısı."}
            }
        }
    },
    {
        "name": "get_job",
        "description": "Belirli bir video işinin (job_id) detaylı durumunu, modelini, ilerleme yüzdesini ve varsa video linkini döner.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Sorgulanacak işin kimliği (ör. vid_20260908_x821)."}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "cancel_job",
        "description": "Kuyrukta bekleyen veya çalışmakta olan bir video işini iptal eder.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "İptal edilecek işin kimliği."}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "retry_job",
        "description": "Başarısız olmuş veya iptal edilmiş bir işi yeniden sıraya ekler.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Yeniden denenecek işin kimliği."}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "reorder_job",
        "description": "Kuyrukta bekleyen bir işin önceliğini değiştirir ('up' ile öne çeker, 'down' ile arkaya alır).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Sırası değiştirilecek iş kimliği."},
                "direction": {"type": "string", "enum": ["up", "down"], "description": "Taşıma yönü."}
            },
            "required": ["job_id", "direction"]
        }
    },
    {
        "name": "delete_job",
        "description": "Bir işi kuyruktan ve sistem geçmişinden tamamen siler.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Silinecek iş kimliği."}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "list_recent_videos",
        "description": "Google Drive ve yerel depoda tamamlanmış en son üretilen videoları listeler.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10, "description": "Listelenecek video sayısı."}
            }
        }
    },
    {
        "name": "free_vram",
        "description": "ComfyUI'nin GPU belleğinde (VRAM) tuttuğu tüm model ağırlıklarını boşaltır. Model veya LoRA değiştirdikten sonra 'CUDA out of memory' hatası alındığında kullanın.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "list_presets",
        "description": "Kullanılabilir kamera hareketi presetlerini ve açıklamalarını listeler.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]


def execute_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """MCP araç çağrısını ilgili backend fonksiyonuna yönlendirir."""

    # 1. MEDYA YÜKLEME ARACI
    if name == "upload_asset":
        file_path = arguments.get("file_path")
        url = arguments.get("url")
        base64_data = arguments.get("base64_data")
        custom_fn = arguments.get("filename")

        content = None
        target_fn = custom_fn or "uploaded_asset"

        if file_path:
            if not os.path.exists(file_path):
                return {"status": "error", "message": f"Yerel dosya bulunamadı: '{file_path}'"}
            try:
                with open(file_path, "rb") as f:
                    content = f.read()
                target_fn = custom_fn or os.path.basename(file_path)
            except Exception as e:
                return {"status": "error", "message": f"Dosya okunamadı: {e}"}

        elif url:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=25) as resp:
                    content = resp.read()
                parsed = urllib.parse.urlparse(url)
                target_fn = custom_fn or (os.path.basename(parsed.path) or "downloaded_file")
            except Exception as e:
                return {"status": "error", "message": f"URL indirilemedi: {e}"}

        elif base64_data:
            try:
                if "," in base64_data:
                    base64_data = base64_data.split(",", 1)[1]
                content = base64.b64decode(base64_data)
                target_fn = custom_fn or "base64_asset.png"
            except Exception as e:
                return {"status": "error", "message": f"Base64 çözülemedi: {e}"}
        else:
            return {"status": "error", "message": "Lütfen 'file_path', 'url' veya 'base64_data' parametrelerinden birini sağlayın."}

        asset_info = storage.save_asset(content, target_fn)
        return {
            "status": "success",
            "message": f"Medya başarıyla yüklendi: {asset_info['filename']} ({asset_info['media_type']})",
            "asset_id": asset_info["asset_id"],
            "filename": asset_info["filename"],
            "media_type": asset_info["media_type"],
            "size_bytes": asset_info["size"],
            "preview_url": f"/api/assets/{asset_info['asset_id']}"
        }

    # 2. MINIMAX H3 OMNI-REFERENCE VİDEO ÜRETİMİ
    elif name == "generate_omni_video":
        prompt = arguments.get("prompt") or ""
        if not prompt.strip():
            return {"status": "error", "message": "MiniMax H3 üretimi için bir 'prompt' metni gereklidir."}
        raw_images = arguments.get("images") or []
        raw_videos = arguments.get("videos") or []
        raw_audios = arguments.get("audios") or []

        # Akıllı çözümleme: Yerel yol veya URL ise otomatik yükle
        resolved_images = [resolve_media_item(i, "image") for i in raw_images]
        resolved_videos = [resolve_media_item(v, "video") for v in raw_videos]
        resolved_audios = [resolve_media_item(a, "audio") for a in raw_audios]

        job = queue_manager.create_job({
            "model": "minimax_h3",
            "prompt": prompt,
            "negative_prompt": arguments.get("negative_prompt", "worst quality, low quality, deformed, blurry, flickering, artifacts, distorted, static, jittery"),
            "aspect_ratio": arguments.get("aspect_ratio", "16:9"),
            "duration": arguments.get("duration", 8),
            "quality": arguments.get("quality", "standard"),
            "fps": 24,
            "seed": arguments.get("seed", -1),
            "enhance_prompt": arguments.get("enhance_prompt", False),
            "ref_images": resolved_images,
            "ref_videos": resolved_videos,
            "ref_audios": resolved_audios,
            "ref_image_size": arguments.get("ref_image_size", "match"),
            "loras": arguments.get("loras") or [],
            "audio": True
        })

        return {
            "status": "success",
            "message": f"MiniMax H3 Omni video işi #{job['id']} kuyruğa eklendi.",
            "job_id": job["id"],
            "model": "MiniMax H3 Omni Ref2VA Q8_0",
            "duration": job["duration"],
            "reference_counts": {
                "images": len(resolved_images),
                "videos": len(resolved_videos),
                "audios": len(resolved_audios)
            },
            "job": job
        }

    # 3. LTX-2.5 IMAGE TO VIDEO (GÖRSEL YOLU VEYA ASSET ID)
    elif name == "generate_video_from_image":
        asset_id = arguments.get("asset_id")
        image_path = arguments.get("image_path")
        image_url = arguments.get("image_url")

        # Doğrudan yol veya URL verilmişse otomatik yükle
        if image_path:
            asset_id = resolve_media_item(image_path, "image")
        elif image_url:
            asset_id = resolve_media_item(image_url, "image")

        if not asset_id:
            return {"status": "error", "message": "Lütfen bir 'image_path', 'image_url' veya 'asset_id' belirtin."}

        asset_path = storage.get_asset_path(asset_id)
        if not asset_path:
            available_assets = [a["filename"] for a in storage.list_assets()]
            return {
                "status": "error",
                "message": f"Asset '{asset_id}' bulunamadı. Mevcut assetler: {available_assets[:5]}..."
            }

        job = queue_manager.create_job({
            "model": "ltx25",
            "mode": "image_to_video",
            "asset_id": asset_id,
            "prompt": arguments.get("prompt"),
            "aspect_ratio": arguments.get("aspect_ratio", "16:9"),
            "duration": arguments.get("duration", 5),
            "camera": arguments.get("camera", "static"),
            "motion_strength": arguments.get("motion_strength", "medium"),
            "image_fidelity": arguments.get("image_fidelity", 0.95),
            "quality": arguments.get("quality", "standard"),
            "fps": arguments.get("fps", 24),
            "seed": arguments.get("seed", -1),
            "enhance_prompt": arguments.get("enhance_prompt", True),
            "audio": arguments.get("audio", True),
            "loras": arguments.get("loras") or []
        })

        return {
            "status": "success",
            "message": f"LTX-2.5 Görselden video işi #{job['id']} kuyruğa eklendi. (Fidelity: {job['image_fidelity']})",
            "job_id": job["id"],
            "job": job
        }

    # 4. LTX-2.5 TEXT TO VIDEO
    elif name == "generate_video":
        if not (arguments.get("prompt") or "").strip():
            return {"status": "error", "message": "Video üretimi için bir 'prompt' metni gereklidir."}
        job = queue_manager.create_job({
            "model": "ltx25",
            "mode": "text_to_video",
            "prompt": arguments.get("prompt"),
            "aspect_ratio": arguments.get("aspect_ratio", "16:9"),
            "duration": arguments.get("duration", 5),
            "camera": arguments.get("camera", "static"),
            "quality": arguments.get("quality", "standard"),
            "fps": arguments.get("fps", 24),
            "seed": arguments.get("seed", -1),
            "enhance_prompt": arguments.get("enhance_prompt", True),
            "audio": arguments.get("audio", True),
            "loras": arguments.get("loras") or []
        })
        return {
            "status": "success",
            "message": f"LTX-2.5 Video işi #{job['id']} başarıyla kuyruğa eklendi.",
            "job_id": job["id"],
            "job": job
        }

    # 5. LORA LİSTELEME
    elif name == "list_loras":
        loras = lora_manager.list_available_loras()
        return {
            "status": "success",
            "total": len(loras),
            "loras": loras
        }

    # 6. LORA İNDİRME (COLAB İNTERNETİ)
    elif name == "download_lora":
        url = arguments.get("url")
        filename = arguments.get("filename")
        hf_repo = arguments.get("hf_repo")
        hf_file = arguments.get("hf_file")

        if not url and not (hf_repo and hf_file):
            return {"status": "error", "message": "Lütfen bir 'url' veya 'hf_repo' ve 'hf_file' belirtin."}

        task = lora_manager.start_lora_download(
            url=url,
            filename=filename,
            hf_repo=hf_repo,
            hf_file=hf_file
        )
        return {
            "status": "success",
            "message": f"LoRA indirme görevi Colab interneti ile başlatıldı: {task['filename']}",
            "task_id": task["id"],
            "filename": task["filename"],
            "task": task
        }

    # 7. SİSTEM DURUMU
    elif name == "get_system_status":
        has_cuda = bool(torch and torch.cuda.is_available())
        gpu_name = torch.cuda.get_device_name(0) if has_cuda else "CPU (Simülasyon)"
        gpu_memory_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 1) if has_cuda else 0
        drive_connected = os.path.exists(settings.DRIVE_PROJECT_ROOT) or os.path.exists(settings.GOOGLE_DRIVE_MOUNT_PATH)
        jobs = queue_manager.list_jobs(limit=100)
        completed_count = sum(1 for j in jobs if j.get("status") == "completed")

        from app.backend.engines import get_engine as _get_engine
        comfy_stats = _get_engine("ltx25").get_system_stats()

        return {
            "status": "online",
            "comfyui": {"online": comfy_stats is not None, "url": settings.COMFYUI_URL},
            "gpu": {"available": has_cuda, "name": gpu_name, "vram_gb": gpu_memory_gb},
            "storage": {"drive_connected": drive_connected, "drive_root": settings.DRIVE_PROJECT_ROOT},
            "queue": {"active_job_id": queue_manager.active_job_id, "queue_length": len(queue_manager.queue), "completed_total": completed_count},
            "supported_models": [
                {"id": "minimax_h3", "name": "MiniMax H3 Omni Ref2VA", "features": "9 gorsel, 3 video, 3 ses referansi; 32 kHz stereo"},
                {"id": "ltx25", "name": "LTX-2.5 Distilled 22B", "features": "Hizli (8 adim), metin veya tek gorsel"}
            ]
        }

    # 6. PROMPT ZENGİNLEŞTİRME
    elif name == "enhance_prompt":
        raw = arguments.get("prompt", "")
        enhanced = enhance_prompt(raw)
        return {"status": "success", "original": raw, "enhanced": enhanced}

    # 7. VARLIKLARI LİSTELEME
    elif name == "list_assets":
        assets = storage.list_assets()
        return {
            "status": "success",
            "total_assets": len(assets),
            "assets": [
                {
                    "id": a["id"],
                    "filename": a["filename"],
                    "media_type": a.get("media_type", "image"),
                    "location": a["location"],
                    "size_kb": round(a["size_bytes"] / 1024, 1)
                }
                for a in assets
            ]
        }

    # 8. İŞLERİ LİSTELEME
    elif name == "list_jobs":
        limit = arguments.get("limit", 20)
        jobs = queue_manager.list_jobs(limit=limit)
        return {"total": len(jobs), "jobs": jobs}

    # 9. İŞ DETAYI
    elif name == "get_job":
        job_id = arguments.get("job_id")
        job = queue_manager.get_job(job_id)
        if not job:
            return {"status": "error", "message": f"Job {job_id} bulunamadı."}
        return {"job": job}

    # 10. İŞ İPTAL
    elif name == "cancel_job":
        job_id = arguments.get("job_id")
        success = queue_manager.cancel_job(job_id)
        return {"status": "success" if success else "error", "job_id": job_id, "cancelled": success}

    # 11. İŞ YENİDEN DENEME
    elif name == "retry_job":
        job_id = arguments.get("job_id")
        retried = queue_manager.retry_job(job_id)
        if not retried:
            return {"status": "error", "message": f"Job {job_id} yeniden sıraya eklenemedi."}
        return {"status": "success", "job": retried}

    # 12. İŞ SIRALAMASI DEĞİŞTİRME
    elif name == "reorder_job":
        job_id = arguments.get("job_id")
        direction = arguments.get("direction", "up")
        success = queue_manager.reorder_queue(job_id, direction)
        return {"status": "success" if success else "error", "job_id": job_id, "direction": direction, "reordered": success}

    # 13. İŞ SİLME
    elif name == "delete_job":
        job_id = arguments.get("job_id")
        success = queue_manager.delete_job(job_id)
        return {"status": "success" if success else "error", "job_id": job_id, "deleted": success}

    # 14. SON VİDEOLAR
    elif name == "list_recent_videos":
        limit = arguments.get("limit", 10)
        completed_jobs = [j for j in queue_manager.list_jobs(limit=100) if j.get("status") == "completed"]
        return {"total": len(completed_jobs[:limit]), "videos": completed_jobs[:limit]}

    # 16. GPU BELLEĞİNİ BOŞALT
    elif name == "free_vram":
        from app.backend.engines import get_engine as _get_engine
        ok = _get_engine("ltx25").free_memory(unload_models=True)
        queue_manager.reset_loaded_signature()
        return {
            "status": "success" if ok else "error",
            "message": "ComfyUI GPU belleği boşaltıldı." if ok else "ComfyUI'ye ulaşılamadı."
        }

    # 15. KAMERA PRESETLERİ
    elif name == "list_presets":
        presets = get_all_presets()
        return {"total": len(presets), "camera_presets": [p.model_dump() for p in presets]}

    else:
        return {"status": "error", "message": f"Bilinmeyen araç: {name}"}


@mcp_router.get("")
@mcp_router.get("/")
async def mcp_info():
    """
    MCP uç noktası hakkında bilgi döner. Claude Remote MCP bağlantısı POST
    (JSON-RPC 2.0) üzerinden yapılır; bu GET yalnızca doğrulama içindir.
    """
    return JSONResponse(content={
        "name": "ozzyvision-lab-mcp",
        "version": "2.0.0",
        "protocol": "JSON-RPC 2.0 over HTTP POST",
        "transport": "streamable-http",
        "tool_count": len(MCP_TOOLS),
        "tools": [t["name"] for t in MCP_TOOLS],
        "hint": "Claude > Settings > Connectors > Add Custom Connector ile bu URL'i ekleyin."
    })


@mcp_router.post("")
@mcp_router.post("/")
async def handle_mcp_rpc(request: Request):
    """
    JSON-RPC 2.0 tabanlı MCP protokol işleyicisi (Claude Custom Connector uyumlu).
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})

    method = body.get("method")
    req_id = body.get("id")
    params = body.get("params", {})

    if method == "initialize":
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "ozzyvision-lab-mcp",
                    "version": "2.0.0"
                }
            }
        })

    elif method == "notifications/initialized":
        return Response(status_code=204)

    elif method == "tools/list":
        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": MCP_TOOLS
            }
        })

    elif method == "ping":
        return JSONResponse(content={"jsonrpc": "2.0", "id": req_id, "result": {}})

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            result = execute_tool(tool_name, arguments)
        except Exception as e:
            print(f"[MCP] Araç çalıştırma hatası ({tool_name}): {e}")
            result = {"status": "error", "message": f"Araç '{tool_name}' çalıştırılamadı: {e}"}

        is_error = isinstance(result, dict) and result.get("status") == "error"
        try:
            text_payload = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        except Exception:
            text_payload = str(result)

        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": text_payload
                    }
                ],
                "isError": is_error,
                # MCP spec alanı + geriye dönük uyumluluk için "structured"
                "structuredContent": result,
                "structured": result
            }
        })

    return JSONResponse(content={
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"Method not found: {method}"
        }
    })
