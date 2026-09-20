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
  headline?: string
  hook_line?: string
  story_angle?: string
  why_it_hits?: string[]
  risk_flags?: string[]
  candidate_types?: string[]
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
  clip_count: number
  duration_sec?: number | null
  thumbnail_url?: string | null
  source?: string
  views?: number | null
  status?: string
  current_stage?: string | null
  stage_progress?: number | null
  completed_stages?: string[]
  completed?: boolean
  error?: string | null
  created_at?: number
}

export interface ProjectLifecycleStage {
  id: string
  label: string
  state: 'completed' | 'active' | 'waiting' | 'failed' | 'skipped'
  progress?: number | null
  message?: string | null
  runtime_sec?: number | null
  error?: string | null
}

export interface ProjectLifecycle {
  job_id: string
  title: string | null
  source: string
  thumbnail_url?: string | null
  status: string
  current_stage?: string | null
  progress?: number | null
  clip_count: number
  rendered: boolean
  error?: string | null
  stages: ProjectLifecycleStage[]
}

export interface SetupState {
  has_gemini_key: boolean
  onboarded: boolean
}

export interface GenerationConfig {
  config_version?: number
  style_profile_id?: string
  layout?: {
    preset_id?: string | null
    target_aspect_ratio?: string | null
    content_aspect_ratio?: string | null
    content_bbox?: Record<string, number> | null
    background_mode?: string | null
    title_placement_relation?: string | null
    custom_overrides?: Record<string, unknown>
  }
  captions?: {
    preset_id?: string | null
    enabled?: boolean
    fill?: 'white' | 'yellow' | 'cyan'
    [key: string]: unknown
  }
  title_hook?: {
    mode?: 'none' | 'generated' | 'manual' | 'profile_default'
    manual_text?: string | null
    preset_id?: string | null
    placement?: string | null
    enabled?: boolean
    [key: string]: unknown
  }
  broll?: {
    mode?: 'off' | 'conservative' | 'balanced' | 'aggressive'
    presentation?: 'replace' | 'overlay' | 'mixed'
    [key: string]: unknown
  }
  sfx?: {
    mode?: 'off' | 'minimal' | 'balanced' | 'punchy'
    [key: string]: unknown
  }
  music?: {
    mode?: 'off' | 'low' | 'medium'
    [key: string]: unknown
  }
  camera?: {
    speaker_change?: 'cut' | 'pan' | 'locked'
    pan_duration_s?: number
    deadzone_frac?: number
    punch?: { enabled?: boolean; intensity?: number; [key: string]: unknown }
    zoom_lock_per_scene?: boolean
    [key: string]: unknown
  }
  transitions?: { mode?: 'none' | 'minimal' | 'profile_default' | 'custom'; [key: string]: unknown }
  user_overrides?: Record<string, unknown>
  [key: string]: unknown
}

export interface EditStyleProfile {
  id: string
  name: string
  scope: 'global' | 'creator' | 'page/account' | 'client' | 'custom'
  description: string | null
  config_version: number
  config: GenerationConfig
  is_active: boolean
  is_default: boolean
  created_at: number
  updated_at: number
}

export interface AnalyzerVideoSummary {
  job_id: string
  status: string
  created_at: number
  analyzed_at: number | null
  duration_sec: number
  job_mode: 'clipping' | 'research'
  scoring_status: 'available' | 'unavailable'
  source: {
    title: string | null
    type: string | null
    platform: string | null
    source_url: string | null
    video_url: string | null
    thumbnail_url: string | null
  }
  model: string | null
  scene_count: number | null
  speaker_count: number | null
  audio_event_count: number | null
  candidate_count: number | null
  scored_count: number | null
}

export interface AnalyzerWord {
  word: string
  start: number
  end: number
  score?: number
  speaker?: number
}

export interface AnalyzerSegment {
  start: number
  end: number
  text: string
  speaker?: number
  words?: AnalyzerWord[]
}

export interface AnalyzerCandidate extends Partial<Clip> {
  start: number
  end: number
  t1_raw?: Record<string, unknown>
  transcript?: string
}

export interface AnalyzerBBox { x: number; y: number; width: number; height: number }

export interface AnalyzerTextTrack {
  id: string; start: number; end: number; text: string; confidence: number
  bbox: AnalyzerBBox; center_x: number; center_y: number; relative_size: number; height_ratio: number
  line_count: number; duration: number; sample_hits: number
  classification: 'title_hook' | 'subtitles/captions' | 'label' | 'CTA' | 'watermark/username' | 'other'
  classification_confidence: number; canvas_position: 'top' | 'upper_middle' | 'center' | 'lower_middle' | 'bottom'
  content_relation: 'above_content' | 'overlay_top' | 'overlay_center' | 'overlay_bottom' | 'below_content' | 'outside_content'
  provenance: { detector: string; version: string | null }
}

export interface AnalyzerTimedEvidence {
  start: number; end: number; confidence: number; type?: string; face_count?: number
  [key: string]: unknown
}

export interface AnalyzerVisualUnit {
  id: string; start_ms: number; end_ms: number
  visual_type: 'talking_head' | 'b_roll' | 'screenshot' | 'screen_recording' | 'meme_or_graphic' | 'environment' | 'mixed' | 'uncertain'
  confidence: number; visual_subject: string | null
  relation_to_speech: { type: 'speaker_visible' | 'illustrates_speech' | 'demonstrates_speech' | 'contextual_cutaway' | 'unrelated_or_unclear' | 'no_speech'; confidence: number }
  source_shot_ids: string[]; representative_frame_refs: string[]
}

export interface AnalyzerFeature<T> {
  source: 'detector' | 'llm' | 'derived' | 'human'; confidence: number | null
  status: 'raw' | 'interpreted' | 'corrected' | 'unavailable'
  evidence: Record<string, unknown>; model_or_detector: string | null; value: T
}

export interface AnalyzerCaptionTrack {
  id: string; start_ms: number; end_ms: number; text: string; bbox: AnalyzerBBox; line_count: number
  confidence: number | null; role: 'caption' | 'emphasized_caption'
  transcript_alignment: { status: string; similarity: number | null; transcript_reference: { start: number; end: number; text: string } | null }
  visual_unit_ids: string[]
}

export interface AnalyzerCaptionEmphasis {
  start_ms: number; end_ms: number; emphasized_text: string
  emphasis_type: 'color_highlight' | 'size_emphasis' | 'isolated_word' | 'style_change' | 'possible_scale_pop' | 'unknown_emphasis'
  confidence: number; caption_track_id: string
}

export interface AnalyzerAudioSegment {
  id: string; start_ms: number; end_ms: number
  type: 'speech' | 'music' | 'sfx' | 'ambience' | 'silence' | 'mixed' | 'uncertain'
  subtype: string | null; confidence: number
}

export interface AnalyzerSfxEvent {
  id: string; start_ms: number; end_ms: number; type: 'sfx'; subtype: string | null
  confidence: number; energy_peak: number | null; source_detector_labels: string[]
}

export interface AnalyzerSourceEditingEvent {
  id: string; type: string; subtype?: string; timestamp_ms?: number
  start_ms: number; end_ms: number; confidence: number
  source: 'detector' | 'llm' | 'derived' | 'human'
  status: 'raw' | 'interpreted' | 'corrected' | 'unavailable'
  evidence: Record<string, unknown>
}

export interface AnalyzerSourceEditing {
  schema_version: number; status: string
  cuts: AnalyzerFeature<AnalyzerSourceEditingEvent[]>
  shots: AnalyzerFeature<AnalyzerSourceEditingEvent[]>
  transitions: AnalyzerFeature<AnalyzerSourceEditingEvent[]>
  reframes: AnalyzerFeature<AnalyzerSourceEditingEvent[]>
  zooms: AnalyzerFeature<AnalyzerSourceEditingEvent[]>
  pattern_interrupts: AnalyzerFeature<AnalyzerSourceEditingEvent[]>
  cross_modal_relationships: Array<Record<string, unknown>>
  metrics: Record<string, unknown>; capabilities: Record<string, unknown>
  evidence: Record<string, unknown>; provenance: Record<string, unknown>; limitations: string[]
}

export interface AnalyzerSemanticUnit {
  semantic_unit_id: string; start_ms: number; end_ms: number; speaker_ids: string[]
  transcript: string; semantic_summary: string; primary_story_role: string; secondary_roles: string[]
  confidence: number; source: 'detector' | 'llm' | 'derived' | 'human'
  status: 'raw' | 'interpreted' | 'corrected' | 'unavailable'; references: Record<string, string[]>
}

export interface AnalyzerStorySegment {
  story_id: string; start_ms: number; end_ms: number; semantic_unit_ids: string[]
  topic_summary: string; start_reason: string; end_reason: string; confidence: number
  completeness: {
    setup_complete: boolean; claim_complete: boolean; payoff_present: boolean
    conclusion_present: boolean; unresolved: boolean; next_topic_started: boolean
    likely_semantic_end_ms: number
  }
}

export interface AnalyzerSpeechStory {
  schema_version: number; status: string
  transcript: AnalyzerFeature<Record<string, unknown>>; speaker_structure: AnalyzerFeature<Record<string, unknown>>
  semantic_units: AnalyzerFeature<AnalyzerSemanticUnit[]>; story_segments: AnalyzerFeature<AnalyzerStorySegment[]>
  story_beats: AnalyzerFeature<AnalyzerStorySegment[]>
  hooks: AnalyzerFeature<Array<{ id: string; start_ms: number; end_ms: number; semantic_unit_id: string | null; hook_types: string[] }>>
  speech_signals: AnalyzerFeature<Array<Record<string, unknown>>>
  payoff_relationships: AnalyzerFeature<Array<Record<string, unknown>>>
  structural_metrics: Record<string, number | null>; evidence: Record<string, unknown>
  provenance: Record<string, unknown>; limitations: string[]
}

export type CreatorPerformanceLabel = 'strong' | 'average' | 'weak' | 'unclassified'
export type CreatorSelectionReason = 'creator_relative_strong' | 'creator_relative_average' | 'creator_relative_weak' | 'top_views' | 'manual' | 'editing_reference'
export type ResearchQueueStatus = 'queued' | 'claimed_by_worker' | 'downloading' | 'uploading' | 'uploaded' | 'waiting_for_analysis' | 'analyzing' | 'completed' | 'failed' | 'cancelled'

export interface CreatorSourceVideo {
  id: number; platform: 'youtube'; external_video_id: string; creator_source_id: number
  canonical_url: string; title: string | null; published_at: number | null; duration_sec: number | null
  views: number | null; likes: number | null; comments: number | null; thumbnail_url: string | null
  first_seen_at: number; last_metadata_refresh_at: number; download_status: string; analysis_status: string
  analysis_job_id: string | null; derived_performance_label: CreatorPerformanceLabel
  manual_performance_label: CreatorPerformanceLabel | null; performance_label: CreatorPerformanceLabel
  performance_metric: string | null; is_reference: boolean; is_editing_reference: boolean
  tab_origin: string | null; content_type: 'video' | 'short' | null
  selected_for_analysis: boolean; selected_at: number | null; selection_reason: CreatorSelectionReason | null
  research_queue_item_id: number | null; research_queue_status: ResearchQueueStatus | null
}

export interface CreatorSource {
  id: number; platform: 'youtube'; external_creator_id: string | null; handle: string | null
  display_name: string | null; canonical_channel_url: string; thumbnail_url: string | null
  subscriber_count: number | null; first_seen_at: number; last_refreshed_at: number; video_count?: number
}

export interface CreatorSourceDetail extends CreatorSource {
  videos: CreatorSourceVideo[]
  selection_summary: { selected: number; strong: number; average: number; weak: number; manual_reference: number }
}

export interface ResearchQueueItem {
  id: number; creator_video_id: number; creator_source_id: number; platform: 'youtube'
  external_video_id: string; canonical_url: string; catalog_title: string | null
  creator_handle: string | null; creator_display_name: string | null; source_metadata: Record<string, unknown>
  status: ResearchQueueStatus; created_at: number; started_at: number | null; completed_at: number | null
  updated_at: number; failure_reason: string | null; job_id: string | null
  analysis_status: string | null; analysis_error: string | null; progress_stage: string | null
}

export interface QueueSelectedResult {
  queued_count: number; skipped_already_queued: number; skipped_already_analyzed: number
  errors: Array<{ creator_video_id: number; error: string }>; queue_item_ids: number[]
}

export interface AnalyzerVideoDetail {
  analysis_run: {
    analysis_run_id: string; job_id: string; creator_video_id: number | null; source_identity: string | null
    analyzer_version: string; schema_version: number; pipeline_version: string | null; config_fingerprint: string | null
    status: string; artifact_path: string | null; started_at: number | null; completed_at: number | null
    created_at: number | null; error: string | null
  }
  analyzer_version: string
  video_dna: {
    source: Record<string, unknown>; provenance: Record<string, unknown>
    speech_story: AnalyzerSpeechStory; text_system: {
      title_hooks: AnalyzerFeature<Array<Record<string, unknown>>>; text_blocks: AnalyzerFeature<Array<Record<string, unknown>>>
      caption_tracks: AnalyzerFeature<AnalyzerCaptionTrack[]>; emphasis_events: AnalyzerFeature<AnalyzerCaptionEmphasis[]>
      overlays: Array<Record<string, unknown>>; caption_metrics: { captions_present?: boolean; caption_coverage_ratio?: number; caption_event_count?: number; emphasis_event_count?: number }
      caption_evidence: Record<string, unknown>; caption_provenance: Record<string, unknown>; caption_limitations: string[]
      caption_style: { status: string; reason: string }
    }; layout: Record<string, unknown>
    visual: {
      status: string; visual_units: AnalyzerFeature<AnalyzerVisualUnit[]>; b_roll_segments: AnalyzerFeature<Array<Record<string, unknown>>>
      objects_entities_summary: Array<{ label: string; confidence: number; unit_count: number }>
      scene_environment_summary: Array<{ label: string; confidence: number; unit_count: number }>
      actions_summary: Array<{ label: string; confidence: number; unit_count: number }>
      ratios_statistics: {
        talking_head_ratio?: number; b_roll_ratio?: number; screenshot_or_graphic_ratio?: number
        visual_change_rate_per_minute?: number; shot_count?: number; median_shot_duration_sec?: number; average_shot_duration_sec?: number
      }
      evidence: Record<string, unknown>; provenance: Record<string, unknown>; limitations: string[]
      observations: AnalyzerFeature<AnalyzerTimedEvidence[]>; scene_markers: AnalyzerFeature<number[]>
      object_action_understanding: { status: string; reason: string }; b_roll_detection: { status: string; reason: string }
    }
    source_editing: AnalyzerSourceEditing; audio: {
      status: string; audio_segments: AnalyzerFeature<AnalyzerAudioSegment[]>
      music_segments: AnalyzerFeature<Array<Record<string, unknown>>>; sfx_events: AnalyzerFeature<AnalyzerSfxEvent[]>
      dynamics: Record<string, unknown>; ducking_events: Array<{ id: string; start_ms: number; end_ms: number; confidence: number; type: string }>
      cross_modal_relationships: Array<{ relation_type: string; audio_event_id: string; target_type: string; target_id_reference: string; delta_ms: number; confidence: number }>
      metrics: { speech_coverage_ratio?: number; music_coverage_ratio?: number; silence_ratio?: number; sfx_event_count?: number; probable_ducking_event_count?: number }
      provenance: Record<string, unknown>; evidence: Record<string, unknown>; limitations: string[]
      events: AnalyzerFeature<Array<Record<string, unknown>>>; signal_summaries: Array<Record<string, unknown>>
      music_segmentation: { status: string; reason: string }; sound_effect_detection: { status: string; reason: string }
      audio_dynamics: { status: string; reason: string }; cross_modal_audio_alignment: { status: string; reason: string }
    }
    performance: Record<string, unknown>; uncertainty: Record<string, unknown>; human_corrections: Record<string, unknown>
  }
  job: AnalyzerVideoSummary & { error: string | null }
  source: AnalyzerVideoSummary['source'] & { probe: Record<string, number | string | boolean | null>; heatmap_available: boolean }
  transcript: { language: string | null; model: string | null; word_count: number | null; segments: AnalyzerSegment[] }
  speakers: { count: number | null; turns: Array<{ speaker: number; start: number; end: number }> }
  scenes: { timestamps: number[]; count: number | null; detector_outcome: string | null; detector_error: string | null }
  audio: {
    events: Array<{ type: string; start: number; end: number; confidence?: number; sources?: string[] }>
    counts: Record<string, number>
    arousal_source: string | null
    curves: Array<{ name: string; values: number[]; sample_count: number; grid_sec: number | null; min: number | null; max: number | null; mean: number | null }>
    audio_intelligence: Record<string, unknown> | null
    source_editing: Record<string, unknown> | null
    story_semantics: Record<string, unknown> | null
    detector_benchmark: Record<string, number>
  }
  source_analysis: {
    available: boolean
    text_tracks: AnalyzerTextTrack[]
    text_blocks: Array<{
      id: string; text: string; start: number; end: number; bbox: AnalyzerBBox; line_count: number
      confidence: number; canvas_position: string; content_relation: string; source_track_ids: string[]
      lines: Array<{ track_id: string; text: string; start: number; end: number; bbox: AnalyzerBBox; confidence: number }>
    }>
    title_hook_candidates: Array<{
      track_id: string; text: string; start: number; end: number; confidence: number
      classification: 'title_hook'; bbox: AnalyzerBBox; canvas_position: string; content_relation: string
      evidence: Record<string, unknown>; provenance: Record<string, unknown>
    }>
    source_layout: null | {
      canvas_aspect_ratio: number; primary_content_bbox: AnalyzerBBox; primary_content_aspect_ratio: number
      layout_mode: string; approximate_shape: string; rounded_corners: boolean; split_screen: boolean
      background_relationship: string; confidence: number; provenance: Record<string, unknown>
    }
    layout_signature: Record<string, unknown> | null
    visual_observations: AnalyzerTimedEvidence[]
    visual_understanding: Record<string, unknown> | null
    caption_system: Record<string, unknown> | null
    audio_intelligence: Record<string, unknown> | null
    source_editing_evidence: {
      shot_cuts: AnalyzerTimedEvidence[]; visual_change_density_per_minute: number | null
      layout_changes: AnalyzerTimedEvidence[]; b_roll_candidates: AnalyzerTimedEvidence[]; provenance: Record<string, unknown>
    }
    runtime: {
      ocr_sec: number | null; layout_sec: number | null; visual_sampling_sec: number | null
      sample_count: number | null; device: string | null; onnx_providers: string[]; artifact_size_bytes: number | null
      visual_semantic_sec: number | null; visual_semantic_sample_count: number | null
      visual_semantic_inference_batches: number | null; visual_semantic_peak_gpu_memory_bytes: number | null
      audio_intelligence_sec: number | null
      story_semantics_sec: number | null
    }
    provenance: Record<string, unknown>
  }
  candidate_analysis: { candidate_count: number | null; scored_count: number | null; clips: AnalyzerCandidate[] }
  generated_edit: {
    camera_settings: Record<string, unknown>
    camera_stats: Array<{ clip: number; tracks: number; switch_cuts: number; shot_cuts: number; punches: number }>
    device: string | null
    trajectories: Array<{
      clip: number; clip_start: number; clip_end: number; fps: number | null; frame_count: number; cuts: number[]
      punches: Array<{ start: number; end: number; source_start: number; source_end: number; trigger: string }>
      meta: Record<string, unknown>; crop_summary: { min_width: number | null; max_width: number | null }
    }>
    render: {
      outputs: Array<RenderOutput & { url: string | null }>
      caption_preset: string | null; caption_color: string | null; captions_burned: boolean | null
      acceleration: Record<string, string>
    }
  }
  provenance: {
    llm_mode: string | null; model: string | null
    llm_generation: { thinking_enabled?: boolean | null; generation_options?: Record<string, unknown> }
    scoring_config_version: number | null; asr_model: string | null; asr_device: string | null
    diarization_device: string | null; event_device: string | null
  }
  qa: Array<{
    id: number; start_sec: number; end_sec: number; target_type: string
    original: unknown; corrected: unknown; note: string | null; created_at: number
  }>
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
  width?: number
  height?: number
  media_url?: string
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
  feedback_adjustment?: number
  
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
