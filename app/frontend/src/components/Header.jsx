import React, { useState } from 'react';
import { Video, Cpu, HardDrive, Zap, Layers, Image as ImageIcon, Settings as SettingsIcon, Eraser } from 'lucide-react';
import { freeVram } from '../services/api';

function usageColors(ratio) {
  if (ratio >= 0.9) return { color: '#fca5a5', borderColor: 'rgba(244, 63, 94, 0.45)' };
  if (ratio >= 0.75) return { color: '#fcd34d', borderColor: 'rgba(245, 158, 11, 0.4)' };
  return { color: 'var(--text-secondary)', borderColor: 'var(--border-subtle)' };
}

function UsageBadge({ label, used, total, title }) {
  if (!(total > 0)) return null;
  const ratio = (used || 0) / total;
  return (
    <div className="badge" title={title} style={usageColors(ratio)}>
      <span>{label} {used ?? '?'}/{total} GB</span>
    </div>
  );
}

export default function Header({ status, liveResources, activeTab, setActiveTab, queueCount, onRefresh }) {
  const gpuInfo = status?.gpu || {};
  const comfyOnline = status?.comfyui?.online;
  const driveConnected = status?.storage?.drive_connected;
  const [isFreeing, setIsFreeing] = useState(false);

  // İş sürerken WebSocket ile gelen ölçüm (~2 sn), yoksa periyodik durum sorgusu (15 sn)
  const vramUsed = liveResources?.vram_used_gb ?? gpuInfo.vram_used_gb;
  const vramTotal = liveResources?.vram_total_gb ?? gpuInfo.vram_gb;
  const ramUsed = liveResources?.ram_used_gb ?? gpuInfo.ram_used_gb;
  const ramTotal = liveResources?.ram_total_gb ?? gpuInfo.ram_gb;

  const handleFreeVram = async () => {
    if (isFreeing) return;
    setIsFreeing(true);
    try {
      const res = await freeVram();
      if (onRefresh) onRefresh();
      if (!res.success) alert(res.message);
    } catch (err) {
      alert(err.message || 'GPU belleği boşaltılamadı.');
    } finally {
      setIsFreeing(false);
    }
  };

  return (
    <header style={{
      borderBottom: '1px solid var(--border-subtle)',
      background: 'rgba(7, 9, 14, 0.85)',
      backdropFilter: 'blur(20px)',
      position: 'sticky',
      top: 0,
      zIndex: 100
    }}>
      <div style={{
        maxWidth: '1600px',
        margin: '0 auto',
        padding: '14px 24px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '16px'
      }}>
        {/* Sol Logo & Başlık */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{
            width: '42px',
            height: '42px',
            borderRadius: '12px',
            background: 'var(--gradient-glow)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: 'var(--shadow-glow)'
          }}>
            <Video size={22} color="#ffffff" />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <h1 style={{ fontSize: '19px', fontWeight: 800, letterSpacing: '-0.02em', background: 'linear-gradient(to right, #ffffff, #c7d2fe)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                OzzyVision-Lab
              </h1>
              <span style={{ fontSize: '10px', background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.25), rgba(168, 85, 247, 0.25))', color: '#c084fc', border: '1px solid rgba(168, 85, 247, 0.4)', padding: '2px 8px', borderRadius: '6px', fontWeight: 700, letterSpacing: '0.04em' }}>
                DUAL ENGINE
              </span>
            </div>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>LTX-2.5 & MiniMax H3 video stüdyosu</p>
          </div>
        </div>

        {/* Orta Navigasyon Sekmeleri */}
        <nav style={{ display: 'flex', alignItems: 'center', gap: '6px', background: 'rgba(255, 255, 255, 0.04)', padding: '4px', borderRadius: '12px', border: '1px solid var(--border-subtle)' }}>
          <button
            onClick={() => setActiveTab('create')}
            style={{
              background: activeTab === 'create' ? 'linear-gradient(135deg, var(--accent-primary), var(--accent-secondary))' : 'transparent',
              color: activeTab === 'create' ? '#ffffff' : 'var(--text-secondary)',
              border: 'none',
              borderRadius: '8px',
              padding: '8px 16px',
              fontFamily: 'var(--font-heading)',
              fontWeight: 600,
              fontSize: '13px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              transition: 'all 0.2s',
              boxShadow: activeTab === 'create' ? '0 2px 12px rgba(99, 102, 241, 0.35)' : 'none'
            }}
          >
            <Zap size={15} />
            Stüdyo
          </button>

          <button
            onClick={() => setActiveTab('queue')}
            style={{
              background: activeTab === 'queue' ? 'linear-gradient(135deg, var(--accent-primary), var(--accent-secondary))' : 'transparent',
              color: activeTab === 'queue' ? '#ffffff' : 'var(--text-secondary)',
              border: 'none',
              borderRadius: '8px',
              padding: '8px 16px',
              fontFamily: 'var(--font-heading)',
              fontWeight: 600,
              fontSize: '13px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              position: 'relative',
              transition: 'all 0.2s',
              boxShadow: activeTab === 'queue' ? '0 2px 12px rgba(99, 102, 241, 0.35)' : 'none'
            }}
          >
            <Layers size={15} />
            İşlem Kuyruğu
            {queueCount > 0 && (
              <span style={{
                background: '#ec4899',
                color: '#fff',
                borderRadius: '999px',
                padding: '1px 6px',
                fontSize: '10px',
                fontWeight: 700
              }}>
                {queueCount}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('gallery')}
            style={{
              background: activeTab === 'gallery' ? 'linear-gradient(135deg, var(--accent-primary), var(--accent-secondary))' : 'transparent',
              color: activeTab === 'gallery' ? '#ffffff' : 'var(--text-secondary)',
              border: 'none',
              borderRadius: '8px',
              padding: '8px 16px',
              fontFamily: 'var(--font-heading)',
              fontWeight: 600,
              fontSize: '13px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              transition: 'all 0.2s',
              boxShadow: activeTab === 'gallery' ? '0 2px 12px rgba(99, 102, 241, 0.35)' : 'none'
            }}
          >
            <ImageIcon size={15} />
            Medya Galerisi
          </button>

          <button
            onClick={() => setActiveTab('settings')}
            style={{
              background: activeTab === 'settings' ? 'linear-gradient(135deg, var(--accent-primary), var(--accent-secondary))' : 'transparent',
              color: activeTab === 'settings' ? '#ffffff' : 'var(--text-secondary)',
              border: 'none',
              borderRadius: '8px',
              padding: '8px 16px',
              fontFamily: 'var(--font-heading)',
              fontWeight: 600,
              fontSize: '13px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              transition: 'all 0.2s',
              boxShadow: activeTab === 'settings' ? '0 2px 12px rgba(99, 102, 241, 0.35)' : 'none'
            }}
          >
            <SettingsIcon size={15} />
            Sistem & Entegrasyon
          </button>
        </nav>

        {/* Sağ Canlı Durum Rozetleri */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {/* GPU */}
          <div className="badge badge-gpu" title={gpuInfo.name || 'GPU'}>
            <Cpu size={13} />
            <span>{gpuInfo.available ? (gpuInfo.name?.includes('A100') ? 'A100 80GB' : gpuInfo.name) : 'CPU / Sim'}</span>
          </div>

          {/* GPU ve sistem belleği: "OOM" hatası ikisinden birinin dolmasıdır */}
          <UsageBadge
            label="VRAM"
            used={vramUsed}
            total={vramTotal}
            title="GPU belleği"
          />
          <UsageBadge
            label="RAM"
            used={ramUsed}
            total={ramTotal}
            title="Sistem belleği. Dolarsa ComfyUI kapanır ve VRAM dolmadan OOM hatası görülür."
          />

          <button
            onClick={handleFreeVram}
            disabled={isFreeing}
            title="ComfyUI'nin GPU belleğinde tuttuğu tüm modelleri boşaltır. Model veya LoRA değiştirdikten sonra 'CUDA out of memory' alırsanız kullanın."
            className="badge"
            style={{
              cursor: isFreeing ? 'wait' : 'pointer',
              opacity: isFreeing ? 0.6 : 1,
              background: 'rgba(255,255,255,0.04)',
              color: 'var(--text-secondary)'
            }}
          >
            <Eraser size={13} />
            <span>{isFreeing ? 'Boşaltılıyor...' : 'VRAM Temizle'}</span>
          </button>

          {/* ComfyUI */}
          <div className={`badge ${comfyOnline ? 'badge-online' : 'badge-offline'}`}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: comfyOnline ? '#10b981' : '#f43f5e' }}></span>
            <span>ComfyUI</span>
          </div>

          {/* Google Drive */}
          <div className={`badge ${driveConnected ? 'badge-online' : 'badge-offline'}`}>
            <HardDrive size={13} />
            <span>{driveConnected ? 'Drive Bağlı' : 'Drive Çevrimdışı'}</span>
          </div>
        </div>
      </div>
    </header>
  );
}
