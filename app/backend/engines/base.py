"""
Base Generation Engine Interface
Tüm video modelleri (LTX-2.5, MiniMax H3 vb.) için ortak soyut motor sınıfı.

ComfyUI ile HTTP haberleşmesi (prompt kuyruğa alma, geçmiş okuma, VRAM boşaltma,
çalışan işi kesme) burada tek noktada toplanmıştır; motorlar yalnızca kendi
workflow derleme mantığını uygular.
"""

import json
import time
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Set, Tuple
import config.settings as settings


# Eksik düğümler için hangi eklentinin kurulması gerektiğini söyleyen harita
NODE_PACKAGE_HINTS = {
    "UnetLoaderGGUF": "ComfyUI-GGUF (https://github.com/city96/ComfyUI-GGUF)",
    "CLIPLoaderGGUF": "ComfyUI-GGUF (https://github.com/city96/ComfyUI-GGUF)",
    "VHS_VideoCombine": "ComfyUI-VideoHelperSuite (https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite)",
    "LTXVConditioning": "ComfyUI-LTXVideo (https://github.com/Lightricks/ComfyUI-LTXVideo)",
    "LTXVImgToVideo": "ComfyUI-LTXVideo (https://github.com/Lightricks/ComfyUI-LTXVideo)",
    "LTXVEmptyLatentAudio": "ComfyUI-LTXVideo (LTX-2.5 ses desteği)",
    "LTXVConcatAVLatent": "ComfyUI-LTXVideo (LTX-2.5 ses desteği)",
    "LTXVSeparateAVLatent": "ComfyUI-LTXVideo (LTX-2.5 ses desteği)",
    "LTXVAudioVAEDecode": "ComfyUI-LTXVideo (LTX-2.5 ses desteği)",
    "MiniMaxH3ReferenceToVideo": "Güncel ComfyUI çekirdeği veya ComfyUI-H3-Multishot",
    "MiniMaxH3ImageToVideo": "Güncel ComfyUI çekirdeği veya ComfyUI-H3-Multishot",
}

# Motorların "varsa kullan" mantığıyla eklediği, düğüm kabul etmiyorsa
# sessizce kaldırılabilecek girdiler. (Zorunlu girdiler ASLA buraya konmaz.)
OPTIONAL_NODE_INPUTS = {
    "audio_vae",
    "device",
    "format",
    "weight_dtype",
    "ref_image_size",
    "first_frame",
    "strength",
    "conditioning_strength",
    "bit_depth",
}

# /object_info yanıtı için basit önbellek (ComfyUI yeniden başlatılınca yenilenir)
_OBJECT_INFO_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_OBJECT_INFO_TTL = 120.0


class BaseVideoEngine(ABC):
    """Video üretim motorları için taban sınıf."""

    def __init__(self, name: str):
        self.name = name

    # ------------------------------------------------------------------
    # Motorların uygulaması gereken soyut arayüz
    # ------------------------------------------------------------------
    @abstractmethod
    def build_workflow(
        self,
        job_params: Dict[str, Any],
        is_i2v: bool = False
    ) -> Dict[str, Any]:
        """
        Kullanıcı parametrelerinden ComfyUI API uyumlu prompt/workflow JSON'ı üretir.
        """
        pass

    @abstractmethod
    def calculate_dimensions_and_frames(
        self,
        aspect_ratio: str,
        duration: int,
        fps: int = 24,
        quality: str = "standard"
    ) -> Dict[str, int]:
        """
        Model kısıtlarına (ör. LTX-2.5 için mod 32 çözünürlük, 8n+1 frame) uygun boyut ve kare sayısını döner.
        """
        pass

    # ------------------------------------------------------------------
    # Ortak ComfyUI HTTP yardımcıları
    # ------------------------------------------------------------------
    def _request_json(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: float = 10.0
    ) -> Optional[Any]:
        """ComfyUI'ye GET/POST isteği atar; hata durumunda None döner."""
        url = f"{settings.COMFYUI_URL}{path}"
        try:
            if payload is None:
                req = urllib.request.Request(url, headers={'User-Agent': 'OzzyVision-Lab'})
            else:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json', 'User-Agent': 'OzzyVision-Lab'}
                )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read().decode('utf-8')
                if not body:
                    return {}
                try:
                    return json.loads(body)
                except json.JSONDecodeError:
                    return {}
        except Exception:
            return None

    def get_queue(self) -> Optional[Dict[str, Any]]:
        """ComfyUI /queue endpoint'inden aktif ve bekleyen iş durumunu çeker."""
        result = self._request_json("/queue", timeout=5)
        return result if isinstance(result, dict) else None

    def get_system_stats(self) -> Optional[Dict[str, Any]]:
        """ComfyUI /system_stats endpoint'inden sunucu sağlık ve GPU durumunu çeker."""
        result = self._request_json("/system_stats", timeout=5)
        return result if isinstance(result, dict) else None

    def free_memory(self, unload_models: bool = True) -> bool:
        """
        ComfyUI /free endpoint'ini çağırarak yüklü modelleri VRAM'den boşaltır.

        LTX-2.5 <-> MiniMax H3 geçişlerinde veya LoRA zinciri değiştiğinde ComfyUI
        eski model kopyasını bellekte tutmaya devam ettiği için yeni kombinasyon
        yüklenirken CUDA OOM alınır. Bu çağrı o kopyayı serbest bırakır.
        """
        result = self._request_json(
            "/free",
            payload={"unload_models": bool(unload_models), "free_memory": True},
            timeout=30
        )
        return result is not None

    def interrupt(self) -> bool:
        """ComfyUI üzerinde çalışmakta olan işi keser (iptal için)."""
        result = self._request_json("/interrupt", payload={}, timeout=10)
        return result is not None

    def delete_from_queue(self, prompt_id: str) -> bool:
        """Henüz başlamamış bir promptu ComfyUI kuyruğundan siler."""
        result = self._request_json("/queue", payload={"delete": [prompt_id]}, timeout=10)
        return result is not None

    def queue_prompt(self, workflow: Dict[str, Any], client_id: str) -> Optional[str]:
        """
        Hazırlanan workflow'u ComfyUI /prompt endpoint'ine post eder ve prompt_id döner.
        Hata durumunda ComfyUI'nin döndürdüğü gerçek düğüm hatasını RuntimeError olarak fırlatır.
        """
        payload = json.dumps({"prompt": workflow, "client_id": client_id}).encode('utf-8')
        req = urllib.request.Request(
            f"{settings.COMFYUI_URL}/prompt",
            data=payload,
            headers={'Content-Type': 'application/json'}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result.get("prompt_id")
        except urllib.error.HTTPError as he:
            raise RuntimeError(self._format_http_error(he))
        except urllib.error.URLError as ue:
            print(f"[{self.name}] ComfyUI connection error: {ue}")
            if settings.IS_COLAB or not getattr(settings, "DEV_MOCK_MODE", False):
                raise RuntimeError(f"ComfyUI sunucusuna erişilemiyor ({settings.COMFYUI_URL}): {ue.reason}")
            return None
        except Exception as e:
            print(f"[{self.name}] ComfyUI queue error: {e}")
            raise

    def _format_http_error(self, he: urllib.error.HTTPError) -> str:
        """ComfyUI'nin JSON hata gövdesini okunabilir tek satıra çevirir."""
        err_body = he.read().decode('utf-8', errors='ignore')
        err_msg = f"ComfyUI HTTP {he.code}"
        try:
            err_json = json.loads(err_body)
            error_details = []
            for nid, nerr in (err_json.get("node_errors") or {}).items():
                for e in nerr.get("errors", []):
                    cls = e.get("class_type", "")
                    msg = e.get("message", "")
                    details = e.get("details", "")
                    error_details.append(f"Düğüm {nid} ({cls}): {msg} {details}".strip())
            if error_details:
                err_msg = f"ComfyUI Düğüm Hatası: {'; '.join(error_details)}"
            elif "error" in err_json:
                err_info = err_json["error"]
                if isinstance(err_info, dict):
                    err_msg = f"ComfyUI Hatası: {err_info.get('message') or err_info.get('type') or err_body}"
                else:
                    err_msg = f"ComfyUI Hatası: {err_info}"
        except Exception:
            if err_body:
                err_msg = f"ComfyUI HTTP {he.code}: {err_body[:250]}"
        print(f"[{self.name}] ComfyUI rejected prompt: {err_msg}")
        return err_msg

    def get_history(self, prompt_id: str) -> Optional[Dict[str, Any]]:
        """ComfyUI /history/{prompt_id} endpoint'inden iş durumunu ve çıktılarını çeker."""
        result = self._request_json(f"/history/{prompt_id}", timeout=10)
        return result if isinstance(result, dict) else None

    # ------------------------------------------------------------------
    # Workflow doğrulama (eksik custom node / uyumsuz girdi tespiti)
    # ------------------------------------------------------------------
    def get_object_info(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """
        ComfyUI'de kurulu tüm düğümlerin şemasını (/object_info) önbellekli olarak döner.
        ComfyUI kapalıysa None döner ve doğrulama atlanır.
        """
        now = time.time()
        if not force and _OBJECT_INFO_CACHE["data"] is not None:
            if (now - _OBJECT_INFO_CACHE["ts"]) < _OBJECT_INFO_TTL:
                return _OBJECT_INFO_CACHE["data"]

        data = self._request_json("/object_info", timeout=30)
        if isinstance(data, dict) and data:
            _OBJECT_INFO_CACHE["data"] = data
            _OBJECT_INFO_CACHE["ts"] = now
            return data
        return None

    @staticmethod
    def _accepted_inputs(node_schema: Dict[str, Any]) -> Set[str]:
        """Bir düğümün kabul ettiği tüm girdi adlarını (required + optional) döner."""
        names: Set[str] = set()
        spec = node_schema.get("input") or {}
        for section in ("required", "optional", "hidden"):
            block = spec.get(section) or {}
            if isinstance(block, dict):
                names.update(block.keys())
        return names

    def validate_workflow(self, workflow: Dict[str, Any]) -> Tuple[Dict[str, Any], list]:
        """
        Workflow'u ComfyUI'nin gerçek düğüm şemasına göre doğrular.

        - Kurulu olmayan düğüm sınıfları RuntimeError ile, hangi eklentinin
          kurulması gerektiğini söyleyerek raporlanır (ComfyUI'nin şifreli
          "Prompt has no outputs" / HTTP 400 hatası yerine).
        - Motorun "varsa kullanılsın" diye eklediği isteğe bağlı girdiler
          (ör. audio_vae, device, format) düğüm kabul etmiyorsa kaldırılır.

        ComfyUI erişilemiyorsa doğrulama sessizce atlanır.
        Döner: (temizlenmiş_workflow, uyarılar)
        """
        object_info = self.get_object_info()
        if not object_info:
            return workflow, []

        warnings = []
        missing_classes = []

        for node_id, node in workflow.items():
            cls = node.get("class_type")
            if not cls:
                continue
            schema = object_info.get(cls)
            if schema is None:
                missing_classes.append(cls)
                continue

            accepted = self._accepted_inputs(schema)
            if not accepted:
                continue

            for key in list((node.get("inputs") or {}).keys()):
                if key in accepted:
                    continue
                # Dinamik/şablonlu girdiler (ör. ref_images.ref_image_0) şemada görünmez
                if "." in key:
                    continue
                if key in OPTIONAL_NODE_INPUTS:
                    node["inputs"].pop(key, None)
                    warnings.append(f"Düğüm {node_id} ({cls}): '{key}' girdisi desteklenmiyor, kaldırıldı.")

        if missing_classes:
            details = []
            for cls in sorted(set(missing_classes)):
                hint = NODE_PACKAGE_HINTS.get(cls)
                details.append(f"{cls}" + (f" -> {hint}" if hint else ""))
            raise RuntimeError(
                "ComfyUI'de gerekli düğümler kurulu değil: " + "; ".join(details) +
                ". İlgili custom node paketini kurup ComfyUI'yi yeniden başlatın."
            )

        return workflow, warnings
