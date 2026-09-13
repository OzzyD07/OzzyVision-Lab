"""
GPU / sistem belleği ölçümü ve bellek hatalarının sınıflandırılması.

"OOM" tek bir şey değildir:
  - gpu_oom : CUDA belleği yetmedi. ComfyUI ayakta kalır, düğüm hatası döner.
  - ram_oom : Sistem RAM'i doldu. İşletim sistemi ComfyUI sürecini öldürür;
              VRAM bu sırada dolu görünmez.
  - crash   : Süreç başka bir nedenle kapandı.
  - other   : Bellekle ilgisi olmayan hata (ör. "CUDA error: illegal memory access").
"""

import re
import shutil
import subprocess
from typing import Any, Dict, Optional, Tuple

GIB = 1024 ** 3

# Süreç öldüğünde son ölçümde RAM bu oranın üstündeyse sebep RAM kabul edilir.
# Ölçümler ~2 sn arayla alındığı için %100'ü görmek beklenmez.
RAM_PRESSURE_RATIO = 0.85

# Sıra önemlidir:
#  1) Açıkça CPU belleğine ait mesajlar (PyTorch CPU hatası da "tried to allocate" içerir)
#  2) GPU mesajları
#  3) Genel RAM mesajları ("memoryerror", "OutOfMemoryError" içinde de geçer; bu yüzden GPU'dan sonra)
_CPU_ALLOC_MARKERS = (
    "defaultcpuallocator",
    "can't allocate memory",
    "cannot allocate memory",
)

_GPU_MARKERS = (
    "cuda out of memory",
    "outofmemoryerror",
    "allocation on device",
    "out of memory on your gpu",
    "tried to allocate",
    "_alloc_failed",
)

_RAM_MARKERS = (
    "memoryerror",
    "not enough memory",
    "killed",
)

GPU_OOM = "gpu_oom"
RAM_OOM = "ram_oom"
CRASH = "crash"
OTHER = "other"


def _gb(value: Any) -> Optional[float]:
    try:
        return round(float(value) / GIB, 1)
    except (TypeError, ValueError):
        return None


def parse_comfy_stats(stats: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """ComfyUI /system_stats yanıtını sade bir ölçüme çevirir."""
    if not isinstance(stats, dict):
        return None

    sample: Dict[str, Any] = {}

    system = stats.get("system") or {}
    ram_total = _gb(system.get("ram_total"))
    ram_free = _gb(system.get("ram_free"))
    if ram_total:
        sample["ram_total_gb"] = ram_total
        if ram_free is not None:
            sample["ram_used_gb"] = round(ram_total - ram_free, 1)

    cuda = next(
        (d for d in (stats.get("devices") or []) if str(d.get("type", "")).lower() == "cuda"),
        None
    )
    if cuda:
        name = str(cuda.get("name", ""))
        # "cuda:0 NVIDIA A100-SXM4-80GB : cudaMallocAsync" -> "NVIDIA A100-SXM4-80GB"
        name = re.sub(r"^cuda:\d+\s*", "", name).split(" : ")[0].strip()
        sample["gpu_name"] = name or None
        vram_total = _gb(cuda.get("vram_total"))
        vram_free = _gb(cuda.get("vram_free"))
        if vram_total:
            sample["vram_total_gb"] = vram_total
            if vram_free is not None:
                sample["vram_used_gb"] = round(vram_total - vram_free, 1)

    return sample or None


def query_nvidia_smi() -> Optional[Dict[str, Any]]:
    """
    ComfyUI kapalıyken GPU bilgisini nvidia-smi'den okur.
    torch kullanılmaz: torch.cuda çağrıları backend sürecinde kalıcı bir CUDA
    bağlamı açıp hem VRAM'den hem sistem RAM'inden pay alır.
    """
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip().splitlines()
    except Exception:
        return None
    if not out:
        return None
    parts = [p.strip() for p in out[0].split(",")]
    if len(parts) < 3:
        return None
    try:
        return {
            "gpu_name": parts[0],
            "vram_total_gb": round(float(parts[1]) / 1024, 1),
            "vram_used_gb": round(float(parts[2]) / 1024, 1),
        }
    except ValueError:
        return None


def current_snapshot(engine) -> Tuple[bool, Dict[str, Any]]:
    """
    Anlık kaynak durumu: önce ComfyUI (VRAM + RAM), kapalıysa nvidia-smi (yalnız VRAM).
    Döner: (comfy_online, gpu_bilgisi)
    """
    stats = engine.get_system_stats()
    sample = parse_comfy_stats(stats) if stats is not None else None
    if not sample or not sample.get("vram_total_gb"):
        smi = query_nvidia_smi()
        if smi:
            sample = {**smi, **{k: v for k, v in (sample or {}).items() if k.startswith("ram_")}}
    sample = sample or {}
    gpu = {
        "available": bool(sample.get("vram_total_gb")),
        "name": sample.get("gpu_name") or "GPU yok",
        "vram_gb": sample.get("vram_total_gb", 0),
        "vram_used_gb": sample.get("vram_used_gb", 0),
        "ram_gb": sample.get("ram_total_gb", 0),
        "ram_used_gb": sample.get("ram_used_gb", 0),
    }
    return stats is not None, gpu


def format_sample(sample: Optional[Dict[str, Any]]) -> str:
    if not sample:
        return "ölçüm yok"
    parts = []
    if sample.get("vram_total_gb"):
        parts.append(f"VRAM {sample.get('vram_used_gb', '?')}/{sample['vram_total_gb']} GB")
    if sample.get("ram_total_gb"):
        parts.append(f"RAM {sample.get('ram_used_gb', '?')}/{sample['ram_total_gb']} GB")
    return " · ".join(parts) if parts else "ölçüm yok"


def ram_pressure(sample: Optional[Dict[str, Any]]) -> Optional[float]:
    if not sample or not sample.get("ram_total_gb") or sample.get("ram_used_gb") is None:
        return None
    return sample["ram_used_gb"] / sample["ram_total_gb"]


def classify_failure(
    message: str,
    comfy_alive: bool = True,
    last_sample: Optional[Dict[str, Any]] = None
) -> str:
    """Bir iş hatasının türünü belirler."""
    low = (message or "").lower()

    if any(m in low for m in _CPU_ALLOC_MARKERS):
        return RAM_OOM
    if any(m in low for m in _GPU_MARKERS):
        return GPU_OOM
    if any(m in low for m in _RAM_MARKERS):
        return RAM_OOM

    if not comfy_alive:
        pressure = ram_pressure(last_sample)
        if pressure is not None and pressure >= RAM_PRESSURE_RATIO:
            return RAM_OOM
        return CRASH

    return OTHER


def parse_allocation(message: str) -> Tuple[Optional[str], Optional[str]]:
    """CUDA OOM mesajından istenen ve boş bellek miktarını çıkarır."""
    msg = message or ""
    # Yerel ayırıcı:     "Tried to allocate 2.00 GiB ... of which 1.25 GiB is free"
    # cudaMallocAsync:  "Requested : 12.00 GiB ... Free (according to CUDA): 1.25 GiB"
    wanted = (re.search(r"tried to allocate\s+([\d.]+\s*[KMG]i?B)", msg, re.IGNORECASE)
              or re.search(r"requested\s*:\s*([\d.]+\s*[KMG]i?B)", msg, re.IGNORECASE))
    # Özel (cudaMallocAsync) desen önce: genel desen "Requested : 12.00 GiB Free (...)" içindeki
    # "12.00 GiB Free" parçasını yanlışlıkla boş bellek sanar.
    free = (re.search(r"free\s*\(according to cuda\)\s*:\s*([\d.]+\s*[KMG]i?B)", msg, re.IGNORECASE)
            or re.search(r"of which\s+([\d.]+\s*[KMG]i?B)\s+(?:is\s+)?free", msg, re.IGNORECASE)
            or re.search(r"([\d.]+\s*[KMG]i?B)\s+(?:is\s+)?free", msg, re.IGNORECASE))
    return (wanted.group(1) if wanted else None, free.group(1) if free else None)
