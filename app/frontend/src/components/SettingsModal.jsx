import React from 'react';
import { HardDrive, Server, Bot, ShieldCheck, ExternalLink, Copy, Check } from 'lucide-react';

export default function SettingsModal({ status }) {
  const [copied, setCopied] = React.useState(false);
  const mcpUrl = `${window.location.origin}/mcp`;

  const handleCopy = () => {
    navigator.clipboard.writeText(mcpUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={{ maxWidth: '1000px', margin: '0 auto', padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div>
        <h2 style={{ fontSize: '22px', fontWeight: 800, color: 'var(--text-primary)' }}>
          Sistem & Entegrasyon
        </h2>
      </div>

      {/* GOOGLE DRIVE YAPILANDIRMASI */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <h3 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <HardDrive size={18} color="#06b6d4" />
          Google Drive Depolama
        </h3>
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          Videolar, referans dosyalar ve iş kayıtları Drive'a yazılır; Colab kapansa da korunur.
        </p>

        <div style={{ background: 'rgba(0,0,0,0.3)', padding: '16px', borderRadius: '12px', fontSize: '12px', fontFamily: 'var(--font-mono)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div><span style={{ color: 'var(--text-muted)' }}>Drive Kök Dizini:</span> <span style={{ color: '#06b6d4' }}>{status?.storage?.drive_root || '/content/drive/MyDrive/OzzyVision-Lab'}</span></div>
          <div><span style={{ color: 'var(--text-muted)' }}>Yerel Çalışma Alanı:</span> <span style={{ color: '#fff' }}>{status?.storage?.local_cache || '/content/OzzyVision-Lab'}</span></div>
          <div><span style={{ color: 'var(--text-muted)' }}>Durum:</span> <span style={{ color: status?.storage?.drive_connected ? '#34d399' : '#fb7185' }}>{status?.storage?.drive_connected ? 'Bağlandı (Mounted)' : 'Çevrimdışı (Yerel Depolama Kullanılıyor)'}</span></div>
        </div>

        <p style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          Yollar <code>config/settings.py</code> içinden değiştirilebilir.
        </p>
      </div>

      {/* CLAUDE REMOTE MCP ENTEGRASYONU */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <h3 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Bot size={18} color="#a855f7" />
          Claude Remote MCP Sunucusu
        </h3>
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          Claude ile konuşarak video üretebilir ve kuyruğu yönetebilirsiniz.
        </p>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', background: 'rgba(0,0,0,0.4)', padding: '12px 16px', borderRadius: '10px', border: '1px solid var(--border-subtle)' }}>
          <span style={{ fontSize: '13px', fontFamily: 'var(--font-mono)', color: '#a855f7', flex: 1, wordBreak: 'break-all' }}>
            {mcpUrl}
          </span>
          <button
            onClick={handleCopy}
            className="btn-secondary"
            style={{ padding: '6px 12px', fontSize: '12px' }}
          >
            {copied ? <Check size={14} color="#10b981" /> : <Copy size={14} />}
            {copied ? 'Kopyalandı' : 'Kopyala'}
          </button>
        </div>

        <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.7, background: 'rgba(255,255,255,0.02)', padding: '16px', borderRadius: '12px' }}>
          <strong>Claude'a ekleme</strong>
          <ol style={{ paddingLeft: '20px', marginTop: '6px' }}>
            <li>Claude &rarr; <strong>Settings &rarr; Connectors</strong></li>
            <li><strong>Add Custom Connector</strong></li>
            <li>Yukarıdaki adresi yapıştırıp kaydedin.</li>
          </ol>
        </div>
      </div>

      {/* MOTOR VE MODEL DETAYLARI */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <h3 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Server size={18} color="#6366f1" />
          Motorlar
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px', fontSize: '12px' }}>
          <div style={{ background: 'rgba(255,255,255,0.02)', padding: '12px', borderRadius: '10px', border: '1px solid rgba(99,102,241,0.2)' }}>
            <span style={{ color: '#818cf8', fontWeight: 700 }}>LTX-2.5</span>
            <p style={{ fontWeight: 600, color: '#fff', marginTop: '4px' }}>22B Distilled (8 adım)</p>
            <p style={{ color: 'var(--text-muted)', fontSize: '11px', marginTop: '2px' }}>Gemma 4 12B + Audio VAE</p>
          </div>
          <div style={{ background: 'rgba(255,255,255,0.02)', padding: '12px', borderRadius: '10px', border: '1px solid rgba(168,85,247,0.2)' }}>
            <span style={{ color: '#c084fc', fontWeight: 700 }}>MiniMax H3 Omni</span>
            <p style={{ fontWeight: 600, color: '#fff', marginTop: '4px' }}>Ref2VA FP8 Scaled</p>
            <p style={{ color: 'var(--text-muted)', fontSize: '11px', marginTop: '2px' }}>Qwen3-VL 32B + 32 kHz stereo</p>
          </div>
          <div style={{ background: 'rgba(255,255,255,0.02)', padding: '12px', borderRadius: '10px' }}>
            <span style={{ color: 'var(--text-muted)' }}>Çıkarım:</span>
            <p style={{ fontWeight: 600, color: '#fff', marginTop: '4px' }}>ComfyUI (headless)</p>
            <p style={{ color: 'var(--text-muted)', fontSize: '11px', marginTop: '2px' }}>{status?.comfyui?.url || 'http://127.0.0.1:8188'}</p>
          </div>
          <div style={{ background: 'rgba(255,255,255,0.02)', padding: '12px', borderRadius: '10px' }}>
            <span style={{ color: 'var(--text-muted)' }}>GPU:</span>
            <p style={{ fontWeight: 600, color: '#fff', marginTop: '4px' }}>{status?.gpu?.name || 'Tespit edilmedi'}</p>
            <p style={{ color: 'var(--text-muted)', fontSize: '11px', marginTop: '2px' }}>{status?.gpu?.vram_gb ? status.gpu.vram_gb + ' GB VRAM' : '-'}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
