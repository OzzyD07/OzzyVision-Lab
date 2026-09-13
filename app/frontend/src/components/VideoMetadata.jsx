import React from 'react';
import { Image as ImageIcon, Film, Music, Layers } from 'lucide-react';

const MODEL_LABELS = {
  ltx25: 'LTX-2.5 Distilled 22B',
  minimax_h3: 'MiniMax H3 Omni Ref2VA'
};

const TYPE_LABELS = {
  text_to_video: 'Metinden Video (T2V)',
  image_to_video: 'Görselden Video (I2V)',
  reference_to_video: 'Referanstan Video (Ref2VA)'
};

const QUALITY_LABELS = {
  draft: 'Taslak',
  standard: 'Standart',
  high: 'Yüksek'
};

const MOTION_LABELS = {
  low: 'Düşük',
  medium: 'Orta',
  high: 'Yüksek'
};

const REF_SIZE_LABELS = {
  match: 'Hedefe ölçekle (match)',
  max: 'Maksimum detay (max)'
};

function Section({ title, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <h4 style={{
        fontSize: '11px',
        fontWeight: 700,
        color: 'var(--text-muted)',
        textTransform: 'uppercase',
        letterSpacing: '0.05em'
      }}>
        {title}
      </h4>
      {children}
    </div>
  );
}

function Row({ label, value, mono }) {
  if (value === null || value === undefined || value === '') return null;
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      gap: '12px',
      fontSize: '12px',
      padding: '5px 0',
      borderBottom: '1px solid rgba(255,255,255,0.04)'
    }}>
      <span style={{ color: 'var(--text-muted)', flexShrink: 0 }}>{label}</span>
      <span style={{
        color: 'var(--text-primary)',
        fontWeight: 600,
        textAlign: 'right',
        wordBreak: 'break-word',
        fontFamily: mono ? 'var(--font-mono)' : 'inherit',
        fontSize: mono ? '11px' : 'inherit'
      }}>
        {value}
      </span>
    </div>
  );
}

function TextBlock({ children }) {
  return (
    <p style={{
      fontSize: '13px',
      lineHeight: 1.6,
      color: 'var(--text-primary)',
      background: 'rgba(255,255,255,0.02)',
      border: '1px solid var(--border-subtle)',
      padding: '12px',
      borderRadius: '10px',
      whiteSpace: 'pre-wrap'
    }}>
      {children}
    </p>
  );
}

function ReferenceGrid({ items, kind }) {
  if (!items || items.length === 0) return null;

  const icons = { image: ImageIcon, video: Film, audio: Music };
  const titles = { image: 'Referans Görseller', video: 'Referans Videolar', audio: 'Referans Sesler' };
  const Icon = icons[kind];

  return (
    <Section title={`${titles[kind]} (${items.length})`}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
        {items.map((item, idx) => (
          <div
            key={`${kind}-${idx}`}
            style={{
              width: kind === 'audio' ? '220px' : '110px',
              display: 'flex',
              flexDirection: 'column',
              gap: '4px'
            }}
          >
            {kind === 'image' && (
              <img
                src={`/api/assets/${encodeURIComponent(item)}`}
                alt={item}
                style={{
                  width: '110px',
                  height: '110px',
                  objectFit: 'cover',
                  borderRadius: '8px',
                  border: '1px solid var(--border-subtle)',
                  background: '#000'
                }}
              />
            )}
            {kind === 'video' && (
              <video
                src={`/api/assets/${encodeURIComponent(item)}`}
                controls
                muted
                style={{
                  width: '110px',
                  height: '110px',
                  objectFit: 'cover',
                  borderRadius: '8px',
                  border: '1px solid var(--border-subtle)',
                  background: '#000'
                }}
              />
            )}
            {kind === 'audio' && (
              <audio
                src={`/api/assets/${encodeURIComponent(item)}`}
                controls
                style={{ width: '220px', height: '34px' }}
              />
            )}
            <span
              title={item}
              style={{
                fontSize: '10px',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                display: 'flex',
                alignItems: 'center',
                gap: '4px'
              }}
            >
              <Icon size={10} />
              {item}
            </span>
          </div>
        ))}
      </div>
    </Section>
  );
}

function formatVideoInfo(info) {
  if (!info || !info.video_codec) return null;
  const parts = [info.video_codec, info.pix_fmt, info.profile].filter(Boolean);
  const audio = info.audio_codec ? ` + ${info.audio_codec}` : '';
  return parts.join(' · ') + audio;
}

/**
 * Bir işin tüm üretim parametrelerini ve kullanılan içerikleri gösterir.
 */
export default function VideoMetadata({ job, cameraPresets = [] }) {
  if (!job) return null;

  const dims = job.dimensions || {};
  const loras = job.applied_loras || job.loras || [];
  const loaders = job.engine_loaders || {};
  const cameraLabel =
    cameraPresets.find((p) => p.id === job.camera)?.name_tr || job.camera || 'static';

  const renderTime = (() => {
    if (!job.created_at || !job.completed_at) return null;
    const secs = Math.round(
      (new Date(job.completed_at) - new Date(job.created_at)) / 1000
    );
    if (!Number.isFinite(secs) || secs < 0) return null;
    return secs >= 60 ? `${Math.floor(secs / 60)} dk ${secs % 60} sn` : `${secs} sn`;
  })();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Promptlar */}
      <Section title="Prompt">
        <TextBlock>{job.prompt || '—'}</TextBlock>
      </Section>

      {job.final_prompt && job.final_prompt !== job.prompt && (
        <Section title={job.enhance_prompt ? 'İşlenmiş Prompt (Zenginleştirme + Kamera)' : 'İşlenmiş Prompt (Kamera Eklendi)'}>
          <TextBlock>{job.final_prompt}</TextBlock>
        </Section>
      )}

      {job.negative_prompt && (
        <Section title="Negatif Prompt">
          <TextBlock>{job.negative_prompt}</TextBlock>
        </Section>
      )}

      {/* Referans içerikler */}
      <ReferenceGrid items={job.ref_images} kind="image" />
      <ReferenceGrid items={job.ref_videos} kind="video" />
      <ReferenceGrid items={job.ref_audios} kind="audio" />

      {job.asset_id && (!job.ref_images || job.ref_images.length === 0) && (
        <Section title="Referans Görsel">
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <img
              src={`/api/assets/${encodeURIComponent(job.asset_id)}`}
              alt="Referans"
              style={{
                width: '110px',
                height: '110px',
                objectFit: 'cover',
                borderRadius: '8px',
                border: '1px solid var(--border-subtle)',
                background: '#000'
              }}
            />
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {job.image_filename || job.asset_id}
            </div>
          </div>
        </Section>
      )}

      {/* LoRA katmanları */}
      {loras.length > 0 && (
        <Section title={`LoRA Katmanları (${loras.length})`}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {loras.map((l, idx) => (
              <div
                key={`lora-${idx}`}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: '12px',
                  background: 'rgba(168, 85, 247, 0.08)',
                  border: '1px solid rgba(168, 85, 247, 0.25)',
                  borderRadius: '8px',
                  padding: '8px 12px'
                }}
              >
                <span style={{
                  fontSize: '12px',
                  color: '#e9d5ff',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis'
                }}>
                  <Layers size={12} />
                  {l.name}
                </span>
                <span style={{ fontSize: '12px', fontFamily: 'var(--font-mono)', color: '#c084fc', flexShrink: 0 }}>
                  {(l.strength_model ?? l.strength ?? 1).toFixed
                    ? (l.strength_model ?? l.strength ?? 1).toFixed(2)
                    : (l.strength_model ?? l.strength ?? 1)}x
                  {l.strength_clip ? ` · CLIP ${l.strength_clip}` : ''}
                </span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Üretim parametreleri */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '20px' }}>
        <Section title="Üretim Ayarları">
          <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-subtle)', borderRadius: '10px', padding: '4px 12px' }}>
            <Row label="Motor" value={MODEL_LABELS[job.model] || job.model} />
            <Row label="Mod" value={TYPE_LABELS[job.type] || job.type} />
            <Row label="Kamera" value={cameraLabel} />
            <Row label="En-Boy Oranı" value={job.aspect_ratio} />
            <Row
              label="Çözünürlük"
              value={dims.width ? `${dims.width} × ${dims.height}` : null}
              mono
            />
            <Row label="Süre" value={job.duration ? `${job.duration} sn` : null} />
            <Row label="FPS" value={job.fps} />
            <Row label="Kare Sayısı" value={dims.frames} mono />
            <Row label="Kalite" value={QUALITY_LABELS[job.quality] || job.quality} />
            <Row label="Ses" value={job.audio ? 'Açık' : 'Kapalı'} />
            {job.model === 'ltx25' && (
              <Row label="Hareket Gücü" value={MOTION_LABELS[job.motion_strength] || job.motion_strength} />
            )}
            {job.type === 'image_to_video' && (
              <Row label="Görsel Sadakati" value={`%${Math.round((job.image_fidelity ?? 0.95) * 100)}`} />
            )}
            {job.model === 'minimax_h3' && (
              <Row label="Referans Ölçeği" value={REF_SIZE_LABELS[job.ref_image_size] || job.ref_image_size} />
            )}
            <Row label="Prompt Zenginleştirme" value={job.enhance_prompt ? 'Açık' : 'Kapalı'} />
          </div>
        </Section>

        <Section title="Çıkarım Detayları">
          <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-subtle)', borderRadius: '10px', padding: '4px 12px' }}>
            <Row label="Seed" value={job.seed} mono />
            <Row label="Adım (Steps)" value={job.steps} mono />
            <Row label="CFG" value={job.cfg} mono />
            <Row label="Örnekleyici" value={job.sampler} />
            <Row label="Diffusion Modeli" value={loaders.diffusion} mono />
            <Row label="Yükleyici Düğümü" value={loaders.diffusion_node} mono />
            <Row label="Metin Kodlayıcı" value={loaders.text_encoder} mono />
            <Row label="Video VAE" value={loaders.video_vae} mono />
            <Row label="Ses VAE" value={loaders.audio_vae} mono />
          </div>
        </Section>

        <Section title="Kayıt Bilgileri">
          <div style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-subtle)', borderRadius: '10px', padding: '4px 12px' }}>
            <Row label="İş Kimliği" value={job.id} mono />
            <Row
              label="Oluşturulma"
              value={job.created_at ? new Date(job.created_at).toLocaleString('tr-TR') : null}
            />
            <Row
              label="Tamamlanma"
              value={job.completed_at ? new Date(job.completed_at).toLocaleString('tr-TR') : null}
            />
            <Row label="Üretim Süresi" value={renderTime} />
            <Row label="Google Drive" value={job.drive_video_path ? 'Yedeklendi' : 'Yerel'} />
            <Row label="Video Biçimi" value={formatVideoInfo(job.video_info)} mono />
            {job.video_info?.transcoded && (
              <Row label="Orijinal Biçim" value={`${formatVideoInfo(job.video_info.original)} (tarayıcı için dönüştürüldü)`} mono />
            )}
          </div>
        </Section>
      </div>
    </div>
  );
}
