import type { JobResults, ProjectLifecycle } from '../types'

interface Props {
  lifecycle: ProjectLifecycle
  results: JobResults | null
  activeJobId: string | null
  activeStage: string | null
  liveStages: Record<string, { fraction: number; message: string }>
  onBack: () => void
  onViewClips: () => void
  onDelete: () => Promise<void>
}

function statusLabel(status: string) {
  if (status === 'done') return 'Completed'
  if (status === 'failed') return 'Failed'
  if (status === 'waiting_for_worker') return 'Waiting'
  if (status === 'downloading') return 'Downloading'
  if (status === 'uploading') return 'Uploading'
  return 'Processing'
}

function formatRuntime(seconds?: number | null) {
  if (seconds == null) return ''
  return seconds < 60 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds / 60)}m`
}

export default function ProjectLifecycleDetail({ lifecycle, results, activeJobId, activeStage, liveStages, onBack, onViewClips, onDelete }: Props) {
  const liveStageId = activeStage === 'worker_queued' ? 'source' : activeStage
  const stages = lifecycle.stages.map((stage) => {
    if (activeJobId !== lifecycle.job_id || !liveStageId || stage.id !== liveStageId) return stage
    const live = activeStage ? liveStages[activeStage] : undefined
    return { ...stage, state: 'active' as const, progress: live?.fraction, message: live?.message || stage.message }
  })
  const isComplete = lifecycle.status === 'done' || lifecycle.rendered
  const status = isComplete ? 'done' : lifecycle.status
  const live = activeJobId === lifecycle.job_id && activeStage ? liveStages[activeStage] : undefined
  const overallProgress = status === 'done' ? 1 : live?.fraction != null && live.fraction >= 0 ? live.fraction : lifecycle.progress

  return <main className="new-page" style={{ padding: '28px 32px', maxWidth: '960px', margin: '0 auto' }}>
    <button className="creative-back" onClick={onBack}>← Back to Projects</button>
    <section style={{ display: 'flex', gap: '20px', alignItems: 'center', margin: '24px 0 30px' }}>
      <div style={{ width: '150px', height: '92px', borderRadius: '12px', flexShrink: 0, background: lifecycle.thumbnail_url ? `center / cover url("${lifecycle.thumbnail_url}")` : 'linear-gradient(135deg,#29283a,#7770a1)' }} />
      <div style={{ minWidth: 0, flex: 1 }}><p className="new-eyebrow">PROJECT LIFECYCLE</p><h1 style={{ margin: '4px 0', fontSize: '26px' }}>{lifecycle.title || 'Untitled project'}</h1><p style={{ margin: 0, color: '#898b95', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{lifecycle.source}</p></div>
      <div style={{ textAlign: 'right' }}><strong style={{ color: status === 'failed' ? '#be123c' : status === 'done' ? '#059669' : '#6c4df6' }}>{statusLabel(status)}</strong>{lifecycle.clip_count > 0 && <div style={{ color: '#898b95', fontSize: '12px', marginTop: '5px' }}>{lifecycle.clip_count} clips</div>}</div>
    </section>
    {overallProgress != null && overallProgress >= 0 && status !== 'done' && <div style={{ height: '6px', background: '#eceaf5', borderRadius: '4px', marginBottom: '22px' }}><div style={{ height: '100%', width: `${Math.min(100, overallProgress * 100)}%`, background: '#6c4df6', borderRadius: '4px' }} /></div>}
    {lifecycle.error && status === 'failed' && <div role="alert" style={{ padding: '12px 14px', borderRadius: '9px', background: '#fff1f2', color: '#be123c', marginBottom: '18px', fontSize: '13px' }}>{lifecycle.error}</div>}
    <section style={{ background: '#fff', border: '1px solid #e4e3ea', borderRadius: '14px', padding: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}><h2 style={{ margin: 0, fontSize: '17px' }}>Pipeline</h2><div style={{ display: 'flex', gap: '8px' }}>{status === 'done' && results?.render?.outputs?.length && <button className="new-primary" onClick={onViewClips}>View clips</button>}<button className="new-secondary" onClick={() => { if (confirm(`Delete project "${lifecycle.title || 'Untitled project'}" (${lifecycle.job_id})? This cannot be undone.`)) void onDelete().catch((error: unknown) => alert(error instanceof Error ? error.message : 'Could not delete project.')) }}>Delete</button></div></div>
      <div style={{ display: 'grid', gap: '9px' }}>{stages.map((stage) => {
        const active = stage.state === 'active'
        const failed = stage.state === 'failed'
        const completed = stage.state === 'completed'
        const liveMessage = active && activeStage ? liveStages[activeStage]?.message : null
        return <div key={stage.id} style={{ display: 'grid', gridTemplateColumns: '24px 1fr auto', gap: '10px', alignItems: 'center', padding: '10px 11px', borderRadius: '9px', background: active ? '#f0edff' : failed ? '#fff1f2' : 'transparent', color: completed ? '#334155' : failed ? '#be123c' : active ? '#4c32b8' : '#9a9ba4' }}>
          <span style={{ width: '20px', height: '20px', borderRadius: '50%', display: 'grid', placeItems: 'center', background: completed ? '#d1fae5' : failed ? '#ffe4e6' : active ? '#ddd6fe' : '#f1f0f5', color: completed ? '#059669' : failed ? '#e11d48' : active ? '#6c4df6' : '#a5a4ad', fontSize: '12px', fontWeight: 700 }}>{completed ? '✓' : failed ? '!' : active ? '·' : ' '}</span>
          <div><strong style={{ fontSize: '13px' }}>{stage.label}</strong>{(stage.message || liveMessage || stage.error) && <div style={{ fontSize: '11px', marginTop: '2px' }}>{liveMessage || stage.message || stage.error}</div>}</div>
          <div style={{ fontSize: '11px', whiteSpace: 'nowrap' }}>{active && typeof stage.progress === 'number' && stage.progress >= 0 ? `${Math.round(stage.progress * 100)}%` : formatRuntime(stage.runtime_sec)}</div>
        </div>
      })}</div>
    </section>
  </main>
}
