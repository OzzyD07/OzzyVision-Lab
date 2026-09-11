import React, { useState, useEffect } from 'react';
import { Film, Download, Sparkles, Trash2, X } from 'lucide-react';
import { deleteJob } from '../services/api';
import VideoMetadata from './VideoMetadata';

/**
 * Galeri karti onizlemesi.
 * Tarayicilar oynatma baslamadan videonun ilk karesini cizmeyebilir; kart bu yuzden
 * video yuklense bile siyah gorunuyordu. Kucuk bir seek ilk kareyi cizmeye zorlar.
 * Dosya bozuk/eksikse sessiz siyah kutu yerine acik bir yer tutucu gosterilir.
 */
function VideoThumb({ src }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <div style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '6px',
        color: 'var(--text-muted)',
        fontSize: '11px'
      }}>
        <Film size={28} color="rgba(255,255,255,0.2)" />
        Önizleme yüklenemedi
      </div>
    );
  }

  return (
    <video
      src={src}
      muted
      loop
      playsInline
      preload="metadata"
      onLoadedData={(e) => {
        const v = e.currentTarget;
        if (v.currentTime === 0) {
          v.currentTime = Math.min(0.1, (v.duration || 0.2) / 2);
        }
      }}
      onError={() => setFailed(true)}
      onMouseOver={(e) => e.currentTarget.play().catch(() => {})}
      onMouseOut={(e) => e.currentTarget.pause()}
      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
    />
  );
}

export default function GalleryView({ videos, onReuseSettings, onRefresh, cameraPresets = [] }) {
  const [selectedVideo, setSelectedVideo] = useState(null);

  // Modal aciktayken arka plandaki galeri kaymasin ve Esc ile kapansin
  useEffect(() => {
    if (!selectedVideo) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e) => {
      if (e.key === 'Escape') setSelectedVideo(null);
    };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKey);
    };
  }, [selectedVideo]);

  const handleDelete = async (id, e) => {
    e.stopPropagation();
    if (confirm('Bu videoyu silmek istediğinize emin misiniz?')) {
      await deleteJob(id);
      if (selectedVideo?.id === id) setSelectedVideo(null);
      if (onRefresh) onRefresh();
    }
  };

  return (
    <div style={{ maxWidth: '1600px', margin: '0 auto', padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: '22px', fontWeight: 800, color: 'var(--text-primary)' }}>
            Galeri
          </h2>
        </div>
        <span className="badge badge-gpu" style={{ padding: '6px 14px', fontSize: '13px' }}>
          {videos.length} video
        </span>
      </div>

      {videos.length === 0 ? (
        <div className="glass-panel" style={{ padding: '60px 20px', textAlign: 'center' }}>
          <Film size={48} color="rgba(255,255,255,0.15)" style={{ margin: '0 auto 16px' }} />
          <h3 style={{ fontSize: '18px', color: 'var(--text-secondary)' }}>Henüz video yok</h3>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginTop: '6px' }}>
            Stüdyo sekmesinden ilk videonuzu oluşturun.
          </p>
        </div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          gap: '20px'
        }}>
          {videos.map((vid) => (
            <div
              key={vid.id}
              onClick={() => setSelectedVideo(vid)}
              className="glass-panel"
              style={{
                borderRadius: '16px',
                overflow: 'hidden',
                cursor: 'pointer',
                display: 'flex',
                flexDirection: 'column',
                transition: 'transform 0.2s, border-color 0.2s'
              }}
            >
              {/* Video Kartı Üst Görsel / Video */}
              <div style={{ position: 'relative', width: '100%', height: '200px', background: '#000' }}>
                <VideoThumb src={`/api/videos/${vid.id}/stream`} />
                <div style={{
                  position: 'absolute',
                  bottom: '8px',
                  right: '8px',
                  background: 'rgba(0,0,0,0.75)',
                  padding: '3px 8px',
                  borderRadius: '6px',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  color: '#fff'
                }}>
                  {vid.duration}s | {vid.aspect_ratio}
                </div>
                <div style={{
                  position: 'absolute',
                  top: '8px',
                  left: '8px',
                  background: vid.model === 'minimax_h3'
                    ? 'linear-gradient(135deg, rgba(168,85,247,0.95), rgba(99,102,241,0.95))'
                    : (vid.type === 'image_to_video' ? 'rgba(99,102,241,0.9)' : 'rgba(16,185,129,0.9)'),
                  padding: '3px 8px',
                  borderRadius: '6px',
                  fontSize: '10px',
                  fontWeight: 700,
                  color: '#fff',
                  backdropFilter: 'blur(4px)'
                }}>
                  {vid.model === 'minimax_h3' ? 'MiniMax H3' : (vid.type === 'image_to_video' ? 'LTX I2V' : 'LTX T2V')}
                </div>
              </div>

              {/* Video Kartı Alt Bilgiler */}
              <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '8px', flex: 1, justifyContent: 'space-between' }}>
                <div>
                  <p style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)', lineClamp: 2, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                    {vid.prompt}
                  </p>
                  <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '6px' }}>
                    Kamera: {vid.camera || 'Static'} | Kalite: {vid.quality}
                  </p>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '10px', borderTop: '1px solid var(--border-subtle)' }}>
                  <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                    #{vid.id.slice(-6)}
                  </span>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (onReuseSettings) onReuseSettings(vid);
                      }}
                      className="btn-secondary"
                      style={{ padding: '4px 8px', fontSize: '11px', borderRadius: '6px' }}
                      title="Ayarları Tekrar Kullan"
                    >
                      <Sparkles size={12} />
                      Reuse
                    </button>
                    <button
                      onClick={(e) => handleDelete(vid.id, e)}
                      className="btn-secondary"
                      style={{ padding: '4px 8px', fontSize: '11px', borderRadius: '6px', color: '#fb7185' }}
                      title="Sil"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* DETAY VE OYNATICI MODALI */}
      {selectedVideo && (
        <div
          onClick={() => setSelectedVideo(null)}
          style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.85)',
          backdropFilter: 'blur(10px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          padding: '24px'
        }}>
          <div className="glass-panel" onClick={(e) => e.stopPropagation()} style={{
            maxWidth: '1000px',
            width: '100%',
            maxHeight: '90vh',
            overflowY: 'auto',
            borderRadius: '20px',
            border: '1px solid var(--border-active)',
            padding: '24px',
            display: 'flex',
            flexDirection: 'column',
            gap: '20px'
          }}>
            {/* Modal Üst Çubuk */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span className="badge badge-gpu">#{selectedVideo.id}</span>
                <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                  {new Date(selectedVideo.created_at).toLocaleString('tr-TR')}
                </span>
              </div>
              <button
                onClick={() => setSelectedVideo(null)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
              >
                <X size={20} />
              </button>
            </div>

            {/* Oynatıcı Alanı */}
            <div style={{ width: '100%', maxHeight: '480px', borderRadius: '12px', overflow: 'hidden', background: '#000', display: 'flex', justifyContent: 'center' }}>
              <video
                src={`/api/videos/${selectedVideo.id}/stream`}
                controls
                autoPlay
                loop
                style={{ maxWidth: '100%', maxHeight: '480px' }}
              />
            </div>

            {/* Video Detayları ve Metadata */}
            <VideoMetadata job={selectedVideo} cameraPresets={cameraPresets} />

            {/* Buton Aksiyonları */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', paddingTop: '16px', borderTop: '1px solid var(--border-subtle)' }}>
              <a
                href={`/api/videos/${selectedVideo.id}/stream`}
                download={`${selectedVideo.id}.mp4`}
                className="btn-secondary"
                style={{ textDecoration: 'none' }}
              >
                <Download size={14} />
                Videoyu İndir (MP4)
              </a>
              <button
                onClick={() => {
                  if (onReuseSettings) onReuseSettings(selectedVideo);
                  setSelectedVideo(null);
                }}
                className="btn-primary"
              >
                <Sparkles size={14} />
                Ayarları Kullan (Reuse)
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
