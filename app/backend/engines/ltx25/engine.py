"""
LTX-2.5 Distilled GGUF Video Engine Adapter
ComfyUI API ile haberleşir, iş akışı JSON'ını dinamik olarak derler ve çıktıları yönetir.
"""

import json
import os
import random
from pathlib import Path
from typing import Dict, Any, Tuple

from app.backend.engines.base import BaseVideoEngine
from app.backend.camera_presets import apply_camera_preset
from app.backend.prompt_enhancer import enhance_prompt
import config.settings as settings


class LTX25Engine(BaseVideoEngine):
    """LTX-2.5 Distilled Q8 GGUF Motoru"""

    def __init__(self):
        super().__init__(name="ltx25")
        self.workflow_dir = Path(__file__).resolve().parent

    def calculate_dimensions_and_frames(
        self,
        aspect_ratio: str,
        duration: int,
        fps: int = 24,
        quality: str = "standard"
    ) -> Dict[str, int]:
        """
        LTX-2.5 kısıtları:
        1. Çözünürlük 32'ye tam bölünmelidir.
        2. Frame sayısı: 8n + 1 kuralına uymalıdır.
        """
        # Standart ve High modlar için temel çözünürlükler (32'nin katları)
        resolutions = {
            "16:9": (960, 544),    # 960 % 32 = 0, 544 % 32 = 0
            "9:16": (544, 960),    # 544 % 32 = 0, 960 % 32 = 0
            "1:1":  (768, 768),    # 768 % 32 = 0
            "4:3":  (896, 672),    # 896 % 32 = 0, 672 % 32 = 0
            "21:9": (1152, 480)    # 1152 % 32 = 0, 480 % 32 = 0
        }

        # Kaliteye göre ölçeklendirme
        width, height = resolutions.get(aspect_ratio, (960, 544))
        if quality == "draft":
            # Daha düşük çözünürlük (%75 ama 32'ye yuvarlanmış)
            width = (int(width * 0.75) // 32) * 32
            height = (int(height * 0.75) // 32) * 32

        # 8n + 1 frame hesaplama
        # Örneğin 3s * 24fps = 72 frame -> en yakın 8n+1: 73 (8*9 + 1)
        raw_frames = max(1, duration * fps)
        n = round((raw_frames - 1) / 8)
        frames = int(8 * max(1, n) + 1)

        return {
            "width": width,
            "height": height,
            "frames": frames,
            "fps": fps
        }

    def resolve_diffusion_model(self) -> Tuple[str, str]:
        """
        ComfyUI'de gercekten mevcut olan LTX-2.5 diffusion dosyasini ve
        ona uygun yukleyici dugumunu belirler.

        LTX-2.5 resmi olarak safetensors (int8/bf16/nvfp4) dagitilir; ayrica
        toplulukta GGUF varyantlari vardir. Sabit "UnetLoaderGGUF" kullanmak,
        safetensors indirildiginde ComfyUI'de dugum hatasina yol acardi.
        Doner: (dosya_adi, class_type)
        """
        candidates = list(getattr(settings, "MODEL_DIFFUSION_CANDIDATES", None)
                          or [settings.MODEL_DIFFUSION])

        available = set()
        for sub in ("diffusion_models", "unet"):
            d = os.path.join(settings.COMFYUI_DIR, "models", sub)
            if os.path.isdir(d):
                try:
                    available.update(os.listdir(d))
                except OSError:
                    pass

        chosen = None
        if available:
            for cand in candidates:
                if cand in available:
                    chosen = cand
                    break
            if chosen is None:
                # Listede yoksa dizindeki herhangi bir LTX dosyasini kabul et
                for fn in sorted(available):
                    low = fn.lower()
                    if low.startswith("ltx") and low.endswith((".safetensors", ".gguf")):
                        chosen = fn
                        break

        if chosen is None:
            chosen = candidates[0]

        class_type = "UnetLoaderGGUF" if chosen.lower().endswith(".gguf") else "UNETLoader"
        return chosen, class_type

    def build_workflow(
        self,
        job_params: Dict[str, Any],
        is_i2v: bool = False
    ) -> Dict[str, Any]:
        """
        Girdi parametrelerine göre ComfyUI API JSON nesnesini hazırlar.
        """
        template_file = "i2v_workflow.json" if is_i2v else "t2v_workflow.json"
        template_path = self.workflow_dir / template_file

        with open(template_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        # 0. Model yükleyici düğümlerini gerçek dosyalara göre ayarla
        unet_fn, unet_class = self.resolve_diffusion_model()
        if "1" in workflow:
            workflow["1"]["class_type"] = unet_class
            workflow["1"]["inputs"] = {"unet_name": unet_fn}
            if unet_class == "UNETLoader":
                workflow["1"]["inputs"]["weight_dtype"] = "default"

        if "2" in workflow and "inputs" in workflow["2"]:
            workflow["2"]["inputs"]["clip_name"] = settings.MODEL_TEXT_ENCODER

        if "3" in workflow and "inputs" in workflow["3"]:
            workflow["3"]["inputs"]["vae_name"] = settings.MODEL_VIDEO_VAE

        # 1. Prompt zenginleştirme & Kamera Preset uygulaması
        raw_prompt = job_params.get("prompt", "")
        if job_params.get("enhance_prompt", False):
            raw_prompt = enhance_prompt(raw_prompt)

        final_prompt = apply_camera_preset(
            base_prompt=raw_prompt,
            camera_id=job_params.get("camera", "static"),
            preserve_identity=is_i2v
        )

        neg_prompt = job_params.get(
            "negative_prompt",
            "worst quality, low quality, deformed, blurry, flickering, artifacts, distorted, static, jittery"
        )

        # 2. Boyut ve Frame hesabı
        dims = self.calculate_dimensions_and_frames(
            aspect_ratio=job_params.get("aspect_ratio", "16:9"),
            duration=int(job_params.get("duration", 5)),
            fps=int(job_params.get("fps", 24)),
            quality=job_params.get("quality", "standard")
        )

        # 3. Seed belirleme
        seed = int(job_params.get("seed", -1))
        if seed <= 0:
            seed = random.randint(1, 2**31 - 1)

        # 4. Adım sayısı ve CFG (Distilled modeller için optimize)
        quality = job_params.get("quality", "standard")
        steps = 8 if quality == "draft" else (8 if quality == "standard" else 10)
        cfg = 1.0

        # 5. LoRA Düğümlerini Zincirleme Ekle (Varsa)
        #
        # ÖNEMLİ (VRAM): LoRA varsayılan olarak SADECE diffusion modeline uygulanır
        # (LoraLoaderModelOnly). Klasik `LoraLoader` düğümü CLIP'i de patchlediği için
        # ComfyUI, Gemma 4 12B metin kodlayıcısını VRAM'e alıp klonlamak zorunda kalır;
        # bu da tek GPU'da neredeyse her zaman CUDA OOM ile sonuçlanır. Video LoRA'ları
        # zaten text-encoder ağırlığı içermediğinden CLIP patch'lemenin faydası yoktur.
        # Kullanıcı bilinçli olarak strength_clip > 0 verirse tam LoraLoader kullanılır.
        current_model_ref = ["1", 0]
        current_clip_ref = ["2", 0]
        loras = job_params.get("loras", [])
        active_loras = []
        allow_clip_default = bool(getattr(settings, "LORA_APPLY_TO_CLIP", False))

        if isinstance(loras, list):
            lora_node_start = 50
            for idx, lora in enumerate(loras[:getattr(settings, "MAX_LORAS_PER_JOB", 3)]):
                if isinstance(lora, dict):
                    lora_name = lora.get("name")
                    strength_model = float(lora.get("strength", 1.0))
                    if "strength_clip" in lora and lora.get("strength_clip") is not None:
                        strength_clip = float(lora["strength_clip"])
                    else:
                        strength_clip = strength_model if allow_clip_default else 0.0
                else:
                    lora_name = str(lora)
                    strength_model = 1.0
                    strength_clip = 1.0 if allow_clip_default else 0.0

                if not lora_name:
                    continue

                node_id = str(lora_node_start + idx)

                if strength_clip != 0.0:
                    workflow[node_id] = {
                        "class_type": "LoraLoader",
                        "inputs": {
                            "model": current_model_ref,
                            "clip": current_clip_ref,
                            "lora_name": lora_name,
                            "strength_model": strength_model,
                            "strength_clip": strength_clip
                        }
                    }
                    current_model_ref = [node_id, 0]
                    current_clip_ref = [node_id, 1]
                else:
                    workflow[node_id] = {
                        "class_type": "LoraLoaderModelOnly",
                        "inputs": {
                            "model": current_model_ref,
                            "lora_name": lora_name,
                            "strength_model": strength_model
                        }
                    }
                    current_model_ref = [node_id, 0]

                active_loras.append({
                    "name": lora_name,
                    "strength_model": strength_model,
                    "strength_clip": strength_clip
                })

        # 6. Node değerlerini güncelle
        # Positive Prompt (Node 4)
        if "4" in workflow and "inputs" in workflow["4"]:
            workflow["4"]["inputs"]["text"] = final_prompt
            workflow["4"]["inputs"]["clip"] = current_clip_ref

        # Negative Prompt (Node 5)
        if "5" in workflow and "inputs" in workflow["5"]:
            workflow["5"]["inputs"]["text"] = neg_prompt
            workflow["5"]["inputs"]["clip"] = current_clip_ref

        # LTXVConditioning Frame Rate (Node 7)
        if "7" in workflow and "inputs" in workflow["7"]:
            workflow["7"]["inputs"]["frame_rate"] = dims["fps"]
            # Savunmacı temizleme: LTXVConditioning sadece positive, negative, frame_rate kabul eder
            workflow["7"]["inputs"].pop("image", None)
            workflow["7"]["inputs"].pop("conditioning_strength", None)

        # Latent Boyutları (Node 8: EmptyLTXVLatentVideo veya LTXVImgToVideo)
        if "8" in workflow and "inputs" in workflow["8"]:
            workflow["8"]["inputs"]["width"] = dims["width"]
            workflow["8"]["inputs"]["height"] = dims["height"]
            workflow["8"]["inputs"]["length"] = dims["frames"]

        # Sampler Parametreleri (Node 9)
        if "9" in workflow and "inputs" in workflow["9"]:
            workflow["9"]["inputs"]["model"] = current_model_ref
            workflow["9"]["inputs"]["seed"] = seed
            workflow["9"]["inputs"]["steps"] = steps
            workflow["9"]["inputs"]["cfg"] = cfg

        # Video Combine Parametreleri (Node 11)
        if "11" in workflow and "inputs" in workflow["11"]:
            workflow["11"]["inputs"]["frame_rate"] = dims["fps"]
            workflow["11"]["inputs"]["filename_prefix"] = f"OzzyVision_{job_params.get('id', 'job')}"

        # I2V özel ayarları
        if is_i2v:
            # Görsel yolu (Node 6)
            image_name = job_params.get("image_filename", "input.png")
            if "6" in workflow and "inputs" in workflow["6"]:
                workflow["6"]["inputs"]["image"] = image_name

            # LTXVImgToVideo (Node 8) - Görsel sadakat / referans koruma kuvveti
            fidelity = float(job_params.get("image_fidelity", settings.DEFAULT_IMAGE_FIDELITY))
            if "8" in workflow and "inputs" in workflow["8"]:
                workflow["8"]["inputs"]["strength"] = fidelity

        # 6. Doğal Ses Ayarları (LTX-2.5 Dual-Stream AV Pipeline)
        with_audio = bool(job_params.get("audio", True))
        video_latent_ref = ["8", 2] if is_i2v else ["8", 0]

        if with_audio:
            # Düğüm 12: Audio VAE Yükleyici
            workflow["12"] = {
                "class_type": "VAELoader",
                "inputs": {
                    "vae_name": settings.MODEL_AUDIO_VAE
                }
            }
            # Düğüm 13: LTX-2.5 Boş Ses Latent Üretici
            workflow["13"] = {
                "class_type": "LTXVEmptyLatentAudio",
                "inputs": {
                    "audio_vae": ["12", 0],
                    "frames_number": dims["frames"],
                    "frame_rate": dims["fps"],
                    "batch_size": 1
                }
            }
            # Düğüm 14: Video Latent ile Ses Latent'ini Birleştir (Joint AV Latent)
            workflow["14"] = {
                "class_type": "LTXVConcatAVLatent",
                "inputs": {
                    "video_latent": video_latent_ref,
                    "audio_latent": ["13", 0]
                }
            }
            # Sampler (Düğüm 9) birleşik AV latent'ini alır
            if "9" in workflow and "inputs" in workflow["9"]:
                workflow["9"]["inputs"]["latent_image"] = ["14", 0]

            # Düğüm 15: Örnekleme sonrası Video ve Ses Latentlerini Ayır
            workflow["15"] = {
                "class_type": "LTXVSeparateAVLatent",
                "inputs": {
                    "av_latent": ["9", 0]
                }
            }
            # Düğüm 10 (Video VAEDecode) ayrılmış video latent'i alır
            if "10" in workflow and "inputs" in workflow["10"]:
                workflow["10"]["inputs"]["samples"] = ["15", 0]

            # Düğüm 16: Ses Latentini Dalgaya Çevir (Audio VAEDecode)
            workflow["16"] = {
                "class_type": "LTXVAudioVAEDecode",
                "inputs": {
                    "samples": ["15", 1],
                    "audio_vae": ["12", 0]
                }
            }
            # Düğüm 11 (VideoCombine) hem video karelerini hem sesi birleştirir
            if "11" in workflow and "inputs" in workflow["11"]:
                workflow["11"]["inputs"]["audio"] = ["16", 0]
        else:
            # Sessiz mod: Audio düğümlerini temizle, saf video üret
            if "9" in workflow and "inputs" in workflow["9"]:
                workflow["9"]["inputs"]["latent_image"] = video_latent_ref
            if "10" in workflow and "inputs" in workflow["10"]:
                workflow["10"]["inputs"]["samples"] = ["9", 0]
            if "11" in workflow and "inputs" in workflow["11"]:
                workflow["11"]["inputs"].pop("audio", None)

            workflow.pop("12", None)
            workflow.pop("13", None)
            workflow.pop("14", None)
            workflow.pop("15", None)
            workflow.pop("16", None)

        return {
            "prompt": workflow,
            "metadata": {
                "final_prompt": final_prompt,
                "seed": seed,
                "dimensions": dims,
                "steps": steps,
                "cfg": cfg,
                "sampler": "euler / sgm_uniform",
                "audio": with_audio,
                "loras": active_loras,
                "loaders": {
                    "diffusion": unet_fn,
                    "diffusion_node": unet_class,
                    "text_encoder": settings.MODEL_TEXT_ENCODER,
                    "video_vae": settings.MODEL_VIDEO_VAE,
                    "audio_vae": settings.MODEL_AUDIO_VAE if with_audio else None
                }
            }
        }
