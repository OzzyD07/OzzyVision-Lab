<div align="center">

# OzzyVision-Lab
### LTX-2.5 & MiniMax H3 ile video + ses üretim stüdyosu

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://reactjs.org/)
[![Vite](https://img.shields.io/badge/Vite-5.4-646CFF?style=for-the-badge&logo=vite&logoColor=white)](https://vitejs.dev/)
[![ComfyUI](https://img.shields.io/badge/ComfyUI-Headless_API-ff6b6b?style=for-the-badge)](https://github.com/comfyanonymous/ComfyUI)
[![Colab](https://img.shields.io/badge/Google_Colab-A100_80GB-F9AB00?style=for-the-badge&logo=googlecolab&logoColor=white)](https://colab.research.google.com/)
[![MCP](https://img.shields.io/badge/Claude-Remote_MCP_2.0-7952b3?style=for-the-badge&logo=anthropic&logoColor=white)](https://modelcontextprotocol.io/)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

<p align="center">
  ComfyUI üzerinde çalışan, LTX-2.5 ve MiniMax H3 modellerini tek arayüzde toplayan
  kişisel bir video ve ses üretim stüdyosu.
  <br />
  Google Colab A100 (80GB) için hazırlanmıştır; 24GB+ VRAM'li yerel makinelerde de çalışır.
</p>

[Özellikler](#özellikler) • [Colab](#google-colab-ile-başlangıç) • [Yerel kurulum](#yerel-kurulum) • [Claude MCP](#claude-mcp-entegrasyonu) • [Ortam değişkenleri](#ortam-değişkenleri)

---

</div>

## Özellikler

### İki motor
1. **Lightricks LTX-2.5 Distilled (22B, Comfy Int8):**
   - **8-Step Turbo Çıkarım:** Saniyeler içinde 24 FPS akıcı, yüksek sadakatli sinematik video üretimi.
   - **Character & Face Fidelity:** Yüklenen referans görselin yüz hatlarını, kıyafet detaylarını ve ışık dengesini bozmadan canlandırma (Image-to-Video).
   - **Doğal Ambiyans Sesi (Native Audio VAE):** Sahne dinamiğine uygun dahili stereo ses efektleri.
   - **17+ Sinematik Kamera Hareketi:** Dolly In/Out, Orbit, Pan, Tilt, Handheld, Crane, FPV Drone ve Dinamik Zoom.

2. **MiniMax H3 Omni-Reference (Resmi FP8 Scaled Safetensors):**
   - **Omni-Reference Vault:** 9 adede kadar görsel, 3 video ve 3 ses referansını aynı sahnede harmanlayabilme.
   - **Doğal 32 kHz Senkronize Stereo Ses:** Video ve ses tek bir latent uzayında eşzamanlı üretilir.
   - **Çok Dilli Dudak Senkronizasyonu (Lip-Sync):** `<d>[Turkish] Merhaba!</d>` etiketleriyle karakterin ağız ve mimik hareketlerini konuşmayla tam senkronize eder.

---

### Stüdyo
- **Lüks Koyu Arayüz (Dark Glassmorphism):** Runway Gen-3 ve Higgsfield estetiğinde, göz yormayan, modern ve duyarlı tasarım.
- **LoRA Model Hub & Bulut İndirici:** Hugging Face veya Civitai doğrudan bağlantılarını yapıştırarak modelleri bilgisayarınızın kotasını harcamadan doğrudan bulut GPU önbelleğinize ve Google Drive'a aktarın.
- **Hızlı LoRA Ayarı & Önayarlar:** Kütüphanedeki modeller tek tıkla (`+ Turbo 4-Step`, `+ Film Grain`) sahneye eklenir; `-2.0x` ile `+2.0x` arasında ince ayar yapılabilir.
- **GPU Görev Kuyruğu (Sequential FIFO):** Tek bir GPU üzerinde işlerin çakışmasını önleyen, anlık aşama bildiren (%0 - %100) profesyonel kuyruk yöneticisi.
- **Yaratıcı Medya Arşivi (Gallery):** Üretilen videoları oynatın, metadata detaylarını inceleyin ve dilediğiniz ayarları tek tıkla stüdyoya geri aktarın (*Reuse Settings*).
- **Kalıcı Google Drive Depolama (`OzzyVision-Lab`):** Oturum kapansa bile ağırlıklar, LoRA'lar, üretilen videolar ve durum kayıtları Google Drive'ınızda güvenle saklanır; bir kez indirilen modeller asla tekrar indirilmez.
- **Claude Remote MCP Desteği:** Claude Desktop veya Claude.ai ile doğrudan konuşarak sahne yönetebilir, kamera hareketleri verebilir ve video ürettirebilirsiniz.

---

## Google Colab ile başlangıç

Google Colab üzerinde A100 GPU kullanarak 5 dakika içinde stüdyoyu ayağa kaldırabilirsiniz:

### 1. Adım: Notebook'u Açın
`colab/OzzyVision_Lab.ipynb` dosyasını Google Colab'a yükleyin veya doğrudan GitHub üzerinden açın.

### 2. Adım: Donanımı A100 Olarak Seçin
Colab menüsünden:
> **Runtime (Çalışma Zamanı)** &rarr; **Change runtime type (Çalışma zamanı türünü değiştir)** &rarr; **A100 GPU (80GB)** seçeneğini işaretleyin.

### 3. Adım: Hücreleri Çalıştırın
Notebook hücrelerini sırayla çalıştırın:
1. **Google Drive Bağlantısı:** `MyDrive/OzzyVision-Lab` dizini otomatik olarak oluşturulur. *(Eski `LTX-Studio` klasörünüz varsa otomatik olarak taşınır ve verileriniz korunur.)*
2. **Ortam ve Bağımlılıklar:** ComfyUI, PyTorch, xFormers ve gerekli düğümler kurulur.
3. **Model Kontrolü:** Modeller ilk seferde Drive'a indirilir, sonraki oturumlarda saniyeler içinde bağlanır.
4. **Tek Tıkla Başlatıcı (One-Click Launcher):** FastAPI backend, Vite frontend ve ComfyUI tek bir port üzerinden güvenli Ngrok tüneline açılır.

### 4. Adım: Stüdyoya Bağlanın
Terminal çıktısında beliren bağlantıya tıklayın:
- 🌐 **Web Studio:** `https://xxxx.ngrok-free.app`
- 🤖 **Claude MCP Endpoint:** `https://xxxx.ngrok-free.app/mcp`

---

## Yerel kurulum

Projeyi kendi bilgisayarınızda veya yerel sunucunuzda çalıştırmak için:

### Gereksinimler
- **İşletim Sistemi:** Linux (Ubuntu 22.04+ önerilir) veya Windows 11
- **GPU:** NVIDIA RTX 3090 / 4090 (24GB) veya A100 / H100
- **CUDA:** 12.1+ ve cuDNN
- **Python:** 3.10, 3.11 veya 3.12
- **Node.js:** 18+ ve npm

### Kurulum Adımları

```bash
# 1. Depoyu klonlayın
git clone https://github.com/<kullanici-adi>/OzzyVision-Lab.git
cd OzzyVision-Lab

# 2. Python sanal ortamını oluşturun ve aktif edin
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux:
source venv/bin/activate

# 3. Bağımlılıkları yükleyin
pip install -r requirements.txt

# 4. Frontend bağımlılıklarını yükleyin ve derleyin
cd app/frontend
npm install
npm run build
cd ../..

# 5. Testleri çalıştırarak ortamı doğrulayın
pytest tests/

# 6. Backend sunucusunu başlatın
uvicorn app.backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Tarayıcınızda `http://localhost:8000` adresine giderek stüdyoyu kullanmaya başlayabilirsiniz.

---

## Claude MCP entegrasyonu

OzzyVision-Lab, **Model Context Protocol (MCP)** standardını destekler. Claude'a stüdyonuzun kontrolünü vermek için:

1. Claude Desktop uygulamasını veya [Claude.ai](https://claude.ai) arayüzünü açın.
2. **Settings (Ayarlar)** &rarr; **Integrations / Connectors (Bağlayıcılar)** bölümüne gidin.
3. **Add Custom Connector** butonuna tıklayın.
4. URL alanına Ngrok adresinizi girin:
   ```text
   https://senin-domain.ngrok-free.app/mcp
   ```
5. Bağlantıyı kaydedin. Artık Claude ile doğal dilde konuşarak video üretebilirsiniz!

### Örnek Claude Komutları:
> *"Sisli Tokyo sokağında yürüyen bir samuray için 9:16 oranında 6 saniyelik sinematik bir video üret. Kamera yavaşça yaklaşsın (Dolly In)."*

> *"Yüklediğim asset_49a12 referans görselini kullanarak karakterin kameraya dönüp gülümsediği bir video oluştur, yüz tutarlılığı yüksek olsun."*

> *"Şu an kuyrukta bekleyen işlerin durumunu listele."*

---

## Dizin yapısı

```text
OzzyVision-Lab/
├── config/
│   ├── __init__.py
│   └── settings.py              # Merkezi Drive yolları ve ortam konfigürasyonu
├── app/
│   ├── backend/
│   │   ├── main.py              # FastAPI çekirdeği, REST API rotaları & WebSocket
│   │   ├── queue_manager.py     # Tekil GPU için thread-safe sıralı işlem kuyruğu
│   │   ├── storage.py           # Google Drive kalıcı depolama senkronizasyonu
│   │   ├── camera_presets.py    # 17 adet sinematik kamera matematiksel profili
│   │   ├── prompt_enhancer.py   # LLM destekli sinematik prompt geliştirici
│   │   ├── lora_manager.py      # LoRA kütüphanesi, bulut indirici & ComfyUI senkronizasyonu
│   │   └── engines/
│   │       ├── base.py          # Soyut motor + ComfyUI HTTP katmanı (VRAM /free, /interrupt, şema doğrulama)
│   │       ├── ltx25/
│   │       │   ├── engine.py    # LTX-2.5 işleyici (8n+1 frame, mod 32, safetensors/GGUF oto-seçim)
│   │       │   ├── i2v_workflow.json # Image-to-Video API grafiği
│   │       │   └── t2v_workflow.json # Text-to-Video API grafiği
│   │       └── minimax_h3/
│   │           ├── engine.py    # MiniMax H3 Omni (Resmi FP8 Scaled + Stereo Audio)
│   │           └── ref2va_workflow.json # Omni-Reference API grafiği
│   ├── frontend/
│   │   ├── index.html
│   │   ├── vite.config.js
│   │   └── src/
│   │       ├── index.css        # Luxury Glassmorphism koyu tema & slider stilleri
│   │       ├── App.jsx          # Ana stüdyo düzeni ve sekme yönlendirici
│   │       ├── components/
│   │       │   ├── Header.jsx       # Üst navigasyon ve canlı GPU/ComfyUI rozetleri
│   │       │   ├── CreateStudio.jsx # Yaratıcı kontrol paneli, LoRA hub & oynatıcı
│   │       │   ├── QueueDrawer.jsx  # GPU kuyruk yöneticisi ve iş geçmişi
│   │       │   ├── GalleryView.jsx  # Medya galerisi ve metadata inceleme
│   │       │   └── SettingsModal.jsx# Mimari şeması ve Claude MCP yapılandırması
│   │       └── services/api.js      # REST ve WebSocket istemcisi
│   └── mcp/
│       └── server.py            # Claude Remote MCP 2.0 protokol sunucusu (/mcp)
├── tests/
│   ├── test_phase01_fidelity.py    # Bağımsız LTX-2.5 referans sadakat testi
│   ├── test_api.py                 # FastAPI uç nokta, kuyruk, LoRA, MCP ve güvenlik testleri
│   └── test_integration_comfy.py   # Sahte ComfyUI ile uçtan uca akış & VRAM/OOM regresyon testleri
├── colab/
│   └── OzzyVision_Lab.ipynb    # Google Colab kurulum ve başlatma notebook'u
├── requirements.txt             # Python paket gereksinimleri
└── README.md                    # Proje dökümantasyonu
```

---

## Model kaynakları

Notebook bu dosyaları Drive'a indirir. **İlk kaynak başarısız olursa (lisans onayı / 404)
otomatik olarak yedek aynaya geçilir.**

### LTX-2.5 — `Lightricks/LTX-2.5` (lisans onayı gerekir) · yedek: `comfyicu/LTX-2.5`

| Bileşen | Depo içi yol |
| --- | --- |
| Diffusion (22B Distilled) | `diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` |
| Text Encoder (Gemma 4 12B) | `text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` |
| Video VAE | `vae/ltx-2.5-video-vae-bf16.safetensors` |
| Audio VAE | `vae/ltx-2.5-audio-vae-bf16.safetensors` |
| Spatial Upscaler (ops.) | `latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` |

> **Lisans onayı:** [huggingface.co/Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5)
> sayfasından lisansı kabul edin ve `HF_TOKEN`'ı Colab Secrets'a ekleyin.
>
> **Düşük VRAM / GGUF alternatifi:** Notebook'ta `LTX_QUANT = "gguf"` yaparsanız
> `vantagewithai/LTX-2.5-GGUF` deposundan Q8_0 GGUF indirilir. Motor, hangi format
> mevcutsa doğru yükleyici düğümü (`UNETLoader` / `UnetLoaderGGUF`) otomatik seçer.

### MiniMax H3 — `Comfy-Org/MiniMax-H3`

| Bileşen | Depo içi yol |
| --- | --- |
| Diffusion (Ref2VA FP8) | `diffusion_models/minimax_h3_ref2va_pruned_fp8_scaled.safetensors` |
| Text Encoder (Qwen3-VL 32B) | `text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| Video VAE | `vae/minimax_h3_video_vae_fp16.safetensors` |
| Audio VAE | `vae/minimax_h3_audio_vae_fp32.safetensors` |

---

## Google Drive dizin düzeni

Google Drive'ınız bağlandığında otomatik oluşturulan hiyerarşi:

```text
Google Drive / MyDrive / OzzyVision-Lab/
├── models/
│   ├── diffusion_models/        # LTX-2.5 22B Int8 & MiniMax H3 FP8 Safetensors
│   ├── text_encoders/           # Gemma 4 12B & Qwen 2.5
│   ├── vae/                     # LTX & MiniMax VAE ağırlıkları
│   └── loras/                   # İndirilen özel stil & karakter LoRA modelleri
├── jobs/                        # Her video için job.json durum ve metadata dosyaları
├── gallery/                     # Üretilen MP4 videoları ve önizlemeler
└── assets/                      # Yüklenen referans görseller, videolar ve sesler
```

---

## Testler

Sistemin kararlılığı otomatik birim testleriyle doğrulanmıştır:

```bash
pytest tests/ -v
```

Çıktı:
```text
tests/test_api.py ....................                                   [ 74%]
tests/test_integration_comfy.py .......                                  [100%]
====================== 28 passed in 35.4s [100%] ======================
```

`tests/test_integration_comfy.py` sahte bir ComfyUI HTTP sunucusu ayağa kaldırarak
gerçek üretim akışının tamamını doğrular: LoRA senkronizasyonu, VRAM boşaltma,
workflow şema doğrulaması, iş tamamlama ve iptal.

---

## Ortam değişkenleri

Hiçbiri zorunlu değildir; hepsinin çalışan bir varsayılanı vardır. Aşağıdaki tablo
hangisini, nerede tanımlayacağınızı gösterir.

**Nerede tanımlanır?**

| Yer | Nasıl | Ne zaman |
| --- | --- | --- |
| **Colab Secrets** | Sol menü 🔑 → *Add new secret* → *Notebook access* açık | Jetonlar (`HF_TOKEN`, `NGROK_AUTHTOKEN`) — notebook bunları otomatik okur |
| **`config/settings.py`** | Dosyadaki varsayılan değeri doğrudan değiştirin | Kalıcı tercihler (yollar, VRAM davranışı) |
| **Kabuk / terminal** | `export DEGISKEN=deger` (Windows: `$env:DEGISKEN="deger"`) | Yerel kurulumda tek seferlik deneme |

### Jetonlar (opsiyonel — Colab Secrets)

| Değişken | Varsayılan | Ne işe yarar |
| --- | --- | --- |
| `HF_TOKEN` | boş | Lisans onayı isteyen `Lightricks/LTX-2.5` deposundan indirme. Yoksa açık ayna (`comfyicu/LTX-2.5`) kullanılır. |
| `NGROK_AUTHTOKEN` | boş | Stüdyoyu tarayıcıya açan tünel. **Colab'da pratikte gereklidir.** |
| `NGROK_DOMAIN` | boş | Ngrok'ta rezerve ettiğiniz sabit alan adı. |
| `CIVITAI_TOKEN` | boş | Civitai'den LoRA indirme. |

### Sunucu (opsiyonel — `config/settings.py`)

| Değişken | Varsayılan | Ne işe yarar |
| --- | --- | --- |
| `COMFYUI_HOST` / `COMFYUI_PORT` | `127.0.0.1` / `8188` | ComfyUI adresi. ComfyUI'yi farklı portta çalıştırıyorsanız değiştirin. |
| `COMFYUI_MAX_WAIT_SECONDS` | `1800` | Tek işin zaman aşımı. Uzun videolarda artırın. |
| `BACKEND_HOST` / `BACKEND_PORT` | `0.0.0.0` / `8000` | FastAPI adresi. |
| `COMFY_POLL_INTERVAL` | `2.0` | İş sırasında ComfyUI durumu ve VRAM/RAM ölçümünün alınma aralığı (saniye). |
| `COMFY_CRASH_GRACE_SECONDS` | `15` | ComfyUI yanıt vermezse çökmüş sayılmadan önce beklenen süre. |

### VRAM davranışı (opsiyonel — `config/settings.py`)

| Değişken | Varsayılan | Ne işe yarar |
| --- | --- | --- |
| `FREE_VRAM_ON_MODEL_SWITCH` | `1` | Model veya LoRA değiştiğinde GPU belleğini boşaltır. Kapatmayın — OOM'un ana koruması budur. |
| `FREE_VRAM_BEFORE_LORA_JOB` | `1` | LoRA'lı ilk işten önce belleği boşaltır. |
| `FREE_VRAM_SETTLE_SECONDS` | `2.5` | Boşaltma sonrası bekleme. |
| `LORA_APPLY_TO_CLIP` | `0` | LoRA'yı metin kodlayıcıya da uygular. Açmak OOM riskini ciddi biçimde artırır. |
| `MAX_LORAS_PER_JOB` | `3` | Aynı anda zincirlenecek LoRA sayısı. |

> **Notebook ayarı:** `COMFY_LOW_RAM` ortam değişkeni değil, notebook'un 6. adım hücresindeki bir değişkendir. Stüdyo "Sistem RAM'i doldu" hatası verirse `True` yapıp hücreyi yeniden çalıştırın; modeller her üretimde yeniden okunur ama sistem RAM'inde birikmez.

### Model dosyaları (opsiyonel — `config/settings.py`)

| Değişken | Varsayılan | Ne işe yarar |
| --- | --- | --- |
| `MODEL_DIFFUSION` | `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | Başka bir LTX-2.5 varyantı (ör. GGUF) kullanmak isterseniz. Motor, dosya uzantısına göre doğru yükleyici düğümünü kendisi seçer. |
| `MINIMAX_DIFFUSION_MODEL` | `minimax_h3_ref2va_pruned_fp8_scaled.safetensors` | MiniMax H3 varyantı. |

### Geliştirme (opsiyonel)

| Değişken | Varsayılan | Ne işe yarar |
| --- | --- | --- |
| `DEV_MOCK_MODE` | `0` | ComfyUI olmadan sahte çıktı üretir; arayüz geliştirirken işe yarar. |
| `PROGRESS_PERSIST_INTERVAL` | `10` | İlerleme yüzdesinin Drive'a yazılma sıklığı (saniye). |
| `GOOGLE_DRIVE_MOUNT_PATH` / `DRIVE_PROJECT_ROOT` | `/content/drive/MyDrive` · `.../OzzyVision-Lab` | Drive dizin yapısını taşımak isterseniz. |

---

## Lisans

Bu depodaki kaynak kod [MIT Lisansı](LICENSE) altındadır — Copyright (c) 2026 OzzyAi-Labs.

### Üçüncü taraf bileşenler

MIT lisansı yalnızca bu depodaki kodu kapsar. Aşağıdakiler depoya dahil **edilmez**;
kurulum sırasında ayrıca indirilir ve kendi lisanslarına tabidir:

| Bileşen | Lisans | Not |
| --- | --- | --- |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | GPL-3.0 | Notebook tarafından ayrıca klonlanır; bu proje ona yalnızca HTTP API üzerinden bağlanır. |
| ComfyUI custom node'ları (GGUF, VideoHelperSuite, LTXVideo) | Kendi depolarına bakınız | Ayrıca klonlanır. |
| FastAPI, uvicorn, React, Vite, lucide-react | MIT / BSD / Apache-2.0 | `pip` ve `npm` ile kurulur. |
| [LTX-2.5 model ağırlıkları](https://huggingface.co/Lightricks/LTX-2.5) | LTX-2 Community License | İndirmeden önce Hugging Face üzerinden kabul etmeniz gerekir. |
| [MiniMax H3 model ağırlıkları](https://huggingface.co/Comfy-Org/MiniMax-H3) | MiniMax H3 Community License | Ticari kullanım şartları için lisansı okuyun. |

> Model ağırlıklarının lisansları MIT değildir ve kullanım kısıtları içerebilir.
> Ürettiğiniz videoları ticari olarak kullanacaksanız ilgili model lisansını okuyun.

## Teşekkürler

- **[Lightricks](https://github.com/Lightricks/LTX-Video):** LTX-Video ve LTX-2.5 açık kaynak modelleri için.
- **[MiniMax](https://github.com/MiniMax-AI):** MiniMax H3 Omni-Reference video ve ses üretimi için.
- **[ComfyUI](https://github.com/comfyanonymous/ComfyUI):** Esnek ve güçlü düğüm tabanlı çıkarım motoru için.
- **[Anthropic](https://modelcontextprotocol.io/):** Model Context Protocol (MCP) standardı için.

---

<div align="center">
  <sub>© 2026 <b>OzzyAi-Labs</b> · MIT Lisansı</sub>
</div>
