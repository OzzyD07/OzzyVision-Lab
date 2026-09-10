import React, { useState, useEffect } from 'react';
import Header from './components/Header';
import CreateStudio from './components/CreateStudio';
import QueueDrawer from './components/QueueDrawer';
import GalleryView from './components/GalleryView';
import SettingsModal from './components/SettingsModal';
import {
  fetchStatus, fetchJobs, fetchGallery, fetchCameraPresets, connectWebSocket
} from './services/api';

export default function App() {
  const [activeTab, setActiveTab] = useState('create'); // 'create' | 'queue' | 'gallery' | 'settings'
  const [status, setStatus] = useState(null);
  const [cameraPresets, setCameraPresets] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [gallery, setGallery] = useState([]);
  const [activeJobId, setActiveJobId] = useState(null);
  const [initialSettings, setInitialSettings] = useState(null);

  // Verileri çek
  const loadData = async () => {
    try {
      const [s, p, j, g] = await Promise.all([
        fetchStatus(),
        fetchCameraPresets(),
        fetchJobs(),
        fetchGallery()
      ]);
      setStatus(s);
      setCameraPresets(p.presets || []);
      setJobs(j.jobs || []);
      setGallery(g.videos || []);
      setActiveJobId(s.queue?.active_job_id || null);
    } catch (err) {
      console.error('[LoadData Error]', err);
    }
  };

  useEffect(() => {
    loadData();

    // WebSocket ile gerçek zamanlı ilerleme dinle
    const disconnectWs = connectWebSocket((wsMessage) => {
      if (wsMessage.type === 'state_update') {
        setActiveJobId(wsMessage.active_job_id);

        if (wsMessage.updated_job) {
          setJobs((prevJobs) => {
            const exists = prevJobs.some(j => j.id === wsMessage.updated_job.id);
            if (exists) {
              return prevJobs.map(j => j.id === wsMessage.updated_job.id ? wsMessage.updated_job : j);
            }
            return [wsMessage.updated_job, ...prevJobs];
          });

          // Eğer tamamlandıysa galeriyi yenile
          if (wsMessage.updated_job.status === 'completed') {
            fetchGallery().then(g => setGallery(g.videos || [])).catch(() => {});
          }
        }
      }
    });

    // 15 saniyede bir genel durum kontrolü
    const interval = setInterval(loadData, 15000);

    return () => {
      disconnectWs();
      clearInterval(interval);
    };
  }, []);

  // Galeri'den ayarları üretim paneline geri yükle
  const handleReuseSettings = (videoJob) => {
    setInitialSettings({
      model: videoJob.model || 'ltx25',
      prompt: videoJob.prompt,
      camera: videoJob.camera,
      aspect_ratio: videoJob.aspect_ratio,
      duration: videoJob.duration,
      quality: videoJob.quality,
      seed: videoJob.seed,
      asset_id: videoJob.asset_id,
      image_fidelity: videoJob.image_fidelity,
      ref_images: videoJob.ref_images || [],
      ref_videos: videoJob.ref_videos || [],
      ref_audios: videoJob.ref_audios || [],
      ref_image_size: videoJob.ref_image_size || 'match',
      loras: videoJob.loras || []
    });
    setActiveTab('create');
  };


  const activeJob = jobs.find(j => j.id === activeJobId);
  const queueCount = jobs.filter(j => j.status === 'queued').length;

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Üst Durum ve Navigasyon Çubuğu */}
      <Header
        status={status}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        queueCount={queueCount}
        onRefresh={loadData}
      />

      {/* Ana İçerik Görünümü */}
      <main style={{ flex: 1, paddingBottom: '60px' }}>
        {activeTab === 'create' && (
          <CreateStudio
            cameraPresets={cameraPresets}
            activeJob={activeJob}
            onJobCreated={(newJob) => {
              setJobs(prev => [newJob, ...prev]);
              setActiveTab('create');
            }}
            initialSettings={initialSettings}
            onClearInitialSettings={() => setInitialSettings(null)}
          />
        )}

        {activeTab === 'queue' && (
          <QueueDrawer
            jobs={jobs}
            activeJobId={activeJobId}
            onRefresh={loadData}
          />
        )}

        {activeTab === 'gallery' && (
          <GalleryView
            videos={gallery}
            cameraPresets={cameraPresets}
            onReuseSettings={handleReuseSettings}
            onRefresh={loadData}
          />
        )}

        {activeTab === 'settings' && (
          <SettingsModal status={status} />
        )}
      </main>
    </div>
  );
}
