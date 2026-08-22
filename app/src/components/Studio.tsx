import { useState, useEffect } from 'react'
import type { JobSummary } from '../types'
import KeyModal from './KeyModal'

const STAGE_ORDER = [
  'ingest', 'asr', 'diarize', 'events', 'candidates', 'score', 'camera', 'render'
]

const STAGE_LABELS: Record<string, string> = {
  ingest: 'INGEST',
  asr: 'TRANSCRIBE',
  diarize: 'SPEAKERS',
  events: 'LISTEN',
  candidates: 'SCAN',
  score: 'JUDGE',
  camera: 'DIRECT',
  render: 'RENDER'
}

const CAPTION_PRESETS = ['classic', 'beast', 'hormozi', 'minimal', 'karaoke-pop']

interface Props {
  jobs: JobSummary[]
  running: boolean
  stages: Record<string, { fraction: number; message: string }>
  error: string | null
  initialSource?: string
  onRun: (source: string, llm: string, geminiModel: string, captions: string, asrModel: string) => void
  onOpenLoop: () => void
  onOpenAnalytics: () => void
  onOpenJob: (id: string) => void
  onResume: (id: string, llm?: string, geminiModel?: string, asrModel?: string) => void
  onDeleteJob: (id: string) => void
}

export default function Studio({ jobs, running, stages, error, initialSource, onRun, onOpenLoop, onOpenAnalytics, onOpenJob, onResume, onDeleteJob }: Props) {
  const [source, setSource] = useState(initialSource || '')
  const [llm, setLlm] = useState('gemini')
  const [geminiModel, setGeminiModel] = useState('gemini-3.7-flash')
  const [captions, setCaptions] = useState('classic')
  const [asrModel, setAsrModel] = useState('large-v3-turbo')
  const [showKey, setShowKey] = useState(false)

  const GEMINI_MODELS = ['gemini-3.7-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.1-pro', 'gemini-2.5-flash', 'gemini-2.5-pro']
  const ASR_MODELS = ['large-v3-turbo', 'large-v3', 'large-v2', 'medium.en', 'small.en', 'base.en', 'tiny.en']

  useEffect(() => {
    if (initialSource) {
      setSource(initialSource)
    }
  }, [initialSource])

  const renderCaptionPreview = () => {
    const getStyle = () => {
      switch (captions) {
        case 'classic':
          return {
            fontFamily: 'Arial, sans-serif',
            color: 'white',
            textShadow: '-2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000, 2px 2px 0 #000',
            fontSize: '18px',
            fontWeight: 'normal',
            textTransform: 'none' as const
          }
        case 'beast':
          return {
            fontFamily: '"Arial Black", Impact, sans-serif',
            color: '#ffd700',
            textShadow: '2px 2px 0 #000, -2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000',
            fontSize: '24px',
            fontWeight: '900',
            textTransform: 'uppercase' as const,
            transform: 'rotate(-2deg)'
          }
        case 'hormozi':
          return {
            fontFamily: 'system-ui, sans-serif',
            color: '#fff',
            textShadow: '0 4px 8px rgba(0,0,0,0.8)',
            fontSize: '22px',
            fontWeight: 900,
            textTransform: 'uppercase' as const,
          }
        case 'minimal':
          return {
            fontFamily: 'system-ui, sans-serif',
            color: 'rgba(255,255,255,0.9)',
            fontSize: '16px',
            fontWeight: 300,
            letterSpacing: '1px'
          }
        case 'karaoke-pop':
          return {
            fontFamily: 'system-ui, cursive, sans-serif',
            color: '#00ffff',
            textShadow: '0 0 10px #00ffff, 0 0 20px #00ffff',
            fontSize: '22px',
            fontWeight: 'bold',
          }
        default:
          return { color: 'white' }
      }
    }

    return (
      <div style={{ marginTop: '16px', padding: '24px 16px', background: 'var(--panel)', borderRadius: '8px', border: '1px solid var(--border)', textAlign: 'center' }}>
        <div style={{ ...getStyle(), display: 'inline-block' }}>
          {captions === 'hormozi' ? (
            <>MAKE IT <span style={{ color: '#00ff00' }}>POP</span></>
          ) : captions === 'karaoke-pop' ? (
            <>SING <span style={{ color: '#fff', textShadow: 'none' }}>ALONG</span></>
          ) : captions === 'beast' ? (
            <>GO HARD</>
          ) : captions === 'classic' ? (
            <>Standard Subtitles</>
          ) : (
            <>Clean & Simple</>
          )}
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
        </footer>
      </aside>

      <main className="stage-area">
        <section className="input-block">
          <h1 className="input-heading">
            FEED IT<span className="amber"> AN HOUR.</span>
          </h1>
          <div className="input-row">
            <input
              value={source}
              onChange={(e) => setSource(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && source.trim() && !running && onRun(source.trim(), llm, geminiModel, captions, asrModel)}
              placeholder="YouTube URL or a path to a video file"
              disabled={running}
            />
            <button
              className="btn-primary"
              onClick={() => onRun(source.trim(), llm, geminiModel, captions, asrModel)}
              disabled={running || !source.trim()}
            >
              {running ? 'WORKING' : 'CUT IT'}
            </button>
          </div>
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
            </div>
            {renderCaptionPreview()}
          </div>
        </section>

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
