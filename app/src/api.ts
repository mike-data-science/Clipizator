import type { JobResults, JobSummary, ProjectLifecycle, LoopOverview, SetupState, SyncSummary, Campaign, CampaignFull, CampaignVideo, CampaignClip, CampaignMoment, AnalyzerVideoSummary, AnalyzerVideoDetail, CreatorPerformanceLabel, CreatorSelectionReason, CreatorSource, CreatorSourceDetail, CreatorSourceVideo, QueueSelectedResult, ResearchQueueItem, EditStyleProfile, GenerationConfig } from './types'

const API = '/api'

async function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

async function put<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

async function get<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}


/* ---- WebSocket event bus (replaces Tauri's listen/emit) ---- */

type EventCallback = (payload: unknown) => void
const _listeners: Map<string, Set<EventCallback>> = new Map()
let _ws: WebSocket | null = null
let _wsReconnectTimer: ReturnType<typeof setTimeout> | null = null

function _ensureWs() {
  if (_ws && (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING)) return
  
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  // If running via Vite dev server, vite.config.ts proxies /ws
  // If running in production, it will connect to the same origin
  const wsUrl = `${protocol}//${host}/ws`
  
  _ws = new WebSocket(wsUrl)
  _ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data)
      // broadcast to all 'pipeline-event' listeners
      const cbs = _listeners.get('pipeline-event')
      if (cbs) cbs.forEach((cb) => cb({ payload: data }))
    } catch { /* ignore non-JSON */ }
  }
  _ws.onclose = () => {
    if (_wsReconnectTimer) clearTimeout(_wsReconnectTimer)
    _wsReconnectTimer = setTimeout(_ensureWs, 2000)
  }
  _ws.onerror = () => _ws?.close()
}

export function listen<T = unknown>(
  event: string,
  callback: (ev: { payload: T }) => void,
): Promise<() => void> {
  _ensureWs()
  if (!_listeners.has(event)) _listeners.set(event, new Set())
  const cbs = _listeners.get(event)!
  const cb = callback as EventCallback
  cbs.add(cb)
  return Promise.resolve(() => { cbs.delete(cb) })
}

/* ---- file URL helper ---- */

function fileUrl(absolutePath: string): string {
  // Convert an absolute filesystem path to a /media/ URL.
  // The backend serves files from PUBLIKCLIP_HOME at /media/.
  // Paths look like: C:\Users\...\.publikclip\jobs\<id>\render_0.mp4
  // We extract everything after .publikclip/ (or .publikclip\)
  const markers = ['.publikclip/', '.publikclip\\']
  for (const marker of markers) {
    const idx = absolutePath.indexOf(marker)
    if (idx !== -1) {
      const relative = absolutePath.slice(idx + marker.length).replace(/\\/g, '/')
      return `/media/${relative}`
    }
  }
  // fallback: try to use the path as-is
  return `/media/${absolutePath.replace(/\\/g, '/')}`
}

/* ---- API object ---- */

export const api = {
  uploadVideo: async (file: File, llm: string, gemini_model: string, captions: string, asr_model: string, generation_config?: GenerationConfig) => {
    const formData = new FormData()
    formData.append('video', file)
    formData.append('llm', llm)
    formData.append('gemini_model', gemini_model)
    formData.append('captions', captions)
    formData.append('asr_model', asr_model)
    if (generation_config) formData.append('generation_config', JSON.stringify(generation_config))
    const res = await fetch(`${API}/jobs/upload`, {
      method: 'POST',
      body: formData,
    })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },
  runJob: (source: string, llm: string, gemini_model: string, captions: string, asr_model: string, caption_color?: string, generation_config?: GenerationConfig) =>
    post<{ ok: boolean; job_id: string }>('/jobs', { source, llm, gemini_model, captions, asr_model, caption_color, generation_config }),
  listStyleProfiles: () => get<{ profiles: EditStyleProfile[] }>('/style-profiles'),
  getStyleProfile: (profileId: string) => get<EditStyleProfile>(`/style-profiles/${encodeURIComponent(profileId)}`),
  getGenerationConfig: (jobId: string) => get<{ job_id: string; config: GenerationConfig; resolved_config: GenerationConfig }>(`/jobs/${encodeURIComponent(jobId)}/generation-config`),
  saveGenerationConfig: (jobId: string, config: GenerationConfig) => put(`/jobs/${encodeURIComponent(jobId)}/generation-config`, config),
  previewGenerationConfig: (jobId: string, config?: GenerationConfig) => post<{ resolved_config: GenerationConfig }>(`/jobs/${encodeURIComponent(jobId)}/generation-config/preview`, config),
  resumeJob: (jobId: string, llm?: string, gemini_model?: string, captions?: string, camera?: string, asr_model?: string) =>
    post<void>(`/jobs/${jobId}/resume`, { llm, gemini_model, captions, camera, asr_model }),
  jobResults: (jobId: string) => get<JobResults>(`/jobs/${jobId}/results`),
  jobLifecycle: (jobId: string) => get<ProjectLifecycle>(`/jobs/${encodeURIComponent(jobId)}/lifecycle`),
  listJobs: () => get<JobSummary[]>('/jobs'),
  previewUrl: (jobId: string, clipIndex: number, revision = 0) =>
    `${API}/jobs/${encodeURIComponent(jobId)}/clips/${clipIndex}/preview?v=${revision}`,
  saveGeminiKey: (key: string) => post<boolean>('/settings/gemini-key', { key }),
  savePexelsKey: (key: string) => post<boolean>('/settings/pexels-key', { key }),
  setupState: () => get<SetupState>('/setup'),
  markOnboarded: () => post<void>('/setup/onboard'),
  checkOllama: () => get<{ running: boolean; models: string[] }>('/ollama/status'),
  listAnalyzerVideos: () => get<AnalyzerVideoSummary[]>('/analyzer/videos'),
  analyzerVideo: (jobId: string) => get<AnalyzerVideoDetail>(`/analyzer/videos/${encodeURIComponent(jobId)}`),
  listCreatorSources: () => get<CreatorSource[]>('/analyzer/sources'),
  addCreatorSource: (source: string) => post<CreatorSourceDetail>('/analyzer/sources', { source }),
  refreshCreatorSource: (id: number) => post<CreatorSourceDetail>(`/analyzer/sources/${id}/refresh`),
  creatorSource: (id: number) => get<CreatorSourceDetail>(`/analyzer/sources/${id}`),
  setCreatorVideoPerformance: (id: number, label: CreatorPerformanceLabel | null) => put<CreatorSourceVideo>(`/analyzer/source-videos/${id}/performance`, { label }),
  setCreatorVideoReferences: (id: number, reference?: boolean, editing_reference?: boolean) => put<CreatorSourceVideo>(`/analyzer/source-videos/${id}/references`, { reference, editing_reference }),
  setCreatorSelection: (creatorId: number, videoIds: number[], selected: boolean, reason: CreatorSelectionReason | null = null) => put<CreatorSourceDetail>(`/analyzer/sources/${creatorId}/selection`, { video_ids: videoIds, selected, reason }),
  clearCreatorSelection: (creatorId: number) => post<CreatorSourceDetail>(`/analyzer/sources/${creatorId}/selection/clear`),
  autoSelectCreatorSample: (creatorId: number) => post<CreatorSourceDetail>(`/analyzer/sources/${creatorId}/selection/auto`),
  queueSelectedCreatorVideos: (creatorId: number) => post<QueueSelectedResult>(`/analyzer/sources/${creatorId}/research-queue`),
  listResearchQueue: () => get<ResearchQueueItem[]>('/analyzer/research-queue'),
  retryResearchQueueItem: (itemId: number) => post<ResearchQueueItem>(`/analyzer/research-queue/${itemId}/retry`),
  exportClip: (jobId: string, clipIndex: number, title?: string) => {
    // Trigger a browser download
    const params = new URLSearchParams()
    if (title) params.set('title', title)
    const url = `${API}/jobs/${jobId}/clips/${clipIndex}/download?${params}`
    const a = document.createElement('a')
    a.href = url
    a.download = `${title || 'clip'}.mp4`
    a.click()
    return Promise.resolve(url)
  },

  // Edit commands
  editTool: (jobId: string, editCmd: string, body?: Record<string, unknown>) =>
    post(`/jobs/${jobId}/edit/${editCmd}`, body),
  runEditRender: (jobId: string, clipIndex: number) =>
    post(`/jobs/${jobId}/clips/${clipIndex}/render`),
  submitClipFeedback: (jobId: string, clipIndex: number, label: 'approved' | 'rejected' | 'neutral', reason?: string) =>
    post<{ ok: boolean; feedback: Record<string, unknown> }>(`/jobs/${jobId}/clips/${clipIndex}/feedback`, { label, reason }),
  saveClipEdits: (jobId: string, edits: Record<string, unknown>) =>
    put(`/jobs/${jobId}/edits`, edits),

  // Instagram
  igStatus: () => get<{ connected: boolean; username?: string }>('/instagram/status'),
  igConnect: (appId: string, appSecret: string) =>
    post<{ ok: boolean; username?: string }>('/instagram/connect', { appId, appSecret }),
  igSync: () => post<SyncSummary>('/instagram/sync'),
  igOverview: () => get<LoopOverview>('/instagram/overview'),
  igLink: (jobId: string, clip: number, mediaId: string, source: 'manual' | 'match_confirmed') =>
    post<{ ok: boolean }>('/instagram/link', { job_id: jobId, clip, media_id: mediaId, source }),
  igUnlink: (mediaId: string) =>
    post<{ ok: boolean }>('/instagram/unlink', { media_id: mediaId }),
  igReject: (mediaId: string, jobId: string, clip: number) =>
    post<{ ok: boolean }>('/instagram/reject', { media_id: mediaId, job_id: jobId, clip }),

  // Campaigns
  listCampaigns: () => get<Campaign[]>('/campaigns'),
  createCampaign: (name: string, description?: string, rules?: string) =>
    post<Campaign>('/campaigns', { name, description, rules }),
  getCampaign: (id: string) => get<CampaignFull>(`/campaigns/${id}`),
    refreshCampaignVideo: (campaignId: string, videoId: number) =>
      post<{ ok: boolean; job_id: string; message: string }>(`/campaigns/${campaignId}/videos/${videoId}/refresh`),
  updateCampaign: (id: string, name?: string, description?: string, rules?: string) =>
    put<{ ok: boolean }>(`/campaigns/${id}`, { name, description, rules }),
  deleteCampaign: (id: string) =>
    fetch(`${API}/campaigns/${id}`, { method: 'DELETE' }).then(r => r.json()),
    
  addCampaignVideo: (id: string, url: string) =>
    post<CampaignVideo>(`/campaigns/${id}/videos`, { url }),
  deleteCampaignVideo: (campaignId: string, videoId: number) =>
    fetch(`${API}/campaigns/${campaignId}/videos/${videoId}`, { method: 'DELETE' }).then(r => r.json()),
    
  getCampaignTranscripts: (id: string, q?: string) => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    return get<unknown[]>(`/campaigns/${id}/transcripts?${params}`)
  },
    
  addCampaignClip: (id: string, clip: Partial<CampaignClip>) =>
    post<CampaignClip>(`/campaigns/${id}/clips`, clip),
  updateCampaignClip: (campaignId: string, clipId: number, clip: Partial<CampaignClip>) =>
    put<{ ok: boolean }>(`/campaigns/${campaignId}/clips/${clipId}`, clip),
  deleteCampaignClip: (campaignId: string, clipId: number) =>
    fetch(`${API}/campaigns/${campaignId}/clips/${clipId}`, { method: 'DELETE' }).then(r => r.json()),
    
  analyzeClip: (id: string, url: string, role: 'mine' | 'competitor' = 'competitor', settings?: { download: boolean; transcribe: boolean; analyze: boolean }) =>
    post<{ ok: boolean; message: string }>(`/campaigns/${id}/clips/analyze`, { url, role, settings }),
    
  importAnalyticsCsv: (id: string, file: File) => {
    return file.text().then(text => 
      fetch(`${API}/campaigns/${id}/clips/import-csv`, {
        method: 'POST',
        headers: { 'Content-Type': 'text/csv' },
        body: text
      }).then(r => r.json())
    )
  },
    
  analyzeCampaign: (id: string, options?: { llm_mode?: string, gemini_model?: string, video_urls?: string[] }) =>
    post<{ ok: boolean }>(`/campaigns/${id}/analyze`, options || {}),
  getCampaignMoments: (id: string, unclipped?: boolean) => {
    const params = new URLSearchParams()
    if (unclipped) params.set('unclipped', 'true')
    return get<CampaignMoment[]>(`/campaigns/${id}/moments?${params}`)
  },
  getCampaignHooks: (id: string) =>
    get<unknown[]>(`/campaigns/${id}/hooks`),
  getCampaignInsights: (id: string) =>
    get<{ feature_weights: Record<string, number>; feedback: { total: number; approvals: number; rejections: number; net: number } }>(`/campaigns/${id}/insights`),
    
  // Analyzer
  getVideoRanking: (id: string) =>
    get<Array<{ video_url: string; clip_potential: number; total_score: number }>>(`/campaigns/${id}/analyzer/video-ranking`),
  getHookRecommendations: (id: string) =>
    get<{ recommendation: string; visual_score: number; audio_score: number }>(`/campaigns/${id}/analyzer/hook-recommendations`),
  getCompetitorMatches: (campaignId: string, videoUrl: string) =>
    get<Array<{ clip_url: string; competitor_text: string; visual_hook: string; matched_in_video: string; start_sec: number; end_sec: number; confidence: number }>>(`/campaigns/${campaignId}/competitor-matches?video_url=${encodeURIComponent(videoUrl)}`),
  improveHook: (campaignId: string, matched_transcript: string, competitor_visual_hook: string) =>
    post<{ visual_hooks: string[], audio_hooks: string[] }>(`/campaigns/${campaignId}/analyzer/improve-hook`, { matched_transcript, competitor_visual_hook }),
  searchHashtag: (campaignId: string, hashtag: string) =>
    post<{ ok: boolean, message: string }>(`/campaigns/${campaignId}/hashtag-search`, { hashtag }),

  deleteJob: async (jobId: string) => {
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' })
    if (!response.ok) throw new Error(await response.text())
    return response.json()
  },

  fileUrl,
}
