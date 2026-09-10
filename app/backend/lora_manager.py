"""
OzzyVision-Lab - LoRA Yöneticisi ve İndirme Servisi
Hem LTX-2.5 hem de MiniMax H3 için LoRA modellerini listeler,
Google Colab'in gigabit hızındaki interneti ile Hugging Face / Civitai üzerinden doğrudan Drive'a indirir.
"""

import os
import re
import sys
import time
import uuid
import shutil
import urllib.parse
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests

import config.settings as settings

# Thread-safe indirme görevleri takip tablosu
_download_tasks: Dict[str, Dict[str, Any]] = {}
_tasks_lock = threading.Lock()


def get_lora_directories() -> List[str]:
    """Sistemde LoRA dosyalarının aranacağı dizinleri döner."""
    dirs = []
    # 1. Aktif lora dizini (Drive veya local)
    active_dir = getattr(settings, "ACTIVE_LORAS_DIR", None)
    if active_dir:
        dirs.append(active_dir)
        os.makedirs(active_dir, exist_ok=True)

    # 2. ComfyUI lora dizini
    comfy_dir = getattr(settings, "COMFYUI_LORAS_DIR", None)
    if comfy_dir and comfy_dir != active_dir:
        dirs.append(comfy_dir)
        os.makedirs(comfy_dir, exist_ok=True)

    return dirs


def list_available_loras() -> List[Dict[str, Any]]:
    """
    Kayıtlı tüm LoRA dosyalarını (.safetensors, .pt, .bin, .gguf) listeler.
    """
    supported_extensions = {".safetensors", ".pt", ".bin", ".gguf"}
    found_loras: Dict[str, Dict[str, Any]] = {}

    for lora_dir in get_lora_directories():
        p = Path(lora_dir)
        if not p.exists() or not p.is_dir():
            continue

        try:
            for item in p.rglob("*"):
                if item.is_file() and item.suffix.lower() in supported_extensions:
                    # Ana dizine göre bağıl ad (veya dosya adı)
                    rel_name = item.name
                    if rel_name not in found_loras:
                        size_bytes = item.stat().st_size
                        found_loras[rel_name] = {
                            "name": rel_name,
                            "size_mb": round(size_bytes / (1024 * 1024), 2),
                            "path": str(item.resolve()),
                            "modified_at": item.stat().st_mtime
                        }
        except Exception as e:
            print(f"[LoRAManager] Dizin taranırken hata ({lora_dir}): {e}")

    # Değiştirilme tarihine göre yeniden eskiye sırala
    sorted_loras = sorted(
        list(found_loras.values()),
        key=lambda x: x.get("modified_at", 0),
        reverse=True
    )
    return sorted_loras


def _extract_filename_from_headers(response: requests.Response, default_name: str) -> str:
    """Content-Disposition başlığından veya URL'den dosya adını çıkarır."""
    cd = response.headers.get("content-disposition", "")
    if cd:
        fname_match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)["\']?', cd, re.IGNORECASE)
        if fname_match:
            fname = urllib.parse.unquote(fname_match.group(1).strip())
            if fname:
                return os.path.basename(fname)
    return default_name


def _clean_hf_url(url: str) -> str:
    """Hugging Face blob linklerini doğrudan indirme (resolve) linkine dönüştürür."""
    if "huggingface.co" in url and "/blob/" in url:
        url = url.replace("/blob/", "/resolve/")
    return url


def start_lora_download(
    url: Optional[str] = None,
    filename: Optional[str] = None,
    hf_repo: Optional[str] = None,
    hf_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Colab'in yüksek hızlı internetini kullanarak arka planda LoRA indirme başlatır.
    """
    task_id = uuid.uuid4().hex[:8]

    # Başlangıç dosya adı belirleme
    target_name = (filename or "").strip()
    if not target_name:
        if hf_file:
            target_name = os.path.basename(hf_file)
        elif url:
            parsed_path = urllib.parse.urlparse(url).path
            base = os.path.basename(parsed_path)
            if base and ("." in base):
                target_name = base
            else:
                target_name = f"lora_{task_id}.safetensors"
        else:
            target_name = f"lora_{task_id}.safetensors"

    if not any(target_name.endswith(ext) for ext in [".safetensors", ".pt", ".bin", ".gguf"]):
        target_name += ".safetensors"

    task = {
        "id": task_id,
        "url": url,
        "filename": target_name,
        "hf_repo": hf_repo,
        "hf_file": hf_file,
        "status": "pending",
        "progress": 0.0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "speed_mbps": 0.0,
        "error": None,
        "target_path": None,
        "created_at": time.time(),
        "completed_at": None
    }

    with _tasks_lock:
        _download_tasks[task_id] = task

    thread = threading.Thread(
        target=_download_worker,
        args=(task_id,),
        daemon=True
    )
    thread.start()

    return task


def _download_worker(task_id: str):
    """Arka plan indirme iş parçacığı."""
    with _tasks_lock:
        task = _download_tasks.get(task_id)
        if not task:
            return

    target_dir = getattr(settings, "ACTIVE_LORAS_DIR", None) or get_lora_directories()[0]
    os.makedirs(target_dir, exist_ok=True)

    url = task.get("url")
    hf_repo = task.get("hf_repo")
    hf_file = task.get("hf_file")
    filename = task.get("filename")

    target_file_path = os.path.join(target_dir, filename)
    task["target_path"] = target_file_path

    try:
        task["status"] = "downloading"

        # 1. YÖNTEM: Hugging Face Hub (hf_repo ve hf_file verilmişse)
        if hf_repo and hf_file:
            try:
                from huggingface_hub import hf_hub_download
                token = settings.HF_TOKEN if getattr(settings, "HF_TOKEN", "") else None
                downloaded = hf_hub_download(
                    repo_id=hf_repo,
                    filename=hf_file,
                    local_dir=target_dir,
                    token=token
                )
                if os.path.exists(downloaded) and os.path.abspath(downloaded) != os.path.abspath(target_file_path):
                    shutil.move(downloaded, target_file_path)

                final_size = os.path.getsize(target_file_path)
                task["total_bytes"] = final_size
                task["downloaded_bytes"] = final_size
                task["progress"] = 100.0
                task["status"] = "completed"
                task["completed_at"] = time.time()
                _sync_to_comfyui(target_file_path)
                return
            except Exception as e:
                print(f"[LoRAManager] hf_hub_download denenirken hata ({e}), URL indirmesine geçiliyor...")

        # 2. YÖNTEM: Doğrudan HTTP/HTTPS Akışlı İndirme (Colab İnterneti)
        if not url:
            raise ValueError("İndirme için geçerli bir URL veya Hugging Face repo bilgisi sağlanmalıdır.")

        clean_url = _clean_hf_url(url)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if "huggingface.co" in clean_url and getattr(settings, "HF_TOKEN", ""):
            headers["Authorization"] = f"Bearer {settings.HF_TOKEN}"
        if "civitai.com" in clean_url and getattr(settings, "CIVITAI_TOKEN", ""):
            headers["Authorization"] = f"Bearer {settings.CIVITAI_TOKEN}"

        with requests.get(clean_url, headers=headers, stream=True, timeout=30, allow_redirects=True) as resp:
            resp.raise_for_status()

            # Kimlik doğrulama gerektiren bağlantılar model yerine HTML/JSON döner.
            # Bunu sessizce ".safetensors" olarak kaydetmek yerine anlaşılır hata ver.
            content_type = (resp.headers.get("content-type") or "").lower()
            if content_type.startswith(("text/html", "application/json")):
                raise ValueError(
                    "Bağlantı model dosyası yerine bir web sayfası döndürdü. "
                    "Civitai için API token (CIVITAI_TOKEN), Hugging Face gated repo için HF_TOKEN gerekebilir "
                    "veya doğrudan indirme (resolve) bağlantısını kullanın."
                )

            # Gerçek dosya adını başlıklardan güncelle
            real_name = _extract_filename_from_headers(resp, filename)
            if real_name != filename:
                task["filename"] = real_name
                target_file_path = os.path.join(target_dir, real_name)
                task["target_path"] = target_file_path

            total_len = int(resp.headers.get("content-length", 0))
            task["total_bytes"] = total_len

            temp_path = target_file_path + ".downloading"
            downloaded = 0
            start_time = time.time()
            last_speed_check = start_time
            last_downloaded = 0

            with open(temp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):  # 1MB parçalar
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    task["downloaded_bytes"] = downloaded

                    if total_len > 0:
                        task["progress"] = round((downloaded / total_len) * 100, 1)

                    now = time.time()
                    elapsed = now - last_speed_check
                    if elapsed >= 0.5:
                        speed = (downloaded - last_downloaded) / elapsed / (1024 * 1024)
                        task["speed_mbps"] = round(speed, 2)
                        last_speed_check = now
                        last_downloaded = downloaded

            if os.path.exists(temp_path):
                actual_size = os.path.getsize(temp_path)
                if total_len > 0 and actual_size < total_len:
                    raise IOError(
                        f"İndirme yarıda kesildi ({actual_size} / {total_len} bayt). Lütfen tekrar deneyin."
                    )
                if actual_size < 1024:
                    raise ValueError("İndirilen dosya geçersiz veya boş (1 KB'den küçük).")
                if os.path.exists(target_file_path):
                    os.remove(target_file_path)
                os.rename(temp_path, target_file_path)

            task["progress"] = 100.0
            task["status"] = "completed"
            task["completed_at"] = time.time()
            _sync_to_comfyui(target_file_path)

    except Exception as exc:
        print(f"[LoRAManager] İndirme hatası: {exc}")
        task["status"] = "failed"
        task["error"] = str(exc)
        temp_path = target_file_path + ".downloading"
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def _sync_to_comfyui(target_file_path: str) -> bool:
    """
    Bir LoRA dosyasını ComfyUI'nin loras dizinine bağlar (symlink) veya kopyalar.
    ComfyUI yalnızca kendi `models/loras` arama yolundaki dosyaları kabul ettiği için,
    Drive'daki bir LoRA bu adım yapılmadan iş akışında "value not in list" hatası verir.
    """
    comfy_dir = getattr(settings, "COMFYUI_LORAS_DIR", None)
    if not comfy_dir or not os.path.exists(target_file_path):
        return False

    os.makedirs(comfy_dir, exist_ok=True)
    comfy_target = os.path.join(comfy_dir, os.path.basename(target_file_path))

    # Kaynak ile hedef aynı dosyaysa (aynı yol veya dizin symlink'i) iş yok
    try:
        if os.path.exists(comfy_target) and os.path.samefile(target_file_path, comfy_target):
            return True
    except OSError:
        pass
    if os.path.abspath(target_file_path) == os.path.abspath(comfy_target):
        return True

    # Kırık symlink'ler os.path.exists ile görünmez; lexists ile temizle
    if os.path.lexists(comfy_target) and not os.path.exists(comfy_target):
        try:
            os.remove(comfy_target)
        except OSError:
            pass

    if not os.path.lexists(comfy_target):
        try:
            os.symlink(target_file_path, comfy_target)
            return True
        except (OSError, NotImplementedError, AttributeError):
            # Windows'ta symlink yetkisi olmayabilir -> kopyala
            pass

        try:
            shutil.copy2(target_file_path, comfy_target)
            return True
        except Exception as e:
            print(f"[LoRAManager] ComfyUI eşitleme uyarısı: {e}")
            return False

    return True


def resolve_lora_path(lora_name: str) -> Optional[str]:
    """Verilen LoRA adının diskteki gerçek yolunu bulur (alt dizinler dahil)."""
    clean_name = lora_name.replace("\\", "/").strip("/")
    base_name = os.path.basename(clean_name)

    for lora_dir in get_lora_directories():
        direct = os.path.join(lora_dir, clean_name)
        if os.path.isfile(direct):
            return direct
        flat = os.path.join(lora_dir, base_name)
        if os.path.isfile(flat):
            return flat

    # Alt dizinlerde derin arama (indirilen LoRA'lar repo alt klasörüne düşebilir)
    for lora_dir in get_lora_directories():
        p = Path(lora_dir)
        if not p.is_dir():
            continue
        try:
            for item in p.rglob(base_name):
                if item.is_file():
                    return str(item)
        except OSError:
            continue

    return None


def ensure_loras_available(lora_names: List[str]) -> Dict[str, Any]:
    """
    Bir iş kuyruğa verilmeden önce, istenen LoRA'ların ComfyUI arama yolunda
    hazır olduğunu garanti eder.

    Döner: {"ok": bool, "resolved": {istenen_ad: comfy_adi}, "missing": [...]}
    """
    resolved: Dict[str, str] = {}
    missing: List[str] = []

    for name in lora_names:
        if not name:
            continue
        path = resolve_lora_path(name)
        if not path:
            missing.append(name)
            continue
        if _sync_to_comfyui(path):
            resolved[name] = os.path.basename(path)
        else:
            missing.append(name)

    return {"ok": not missing, "resolved": resolved, "missing": missing}


def get_download_status(task_id: str) -> Optional[Dict[str, Any]]:
    """Belirli bir indirme görevinin durumunu döner."""
    with _tasks_lock:
        task = _download_tasks.get(task_id)
        return dict(task) if task else None


def get_all_downloads() -> List[Dict[str, Any]]:
    """Tüm indirme görevlerini en yeniden en eskiye listeler."""
    with _tasks_lock:
        tasks = [dict(t) for t in _download_tasks.values()]
    return sorted(tasks, key=lambda t: t.get("created_at", 0), reverse=True)


def delete_lora(filename: str) -> bool:
    """Belirtilen LoRA dosyasını sistemden siler."""
    deleted = False
    clean_name = os.path.basename(filename)

    for d in get_lora_directories():
        fpath = os.path.join(d, clean_name)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
                deleted = True
            except Exception as e:
                print(f"[LoRAManager] Dosya silinemedi ({fpath}): {e}")

    return deleted
