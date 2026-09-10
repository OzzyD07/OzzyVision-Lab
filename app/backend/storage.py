"""
Storage and Synchronization Manager
Yerel çalışma alanı (/content veya local) ile Google Drive kalıcı depolama arasındaki
dosya, görsel, video ve job.json senkronizasyonunu yönetir.
"""

import os
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
import config.settings as settings


# Dosya adı olarak kullanılabilecek güvenli kimlikler.
# Stüdyo ngrok üzerinden herkese açık bir adreste yayınlandığı için
# job_id / asset_id gibi URL parametreleri dizin geçişine (path traversal)
# izin vermemelidir.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def is_safe_id(value: str) -> bool:
    """Kimliğin dosya yolu bileşeni olarak güvenli olup olmadığını denetler."""
    if not value or not isinstance(value, str) or len(value) > 200:
        return False
    if value in (".", "..") or value.startswith("."):
        return False
    return bool(_SAFE_ID_RE.match(value))


def safe_copy(src: str, dst: str) -> bool:
    """
    Kaynak ve hedef dosya aynı fiziksel dosya değilse kopyalar.
    Symlink veya aynı dosya durumunda SameFileError fırlatmaz.
    """
    if not src or not os.path.exists(src):
        return False
    try:
        if os.path.exists(dst) and os.path.samefile(src, dst):
            return True
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except (shutil.SameFileError, OSError):
        return True


class StorageManager:
    """Kalıcı Google Drive ve yerel önbellek dosya yöneticisi"""

    def __init__(self):
        self.drive_mounted = os.path.exists(settings.DRIVE_PROJECT_ROOT)
        self.ensure_directories()

    def ensure_directories(self):
        """Tüm yerel ve (varsa) Drive dizinlerinin varlığını garanti eder."""
        # Yerel çalışma dizinleri
        for d in [settings.LOCAL_RUNTIME_DIR, settings.LOCAL_JOBS_DIR,
                  settings.LOCAL_ASSETS_DIR, settings.LOCAL_OUTPUT_DIR]:
            os.makedirs(d, exist_ok=True)

        # Drive dizinleri (Drive bağlı ise oluştur)
        if os.path.exists(settings.GOOGLE_DRIVE_MOUNT_PATH):
            self.drive_mounted = True
            for d in [settings.DRIVE_PROJECT_ROOT, settings.DRIVE_MODELS_DIR,
                      settings.DRIVE_JOBS_DIR, settings.DRIVE_GALLERY_DIR,
                      settings.DRIVE_PRESETS_DIR, settings.DRIVE_ASSETS_DIR]:
                os.makedirs(d, exist_ok=True)

    IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
    VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".avi")
    AUDIO_EXTS = (".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a")
    ALL_EXTS = IMAGE_EXTS + VIDEO_EXTS + AUDIO_EXTS

    def detect_media_type(self, filename: str) -> str:
        """Dosya uzantısına göre media_type döner ('image', 'video', 'audio')."""
        ext = os.path.splitext(filename)[1].lower()
        if ext in self.VIDEO_EXTS:
            return "video"
        elif ext in self.AUDIO_EXTS:
            return "audio"
        return "image"

    def save_asset(self, file_content: bytes, original_filename: str) -> Dict[str, Any]:
        """
        Kullanıcı veya API tarafından yüklenen referans görseli/videoyu/sesi kaydeder.
        Benzersiz asset_id üretir ve medya tipini belirler.
        """
        ext = os.path.splitext(original_filename)[1].lower()
        if not ext or ext not in self.ALL_EXTS:
            ext = ".png"

        media_type = self.detect_media_type(f"file{ext}")
        prefix = "img" if media_type == "image" else ("vid" if media_type == "video" else "aud")
        asset_id = f"asset_{prefix}_{uuid.uuid4().hex[:8]}"
        filename = f"{asset_id}{ext}"

        local_path = os.path.join(settings.LOCAL_ASSETS_DIR, filename)
        with open(local_path, "wb") as f:
            f.write(file_content)

        # ComfyUI'nin input dizinine de kopyala (ComfyUI LoadImage/LoadVideo/LoadAudio doğrudan okuyabilsin)
        comfy_input_dir = os.path.join(settings.COMFYUI_DIR, "input")
        os.makedirs(comfy_input_dir, exist_ok=True)
        safe_copy(local_path, os.path.join(comfy_input_dir, filename))

        # Drive bağlıysa oraya da kalıcı olarak yedekle
        if self.drive_mounted and os.path.exists(settings.DRIVE_ASSETS_DIR):
            safe_copy(local_path, os.path.join(settings.DRIVE_ASSETS_DIR, filename))

        return {
            "asset_id": asset_id,
            "filename": filename,
            "media_type": media_type,
            "local_path": local_path,
            "size": len(file_content)
        }

    def get_asset_path(self, asset_id: str) -> Optional[str]:
        """asset_id veya dosya adına göre yerel dosya yolunu döner."""
        if not is_safe_id(asset_id):
            return None
        lookup_exts = self.ALL_EXTS + ("",)
        # 1. Local assets içinde ara
        for ext in lookup_exts:
            target = os.path.join(settings.LOCAL_ASSETS_DIR, f"{asset_id}{ext}")
            if os.path.exists(target):
                return target

        # 2. Drive bağlıysa Drive'dan geri getir
        if self.drive_mounted and os.path.exists(settings.DRIVE_ASSETS_DIR):
            for ext in lookup_exts:
                target = os.path.join(settings.DRIVE_ASSETS_DIR, f"{asset_id}{ext}")
                if os.path.exists(target):
                    local_target = os.path.join(settings.LOCAL_ASSETS_DIR, f"{asset_id}{ext}")
                    safe_copy(target, local_target)
                    return local_target

        # 3. ComfyUI input içinde ara (kullanıcı doğrudan oraya yüklemiş olabilir)
        comfy_input = os.path.join(settings.COMFYUI_DIR, "input")
        if os.path.exists(comfy_input):
            for ext in lookup_exts:
                target = os.path.join(comfy_input, f"{asset_id}{ext}")
                if os.path.exists(target):
                    return target

        return None

    def list_assets(self) -> List[Dict[str, Any]]:
        """
        Hem Drive hem de yerel assets klasöründeki tüm referans dosyaları listeler.
        Dosya adlarını, ID'leri, medya tiplerini ve konumlarını döner.
        """
        assets = {}
        valid_exts = self.ALL_EXTS

        # 1. Drive assets klasörü
        if self.drive_mounted and os.path.exists(settings.DRIVE_ASSETS_DIR):
            for fn in os.listdir(settings.DRIVE_ASSETS_DIR):
                if fn.lower().endswith(valid_exts):
                    p = os.path.join(settings.DRIVE_ASSETS_DIR, fn)
                    base, _ = os.path.splitext(fn)
                    assets[fn] = {
                        "id": base,
                        "filename": fn,
                        "media_type": self.detect_media_type(fn),
                        "location": "google_drive",
                        "size_bytes": os.path.getsize(p),
                        "path": p
                    }

        # 2. Local assets klasörü
        if os.path.exists(settings.LOCAL_ASSETS_DIR):
            for fn in os.listdir(settings.LOCAL_ASSETS_DIR):
                if fn.lower().endswith(valid_exts) and fn not in assets:
                    p = os.path.join(settings.LOCAL_ASSETS_DIR, fn)
                    base, _ = os.path.splitext(fn)
                    assets[fn] = {
                        "id": base,
                        "filename": fn,
                        "media_type": self.detect_media_type(fn),
                        "location": "local_assets",
                        "size_bytes": os.path.getsize(p),
                        "path": p
                    }

        # 3. ComfyUI input klasörü
        comfy_input = os.path.join(settings.COMFYUI_DIR, "input")
        if os.path.exists(comfy_input):
            for fn in os.listdir(comfy_input):
                if fn.lower().endswith(valid_exts) and fn not in assets:
                    p = os.path.join(comfy_input, fn)
                    base, _ = os.path.splitext(fn)
                    assets[fn] = {
                        "id": base,
                        "filename": fn,
                        "media_type": self.detect_media_type(fn),
                        "location": "comfy_input",
                        "size_bytes": os.path.getsize(p),
                        "path": p
                    }

        return list(assets.values())


    def save_job(self, job_data: Dict[str, Any]):
        """
        Job durumunu job.json olarak hem yerele hem Drive'a kaydeder.
        """
        job_id = job_data["id"]
        job_dir = os.path.join(settings.LOCAL_JOBS_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)

        json_path = os.path.join(job_dir, "job.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(job_data, f, indent=2, ensure_ascii=False)

        # Drive kalıcı klasörüne kopyala
        if self.drive_mounted and os.path.exists(settings.DRIVE_JOBS_DIR):
            drive_job_dir = os.path.join(settings.DRIVE_JOBS_DIR, job_id)
            os.makedirs(drive_job_dir, exist_ok=True)
            safe_copy(json_path, os.path.join(drive_job_dir, "job.json"))

    def save_job_output(
        self,
        job_id: str,
        video_source_path: str,
        thumbnail_source_path: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Üretilen MP4 videosunu ve thumbnail görselini job dizinine ve Drive galerisine kaydeder.
        """
        local_job_dir = os.path.join(settings.LOCAL_JOBS_DIR, job_id)
        os.makedirs(local_job_dir, exist_ok=True)

        local_mp4 = os.path.join(local_job_dir, "output.mp4")
        if os.path.exists(video_source_path):
            safe_copy(video_source_path, local_mp4)

        local_thumb = None
        if thumbnail_source_path and os.path.exists(thumbnail_source_path):
            local_thumb = os.path.join(local_job_dir, "thumbnail.jpg")
            safe_copy(thumbnail_source_path, local_thumb)

        # Drive senkronizasyonu
        drive_mp4 = None
        if self.drive_mounted and os.path.exists(settings.DRIVE_JOBS_DIR):
            drive_job_dir = os.path.join(settings.DRIVE_JOBS_DIR, job_id)
            os.makedirs(drive_job_dir, exist_ok=True)
            if os.path.exists(local_mp4):
                drive_mp4 = os.path.join(drive_job_dir, "output.mp4")
                safe_copy(local_mp4, drive_mp4)

                # Ayrıca gallery klasörüne de kolay erişim için kopyala
                if os.path.exists(settings.DRIVE_GALLERY_DIR):
                    safe_copy(local_mp4, os.path.join(settings.DRIVE_GALLERY_DIR, f"{job_id}.mp4"))

            if local_thumb and os.path.exists(local_thumb):
                safe_copy(local_thumb, os.path.join(drive_job_dir, "thumbnail.jpg"))

        return {
            "local_video_path": local_mp4,
            "local_thumbnail_path": local_thumb,
            "drive_video_path": drive_mp4
        }

    def load_all_jobs(self) -> List[Dict[str, Any]]:
        """
        Sistem açıldığında hem yerel hem Drive üzerindeki geçmiş job'ları yükler.
        Böylece Colab kapansa bile state korunur.
        """
        jobs = {}

        # 1. Drive'dan oku (varsa)
        if self.drive_mounted and os.path.exists(settings.DRIVE_JOBS_DIR):
            for entry in os.listdir(settings.DRIVE_JOBS_DIR):
                job_json_path = os.path.join(settings.DRIVE_JOBS_DIR, entry, "job.json")
                if os.path.isfile(job_json_path):
                    try:
                        with open(job_json_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            jobs[data["id"]] = data
                    except Exception:
                        pass

        # 2. Yerel dizinden oku (yereldeki güncellemeleri ezmesin)
        if os.path.exists(settings.LOCAL_JOBS_DIR):
            for entry in os.listdir(settings.LOCAL_JOBS_DIR):
                job_json_path = os.path.join(settings.LOCAL_JOBS_DIR, entry, "job.json")
                if os.path.isfile(job_json_path):
                    try:
                        with open(job_json_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            jobs[data["id"]] = data
                    except Exception:
                        pass

        # Tarihe göre sırala (en yeni en başta)
        job_list = list(jobs.values())
        job_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return job_list


# Singleton instance
storage = StorageManager()
