"""
MiniMax H3 Omni-Modal Video Engine Adapter
(minimax_h3_ref2va_pruned_fp8_scaled.safetensors - Resmi Comfy-Org sürümü)

Omni-Reference video ve doğal 32 kHz stereo ses üretim motoru.
Desteklenen referans limitleri:
- Images: <= 9
- Videos: <= 3 (2-15s, toplam <= 15s)
- Audio: <= 3 (2-15s, toplam <= 15s)
- Toplam karma dosya: <= 12
"""

import json
import os
import random
from pathlib import Path
from typing import Dict, Any, List

from app.backend.engines.base import BaseVideoEngine
from app.backend import video_compat
from app.backend.camera_presets import apply_camera_preset
from app.backend.prompt_enhancer import enhance_prompt
import config.settings as settings


class MiniMaxH3Engine(BaseVideoEngine):
    """MiniMax H3 Ref2VA Omni Video & Audio Motoru"""

    def __init__(self):
        super().__init__(name="minimax_h3")
        self.workflow_dir = Path(__file__).resolve().parent

    def calculate_dimensions_and_frames(
        self,
        aspect_ratio: str,
        duration: int,
        fps: int = 24,
        quality: str = "standard"
    ) -> Dict[str, int]:
        """
        MiniMax H3 kısıtları:
        1. 768p tabanlı çözünürlükler (kısa kenar 768px veya 32'nin katı).
        2. Çıktı süresi 4 - 15 saniye aralığında olmalıdır.
        3. Sabit 24 FPS.
        4. MiniMax H3 3D VAE frame boyutu: (17k + 5) zamansal grid formülü.
        """
        resolutions = {
            "16:9": (1344, 768),
            "9:16": (768, 1344),
            "1:1":  (768, 768),
            "4:3":  (1024, 768),
            "3:4":  (768, 1024),
            "21:9": (1536, 640)
        }

        width, height = resolutions.get(aspect_ratio, (1344, 768))

        if quality == "draft":
            # Hızlı önizleme için %75 ölçek (32'nin katına yuvarlanmış)
            width = (int(width * 0.75) // 32) * 32
            height = (int(height * 0.75) // 32) * 32

        # MiniMax H3 4-15 saniye destekler
        clamped_duration = max(4, min(15, int(duration)))

        # MiniMax H3 3D VAE (17k + 5) grid formülü:
        # max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17
        raw_frames = max(5, round(clamped_duration * fps))
        frames = int(raw_frames + ((5 - (raw_frames % 17)) % 17))

        return {
            "width": width,
            "height": height,
            "frames": frames,
            "duration": clamped_duration,
            "fps": fps
        }

    @staticmethod
    def _reference_video_meta(job_params: Dict[str, Any], ref_videos: List[str]) -> List[Dict[str, Any]]:
        """
        Her referans video için ComfyUI'ye verilecek dosya adı ve ses izi bilgisi.
        Kuyruk yöneticisi hazırladıysa onu kullanır; aksi halde ComfyUI input dizinindeki dosyayı inceler.
        """
        prepared = job_params.get("ref_videos_prepared") or []
        if len(prepared) == len(ref_videos) and all(isinstance(p, dict) and p.get("file") for p in prepared):
            return prepared
        result = []
        for name in ref_videos:
            info = video_compat.probe(os.path.join(settings.COMFYUI_DIR, "input", name))
            result.append({"file": name, "has_audio": bool(info and info.get("audio_codec"))})
        return result

    def validate_reference_inputs(
        self,
        images: List[str],
        videos: List[str],
        audios: List[str]
    ) -> None:
        """
        Model kısıtlarını denetler:
        - Images <= 9
        - Videos <= 3
        - Audios <= 3
        - Toplam <= 12
        """
        if len(images) > settings.MINIMAX_MAX_IMAGES:
            raise ValueError(f"En fazla {settings.MINIMAX_MAX_IMAGES} görsel referansı yüklenebilir (Verilen: {len(images)})")
        if len(videos) > settings.MINIMAX_MAX_VIDEOS:
            raise ValueError(f"En fazla {settings.MINIMAX_MAX_VIDEOS} video klibi yüklenebilir (Verilen: {len(videos)})")
        if len(audios) > settings.MINIMAX_MAX_AUDIOS:
            raise ValueError(f"En fazla {settings.MINIMAX_MAX_AUDIOS} ses klibi yüklenebilir (Verilen: {len(audios)})")

        total = len(images) + len(videos) + len(audios)
        if total > settings.MINIMAX_MAX_TOTAL_REFERENCES:
            raise ValueError(f"Toplam karma referans sayısı en fazla {settings.MINIMAX_MAX_TOTAL_REFERENCES} olabilir (Verilen: {total})")

    def build_workflow(
        self,
        job_params: Dict[str, Any],
        is_i2v: bool = False
    ) -> Dict[str, Any]:
        """
        MiniMax H3 Text-to-Video, Image-to-Video ve Reference-to-Video ComfyUI iş akışını derler.
        """
        template_path = self.workflow_dir / "ref2va_workflow.json"
        with open(template_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        # 1. Referans dosyaları ayrıştır ve doğrula
        ref_images: List[str] = list(job_params.get("ref_images") or [])
        ref_videos: List[str] = list(job_params.get("ref_videos") or [])
        ref_audios: List[str] = list(job_params.get("ref_audios") or [])

        # Tekli I2V (image_filename) parametresi varsa ve ref_images boşsa
        single_image = job_params.get("image_filename")
        if single_image and not ref_images and not ref_videos and not ref_audios:
            # Saf tekli I2V modu
            has_single_image = True
        elif single_image and single_image not in ref_images:
            ref_images = [single_image] + ref_images
            has_single_image = False
        else:
            has_single_image = False

        self.validate_reference_inputs(ref_images, ref_videos, ref_audios)

        # 2. Prompt hazırlığı (kamera preseti dahil)
        raw_prompt = job_params.get("prompt", "")
        if job_params.get("enhance_prompt", False):
            raw_prompt = enhance_prompt(raw_prompt)

        has_any_reference = bool(ref_images or ref_videos or ref_audios or single_image)
        final_prompt = apply_camera_preset(
            base_prompt=raw_prompt,
            camera_id=job_params.get("camera", "auto"),
            preserve_identity=has_any_reference
        )

        # 3. Boyut ve Frame hesabı
        dims = self.calculate_dimensions_and_frames(
            aspect_ratio=job_params.get("aspect_ratio", "16:9"),
            duration=int(job_params.get("duration", settings.MINIMAX_DEFAULT_DURATION)),
            fps=int(job_params.get("fps", 24)),
            quality=job_params.get("quality", "standard")
        )

        # 4. Seed ve Örnekleyici Ayarları
        seed = int(job_params.get("seed", -1))
        if seed <= 0:
            seed = random.randint(1, 2**31 - 1)

        quality = job_params.get("quality", "standard")
        steps = 4 if quality == "draft" else (10 if quality == "high" else 8)
        cfg = float(settings.MINIMAX_DEFAULT_CFG)  # MiniMax H3 CFG-distilled (1.0)
        ref_image_size = job_params.get("ref_image_size", "match")

        # 5. Model ve CLIP Loader Güncelleme
        unet_fn = getattr(settings, "MINIMAX_DIFFUSION_MODEL", None) or settings.MINIMAX_DIFFUSION_GGUF
        comfy_diff_models = os.path.join(settings.COMFYUI_DIR, "models", "diffusion_models")
        if os.path.exists(comfy_diff_models):
            try:
                available_unets = os.listdir(comfy_diff_models)
                for cand in [
                    "minimax_h3_ref2va_pruned_fp8_scaled.safetensors",
                    "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                    "minimax_h3_ref2va_pruned_bf16.safetensors",
                ]:
                    if cand in available_unets:
                        unet_fn = cand
                        break
            except Exception:
                pass

        if "1" in workflow and "inputs" in workflow["1"]:
            workflow["1"]["inputs"]["unet_name"] = unet_fn
            if unet_fn.endswith(".safetensors"):
                workflow["1"]["class_type"] = "UNETLoader"
                workflow["1"]["inputs"]["weight_dtype"] = "default"
            else:
                workflow["1"]["class_type"] = "UnetLoaderGGUF"

        clip_fn = getattr(settings, "MINIMAX_TEXT_ENCODER", None) or getattr(settings, "MINIMAX_TEXT_ENCODER_GGUF", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors")

        # ComfyUI modelleri dizininde resmi safetensors varyantı varsa önceliklendir
        comfy_text_encoders = os.path.join(settings.COMFYUI_DIR, "models", "text_encoders")
        if os.path.exists(comfy_text_encoders):
            try:
                available = os.listdir(comfy_text_encoders)
                for cand in [
                    "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                    "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
                    "qwen3vl_32b_minimax_h3_int4_convrot.safetensors",
                    "qwen3vl_32b_minimax_h3_bf16.safetensors"
                ]:
                    if cand in available:
                        clip_fn = cand
                        break
            except Exception:
                pass

        if "2" in workflow and "inputs" in workflow["2"]:
            workflow["2"]["inputs"]["clip_name"] = clip_fn
            workflow["2"]["inputs"]["type"] = "minimax"
            if clip_fn.endswith(".safetensors"):
                workflow["2"]["class_type"] = "CLIPLoader"
                workflow["2"]["inputs"]["device"] = "default"
            else:
                workflow["2"]["class_type"] = "CLIPLoaderGGUF"

        if "3" in workflow and "inputs" in workflow["3"]:
            workflow["3"]["inputs"]["vae_name"] = settings.MINIMAX_VIDEO_VAE

        if "4" in workflow and "inputs" in workflow["4"]:
            workflow["4"]["inputs"]["vae_name"] = settings.MINIMAX_AUDIO_VAE

        # 6. LoRA Düğümlerini Zincirleme Ekle (Varsa)
        current_model_ref = ["1", 0]
        loras = job_params.get("loras", [])
        active_loras = []

        if isinstance(loras, list):
            lora_node_start = 50
            for idx, lora in enumerate(loras[:getattr(settings, "MAX_LORAS_PER_JOB", 3)]):
                lora_name = lora.get("name") if isinstance(lora, dict) else str(lora)
                if not lora_name:
                    continue
                strength_model = float(lora.get("strength", 1.0) if isinstance(lora, dict) else 1.0)
                # MiniMax H3'te Qwen3-VL 32B kodlayıcısı patchlenmez (VRAM koruması):
                # LoRA yalnızca diffusion modeline uygulanır.
                strength_clip = 0.0
                node_id = str(lora_node_start + idx)

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

        # 7. MiniMax Koşullandırma & Latent Düğümü (Node 8)
        # Çoklu Referans varsa: MiniMaxH3ReferenceToVideo
        # Referans yoksa veya tekli görsel I2V ise: MiniMaxH3ImageToVideo
        has_multi_ref = bool(ref_images or ref_videos or ref_audios)
        video_audio_count = 0

        if has_multi_ref:
            # Çoklu Referans (R2V) Düğümü
            workflow["8"] = {
                "class_type": "MiniMaxH3ReferenceToVideo",
                "inputs": {
                    "clip": ["2", 0],
                    "vae": ["3", 0],
                    "audio_vae": ["4", 0],
                    "prompt": final_prompt,
                    "width": dims["width"],
                    "height": dims["height"],
                    "length": dims["frames"],
                    "ref_image_size": ref_image_size
                }
            }

            # Resim referanslarını bağla
            for idx, img_fn in enumerate(ref_images):
                img_node_id = f"10{idx + 1}"
                workflow[img_node_id] = {
                    "class_type": "LoadImage",
                    "inputs": {
                        "image": img_fn
                    }
                }
                workflow["8"]["inputs"][f"ref_images.ref_image_{idx}"] = [img_node_id, 0]

            # Video referanslarını bağla.
            # ref_videos girdisi IMAGE (24 fps kareler) bekler; LoadVideo ise VIDEO döndürür.
            # GetVideoComponents videoyu kareler (0) ve sese (1) ayırır; ses aynı numaralı
            # ref_video_audios yuvasına gider.
            for idx, video in enumerate(self._reference_video_meta(job_params, ref_videos)):
                load_id = f"20{idx + 1}"
                split_id = f"21{idx + 1}"
                workflow[load_id] = {
                    "class_type": "LoadVideo",
                    "inputs": {"file": video["file"]}
                }
                workflow[split_id] = {
                    "class_type": "GetVideoComponents",
                    "inputs": {"video": [load_id, 0]}
                }
                workflow["8"]["inputs"][f"ref_videos.ref_video_{idx}"] = [split_id, 0]
                if video.get("has_audio"):
                    workflow["8"]["inputs"][f"ref_video_audios.ref_video_audio_{idx}"] = [split_id, 1]
                    video_audio_count += 1

            # Ses referanslarını bağla
            for idx, aud_fn in enumerate(ref_audios):
                aud_node_id = f"30{idx + 1}"
                workflow[aud_node_id] = {
                    "class_type": "LoadAudio",
                    "inputs": {
                        "audio": aud_fn
                    }
                }
                workflow["8"]["inputs"][f"ref_audios.ref_audio_{idx}"] = [aud_node_id, 0]

        else:
            # Saf Text-to-Video (T2V) veya Tekli Görsel (I2V)
            workflow["8"] = {
                "class_type": "MiniMaxH3ImageToVideo",
                "inputs": {
                    "clip": ["2", 0],
                    "vae": ["3", 0],
                    # Ses latenti üretimi için audio VAE. Düğüm bu girdiyi kabul
                    # etmiyorsa validate_workflow otomatik olarak kaldırır.
                    "audio_vae": ["4", 0],
                    "prompt": final_prompt,
                    "width": dims["width"],
                    "height": dims["height"],
                    "length": dims["frames"]
                }
            }

            if has_single_image and single_image:
                workflow["7"] = {
                    "class_type": "LoadImage",
                    "inputs": {
                        "image": single_image
                    }
                }
                workflow["8"]["inputs"]["first_frame"] = ["7", 0]

        # 8. Guider & Sampler Ayarları
        # BasicGuider (Node 9)
        if "9" in workflow and "inputs" in workflow["9"]:
            workflow["9"]["inputs"]["model"] = current_model_ref
            workflow["9"]["inputs"]["conditioning"] = ["8", 0]

        # BasicScheduler (Node 11)
        if "11" in workflow and "inputs" in workflow["11"]:
            workflow["11"]["inputs"]["model"] = current_model_ref
            workflow["11"]["inputs"]["steps"] = steps
            workflow["11"]["inputs"]["denoise"] = 1.0

        # RandomNoise (Node 12)
        if "12" in workflow and "inputs" in workflow["12"]:
            workflow["12"]["inputs"]["noise_seed"] = seed

        # SamplerCustomAdvanced (Node 13)
        if "13" in workflow and "inputs" in workflow["13"]:
            workflow["13"]["inputs"]["latent_image"] = ["8", 1]

        # CreateVideo (Node 16)
        if "16" in workflow and "inputs" in workflow["16"]:
            workflow["16"]["inputs"]["fps"] = dims["fps"]

        # SaveVideo (Node 17)
        if "17" in workflow and "inputs" in workflow["17"]:
            workflow["17"]["inputs"]["filename_prefix"] = f"OzzyVision_MiniMax_{job_params.get('id', 'job')}"
            workflow["17"]["inputs"]["format"] = "auto"

        return {
            "prompt": workflow,
            "metadata": {
                "final_prompt": final_prompt,
                "seed": seed,
                "dimensions": dims,
                "steps": steps,
                "cfg": cfg,
                "model": "minimax_h3",
                "reference_counts": {
                    "images": len(ref_images),
                    "videos": len(ref_videos),
                    "video_audios": video_audio_count,
                    "audios": len(ref_audios),
                    "total": len(ref_images) + len(ref_videos) + len(ref_audios)
                },
                "ref_image_size": ref_image_size,
                "sampler": "res_multistep / simple",
                "loras": active_loras,
                "loaders": {
                    "diffusion": unet_fn,
                    "diffusion_node": workflow["1"]["class_type"],
                    "text_encoder": clip_fn,
                    "video_vae": settings.MINIMAX_VIDEO_VAE,
                    "audio_vae": settings.MINIMAX_AUDIO_VAE
                }
            }
        }
