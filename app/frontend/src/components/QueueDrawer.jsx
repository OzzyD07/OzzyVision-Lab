import React from 'react';
import { Layers, ArrowUp, ArrowDown, XCircle, RotateCcw, CheckCircle, Clock, Trash2 } from 'lucide-react';
import { cancelJob, retryJob, reorderJob, deleteJob } from '../services/api';

export default function QueueDrawer({ jobs, activeJobId, onRefresh }) {
  const activeJob = jobs.find(j => j.id === activeJobId);
  const queuedJobs = jobs.filter(j => j.status === 'queued');
  const pastJobs = jobs.filter(j => j.status !== 'queued' && j.id !== activeJobId);

  const handleCancel = async (id) => {
    await cancelJob(id);
    if (onRefresh) onRefresh();
  };

  const handleRetry = async (id) => {
    await retryJob(id);
    if (onRefresh) onRefresh();
  };

  const handleReorder = async (id, dir) => {
    await reorderJob(id, dir);
    if (onRefresh) onRefresh();
  };

  const handleDelete = async (id) => {
    await deleteJob(id);
    if (onRefresh) onRefresh();
  };

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: '22px', fontWeight: 800, color: 'var(--text-primary)' }}>
            İşlem Kuyruğu
          </h2>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
            İşler tek GPU üzerinde sırayla yürütülür
          </p>
        </div>
        <span className="badge badge-gpu" style={{ padding: '6px 14px', fontSize: '13px' }}>
          Toplam: {jobs.length} Görev
        </span>
      </div>

      {/* ŞU AN ÇALIŞAN İŞ (ACTIVE JOB) */}
      {activeJob && (
        <div className="glass-panel" style={{ padding: '24px', border: '1px solid var(--border-active)', background: 'linear-gradient(180deg, rgba(99,102,241,0.08) 0%, rgba(15,18,28,0.85) 100%)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span className="badge badge-online">İŞLENİYOR</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 700, color: '#fff' }}>
                #{activeJob.id}
              </span>
            </div>
            <span style={{ fontSize: '20px', fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--accent-primary)' }}>
              %{activeJob.progress || 0}
            </span>
          </div>

          <p style={{ fontSize: '14px', fontWeight: 600, color: '#e0e7ff', marginBottom: '8px' }}>
            {activeJob.current_stage || 'Sinematik video render işlemi devam ediyor...'}
          </p>

          <div className="progress-bar-container" style={{ height: '10px', marginBottom: '14px' }}>
            <div className="progress-bar-fill" style={{ width: `${activeJob.progress || 0}%` }}></div>
          </div>

          <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
            <strong>Prompt:</strong> {activeJob.prompt}
          </p>
        </div>
      )}

      {/* SIRADA BEKLEYENLER */}
      <div>
        <h3 style={{ fontSize: '16px', fontWeight: 700, marginBottom: '12px', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Clock size={16} color="#06b6d4" />
          Kuyrukta Bekleyen Görevler ({queuedJobs.length})
        </h3>

        {queuedJobs.length === 0 ? (
          <div className="glass-panel" style={{ padding: '30px', textAlign: 'center', color: 'var(--text-muted)' }}>
            Şu anda işlem kuyruğunda bekleyen görev bulunmuyor. Stüdyo sekmesinden yeni bir sahne başlatabilirsiniz.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {queuedJobs.map((job, idx) => (
              <div
                key={job.id}
                className="glass-panel"
                style={{
                  padding: '16px 20px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '16px'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 700, color: 'var(--text-muted)' }}>
                    #{idx + 1}
                  </span>
                  <div>
                    <h4 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>
                      {job.prompt ? (job.prompt.length > 70 ? job.prompt.slice(0, 70) + '...' : job.prompt) : 'Video İşi'}
                    </h4>
                    <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                      {job.type === 'image_to_video' ? '📷 I2V' : '📝 T2V'} | {job.aspect_ratio} | {job.duration}s | Kalite: {job.quality}
                    </p>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <button
                    onClick={() => handleReorder(job.id, 'up')}
                    disabled={idx === 0}
                    className="btn-secondary"
                    style={{ padding: '6px 10px' }}
                    title="Yukarı Taşı"
                  >
                    <ArrowUp size={14} />
                  </button>
                  <button
                    onClick={() => handleReorder(job.id, 'down')}
                    disabled={idx === queuedJobs.length - 1}
                    className="btn-secondary"
                    style={{ padding: '6px 10px' }}
                    title="Aşağı Taşı"
                  >
                    <ArrowDown size={14} />
                  </button>
                  <button
                    onClick={() => handleCancel(job.id)}
                    className="btn-secondary"
                    style={{ padding: '6px 10px', color: '#fb7185' }}
                    title="İptal Et"
                  >
                    <XCircle size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* GEÇMİŞ İŞLER */}
      <div>
        <h3 style={{ fontSize: '16px', fontWeight: 700, marginBottom: '12px', color: 'var(--text-primary)' }}>
          Tamamlanan ve Arşiv Görevler ({pastJobs.length})
        </h3>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {pastJobs.slice(0, 15).map((job) => (
            <div
              key={job.id}
              className="glass-panel"
              style={{
                padding: '14px 20px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '16px',
                opacity: job.status === 'completed' ? 1 : 0.75
              }}
            >
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span className={`badge ${job.status === 'completed' ? 'badge-online' : 'badge-offline'}`}>
                    {job.status === 'completed' ? 'BAŞARILI' : (job.status === 'cancelled' ? 'İPTAL EDİLDİ' : 'BAŞARISIZ')}
                  </span>
                  <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                    {job.prompt ? (job.prompt.length > 60 ? job.prompt.slice(0, 60) + '...' : job.prompt) : job.id}
                  </span>
                </div>
                {job.error && (
                  <p style={{ fontSize: '11px', color: '#fb7185', marginTop: '4px' }}>
                    Hata: {job.error}
                  </p>
                )}
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                {(job.status === 'failed' || job.status === 'cancelled') && (
                  <button
                    onClick={() => handleRetry(job.id)}
                    className="btn-secondary"
                    style={{ padding: '6px 12px', fontSize: '12px' }}
                  >
                    <RotateCcw size={13} />
                    Yeniden Dene
                  </button>
                )}
                <button
                  onClick={() => handleDelete(job.id)}
                  className="btn-secondary"
                  style={{ padding: '6px 10px', color: 'var(--text-muted)' }}
                  title="Sil"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
