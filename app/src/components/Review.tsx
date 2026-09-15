import { useMemo, useState } from 'react'
import { api } from '../api'
import type { Clip, JobResults, RenderOutput } from '../types'
import ClipEditor from './ClipEditor'

/**
 * The review bay: filmstrip of rendered clips, a 9:16 monitor, and THE
 * AUDIT — the score's full provenance. This panel is the product thesis:
 * never a bare number.
 */

const RESTYLE_PRESETS = ['hormozi']
const CAMERA_MODES: [string, string][] = [
  ['cut', 'hard cut on speaker change'],
  ['pan', 'eased pan between speakers'],
  ['locked', 'static crop, no switching']
]

interface Props {
  results: JobResults
  onBack: () => void
  onRestyle: (captions: string, camera: string) => void
  initialClip?: number
  initialEditClip?: number | null
}

const RULE_LABELS: Record<string, string> = {
  funny_no_laugh: 'FUNNY, NO LAUGHTER',
  funny_corroborated: 'LAUGHTER CONFIRMED ×2',
  shock_no_arousal: 'SHOCK, FLAT DELIVERY',
  bait_penalty: 'ENGAGEMENT BAIT',
  heatmap_boost: 'HUMANS REPLAYED THIS'
}

const SIGNAL_LABELS: Record<string, string> = {
  laughter: 'laughter',
  audio_events: 'audio events',
  arousal: 'vocal arousal',
  replay_heatmap: 'replay heatmap',
  visual: 'visual pass'
}

function fmtTime(t: number): string {
  const m = Math.floor(t / 60)
  const s = Math.floor(t % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function Review({ results, onBack, onRestyle, initialClip = 0, initialEditClip = null }: Props) {
  const outputs = results.render?.outputs ?? []
  const clips = results.score?.clips ?? []
  const [selected, setSelected] = useState(initialClip)
  const [exported, setExported] = useState<Record<number, string>>({})
  const [feedbackStatus, setFeedbackStatus] = useState<Record<number, 'approved' | 'rejected' | 'neutral'>>({})
  const currentPreset = results.render?.caption_preset ?? 'hormozi'
  const [restylePreset, setRestylePreset] = useState(currentPreset)
  const [restyleCamera, setRestyleCamera] = useState('cut')
  const editOnly = initialEditClip !== null
  const [editing, setEditing] = useState<number | null>(initialEditClip)
  const [reloadKey, setReloadKey] = useState(0)
  const [originalQuality, setOriginalQuality] = useState(false)
  const [previewFailed, setPreviewFailed] = useState<string | null>(null)
  const styleChanged = restylePreset !== currentPreset || restyleCamera !== 'cut'

  const pair = useMemo(() => {
    const out = outputs[selected]
    const clip = out ? clips[out.clip] : undefined
    return { out, clip }
  }, [outputs, clips, selected])
  const previewKey = `${results.job_id}:${pair.out?.clip}:${reloadKey}`
  const useOriginal = originalQuality || previewFailed === previewKey

  async function doExport(out: RenderOutput, clip: Clip) {
    const title = `${results.ingest?.title ?? 'clip'} ${fmtTime(clip.start)}`
    const dest = await api.exportClip(results.job_id, out.clip, title)
    setExported((prev) => ({ ...prev, [out.clip]: dest }))
  }

  async function submitDecision(label: 'approved' | 'rejected' | 'neutral', reason?: string) {
    if (!pair.out) return
    try {
      await api.submitClipFeedback(results.job_id, pair.out.clip, label, reason)
      setFeedbackStatus((prev) => ({ ...prev, [pair.out!.clip]: label }))
    } catch (err) {
      console.error('clip feedback failed', err)
      alert(err instanceof Error ? err.message : 'Could not save the clip decision.')
    }
  }

  if (editing !== null) {
    return (
      <div className="clip-editor-page">
        <ClipEditor
          key={`${editing}-${reloadKey}`}
          jobId={results.job_id}
          clipIndex={editing}
          onClose={() => editOnly ? onBack() : setEditing(null)}
          onRendered={() => setReloadKey((k) => k + 1)}
        />
      </div>
    )
  }

  return (
    <div className="review">
      <div className="grain" />
      <header className="review-head">
        <button className="btn-ghost" onClick={onBack}>
          ← studio
        </button>
        <div className="review-title-block">
          <h1 className="review-title">{results.ingest?.title ?? results.job_id}</h1>
          <p className="review-sub mono">
            {outputs.length} clips · scored by {results.score?.model ?? '—'} ·{' '}
            {results.score?.llm_mode === 'ollama' ? 'LOCAL ESTIMATE' : 'standard confidence'} ·{' '}
            {results.candidates?.heatmap_present ? 'replay heatmap in play' : 'no public heatmap'}
          </p>
        </div>
      </header>

      <div className="restyle-bar">
        <span className="opt-label">captions</span>
        {RESTYLE_PRESETS.map((preset) => (
          <button
            key={preset}
            className={`opt ${restylePreset === preset ? 'opt-on' : ''}`}
            onClick={() => setRestylePreset(preset)}
          >
            {preset}
          </button>
        ))}
        <span className="opt-label" style={{ marginLeft: 18 }}>
          camera
        </span>
        {CAMERA_MODES.map(([mode, hint]) => (
          <button
            key={mode}
            className={`opt ${restyleCamera === mode ? 'opt-on' : ''}`}
            onClick={() => setRestyleCamera(mode)}
            title={hint}
          >
            {mode}
          </button>
        ))}
        <button
          className="btn-primary restyle-go"
          disabled={!styleChanged}
          onClick={() => onRestyle(restylePreset, restyleCamera)}
          title="re-renders only the changed stages — scores and cuts stay"
        >
          RESTYLE + RE-RENDER
        </button>
      </div>

      <div className="filmstrip">
        {outputs.map((out, i) => {
          const clip = clips[out.clip]
          return (
            <button
              key={out.clip}
              className={`film-card ${i === selected ? 'film-on' : ''}`}
              onClick={() => setSelected(i)}
              style={{ animationDelay: `${i * 50}ms` }}
            >
              <span className="film-score mono">{Math.round(clip?.score ?? out.score)}</span>
              <span className="film-time mono">{clip ? fmtTime(clip.start) : ''}</span>
              <span className="film-platform">{out.best_platform}</span>
            </button>
          )
        })}
      </div>

      {pair.clip && results.ingest?.probe && (
        <div className="source-timeline-panel">
          <div className="source-timeline-head"><span>SOURCE VIDEO</span><b>{fmtTime(results.ingest.probe.duration_sec)} total</b><span className="source-timeline-cut">Clip {selected + 1}: {fmtTime(pair.clip.start)} – {fmtTime(pair.clip.end)}</span></div>
          <div className="source-timeline"><div className="source-timeline-progress" style={{ left: `${Math.max(0, Math.min(100, pair.clip.start / results.ingest.probe.duration_sec * 100))}%`, width: `${Math.max(1, Math.min(100, (pair.clip.end - pair.clip.start) / results.ingest.probe.duration_sec * 100))}%` }} /><span className="source-timeline-marker" style={{ left: `${Math.max(0, Math.min(100, pair.clip.start / results.ingest.probe.duration_sec * 100))}%` }} /><span className="source-timeline-marker end" style={{ left: `${Math.max(0, Math.min(100, pair.clip.end / results.ingest.probe.duration_sec * 100))}%` }} /></div>
          <div className="source-timeline-labels"><span>0:00</span><span>{fmtTime(results.ingest.probe.duration_sec / 2)}</span><span>{fmtTime(results.ingest.probe.duration_sec)}</span></div>
        </div>
      )}

      {pair.out && pair.clip && (
        <div className="bay">
          <div className="monitor-wrap">
            <video
              key={`${previewKey}:${useOriginal}`}
              className="monitor"
              src={useOriginal ? `${api.fileUrl(pair.out.path)}?v=${reloadKey}` : api.previewUrl(results.job_id, pair.out.clip, reloadKey)}
              preload="auto"
              onError={() => { if (!useOriginal) setPreviewFailed(previewKey) }}
              controls
              playsInline
            />
            <div className="monitor-actions">
              <label style={{ display: 'block', color: 'var(--dim)', marginBottom: 8 }}>
                Playback:{' '}
                <select value={originalQuality ? 'original' : 'preview'} onChange={e => setOriginalQuality(e.target.value === 'original')}>
                  <option value="preview">Fast preview · 720p</option>
                  <option value="original">Original · full quality</option>
                </select>
              </label>
              <p className="mono" style={{ color: 'var(--dim)', fontSize: 11 }}>
                {previewFailed === previewKey && !originalQuality ? 'Preview unavailable — playing the original. ' : ''}
                Downloads always use full quality.
              </p>
              <button className="btn-secondary" onClick={() => setEditing(pair.out!.clip)}>
                ✎ EDIT CLIP (bounds · cuts · visuals)
              </button>
              <div className="feedback-group" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
                <button
                  className="btn-secondary"
                  style={{
                    borderColor: feedbackStatus[pair.out.clip] === 'approved' ? '#5ee7a5' : undefined,
                    background: feedbackStatus[pair.out.clip] === 'approved' ? 'rgba(94, 231, 165, 0.12)' : undefined,
                  }}
                  onClick={() => submitDecision('approved', 'Strong clip candidate')}
                >
                  ✓ APPROVE
                </button>
                <button
                  className="btn-secondary"
                  style={{
                    borderColor: feedbackStatus[pair.out.clip] === 'rejected' ? '#ff8a8a' : undefined,
                    background: feedbackStatus[pair.out.clip] === 'rejected' ? 'rgba(255, 138, 138, 0.12)' : undefined,
                  }}
                  onClick={() => submitDecision('rejected', 'Weak clip candidate')}
                >
                  ✕ REJECT
                </button>
                <button
                  className="btn-secondary"
                  style={{
                    borderColor: feedbackStatus[pair.out.clip] === 'neutral' ? '#f8d66d' : undefined,
                    background: feedbackStatus[pair.out.clip] === 'neutral' ? 'rgba(248, 214, 109, 0.12)' : undefined,
                  }}
                  onClick={() => submitDecision('neutral', 'Keep for later review')}
                >
                  ○ HOLD
                </button>
              </div>
              <button className="btn-primary" onClick={() => doExport(pair.out!, pair.clip!)}>
                {exported[pair.out.clip] ? 'EXPORTED ✓' : 'EXPORT MP4'}
              </button>
              {exported[pair.out.clip] && (
                <span className="mono export-path">{exported[pair.out.clip]}</span>
              )}
            </div>
          </div>

          <aside className="audit">
            <p className="audit-kicker">THE AUDIT</p>
            <div className="audit-score-row">
              <span className="audit-big mono">{Math.round(pair.clip.score)}</span>
              <div className="audit-platforms">
                {Object.entries(pair.clip.platform_scores).map(([platform, value]) => (
                  <div className="platform-row" key={platform}>
                    <span className="platform-name">{platform}</span>
                    <div className="platform-bar">
                      <div className="platform-fill" style={{ width: `${value}%` }} />
                    </div>
                    <span className="mono platform-val">{Math.round(value)}</span>
                  </div>
                ))}
              </div>
            </div>
            <p className="audit-summary">{pair.clip.summary}</p>

            {(pair.clip.headline || pair.clip.hook_line || pair.clip.story_angle || pair.clip.why_it_hits?.length || pair.clip.risk_flags?.length) && (
              <div style={{ marginTop: 18, paddingTop: 14, borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                <p className="audit-label">CLIP INTELLIGENCE</p>
                {pair.clip.headline && (
                  <div style={{ marginBottom: 10 }}>
                    <div className="mono" style={{ fontSize: 10, color: 'var(--faint)', marginBottom: 4 }}>HEADLINE</div>
                    <div>{pair.clip.headline}</div>
                  </div>
                )}
                {pair.clip.hook_line && (
                  <div style={{ marginBottom: 10 }}>
                    <div className="mono" style={{ fontSize: 10, color: 'var(--faint)', marginBottom: 4 }}>HOOK</div>
                    <div>{pair.clip.hook_line}</div>
                  </div>
                )}
                {pair.clip.story_angle && (
                  <div style={{ marginBottom: 10 }}>
                    <div className="mono" style={{ fontSize: 10, color: 'var(--faint)', marginBottom: 4 }}>STORY ANGLE</div>
                    <div>{pair.clip.story_angle}</div>
                  </div>
                )}
                {pair.clip.why_it_hits && pair.clip.why_it_hits.length > 0 && (
                  <div style={{ marginBottom: 10 }}>
                    <div className="mono" style={{ fontSize: 10, color: 'var(--faint)', marginBottom: 4 }}>WHY IT HITS</div>
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {pair.clip.why_it_hits.map((reason, i) => <li key={i}>{reason}</li>)}
                    </ul>
                  </div>
                )}
                {pair.clip.risk_flags && pair.clip.risk_flags.length > 0 && (
                  <div>
                    <div className="mono" style={{ fontSize: 10, color: 'var(--faint)', marginBottom: 4 }}>RISK FLAGS</div>
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {pair.clip.risk_flags.map((risk, i) => <li key={i}>{risk}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            )}

            <p className="audit-label">SUBSCORES</p>
            <div className="subs">
              {Object.entries(pair.clip.subscores).map(([name, value]) => (
                <div className="sub-row" key={name}>
                  <span className="sub-name">{name.replace('_', ' ')}</span>
                  <div className="sub-bar">
                    <div className="sub-fill" style={{ width: `${value * 10}%` }} />
                  </div>
                  <span className="mono sub-val">{value.toFixed(1)}</span>
                </div>
              ))}
            </div>

            {pair.clip.adjustments.length > 0 && (
              <>
                <p className="audit-label">ADJUSTMENTS</p>
                <div className="ledger">
                  {pair.clip.adjustments.map((adj, i) => (
                    <div className="ledger-row" key={i}>
                      <span className={`ledger-factor mono ${adj.factor >= 1 ? 'up' : 'down'}`}>
                        ×{adj.factor}
                      </span>
                      <div>
                        <span className="ledger-rule">{RULE_LABELS[adj.rule] ?? adj.rule}</span>
                        <span className="ledger-reason">{adj.reason}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}

            <p className="audit-label">SIGNALS</p>
            <div className="signals">
              {pair.clip.signals_fired.map((signal) => (
                <span className="sig sig-on" key={signal}>
                  <span className="led led-on" />
                  {SIGNAL_LABELS[signal] ?? signal}
                </span>
              ))}
              {pair.clip.signals_missing.map((signal) => (
                <span className="sig sig-off" key={signal}>
                  <span className="led led-off" />
                  {SIGNAL_LABELS[signal] ?? signal}
                </span>
              ))}
            </div>

            {pair.clip.music && (
              <>
                <p className="audit-label">MUSIC BRIEF</p>
                <div className="music-card">
                  <p className="music-main">
                    <span className="amber">{pair.clip.music.genre}</span> ·{' '}
                    {pair.clip.music.mood} · <span className="mono">{pair.clip.music.bpm_range} bpm</span>
                  </p>
                  <p className="music-theme">{pair.clip.music.theme}</p>
                  <p className="music-alt">
                    also try:{' '}
                    {pair.clip.music.alternatives
                      .map((alt) => `${alt.genre} (${alt.bpm_range})`)
                      .join(' / ')}
                  </p>
                </div>
              </>
            )}

            <p className="audit-fine mono">
              confidence: {pair.clip.confidence} · captions: {results.render?.caption_preset} ·{' '}
              {pair.out.words} words · {pair.out.event_tags} event tags
            </p>
          </aside>
        </div>
      )}
    </div>
  )
}
