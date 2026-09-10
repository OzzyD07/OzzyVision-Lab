/**
 * OzzyVision-Lab API istemcisi
 */

const API_BASE = '/api';

export async function fetchStatus() {
  const res = await fetch(`${API_BASE}/status`);
  if (!res.ok) throw new Error('Status alınamadı');
  return res.json();
}

export async function createJob(payload) {
  const res = await fetch(`${API_BASE}/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error('İş oluşturulamadı');
  return res.json();
}

export async function fetchJobs(limit = 50) {
  const res = await fetch(`${API_BASE}/jobs?limit=${limit}`);
  if (!res.ok) throw new Error('İş listesi alınamadı');
  return res.json();
}

export async function cancelJob(jobId) {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/cancel`, { method: 'POST' });
  return res.json();
}

export async function retryJob(jobId) {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/retry`, { method: 'POST' });
  return res.json();
}

export async function reorderJob(jobId, direction) {
  const formData = new FormData();
  formData.append('direction', direction);
  const res = await fetch(`${API_BASE}/jobs/${jobId}/reorder`, {
    method: 'POST',
    body: formData
  });
  return res.json();
}

export async function deleteJob(jobId) {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`, { method: 'DELETE' });
  return res.json();
}

export async function uploadAsset(file) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/assets/upload`, {
    method: 'POST',
    body: formData
  });
  if (!res.ok) throw new Error('Görsel yüklenemedi');
  return res.json();
}

export async function fetchGallery(limit = 50) {
  const res = await fetch(`${API_BASE}/gallery?limit=${limit}`);
  if (!res.ok) throw new Error('Galeri yüklenemedi');
  return res.json();
}

export async function fetchCameraPresets() {
  const res = await fetch(`${API_BASE}/presets/camera`);
  if (!res.ok) throw new Error('Kamera presetleri alınamadı');
  return res.json();
}

export async function enhancePromptApi(prompt) {
  const res = await fetch(`${API_BASE}/prompt/enhance`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt })
  });
  if (!res.ok) throw new Error('Prompt zenginleştirilemedi');
  return res.json();
}

export async function fetchLoras() {
  const res = await fetch(`${API_BASE}/loras`);
  if (!res.ok) throw new Error('LoRA listesi alınamadı');
  return res.json();
}

export async function downloadLora(payload) {
  const res = await fetch(`${API_BASE}/loras/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'LoRA indirme başlatılamadı');
  }
  return res.json();
}

export async function fetchLoraDownloads() {
  const res = await fetch(`${API_BASE}/loras/downloads`);
  if (!res.ok) throw new Error('İndirmeler alınamadı');
  return res.json();
}

export async function fetchLoraDownloadProgress(taskId) {
  const res = await fetch(`${API_BASE}/loras/downloads/${taskId}`);
  if (!res.ok) throw new Error('İndirme durumu alınamadı');
  return res.json();
}

export async function deleteLora(filename) {
  const res = await fetch(`${API_BASE}/loras/${encodeURIComponent(filename)}`, {
    method: 'DELETE'
  });
  if (!res.ok) throw new Error('LoRA silinemedi');
  return res.json();
}

export async function freeVram() {
  const res = await fetch(`${API_BASE}/system/free_vram`, { method: 'POST' });
  if (!res.ok) throw new Error('GPU belleği boşaltılamadı');
  return res.json();
}

export function connectWebSocket(onStateUpdate) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/jobs`;
  let ws = null;
  let reconnectTimer = null;

  function connect() {
    try {
      ws = new WebSocket(wsUrl);
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          onStateUpdate(data);
        } catch (e) {
          console.error('[WS Parse Error]', e);
        }
      };

      ws.onclose = () => {
        reconnectTimer = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch (e) {
      reconnectTimer = setTimeout(connect, 3000);
    }
  }

  connect();

  return () => {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (ws) ws.close();
  };
}
