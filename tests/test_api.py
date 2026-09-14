"""
FastAPI Backend & Kuyruk Birim Testleri
Tüm API endpoint'lerinin, kamera presetlerinin ve prompt enhancer'ın doğruluğunu kontrol eder.
"""

import sys
from pathlib import Path

# Windows console cp1254 unicode encode hatasını önlemek için stdout utf-8 yap
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
from app.backend.main import app
from app.backend.camera_presets import get_all_presets, apply_camera_preset
from app.backend.prompt_enhancer import enhance_prompt

client = TestClient(app)

def test_camera_presets():
    presets = get_all_presets()
    assert len(presets) >= 15, "En az 15 kamera preseti tanımlı olmalı"
    preset_ids = [p.id for p in presets]
    assert "static" in preset_ids
    assert "dolly_in" in preset_ids
    assert "orbit_left" in preset_ids
    assert "crane_up" in preset_ids

    applied = apply_camera_preset("A girl walking", "dolly_in", preserve_identity=True)
    assert "dolly-in" in applied
    assert "subject identity" in applied
    print("✅ test_camera_presets başarılı!")

def test_prompt_enhancer():
    orig = "kadın gülümsüyor"
    enhanced = enhance_prompt(orig)
    assert "a young woman" in enhanced.lower()
    assert "cinematography" in enhanced.lower()
    print("✅ test_prompt_enhancer başarılı!")

def test_api_status():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "gpu" in data
    assert "comfyui" in data
    assert "storage" in data
    print("✅ test_api_status başarılı!")

def test_api_presets():
    response = client.get("/api/presets/camera")
    assert response.status_code == 200
    data = response.json()
    assert "presets" in data
    assert len(data["presets"]) > 0
    print("✅ test_api_presets başarılı!")

def test_api_prompt_enhance():
    response = client.post("/api/prompt/enhance", json={"prompt": "futuristic city"})
    assert response.status_code == 200
    data = response.json()
    assert "enhanced" in data
    assert len(data["enhanced"]) > len("futuristic city")
    print("✅ test_api_prompt_enhance başarılı!")

def test_api_jobs_crud():
    # Job oluşturma
    create_resp = client.post("/api/jobs", json={
        "prompt": "Test video generation prompt",
        "aspect_ratio": "16:9",
        "duration": 3,
        "camera": "static",
        "quality": "draft"
    })
    assert create_resp.status_code == 200
    job = create_resp.json()["job"]
    job_id = job["id"]
    assert job["status"] in ["queued", "preparing", "generating"]

    # Job getirme
    get_resp = client.get(f"/api/jobs/{job_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["job"]["id"] == job_id

    # Job listeleme
    list_resp = client.get("/api/jobs")
    assert list_resp.status_code == 200
    assert any(j["id"] == job_id for j in list_resp.json()["jobs"])
    print("✅ test_api_jobs_crud başarılı!")

def test_mcp_endpoints():
    import base64
    import tempfile

    # 1. MCP initialize
    init_resp = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "initialize",
        "id": 1,
        "params": {}
    })
    assert init_resp.status_code == 200
    assert "protocolVersion" in init_resp.json()["result"]

    # 2. MCP tools/list
    tools_resp = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/list",
        "id": 2,
        "params": {}
    })
    assert tools_resp.status_code == 200
    tools = tools_resp.json()["result"]["tools"]
    tool_names = [t["name"] for t in tools]

    expected_tools = [
        "upload_asset", "generate_omni_video", "generate_video_from_image",
        "generate_video", "get_system_status", "enhance_prompt", "list_assets",
        "list_jobs", "get_job", "cancel_job", "retry_job", "reorder_job",
        "delete_job", "list_recent_videos", "list_presets"
    ]
    for exp in expected_tools:
        assert exp in tool_names, f"Araç '{exp}' MCP araç listesinde bulunamadı."

    # 3. upload_asset testi (Base64)
    b64_fake_png = base64.b64encode(b"FAKE_PNG_HEADER_DATA").decode("utf-8")
    up_resp = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 3,
        "params": {
            "name": "upload_asset",
            "arguments": {
                "base64_data": b64_fake_png,
                "filename": "mcp_char.png"
            }
        }
    })
    assert up_resp.status_code == 200
    res3 = up_resp.json()["result"]["structured"]
    assert res3["status"] == "success"
    assert res3["media_type"] == "image"
    uploaded_asset_id = res3["asset_id"]

    # 4. upload_asset testi (Yerel dosya yolu)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
        tmp_audio.write(b"RIFF_FAKE_WAV")
        tmp_audio_path = tmp_audio.name

    up_file_resp = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 4,
        "params": {
            "name": "upload_asset",
            "arguments": {
                "file_path": tmp_audio_path
            }
        }
    })
    assert up_file_resp.status_code == 200
    res4 = up_file_resp.json()["result"]["structured"]
    assert res4["status"] == "success"
    assert res4["media_type"] == "audio"
    uploaded_audio_id = res4["asset_id"]

    # 5. generate_omni_video testi (MiniMax H3)
    omni_resp = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 5,
        "params": {
            "name": "generate_omni_video",
            "arguments": {
                "prompt": "Character <Picture 1> talks with timbre <Audio 1>: <d>[Turkish] Merhaba!</d>",
                "images": [uploaded_asset_id],
                "audios": [uploaded_audio_id],
                "duration": 6,
                "aspect_ratio": "16:9",
                "ref_image_size": "max"
            }
        }
    })
    assert omni_resp.status_code == 200
    res5 = omni_resp.json()["result"]["structured"]
    assert res5["status"] == "success"
    assert res5["job"]["model"] == "minimax_h3"
    assert res5["job"]["ref_image_size"] == "max"
    omni_job_id = res5["job_id"]

    # 6. generate_video_from_image testi (Doğrudan yerel dosya yolu ile LTX-2.5)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_img:
        tmp_img.write(b"FAKE_JPEG_DATA")
        tmp_img_path = tmp_img.name

    i2v_resp = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 6,
        "params": {
            "name": "generate_video_from_image",
            "arguments": {
                "image_path": tmp_img_path,
                "prompt": "A girl turns around slowly",
                "camera": "dolly_in"
            }
        }
    })
    assert i2v_resp.status_code == 200
    res6 = i2v_resp.json()["result"]["structured"]
    assert res6["status"] == "success"
    assert res6["job"]["model"] == "ltx25"

    # 7. get_system_status testi
    status_resp = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 7,
        "params": {
            "name": "get_system_status",
            "arguments": {}
        }
    })
    assert status_resp.status_code == 200
    res7 = status_resp.json()["result"]["structured"]
    assert res7["status"] == "online"
    assert "gpu" in res7
    assert len(res7["supported_models"]) >= 2

    # 8. enhance_prompt testi
    enh_resp = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 8,
        "params": {
            "name": "enhance_prompt",
            "arguments": {"prompt": "neon cyberpunk car"}
        }
    })
    assert enh_resp.status_code == 200
    res8 = enh_resp.json()["result"]["structured"]
    assert len(res8["enhanced"]) > len("neon cyberpunk car")

    # Temizlik
    try:
        os.remove(tmp_audio_path)
        os.remove(tmp_img_path)
    except Exception:
        pass

    print("✅ test_mcp_endpoints (Gelişmiş Yükleme, MiniMax H3 Omni & Stüdyo Araçları) başarılı!")


def test_workflows():
    from app.backend.engines.ltx25.engine import LTX25Engine
    engine = LTX25Engine()

    # 1. T2V Sesli (Audio=True) Testi
    wf_t2v_audio = engine.build_workflow({"prompt": "A cinematic city", "fps": 24, "duration": 5, "audio": True}, is_i2v=False)
    p = wf_t2v_audio["prompt"]
    assert p["7"]["inputs"]["frame_rate"] == 24
    assert p["12"]["class_type"] == "VAELoader"
    assert p["13"]["class_type"] == "LTXVEmptyLatentAudio"
    assert p["14"]["class_type"] == "LTXVConcatAVLatent"
    assert p["14"]["inputs"]["video_latent"] == ["8", 0]
    assert p["14"]["inputs"]["audio_latent"] == ["13", 0]
    assert p["9"]["inputs"]["latent_image"] == ["14", 0]
    assert p["15"]["class_type"] == "LTXVSeparateAVLatent"
    assert p["15"]["inputs"]["av_latent"] == ["9", 0]
    assert p["10"]["inputs"]["samples"] == ["15", 0]
    assert p["16"]["class_type"] == "LTXVAudioVAEDecode"
    assert p["16"]["inputs"]["samples"] == ["15", 1]
    assert p["11"]["inputs"]["audio"] == ["16", 0]
    assert wf_t2v_audio["metadata"]["audio"] is True

    # 2. I2V Sesli (Audio=True) Testi
    wf_i2v_audio = engine.build_workflow({"prompt": "A girl smiling", "image_filename": "face.png", "image_fidelity": 0.85, "audio": True}, is_i2v=True)
    p = wf_i2v_audio["prompt"]
    assert p["6"]["inputs"]["image"] == "face.png"
    assert p["8"]["class_type"] == "LTXVImgToVideo"
    assert p["8"]["inputs"]["strength"] == 0.85
    assert p["14"]["inputs"]["video_latent"] == ["8", 2]
    assert p["14"]["inputs"]["audio_latent"] == ["13", 0]
    assert p["9"]["inputs"]["positive"] == ["8", 0]
    assert p["9"]["inputs"]["latent_image"] == ["14", 0]
    assert p["15"]["inputs"]["av_latent"] == ["9", 0]
    assert p["10"]["inputs"]["samples"] == ["15", 0]
    assert p["16"]["inputs"]["samples"] == ["15", 1]
    assert p["11"]["inputs"]["audio"] == ["16", 0]
    assert wf_i2v_audio["metadata"]["audio"] is True

    # 3. Sessiz Mod (Audio=False) Testi
    wf_silent = engine.build_workflow({"prompt": "A silent robot", "audio": False}, is_i2v=False)
    p = wf_silent["prompt"]
    assert p["9"]["inputs"]["latent_image"] == ["8", 0]
    assert p["10"]["inputs"]["samples"] == ["9", 0]
    assert "audio" not in p["11"]["inputs"]
    assert "12" not in p and "13" not in p and "14" not in p and "15" not in p and "16" not in p
    assert wf_silent["metadata"]["audio"] is False

    print("✅ test_workflows (T2V, I2V, Sesli & Sessiz) başarıyla doğrulandı!")

def test_minimax_h3_engine():
    from app.backend.engines.minimax_h3.engine import MiniMaxH3Engine
    engine = MiniMaxH3Engine()

    # 1. Boyut ve Frame Hesaplama Testi (4-15 sn aralığı, 768p tabanlı, 17k+5 ızgarası)
    dims_16_9 = engine.calculate_dimensions_and_frames(aspect_ratio="16:9", duration=8, fps=24)
    assert dims_16_9["width"] == 1344
    assert dims_16_9["height"] == 768
    assert dims_16_9["duration"] == 8
    assert (dims_16_9["frames"] - 5) % 17 == 0

    # Sınır testleri (2 saniye verilirse en az 4 saniyeye çekilmeli, 25 saniye verilirse 15'e çekilmeli)
    dims_min = engine.calculate_dimensions_and_frames(aspect_ratio="9:16", duration=2)
    assert dims_min["duration"] == 4
    assert dims_min["width"] == 768
    assert dims_min["height"] == 1344
    assert (dims_min["frames"] - 5) % 17 == 0

    dims_max = engine.calculate_dimensions_and_frames(aspect_ratio="1:1", duration=25)
    assert dims_max["duration"] == 15
    assert dims_max["width"] == 768
    assert dims_max["height"] == 768
    assert (dims_max["frames"] - 5) % 17 == 0

    # 2. Saf Text-to-Video (T2V) Workflow İnşası Doğrulaması
    t2v_params = {
        "prompt": "Cinematic shot of a cyberpunk street at night, neon lights reflection, synthwave ambient audio",
        "aspect_ratio": "16:9",
        "duration": 5,
        "fps": 24,
        "quality": "standard"
    }
    t2v_built = engine.build_workflow(t2v_params)
    t2v_wf = t2v_built["prompt"]

    # T2V Temel düğümler ve bağlantılar
    assert t2v_wf["1"]["class_type"] in ["UnetLoaderGGUF", "UNETLoader"]
    assert t2v_wf["2"]["class_type"] in ["CLIPLoaderGGUF", "CLIPLoader"]
    assert t2v_wf["2"]["inputs"]["type"] == "minimax"
    assert t2v_wf["3"]["class_type"] == "VAELoader"
    assert t2v_wf["4"]["class_type"] == "VAELoader"

    # T2V'de MiniMaxH3ImageToVideo düğümü kullanılmalı
    assert t2v_wf["8"]["class_type"] == "MiniMaxH3ImageToVideo"
    assert t2v_wf["8"]["inputs"]["prompt"] == t2v_params["prompt"]
    assert (t2v_wf["8"]["inputs"]["length"] - 5) % 17 == 0

    # Sampler Custom Advanced ve Guider bağlantıları
    assert t2v_wf["9"]["class_type"] == "BasicGuider"
    assert t2v_wf["9"]["inputs"]["conditioning"] == ["8", 0]
    assert t2v_wf["10"]["class_type"] == "KSamplerSelect"
    assert t2v_wf["11"]["class_type"] == "BasicScheduler"
    assert t2v_wf["12"]["class_type"] == "RandomNoise"
    assert t2v_wf["13"]["class_type"] == "SamplerCustomAdvanced"
    assert t2v_wf["13"]["inputs"]["guider"] == ["9", 0]
    assert t2v_wf["13"]["inputs"]["latent_image"] == ["8", 1]

    # VAE ve Çıktı Düğümleri
    assert t2v_wf["14"]["class_type"] == "VAEDecode"
    assert t2v_wf["14"]["inputs"]["vae"] == ["3", 0]
    assert t2v_wf["15"]["class_type"] == "VAEDecodeAudio"
    assert t2v_wf["15"]["inputs"]["vae"] == ["4", 0]
    assert t2v_wf["16"]["class_type"] == "CreateVideo"
    assert t2v_wf["17"]["class_type"] == "SaveVideo"

    # 3. Çoklu Referans (R2V / Omni) Workflow İnşası
    ref_params = {
        "prompt": "A character holding <Picture 1>, camera following <Video 1>, talking referencing timbre of <Audio 1>. <d>[Turkish] Merhaba dünya!</d>",
        "aspect_ratio": "16:9",
        "duration": 6,
        "fps": 24,
        "ref_images": ["char_front.png", "char_side.png"],
        "ref_videos": ["motion_dance.mp4"],
        "ref_audios": ["voice_timbre.wav"],
        "ref_image_size": "max",
        "quality": "standard"
    }

    built = engine.build_workflow(ref_params)
    wf = built["prompt"]

    # MiniMaxH3ReferenceToVideo node (Node 8) kontrolleri
    assert wf["8"]["class_type"] == "MiniMaxH3ReferenceToVideo"
    node8 = wf["8"]["inputs"]
    assert node8["ref_image_size"] == "max"
    assert "<d>[Turkish] Merhaba dünya!</d>" in node8["prompt"]
    assert node8["ref_images.ref_image_0"] == ["101", 0]
    assert node8["ref_images.ref_image_1"] == ["102", 0]
    # ref_videos IMAGE (kareler) bekler: LoadVideo -> GetVideoComponents çıktı 0
    assert node8["ref_videos.ref_video_0"] == ["211", 0]
    assert node8["ref_audios.ref_audio_0"] == ["301", 0]

    # Yükleyici düğümlerin varlığı
    assert wf["101"]["inputs"]["image"] == "char_front.png"
    assert wf["102"]["inputs"]["image"] == "char_side.png"
    # LoadVideo'nun girdisi "file" (ComfyUI nodes_video.py); VIDEO çıktısı GetVideoComponents'e gider
    assert wf["201"] == {"class_type": "LoadVideo", "inputs": {"file": "motion_dance.mp4"}}
    assert wf["211"] == {"class_type": "GetVideoComponents", "inputs": {"video": ["201", 0]}}
    assert wf["301"]["inputs"]["audio"] == "voice_timbre.wav"

    # 4. Referans Limitleri Doğrulama Testi (> 9 resim veya > 12 toplam hata fırlatmalı)
    too_many_imgs = [f"img_{i}.png" for i in range(10)]
    try:
        engine.validate_reference_inputs(too_many_imgs, [], [])
        assert False, "10 görsel hataya yol açmalıydı"
    except ValueError:
        pass

    too_many_total = [f"img_{i}.png" for i in range(8)]
    videos = [f"vid_{i}.mp4" for i in range(3)]
    audios = [f"aud_{i}.mp3" for i in range(3)]
    # Toplam: 8 + 3 + 3 = 14 > 12
    try:
        engine.validate_reference_inputs(too_many_total, videos, audios)
        assert False, "14 toplam referans hataya yol açmalıydı"
    except ValueError:
        pass

    print("✅ test_minimax_h3_engine başarıyla doğrulandı!")

def test_multimodal_assets_and_jobs():
    from app.backend.storage import storage
    # Görsel kaydet
    img_asset = storage.save_asset(b"FAKE_PNG_DATA", "test_photo.png")
    assert img_asset["media_type"] == "image"
    assert img_asset["filename"].endswith(".png")

    # Video kaydet
    vid_asset = storage.save_asset(b"FAKE_MP4_DATA", "clip.mp4")
    assert vid_asset["media_type"] == "video"
    assert vid_asset["filename"].endswith(".mp4")

    # Ses kaydet
    aud_asset = storage.save_asset(b"FAKE_WAV_DATA", "voice.wav")
    assert aud_asset["media_type"] == "audio"
    assert aud_asset["filename"].endswith(".wav")

    # MiniMax H3 ile Job oluştur
    create_resp = client.post("/api/jobs", json={
        "model": "minimax_h3",
        "prompt": "Test MiniMax prompt with <Picture 1> and <Audio 1>",
        "aspect_ratio": "16:9",
        "duration": 8,
        "ref_images": [img_asset["asset_id"]],
        "ref_audios": [aud_asset["asset_id"]],
        "ref_image_size": "match"
    })
    assert create_resp.status_code == 200
    job = create_resp.json()["job"]
    assert job["model"] == "minimax_h3"
    assert job["type"] == "reference_to_video"
    assert len(job["ref_images"]) == 1
    assert len(job["ref_audios"]) == 1

    print("✅ test_multimodal_assets_and_jobs başarıyla doğrulandı!")


def test_lora_support():
    """LoRA Yöneticisi, Dinamik İş Akışı Zinciri (LTX-2.5 & MiniMax H3), REST API ve MCP araçlarını test eder."""
    import os
    import config.settings as settings
    import app.backend.lora_manager as lora_manager
    from app.backend.engines.ltx25.engine import LTX25Engine
    from app.backend.engines.minimax_h3.engine import MiniMaxH3Engine

    # 1. Test LoRA dosyası oluştur
    lora_dir = settings.ACTIVE_LORAS_DIR
    os.makedirs(lora_dir, exist_ok=True)
    test_lora_name = "test_cyberpunk_v1.safetensors"
    test_lora_path = os.path.join(lora_dir, test_lora_name)
    with open(test_lora_path, "wb") as f:
        f.write(b"MOCK_LORA_WEIGHTS_CONTENT" * 1000)

    # 2. list_available_loras testi
    loras = lora_manager.list_available_loras()
    assert any(l["name"] == test_lora_name for l in loras)
    found = next(l for l in loras if l["name"] == test_lora_name)
    assert found["size_mb"] >= 0.02

    # 3. LTX-2.5 Tekli ve Çoklu LoRA Enjeksiyon Testi
    ltx_engine = LTX25Engine()
    # Tekli LoRA
    wf_ltx = ltx_engine.build_workflow({
        "prompt": "Cyberpunk city",
        "loras": [{"name": test_lora_name, "strength": 0.8}]
    })
    prompt_ltx = wf_ltx["prompt"]
    assert "50" in prompt_ltx
    # VRAM koruması: LoRA varsayılan olarak SADECE diffusion modeline uygulanır.
    # CLIP (Gemma 4 12B) patchlemek dev metin kodlayıcıyı VRAM'e çekip OOM'a yol açıyordu.
    assert prompt_ltx["50"]["class_type"] == "LoraLoaderModelOnly"
    assert prompt_ltx["50"]["inputs"]["model"] == ["1", 0]
    assert "clip" not in prompt_ltx["50"]["inputs"]
    assert prompt_ltx["50"]["inputs"]["strength_model"] == 0.8
    assert prompt_ltx["9"]["inputs"]["model"] == ["50", 0]
    # CLIP zinciri dokunulmadan orijinal CLIPLoader'a bağlı kalmalı
    assert prompt_ltx["4"]["inputs"]["clip"] == ["2", 0]
    assert prompt_ltx["5"]["inputs"]["clip"] == ["2", 0]
    assert len(wf_ltx["metadata"]["loras"]) == 1
    assert wf_ltx["metadata"]["loras"][0]["strength_clip"] == 0.0

    # Kullanıcı bilinçli olarak strength_clip verirse tam LoraLoader kullanılır
    wf_ltx_clip = ltx_engine.build_workflow({
        "prompt": "Cyberpunk city",
        "loras": [{"name": test_lora_name, "strength": 0.8, "strength_clip": 0.6}]
    })
    p_clip = wf_ltx_clip["prompt"]
    assert p_clip["50"]["class_type"] == "LoraLoader"
    assert p_clip["50"]["inputs"]["clip"] == ["2", 0]
    assert p_clip["50"]["inputs"]["strength_clip"] == 0.6
    assert p_clip["4"]["inputs"]["clip"] == ["50", 1]
    assert p_clip["5"]["inputs"]["clip"] == ["50", 1]

    # Çift LoRA Zincirleme (model-only zinciri)
    wf_ltx_double = ltx_engine.build_workflow({
        "prompt": "Cyberpunk city",
        "loras": [
            {"name": test_lora_name, "strength": 0.7},
            {"name": "test_style_v2.safetensors", "strength": 0.5}
        ]
    })
    p_double = wf_ltx_double["prompt"]
    assert "50" in p_double and "51" in p_double
    assert p_double["51"]["inputs"]["model"] == ["50", 0]
    assert p_double["9"]["inputs"]["model"] == ["51", 0]
    assert p_double["4"]["inputs"]["clip"] == ["2", 0]

    # En fazla MAX_LORAS_PER_JOB kadar LoRA zincire eklenir
    wf_ltx_many = ltx_engine.build_workflow({
        "prompt": "Cyberpunk city",
        "loras": [{"name": f"l{i}.safetensors", "strength": 1.0} for i in range(6)]
    })
    assert len(wf_ltx_many["metadata"]["loras"]) == settings.MAX_LORAS_PER_JOB

    # 4. MiniMax H3 LoRA Enjeksiyon Testi
    h3_engine = MiniMaxH3Engine()
    wf_h3 = h3_engine.build_workflow({
        "prompt": "MiniMax character scene",
        "duration": 6,
        "loras": [{"name": test_lora_name, "strength": 0.95}]
    })
    prompt_h3 = wf_h3["prompt"]
    assert "50" in prompt_h3
    assert prompt_h3["50"]["class_type"] == "LoraLoaderModelOnly"
    assert prompt_h3["50"]["inputs"]["model"] == ["1", 0]
    assert prompt_h3["9"]["inputs"]["model"] == ["50", 0]
    assert prompt_h3["11"]["inputs"]["model"] == ["50", 0]
    assert len(wf_h3["metadata"]["loras"]) == 1

    # 5. REST API Testleri
    get_loras_resp = client.get("/api/loras")
    assert get_loras_resp.status_code == 200
    lora_list = get_loras_resp.json()["loras"]
    assert any(l["name"] == test_lora_name for l in lora_list)

    # İndirme API validasyon testi
    bad_dl_resp = client.post("/api/loras/download", json={})
    assert bad_dl_resp.status_code == 400

    # 6. MCP Araçları Testi
    # MCP list_loras
    mcp_list_resp = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "id": "mcp-lora-1",
        "method": "tools/call",
        "params": {"name": "list_loras", "arguments": {}}
    })
    assert mcp_list_resp.status_code == 200
    mcp_loras = mcp_list_resp.json()["result"]["structured"]["loras"]
    assert any(l["name"] == test_lora_name for l in mcp_loras)

    # MCP generate_video with loras
    mcp_gen_resp = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "id": "mcp-lora-2",
        "method": "tools/call",
        "params": {
            "name": "generate_video",
            "arguments": {
                "prompt": "A futuristic vehicle",
                "loras": [{"name": test_lora_name, "strength": 0.85}]
            }
        }
    })
    assert mcp_gen_resp.status_code == 200
    gen_job = mcp_gen_resp.json()["result"]["structured"]["job"]
    assert len(gen_job["loras"]) == 1
    assert gen_job["loras"][0]["name"] == test_lora_name

    # MCP generate_omni_video with loras
    mcp_omni_resp = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "id": "mcp-lora-3",
        "method": "tools/call",
        "params": {
            "name": "generate_omni_video",
            "arguments": {
                "prompt": "An omni character",
                "duration": 6,
                "loras": [{"name": test_lora_name, "strength": 0.9}]
            }
        }
    })
    assert mcp_omni_resp.status_code == 200
    omni_job = mcp_omni_resp.json()["result"]["structured"]["job"]
    assert len(omni_job["loras"]) == 1

    # 7. LoRA Silme Testi
    del_resp = client.delete(f"/api/loras/{test_lora_name}")
    assert del_resp.status_code == 200
    assert not os.path.exists(test_lora_path)

    print("✅ test_lora_support (LoRA Yöneticisi, Dinamik Zincir, API & MCP) başarıyla doğrulandı!")


def test_comfy_logs_endpoint():
    resp = client.get("/api/system/comfy_logs?lines=20")
    assert resp.status_code == 200
    data = resp.json()
    assert "available" in data
    assert "lines" in data
    print("✅ test_comfy_logs_endpoint başarıyla doğrulandı!")


if __name__ == "__main__":
    test_camera_presets()
    test_prompt_enhancer()
    test_api_status()
    test_api_presets()
    test_api_prompt_enhance()
    test_workflows()
    test_minimax_h3_engine()
    test_multimodal_assets_and_jobs()
    test_api_jobs_crud()
    test_mcp_endpoints()
    test_lora_support()
    test_comfy_logs_endpoint()
    print("\n🎉 TÜM BACKEND BİRİM TESTLERİ (LTX-2.5 & MINIMAX-H3 + LORA DESTEĞİ) EKSİKSİZ GEÇTİ!")




# ==========================================================
# REGRESYON TESTLERİ - VRAM / OOM, LoRA SENKRONİZASYONU, İPTAL
# ==========================================================

def test_vram_model_signature_changes():
    """Model veya LoRA seti değiştiğinde VRAM imzası değişmeli (OOM önleme tetiği)."""
    from app.backend.queue_manager import QueueManager

    sig = QueueManager._model_signature

    base = {"model": "ltx25", "type": "text_to_video", "loras": []}
    same = {"model": "ltx25", "type": "text_to_video", "loras": []}
    assert sig(base) == sig(same)

    # Model değişimi -> yeni imza (LTX <-> MiniMax geçişi VRAM'i boşaltmalı)
    other_model = {"model": "minimax_h3", "type": "text_to_video", "loras": []}
    assert sig(base) != sig(other_model)

    # LoRA eklenmesi -> yeni imza
    with_lora = {"model": "ltx25", "type": "text_to_video",
                 "loras": [{"name": "a.safetensors", "strength": 1.0}]}
    assert sig(base) != sig(with_lora)

    # LoRA gücü değişimi -> yeni imza (ComfyUI ayrı bir patchlenmiş kopya yükler)
    diff_strength = {"model": "ltx25", "type": "text_to_video",
                     "loras": [{"name": "a.safetensors", "strength": 0.5}]}
    assert sig(with_lora) != sig(diff_strength)

    # Sıralama farkı imzayı değiştirmemeli
    two_a = {"model": "ltx25", "type": "text_to_video", "loras": [
        {"name": "a.safetensors", "strength": 1.0}, {"name": "b.safetensors", "strength": 1.0}]}
    two_b = {"model": "ltx25", "type": "text_to_video", "loras": [
        {"name": "b.safetensors", "strength": 1.0}, {"name": "a.safetensors", "strength": 1.0}]}
    assert sig(two_a) == sig(two_b)

    print("✅ test_vram_model_signature_changes doğrulandı!")


def test_oom_error_detection():
    """OOM hataları tanınmalı ki kullanıcıya çözüm önerisi gösterilebilsin."""
    from app.backend.queue_manager import _is_oom_error

    assert _is_oom_error("CUDA out of memory. Tried to allocate 2.00 GiB")
    assert _is_oom_error("torch.cuda.OutOfMemoryError: ...")
    assert _is_oom_error("Allocation on device failed: not enough memory")
    assert not _is_oom_error("FileNotFoundError: workflow.json")
    assert not _is_oom_error("")

    print("✅ test_oom_error_detection doğrulandı!")


def test_lora_comfyui_sync():
    """Drive'daki bir LoRA, iş kuyruğa verilmeden önce ComfyUI arama yoluna bağlanmalı."""
    import os
    import config.settings as settings
    import app.backend.lora_manager as lora_manager

    os.makedirs(settings.ACTIVE_LORAS_DIR, exist_ok=True)
    os.makedirs(settings.COMFYUI_LORAS_DIR, exist_ok=True)

    name = "test_sync_lora.safetensors"
    src = os.path.join(settings.ACTIVE_LORAS_DIR, name)
    with open(src, "wb") as f:
        f.write(b"X" * 4096)

    comfy_target = os.path.join(settings.COMFYUI_LORAS_DIR, name)
    if os.path.lexists(comfy_target):
        os.remove(comfy_target)

    try:
        result = lora_manager.ensure_loras_available([name])
        assert result["ok"], result
        assert result["resolved"][name] == name
        assert os.path.exists(comfy_target), "LoRA ComfyUI loras dizinine bağlanmadı"

        # Yol çözümleme
        assert lora_manager.resolve_lora_path(name) is not None

        # Eksik LoRA anlaşılır şekilde raporlanmalı (ComfyUI'nin şifreli hatası yerine)
        missing = lora_manager.ensure_loras_available(["kesinlikle_yok_12345.safetensors"])
        assert not missing["ok"]
        assert "kesinlikle_yok_12345.safetensors" in missing["missing"]
    finally:
        for path in (src, comfy_target):
            if os.path.lexists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    print("✅ test_lora_comfyui_sync doğrulandı!")


def test_job_cancellation_marks_cancelled():
    """İptal edilen iş kuyruktan çıkmalı ve tekrar başlatılmamalı."""
    from app.backend.queue_manager import queue_manager, JobStatus

    resp = client.post("/api/jobs", json={"prompt": "iptal testi", "model": "ltx25"})
    job_id = resp.json()["job"]["id"]

    cancel = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["success"] is True

    job = queue_manager.get_job(job_id)
    assert job["status"] == JobStatus.CANCELLED
    assert job_id not in queue_manager.queue

    # Yeniden deneme iptal bayrağını temizlemeli
    retried = client.post(f"/api/jobs/{job_id}/retry")
    assert retried.status_code == 200
    assert job_id not in queue_manager._cancel_requested

    client.delete(f"/api/jobs/{job_id}")

    print("✅ test_job_cancellation_marks_cancelled doğrulandı!")


def test_mcp_spec_compliance():
    """MCP yanıtları spec uyumlu olmalı: JSON metin gövdesi + structuredContent."""
    import json as _json

    resp = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": "spec-1",
        "method": "tools/call",
        "params": {"name": "list_presets", "arguments": {}}
    })
    assert resp.status_code == 200
    result = resp.json()["result"]

    # İçerik geçerli JSON olmalı (daha önce Python dict repr'ı gönderiliyordu)
    parsed = _json.loads(result["content"][0]["text"])
    assert parsed["total"] > 0
    assert result["isError"] is False
    assert "structuredContent" in result
    assert result["structuredContent"] == result["structured"]

    # Hatalı araç çağrısı isError=True dönmeli, 500 patlamamalı
    bad = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": "spec-2",
        "method": "tools/call",
        "params": {"name": "generate_video", "arguments": {}}
    })
    assert bad.status_code == 200
    assert bad.json()["result"]["isError"] is True

    # Bilinmeyen metot JSON-RPC hatası dönmeli
    unknown = client.post("/mcp", json={"jsonrpc": "2.0", "id": "spec-3", "method": "yok/olan"})
    assert unknown.json()["error"]["code"] == -32601

    # ping
    ping = client.post("/mcp", json={"jsonrpc": "2.0", "id": "spec-4", "method": "ping"})
    assert ping.json()["result"] == {}

    # GET /mcp bilgi dönmeli (statik dosya 404'üne düşmemeli)
    info = client.get("/mcp")
    assert info.status_code == 200
    assert "free_vram" in info.json()["tools"]

    print("✅ test_mcp_spec_compliance doğrulandı!")


def test_minimax_applies_camera_preset():
    """MiniMax H3 de kamera presetlerini prompta uygulamalı (önceden yok sayılıyordu)."""
    from app.backend.engines.minimax_h3.engine import MiniMaxH3Engine

    engine = MiniMaxH3Engine()
    built = engine.build_workflow({"prompt": "bir karakter", "camera": "orbit_left", "duration": 6})
    final = built["metadata"]["final_prompt"].lower()
    assert "bir karakter" in final
    assert len(final) > len("bir karakter")

    print("✅ test_minimax_applies_camera_preset doğrulandı!")


def test_free_vram_endpoint():
    """VRAM boşaltma uç noktası ComfyUI kapalıyken de temiz yanıt vermeli."""
    resp = client.post("/api/system/free_vram")
    assert resp.status_code == 200
    body = resp.json()
    assert "success" in body and "message" in body

    print("✅ test_free_vram_endpoint doğrulandı!")


def test_path_traversal_is_blocked():
    """Herkese açık ngrok adresinde job_id / asset_id ile dizin geçişi engellenmeli."""
    from app.backend.storage import is_safe_id

    assert is_safe_id("vid_20250101_abc123")
    assert is_safe_id("asset_img_deadbeef.png")
    assert not is_safe_id("../../etc/passwd")
    assert not is_safe_id("..")
    assert not is_safe_id("a/b")
    assert not is_safe_id("")
    assert not is_safe_id(".gizli")

    resp = client.get("/api/videos/..%2F..%2Fsecret/stream")
    assert resp.status_code in (400, 404)

    resp2 = client.get("/api/assets/..%2F..%2Fsecret")
    assert resp2.status_code in (400, 404)

    print("✅ test_path_traversal_is_blocked doğrulandı!")


def test_ltx_model_loader_autodetect():
    """LTX-2.5 diffusion dosyası safetensors veya GGUF olabilir; yükleyici düğüm otomatik seçilmeli."""
    import os
    import config.settings as settings
    from app.backend.engines.ltx25.engine import LTX25Engine

    engine = LTX25Engine()
    diff_dir = os.path.join(settings.COMFYUI_DIR, "models", "diffusion_models")
    os.makedirs(diff_dir, exist_ok=True)

    st_name = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
    gguf_name = "ltx-2.5-22b-distilled-transformer-Q8_0.gguf"
    st_path = os.path.join(diff_dir, st_name)
    gguf_path = os.path.join(diff_dir, gguf_name)

    try:
        # 1. Resmi safetensors mevcut -> UNETLoader
        with open(st_path, "wb") as f:
            f.write(b"x")
        name, cls = engine.resolve_diffusion_model()
        assert name == st_name
        assert cls == "UNETLoader"
        wf = engine.build_workflow({"prompt": "t"})["prompt"]
        assert wf["1"]["class_type"] == "UNETLoader"
        assert wf["1"]["inputs"]["unet_name"] == st_name
        assert wf["1"]["inputs"]["weight_dtype"] == "default"

        # 2. Yalnızca GGUF mevcut -> UnetLoaderGGUF (weight_dtype gönderilmez)
        os.remove(st_path)
        with open(gguf_path, "wb") as f:
            f.write(b"x")
        name, cls = engine.resolve_diffusion_model()
        assert name == gguf_name
        assert cls == "UnetLoaderGGUF"
        wf = engine.build_workflow({"prompt": "t"})["prompt"]
        assert wf["1"]["class_type"] == "UnetLoaderGGUF"
        assert "weight_dtype" not in wf["1"]["inputs"]

        # 3. Text encoder ve VAE adları ayarlardan gelmeli
        assert wf["2"]["inputs"]["clip_name"] == settings.MODEL_TEXT_ENCODER
        assert wf["3"]["inputs"]["vae_name"] == settings.MODEL_VIDEO_VAE
    finally:
        for p in (st_path, gguf_path):
            if os.path.lexists(p):
                os.remove(p)

    print("✅ test_ltx_model_loader_autodetect doğrulandı!")
