import React, { useState, useEffect, useRef } from 'react';
import {
  Upload, Wand2, Play, Sparkles, Sliders, Film, Camera, Clock,
  Maximize2, Eye, RefreshCw, CheckCircle2, AlertCircle, Trash2, HelpCircle,
  Volume2, VolumeX, Layers, Video, Mic, MessageSquare, Plus, Info, Image as ImageIcon,
  Download, X, Link, Check, ExternalLink
} from 'lucide-react';
import {
  uploadAsset, enhancePromptApi, createJob,
  fetchLoras, downloadLora, fetchLoraDownloadProgress, deleteLora
} from '../services/api';

export default function CreateStudio({
  cameraPresets,
  activeJob,
  onJobCreated,
  initialSettings,
  onClearInitialSettings
}) {
  // 1. Model Seçimi: 'ltx25' | 'minimax_h3'
  const [model, setModel] = useState('minimax_h3');

  // Ortak Form State'leri
  const [prompt, setPrompt] = useState('');
  const [negativePrompt, setNegativePrompt] = useState('worst quality, low quality, deformed, blurry, flickering, artifacts, distorted, static, jittery');
  const [showNegative, setShowNegative] = useState(false);
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [duration, setDuration] = useState(8);
  const [quality, setQuality] = useState('standard');
  const [fps, setFps] = useState(24);
  const [seed, setSeed] = useState(-1);
  const [isRandomSeed, setIsRandomSeed] = useState(true);
  const [enhancePrompt, setEnhancePrompt] = useState(true);

  // LTX-2.5 Özel State'leri
  const [ltxMode, setLtxMode] = useState('image_to_video'); // 'image_to_video' | 'text_to_video'
  const [camera, setCamera] = useState('auto');
  const [motionStrength, setMotionStrength] = useState('medium');
  const [imageFidelity, setImageFidelity] = useState(0.95);
  const [ltxAudio, setLtxAudio] = useState(true);
  const [ltxAssetId, setLtxAssetId] = useState(null);
  const [ltxPreviewUrl, setLtxPreviewUrl] = useState(null);

  // MiniMax H3 Özel State'leri (Omni-Reference)
  // refImages: [{ asset_id, filename, preview_url, media_type }] (Max 9)
  const [refImages, setRefImages] = useState([]);
  // refVideos: [{ asset_id, filename, preview_url, media_type }] (Max 3)
  const [refVideos, setRefVideos] = useState([]);
  // refAudios: [{ asset_id, filename, preview_url, media_type }] (Max 3)
  const [refAudios, setRefAudios] = useState([]);
  // refImageSize: 'match' (hızlı) | 'max' (2048px yüksek sadakat)
  const [refImageSize, setRefImageSize] = useState('match');
  const [selectedLanguage, setSelectedLanguage] = useState('Turkish');

  // UI Durumları
  const [isUploading, setIsUploading] = useState(false);
  const [isEnhancing, setIsEnhancing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);

  // LoRA State'leri (Universal: Hem LTX Hem MiniMax)
  const [availableLoras, setAvailableLoras] = useState([]);
  const [selectedLoras, setSelectedLoras] = useState([]); // [{ name: string, strength: number }]
  const [showLoraModal, setShowLoraModal] = useState(false);
  const [loraUrl, setLoraUrl] = useState('');
  const [loraFilename, setLoraFilename] = useState('');
  const [activeDownloadTask, setActiveDownloadTask] = useState(null);
  const [isStartingDownload, setIsStartingDownload] = useState(false);
  const [loraModalError, setLoraModalError] = useState(null);
  const [isLoadingLoras, setIsLoadingLoras] = useState(false);

  // LoRA listesini çek
  const loadLoras = async () => {
    setIsLoadingLoras(true);
    try {
      const res = await fetchLoras();
      setAvailableLoras(res.loras || []);
    } catch (err) {
      console.error('[LoadLoras Error]', err);
    } finally {
      setIsLoadingLoras(false);
    }
  };

  useEffect(() => {
    loadLoras();
  }, []);

  // Aktif indirme takibi (Colab polling)
  useEffect(() => {
    if (!activeDownloadTask || activeDownloadTask.status === 'completed' || activeDownloadTask.status === 'failed') {
      return;
    }
    const interval = setInterval(async () => {
      try {
        const res = await fetchLoraDownloadProgress(activeDownloadTask.id);
        if (res && res.task) {
          setActiveDownloadTask(res.task);
          if (res.task.status === 'completed') {
            loadLoras();
            setSelectedLoras(prev => {
              if (prev.some(l => l.name === res.task.filename)) return prev;
              if (prev.length >= 3) return prev;
              return [...prev, { name: res.task.filename, strength: 1.0 }];
            });
          }
        }
      } catch (e) {
        console.error('[Lora Poll Error]', e);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [activeDownloadTask]);

  const handleStartLoraDownload = async (e) => {
    if (e) e.preventDefault();
    if (!loraUrl.trim()) {
      setLoraModalError('Lütfen geçerli bir indirme bağlantısı (URL) girin.');
      return;
    }
    setIsStartingDownload(true);
    setLoraModalError(null);
    try {
      const res = await downloadLora({
        url: loraUrl.trim(),
        filename: loraFilename.trim() || undefined
      });
      setActiveDownloadTask(res.task);
      setLoraUrl('');
      setLoraFilename('');
    } catch (err) {
      setLoraModalError(err.message || 'İndirme başlatılamadı.');
    } finally {
      setIsStartingDownload(false);
    }
  };

  const handleAddLora = (loraName) => {
    if (selectedLoras.some(l => l.name === loraName)) return;
    if (selectedLoras.length >= 3) {
      alert('En fazla 3 LoRA modeli ekleyebilirsiniz.');
      return;
    }
    setSelectedLoras(prev => [...prev, { name: loraName, strength: 1.0 }]);
  };

  const handleRemoveLora = (loraName) => {
    setSelectedLoras(prev => prev.filter(l => l.name !== loraName));
  };

  const handleUpdateLoraStrength = (loraName, strength) => {
    setSelectedLoras(prev => prev.map(l => l.name === loraName ? { ...l, strength: parseFloat(strength) } : l));
  };

  const handleDeleteLoraDisk = async (loraName) => {
    if (!window.confirm(`'${loraName}' LoRA modelini diskten ve Drive'dan kalıcı olarak silmek istediğinize emin misiniz?`)) return;
    try {
      await deleteLora(loraName);
      handleRemoveLora(loraName);
      loadLoras();
    } catch (err) {
      alert('Silinemedi: ' + err.message);
    }
  };

  // Dosya Yükleme Referansları
  const ltxFileInputRef = useRef(null);
  const minimaxImageInputRef = useRef(null);
  const minimaxVideoInputRef = useRef(null);
  const minimaxAudioInputRef = useRef(null);
  const promptTextareaRef = useRef(null);

  // Toplam referans sayısı (MiniMax H3 kısıtı: max 12)
  const totalRefFiles = refImages.length + refVideos.length + refAudios.length;

  // Model değiştiğinde varsayılan süre ve en-boy oranını optimize et
  const handleModelSwitch = (newModel) => {
    setModel(newModel);
    if (newModel === 'minimax_h3') {
      if (duration < 4) setDuration(8);
      if (duration > 15) setDuration(15);
    } else {
      if (duration > 8) setDuration(5);
    }
  };

  // Galeri'den veya geçmişten gelen ayarları geri yükle
  useEffect(() => {
    if (initialSettings) {
      if (initialSettings.model) setModel(initialSettings.model);
      if (initialSettings.prompt) setPrompt(initialSettings.prompt);
      if (initialSettings.aspect_ratio) setAspectRatio(initialSettings.aspect_ratio);
      if (initialSettings.duration) setDuration(initialSettings.duration);
      if (initialSettings.quality) setQuality(initialSettings.quality);
      if (initialSettings.seed !== undefined) {
        setSeed(initialSettings.seed);
        setIsRandomSeed(initialSettings.seed === -1);
      }
      if (initialSettings.camera) setCamera(initialSettings.camera);
      if (initialSettings.image_fidelity) setImageFidelity(initialSettings.image_fidelity);
      if (initialSettings.audio !== undefined) setLtxAudio(initialSettings.audio);

      if (initialSettings.asset_id) {
        setLtxAssetId(initialSettings.asset_id);
        setLtxPreviewUrl(`/api/assets/${initialSettings.asset_id}`);
        setLtxMode('image_to_video');
      }

      if (initialSettings.ref_images && Array.isArray(initialSettings.ref_images)) {
        setRefImages(initialSettings.ref_images.map((id, idx) => ({
          asset_id: id,
          filename: `Picture_${idx + 1}.png`,
          preview_url: `/api/assets/${id}`,
          media_type: 'image'
        })));
      }
      if (initialSettings.ref_videos && Array.isArray(initialSettings.ref_videos)) {
        setRefVideos(initialSettings.ref_videos.map((id, idx) => ({
          asset_id: id,
          filename: `Video_${idx + 1}.mp4`,
          preview_url: `/api/assets/${id}`,
          media_type: 'video'
        })));
      }
      if (initialSettings.ref_audios && Array.isArray(initialSettings.ref_audios)) {
        setRefAudios(initialSettings.ref_audios.map((id, idx) => ({
          asset_id: id,
          filename: `Audio_${idx + 1}.wav`,
          preview_url: `/api/assets/${id}`,
          media_type: 'audio'
        })));
      }
      if (initialSettings.ref_image_size) setRefImageSize(initialSettings.ref_image_size);
      if (initialSettings.loras && Array.isArray(initialSettings.loras)) setSelectedLoras(initialSettings.loras);

      if (onClearInitialSettings) onClearInitialSettings();
    }
  }, [initialSettings]);

  // Klavye kısayolu (Ctrl + Enter)
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        handleGenerate();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [model, prompt, ltxMode, ltxAssetId, camera, motionStrength, imageFidelity, aspectRatio, duration, quality, fps, seed, isRandomSeed, enhancePrompt, refImages, refVideos, refAudios, refImageSize]);

  // Prompt metin alanında imlecin olduğu yere metin yapıştırıcı
  const insertTextAtCursor = (textToInsert) => {
    const textarea = promptTextareaRef.current;
    if (!textarea) {
      setPrompt((prev) => (prev ? `${prev} ${textToInsert}` : textToInsert));
      return;
    }
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const current = textarea.value;
    const before = current.substring(0, start);
    const after = current.substring(end);
    const updated = before + (before.endsWith(' ') || !before ? '' : ' ') + textToInsert + (after.startsWith(' ') || !after ? '' : ' ') + after;
    setPrompt(updated);
    setTimeout(() => {
      textarea.focus();
      const newPos = start + textToInsert.length + 1;
      textarea.setSelectionRange(newPos, newPos);
    }, 50);
  };

  // Diyalog Şablonu Ekle
  const handleInsertDialogue = (lang = selectedLanguage) => {
    insertTextAtCursor(`<d>[${lang}] Konuşma metnini buraya yazın</d>`);
  };

  // LTX Tekil Görsel Yükleme
  const handleLtxImageUpload = async (file) => {
    if (!file) return;
    setIsUploading(true);
    setErrorMessage(null);
    try {
      const res = await uploadAsset(file);
      setLtxAssetId(res.asset_id);
      setLtxPreviewUrl(res.preview_url);
    } catch (err) {
      setErrorMessage('Görsel yüklenemedi: ' + err.message);
    } finally {
      setIsUploading(false);
    }
  };

  // MiniMax H3 Çoklu Medya Yükleme (Görsel / Video / Ses)
  const handleMinimaxMediaUpload = async (files, expectedType) => {
    if (!files || files.length === 0) return;
    setIsUploading(true);
    setErrorMessage(null);

    try {
      for (const file of Array.from(files)) {
        if (totalRefFiles >= 12) {
          setErrorMessage('MiniMax H3 için toplam maksimum 12 referans dosya sınırına ulaşıldı.');
          break;
        }

        const res = await uploadAsset(file);
        const item = {
          asset_id: res.asset_id,
          filename: res.filename || file.name,
          preview_url: res.preview_url,
          media_type: res.media_type || expectedType
        };

        if (res.media_type === 'video' || expectedType === 'video') {
          if (refVideos.length >= 3) {
            setErrorMessage('En fazla 3 referans video klibi eklenebilir.');
            continue;
          }
          setRefVideos((prev) => [...prev, item]);
        } else if (res.media_type === 'audio' || expectedType === 'audio') {
          if (refAudios.length >= 3) {
            setErrorMessage('En fazla 3 referans ses klibi eklenebilir.');
            continue;
          }
          setRefAudios((prev) => [...prev, item]);
        } else {
          if (refImages.length >= 9) {
            setErrorMessage('En fazla 9 referans görsel eklenebilir.');
            continue;
          }
          setRefImages((prev) => [...prev, item]);
        }
      }
    } catch (err) {
      setErrorMessage('Medya yüklenirken hata oluştu: ' + err.message);
    } finally {
      setIsUploading(false);
    }
  };

  // Prompt Zenginleştirme
  const handleEnhance = async () => {
    if (!prompt.trim()) return;
    setIsEnhancing(true);
    try {
      const res = await enhancePromptApi(prompt);
      setPrompt(res.enhanced);
    } catch (err) {
      console.error(err);
    } finally {
      setIsEnhancing(false);
    }
  };

  // Üretim Başlatma (Generate)
  const handleGenerate = async () => {
    setErrorMessage(null);

    // LTX-2.5 Doğrulamaları
    if (model === 'ltx25') {
      if (!prompt.trim() && ltxMode === 'text_to_video') {
        setErrorMessage('Lütfen video için bir prompt yazın.');
        return;
      }
      if (ltxMode === 'image_to_video' && !ltxAssetId) {
        setErrorMessage('Lütfen bir referans görsel yükleyin.');
        return;
      }
    }

    // MiniMax H3 Doğrulamaları
    if (model === 'minimax_h3') {
      if (!prompt.trim()) {
        setErrorMessage('Lütfen video sahnesi veya referanslar için bir prompt açıklaması yazın.');
        return;
      }
      if (refImages.length > 9) {
        setErrorMessage('En fazla 9 adet referans görsel yüklenebilir.');
        return;
      }
      if (refVideos.length > 3) {
        setErrorMessage('En fazla 3 adet referans video yüklenebilir.');
        return;
      }
      if (refAudios.length > 3) {
        setErrorMessage('En fazla 3 adet referans ses yüklenebilir.');
        return;
      }
      if (totalRefFiles > 12) {
        setErrorMessage('Toplam referans sayısı (Görsel + Video + Ses) 12\'yi geçemez.');
        return;
      }
    }

    setIsSubmitting(true);

    let payload = {};
    if (model === 'ltx25') {
      payload = {
        model: 'ltx25',
        mode: ltxMode,
        prompt,
        negative_prompt: negativePrompt,
        camera,
        motion_strength: motionStrength,
        image_fidelity: parseFloat(imageFidelity),
        aspect_ratio: aspectRatio,
        duration: parseInt(duration),
        quality,
        fps: parseInt(fps),
        seed: isRandomSeed ? -1 : parseInt(seed),
        enhance_prompt: enhancePrompt,
        audio: ltxAudio,
        loras: selectedLoras,
        asset_id: ltxMode === 'image_to_video' ? ltxAssetId : null
      };
    } else {
      payload = {
        model: 'minimax_h3',
        prompt,
        negative_prompt: negativePrompt,
        camera,
        aspect_ratio: aspectRatio,
        duration: parseInt(duration),
        quality,
        fps: 24,
        seed: isRandomSeed ? -1 : parseInt(seed),
        enhance_prompt: enhancePrompt,
        ref_images: refImages.map((i) => i.asset_id),
        ref_videos: refVideos.map((v) => v.asset_id),
        ref_audios: refAudios.map((a) => a.asset_id),
        ref_image_size: refImageSize,
        loras: selectedLoras,
        audio: true
      };
    }

    try {
      const res = await createJob(payload);
      if (onJobCreated) onJobCreated(res.job);
    } catch (err) {
      setErrorMessage('Üretim başlatılamadı: ' + err.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="studio-layout">
      {/* SOL KONTROL PANELİ */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>

        {/* 1. MODEL SEÇİCİ (LTX-2.5 ↔ MINIMAX H3) */}
        <div>
          <label style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px', display: 'block' }}>
            Model
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', background: 'rgba(0,0,0,0.4)', padding: '5px', borderRadius: '14px', border: '1px solid var(--border-subtle)' }}>
            
            {/* MiniMax H3 Butonu */}
            <button
              type="button"
              onClick={() => handleModelSwitch('minimax_h3')}
              style={{
                padding: '12px 10px',
                borderRadius: '10px',
                border: model === 'minimax_h3' ? '1px solid #a855f7' : 'none',
                background: model === 'minimax_h3' ? 'linear-gradient(135deg, rgba(168, 85, 247, 0.25) 0%, rgba(99, 102, 241, 0.2) 100%)' : 'transparent',
                color: model === 'minimax_h3' ? '#ffffff' : 'var(--text-secondary)',
                cursor: 'pointer',
                textAlign: 'left',
                transition: 'all 0.2s',
                display: 'flex',
                flexDirection: 'column',
                gap: '4px'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: '13px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Layers size={15} color={model === 'minimax_h3' ? '#c084fc' : '#94a3b8'} />
                  MiniMax H3 Omni
                </span>
                <span style={{ fontSize: '9px', fontWeight: 800, padding: '2px 6px', borderRadius: '4px', background: 'linear-gradient(135deg, #a855f7, #6366f1)', color: '#fff', letterSpacing: '0.04em' }}>
                  FP8
                </span>
              </div>
              <span style={{ fontSize: '10px', color: model === 'minimax_h3' ? '#e9d5ff' : 'var(--text-muted)' }}>
                9 görsel · 3 video · 3 ses referansı · 32 kHz stereo
              </span>
            </button>

            {/* LTX-2.5 Butonu */}
            <button
              type="button"
              onClick={() => handleModelSwitch('ltx25')}
              style={{
                padding: '12px 10px',
                borderRadius: '10px',
                border: model === 'ltx25' ? '1px solid #6366f1' : 'none',
                background: model === 'ltx25' ? 'linear-gradient(135deg, rgba(99, 102, 241, 0.25) 0%, rgba(59, 130, 246, 0.15) 100%)' : 'transparent',
                color: model === 'ltx25' ? '#ffffff' : 'var(--text-secondary)',
                cursor: 'pointer',
                textAlign: 'left',
                transition: 'all 0.2s',
                display: 'flex',
                flexDirection: 'column',
                gap: '4px'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: '13px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Wand2 size={15} color={model === 'ltx25' ? '#818cf8' : '#94a3b8'} />
                  LTX-2.5 Distilled
                </span>
                <span style={{ fontSize: '9px', fontWeight: 800, padding: '2px 6px', borderRadius: '4px', background: 'linear-gradient(135deg, #6366f1, #3b82f6)', color: '#fff', letterSpacing: '0.04em' }}>
                  8 ADIM
                </span>
              </div>
              <span style={{ fontSize: '10px', color: model === 'ltx25' ? '#c7d2fe' : 'var(--text-muted)' }}>
                Hızlı üretim · 24 FPS · dahili ses
              </span>
            </button>

          </div>
        </div>

        {/* 2. MODEL BAZLI GİRDİ PANELİ */}

        {/* A. LTX-2.5 MOD SEÇİMİ VE TEKLİ GÖRSEL YÜKLEME */}
        {model === 'ltx25' && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', background: 'rgba(0,0,0,0.3)', padding: '4px', borderRadius: '12px' }}>
              <button
                type="button"
                onClick={() => setLtxMode('image_to_video')}
                style={{
                  padding: '9px',
                  borderRadius: '8px',
                  border: 'none',
                  background: ltxMode === 'image_to_video' ? 'var(--accent-primary)' : 'transparent',
                  color: ltxMode === 'image_to_video' ? '#ffffff' : 'var(--text-secondary)',
                  fontWeight: 600,
                  fontSize: '12px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px',
                  transition: 'all 0.2s'
                }}
              >
                <Upload size={14} />
                Image to Video
              </button>
              <button
                type="button"
                onClick={() => setLtxMode('text_to_video')}
                style={{
                  padding: '9px',
                  borderRadius: '8px',
                  border: 'none',
                  background: ltxMode === 'text_to_video' ? 'var(--accent-primary)' : 'transparent',
                  color: ltxMode === 'text_to_video' ? '#ffffff' : 'var(--text-secondary)',
                  fontWeight: 600,
                  fontSize: '12px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '6px',
                  transition: 'all 0.2s'
                }}
              >
                <Wand2 size={14} />
                Text to Video
              </button>
            </div>

            {/* LTX-2.5 Tekli Görsel Kutusu */}
            {ltxMode === 'image_to_video' && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Camera size={14} color="#818cf8" />
                    Referans Görsel (Reference Image)
                  </label>
                  {ltxAssetId && <span className="badge badge-gpu" style={{ fontSize: '10px' }}>{ltxAssetId}</span>}
                </div>

                {ltxPreviewUrl ? (
                  <div style={{ position: 'relative', borderRadius: '12px', overflow: 'hidden', border: '1px solid var(--border-active)', height: '160px', background: '#000' }}>
                    <img src={ltxPreviewUrl} alt="Reference" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
                    <button
                      type="button"
                      onClick={() => { setLtxAssetId(null); setLtxPreviewUrl(null); }}
                      style={{ position: 'absolute', top: '8px', right: '8px', background: 'rgba(244, 63, 94, 0.8)', color: '#fff', border: 'none', borderRadius: '8px', padding: '6px', cursor: 'pointer' }}
                      title="Görseli Kaldır"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ) : (
                  <div
                    onClick={() => ltxFileInputRef.current?.click()}
                    style={{ border: '2px dashed rgba(255, 255, 255, 0.15)', borderRadius: '12px', padding: '24px 16px', textAlign: 'center', cursor: 'pointer', background: 'rgba(255, 255, 255, 0.02)' }}
                  >
                    <input type="file" ref={ltxFileInputRef} onChange={(e) => e.target.files && handleLtxImageUpload(e.target.files[0])} accept="image/*" style={{ display: 'none' }} />
                    <Upload size={22} color="#818cf8" style={{ margin: '0 auto 6px' }} />
                    <p style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                      {isUploading ? 'Görsel Yükleniyor...' : 'Görsel seçin veya buraya bırakın'}
                    </p>
                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>PNG, JPG, WEBP</p>
                  </div>
                )}
              </div>
            )}

            {/* LTX Image Fidelity Slider */}
            {ltxMode === 'image_to_video' && (
              <div style={{ background: 'rgba(255,255,255,0.02)', padding: '12px', borderRadius: '12px', border: '1px solid var(--border-subtle)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                  <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Eye size={13} color="#a855f7" />
                    Image Fidelity (Karakter Koruma)
                  </label>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', fontWeight: 700, color: '#a855f7' }}>
                    {Math.round(imageFidelity * 100)}%
                  </span>
                </div>
                <input type="range" min="0.50" max="1.00" step="0.01" value={imageFidelity} onChange={(e) => setImageFidelity(e.target.value)} />
              </div>
            )}
          </>
        )}

        {/* B. MINIMAX H3 ÇOK KİPLİ REFERANS HAVUZU (MULTI-MODAL VAULT) */}
        {model === 'minimax_h3' && (
          <div style={{ background: 'rgba(168, 85, 247, 0.04)', padding: '16px', borderRadius: '16px', border: '1px solid rgba(168, 85, 247, 0.25)', display: 'flex', flexDirection: 'column', gap: '14px' }}>
            
            {/* Havuz Başlığı & Toplam Sayaç */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ fontSize: '13px', fontWeight: 700, color: '#e9d5ff', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Layers size={14} color="#c084fc" />
                  Omni-Reference Havuzu
                </h3>
                <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  Karakter, hareket ve ses referansları
                </p>
              </div>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: 700,
                  padding: '4px 10px',
                  borderRadius: '8px',
                  fontFamily: 'var(--font-mono)',
                  background: totalRefFiles >= 12 ? 'rgba(244, 63, 94, 0.2)' : 'rgba(168, 85, 247, 0.15)',
                  color: totalRefFiles >= 12 ? '#f43f5e' : '#c084fc',
                  border: `1px solid ${totalRefFiles >= 12 ? 'rgba(244, 63, 94, 0.4)' : 'rgba(168, 85, 247, 0.3)'}`
                }}
              >
                {totalRefFiles} / 12 Dosya
              </span>
            </div>

            {/* 1. Görseller Alt Alanı (Max 9) */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                  <ImageIcon size={13} color="#a855f7" />
                  Görseller ({refImages.length}/9)
                </span>
                <button
                  type="button"
                  disabled={refImages.length >= 9 || totalRefFiles >= 12}
                  onClick={() => minimaxImageInputRef.current?.click()}
                  className="btn-secondary"
                  style={{ padding: '3px 8px', fontSize: '10px', borderRadius: '6px', opacity: (refImages.length >= 9 || totalRefFiles >= 12) ? 0.5 : 1 }}
                >
                  <Plus size={11} /> Görsel Ekle
                </button>
                <input
                  type="file"
                  ref={minimaxImageInputRef}
                  multiple
                  accept="image/*"
                  onChange={(e) => handleMinimaxMediaUpload(e.target.files, 'image')}
                  style={{ display: 'none' }}
                />
              </div>

              {refImages.length === 0 ? (
                <div
                  onClick={() => minimaxImageInputRef.current?.click()}
                  style={{ border: '1px dashed rgba(168, 85, 247, 0.25)', borderRadius: '10px', padding: '12px', textAlign: 'center', cursor: 'pointer', background: 'rgba(0,0,0,0.2)' }}
                >
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    Karakter yüzü, kıyafet veya ortam referansı ekleyin (9 adede kadar)
                  </span>
                </div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(80px, 1fr))', gap: '8px' }}>
                  {refImages.map((img, idx) => {
                    const tag = `<Picture ${idx + 1}>`;
                    return (
                      <div
                        key={img.asset_id}
                        style={{ position: 'relative', borderRadius: '8px', overflow: 'hidden', height: '75px', border: '1px solid rgba(168, 85, 247, 0.4)', background: '#000' }}
                      >
                        <img src={img.preview_url} alt={tag} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                        
                        {/* Etiketi Prompta Ekleyici Rozet */}
                        <button
                          type="button"
                          onClick={() => insertTextAtCursor(tag)}
                          title="Tıkla: Bu etiketi prompta ekle"
                          style={{
                            position: 'absolute',
                            bottom: '2px',
                            left: '2px',
                            right: '2px',
                            background: 'rgba(0,0,0,0.85)',
                            color: '#c084fc',
                            border: '1px solid rgba(168, 85, 247, 0.5)',
                            borderRadius: '4px',
                            padding: '2px 0',
                            fontSize: '9px',
                            fontWeight: 700,
                            fontFamily: 'var(--font-mono)',
                            cursor: 'pointer'
                          }}
                        >
                          {tag}
                        </button>

                        <button
                          type="button"
                          onClick={() => setRefImages((prev) => prev.filter((_, i) => i !== idx))}
                          style={{ position: 'absolute', top: '3px', right: '3px', background: 'rgba(244, 63, 94, 0.85)', color: '#fff', border: 'none', borderRadius: '4px', padding: '3px', cursor: 'pointer' }}
                        >
                          <Trash2 size={10} />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* 2. Videolar Alt Alanı (Max 3, 2-15s) */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                  <Video size={13} color="#06b6d4" />
                  Videolar ({refVideos.length}/3, 2–15s)
                </span>
                <button
                  type="button"
                  disabled={refVideos.length >= 3 || totalRefFiles >= 12}
                  onClick={() => minimaxVideoInputRef.current?.click()}
                  className="btn-secondary"
                  style={{ padding: '3px 8px', fontSize: '10px', borderRadius: '6px', opacity: (refVideos.length >= 3 || totalRefFiles >= 12) ? 0.5 : 1 }}
                >
                  <Plus size={11} /> Video Ekle
                </button>
                <input
                  type="file"
                  ref={minimaxVideoInputRef}
                  multiple
                  accept="video/*"
                  onChange={(e) => handleMinimaxMediaUpload(e.target.files, 'video')}
                  style={{ display: 'none' }}
                />
              </div>

              {refVideos.length === 0 ? (
                <div
                  onClick={() => minimaxVideoInputRef.current?.click()}
                  style={{ border: '1px dashed rgba(6, 182, 212, 0.25)', borderRadius: '10px', padding: '10px', textAlign: 'center', cursor: 'pointer', background: 'rgba(0,0,0,0.2)' }}
                >
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    Kamera veya hareket referansı için video yükleyin (Maks. 3 klip)
                  </span>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {refVideos.map((vid, idx) => {
                    const tag = `<Video ${idx + 1}>`;
                    return (
                      <div
                        key={vid.asset_id}
                        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(0,0,0,0.3)', padding: '6px 10px', borderRadius: '8px', border: '1px solid rgba(6, 182, 212, 0.3)' }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <Video size={13} color="#06b6d4" />
                          <button
                            type="button"
                            onClick={() => insertTextAtCursor(tag)}
                            style={{ background: 'rgba(6, 182, 212, 0.2)', border: '1px solid rgba(6, 182, 212, 0.4)', borderRadius: '4px', padding: '2px 6px', fontSize: '10px', fontWeight: 700, color: '#38bdf8', cursor: 'pointer', fontFamily: 'var(--font-mono)' }}
                          >
                            {tag}
                          </button>
                          <span style={{ fontSize: '11px', color: 'var(--text-secondary)', maxWidth: '140px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {vid.filename}
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={() => setRefVideos((prev) => prev.filter((_, i) => i !== idx))}
                          style={{ background: 'transparent', border: 'none', color: '#f43f5e', cursor: 'pointer', padding: '4px' }}
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* 3. Sesler Alt Alanı (Max 3, 2-15s - Timbre & Music) */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                  <Mic size={13} color="#10b981" />
                  Sesler ({refAudios.length}/3, 2–15s - Ses Tınısı & BGM)
                </span>
                <button
                  type="button"
                  disabled={refAudios.length >= 3 || totalRefFiles >= 12}
                  onClick={() => minimaxAudioInputRef.current?.click()}
                  className="btn-secondary"
                  style={{ padding: '3px 8px', fontSize: '10px', borderRadius: '6px', opacity: (refAudios.length >= 3 || totalRefFiles >= 12) ? 0.5 : 1 }}
                >
                  <Plus size={11} /> Ses Ekle
                </button>
                <input
                  type="file"
                  ref={minimaxAudioInputRef}
                  multiple
                  accept="audio/*"
                  onChange={(e) => handleMinimaxMediaUpload(e.target.files, 'audio')}
                  style={{ display: 'none' }}
                />
              </div>

              {refAudios.length === 0 ? (
                <div
                  onClick={() => minimaxAudioInputRef.current?.click()}
                  style={{ border: '1px dashed rgba(16, 185, 129, 0.25)', borderRadius: '10px', padding: '10px', textAlign: 'center', cursor: 'pointer', background: 'rgba(0,0,0,0.2)' }}
                >
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    Karakter ses tonu veya arka plan müziği için ses yükleyin
                  </span>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {refAudios.map((aud, idx) => {
                    const tag = `<Audio ${idx + 1}>`;
                    return (
                      <div
                        key={aud.asset_id}
                        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(0,0,0,0.3)', padding: '6px 10px', borderRadius: '8px', border: '1px solid rgba(16, 185, 129, 0.3)' }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <Mic size={13} color="#10b981" />
                          <button
                            type="button"
                            onClick={() => insertTextAtCursor(tag)}
                            style={{ background: 'rgba(16, 185, 129, 0.2)', border: '1px solid rgba(16, 185, 129, 0.4)', borderRadius: '4px', padding: '2px 6px', fontSize: '10px', fontWeight: 700, color: '#34d399', cursor: 'pointer', fontFamily: 'var(--font-mono)' }}
                          >
                            {tag}
                          </button>
                          <span style={{ fontSize: '11px', color: 'var(--text-secondary)', maxWidth: '140px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {aud.filename}
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={() => setRefAudios((prev) => prev.filter((_, i) => i !== idx))}
                          style={{ background: 'transparent', border: 'none', color: '#f43f5e', cursor: 'pointer', padding: '4px' }}
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Referans Çözünürlük Sadakati (ref_image_size) */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '6px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
              <div>
                <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', display: 'block' }}>
                  Referans Ölçekleme (ref_image_size)
                </span>
                <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                  {refImageSize === 'match' ? 'Hedef çözünürlüğe indirger (Hızlı)' : '2048px detayı korur (Yüksek Sadakat)'}
                </span>
              </div>
              <div style={{ display: 'flex', gap: '4px' }}>
                <button
                  type="button"
                  onClick={() => setRefImageSize('match')}
                  style={{
                    padding: '4px 8px',
                    borderRadius: '6px',
                    fontSize: '11px',
                    fontWeight: 600,
                    cursor: 'pointer',
                    background: refImageSize === 'match' ? 'rgba(168, 85, 247, 0.25)' : 'transparent',
                    border: refImageSize === 'match' ? '1px solid #a855f7' : '1px solid var(--border-subtle)',
                    color: refImageSize === 'match' ? '#c084fc' : 'var(--text-muted)'
                  }}
                >
                  Match
                </button>
                <button
                  type="button"
                  onClick={() => setRefImageSize('max')}
                  style={{
                    padding: '4px 8px',
                    borderRadius: '6px',
                    fontSize: '11px',
                    fontWeight: 600,
                    cursor: 'pointer',
                    background: refImageSize === 'max' ? 'rgba(168, 85, 247, 0.25)' : 'transparent',
                    border: refImageSize === 'max' ? '1px solid #a855f7' : '1px solid var(--border-subtle)',
                    color: refImageSize === 'max' ? '#c084fc' : 'var(--text-muted)'
                  }}
                >
                  Max (2K)
                </button>
              </div>
            </div>

          </div>
        )}

        {/* 3. PROMPT ALANI & DİYALOG ASİSTANI */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Film size={14} color="#6366f1" />
              Prompt (Sahne Açıklaması)
            </label>
            <div style={{ display: 'flex', gap: '6px' }}>
              <button
                type="button"
                onClick={handleEnhance}
                disabled={isEnhancing || !prompt.trim()}
                className="btn-secondary"
                style={{ padding: '4px 10px', fontSize: '11px', borderRadius: '6px' }}
              >
                <Sparkles size={12} color="#a855f7" />
                {isEnhancing ? 'Geliştiriliyor...' : '✨ Enhance'}
              </button>
            </div>
          </div>

          {/* MiniMax H3 Diyalog & Dudak Senkron Asistan Çubuğu */}
          {model === 'minimax_h3' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', overflowX: 'auto', paddingBottom: '2px' }}>
              <button
                type="button"
                onClick={() => handleInsertDialogue()}
                style={{
                  padding: '4px 10px',
                  borderRadius: '6px',
                  background: 'rgba(168, 85, 247, 0.2)',
                  border: '1px solid rgba(168, 85, 247, 0.4)',
                  color: '#c084fc',
                  fontSize: '11px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  whiteSpace: 'nowrap'
                }}
              >
                <MessageSquare size={12} />
                + Diyalog Ekle
              </button>

              <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>Dil:</span>
              {['Turkish', 'English', 'German', 'Japanese', 'Spanish'].map((lang) => (
                <button
                  key={lang}
                  type="button"
                  onClick={() => {
                    setSelectedLanguage(lang);
                    handleInsertDialogue(lang);
                  }}
                  style={{
                    padding: '2px 6px',
                    borderRadius: '4px',
                    border: '1px solid var(--border-subtle)',
                    background: selectedLanguage === lang ? 'rgba(99, 102, 241, 0.2)' : 'rgba(255,255,255,0.02)',
                    color: selectedLanguage === lang ? '#818cf8' : 'var(--text-muted)',
                    fontSize: '10px',
                    cursor: 'pointer'
                  }}
                >
                  {lang}
                </button>
              ))}
            </div>
          )}

          <textarea
            ref={promptTextareaRef}
            className="input-textarea"
            rows={model === 'minimax_h3' ? 4 : 3}
            placeholder={
              model === 'minimax_h3'
                ? "Karakter <Picture 1> kameraya dönüp gülümsüyor, sesi <Audio 1> tınısında konuşuyor: <d>[Turkish] Merhaba, stüdyoya hoş geldiniz!</d> Kamera yavaşça yaklaşıyor..."
                : (ltxMode === 'image_to_video'
                    ? "Karakter yavaşça kameraya dönüp gülümsüyor, sinematik ışıklandırma..."
                    : "Sisli Tokyo sokağında yürüyen bir kadın, 35mm film, 8k...")
            }
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
        </div>

        {/* 4. KAMERA HAREKETİ (LTX-2.5 & MINIMAX H3) */}
        {cameraPresets.length > 0 && (
          <div>
            <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
              <Camera size={14} color="#06b6d4" />
              Kamera Hareketi (Camera Motion)
            </label>
            <select
              value={camera}
              onChange={(e) => setCamera(e.target.value)}
              style={{
                width: '100%',
                background: 'var(--bg-input)',
                border: '1px solid var(--border-subtle)',
                borderRadius: '12px',
                padding: '12px',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-heading)',
                fontSize: '13px',
                outline: 'none'
              }}
            >
              {cameraPresets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name_tr} ({p.name})
                </option>
              ))}
            </select>
          </div>
        )}

        {/* 5. EN-BOY ORANI (ASPECT RATIO) */}
        <div>
          <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '8px', display: 'flex', justifyContent: 'space-between' }}>
            <span>En-Boy Oranı (Aspect Ratio)</span>
            <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {model === 'minimax_h3' ? '768p Tabanlı' : '32 Modlu'}
            </span>
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: model === 'minimax_h3' ? 'repeat(6, 1fr)' : 'repeat(5, 1fr)', gap: '6px' }}>
            {(model === 'minimax_h3'
              ? ['16:9', '9:16', '1:1', '4:3', '3:4', '21:9']
              : ['16:9', '9:16', '1:1', '4:3', '21:9']
            ).map((ratio) => (
              <button
                key={ratio}
                type="button"
                onClick={() => setAspectRatio(ratio)}
                style={{
                  padding: '8px 2px',
                  borderRadius: '8px',
                  border: aspectRatio === ratio ? '1px solid var(--accent-primary)' : '1px solid var(--border-subtle)',
                  background: aspectRatio === ratio ? 'rgba(99, 102, 241, 0.15)' : 'rgba(255, 255, 255, 0.02)',
                  color: aspectRatio === ratio ? '#818cf8' : 'var(--text-secondary)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  fontWeight: 600,
                  cursor: 'pointer'
                }}
              >
                {ratio}
              </button>
            ))}
          </div>
        </div>

        {/* 6. VİDEO SÜRESİ (DURATION) */}
        <div style={{ background: 'rgba(255,255,255,0.02)', padding: '14px', borderRadius: '12px', border: '1px solid var(--border-subtle)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Clock size={13} color="#818cf8" />
              Video Süresi (Duration)
            </label>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 700, color: '#818cf8' }}>
                {duration} Saniye
              </span>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                ({model === 'minimax_h3' ? duration * 24 + 1 : 8 * Math.round((duration * fps - 1) / 8) + 1} Frame)
              </span>
            </div>
          </div>
          <input
            type="range"
            min={model === 'minimax_h3' ? 4 : 3}
            max={model === 'minimax_h3' ? 15 : 8}
            step="1"
            value={duration}
            onChange={(e) => setDuration(parseInt(e.target.value))}
            style={{ width: '100%', accentColor: '#818cf8' }}
          />
          <div style={{ display: 'grid', gridTemplateColumns: model === 'minimax_h3' ? 'repeat(6, 1fr)' : 'repeat(6, 1fr)', gap: '6px', marginTop: '8px' }}>
            {(model === 'minimax_h3' ? [4, 6, 8, 10, 12, 15] : [3, 4, 5, 6, 7, 8]).map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDuration(d)}
                style={{
                  padding: '6px 2px',
                  borderRadius: '6px',
                  border: duration === d ? '1px solid var(--accent-primary)' : '1px solid var(--border-subtle)',
                  background: duration === d ? 'rgba(99, 102, 241, 0.25)' : 'rgba(255, 255, 255, 0.02)',
                  color: duration === d ? '#818cf8' : 'var(--text-muted)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  fontWeight: 600,
                  cursor: 'pointer'
                }}
              >
                {d}s
              </button>
            ))}
          </div>
        </div>

        {/* 7. KALİTE (QUALITY) */}
        <div>
          <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Sliders size={12} color="#818cf8" />
            Kalite & Örnekleme (Quality)
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px' }}>
            {['draft', 'standard', 'high'].map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => setQuality(q)}
                style={{
                  padding: '8px 2px',
                  borderRadius: '8px',
                  border: quality === q ? '1px solid var(--accent-primary)' : '1px solid var(--border-subtle)',
                  background: quality === q ? 'rgba(99, 102, 241, 0.15)' : 'rgba(255, 255, 255, 0.02)',
                  color: quality === q ? '#818cf8' : 'var(--text-secondary)',
                  fontSize: '12px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  textTransform: 'capitalize'
                }}
              >
                {q}
              </button>
            ))}
          </div>
        </div>

        {/* 8. SES AYARI BİLGİSİ */}
        {model === 'minimax_h3' ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(168, 85, 247, 0.06)', padding: '10px 14px', borderRadius: '10px', border: '1px solid rgba(168, 85, 247, 0.25)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Volume2 size={16} color="#c084fc" />
              <div>
                <span style={{ fontSize: '12px', fontWeight: 600, color: '#e9d5ff', display: 'block' }}>
                  Doğal 32 kHz Stereo & Dudak Senkronu
                </span>
                <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                  MiniMax H3 video ve sesi aynı latent uzayında eşzamanlı üretir.
                </span>
              </div>
            </div>
            <span className="badge badge-gpu" style={{ fontSize: '10px', background: 'rgba(168, 85, 247, 0.2)', color: '#c084fc' }}>
              Aktif
            </span>
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(255,255,255,0.02)', padding: '10px 14px', borderRadius: '10px', border: '1px solid var(--border-subtle)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              {ltxAudio ? <Volume2 size={16} color="#818cf8" /> : <VolumeX size={16} color="var(--text-muted)" />}
              <div>
                <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', display: 'block' }}>
                  Doğal Ses Efekti (Native Audio)
                </span>
                <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                  {ltxAudio ? 'LTX-2.5 Audio VAE ile ambiyans ses üretilir' : 'Sessiz video üretilir'}
                </span>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setLtxAudio(!ltxAudio)}
              style={{
                padding: '5px 12px',
                borderRadius: '8px',
                border: ltxAudio ? '1px solid var(--accent-primary)' : '1px solid var(--border-subtle)',
                background: ltxAudio ? 'rgba(99, 102, 241, 0.25)' : 'rgba(255, 255, 255, 0.04)',
                color: ltxAudio ? '#818cf8' : 'var(--text-muted)',
                fontSize: '11px',
                fontWeight: 700,
                cursor: 'pointer',
                letterSpacing: '0.04em'
              }}
            >
              {ltxAudio ? '● ETKİN' : '○ DEVRE DIŞI'}
            </button>
          </div>
        )}

        {/* 9. LORA MODELLERİ (STİL & KARAKTER - HEM LTX HEM MINIMAX) */}
        <div style={{ background: 'rgba(255,255,255,0.02)', padding: '14px', borderRadius: '12px', border: '1px solid var(--border-subtle)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Sliders size={13} color="#c084fc" />
              <label style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>
                LoRA Model Katmanları (Stil & Efekt)
              </label>
              <span className="badge" style={{ fontSize: '10px', background: selectedLoras.length > 0 ? 'rgba(168, 85, 247, 0.2)' : 'rgba(255,255,255,0.05)', color: selectedLoras.length > 0 ? '#c084fc' : 'var(--text-muted)' }}>
                {selectedLoras.length} / 3
              </span>
            </div>

            {/* Cloud Hub / İndir Butonu */}
            <button
              type="button"
              onClick={() => setShowLoraModal(true)}
              className="btn-secondary"
              style={{
                padding: '4px 10px',
                borderRadius: '8px',
                fontSize: '11px',
                background: 'linear-gradient(135deg, rgba(168, 85, 247, 0.2), rgba(99, 102, 241, 0.15))',
                border: '1px solid rgba(168, 85, 247, 0.4)',
                color: '#c084fc',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                cursor: 'pointer'
              }}
            >
              <Download size={12} />
              ☁️ LoRA Hub & Yönet
            </button>
          </div>

          {/* Kütüphanedeki Hazır Modeller İçin Hızlı Ekleme Çubuğu (Chips) */}
          {availableLoras.filter(l => !selectedLoras.some(sl => sl.name === l.name)).length > 0 && selectedLoras.length < 3 && (
            <div style={{ marginTop: '12px', display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
              <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 600 }}>Kütüphane:</span>
              {availableLoras
                .filter(l => !selectedLoras.some(sl => sl.name === l.name))
                .slice(0, 4)
                .map(l => (
                  <button
                    key={l.name}
                    type="button"
                    onClick={() => handleAddLora(l.name)}
                    title={`${l.name} (${l.size_mb} MB) - Tıkla ve Modele Ekle`}
                    style={{
                      padding: '3px 8px',
                      borderRadius: '6px',
                      background: 'rgba(168, 85, 247, 0.12)',
                      border: '1px solid rgba(168, 85, 247, 0.3)',
                      color: '#d8b4fe',
                      fontSize: '10px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      cursor: 'pointer',
                      maxWidth: '160px',
                      transition: 'all 0.15s'
                    }}
                  >
                    <Plus size={10} />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {l.name.replace(/\.(safetensors|pt|bin)$/i, '')}
                    </span>
                  </button>
                ))}
              {availableLoras.filter(l => !selectedLoras.some(sl => sl.name === l.name)).length > 4 && (
                <button
                  type="button"
                  onClick={() => setShowLoraModal(true)}
                  style={{
                    padding: '3px 6px',
                    borderRadius: '6px',
                    background: 'rgba(255,255,255,0.04)',
                    border: '1px solid var(--border-subtle)',
                    color: 'var(--text-muted)',
                    fontSize: '10px',
                    cursor: 'pointer'
                  }}
                >
                  +{availableLoras.filter(l => !selectedLoras.some(sl => sl.name === l.name)).length - 4} model daha
                </button>
              )}
            </div>
          )}

          {/* Seçili LoRA'ların Listesi ve Güç Kaydırıcıları */}
          {selectedLoras.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '12px' }}>
              {selectedLoras.map((lora) => (
                <div
                  key={lora.name}
                  style={{
                    background: 'rgba(11, 14, 23, 0.9)',
                    border: '1px solid rgba(168, 85, 247, 0.35)',
                    borderRadius: '10px',
                    padding: '10px 12px'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <span
                      style={{ fontSize: '11px', fontWeight: 600, color: '#f1f5f9', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '240px' }}
                      title={lora.name}
                    >
                      {lora.name.replace(/\.(safetensors|pt|bin)$/i, '')}
                    </span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: '#c084fc', fontWeight: 700, background: 'rgba(168, 85, 247, 0.15)', padding: '2px 6px', borderRadius: '4px' }}>
                        {lora.strength >= 0 ? '+' : ''}{lora.strength.toFixed(2)}x
                      </span>
                      <button
                        type="button"
                        onClick={() => handleRemoveLora(lora.name)}
                        style={{ background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer', padding: '2px', display: 'flex', alignItems: 'center' }}
                        title="LoRA modelini kaldır"
                      >
                        <X size={13} />
                      </button>
                    </div>
                  </div>

                  <input
                    type="range"
                    min="-2.0"
                    max="2.0"
                    step="0.05"
                    value={lora.strength}
                    onChange={(e) => handleUpdateLoraStrength(lora.name, e.target.value)}
                    style={{ width: '100%', accentColor: '#a855f7', display: 'block' }}
                  />

                  {/* Hızlı Önayar Butonları (Preset Chips) */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '6px' }}>
                    <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>-2.0x (Ters)</span>
                    <div style={{ display: 'flex', gap: '4px' }}>
                      {[0.5, 0.8, 1.0, 1.25].map((preset) => (
                        <button
                          key={preset}
                          type="button"
                          onClick={() => handleUpdateLoraStrength(lora.name, preset)}
                          style={{
                            padding: '1px 6px',
                            borderRadius: '4px',
                            fontSize: '9px',
                            fontWeight: 600,
                            background: Math.abs(lora.strength - preset) < 0.04 ? 'rgba(168, 85, 247, 0.3)' : 'rgba(255,255,255,0.04)',
                            border: Math.abs(lora.strength - preset) < 0.04 ? '1px solid #a855f7' : '1px solid var(--border-subtle)',
                            color: Math.abs(lora.strength - preset) < 0.04 ? '#fff' : 'var(--text-muted)',
                            cursor: 'pointer'
                          }}
                        >
                          {preset}x
                        </button>
                      ))}
                    </div>
                    <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>+2.0x (Güçlü)</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ padding: '10px', textAlign: 'center', border: '1px dashed rgba(255,255,255,0.08)', borderRadius: '8px', marginTop: '10px' }}>
              <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: 0 }}>
                {availableLoras.length > 0
                  ? 'Kütüphaneden ekleyin veya LoRA Hub ile yeni model indirin.'
                  : 'LoRA Hub üzerinden Hugging Face veya Civitai bağlantısı yapıştırarak model indirebilirsiniz.'}
              </p>
            </div>
          )}
        </div>

        {/* 10. SEED AYARI */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', background: 'rgba(255,255,255,0.02)', padding: '10px 14px', borderRadius: '10px', border: '1px solid var(--border-subtle)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>Üretim Tohumu (Seed):</span>
            <span style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: isRandomSeed ? '#a855f7' : '#818cf8', fontWeight: 600 }}>
              {isRandomSeed ? 'Dinamik (Rastgele)' : seed}
            </span>
          </div>
          <button
            type="button"
            onClick={() => {
              if (isRandomSeed) {
                setIsRandomSeed(false);
                setSeed(Math.floor(Math.random() * 1000000));
              } else {
                setIsRandomSeed(true);
                setSeed(-1);
              }
            }}
            className="btn-secondary"
            style={{ padding: '4px 10px', fontSize: '11px', borderRadius: '6px' }}
          >
            <RefreshCw size={12} />
            {isRandomSeed ? 'Sabit Tohum' : 'Dinamik Yap'}
          </button>
        </div>

        {/* HATA MESAJI */}
        {errorMessage && (
          <div style={{ background: 'rgba(244, 63, 94, 0.15)', border: '1px solid rgba(244, 63, 94, 0.3)', padding: '10px 14px', borderRadius: '8px', color: '#fb7185', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertCircle size={15} />
            {errorMessage}
          </div>
        )}

        {/* GENERATE BUTONU */}
        <button
          type="button"
          onClick={handleGenerate}
          disabled={isSubmitting}
          className="btn-primary"
          style={{
            width: '100%',
            padding: '16px',
            fontSize: '15px',
            borderRadius: '14px',
            marginTop: '4px',
            background: model === 'minimax_h3'
              ? 'linear-gradient(135deg, #a855f7 0%, #6366f1 100%)'
              : 'linear-gradient(135deg, #6366f1 0%, #3b82f6 100%)'
          }}
        >
          <Play size={18} fill="#ffffff" />
          {isSubmitting
            ? 'İŞLEM KUYRUĞA ALINIYOR...'
            : (model === 'minimax_h3' ? 'SİNEMATİK ÜRETİMİ BAŞLAT (MINIMAX H3)' : 'SİNEMATİK ÜRETİMİ BAŞLAT (LTX-2.5)')}
        </button>
        <p style={{ textAlign: 'center', fontSize: '11px', color: 'var(--text-muted)' }}>
          Klavye Kısayolu: <kbd style={{ background: 'rgba(255,255,255,0.1)', padding: '2px 6px', borderRadius: '4px', color: '#fff', fontFamily: 'var(--font-mono)' }}>Ctrl + Enter</kbd>
        </p>

      </div>

      {/* SAĞ ÖNİZLEME VE CANLI DURUM ALANI */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', minHeight: '600px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <h2 style={{ fontSize: '17px', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Film size={18} color="#6366f1" />
            Stüdyo Önizleme & Çıktı
          </h2>
          {activeJob && (
            <span className="badge badge-online">
              <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981' }}></span>
              Render Ediliyor (#{activeJob.id.slice(-6)})
            </span>
          )}
        </div>

        {/* AKTİF İŞ CANLI RENDER KARTI */}
        {activeJob && (
          <div style={{ background: 'rgba(0,0,0,0.4)', borderRadius: '16px', padding: '24px', border: '1px solid var(--border-active)', marginBottom: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <div>
                <h3 style={{ fontSize: '15px', color: '#fff' }}>{activeJob.current_stage || 'İşlem Başlatılıyor...'}</h3>
                <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Model: {activeJob.model === 'minimax_h3' ? 'MiniMax H3 Omni (Official FP8)' : 'LTX-2.5 Distilled'} | {activeJob.aspect_ratio} | {activeJob.duration}s
                </p>
              </div>
              <span style={{ fontSize: '24px', fontWeight: 800, fontFamily: 'var(--font-mono)', color: activeJob.model === 'minimax_h3' ? '#c084fc' : 'var(--accent-primary)' }}>
                %{activeJob.progress || 0}
              </span>
            </div>

            {/* İlerleme Çubuğu */}
            <div className="progress-bar-container" style={{ height: '8px' }}>
              <div
                className="progress-bar-fill"
                style={{
                  width: `${activeJob.progress || 0}%`,
                  background: activeJob.model === 'minimax_h3' ? 'linear-gradient(90deg, #a855f7, #ec4899)' : undefined
                }}
              ></div>
            </div>

            <div style={{ marginTop: '14px', fontSize: '12px', color: 'var(--text-secondary)', background: 'rgba(255,255,255,0.02)', padding: '10px', borderRadius: '8px' }}>
              <strong>Prompt:</strong> {activeJob.final_prompt || activeJob.prompt}
            </div>
          </div>
        )}

        {/* VİDEO OYNATICI VEYA BOŞ DURUM */}
        {activeJob && activeJob.status === 'completed' ? (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#000', borderRadius: '16px', overflow: 'hidden', border: '1px solid var(--border-active)' }}>
            <video
              src={`/api/videos/${activeJob.id}/stream`}
              controls
              autoPlay
              loop
              style={{ width: '100%', height: '100%', objectFit: 'contain' }}
            />
          </div>
        ) : (
          <div style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'rgba(0,0,0,0.5)',
            borderRadius: '16px',
            border: '1px solid var(--border-subtle)',
            padding: '24px',
            textAlign: 'center'
          }}>
            <Film size={48} color="rgba(255,255,255,0.15)" style={{ marginBottom: '16px' }} />
            <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
              {activeJob ? 'Video İşleniyor...' : 'Henüz Video Üretilmedi'}
            </h3>
            <p style={{ fontSize: '13px', color: 'var(--text-muted)', maxWidth: '420px' }}>
              {activeJob
                ? 'İşlem tamamlandığında video otomatik olarak bu alanda oynatılacak ve Google Drive galerisine kaydedilecektir.'
                : 'Sol panelden LTX-2.5 veya MiniMax H3 modelini seçin, promptunuzu yazın ve GENERATE butonuna basın.'}
            </p>
          </div>
        )}

      </div>

      {/* COLAB LORA İNDİRME VE YÖNETİM MODAL */}
      {showLoraModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.75)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          padding: '20px'
        }}>
          <div className="glass-panel" style={{
            width: '100%',
            maxWidth: '560px',
            borderRadius: '18px',
            padding: '24px',
            border: '1px solid rgba(168, 85, 247, 0.4)',
            boxShadow: '0 20px 40px rgba(0,0,0,0.6)',
            maxHeight: '90vh',
            overflowY: 'auto'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'rgba(168, 85, 247, 0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <Download size={18} color="#c084fc" />
                </div>
                <div>
                  <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#fff', margin: 0 }}>LoRA Model Hub & Bulut Depolama</h3>
                  <span style={{ fontSize: '11px', color: '#a855f7' }}>⚡ Yüksek Hızlı Cloud Aktarımı • Google Drive & GPU Önbelleği</span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowLoraModal(false)}
                style={{ background: 'transparent', border: 'none', color: '#94a3b8', cursor: 'pointer', padding: '4px' }}
              >
                <X size={18} />
              </button>
            </div>

            <p style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: '1.5', marginBottom: '16px' }}>
              Hugging Face veya Civitai doğrudan model indirme bağlantısını yapıştırın. Model dosyası bilgisayarınızın kotasını harcamadan doğrudan bulut GPU sunucusu üzerinden Google Drive kütüphanenize aktarılır.
            </p>

            <form onSubmit={handleStartLoraDownload} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>
                  Hugging Face / Civitai İndirme URL'si:
                </label>
                <input
                  type="text"
                  placeholder="https://huggingface.co/.../lora.safetensors veya Civitai doğrudan bağlantısı"
                  value={loraUrl}
                  onChange={(e) => setLoraUrl(e.target.value)}
                  style={{
                    width: '100%',
                    background: 'rgba(0,0,0,0.4)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: '8px',
                    padding: '10px 12px',
                    fontSize: '12px',
                    color: '#fff',
                    outline: 'none'
                  }}
                />
              </div>

              <div>
                <label style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>
                  Özel Dosya Adı (Opsiyonel):
                </label>
                <input
                  type="text"
                  placeholder="ornek_stil.safetensors"
                  value={loraFilename}
                  onChange={(e) => setLoraFilename(e.target.value)}
                  style={{
                    width: '100%',
                    background: 'rgba(0,0,0,0.4)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: '8px',
                    padding: '10px 12px',
                    fontSize: '12px',
                    color: '#fff',
                    outline: 'none'
                  }}
                />
              </div>

              {loraModalError && (
                <div style={{ background: 'rgba(244, 63, 94, 0.15)', padding: '8px 12px', borderRadius: '6px', color: '#fb7185', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <AlertCircle size={14} />
                  {loraModalError}
                </div>
              )}

              <button
                type="submit"
                disabled={isStartingDownload || !loraUrl.trim()}
                className="btn-primary"
                style={{
                  padding: '12px',
                  borderRadius: '10px',
                  fontSize: '13px',
                  background: 'linear-gradient(135deg, #a855f7 0%, #6366f1 100%)',
                  marginTop: '4px'
                }}
              >
                {isStartingDownload ? 'İndirme Görevi Başlatılıyor...' : '🚀 Bulut Sunucusuna İndirmeyi Başlat'}
              </button>
            </form>

            {/* AKTİF İNDİRME GÖREVİ KARTI */}
            {activeDownloadTask && (
              <div style={{ marginTop: '16px', background: 'rgba(0,0,0,0.4)', borderRadius: '12px', padding: '14px', border: '1px solid rgba(168, 85, 247, 0.3)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <span style={{ fontSize: '12px', fontWeight: 600, color: '#fff' }}>
                    {activeDownloadTask.filename}
                  </span>
                  <span style={{ fontSize: '11px', color: activeDownloadTask.status === 'completed' ? '#10b981' : (activeDownloadTask.status === 'failed' ? '#fb7185' : '#c084fc'), fontWeight: 700 }}>
                    {activeDownloadTask.status === 'completed' ? 'Tamamlandı ✅' : (activeDownloadTask.status === 'failed' ? 'Hata ❌' : `%${activeDownloadTask.progress || 0}`)}
                  </span>
                </div>

                <div className="progress-bar-container" style={{ height: '6px', marginBottom: '8px' }}>
                  <div
                    className="progress-bar-fill"
                    style={{
                      width: `${activeDownloadTask.progress || 0}%`,
                      background: activeDownloadTask.status === 'completed' ? '#10b981' : (activeDownloadTask.status === 'failed' ? '#fb7185' : 'linear-gradient(90deg, #a855f7, #6366f1)')
                    }}
                  ></div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-muted)' }}>
                  <span>
                    {activeDownloadTask.downloaded_bytes ? `${(activeDownloadTask.downloaded_bytes / (1024 * 1024)).toFixed(1)} MB` : '0 MB'} / {activeDownloadTask.total_bytes ? `${(activeDownloadTask.total_bytes / (1024 * 1024)).toFixed(1)} MB` : '?'}
                  </span>
                  <span>
                    {activeDownloadTask.speed_mbps ? `${activeDownloadTask.speed_mbps} MB/s` : ''}
                  </span>
                </div>
                {activeDownloadTask.error && (
                  <p style={{ color: '#fb7185', fontSize: '11px', marginTop: '6px', margin: 0 }}>
                    Hata: {activeDownloadTask.error}
                  </p>
                )}
              </div>
            )}

            {/* MEVCUT LORALAR LİSTESİ */}
            <div style={{ marginTop: '20px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>
                  Kayıtlı LoRA Model Kütüphanesi ({availableLoras.length}):
                </span>
                <button
                  type="button"
                  onClick={loadLoras}
                  style={{ background: 'transparent', border: 'none', color: '#c084fc', fontSize: '11px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}
                >
                  <RefreshCw size={11} className={isLoadingLoras ? 'spin' : ''} />
                  Yenile
                </button>
              </div>

              {availableLoras.length > 0 ? (
                <div style={{ maxHeight: '180px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {availableLoras.map((lora) => (
                    <div
                      key={lora.name}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        background: 'rgba(255,255,255,0.03)',
                        padding: '6px 10px',
                        borderRadius: '6px',
                        border: '1px solid var(--border-subtle)'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', overflow: 'hidden' }}>
                        <span style={{ fontSize: '11px', color: '#e2e8f0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '280px' }}>
                          {lora.name}
                        </span>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                          ({lora.size_mb} MB)
                        </span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <button
                          type="button"
                          onClick={() => {
                            handleAddLora(lora.name);
                            setShowLoraModal(false);
                          }}
                          style={{
                            padding: '2px 8px',
                            borderRadius: '4px',
                            background: selectedLoras.some(l => l.name === lora.name) ? 'rgba(16, 185, 129, 0.2)' : 'rgba(168, 85, 247, 0.2)',
                            border: 'none',
                            color: selectedLoras.some(l => l.name === lora.name) ? '#10b981' : '#c084fc',
                            fontSize: '10px',
                            cursor: 'pointer'
                          }}
                        >
                          {selectedLoras.some(l => l.name === lora.name) ? 'Seçildi' : '+ Ekle'}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteLoraDisk(lora.name)}
                          style={{ background: 'transparent', border: 'none', color: '#ef4444', cursor: 'pointer', padding: '2px' }}
                          title="Diskten sil"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p style={{ fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic', margin: 0 }}>
                  Henüz LoRA indirilmemiş.
                </p>
              )}
            </div>

            <div style={{ marginTop: '20px', display: 'flex', justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={() => setShowLoraModal(false)}
                className="btn-secondary"
                style={{ padding: '8px 16px', borderRadius: '8px', fontSize: '12px' }}
              >
                Kapat
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
