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
  hormozi: {
    id: 'hormozi',
    label: 'Montserrat Black Italic',
    subtitle: 'Black stroke, white / yellow / cyan fills only',
    fontFamily: "'Montserrat', 'Arial Black', 'Archivo Black', sans-serif",
    fontSize: 32,
    primaryColor: '#FFFFFF',
    activeColor: '#FFE500',
    emphasisColor: '#00E5FF',
    stroke: '8px #000',
    shadow: 'none',
    uppercase: true,
    dotColor: '#FFE500',
    badge: 'BLACK OUTLINE'
  }
}

const CAPTION_PRESETS = ['hormozi']

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
  const [captions, setCaptions] = useState('hormozi')
  const [asrModel, setAsrModel] = useState('large-v3-turbo')
  const [showKey, setShowKey] = useState(false)
  const [showCaptionModal, setShowCaptionModal] = useState(false)

  const [phraseIdx, setPhraseIdx] = useState(0)
  const [wordIdx, setWordIdx] = useState(0)
  const [isPlayingPreview, setIsPlayingPreview] = useState(true)
  const [wordColor, setWordColor] = useState<'white' | 'yellow' | 'cyan'>('white')

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

  const curStyle = CAPTION_PRESET_DEFS[captions] || CAPTION_PRESET_DEFS.hormozi
  const wordColorMap = {
    white: '#FFFFFF',
    yellow: '#FFE500',
    cyan: '#00E5FF',
  } as const

  const renderCaptionPreview = () => {
    const currentPhrase = SAMPLE_PHRASES[phraseIdx]
    const visibleWords = currentPhrase.slice(wordIdx, wordIdx + 1)
    const lineColor = wordColorMap[wordColor]

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
              <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginRight: '8px' }}>
                {(['white', 'yellow', 'cyan'] as const).map((colorKey) => (
                  <button
                    key={colorKey}
                    className="opt"
                    style={{
                      padding: '3px 8px',
                      fontSize: '10px',
                      borderColor: wordColor === colorKey ? 'var(--amber)' : undefined,
                      color: wordColor === colorKey ? 'var(--amber)' : undefined
                    }}
                    onClick={() => setWordColor(colorKey)}
                    title={`Use ${colorKey} fill`}
                  >
                    {colorKey}
                  </button>
                ))}
              </div>
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
              justifyContent: 'center',
              alignItems: 'center',
              minHeight: '80px',
              lineHeight: 0.9,
              transform: 'skewX(-8deg)'
            }}
          >
            {visibleWords.map((item, idx) => {
              const isActive = idx === 0
              return (
                <span
                  key={`${item.text}-${idx}`}
                  style={{
                    color: lineColor,
                    WebkitTextFillColor: lineColor,
                    fontStyle: 'normal',
                    fontWeight: 900,
                    letterSpacing: '0.04em',
                    WebkitTextStroke: curStyle.stroke,
                    textShadow: 'none',
                    display: 'inline-block',
                    transform: isActive ? 'scale(1.12) skewX(-10deg)' : 'skewX(-10deg)',
                    transition: 'transform 0.12s cubic-bezier(0.34, 1.56, 0.64, 1), color 0.12s ease',
                    filter: 'none',
                    paintOrder: 'stroke fill',
                    whiteSpace: 'nowrap'
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
                <span className="rail-job-title">{
                  (() => {
                    const rawTitle = job.title?.trim();
                    const generic = ['media', 'video', 'clip'];
                    const isUrl = !!rawTitle && (/^https?:\/\//i.test(rawTitle) || /(?:youtu\.be|youtube\.com|youtube-nocookie\.com)/i.test(rawTitle));
                    if (rawTitle && !generic.includes(rawTitle.toLowerCase()) && !isUrl) return rawTitle;
                    const fallback = job.id;
                    try {
                      if (typeof (job as any).source === 'string' && /^https?:\/\//i.test((job as any).source)) {
                        const url = new URL((job as any).source)
                        const v = url.searchParams.get('v')
                        if (v) return `YouTube video ${v.slice(0, 8)}`
                        const name = decodeURIComponent(url.pathname).split('/').filter(Boolean).pop()?.replace(/\.[a-z0-9]+$/i, '')
                        if (name && !['watch', 'playlist'].includes(name.toLowerCase())) return name.replace(/[-_]+/g, ' ')
                      }
                    } catch {}
                    return fallback;
                  })()
                }</span>
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
              onKeyDown={(e) => e.key === 'Enter' && (source || initialSource || '').trim() && !running && onRun((source || initialSource || '').trim(), llm, geminiModel, captions, asrModel)}
              placeholder="YouTube URL or a path to a video file"
              disabled={running}
            />
          </div>
          {(initialSource || source) && (
            <div style={{ marginBottom: '24px', background: 'var(--panel)', padding: '16px 24px', borderRadius: '12px', border: '1px solid var(--primary)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <div style={{ fontSize: '13px', color: 'var(--dim)', marginBottom: '4px' }}>Ready to Process</div>
                <div style={{ fontWeight: 600, color: 'var(--fg)' }}>{source || initialSource}</div>
              </div>
              <button
                className="btn-primary"
                onClick={() => onRun((source || initialSource || '').trim(), llm, geminiModel, captions, asrModel)}
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
