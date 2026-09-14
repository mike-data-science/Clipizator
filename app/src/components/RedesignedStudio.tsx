import { useEffect, useState } from 'react'
import type { JobSummary, Campaign } from '../types'
import { api } from '../api'

type Tab = 'home' | 'analytics' | 'integrations' | 'calendar' | 'clips' | 'campaigns'

interface Props {
  jobs: JobSummary[]
  running: boolean
  initialSource?: string
  onRun: (source: string, llm: string, geminiModel: string, captions: string, asrModel: string, captionColor: string) => void
  onUpload: (file: File, llm: string, geminiModel: string, captions: string, asrModel: string) => void
  onOpenJob: (id: string) => void
  onOpenLoop: () => void
  onOpenQueue: () => void
  onOpenTranscribeQueue: () => void
}

export default function RedesignedStudio({ jobs, running, initialSource, onRun, onUpload, onOpenJob, onOpenLoop, onOpenQueue, onOpenTranscribeQueue }: Props) {
  const [tab, setTab] = useState<Tab>('home')
  const [source, setSource] = useState(initialSource || '')
  const [showUpload, setShowUpload] = useState(false)
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [campaignLoading, setCampaignLoading] = useState(false)
  const loadCampaigns = async () => { setCampaignLoading(true); try { setCampaigns(await api.listCampaigns()) } catch { setCampaigns([]) } finally { setCampaignLoading(false) } }
  const createCampaign = async () => { const name = window.prompt('Campaign name'); if (!name?.trim()) return; try { await api.createCampaign(name.trim()); await loadCampaigns() } catch (e) { window.alert(e instanceof Error ? e.message : 'Could not create campaign') } }
  useEffect(() => { if (tab === 'campaigns' && !campaigns.length) void loadCampaigns() }, [tab])
  const nav = [
    ['home', '⌂', 'Home'], ['analytics', '◔', 'Analytics'], ['integrations', '⌘', 'API integrations'],
    ['calendar', '▣', 'Calendar'], ['clips', '▶', 'Clips'], ['campaigns', '▤', 'Campaigns']
  ] as const
  const submit = () => source.trim() && onRun(source.trim(), 'ollama', 'gemini-3.7-flash', 'hormozi', 'large-v3-turbo', 'white')

  return <div className="new-shell">
    <aside className="new-sidebar">
      <div className="new-brand"><span className="new-brand-mark">✦</span><span>clipizator</span></div>
      <button className="new-create" onClick={() => setTab('home')}>＋ <span>Create video</span></button>
      <nav className="new-nav">{nav.map(([id, icon, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}><i>{icon}</i>{label}</button>)}</nav>
      <div className="new-sidebar-spacer" />
      <div className="new-tools-label">WORKSPACE</div>
      <button className="new-nav-tool" onClick={onOpenLoop}>◌ Instagram loop</button>
      <button className="new-nav-tool" onClick={onOpenQueue}>↓ Download queue</button>
      <button className="new-nav-tool" onClick={onOpenTranscribeQueue}>◉ Transcribe queue</button>
      <div className="new-user"><span className="new-avatar">M</span><span><b>Mike</b><small>Personal workspace</small></span><span>⋯</span></div>
    </aside>
    <main className="new-main">
      <header className="new-topbar"><div className="new-breadcrumb">Workspace <span>/</span> {nav.find(n => n[0] === tab)?.[2]}</div><div className="new-top-actions"><button>⌕</button><button>?</button><button className="new-upgrade">Upgrade</button></div></header>
      {tab === 'home' && <section className="new-page new-home"><div className="new-hero"><p className="new-eyebrow">AI VIDEO WORKSPACE</p><h1>Turn long videos<br /><em>into short-form.</em></h1><p className="new-subtitle">Create scroll-stopping clips, captions and campaigns in minutes.</p><div className="new-create-card"><div className="new-input-wrap"><span>◎</span><input value={source} onChange={e => setSource(e.target.value)} onKeyDown={e => e.key === 'Enter' && submit()} placeholder="Paste a video URL to get started" disabled={running} /></div><button className="new-primary" onClick={submit} disabled={running || !source.trim()}>{running ? 'Processing…' : 'Create clips  →'}</button><button className="new-upload" onClick={() => setShowUpload(true)}>Upload file</button>{showUpload && <input className="new-file" type="file" accept="video/*" autoFocus onChange={e => { const f = e.target.files?.[0]; if (f) onUpload(f, 'ollama', 'gemini-3.7-flash', 'hormozi', 'large-v3-turbo'); setShowUpload(false) }} />}</div></div><div className="new-section-head"><div><h2>Recent projects</h2><p>Your latest videos and generated clips</p></div><button className="new-link" onClick={() => setTab('clips')}>View all clips →</button></div><ProjectGrid jobs={jobs} onOpenJob={onOpenJob} /></section>}
      {tab === 'clips' && <section className="new-page"><PageTitle title="Your clips" sub="All finished clips from your projects" /><ProjectGrid jobs={jobs} onOpenJob={onOpenJob} large /></section>}
      {tab === 'analytics' && <section className="new-page"><PageTitle title="Analytics" sub="Understand what is working across your content" /><div className="metrics-grid"><Metric label="Total views" value="—" hint="Connect a channel to see data" /><Metric label="Clips published" value={String(jobs.reduce((n, j) => n + (j.clip_count || 0), 0))} hint="Across your projects" /><Metric label="Engagement rate" value="—" hint="No channel connected" /></div><div className="chart-panel"><h2>Performance overview</h2><div className="chart-placeholder"><span>No publishing data yet</span></div></div></section>}
      {tab === 'campaigns' && <section className="new-page"><PageTitle title="Campaigns" sub="Organize videos for every channel and campaign" /><div className="empty-panel"><div className="empty-icon">▤</div><h2>No campaigns yet</h2><p>Create a campaign to group clips by launch, client or channel.</p><button className="new-primary">＋ New campaign</button></div></section>}
      {tab === 'integrations' && <section className="new-page"><PageTitle title="API integrations" sub="Connect the tools you use to publish and automate" /><div className="integration-grid">{[['YouTube','▶','Import videos and publish clips'],['Instagram','◎','Publish reels automatically'],['TikTok','♪','Send clips to your content calendar'],['Webhooks','⌁','Trigger your own workflows']].map(x => <div className="integration-card"><span>{x[1]}</span><h3>{x[0]}</h3><p>{x[2]}</p><button className="new-secondary">Connect</button></div>)}</div></section>}
      {tab === 'calendar' && <section className="new-page"><PageTitle title="Content calendar" sub="Plan and schedule your next clips" /><div className="calendar-panel"><div className="calendar-head"><button>‹</button><h2>September 2026</h2><button>›</button></div><div className="calendar-grid">{['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(d => <b>{d}</b>)}{Array.from({length:35}, (_,i) => <div className={i === 14 ? 'today' : ''}><small>{(i % 30) + 1}</small>{i === 14 && <span>＋ Add post</span>}</div>)}</div></div></section>}
    </main>
  </div>
}

function PageTitle({ title, sub }: { title: string, sub: string }) { return <div className="new-page-title"><div><h1>{title}</h1><p>{sub}</p></div><button className="new-primary">＋ Create</button></div> }
function Metric({ label, value, hint }: { label: string, value: string, hint: string }) { return <div className="metric-card"><small>{label}</small><strong>{value}</strong><span>{hint}</span></div> }
function fmtDuration(value?: number | null) { if (!value || value < 1) return '—'; const h = Math.floor(value / 3600); const m = Math.floor((value % 3600) / 60); const s = Math.floor(value % 60); return h ? `${h}h ${m}m` : `${m}m ${String(s).padStart(2, '0')}s` }
function ProjectGrid({ jobs, onOpenJob, large = false }: { jobs: JobSummary[], onOpenJob: (id: string) => void, large?: boolean }) { return <div className={`project-grid ${large ? 'large' : ''}`}>{jobs.length ? jobs.map(job => <button className="project-card" key={job.id} onClick={() => onOpenJob(job.id)}><div className="project-thumb" style={job.thumbnail_url ? { backgroundImage: `linear-gradient(180deg, transparent 35%, #151621cc), url("${job.thumbnail_url}")` } : undefined}><span>▶</span><label>{job.clip_count || 0} clips</label></div><div className="project-info"><b>{job.title || 'Untitled project'}</b><small><span>{fmtDuration(job.duration_sec)} video</span><span> · </span><span>{job.rendered ? 'Ready to view' : 'Processing'}</span></small></div></button>) : <div className="empty-projects">Your generated videos will appear here.</div>}</div> }
