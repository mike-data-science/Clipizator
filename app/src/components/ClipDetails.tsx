import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import type { Clip, JobResults, RenderOutput } from '../types'

interface Word { word: string; start: number; end: number }
interface TimelineEvent { type: string; start: number; end: number }
interface EditContext { words?: Word[]; events?: TimelineEvent[] }
interface Props { results: JobResults; clipIndex: number; onBack: () => void; onEdit: () => void }

function fmtTime(value: number) { const safe = Math.max(0, value); return `${String(Math.floor(safe / 60)).padStart(2, '0')}:${String(Math.floor(safe % 60)).padStart(2, '0')}` }
function titleCase(value: string) { return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()) }
function scoreLabel(score: number) { return score >= 75 ? 'Strong potential' : score >= 55 ? 'Promising' : score >= 35 ? 'Moderate' : 'Needs work' }

function groupTranscript(words: Word[], start: number, end: number) {
  const groups: Word[][] = []
  for (const word of words.filter((item) => item.start >= start && item.start < end)) {
    const previous = groups.at(-1)
    if (!previous || previous.length >= 11 || word.start - previous.at(-1)!.end > 1.1) groups.push([word])
    else previous.push(word)
  }
  return groups.map((group) => ({ start: group[0].start, end: group.at(-1)!.end, text: group.map((word) => word.word).join(' ') }))
}

function IconButton({ label, onClick, children, disabled = false }: { label: string; onClick: () => void; children: React.ReactNode; disabled?: boolean }) {
  return <button className="review-icon-button" title={label} aria-label={label} onClick={onClick} disabled={disabled}>{children}</button>
}

function Glyph({ name }: { name: 'edit' | 'send' | 'download' | 'approve' | 'reject' | 'fullscreen' }) {
  const common = { width: 15, height: 15, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
  if (name === 'edit') return <svg {...common}><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z"/></svg>
  if (name === 'send') return <svg {...common}><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>
  if (name === 'download') return <svg {...common}><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>
  if (name === 'approve') return <svg {...common}><path d="m5 12 4 4L19 6"/></svg>
  if (name === 'reject') return <svg {...common}><path d="m6 6 12 12M18 6 6 18"/></svg>
  return <svg {...common}><path d="M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5"/></svg>
}

function VideoStage({ output, clip, jobId, context, onSourceTime }: { output: RenderOutput; clip: Clip; jobId: string; context: EditContext | null; onSourceTime: (time: number) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const [playing, setPlaying] = useState(false)
  const [hasPlayed, setHasPlayed] = useState(false)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(output.duration)
  const [muted, setMuted] = useState(false)
  const [volume, setVolume] = useState(0.9)
  const [volumeOpen, setVolumeOpen] = useState(false)
  const [showControls, setShowControls] = useState(true)
  const [qualityOpen, setQualityOpen] = useState(false)
  const [quality, setQuality] = useState<'preview' | 'original'>('preview')
  const [previewFailed, setPreviewFailed] = useState(false)
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const source = quality === 'original' || previewFailed ? `${api.fileUrl(output.path)}?v=0` : api.previewUrl(jobId, output.clip)

  useEffect(() => () => { if (hideTimer.current) clearTimeout(hideTimer.current) }, [])
  function revealControls() { setShowControls(true); if (hideTimer.current) clearTimeout(hideTimer.current); if (playing) hideTimer.current = setTimeout(() => setShowControls(false), 1800) }
  function togglePlay() { const video = videoRef.current; if (!video) return; if (video.paused) void video.play(); else video.pause() }
  function seek(next: number) { const video = videoRef.current; if (video) video.currentTime = Math.max(0, Math.min(duration, next)) }
  function toggleFullscreen() { void stageRef.current?.requestFullscreen?.() }
  function setPlayerVolume(next: number) {
    const video = videoRef.current
    if (video) { video.volume = next; video.muted = next === 0 }
    setVolume(next)
    setMuted(next === 0)
  }
  const markers = (context?.events ?? []).filter((event) => event.start >= clip.start && event.start < clip.end)

  return <section className="review-video-zone"><div className="review-video-stage" ref={stageRef} onMouseMove={revealControls} onMouseLeave={() => playing && setShowControls(false)}><video ref={videoRef} src={source} playsInline preload="metadata" muted={muted} onClick={togglePlay} onPlay={() => { setHasPlayed(true); setPlaying(true); revealControls() }} onPause={() => { setPlaying(false); setShowControls(true) }} onLoadedMetadata={(event) => { event.currentTarget.volume = volume; setDuration(event.currentTarget.duration || output.duration) }} onTimeUpdate={(event) => { setTime(event.currentTarget.currentTime); onSourceTime(clip.start + event.currentTarget.currentTime) }} onError={() => { if (quality === 'preview') setPreviewFailed(true) }} /> <div className="review-video-top"><div className="quality-menu-wrap"><button className="quality-trigger" onClick={() => setQualityOpen((open) => !open)}>{quality === 'preview' ? '720p' : 'Original'} <span>⌄</span></button>{qualityOpen && <div className="quality-menu"><button onClick={() => { setQuality('preview'); setQualityOpen(false) }}>720p <span>Preview</span></button><button onClick={() => { setQuality('original'); setQualityOpen(false) }}>Original <span>Source</span></button><button disabled>1080p <span>Unavailable</span></button><button disabled>2K <span>Unavailable</span></button><button disabled>4K <span>Unavailable</span></button><button disabled>AI Enhance <span>Coming soon</span></button></div>}</div></div>{!playing && <button className="review-center-play" onClick={togglePlay} aria-label="Play clip"><span>▶</span></button>}{hasPlayed && <div className={`review-video-controls ${showControls || !playing ? 'visible' : ''}`}><input className="review-progress" aria-label="Video progress" type="range" min="0" max={Math.max(duration, 0.1)} step="0.01" value={Math.min(time, duration)} onChange={(event) => seek(Number(event.target.value))} /><div className="review-control-row"><button onClick={togglePlay} aria-label={playing ? 'Pause' : 'Play'}>{playing ? 'Ⅱ' : '▶'}</button><span>{fmtTime(time)} / {fmtTime(duration)}</span><div className="review-volume" onMouseEnter={() => setVolumeOpen(true)} onMouseLeave={() => setVolumeOpen(false)}><button onClick={() => setPlayerVolume(muted ? Math.max(volume, 0.2) : 0)} aria-label={muted ? 'Unmute' : 'Mute'}>{muted ? '🔇' : '🔊'}</button><input className={volumeOpen ? 'open' : ''} aria-label="Volume" type="range" min="0" max="1" step="0.05" value={muted ? 0 : volume} onChange={(event) => setPlayerVolume(Number(event.target.value))} /></div><button onClick={toggleFullscreen} aria-label="Fullscreen"><Glyph name="fullscreen" /></button></div></div>}</div>{markers.length > 0 && <div className="ai-clip-timeline"><span>AI MOMENTS</span><div className="ai-clip-rail" onClick={(event) => { const rect = event.currentTarget.getBoundingClientRect(); seek(((event.clientX - rect.left) / rect.width) * duration) }}><button className="ai-clip-marker hook" style={{ left: '0%' }} onClick={(event) => { event.stopPropagation(); seek(0) }} title="Clip opening hook" /><i style={{ width: `${duration ? (time / duration) * 100 : 0}%` }} />{markers.map((event, index) => <button key={`${event.type}-${index}`} className="ai-clip-marker" style={{ left: `${((event.start - clip.start) / Math.max(0.1, duration)) * 100}%` }} onClick={(clickEvent) => { clickEvent.stopPropagation(); seek(event.start - clip.start) }} title={`${titleCase(event.type)} at ${fmtTime(event.start - clip.start)}`} />)}</div><span>{markers.length} detected moments</span></div>}</section>
}

function ScoreSummary({ clip }: { clip: Clip }) {
  const strengths = clip.why_it_hits?.slice(0, 3) ?? []
  const risks = clip.risk_flags?.slice(0, 3) ?? []
  const contentNames = ['value', 'curiosity_gap', 'hook', 'funniness']
  const contentSignals = contentNames.flatMap((name) => clip.subscores[name] === undefined ? [] : [[name, clip.subscores[name]] as const])
  const platformSignals = Object.entries(clip.platform_scores).sort(([, a], [, b]) => b - a)
  const bestPlatform = platformSignals[0]
  const interpretation = clip.story_angle || strengths[0] || risks[0]
  return <><section className="review-score"><div className="review-score-number"><small>Clip score</small><strong>{Math.round(clip.score)}</strong><span>/ 100</span></div><div><div className="review-score-title"><b>{scoreLabel(clip.score)}</b><i style={{ width: `${Math.max(0, Math.min(100, clip.score))}%` }} /></div><p>{clip.summary}</p></div></section><section className="review-intelligence clip-dna"><div className="clip-dna-head"><p className="review-section-label">CLIP DNA</p>{interpretation && <p>{interpretation}</p>}</div><div className="clip-dna-readout"><div className="clip-dna-signals"><span>Content signals</span>{contentSignals.map(([name, value]) => <div className="clip-dna-signal" key={name} title={`${titleCase(name)}: ${value.toFixed(1)} out of 10`}><label>{titleCase(name)}</label><i><em style={{ width: `${Math.max(0, Math.min(100, value * 10))}%` }} /></i><b>{value.toFixed(1)}</b></div>)}</div>{platformSignals.length > 0 && <div className="clip-dna-platforms"><span>Platform fit</span>{platformSignals.map(([name, value]) => <div className="clip-dna-platform" key={name}><label>{titleCase(name)}{bestPlatform?.[0] === name && <small>Best fit</small>}</label><b>{Math.round(value)}</b></div>)}</div>}</div>{(strengths.length > 0 || risks.length > 0) && <div className="clip-dna-editorial"><div className="clip-dna-working"><span>Working</span>{strengths.map((item) => <p key={item}>{item}</p>)}</div><div className="clip-dna-friction"><span>Friction</span>{risks.map((item) => <p key={item}>{item}</p>)}</div></div>}</section></>
}

function Transcript({ rows, currentSourceTime, onSeek }: { rows: ReturnType<typeof groupTranscript>; currentSourceTime: number; onSeek: (time: number) => void }) {
  return <section className="review-transcript"><div className="review-section-head"><div><p className="review-section-label">TRANSCRIPT</p><span>Click a timestamp to seek</span></div><b>{rows.length} segments</b></div><div className="transcript-list">{rows.length ? rows.map((row) => <button className={currentSourceTime >= row.start && currentSourceTime < row.end ? 'active' : ''} key={`${row.start}-${row.text}`} onClick={() => onSeek(row.start)}><time>{fmtTime(row.start)}</time><span>{row.text}</span></button>) : <p>No timestamped transcript is available for this clip.</p>}</div></section>
}

function DeepAnalysis({ clip, output }: { clip: Clip; output: RenderOutput }) {
  return <section className="deep-analysis"><p className="review-section-label">DEEP ANALYSIS</p><div className="deep-analysis-grid"><article><h2>Story & hook</h2>{clip.hook_line && <div><b>Opening hook</b><p>{clip.hook_line}</p></div>}{clip.story_angle && <div><b>Story angle</b><p>{clip.story_angle}</p></div>}{clip.why_it_hits?.length ? <div><b>Why it works</b><ul>{clip.why_it_hits.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}</article><article><h2>Performance</h2>{Object.entries(clip.platform_scores).map(([name, value]) => <div className="deep-score" key={name}><span>{titleCase(name)}</span><i><em style={{ width: `${value}%` }} /></i><b>{Math.round(value)}</b></div>)}<p className="deep-meta">Best fit: {output.best_platform} · {output.words} words · {output.event_tags} events</p></article><article><h2>Risks & adjustments</h2>{clip.risk_flags?.length ? <div className="risk-tags">{clip.risk_flags.map((item) => <span key={item}>{item}</span>)}</div> : <p>No specific watch-outs recorded.</p>}{clip.adjustments.map((item, index) => <div className="adjustment" key={index}><b className={item.factor >= 1 ? 'positive' : 'negative'}>{item.factor >= 1 ? '+' : ''}{Math.round((item.factor - 1) * 100)}%</b><span><strong>{titleCase(item.rule)}</strong>{item.reason}</span></div>)}</article>{clip.music && <article><h2>Creative direction</h2><div><b>Music direction</b><p>{clip.music.genre} · {clip.music.mood} · {clip.music.bpm_range} bpm</p><p>{clip.music.theme}</p></div></article>}</div></section>
}

export default function ClipDetails({ results, clipIndex, onBack, onEdit }: Props) {
  const output = (results.render?.outputs ?? []).find((item) => item.clip === clipIndex)
  const clip = results.score?.clips?.[clipIndex]
  const [context, setContext] = useState<EditContext | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [title, setTitle] = useState(clip?.headline || `Clip ${String(clipIndex + 1).padStart(2, '0')}`)
  const [sourceTime, setSourceTime] = useState(clip?.start ?? 0)

  useEffect(() => { api.editTool(results.job_id, 'context', { clip: clipIndex }).then((value) => setContext(value as EditContext)).catch(() => setContext(null)) }, [clipIndex, results.job_id])
  const transcript = useMemo(() => clip ? groupTranscript(context?.words ?? [], clip.start, clip.end) : [], [clip, context])
  if (!clip || !output) return <main className="clip-details-page"><button className="detail-back" onClick={onBack}>Back to clips</button><p className="detail-empty">This clip is no longer available in the project.</p></main>
  const selectedClip: Clip = clip
  function seekSource(time: number) { const video = document.querySelector<HTMLVideoElement>('.review-video-stage video'); if (video) { video.currentTime = time - selectedClip.start; void video.play() } setSourceTime(time) }
  function requestDelete() {
    setMenuOpen(false)
    if (confirm('Delete this clip? This cannot be undone.')) {
      alert('Deleting individual clips is not available in the current API.')
    }
  }

  return <div className="clip-details-page review-workspace"><header className="clip-details-head review-app-header"><button className="detail-back" onClick={onBack} aria-label="Back to clips" /><div className="review-source-context"><span className="review-source-icon">▣</span><b title={results.ingest?.title ?? results.job_id}>{results.ingest?.title ?? results.job_id}</b><button disabled title="Editing the original source video is not available yet">Edit original video</button></div></header><main className="review-workspace-main"><div className="review-layout"><div className="review-left"><VideoStage output={output} clip={clip} jobId={results.job_id} context={context} onSourceTime={setSourceTime} /><div className="review-video-metadata"><span>{titleCase(output.best_platform)}</span><span>{output.words} words</span><span>{output.event_tags} detected events</span><span>{fmtTime(clip.start)} - {fmtTime(clip.end)} source</span></div></div><aside className="review-panel"><div className="review-identity"><p>CLIP #{String(clipIndex + 1).padStart(2, '0')}</p><div className="review-title-row">{renaming ? <input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} onBlur={() => setRenaming(false)} onKeyDown={(event) => event.key === 'Enter' && setRenaming(false)} /> : <h1>{title}</h1>}<IconButton label="Rename title" onClick={() => setRenaming(true)}>✎</IconButton><div className="more-menu"><IconButton label="More actions" onClick={() => setMenuOpen((open) => !open)}>•••</IconButton>{menuOpen && <div><button onClick={() => { setRenaming(true); setMenuOpen(false) }}>Rename title</button><button onClick={requestDelete}>Delete clip</button></div>}</div></div></div><ScoreSummary clip={clip} /><div className="review-action-bar"><button onClick={onEdit}><Glyph name="edit" />Edit / Trim</button><button className="publish" onClick={() => alert('Publish coming soon')}><Glyph name="send" />Publish</button><IconButton label="Download MP4" onClick={() => void api.exportClip(results.job_id, output.clip, title)}><Glyph name="download" /></IconButton><IconButton label="Approve" onClick={() => void api.submitClipFeedback(results.job_id, output.clip, 'approved', 'Approved from clip review')}><Glyph name="approve" /></IconButton><IconButton label="Reject" onClick={() => void api.submitClipFeedback(results.job_id, output.clip, 'rejected', 'Rejected from clip review')}><Glyph name="reject" /></IconButton><IconButton label="AI Enhance is coming soon" onClick={() => {}} disabled>✦</IconButton></div><Transcript rows={transcript} currentSourceTime={sourceTime} onSeek={seekSource} /></aside></div><DeepAnalysis clip={clip} output={output} /></main></div>
}
