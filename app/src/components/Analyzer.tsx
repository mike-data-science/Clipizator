import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { AnalyzerCandidate, AnalyzerVideoDetail as AnalyzerDetail, AnalyzerVideoSummary, CreatorPerformanceLabel, CreatorSource, CreatorSourceDetail, CreatorSourceVideo, ResearchQueueItem } from '../types'

const fmtTime = (seconds: number | null | undefined) => {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return 'Not available'
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`
}

const fmtDate = (timestamp: number | null) => timestamp
  ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(timestamp * 1000))
  : 'Not available'

const titleCase = (value: string) => value.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
const displayValue = (value: unknown) => value === null || value === undefined || value === '' ? 'Not available' : String(value)

function AnalyzerShell({ children, detail, onBack, onSources, onQueue, section = 'videos' }: { children: React.ReactNode; detail?: string; onBack: () => void; onSources?: () => void; onQueue?: () => void; section?: 'videos' | 'sources' | 'queue' }) {
  return <div className="analyzer-shell">
    <aside className="analyzer-sidebar">
      <button className="analyzer-brand" onClick={onBack}><span>p</span>publikclip</button>
      <p>ANALYZER</p>
      <button className={section === 'videos' ? 'selected' : ''} onClick={onBack}><span className="analyzer-nav-icon">▤</span>Videos</button>
      <button className={section === 'sources' ? 'selected' : ''} onClick={onSources}><span className="analyzer-nav-icon">◉</span>Creator sources</button>
      <button className={section === 'queue' ? 'selected' : ''} onClick={onQueue}><span className="analyzer-nav-icon">⇢</span>Research queue</button>
      <div className="analyzer-side-space" />
      <button className="analyzer-workspace-back" onClick={onBack}>← Back to workspace</button>
    </aside>
    <main className="analyzer-main">
      <header className="analyzer-topbar"><span>Analyzer</span><i>/</i><b>{section === 'sources' ? 'Creator sources' : section === 'queue' ? 'Research queue' : 'Videos'}</b>{detail && <><i>/</i><strong>{detail}</strong></>}</header>
      {children}
    </main>
  </div>
}

function EmptyValue({ detected = false }: { detected?: boolean }) {
  return <span className="analyzer-empty-value">{detected ? 'Not detected' : 'Not available'}</span>
}

export function AnalyzerVideos({ onBack, onOpen, onSources, onQueue }: { onBack: () => void; onOpen: (jobId: string) => void; onSources: () => void; onQueue: () => void }) {
  const [videos, setVideos] = useState<AnalyzerVideoSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.listAnalyzerVideos()
      .then(setVideos)
      .catch(err => setError(err instanceof Error ? err.message : 'Could not load Analyzer videos'))
      .finally(() => setLoading(false))
  }, [])

  return <AnalyzerShell onBack={onBack} onSources={onSources} onQueue={onQueue}>
    <div className="analyzer-page analyzer-library">
      <div className="analyzer-page-head">
        <div><p className="analyzer-kicker">ANALYZER</p><h1>Analyzed videos</h1><span>Inspect source detections, model interpretation, and generated edits from completed Shorts.</span></div>
        <div className="analyzer-count">{loading ? 'Loading…' : `${videos.length} video${videos.length === 1 ? '' : 's'}`}</div>
      </div>
      {error && <div className="analyzer-error">{error}</div>}
      {!loading && !error && videos.length === 0 && <div className="analyzer-empty"><h2>No analyzed Shorts yet</h2><p>Completed short-form jobs with scoring artifacts will appear here.</p></div>}
      <div className="analyzer-video-grid">
        {videos.map(video => <button className="analyzer-video-card" key={video.job_id} onClick={() => onOpen(video.job_id)}>
          <div className="analyzer-card-preview">
            {video.source.thumbnail_url
              ? <img src={video.source.thumbnail_url} alt="" />
              : video.source.video_url
                ? <video src={video.source.video_url} preload="metadata" muted />
                : <div className="analyzer-no-preview">Preview not available</div>}
            <span>{fmtTime(video.duration_sec)}</span>
          </div>
          <div className="analyzer-card-body">
            <div className="analyzer-card-status"><i />Analyzed</div>
            <h2>{video.source.title || 'Title not available'}</h2>
            <p>{video.source.platform || (video.source.type === 'file' ? 'Local file' : 'Source not available')} · {video.job_id}</p>
            <div className="analyzer-card-facts">
              <span><b>{video.scene_count ?? '—'}</b>Scenes</span>
              <span><b>{video.speaker_count ?? '—'}</b>Speakers</span>
              <span><b>{video.audio_event_count ?? '—'}</b>Audio events</span>
              <span><b>{video.candidate_count ?? '—'}/{video.scored_count ?? '—'}</b>Candidates / scored</span>
            </div>
            <div className="analyzer-card-foot"><span>{video.model || 'Model not available'}</span><time>{fmtDate(video.analyzed_at)}</time></div>
          </div>
        </button>)}
      </div>
    </div>
  </AnalyzerShell>
}

const fmtCount = (value: number | null | undefined) => value === null || value === undefined ? '—' : new Intl.NumberFormat().format(value)

function updateVideo(detail: CreatorSourceDetail, video: CreatorSourceVideo) {
  return { ...detail, videos: detail.videos.map(item => item.id === video.id ? video : item) }
}

export function CreatorSources({ onBack, onOpen, onQueue }: { onBack: () => void; onOpen: (id: number) => void; onQueue: () => void }) {
  const [sources, setSources] = useState<CreatorSource[]>([])
  const [source, setSource] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const reload = () => api.listCreatorSources().then(setSources).catch(err => setError(err instanceof Error ? err.message : 'Could not load creator sources')).finally(() => setLoading(false))
  useEffect(() => { reload() }, [])
  const add = async (event: React.FormEvent) => {
    event.preventDefault(); if (!source.trim()) return
    setSaving(true); setError(null)
    try { const detail = await api.addCreatorSource(source.trim()); setSource(''); onOpen(detail.id) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not add creator') }
    finally { setSaving(false) }
  }
  return <AnalyzerShell onBack={onBack} onQueue={onQueue} section="sources">
    <div className="analyzer-page analyzer-library creator-sources-page">
      <div className="analyzer-page-head"><div><p className="analyzer-kicker">ANALYZER / RESEARCH</p><h1>Creator sources</h1><span>Metadata-only YouTube catalogs for research. Adding a creator does not download or analyze media.</span></div><div className="analyzer-count">{loading ? 'Loading…' : `${sources.length} creator${sources.length === 1 ? '' : 's'}`}</div></div>
      <form className="creator-add" onSubmit={add}><input value={source} onChange={event => setSource(event.target.value)} placeholder="@creator, youtube.com/@creator, or channel URL" aria-label="YouTube creator" /><button disabled={saving}>{saving ? 'Fetching catalog…' : 'Add YouTube creator'}</button></form>
      {error && <div className="analyzer-error">{error}</div>}
      {!loading && !error && sources.length === 0 && <div className="analyzer-empty"><h2>No creator sources yet</h2><p>Add a YouTube channel to persist its public video metadata.</p></div>}
      <div className="creator-source-grid">{sources.map(item => <button key={item.id} className="creator-source-card" onClick={() => onOpen(item.id)}>{item.thumbnail_url ? <img src={item.thumbnail_url} alt="" /> : <i>▶</i>}<div><b>{item.display_name || item.handle || 'YouTube creator'}</b><span>{item.handle ? `@${item.handle}` : item.canonical_channel_url}</span><small>{fmtCount(item.subscriber_count)} subscribers · {item.video_count ?? 0} videos</small></div></button>)}</div>
    </div>
  </AnalyzerShell>
}

export function CreatorSourceDetail({ creatorId, onBack, onHome, onQueue }: { creatorId: number; onBack: () => void; onHome: () => void; onQueue: () => void }) {
  const [data, setData] = useState<CreatorSourceDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | CreatorPerformanceLabel | 'references' | 'analyzed' | 'not_analyzed'>('all')
  const [sort, setSort] = useState<'views' | 'newest'>('views')
  const [queueMessage, setQueueMessage] = useState<string | null>(null)
  const load = () => api.creatorSource(creatorId).then(setData).catch(err => setError(err instanceof Error ? err.message : 'Could not load creator source'))
  useEffect(() => { load() }, [creatorId])
  const patch = async (action: Promise<CreatorSourceVideo>) => { if (!data) return; try { setData(updateVideo(data, await action)) } catch (err) { setError(err instanceof Error ? err.message : 'Could not update video') } }
  if (error) return <AnalyzerShell onBack={onHome} onSources={onBack} onQueue={onQueue} section="sources" detail={String(creatorId)}><div className="analyzer-page"><button className="analyzer-back" onClick={onBack}>← Creator sources</button><div className="analyzer-error">{error}</div></div></AnalyzerShell>
  if (!data) return <AnalyzerShell onBack={onHome} onSources={onBack} onQueue={onQueue} section="sources" detail={String(creatorId)}><div className="analyzer-page analyzer-loading">Loading creator catalog…</div></AnalyzerShell>
  const visible = data.videos.filter(video => filter === 'all' || (filter === 'references' ? video.is_reference || video.is_editing_reference : filter === 'analyzed' ? video.analysis_status === 'analyzed' : filter === 'not_analyzed' ? video.analysis_status !== 'analyzed' : video.performance_label === filter)).sort((a, b) => sort === 'views' ? (b.views || 0) - (a.views || 0) : (b.published_at || 0) - (a.published_at || 0))
  const replaceDetail = async (action: Promise<CreatorSourceDetail>) => { try { setData(await action) } catch (err) { setError(err instanceof Error ? err.message : 'Could not update selection') } }
  const summary = data.selection_summary
  const queueSelected = async () => { try { const result = await api.queueSelectedCreatorVideos(data.id); setQueueMessage(`${result.queued_count} queued · ${result.skipped_already_queued} already queued · ${result.skipped_already_analyzed} already analyzed${result.errors.length ? ` · ${result.errors.length} errors` : ''}`); await load() } catch (err) { setError(err instanceof Error ? err.message : 'Could not queue selected videos') } }
  return <AnalyzerShell onBack={onHome} onSources={onBack} onQueue={onQueue} section="sources" detail={data.display_name || data.handle || String(creatorId)}><div className="analyzer-page creator-detail"><button className="analyzer-back" onClick={onBack}>← Creator sources</button>
    <section className="creator-detail-head">{data.thumbnail_url ? <img src={data.thumbnail_url} alt="" /> : <i>▶</i>}<div><p className="analyzer-kicker">YOUTUBE CREATOR SOURCE</p><h1>{data.display_name || data.handle || 'YouTube creator'}</h1><span>{data.handle ? `@${data.handle} · ` : ''}{fmtCount(data.subscriber_count)} subscribers · Refreshed {fmtDate(data.last_refreshed_at)}</span><a href={data.canonical_channel_url} target="_blank" rel="noreferrer">Open channel ↗</a></div><button className="creator-refresh" onClick={async () => { try { setData(await api.refreshCreatorSource(data.id)) } catch (err) { setError(err instanceof Error ? err.message : 'Refresh failed') } }}>Refresh metadata</button></section>
    <div className="creator-controls"><div>{(['all', 'strong', 'average', 'weak', 'references', 'analyzed', 'not_analyzed'] as const).map(item => <button className={filter === item ? 'active' : ''} onClick={() => setFilter(item)} key={item}>{titleCase(item)}</button>)}</div><select value={sort} onChange={event => setSort(event.target.value as 'views' | 'newest')}><option value="views">Highest views</option><option value="newest">Newest</option></select></div>
    <section className="creator-selection-summary"><div><b>Selected for analysis: {summary.selected}</b><span>Strong {summary.strong} · Average {summary.average} · Weak {summary.weak} · Manual/reference {summary.manual_reference}</span>{queueMessage && <span className="creator-queue-message">{queueMessage}</span>}</div><div><button onClick={() => void replaceDetail(api.setCreatorSelection(data.id, visible.map(video => video.id), true, 'manual'))}>Select all visible</button><button onClick={() => void replaceDetail(api.clearCreatorSelection(data.id))}>Clear selection</button><button onClick={() => void replaceDetail(api.autoSelectCreatorSample(data.id))}>Auto-select sample</button><button className="primary" disabled={summary.selected === 0} onClick={() => void queueSelected()}>Queue selected</button></div></section>
    <p className="creator-catalog-note">Performance labels are creator-relative metadata previews, not a universal quality score. Manual labels override the derived label.</p>
    <div className="creator-video-list">{visible.map(video => <article key={video.id} className="creator-video-row"><label className="creator-select"><input type="checkbox" checked={video.selected_for_analysis} onChange={event => void replaceDetail(api.setCreatorSelection(data.id, [video.id], event.target.checked, event.target.checked ? 'manual' : null))} /><span>Select</span></label>{video.thumbnail_url ? <img src={video.thumbnail_url} alt="" /> : <div className="creator-thumb-empty">No thumbnail</div>}<div className="creator-video-main"><a href={video.canonical_url} target="_blank" rel="noreferrer">{video.title || 'Untitled video'}</a><span>{video.published_at ? fmtDate(video.published_at) : 'Date unavailable'} · {fmtTime(video.duration_sec)}</span><small>{fmtCount(video.views)} views · {fmtCount(video.likes)} likes · {fmtCount(video.comments)} comments{video.tab_origin ? ` · ${video.content_type || 'catalog'} from ${video.tab_origin}` : ''}</small></div><div className="creator-video-status"><b className={`creator-label ${video.performance_label}`}>{video.performance_label}</b><span>{video.manual_performance_label ? 'Manual label' : video.performance_metric || 'No baseline'}</span><small>{video.research_queue_status ? `Queue: ${video.research_queue_status.replaceAll('_', ' ')} · Analysis: ${video.analysis_status.replaceAll('_', ' ')}` : `${video.download_status.replaceAll('_', ' ')} · ${video.analysis_status.replaceAll('_', ' ')}`}</small></div><div className="creator-video-actions"><select value={video.manual_performance_label || 'unclassified'} onChange={event => void patch(api.setCreatorVideoPerformance(video.id, event.target.value === 'unclassified' ? null : event.target.value as CreatorPerformanceLabel))}><option value="unclassified">Manual / derived</option><option value="strong">Strong</option><option value="average">Average</option><option value="weak">Weak</option></select><button className={video.is_reference ? 'active' : ''} onClick={() => void patch(api.setCreatorVideoReferences(video.id, !video.is_reference, undefined))}>★ Reference</button><button className={video.is_editing_reference ? 'active' : ''} onClick={() => void patch(api.setCreatorVideoReferences(video.id, undefined, !video.is_editing_reference))}>✦ Editing ref</button></div></article>)}</div>
  </div></AnalyzerShell>
}

export function ResearchQueue({ onBack, onSources, onOpen }: { onBack: () => void; onSources: () => void; onOpen: (jobId: string) => void }) {
  const [items, setItems] = useState<ResearchQueueItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const load = () => api.listResearchQueue().then(setItems).catch(err => setError(err instanceof Error ? err.message : 'Could not load research queue'))
  useEffect(() => { void load(); const timer = window.setInterval(load, 5000); return () => window.clearInterval(timer) }, [])
  const retry = async (item: ResearchQueueItem) => { try { await api.retryResearchQueueItem(item.id); await load() } catch (err) { setError(err instanceof Error ? err.message : 'Retry failed') } }
  return <AnalyzerShell onBack={onBack} onSources={onSources} onQueue={() => undefined} section="queue"><div className="analyzer-page analyzer-library research-queue-page">
    <div className="analyzer-page-head"><div><p className="analyzer-kicker">ANALYZER / RESEARCH</p><h1>Research queue</h1><span>Selected originals are downloaded sequentially by the laptop worker, then analyzed through the existing pipeline.</span></div><div className="analyzer-count">{items.length} item{items.length === 1 ? '' : 's'}</div></div>
    {error && <div className="analyzer-error">{error}</div>}
    {!error && items.length === 0 && <div className="analyzer-empty"><h2>Queue is empty</h2><p>Select videos from a creator source, then choose Queue selected.</p></div>}
    <div className="research-queue-list">{items.map(item => <article className="research-queue-row" key={item.id}><div><b>{item.catalog_title || item.external_video_id}</b><span>{item.creator_display_name || (item.creator_handle ? `@${item.creator_handle}` : 'YouTube creator')}</span><small>Queued {fmtDate(item.created_at)} · Item #{item.id}</small></div><div><b className={`research-status ${item.status}`}>{titleCase(item.status)}</b><span>Analysis: {titleCase(item.analysis_status || 'pending')}</span><small>{item.progress_stage ? `Stage: ${titleCase(item.progress_stage)} · ` : ''}{item.job_id || 'Job not linked'}</small></div><div>{item.failure_reason && <p>{item.failure_reason}</p>}{item.status === 'failed' && <button onClick={() => void retry(item)}>Retry</button>}{item.status === 'completed' && item.job_id && <button onClick={() => onOpen(item.job_id!)}>Open analysis</button>}</div></article>)}</div>
  </div></AnalyzerShell>
}

function Timeline({ data, duration, onSeek }: { data: AnalyzerDetail; duration: number; onSeek: (time: number) => void }) {
  const pct = (time: number) => `${Math.max(0, Math.min(100, time / Math.max(duration, .1) * 100))}%`
  const speech = data.transcript.segments
  const candidates = data.candidate_analysis.clips
  const punches = data.generated_edit.trajectories.flatMap(item => item.punches)
  const source = data.source_analysis
  const rows = [
    { name: 'Speech', items: speech.map(item => ({ start: item.start, end: item.end, label: item.text, kind: 'speech' })) },
    { name: 'Speaker turns', items: data.speakers.turns.map(item => ({ start: item.start, end: item.end, label: `Speaker ${item.speaker + 1}`, kind: `speaker-${item.speaker % 4}` })) },
    { name: 'Scenes', items: data.scenes.timestamps.map(item => ({ start: item, end: item + .08, label: `Scene at ${fmtTime(item)}`, kind: 'scene' })) },
    { name: 'Audio events', items: data.audio.events.map(item => ({ start: item.start, end: item.end, label: titleCase(item.type), kind: 'audio' })) },
    { name: 'On-screen text', items: source.text_tracks.map(item => ({ start: item.start, end: item.end, label: item.text, kind: 'ocr' })) },
    { name: 'Title hook', items: source.title_hook_candidates.map(item => ({ start: item.start, end: item.end, label: item.text, kind: 'title-hook' })) },
    { name: 'Layout changes', items: source.source_editing_evidence.layout_changes.map(item => ({ start: item.start, end: Math.max(item.end, item.start + .08), label: `Layout change at ${fmtTime(item.start)}`, kind: 'layout-change' })) },
    { name: 'Visual observations', items: source.visual_observations.map(item => ({ start: item.start, end: item.end, label: titleCase(item.type || 'visual observation'), kind: 'visual-observation' })) },
    { name: 'B-roll candidates', items: source.source_editing_evidence.b_roll_candidates.map(item => ({ start: item.start, end: item.end, label: 'Potential source B-roll', kind: 'b-roll' })) },
    { name: 'Candidate interval', items: candidates.map(item => ({ start: item.start, end: item.end, label: `Candidate ${fmtTime(item.start)}–${fmtTime(item.end)}`, kind: 'candidate' })) },
    { name: 'Generated punch-ins', items: punches.map(item => ({ start: item.source_start, end: item.source_end, label: `${titleCase(item.trigger)} punch-in`, kind: 'punch' })) },
  ].filter(row => row.items.length > 0)
  return <section className="analyzer-timeline-card">
    <div className="analyzer-section-title"><div><span>ANALYSIS TIMELINE</span><h2>Source and generated decisions</h2></div><p>Generated punch-ins are separated from detected source signals.</p></div>
    <div className="analyzer-timeline">
      {rows.map(row => <div className="analyzer-timeline-row" key={row.name}>
        <label>{row.name}</label>
        <div className="analyzer-timeline-track" onClick={event => { const rect = event.currentTarget.getBoundingClientRect(); onSeek((event.clientX - rect.left) / rect.width * duration) }}>
          {row.items.map((item, index) => <button key={`${item.start}-${index}`} className={item.kind} title={item.label} style={{ left: pct(item.start), width: `max(2px, ${Math.max(0.08, item.end - item.start) / Math.max(duration, .1) * 100}%)` }} onClick={event => { event.stopPropagation(); onSeek(item.start) }} />)}
          {row.items.length === 0 && <span>None</span>}
        </div>
      </div>)}
      <div className="analyzer-timeline-axis"><span>0:00</span><span>{fmtTime(duration / 2)}</span><span>{fmtTime(duration)}</span></div>
    </div>
  </section>
}

function Curve({ curve }: { curve: AnalyzerDetail['audio']['curves'][number] }) {
  const points = useMemo(() => {
    if (!curve.values.length) return ''
    const min = Math.min(...curve.values), max = Math.max(...curve.values), range = max - min || 1
    return curve.values.map((value, index) => `${index / Math.max(1, curve.values.length - 1) * 100},${34 - (value - min) / range * 30}`).join(' ')
  }, [curve.values])
  return <div className="analyzer-curve">
    <div><b>{curve.name}</b><span>{curve.sample_count ? `${curve.sample_count} samples` : 'Not available'}</span></div>
    {points ? <svg viewBox="0 0 100 38" preserveAspectRatio="none" aria-label={`${curve.name} signal`}><polyline points={points} /></svg> : <EmptyValue />}
    {curve.mean !== null && <small>Mean {curve.mean.toFixed(3)} · Range {curve.min?.toFixed(3)}–{curve.max?.toFixed(3)}</small>}
  </div>
}

function SourceAnalysis({ data, currentTime, onSeek }: { data: AnalyzerDetail; currentTime: number; onSeek: (time: number) => void }) {
  const source = data.source_analysis
  const layout = source.source_layout
  const title = source.title_hook_candidates[0]
  const percent = (value: number) => `${(value * 100).toFixed(1)}%`
  return <section className="analyzer-major-section source-detected">
    <div className="analyzer-major-head"><span className="analyzer-category blue">A</span><div><p>DETECTED IN SOURCE</p><h2>Source analysis</h2><span>Only observations measured from the original video.</span></div></div>
    <div className="analyzer-two-column">
      <article className="analyzer-panel analyzer-transcript">
        <div className="analyzer-panel-head"><div><h3>Transcript</h3><p>{data.transcript.word_count ?? 'Unknown'} words · {data.transcript.language || 'Language unavailable'}</p></div><span>Click to seek</span></div>
        <div className="analyzer-transcript-list">
          {data.transcript.segments.length ? data.transcript.segments.map(segment => <button className={currentTime >= segment.start && currentTime < segment.end ? 'active' : ''} key={`${segment.start}-${segment.text}`} onClick={() => onSeek(segment.start)}>
            <time>{fmtTime(segment.start)}</time><div><b>Speaker {typeof segment.speaker === 'number' ? segment.speaker + 1 : 'not available'}</b><p>{segment.text}</p></div>
          </button>) : <EmptyValue />}
        </div>
      </article>
      <div className="analyzer-stack">
        <article className="analyzer-panel">
          <div className="analyzer-panel-head"><div><h3>Speakers</h3><p>{data.speakers.count === null ? 'Not available' : `${data.speakers.count} detected`}</p></div></div>
          <div className="analyzer-turns">{data.speakers.turns.length ? data.speakers.turns.map((turn, index) => <button key={`${turn.start}-${index}`} onClick={() => onSeek(turn.start)}><i className={`speaker-${turn.speaker % 4}`} /><b>Speaker {turn.speaker + 1}</b><span>{fmtTime(turn.start)}–{fmtTime(turn.end)}</span></button>) : <EmptyValue detected />}</div>
        </article>
        <article className="analyzer-panel">
          <div className="analyzer-panel-head"><div><h3>Scenes</h3><p>{data.scenes.count === null ? 'Not available' : `${data.scenes.count} scene markers`}</p></div><span>{data.scenes.detector_outcome ? titleCase(data.scenes.detector_outcome) : 'Detector status unavailable'}</span></div>
          <div className="analyzer-marker-list">{data.scenes.timestamps.length ? data.scenes.timestamps.map((time, index) => <button onClick={() => onSeek(time)} key={`${time}-${index}`}><b>{String(index + 1).padStart(2, '0')}</b><span>{fmtTime(time)}</span></button>) : <p>No scene cuts detected</p>}</div>
        </article>
      </div>
    </div>
    <article className="analyzer-panel analyzer-text-layout">
      <div className="analyzer-panel-head"><div><h3>Text &amp; layout</h3><p>OCR evidence and source-canvas geometry</p></div><span>DETECTED IN SOURCE</span></div>
      {!source.available ? <p className="analyzer-no-events">Source visual analysis has not been run for this Short.</p> : <>
        <div className="analyzer-title-layout-grid">
          <div className="analyzer-detected-hook"><label>Detected title hook</label>{title ? <button onClick={() => onSeek(title.start)}><b>{title.text}</b><span>{fmtTime(title.start)}–{fmtTime(title.end)} · {Math.round(title.confidence * 100)}% confidence</span><small>{title.canvas_position.replaceAll('_', ' ')} · {title.content_relation.replaceAll('_', ' ')}</small></button> : <EmptyValue detected />}</div>
          <div className="analyzer-layout-summary"><label>Source layout</label>{layout ? <dl>
            <div><dt>Mode</dt><dd>{titleCase(layout.layout_mode)}</dd></div>
            <div><dt>Canvas ratio</dt><dd>{layout.canvas_aspect_ratio.toFixed(3)}</dd></div>
            <div><dt>Primary content ratio</dt><dd>{layout.primary_content_aspect_ratio.toFixed(3)}</dd></div>
            <div><dt>Primary bbox</dt><dd>x {percent(layout.primary_content_bbox.x)} · y {percent(layout.primary_content_bbox.y)} · w {percent(layout.primary_content_bbox.width)} · h {percent(layout.primary_content_bbox.height)}</dd></div>
            <div><dt>Shape / background</dt><dd>{titleCase(layout.approximate_shape)} · {titleCase(layout.background_relationship)}</dd></div>
            <div><dt>Confidence</dt><dd>{Math.round(layout.confidence * 100)}%</dd></div>
          </dl> : <EmptyValue detected />}</div>
        </div>
        <div className="analyzer-ocr-list">
          {source.text_tracks.length ? source.text_tracks.map(track => <button key={track.id} onClick={() => onSeek(track.start)}>
            <time>{fmtTime(track.start)}–{fmtTime(track.end)}</time><div><b>{track.text}</b><span>{titleCase(track.classification)} · {Math.round(track.confidence * 100)}%</span></div>
            <small>x {percent(track.bbox.x)} · y {percent(track.bbox.y)} · w {percent(track.bbox.width)} · h {percent(track.bbox.height)}<br />{track.canvas_position.replaceAll('_', ' ')} · {track.content_relation.replaceAll('_', ' ')} · {track.line_count} line{track.line_count === 1 ? '' : 's'}</small>
          </button>) : <EmptyValue detected />}
        </div>
      </>}
    </article>
    <article className="analyzer-panel analyzer-audio-panel">
      <div className="analyzer-panel-head"><div><h3>Audio</h3><p>Detected events and measured source signals</p></div><span>Arousal source: {data.audio.arousal_source || 'Not available'}</span></div>
      {data.audio.events.length ? <div className="analyzer-event-list">{data.audio.events.map((event, index) => <button key={`${event.start}-${index}`} onClick={() => onSeek(event.start)}><b>{titleCase(event.type)}</b><span>{fmtTime(event.start)}–{fmtTime(event.end)}</span><small>{event.confidence === undefined ? 'Confidence unavailable' : `${Math.round(event.confidence * 100)}% confidence`}</small></button>)}</div> : <p className="analyzer-no-events">No supported audio events detected</p>}
      <div className="analyzer-curves">{data.audio.curves.map(curve => <Curve key={curve.name} curve={curve} />)}</div>
    </article>
  </section>
}

function ScoreBar({ label, value, max = 10 }: { label: string; value: unknown; max?: number }) {
  const numeric = typeof value === 'number' ? value : null
  return <div className="analyzer-scorebar"><span>{label}</span><i>{numeric !== null && <em style={{ width: `${Math.max(0, Math.min(100, numeric / max * 100))}%` }} />}</i><b>{numeric !== null ? numeric.toFixed(1) : '—'}</b></div>
}

function CandidateCard({ candidate, index }: { candidate: AnalyzerCandidate; index: number }) {
  const raw = candidate.t1_raw || {}
  return <article className="analyzer-candidate">
    <div className="analyzer-candidate-head"><div><span>CANDIDATE {String(index + 1).padStart(2, '0')}</span><h3>{candidate.headline || candidate.summary || 'Interpretation title not available'}</h3></div>{typeof candidate.score === 'number' && <strong>{Math.round(candidate.score)}<small>/100</small></strong>}</div>
    <div className="analyzer-interval">Analyzed candidate interval: <b>{fmtTime(candidate.start)} – {fmtTime(candidate.end)}</b><span>Candidate-based score; it does not cover the entire source unless the interval does.</span></div>
    <div className="analyzer-interpret-grid">
      <div className="analyzer-copy-block"><label>Summary</label>{candidate.summary ? <p>{candidate.summary}</p> : <EmptyValue />}</div>
      <div className="analyzer-copy-block"><label>Hook line</label>{candidate.hook_line ? <p>{candidate.hook_line}</p> : <EmptyValue />}</div>
      <div className="analyzer-copy-block"><label>Story angle</label>{candidate.story_angle ? <p>{candidate.story_angle}</p> : <EmptyValue />}</div>
      <div className="analyzer-copy-block"><label>Hook type</label><p>{displayValue(raw.hook_type)}</p></div>
    </div>
    <div className="analyzer-score-grid">
      <ScoreBar label="Hook" value={raw.hook} /><ScoreBar label="Value" value={raw.value} />
      <ScoreBar label="Curiosity gap" value={raw.curiosity_gap} /><ScoreBar label="Funniness" value={raw.funniness} />
      <ScoreBar label="Shock" value={raw.shock} />
    </div>
    <div className="analyzer-platforms">{Object.entries(candidate.platform_scores || {}).map(([platform, score]) => <div key={platform}><span>{titleCase(platform)}</span><b>{Math.round(score)}</b></div>)}</div>
    <div className="analyzer-list-grid">
      <div><label>Why it hits</label>{candidate.why_it_hits?.length ? <ul>{candidate.why_it_hits.map(item => <li key={item}>{item}</li>)}</ul> : <EmptyValue />}</div>
      <div><label>Risk flags</label>{candidate.risk_flags?.length ? <ul className="risks">{candidate.risk_flags.map(item => <li key={item}>{item}</li>)}</ul> : <EmptyValue />}</div>
    </div>
    <div className="analyzer-signal-row"><span>Confidence <b>{candidate.confidence || 'Not available'}</b></span><span>Signals fired {candidate.signals_fired?.length ? candidate.signals_fired.map(item => <i key={item}>{titleCase(item)}</i>) : <EmptyValue />}</span><span>Signals missing {candidate.signals_missing?.length ? candidate.signals_missing.map(item => <i className="missing" key={item}>{titleCase(item)}</i>) : <EmptyValue />}</span></div>
  </article>
}

function AIInterpretation({ data }: { data: AnalyzerDetail }) {
  return <section className="analyzer-major-section ai-interpreted">
    <div className="analyzer-major-head"><span className="analyzer-category purple">B</span><div><p>AI INTERPRETATION</p><h2>Candidate-based creative analysis</h2><span>Semantic judgments from {data.provenance.model || 'the configured model'}, not source detections.</span></div></div>
    {data.candidate_analysis.clips.length
      ? <div className="analyzer-candidates">{data.candidate_analysis.clips.map((candidate, index) => <CandidateCard candidate={candidate} index={index} key={`${candidate.start}-${index}`} />)}</div>
      : <div className="analyzer-panel"><EmptyValue /></div>}
  </section>
}

function GeneratedEdits({ data }: { data: AnalyzerDetail }) {
  const trajectories = data.generated_edit.trajectories
  return <section className="analyzer-major-section generated-edits">
    <div className="analyzer-major-head"><span className="analyzer-category amber">C</span><div><p>GENERATED EDIT SUGGESTIONS</p><h2>Camera, crop, and render outputs</h2><span>Generated edit suggestions — not detected edits from the original video.</span></div></div>
    <div className="analyzer-edit-grid">
      <article className="analyzer-panel"><h3>Generated camera decisions</h3>{data.generated_edit.camera_stats.length ? data.generated_edit.camera_stats.map(stat => <div className="analyzer-edit-stat" key={stat.clip}><b>Clip {stat.clip + 1}</b><span>{stat.punches} punch-ins</span><span>{stat.shot_cuts} shot cuts</span><span>{stat.switch_cuts} speaker cuts</span><span>{stat.tracks} tracks</span></div>) : <EmptyValue />}</article>
      <article className="analyzer-panel"><h3>Camera settings</h3><dl className="analyzer-definition-list">{Object.entries(data.generated_edit.camera_settings).length ? Object.entries(data.generated_edit.camera_settings).map(([key, value]) => <div key={key}><dt>{titleCase(key)}</dt><dd>{displayValue(value)}</dd></div>) : <EmptyValue />}</dl></article>
      <article className="analyzer-panel"><h3>Crop trajectories</h3>{trajectories.length ? trajectories.map(item => <div className="analyzer-trajectory" key={item.clip}><b>Clip {item.clip + 1}</b><span>{item.frame_count} frames at {item.fps || '—'} fps</span><span>Crop width {item.crop_summary.min_width?.toFixed(0) || '—'}–{item.crop_summary.max_width?.toFixed(0) || '—'} px</span><span>{item.cuts.length} generated cut markers</span></div>) : <EmptyValue />}</article>
      <article className="analyzer-panel"><h3>Render outputs</h3>{data.generated_edit.render.outputs.length ? <>{data.generated_edit.render.outputs.map(output => <a className="analyzer-render-link" href={output.url || undefined} target="_blank" rel="noreferrer" key={output.clip}>Clip {output.clip + 1}<span>{fmtTime(output.duration)} · {titleCase(output.best_platform)}</span></a>)}<p className="analyzer-render-meta">Preset {data.generated_edit.render.caption_preset || 'not available'} · {data.generated_edit.render.acceleration.encoding || 'Encoder unavailable'}</p></> : <EmptyValue />}</article>
    </div>
  </section>
}

function QASection({ data }: { data: AnalyzerDetail }) {
  return <section className="analyzer-qa analyzer-panel">
    <div className="analyzer-panel-head"><div><h3>Human QA</h3><p>Existing pilot corrections for this analysis</p></div><span>Read-only in Analyzer v0</span></div>
    {data.qa.length ? <div className="analyzer-qa-table"><div><b>Timestamp</b><b>Detector / event</b><b>Original</b><b>Corrected</b><b>Note</b></div>{data.qa.map(row => <div key={row.id}><span>{fmtTime(row.start_sec)}–{fmtTime(row.end_sec)}</span><span>{titleCase(row.target_type)}</span><span>{JSON.stringify(row.original)}</span><span>{JSON.stringify(row.corrected)}</span><span>{row.note || '—'}</span></div>)}</div> : <div className="analyzer-qa-empty"><b>No pilot QA corrections recorded</b><p>Future corrections will capture timestamp, detector/event type, original value, corrected value, and note here.</p></div>}
  </section>
}

export function AnalyzerVideoDetail({ jobId, onBack, onHome, onSources, onQueue }: { jobId: string; onBack: () => void; onHome: () => void; onSources: () => void; onQueue: () => void }) {
  const [data, setData] = useState<AnalyzerDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const videoRef = useRef<HTMLVideoElement>(null)

  useEffect(() => { api.analyzerVideo(jobId).then(setData).catch(err => setError(err instanceof Error ? err.message : 'Could not load analysis')) }, [jobId])
  const seek = (time: number) => { if (videoRef.current) { videoRef.current.currentTime = time; void videoRef.current.play().catch(() => undefined) } setCurrentTime(time) }

  if (error) return <AnalyzerShell onBack={onHome} onSources={onSources} onQueue={onQueue} detail={jobId}><div className="analyzer-page"><button className="analyzer-back" onClick={onBack}>← Videos</button><div className="analyzer-error">{error}</div></div></AnalyzerShell>
  if (!data) return <AnalyzerShell onBack={onHome} onSources={onSources} onQueue={onQueue} detail={jobId}><div className="analyzer-page analyzer-loading">Loading persisted analysis…</div></AnalyzerShell>
  const duration = data.job.duration_sec
  const lead = data.candidate_analysis.clips[0]

  return <AnalyzerShell onBack={onHome} onSources={onSources} onQueue={onQueue} detail={jobId}>
    <div className="analyzer-page analyzer-detail">
      <button className="analyzer-back" onClick={onBack}>← All analyzed videos</button>
      <div className="analyzer-detail-head">
        <div><p className="analyzer-kicker">ANALYZER VIDEO DETAIL</p><h1>{data.source.title || 'Title not available'}</h1><span className="analyzer-job-id">{jobId}</span></div>
        <span className="analyzer-success"><i />Analysis complete</span>
      </div>
      <section className="analyzer-hero">
        <div className="analyzer-player">
          {data.source.video_url ? <video ref={videoRef} src={data.source.video_url} controls playsInline preload="metadata" onTimeUpdate={event => setCurrentTime(event.currentTarget.currentTime)} /> : <div>Original video unavailable</div>}
        </div>
        <aside className="analyzer-source-card">
          <p>SOURCE METADATA</p>
          <h2>{data.source.title || 'Title not available'}</h2>
          <dl>
            <div><dt>Source</dt><dd>{data.source.platform || (data.source.type === 'file' ? 'Local file' : 'Not available')}</dd></div>
            <div><dt>Duration</dt><dd>{fmtTime(duration)}</dd></div>
            <div><dt>Resolution</dt><dd>{data.source.probe.width && data.source.probe.height ? `${data.source.probe.width} × ${data.source.probe.height}` : 'Not available'}</dd></div>
            <div><dt>Analyzed</dt><dd>{fmtDate(data.job.analyzed_at)}</dd></div>
            <div><dt>Model</dt><dd>{data.provenance.model || 'Not available'}</dd></div>
            <div><dt>Thinking</dt><dd>{data.provenance.llm_generation.thinking_enabled === false ? 'Disabled' : data.provenance.llm_generation.thinking_enabled === true ? 'Enabled' : 'Not available'}</dd></div>
          </dl>
          <div className="analyzer-high-level"><label>MODEL INTERPRETATION</label>{lead?.summary ? <p>{lead.summary}</p> : <EmptyValue />}<small>{lead ? `Candidate interval ${fmtTime(lead.start)}–${fmtTime(lead.end)}` : 'No scored candidate available'}</small></div>
          {data.source.source_url ? <a href={data.source.source_url} target="_blank" rel="noreferrer">Open original source ↗</a> : <span className="analyzer-source-missing">Original source URL not persisted</span>}
        </aside>
      </section>
      <Timeline data={data} duration={duration} onSeek={seek} />
      <SourceAnalysis data={data} currentTime={currentTime} onSeek={seek} />
      <AIInterpretation data={data} />
      <GeneratedEdits data={data} />
      <QASection data={data} />
    </div>
  </AnalyzerShell>
}
