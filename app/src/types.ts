export interface PipelineEvent {
  event: string
  stage?: string
  fraction?: number
  message?: string
  job_id?: string
  ok?: boolean
  error?: string
  [key: string]: unknown
}

export interface Adjustment {
  rule: string
  factor: number
  reason: string
}

export interface MusicBrief {
  genre: string
  instruments: string[]
  mood: string
  theme: string
  energy: string
  bpm_range: string
  duck_intensity: string
  mood_prior?: string
  alternatives: { genre: string; mood: string; bpm_range: string }[]
}

export interface Clip {
  start: number
  end: number
  score: number
  best_platform: string
  platform_scores: Record<string, number>
  subscores: Record<string, number>
  adjustments: Adjustment[]
  signals_fired: string[]
  signals_missing: string[]
  confidence: string
  summary: string
  arousal_pct: number
  heatmap_pct: number | null
  curve_score: number
  music: MusicBrief | null
  t1_raw?: Record<string, unknown>
}

export interface RenderOutput {
  clip: number
  path: string
  score: number
  best_platform: string
  duration: number
  words: number
  event_tags: number
}

export interface JobResults {
  job_id: string
  dir: string
  ingest: {
    title: string
    heatmap: unknown[] | null
    probe: { duration_sec: number; width: number; height: number }
  } | null
  score: { clips: Clip[]; llm_mode: string; model: string; scored_count: number } | null
  render: { outputs: RenderOutput[]; emoji_ok: boolean; caption_preset: string } | null
  events: { counts: Record<string, number>; timeline: unknown[]; arousal_source: string } | null
  candidates: { count: number; effective_weights: Record<string, number>; heatmap_present: boolean } | null
}

export interface JobSummary {
  id: string
  title: string | null
  ingested: boolean
  rendered: boolean
}

export interface SetupState {
  has_gemini_key: boolean
  onboarded: boolean
}

/* ---------- the Instagram loop ---------- */

export interface LoopMetrics {
  views?: number | null
  reach?: number | null
  likes?: number | null
  comments?: number | null
  saved?: number | null
  shares?: number | null
  reposts?: number | null
  total_interactions?: number | null
  ig_reels_avg_watch_time?: number | null
  ig_reels_video_view_total_time?: number | null
  reels_skip_rate?: number | null
}

export interface LoopLinked {
  job_id: string
  clip_index: number
  media_id: string | null
  link_source: string
  linked_at: number
  score: number
  reels_score: number
  config_version: number
  subscores: Record<string, number> | null
  adjustments: Adjustment[] | null
  signals_fired: string[] | null
  signals_missing: string[] | null
  summary: string
  clip_duration: number | null
  clip_thumb: string | null
  ig_thumb: string | null
  permalink: string | null
  caption: string | null
  posted_at: number | null
  media_deleted: boolean
  media_age_hours: number | null
  settling: boolean
  metrics: LoopMetrics | null
  snapshots: { age_hours: number | null; views: number | null }[]
  snapshot_count: number
}

export interface LoopSuggestion {
  media_id: string
  job_id: string
  clip_index: number
  confidence: number
  clip_summary: string
  clip_duration: number | null
  clip_thumb: string | null
  clip_reels_score: number | null
}

export interface LoopUnlinked {
  media_id: string
  thumb: string | null
  permalink: string | null
  caption: string
  posted_at: number | null
  duration_s: number | null
  copyright_flagged: boolean
  suggestion: LoopSuggestion | null
}

export interface LoopClip {
  job_id: string
  clip_index: number
  summary: string
  duration: number | null
  reels_score: number | null
  thumb: string | null
  linked: boolean
}

export interface CalibrationVersion {
  version: number
  constants: Record<string, number>
  fitted_from_n?: number | null
  spearman_rho?: number | null
  pairwise_acc?: number | null
  note?: string | null
  created_at?: number | null
}

export interface LoopReport {
  pairs: number
  ready: boolean
  note?: string
  spearman_rho?: number | null
  pairwise_accuracy?: number | null
  kendall_tau?: number | null
}

export interface LoopOverview {
  connected: boolean
  username: string | null
  last_synced_at: number | null
  linked: LoopLinked[]
  unlinked: LoopUnlinked[]
  clip_library: LoopClip[]
  report: LoopReport
  calibration: {
    active: CalibrationVersion
    history: CalibrationVersion[]
    qualifying_outcomes: number
    recomputable_outcomes: number
    threshold: number
  }
}

export interface SyncSummary {
  ok: boolean
  error?: string
  username?: string
  new_media?: number
  thumbs_cached?: number
  snapshots_pulled?: number
  tombstoned?: number
  fit?: { applied: boolean; version?: number; reason?: string }
}

/* ---------- Campaigns & Analytics ---------- */

export interface Campaign {
  id: string
  name: string
  description: string
  rules: string
  created_at: number
  video_count?: number
  clip_count?: number
  moment_count?: number
}

export interface CampaignVideo {
  id: number
  campaign_id: string
  video_url: string
  job_id: string | null
  title: string | null
  channel: string | null
  duration_sec: number | null
  channel_subscribers: number | null
  added_at: number
  has_transcript?: number
  views?: number
  has_ingest?: boolean
  has_asr?: boolean
}

export interface CampaignClip {
  id: number
  campaign_id: string
  role: 'mine' | 'competitor'
  job_id?: string
  clip_index?: number
  source_video_url?: string
  clip_url?: string
  title?: string
  platform?: string
  posted_at?: number
  
  hook_text?: string
  hook_type?: string
  hook_template?: string
  transcript_excerpt?: string
  start_sec?: number
  end_sec?: number
  duration_sec?: number
  
  views?: number
  likes?: number
  comments?: number
  shares?: number
  watch_time_pct?: number
  avg_view_duration_sec?: number
  ctr?: number
  impressions?: number
  retention_3s?: number
  retention_5s?: number
  swipe_away_pct?: number
  
  channel_subscribers?: number
  views_per_subscriber?: number
  
  predicted_score?: number
  hook_score?: number
  funniness_score?: number
  shock_score?: number
  curiosity_score?: number
  value_score?: number
  
  notes?: string
  raw_metrics_json?: string
  updated_at?: number
  thumbnail_path?: string
  hook_text_overlay?: string
  audio_hook?: string
  audio_transcript_json?: string
  traffic_source?: string
}

export interface ClipAnalytics {
  views?: number
  likes?: number
  watch_time_pct?: number
  avg_view_duration_sec?: number
  impressions?: number
  ctr?: number
}

export interface CampaignMoment {
  id: number
  campaign_id: string
  video_url: string
  start_sec: number
  end_sec: number
  transcript_text: string
  word_count: number
  
  sentence_count: number
  avg_sentence_length: number
  question_density: number
  specificity_score: number
  controversy_score: number
  emotional_arc_type: string
  first_person_ratio: number
  imperative_density: number
  dialogue_ratio: number
  incomplete_thought: number
  
  hook_text: string
  hook_type: string
  hook_template: string
  hook_density_score: number
  first_word_quality: number
  time_to_curiosity: number
  
  payoff_density: number
  middle_energy: number
  drop_off_risk: number
  energy_shape: string
  
  llm_hook_score: number
  llm_funniness: number
  llm_shock: number
  llm_curiosity_gap: number
  llm_value_score: number
  llm_summary: string
  llm_self_contained: number
  llm_hook_type: string
  
  sim_to_top_clips: number
  predicted_virality: number
  recommendation_score: number
  uncertainty: number
  
  has_clip: number
  clip_views?: number
  clip_role?: string
  analyzed_at: number
}

export interface CampaignFull extends Campaign {
  videos: CampaignVideo[]
  clips: CampaignClip[]
  moments: CampaignMoment[]
}

