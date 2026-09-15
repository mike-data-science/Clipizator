import { useState } from 'react'
import type { JobResults } from '../types'
import { api } from '../api'

function fmt(t: number) { const m = Math.floor(t / 60); return `${m}:${String(Math.floor(t % 60)).padStart(2, '0')}` }

interface Props { results: JobResults; onBack: () => void; onOpenClipDetails: (index: number) => void; onEditClip: (index: number) => void; onOpenAnalytics: () => void; onOpenCampaigns: () => void; onOpenLoop: () => void; onOpenQueue: () => void; onOpenTranscribeQueue: () => void }

/* ── tiny icon button ── */
function ActionBtn({ title, color, onClick, children }: { title: string; color?: string; onClick: (e: React.MouseEvent) => void; children: React.ReactNode }) {
  const [hov, setHov] = useState(false)
  return (
    <button
      title={title}
      onClick={onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        width: '32px', height: '32px', border: 'none', borderRadius: '8px', cursor: 'pointer',
        background: hov ? (color || 'rgba(255,255,255,0.25)') : 'rgba(255,255,255,0.12)',
        color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
        backdropFilter: 'blur(6px)', transition: 'background 0.15s, transform 0.1s',
        transform: hov ? 'scale(1.12)' : 'scale(1)', flexShrink: 0,
      }}
    >
      {children}
    </button>
  )
}

/* ── single clip card ── */
function ClipCard({ out, i, clip, jobId, onOpenDetails, onEdit, approved, rejected, onApprove, onReject }: {
  out: { clip: number; duration: number; score: number; path: string };
  i: number;
  clip: { score?: number; headline?: string; summary?: string; start: number; end: number } | undefined;
  jobId: string;
  onOpenDetails: () => void;
  onEdit: () => void;
  approved: boolean;
  rejected: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const [hovered, setHovered] = useState(false)
  const score = Math.round(clip?.score ?? out.score)
  const scoreColor = score >= 80 ? '#10b981' : score >= 60 ? '#f59e0b' : '#ef4444'

  return (
    <div
      className="project-clip-card"
      style={{ position: 'relative', outline: approved ? '2px solid #10b981' : rejected ? '2px solid #ef4444' : 'none' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Media */}
      <div className="project-clip-media" style={{ position: 'relative', cursor: 'pointer' }} onClick={onOpenDetails}>
        <video src={api.previewUrl(jobId, out.clip)} muted preload="metadata" />
        <span className="project-clip-play">▶</span>
        <label>{fmt(out.duration)}</label>

        {/* Hover action bar */}
        <div style={{
          position: 'absolute', bottom: '8px', left: '50%', transform: `translateX(-50%) translateY(${hovered ? '0' : '10px'})`,
          opacity: hovered ? 1 : 0, pointerEvents: hovered ? 'auto' : 'none',
          transition: 'opacity 0.18s ease, transform 0.18s ease',
          display: 'flex', gap: '6px', alignItems: 'center',
          background: 'rgba(18,18,28,0.72)', borderRadius: '12px', padding: '5px 7px',
          backdropFilter: 'blur(8px)', boxShadow: '0 4px 16px rgba(0,0,0,0.35)',
          whiteSpace: 'nowrap',
        }}>
          {/* Edit */}
          <ActionBtn title="Edit in Studio" onClick={e => { e.stopPropagation(); onEdit() }}>
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2.2" fill="none"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
          </ActionBtn>
          {/* Publish */}
          <ActionBtn title="Publish" onClick={e => { e.stopPropagation(); alert('Publish coming soon') }}>
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2.2" fill="none"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M12 8v8m-4-4h8"/></svg>
          </ActionBtn>
          {/* Export */}
          <ActionBtn title="Export / Download" onClick={e => { e.stopPropagation(); window.open(api.previewUrl(jobId, out.clip), '_blank') }}>
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2.2" fill="none"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          </ActionBtn>
          {/* Divider */}
          <div style={{ width: '1px', height: '18px', background: 'rgba(255,255,255,0.2)', margin: '0 1px' }} />
          {/* Approve */}
          <ActionBtn title="Approve" color="rgba(16,185,129,0.7)" onClick={e => { e.stopPropagation(); onApprove() }}>
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2.5" fill="none"><polyline points="20 6 9 17 4 12"/></svg>
          </ActionBtn>
          {/* Reject */}
          <ActionBtn title="Reject" color="rgba(239,68,68,0.7)" onClick={e => { e.stopPropagation(); onReject() }}>
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2.5" fill="none"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </ActionBtn>
        </div>

        {/* Approved / Rejected overlay badge */}
        {(approved || rejected) && (
          <div style={{
            position: 'absolute', top: '7px', left: '7px',
            padding: '3px 8px', borderRadius: '5px', fontSize: '10px', fontWeight: 700,
            background: approved ? 'rgba(16,185,129,0.9)' : 'rgba(239,68,68,0.9)', color: '#fff',
          }}>
            {approved ? '✓ Approved' : '✕ Rejected'}
          </div>
        )}
      </div>

      {/* Info */}
      <div className="project-clip-info" onClick={onOpenDetails} style={{ cursor: 'pointer' }}>
        <div>
          <b>Clip {String(i + 1).padStart(2, '0')}</b>
          <span className="clip-score" style={{ color: scoreColor }}>{score} score</span>
        </div>
        <p>{clip?.headline || clip?.summary || 'Generated highlight from your video'}</p>
        <small>{clip ? `${fmt(clip.start)} – ${fmt(clip.end)} in source` : 'Ready to edit'}</small>
      </div>
    </div>
  )
}

export default function ProjectClips({ results, onBack, onOpenClipDetails, onEditClip, onOpenAnalytics, onOpenCampaigns, onOpenLoop, onOpenQueue, onOpenTranscribeQueue }: Props) {
  const outputs = results.render?.outputs ?? []
  const clips = results.score?.clips ?? []
  const title = results.ingest?.title || 'Untitled project'
  const [approved, setApproved] = useState<Set<number>>(new Set())
  const [rejected, setRejected] = useState<Set<number>>(new Set())

  function toggleApprove(i: number) {
    setApproved(prev => { const s = new Set(prev); s.has(i) ? s.delete(i) : s.add(i); return s })
    setRejected(prev => { const s = new Set(prev); s.delete(i); return s })
  }
  function toggleReject(i: number) {
    setRejected(prev => { const s = new Set(prev); s.has(i) ? s.delete(i) : s.add(i); return s })
    setApproved(prev => { const s = new Set(prev); s.delete(i); return s })
  }

  return (
    <div className="project-view">
      <aside className="project-view-side">
        <button className="project-back" onClick={onBack}>Back to workspace</button>
        <div className="project-view-brand">✦ clipizator</div>
        <div className="project-view-nav">
          <button onClick={onOpenAnalytics}>◔ Analytics</button>
          <button className="selected">▶ Clips</button>
          <button onClick={onOpenCampaigns}>▤ Campaigns</button>
        </div>
        <div className="project-side-bottom">
          <button onClick={onOpenLoop}>◌ Instagram loop</button>
          <button onClick={onOpenQueue}>↓ Download queue</button>
          <button onClick={onOpenTranscribeQueue}>◉ Transcribe queue</button>
        </div>
      </aside>
      <main className="project-view-main">
        <header className="project-view-head">
          <div>
            <p className="new-eyebrow">PROJECT / GENERATED CLIPS</p>
            <h1>{title}</h1>
            <p>{outputs.length} clips · {results.ingest?.probe ? fmt(results.ingest.probe.duration_sec) : '—'} source video</p>
          </div>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            {approved.size > 0 && <span style={{ fontSize: '12px', color: '#10b981', fontWeight: 600 }}>{approved.size} approved</span>}
            {rejected.size > 0 && <span style={{ fontSize: '12px', color: '#ef4444', fontWeight: 600 }}>{rejected.size} rejected</span>}
            <button className="new-primary">＋ Add to campaign</button>
          </div>
        </header>
        <div className="project-clip-toolbar">
          <b>All clips</b>
          <span>{outputs.length} generated from this video</span>
          <button>Sort by score ↓</button>
        </div>
        <div className="project-clips-grid">
          {outputs.map((out, i) => {
            const clip = clips[out.clip]
            return (
              <ClipCard
                key={out.clip}
                out={out}
                i={i}
                clip={clip}
                jobId={results.job_id}
                onOpenDetails={() => onOpenClipDetails(out.clip)}
                onEdit={() => onEditClip(out.clip)}
                approved={approved.has(i)}
                rejected={rejected.has(i)}
                onApprove={() => toggleApprove(i)}
                onReject={() => toggleReject(i)}
              />
            )
          })}
        </div>
      </main>
    </div>
  )
}
