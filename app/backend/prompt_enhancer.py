"""
Prompt Enhancer for LTX-2.5 Video Generation
LTX-2.5 Gemma 4 12B encoder'ı için promptları sinematik derinlik, ışık ve doku detaylarıyla zenginleştirir.
"""

import re
from typing import Dict, Any

# Temel Türkçe -> İngilizce basit anahtar sözcük eşleştirmeleri (gerekirse)
TR_EN_KEYWORDS = {
    "kadın": "a young woman",
    "kız": "a young woman",
    "adam": "a man",
    "erkek": "a man",
    "gülümsüyor": "gently smiling",
    "yürüyor": "walking gracefully",
    "koşuyor": "running dynamically",
    "bakıyor": "gazing with expressive eyes",
    "yağmur": "cinematic rainfall with glistening wet surfaces",
    "gece": "nighttime ambiance, neon reflections",
    "sokak": "urban city street",
    "sisli": "atmospheric misty haze, volumetric lighting",
    "güneş": "golden hour sunlight, warm lens flare",
    "orman": "lush detailed forest, dappled shadows",
    "deniz": "gentle ocean waves, sparkling water surface",
}

CINEMATIC_MODIFIERS = [
    "masterpiece cinematography",
    "photorealistic textures and lifelike skin pores",
    "subtle natural motion and organic fluid movement",
    "35mm film aesthetic, shallow depth of field with soft bokeh",
    "volumetric natural lighting, dynamic range, 8k resolution"
]

def enhance_prompt(prompt: str, style: str = "cinematic") -> str:
    """
    Kullanıcı promptunu LTX-2.5 için optimize edilmiş sinematik bir açıklamayla zenginleştirir.
    """
    clean = prompt.strip()
    if not clean:
        return clean

    enhanced = clean

    # Türkçe anahtar kelimeler varsa tamamlayıcı terimler ekle
    lower_prompt = clean.lower()
    for tr_word, en_trans in TR_EN_KEYWORDS.items():
        if re.search(r'\b' + re.escape(tr_word) + r'\b', lower_prompt):
            if en_trans.lower() not in enhanced.lower():
                enhanced += f", featuring {en_trans}"

    # Sinematik kalite ve aydınlatma eki
    if style == "cinematic":
        modifiers = ", ".join(CINEMATIC_MODIFIERS)
        if not enhanced.endswith("."):
            enhanced += f". Shot in {modifiers}."
        else:
            enhanced += f" Shot in {modifiers}."

    return enhanced
