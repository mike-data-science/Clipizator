import { useState, useEffect } from 'react'
import type { JobSummary } from '../types'
import KeyModal from './KeyModal'

const STAGE_ORDER = [
  'diarize', 'events', 'candidates', 'score', 'camera', 'render'
]

const STAGE_LABELS: Record<string, string> = {
  diarize: 'SPEAKERS',
  events: 'LISTEN',
  candidates: 'SCAN',
  score: 'JUDGE',
  camera: 'DIRECT',
  render: 'RENDER'
}

const CAPTION_PRESET_DEFS: Record<string, {
  id: string
  label: string
  subtitle: string
  fontFamily: string
  fontSize: number
  primaryColor: string
  activeColor: string
  emphasisColor: string
  shadow: string
  stroke: string
  uppercase: boolean
  dotColor: string
  badge: string
}> = {
  beast: {
    id: 'beast',
    label: 'Viral Yellow',
    subtitle: 'CapCut Signature Yellow & Coral',
    fontFamily: "'Anton', 'Impact', sans-serif",
    fontSize: 32,
    primaryColor: '#FFFFFF',
    activeColor: '#FAFF00',
    emphasisColor: '#FF2D55',
    stroke: '3px #000',
    shadow: '2px 2px 0px #000, -2px -2px 0px #000, 2px -2px 0px #000, -2px 2px 0px #000, 0 4px 10px rgba(0,0,0,0.85)',
    uppercase: true,
    dotColor: '#FAFF00',
    badge: 'CAPCUT'
  },
  hormozi: {
    id: 'hormozi',
    label: 'Neon Lime',
    subtitle: 'CapCut Neon Green & Lemon',
    fontFamily: "'Archivo Black', sans-serif",
    fontSize: 27,
    primaryColor: '#FFFFFF',
    activeColor: '#00FF66',
    emphasisColor: '#FAFF00',
    stroke: '2.5px #000',
    shadow: '2px 2px 0px #000, -2px -2px 0px #000, 2px -2px 0px #000, -2px 2px 0px #000, 0 3px 8px rgba(0,0,0,0.8)',
    uppercase: true,
    dotColor: '#00FF66',
    badge: 'VIRAL'
  },
  'karaoke-pop': {
    id: 'karaoke-pop',
    label: 'Cyan Glow',
    subtitle: 'CapCut Electric Cyan & Pink',
    fontFamily: "'Archivo Black', sans-serif",
    fontSize: 26,
    primaryColor: '#FFFFFF',
    activeColor: '#00E5FF',
    emphasisColor: '#FF2DF1',
    stroke: '2.5px #000',
    shadow: '2px 2px 0px #000, -2px -2px 0px #000, 2px -2px 0px #000, -2px 2px 0px #000, 0 0 16px rgba(0,229,255,0.6)',
    uppercase: true,
    dotColor: '#00E5FF',
    badge: 'POP'
  },
  'neon-glow': {
    id: 'neon-glow',
    label: 'Cyber Pink',
    subtitle: 'CapCut Hot Pink & Cyan',
    fontFamily: "'Archivo Black', sans-serif",
    fontSize: 26,
    primaryColor: '#FFFFFF',
    activeColor: '#FF2DF1',
    emphasisColor: '#00E5FF',
    stroke: '2.5px #1A001A',
    shadow: '2px 2px 0px #1a001a, -2px -2px 0px #1a001a, 2px -2px 0px #1a001a, -2px 2px 0px #1a001a, 0 0 18px rgba(255,45,241,0.7)',
    uppercase: true,
    dotColor: '#FF2DF1',
    badge: 'CYBER'
  },
  redbull: {
    id: 'redbull',
    label: 'Flame Orange',
    subtitle: 'CapCut Sunset Orange & Yellow',
    fontFamily: "'Anton', 'Impact', sans-serif",
    fontSize: 32,
    primaryColor: '#FFFFFF',
    activeColor: '#FF5500',
    emphasisColor: '#FAFF00',
    stroke: '3px #000',
    shadow: '2px 2px 0px #000, -2px -2px 0px #000, 2px -2px 0px #000, -2px 2px 0px #000, 0 4px 10px rgba(0,0,0,0.85)',
    uppercase: true,
    dotColor: '#FF5500',
    badge: 'ACTION'
  },
  classic: {
    id: 'classic',
    label: 'Clean White',
    subtitle: 'CapCut Classic Subtitles',
    fontFamily: "'Inter', sans-serif",
    fontSize: 24,
    primaryColor: '#FFFFFF',
    activeColor: '#FAFF00',
    emphasisColor: '#FAFF00',
    stroke: '2px #000',
    shadow: '1.5px 1.5px 0px #000, -1.5px -1.5px 0px #000, 1.5px -1.5px 0px #000, -1.5px 1.5px 0px #000',
    uppercase: false,
    dotColor: '#FAFF00',
    badge: 'CLEAN'
  },
  minimal: {
    id: 'minimal',
    label: 'Minimal Sky',
    subtitle: 'CapCut Sky Blue Accent',
    fontFamily: "'Inter', sans-serif",
    fontSize: 20,
    primaryColor: '#FFFFFF',
    activeColor: '#38BDF8',
    emphasisColor: '#FAFF00',
    stroke: '1.5px #000',
    shadow: '1px 1px 0px #000, -1px -1px 0px #000, 1px -1px 0px #000, -1px 1px 0px #000',
    uppercase: false,
    dotColor: '#38BDF8',
    badge: 'MODERN'
  }
}

const CAPTION_PRESETS = Object.keys(CAPTION_PRESET_DEFS)

const SAMPLE_PHRASES = [
  [
    { text: 'THIS', emp: false },
    { text: 'IS', emp: false },
    { text: 'HOW', emp: false },
    { text: 'VIRAL', emp: true },
    { text: 'CLIPS', emp: false },
    { text: 'EXPLODE', emp: true },
  ],
  [
    { text: 'WATCH', emp: true },
    { text: 'WHAT', emp: false },
    { text: 'HAPPENS', emp: false },
    { text: 'AT', emp: false },
    { text: 'THE', emp: false },
    { text: 'END', emp: true },
  ],
  [
    { text: 'THE', emp: false },
    { text: 'SECRET', emp: true },
    { text: 'TO', emp: false },
    { text: '10M+', emp: true },
    { text: 'VIEWS', emp: false },
  ],
]

interface Props {
  jobs: JobSummary[]
  running: boolean
  stages: Record<string, { fraction: number; message: string }>
  error: string | null
  initialSource?: string
  onRun: (source: string, llm: string, geminiModel: string, captions: string, asrModel: string) => void
  onOpenLoop: () => void
  onOpenAnalytics: () => void
  onOpenQueue: () => void
  onOpenTranscribeQueue: () => void
  onOpenJob: (id: string) => void
  onResume: (id: string, llm?: string, geminiModel?: string, asrModel?: string) => void
  onDeleteJob: (id: string) => void
  onUpload: (file: File, llm: string, geminiModel: string, captions: string, asrModel: string) => void
}

export default function Studio({ jobs, running, stages, error, initialSource, onRun, onOpenLoop, onOpenAnalytics, onOpenQueue, onOpenTranscribeQueue, onOpenJob, onResume, onDeleteJob }: Props) {
  const [source, setSource] = useState(initialSource || '')
  const [llm, setLlm] = useState('ollama')
  const [geminiModel, setGeminiModel] = useState('gemini-3.7-flash')
  const [captions, setCaptions] = useState('beast')
  const [asrModel, setAsrModel] = useState('large-v3-turbo')
  const [showKey, setShowKey] = useState(false)
  const [showCaptionModal, setShowCaptionModal] = useState(false)

  const [phraseIdx, setPhraseIdx] = useState(0)
  const [wordIdx, setWordIdx] = useState(0)
  const [isPlayingPreview, setIsPlayingPreview] = useState(true)

  const GEMINI_MODELS = ['gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.1-pro', 'gemini-2.5-flash', 'gemini-2.5-pro']
  const ASR_MODELS = ['large-v3-turbo', 'large-v3', 'large-v2', 'medium.en', 'small.en', 'base.en', 'tiny.en']

  useEffect(() => {
    if (initialSource) {
      setSource(initialSource)
    }
  }, [initialSource])

  useEffect(() => {
    if (!isPlayingPreview) return
    const phrase = SAMPLE_PHRASES[phraseIdx]
    const timer = setInterval(() => {
      setWordIdx((prev) => (prev + 1 >= phrase.length ? 0 : prev + 1))
    }, 420)
    return () => clearInterval(timer)
  }, [isPlayingPreview, phraseIdx])

  const curStyle = CAPTION_PRESET_DEFS[captions] || CAPTION_PRESET_DEFS.beast

  const renderCaptionPreview = () => {
    const currentPhrase = SAMPLE_PHRASES[phraseIdx]

    if (!showCaptionModal) return null;

    return (
      <div className="modal-overlay" onClick={() => setShowCaptionModal(false)} style={{ zIndex: 1000, position: 'fixed', top: 0, left: 0, width: '100%', height: '100%', backgroundColor: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="caption-preview-container" onClick={e => e.stopPropagation()} style={{ maxWidth: '600px', width: '100%', background: 'var(--bg)', borderRadius: '12px', overflow: 'hidden', border: '1px solid var(--border)', boxShadow: '0 8px 32px rgba(0,0,0,0.5)' }}>
          <div className="caption-preview-header">
            <div className="caption-preview-title">
              <span style={{ color: curStyle.activeColor }}>●</span>
              <span>Live Subtitle Engine · {curStyle.label}</span>
              <span style={{ fontSize: '10px', color: 'var(--amber)', background: 'rgba(255, 178, 36, 0.1)', padding: '2px 6px', borderRadius: '4px' }}>
                {curStyle.badge}
              </span>
            </div>
            <div className="caption-preview-controls">
              <button
                className="opt"
                style={{ padding: '3px 8px', fontSize: '10px' }}
                onClick={() => setPhraseIdx((p) => (p + 1) % SAMPLE_PHRASES.length)}
                title="Cycle sample text"
              >
                ⟳ phrase
              </button>
              <button
                className="opt"
                style={{ padding: '3px 8px', fontSize: '10px' }}
                onClick={() => setIsPlayingPreview((p) => !p)}
                title={isPlayingPreview ? 'Pause preview' : 'Play preview'}
              >
                {isPlayingPreview ? '❚❚' : '▶'}
              </button>
              <button
                className="opt"
                style={{ padding: '3px 8px', fontSize: '10px', marginLeft: '8px' }}
                onClick={() => setShowCaptionModal(false)}
                title="Close preview"
              >
                ✕ Close
              </button>
            </div>
          </div>

        <div className="caption-stage-backdrop">
          <div className="caption-stage-scanlines" />
          <div
            className="caption-stage-target"
            style={{
              fontFamily: curStyle.fontFamily,
              fontSize: `${curStyle.fontSize}px`,
              textTransform: curStyle.uppercase ? 'uppercase' : 'none',
              letterSpacing: curStyle.uppercase ? '0.04em' : 'normal',
              fontWeight: 900,
              display: 'flex',
              flexWrap: 'wrap',
              justifyContent: 'center',
              alignItems: 'center',
              gap: '10px 12px'
            }}
          >
            {currentPhrase.map((item, idx) => {
              const isActive = idx === wordIdx
              const color = isActive
                ? curStyle.activeColor
                : item.emp
                ? curStyle.emphasisColor
                : curStyle.primaryColor

              return (
                <span
                  key={idx}
                  style={{
                    color,
                    WebkitTextStroke: curStyle.stroke,
                    textShadow: curStyle.shadow,
                    display: 'inline-block',
                    transform: isActive ? 'scale(1.14)' : 'scale(1)',
                    transition: 'transform 0.12s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.12s ease',
                    filter: isActive ? 'drop-shadow(0 0 8px currentColor)' : 'none'
                  }}
                >
                  {item.text}
                </span>
              )
            })}
          </div>
        </div>

        <div className="caption-badge-row">
          {CAPTION_PRESETS.map((key) => {
            const def = CAPTION_PRESET_DEFS[key]
            const isSelected = captions === key
            return (
              <button
                key={key}
                className={`caption-chip ${isSelected ? 'active' : ''}`}
                onClick={() => setCaptions(key)}
                disabled={running}
              >
                <span className="caption-chip-dot" style={{ background: def.dotColor }} />
                <span>{def.label}</span>
              </button>
            )
          })}
        </div>
        </div>
      </div>
    )
  }

  return (
    <div className="studio">
      <div className="grain" />
      {showKey && <KeyModal onClose={() => setShowKey(false)} />}
      <aside className="rail">
        <header className="rail-brand">
          <span className="rail-logo">publikclip</span>
          <span className="rail-sub">the clipper that shows its work</span>
        </header>
        <div className="rail-jobs">
          <p className="rail-label">SESSIONS</p>
          {jobs.length === 0 && <p className="rail-empty">nothing yet</p>}
          {jobs.map((job) => (
            <div key={job.id} style={{ display: 'flex', alignItems: 'center' }}>
              <button
                className={`rail-job ${job.rendered ? '' : 'partial'}`}
                style={{ flex: 1, minWidth: 0 }}
                onClick={() => (job.rendered ? onOpenJob(job.id) : onResume(job.id, llm, geminiModel, asrModel))}
                disabled={running}
                title={job.rendered ? 'open results' : 'resume from checkpoint'}
              >
                <span className={`led ${job.rendered ? 'led-on' : 'led-half'}`} />
                <span className="rail-job-title">{job.title ?? job.id}</span>
                <span className="rail-job-hint">{job.rendered ? 'open' : 'resume'}</span>
              </button>
              <button
                style={{ background: 'none', border: 'none', color: 'var(--dim)', cursor: 'pointer', padding: '10px 15px', fontSize: '18px', lineHeight: 1 }}
                onClick={() => onDeleteJob(job.id)}
                title="Delete session"
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <footer className="rail-foot">
          <button className="btn-ghost" onClick={() => setShowKey(true)}>
            ◈ gemini key
          </button>
          <button className="btn-ghost" onClick={onOpenLoop}>
            ⟳ instagram loop
          </button>
          <button className="btn-ghost" onClick={onOpenAnalytics}>
            📊 campaigns
          </button>
          <button className="btn-ghost" onClick={onOpenQueue}>
            📥 download queue
          </button>
          <button className="btn-ghost" onClick={onOpenTranscribeQueue}>
            🎙 transcribe queue
          </button>
        </footer>
      </aside>

      <main className="stage-area">
        <section className="input-block">
          <h1 className="input-heading">
            FEED IT<span className="amber"> AN HOUR.</span>
          </h1>
          <div className="input-row" style={{ display: 'none' }}>
            {/* The URL input is hidden. Studio is now launched from Analytics or Queue redirects */}
            <input
              value={source}
              onChange={(e) => setSource(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && source.trim() && !running && onRun(source.trim(), llm, geminiModel, captions, asrModel)}
              placeholder="YouTube URL or a path to a video file"
              disabled={running}
            />
          </div>
          {initialSource && (
            <div style={{ marginBottom: '24px', background: 'var(--panel)', padding: '16px 24px', borderRadius: '12px', border: '1px solid var(--primary)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <div style={{ fontSize: '13px', color: 'var(--dim)', marginBottom: '4px' }}>Ready to Process</div>
                <div style={{ fontWeight: 600, color: 'var(--fg)' }}>{initialSource}</div>
              </div>
              <button
                className="btn-primary"
                onClick={() => onRun(source.trim(), llm, geminiModel, captions, asrModel)}
                disabled={running}
              >
                {running ? 'WORKING' : 'CUT IT'}
              </button>
            </div>
          )}
          {!initialSource && (
            <div style={{ marginBottom: '24px', background: 'var(--panel)', padding: '24px', borderRadius: '12px', border: '1px dashed var(--border)', textAlign: 'center', color: 'var(--dim)' }}>
              Open a video from Campaigns or the Download Queue to begin processing.
            </div>
          )}
          <div className="run-options">
            <div className="opt-group">
              <span className="opt-label">brain</span>
              {['gemini', 'ollama', 'manual'].map((mode) => (
                <button
                  key={mode}
                  className={`opt ${llm === mode ? 'opt-on' : ''}`}
                  onClick={() => setLlm(mode)}
                  disabled={running}
                >
                  {mode}
                </button>
              ))}
              {llm === 'gemini' && (
                <select
                  className="opt opt-select"
                  value={geminiModel}
                  onChange={(e) => setGeminiModel(e.target.value)}
                  disabled={running}
                  style={{ marginLeft: '8px', background: 'transparent', color: '#fff', border: '1px solid #333', padding: '4px 8px', borderRadius: '4px' }}
                >
                  {GEMINI_MODELS.map(m => <option key={m} value={m} style={{ background: '#000' }}>{m}</option>)}
                </select>
              )}
            </div>
            <div className="opt-group">
              <span className="opt-label">asr model</span>
              {ASR_MODELS.map((preset) => (
                <button
                  key={preset}
                  className={`opt ${asrModel === preset ? 'opt-on' : ''}`}
                  onClick={() => setAsrModel(preset)}
                  disabled={running}
                >
                  {preset}
                </button>
              ))}
            </div>
            <div className="opt-group">
              <span className="opt-label">captions</span>
              {CAPTION_PRESETS.map((preset) => (
                <button
                  key={preset}
                  className={`opt ${captions === preset ? 'opt-on' : ''}`}
                  onClick={() => setCaptions(preset)}
                  disabled={running}
                >
                  {preset}
                </button>
              ))}
              <button 
                className="opt" 
                style={{ marginLeft: '12px', border: '1px solid var(--amber)', color: 'var(--amber)' }}
                onClick={() => setShowCaptionModal(true)}
              >
                👁 Preview Styles
              </button>
            </div>
          </div>
        </section>
        
        {renderCaptionPreview()}

        {(running || Object.keys(stages).length > 0) && (
          <section className="deck">
            {STAGE_ORDER.filter((s) => stages[s] || running).map((name, i) => {
              const st = stages[name]
              const state = !st ? 'idle' : st.fraction >= 1 ? 'done' : 'live'
              return (
                <div className={`deck-row ${state}`} key={name} style={{ animationDelay: `${i * 40}ms` }}>
                  <span className="deck-name mono">{STAGE_LABELS[name] ?? name.toUpperCase()}</span>
                  <div className="deck-bar">
                    <div
                      className={`deck-fill ${st && st.fraction < 0 ? 'indeterminate' : ''}`}
                      style={st && st.fraction >= 0 ? { width: `${Math.min(100, st.fraction * 100)}%` } : undefined}
                    />
                  </div>
                  <span className="deck-msg">
                    {st?.message ?? ''}
                    {st && st.fraction >= 0 && st.fraction < 1 && (
                      <span className="mono" style={{ color: 'var(--amber)', marginLeft: '8px' }}>
                        {Math.floor(st.fraction * 100)}%
                      </span>
                    )}
                  </span>
                </div>
              )
            })}
          </section>
        )}

        {error && (
          <section className="error-block">
            <span className="led led-err" />
            {error}
          </section>
        )}
      </main>
    </div>
  )
}
