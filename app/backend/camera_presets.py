"""
Camera Presets Engine for LTX-2.5 Video Generation
LTX-2.5 için sinematik kamera hareketlerini kontrollü prompt enjeksiyonuyla uygular.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel

class CameraPreset(BaseModel):
    id: str
    name: str
    name_tr: str
    description: str
    category: str
    prompt_template: str
    motion_bias: float = 0.5  # 0.0 - 1.0


CAMERA_PRESETS: Dict[str, CameraPreset] = {
    "auto": CameraPreset(
        id="auto",
        name="Auto (Prompt Directed)",
        name_tr="✨ Otomatik (Prompt Güdümlü / Serbest)",
        description="Camera motion is inferred naturally from your prompt or chosen dynamically by the AI model.",
        category="Smart",
        prompt_template="Cinematic camera motion dynamically tailored to the scene flow.",
        motion_bias=0.5
    ),
    "static": CameraPreset(
        id="static",
        name="Static Locked-off",
        name_tr="Sabit Kamera",
        description="Camera remains stationary on a tripod, capturing subtle natural subject motion.",
        category="Tripod",
        prompt_template="Static shot, locked-off tripod camera, motionless framing with subtle natural movement within the scene.",
        motion_bias=0.2
    ),
    "dolly_in": CameraPreset(
        id="dolly_in",
        name="Dolly In",
        name_tr="Dolly İleri (Yaklaşma)",
        description="Smooth cinematic dolly-in pushing forward toward the subject.",
        category="Dolly",
        prompt_template="The camera performs a smooth, steady cinematic dolly-in pushing smoothly forward toward the subject.",
        motion_bias=0.5
    ),
    "dolly_out": CameraPreset(
        id="dolly_out",
        name="Dolly Out",
        name_tr="Dolly Geri (Uzaklaşma)",
        description="Smooth cinematic dolly-out pulling gently backward from the subject.",
        category="Dolly",
        prompt_template="The camera performs a smooth cinematic dolly-out pulling gently backward, revealing more of the environment.",
        motion_bias=0.5
    ),
    "truck_left": CameraPreset(
        id="truck_left",
        name="Truck Left",
        name_tr="Kamera Sola Kayma",
        description="Camera translates horizontally to the left on a track.",
        category="Tracking",
        prompt_template="The camera smoothly trucks horizontally to the left along a slider track.",
        motion_bias=0.5
    ),
    "truck_right": CameraPreset(
        id="truck_right",
        name="Truck Right",
        name_tr="Kamera Sağa Kayma",
        description="Camera translates horizontally to the right on a track.",
        category="Tracking",
        prompt_template="The camera smoothly trucks horizontally to the right along a slider track.",
        motion_bias=0.5
    ),
    "pan_left": CameraPreset(
        id="pan_left",
        name="Pan Left",
        name_tr="Pan Sola Dönüş",
        description="Camera pivots horizontally to the left.",
        category="Pan/Tilt",
        prompt_template="Cinematic slow pan left, rotating the perspective smoothly across the scene.",
        motion_bias=0.4
    ),
    "pan_right": CameraPreset(
        id="pan_right",
        name="Pan Right",
        name_tr="Pan Sağa Dönüş",
        description="Camera pivots horizontally to the right.",
        category="Pan/Tilt",
        prompt_template="Cinematic slow pan right, rotating the perspective smoothly across the scene.",
        motion_bias=0.4
    ),
    "tilt_up": CameraPreset(
        id="tilt_up",
        name="Tilt Up",
        name_tr="Tilt Yukarı Bakış",
        description="Camera tilts upward vertically.",
        category="Pan/Tilt",
        prompt_template="Cinematic tilt up, elevating the view smoothly from bottom to top.",
        motion_bias=0.4
    ),
    "tilt_down": CameraPreset(
        id="tilt_down",
        name="Tilt Down",
        name_tr="Tilt Aşağı Bakış",
        description="Camera tilts downward vertically.",
        category="Pan/Tilt",
        prompt_template="Cinematic tilt down, gliding the perspective smoothly downward.",
        motion_bias=0.4
    ),
    "orbit_left": CameraPreset(
        id="orbit_left",
        name="Orbit Left",
        name_tr="Sola Yörünge (Orbit)",
        description="360-degree rotational arc around the subject moving left.",
        category="Orbit",
        prompt_template="The camera performs an elegant circular orbit to the left around the center subject.",
        motion_bias=0.6
    ),
    "orbit_right": CameraPreset(
        id="orbit_right",
        name="Orbit Right",
        name_tr="Sağa Yörünge (Orbit)",
        description="360-degree rotational arc around the subject moving right.",
        category="Orbit",
        prompt_template="The camera performs an elegant circular orbit to the right around the center subject.",
        motion_bias=0.6
    ),
    "zoom_in": CameraPreset(
        id="zoom_in",
        name="Optical Zoom In",
        name_tr="Optik Zoom İleri",
        description="Lens focal length zooms inward on the subject.",
        category="Zoom",
        prompt_template="Slow cinematic lens zoom-in, intensifying visual intimacy without shifting camera position.",
        motion_bias=0.4
    ),
    "zoom_out": CameraPreset(
        id="zoom_out",
        name="Optical Zoom Out",
        name_tr="Optik Zoom Geri",
        description="Lens focal length zooms outward revealing context.",
        category="Zoom",
        prompt_template="Slow cinematic lens zoom-out, widening the frame smoothly to reveal surroundings.",
        motion_bias=0.4
    ),
    "handheld": CameraPreset(
        id="handheld",
        name="Handheld Organic",
        name_tr="Elde Çekim (Organik)",
        description="Natural organic handheld camera with realistic micro-shakes.",
        category="Dynamic",
        prompt_template="Authentic organic handheld camera motion, subtle natural breathing and micro-jitter, documentary realism.",
        motion_bias=0.6
    ),
    "fpv": CameraPreset(
        id="fpv",
        name="FPV Drone Dynamic",
        name_tr="FPV Drone Hızlı Uçuş",
        description="Fast dynamic first-person perspective fly-through.",
        category="Dynamic",
        prompt_template="Dynamic FPV drone shot sweeping rapidly and smoothly through the environment with cinematic banking.",
        motion_bias=0.8
    ),
    "crane_up": CameraPreset(
        id="crane_up",
        name="Crane Up (Jib)",
        name_tr="Vinç / Crane Yukarı",
        description="Camera rises vertically on a jib arm high above the subject.",
        category="Crane",
        prompt_template="Sweeping crane shot ascending high above the scene, moving upward in a majestic arc.",
        motion_bias=0.6
    ),
    "crane_down": CameraPreset(
        id="crane_down",
        name="Crane Down (Jib)",
        name_tr="Vinç / Crane Aşağı",
        description="Camera swoops down from above towards ground level.",
        category="Crane",
        prompt_template="Sweeping crane shot descending gracefully from an overhead vantage point towards ground level.",
        motion_bias=0.6
    )
}


def get_all_presets() -> List[CameraPreset]:
    """Tüm kamera presetlerini liste olarak döner."""
    return list(CAMERA_PRESETS.values())


def apply_camera_preset(
    base_prompt: str,
    camera_id: Optional[str] = None,
    preserve_identity: bool = True
) -> str:
    """
    Kullanıcı promptuna kamera hareketini ve kompozisyon koruma kurallarını ekler.
    """
    clean_prompt = base_prompt.strip()
    if not camera_id or camera_id == "auto" or camera_id not in CAMERA_PRESETS:
        # Otomatik mod: Kullanıcının promptundaki kamera talimatını koru, yapay zorlama yapma
        if preserve_identity:
            suffix = "Natural coherent motion, consistent character identity, photorealistic, pristine composition."
            return f"{clean_prompt} {suffix}" if clean_prompt.endswith(".") else f"{clean_prompt}. {suffix}"
        return clean_prompt

    if camera_id == "static":
        if preserve_identity:
            suffix = "Static locked-off shot, consistent character identity, photorealistic, pristine composition."
            return f"{clean_prompt} {suffix}" if clean_prompt.endswith(".") else f"{clean_prompt}. {suffix}"
        return f"{clean_prompt}. Static locked-off tripod shot."

    preset = CAMERA_PRESETS[camera_id]
    suffix = preset.prompt_template

    if preserve_identity:
        suffix += " while maintaining strict subject identity, appearance, and coherent scene structure."

    if clean_prompt.endswith("."):
        return f"{clean_prompt} {suffix}"
    else:
        return f"{clean_prompt}. {suffix}"
