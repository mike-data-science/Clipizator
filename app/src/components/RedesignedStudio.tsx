import { useEffect, useState } from 'react'
import type { JobSummary, Campaign } from '../types'
import type { GenerationConfig } from '../types'
import { api } from '../api'
import CreativeSetup from './CreativeSetupV2'

type Tab = 'home' | 'analytics' | 'integrations' | 'calendar' | 'clips' | 'campaigns' | 'analyzer'

interface Props {
  jobs: JobSummary[]
  running: boolean
  error: string | null
  stages: Record<string, { fraction: number; message: string }>
  activeJobId: string | null
  activeStage: string | null
  initialSource?: string
  onRun: (source: string, llm: string, geminiModel: string, captions: string, asrModel: string, captionColor: string, generationConfig: GenerationConfig) => void | Promise<unknown>
  onUpload: (file: File, llm: string, geminiModel: string, captions: string, asrModel: string, generationConfig: GenerationConfig) => void | Promise<unknown>
  onOpenJob: (id: string) => void
  onDeleteJobs: (ids: string[]) => Promise<void>
  onOpenLoop: () => void
  onOpenQueue: () => void
  onOpenTranscribeQueue: () => void
  onOpenAnalyzer: () => void
}

export default function RedesignedStudio({ jobs, running, error, stages, activeJobId, activeStage, initialSource, onRun, onUpload, onOpenJob, onDeleteJobs, onOpenLoop, onOpenQueue, onOpenTranscribeQueue, onOpenAnalyzer }: Props) {
  const [tab, setTab] = useState<Tab>('home')
  const [source, setSource] = useState(initialSource || '')
  const [showUpload, setShowUpload] = useState(false)
  const [showMagicModal, setShowMagicModal] = useState(false)
  const [showCreativeSetup, setShowCreativeSetup] = useState(false)
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [search, setSearch] = useState('')
  const [filterType, setFilterType] = useState('All')
  const [filterStatus, setFilterStatus] = useState('All')
  const [filterActive, setFilterActive] = useState('All')
  const [sortOrder, setSortOrder] = useState('Newest')
  const [openDropdown, setOpenDropdown] = useState<string | null>(null)
  const [selectingProjects, setSelectingProjects] = useState(false)
  const [selectedProjectIds, setSelectedProjectIds] = useState<Set<string>>(new Set())
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [, setCampaignLoading] = useState(false)
  const loadCampaigns = async () => { setCampaignLoading(true); try { setCampaigns(await api.listCampaigns()) } catch { setCampaigns([]) } finally { setCampaignLoading(false) } }
  useEffect(() => { if (initialSource) setSource(initialSource) }, [initialSource])
  useEffect(() => { if (tab === 'campaigns' && !campaigns.length) void loadCampaigns() }, [tab])
  const getGreeting = () => { const hour = new Date().getHours(); if (hour < 12) return 'Good Morning'; if (hour < 18) return 'Good Afternoon'; return 'Good Evening'; };
  const nav = [
    ['home', <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>, 'Home'], 
    ['analytics', <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="M18 20V10"></path><path d="M12 20V4"></path><path d="M6 20v-6"></path></svg>, 'Analytics'], 
    ['integrations', <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="5 12 12 5 19 12"></polyline></svg>, 'API & Integrations'],
    ['calendar', <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>, 'Calendar'], 
    ['clips', <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"></rect><line x1="7" y1="2" x2="7" y2="22"></line><line x1="17" y1="2" x2="17" y2="22"></line><line x1="2" y1="12" x2="22" y2="12"></line><line x1="2" y1="7" x2="7" y2="7"></line><line x1="2" y1="17" x2="7" y2="17"></line><line x1="17" y1="17" x2="22" y2="17"></line><line x1="17" y1="7" x2="22" y2="7"></line></svg>, 'Clips'], 
    ['campaigns', <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="M4 22h14a2 2 0 0 0 2-2V7.5L14.5 2H6a2 2 0 0 0-2 2v4"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M3 15h6"></path><path d="M6 12v6"></path></svg>, 'Campaigns'],
    ['analyzer', <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19V9"/><path d="M9 19V5"/><path d="M14 19v-7"/><path d="M19 19V3"/></svg>, 'Analyzer']
  ] as const
  const submit = () => { if (source.trim()) { setShowMagicModal(false); setShowCreativeSetup(true) } }
  const beginUpload = (file: File) => { setPendingFile(file); setShowMagicModal(false); setShowCreativeSetup(true) }
  const processWithSetup = async (generationConfig: GenerationConfig) => {
    if (pendingFile) {
      await onUpload(pendingFile, 'ollama', 'gemini-3.7-flash', 'hormozi', 'large-v3-turbo', generationConfig)
      setPendingFile(null)
    } else {
      await onRun(source.trim(), 'ollama', 'gemini-3.7-flash', 'hormozi', 'large-v3-turbo', String(generationConfig.captions?.fill || 'white'), generationConfig)
    }
    setShowCreativeSetup(false)
  }
  const toggleProject = (id: string) => setSelectedProjectIds((current) => {
    const next = new Set(current)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })
  const deleteSelectedProjects = async () => {
    const ids = [...selectedProjectIds]
    if (!ids.length || !confirm(`Delete ${ids.length} selected project${ids.length === 1 ? '' : 's'}? This cannot be undone.`)) return
    try {
      await onDeleteJobs(ids)
      setSelectedProjectIds(new Set())
      setSelectingProjects(false)
    } catch (deleteError) {
      alert(deleteError instanceof Error ? deleteError.message : 'Could not delete selected projects.')
    }
  }

  if (showCreativeSetup) {
    return <CreativeSetup source={source} file={pendingFile} onBack={() => { setShowCreativeSetup(false); setPendingFile(null) }} onProcess={processWithSetup} />
  }

  return <div className="new-shell">
    <aside className="new-sidebar">
      <div className="new-brand"><span className="new-brand-mark">✦</span><span>clipizator</span></div>
      <nav className="new-nav" style={{ marginTop: '10px' }}>{nav.map(([id, icon, label]) => <button key={id} className={tab === id ? 'active' : ''} style={{ display: 'flex', alignItems: 'center', gap: '10px' }} onClick={() => id === 'analyzer' ? onOpenAnalyzer() : setTab(id as Tab)}><i style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{icon}</i>{label}</button>)}</nav>
      <div className="new-sidebar-spacer" />
      <div className="new-tools-label">WORKSPACE</div>
      <button className="new-nav-tool" onClick={onOpenLoop} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"></line></svg> Instagram loop</button>
      <button className="new-nav-tool" onClick={onOpenQueue} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg> Download queue</button>
      <button className="new-nav-tool" onClick={onOpenTranscribeQueue} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}><svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg> Transcribe queue</button>
      <div className="new-user"><span className="new-avatar">M</span><span><b>Mike</b><small>Personal workspace</small></span><span>⋯</span></div>
    </aside>
    <main className="new-main">
      <header className="new-topbar"><div className="new-breadcrumb">Workspace <span>/</span> {nav.find(n => n[0] === tab)?.[2]}</div><div className="new-top-actions"><button>⌕</button><button>?</button><button className="new-upgrade">Upgrade</button></div></header>
      {tab === 'home' && <section className="new-page new-home" style={{ paddingTop: '24px' }}>
        {running && <div role="status" style={{ marginBottom: '16px', padding: '12px 16px', borderRadius: '10px', background: '#f0edff', color: '#5b3fd1', fontSize: '13px', fontWeight: 600 }}>Starting processing… Your project will appear here as it progresses.</div>}
        {error && <div role="alert" style={{ marginBottom: '16px', padding: '12px 16px', borderRadius: '10px', background: '#fff1f2', color: '#be123c', fontSize: '13px' }}>{error}</div>}

        {/* === Magic Clips Modal === */}
        {showMagicModal && <div style={{ position: 'fixed', inset: 0, zIndex: 200, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowMagicModal(false)}>
          <div style={{ background: '#fff', borderRadius: '16px', padding: '32px', width: '500px', maxWidth: '90vw', boxShadow: '0 24px 60px rgba(0,0,0,0.18)' }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
              <h2 style={{ fontSize: '18px', fontWeight: 700, margin: 0 }}>Magic Clips</h2>
              <button style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: '20px', color: '#999', lineHeight: 1 }} onClick={() => setShowMagicModal(false)}>×</button>
            </div>
            <p style={{ fontSize: '13px', color: '#898b95', marginBottom: '20px', lineHeight: 1.5 }}>Get shorts from long video, perfect for podcasts</p>
            <input value={source} onChange={e => setSource(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { submit(); setShowMagicModal(false) } }} placeholder="Paste a video URL to get started..." style={{ width: '100%', padding: '12px 14px', border: '1px solid #dfdee6', borderRadius: '8px', fontSize: '14px', outline: 'none', marginBottom: '12px' }} disabled={running} autoFocus />
            <div style={{ display: 'flex', gap: '10px' }}>
              <button className="new-primary" style={{ flex: 1, padding: '11px' }} onClick={() => { submit(); setShowMagicModal(false) }} disabled={running || !source.trim()}>{running ? 'Processing…' : 'Create clips'}</button>
              <button className="new-secondary" style={{ margin: 0 }} onClick={() => { setShowUpload(true); setShowMagicModal(false) }}>Upload file</button>
            </div>
          </div>
        </div>}
        {showUpload && <input className="new-file" type="file" accept="video/*" autoFocus onChange={e => { const f = e.target.files?.[0]; if (f) beginUpload(f); setShowUpload(false) }} />}

        {/* === Greeting + Service cards === */}
        <div style={{ marginBottom: '28px' }}>
          <h1 style={{ fontSize: '28px', marginBottom: '20px', letterSpacing: '-0.02em', fontWeight: 700 }}>{getGreeting()}</h1>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '14px' }}>
            <div style={{ padding: '18px 20px', background: '#fff', borderRadius: '12px', border: '1px solid #e4e3ea', boxShadow: '0 2px 8px rgba(0,0,0,0.04)', cursor: 'pointer', transition: 'box-shadow 0.15s, transform 0.15s' }} onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.boxShadow = '0 6px 20px rgba(0,0,0,0.09)'; (e.currentTarget as HTMLDivElement).style.transform = 'translateY(-2px)' }} onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.boxShadow = '0 2px 8px rgba(0,0,0,0.04)'; (e.currentTarget as HTMLDivElement).style.transform = '' }}>
              <h3 style={{ fontSize: '14px', marginBottom: '5px', fontWeight: 600 }}>Generate Captions</h3>
              <p style={{ fontSize: '12px', color: '#898b95', margin: 0, lineHeight: 1.4 }}>Get trendy AI captions in just one click</p>
            </div>
            <div style={{ padding: '18px 20px', background: '#fff', borderRadius: '12px', border: '1px solid #e4e3ea', boxShadow: '0 2px 8px rgba(0,0,0,0.04)', cursor: 'pointer', transition: 'box-shadow 0.15s, transform 0.15s' }} onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.boxShadow = '0 6px 20px rgba(0,0,0,0.09)'; (e.currentTarget as HTMLDivElement).style.transform = 'translateY(-2px)' }} onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.boxShadow = '0 2px 8px rgba(0,0,0,0.04)'; (e.currentTarget as HTMLDivElement).style.transform = '' }}>
              <h3 style={{ fontSize: '14px', marginBottom: '5px', fontWeight: 600 }}>AI Auto Edits</h3>
              <p style={{ fontSize: '12px', color: '#898b95', margin: 0, lineHeight: 1.4 }}>Choose a video template, AI will do the rest</p>
            </div>
            <div style={{ padding: '18px 20px', background: '#fff', borderRadius: '12px', border: '1px solid #e4e3ea', boxShadow: '0 2px 8px rgba(0,0,0,0.04)', cursor: 'pointer', transition: 'box-shadow 0.15s, transform 0.15s' }} onClick={() => setShowMagicModal(true)} onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.boxShadow = '0 6px 20px rgba(108,77,246,0.15)'; (e.currentTarget as HTMLDivElement).style.transform = 'translateY(-2px)' }} onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.boxShadow = '0 2px 8px rgba(0,0,0,0.04)'; (e.currentTarget as HTMLDivElement).style.transform = '' }}>
              <h3 style={{ fontSize: '14px', marginBottom: '5px', fontWeight: 600 }}>Magic Clips</h3>
              <p style={{ fontSize: '12px', color: '#898b95', margin: 0, lineHeight: 1.4 }}>Get shorts from long video, perfect for podcasts</p>
            </div>
          </div>
        </div>

        {/* === Projects toolbar === */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px', flexWrap: 'wrap' }} onClick={() => setOpenDropdown(null)}>
          <h2 style={{ fontSize: '18px', fontWeight: 700, margin: 0, marginRight: '4px' }}>Projects</h2>
          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <svg style={{ position: 'absolute', left: '10px', pointerEvents: 'none', color: '#999' }} viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" strokeWidth="2" fill="none"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search..." style={{ padding: '7px 10px 7px 30px', border: '1px solid #e2e1e8', borderRadius: '7px', fontSize: '12px', outline: 'none', width: '160px', background: '#fff', color: '#333' }} />
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: '6px', alignItems: 'center' }}>
            {/* Type dropdown */}
            <div style={{ position: 'relative' }} onClick={e => e.stopPropagation()}>
              <button onClick={() => setOpenDropdown(openDropdown === 'type' ? null : 'type')} style={{ padding: '6px 11px', border: '1px solid ' + (filterType !== 'All' ? '#6c4df6' : '#e2e1e8'), borderRadius: '7px', background: filterType !== 'All' ? '#f0edff' : '#fff', fontSize: '12px', color: filterType !== 'All' ? '#6c4df6' : '#555', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: filterType !== 'All' ? 600 : 400 }}>Type: {filterType} <span style={{ fontSize: '9px' }}>▾</span></button>
              {openDropdown === 'type' && <div style={{ position: 'absolute', top: '34px', right: 0, zIndex: 50, background: '#fff', border: '1px solid #e2e1e8', borderRadius: '9px', boxShadow: '0 8px 24px rgba(0,0,0,0.1)', minWidth: '130px', overflow: 'hidden' }}>
                {['All', 'Clips', 'Full'].map(o => <button key={o} onClick={() => { setFilterType(o); setOpenDropdown(null) }} style={{ display: 'block', width: '100%', padding: '9px 14px', border: 'none', background: filterType === o ? '#f0edff' : 'transparent', color: filterType === o ? '#6c4df6' : '#333', fontSize: '12px', textAlign: 'left', cursor: 'pointer', fontWeight: filterType === o ? 600 : 400 }}>{o}</button>)}
              </div>}
            </div>
            {/* Status dropdown */}
            <div style={{ position: 'relative' }} onClick={e => e.stopPropagation()}>
              <button onClick={() => setOpenDropdown(openDropdown === 'status' ? null : 'status')} style={{ padding: '6px 11px', border: '1px solid ' + (filterStatus !== 'All' ? '#6c4df6' : '#e2e1e8'), borderRadius: '7px', background: filterStatus !== 'All' ? '#f0edff' : '#fff', fontSize: '12px', color: filterStatus !== 'All' ? '#6c4df6' : '#555', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: filterStatus !== 'All' ? 600 : 400 }}>Status: {filterStatus} <span style={{ fontSize: '9px' }}>▾</span></button>
              {openDropdown === 'status' && <div style={{ position: 'absolute', top: '34px', right: 0, zIndex: 50, background: '#fff', border: '1px solid #e2e1e8', borderRadius: '9px', boxShadow: '0 8px 24px rgba(0,0,0,0.1)', minWidth: '155px', overflow: 'hidden' }}>
                {['All', 'Completed', 'Not Completed'].map(o => <button key={o} onClick={() => { setFilterStatus(o); setOpenDropdown(null) }} style={{ display: 'block', width: '100%', padding: '9px 14px', border: 'none', background: filterStatus === o ? '#f0edff' : 'transparent', color: filterStatus === o ? '#6c4df6' : '#333', fontSize: '12px', textAlign: 'left', cursor: 'pointer', fontWeight: filterStatus === o ? 600 : 400 }}>{o}</button>)}
              </div>}
            </div>
            {/* Active dropdown */}
            <div style={{ position: 'relative' }} onClick={e => e.stopPropagation()}>
              <button onClick={() => setOpenDropdown(openDropdown === 'active' ? null : 'active')} style={{ padding: '6px 11px', border: '1px solid ' + (filterActive !== 'All' ? '#6c4df6' : '#e2e1e8'), borderRadius: '7px', background: filterActive !== 'All' ? '#f0edff' : '#fff', fontSize: '12px', color: filterActive !== 'All' ? '#6c4df6' : '#555', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: filterActive !== 'All' ? 600 : 400 }}>{filterActive === 'All' ? 'Active' : filterActive} <span style={{ fontSize: '9px' }}>▾</span></button>
              {openDropdown === 'active' && <div style={{ position: 'absolute', top: '34px', right: 0, zIndex: 50, background: '#fff', border: '1px solid #e2e1e8', borderRadius: '9px', boxShadow: '0 8px 24px rgba(0,0,0,0.1)', minWidth: '130px', overflow: 'hidden' }}>
                {['All', 'Active', 'Archived'].map(o => <button key={o} onClick={() => { setFilterActive(o); setOpenDropdown(null) }} style={{ display: 'block', width: '100%', padding: '9px 14px', border: 'none', background: filterActive === o ? '#f0edff' : 'transparent', color: filterActive === o ? '#6c4df6' : '#333', fontSize: '12px', textAlign: 'left', cursor: 'pointer', fontWeight: filterActive === o ? 600 : 400 }}>{o}</button>)}
              </div>}
            </div>
            {/* Sort dropdown */}
            <div style={{ position: 'relative' }} onClick={e => e.stopPropagation()}>
              <button onClick={() => setOpenDropdown(openDropdown === 'sort' ? null : 'sort')} style={{ padding: '6px 11px', border: '1px solid #e2e1e8', borderRadius: '7px', background: '#fff', fontSize: '12px', color: '#555', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}>{sortOrder} <span style={{ fontSize: '9px' }}>▾</span></button>
              {openDropdown === 'sort' && <div style={{ position: 'absolute', top: '34px', right: 0, zIndex: 50, background: '#fff', border: '1px solid #e2e1e8', borderRadius: '9px', boxShadow: '0 8px 24px rgba(0,0,0,0.1)', minWidth: '120px', overflow: 'hidden' }}>
                {['Newest', 'Oldest'].map(o => <button key={o} onClick={() => { setSortOrder(o); setOpenDropdown(null) }} style={{ display: 'block', width: '100%', padding: '9px 14px', border: 'none', background: sortOrder === o ? '#f0edff' : 'transparent', color: sortOrder === o ? '#6c4df6' : '#333', fontSize: '12px', textAlign: 'left', cursor: 'pointer', fontWeight: sortOrder === o ? 600 : 400 }}>{o}</button>)}
              </div>}
            </div>
            {/* Grid button */}
            <button style={{ padding: '6px 11px', border: '1px solid #e2e1e8', borderRadius: '7px', background: '#fff', fontSize: '12px', color: '#555', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" strokeWidth="2" fill="none"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg> Grid
            </button>
            <button onClick={() => { setSelectingProjects((value) => !value); setSelectedProjectIds(new Set()) }} style={{ padding: '6px 11px', border: '1px solid #e2e1e8', borderRadius: '7px', background: selectingProjects ? '#f0edff' : '#fff', fontSize: '12px', color: selectingProjects ? '#6c4df6' : '#555', cursor: 'pointer', fontWeight: selectingProjects ? 600 : 400 }}>{selectingProjects ? 'Cancel selection' : 'Select projects'}</button>
            {selectingProjects && <button onClick={() => void deleteSelectedProjects()} disabled={!selectedProjectIds.size} style={{ padding: '6px 11px', border: '1px solid #fecdd3', borderRadius: '7px', background: selectedProjectIds.size ? '#fff1f2' : '#fff', fontSize: '12px', color: selectedProjectIds.size ? '#be123c' : '#aaa', cursor: selectedProjectIds.size ? 'pointer' : 'not-allowed', fontWeight: 600 }}>Delete selected{selectedProjectIds.size ? ` (${selectedProjectIds.size})` : ''}</button>}
          </div>
        </div>
        <ProjectGrid
          jobs={jobs
            .filter(j => !search || (j.title || '').toLowerCase().includes(search.toLowerCase()))
            .filter(j => filterStatus === 'All' ? true : filterStatus === 'Completed' ? (j.completed || j.rendered) : !(j.completed || j.rendered))
            .filter(j => filterType === 'All' ? true : filterType === 'Clips' ? (j.clip_count || 0) > 0 : (j.clip_count || 0) === 0)
            .sort((a, b) => sortOrder === 'Newest' ? (b.id > a.id ? 1 : -1) : (a.id > b.id ? 1 : -1))}
          onOpenJob={onOpenJob} stages={stages} activeJobId={activeJobId} activeStage={activeStage} selecting={selectingProjects} selectedIds={selectedProjectIds} onToggle={toggleProject} />
      </section>}
      {tab === 'clips' && <section className="new-page"><PageTitle title="Your clips" sub="All finished clips from your projects" /><ProjectGrid jobs={jobs} onOpenJob={onOpenJob} stages={stages} activeJobId={activeJobId} activeStage={activeStage} large /></section>}
      {tab === 'analytics' && <section className="new-page"><PageTitle title="Analytics" sub="Understand what is working across your content" /><div className="metrics-grid"><Metric label="Total views" value="—" hint="Connect a channel to see data" /><Metric label="Clips published" value={String(jobs.reduce((n, j) => n + (j.clip_count || 0), 0))} hint="Across your projects" /><Metric label="Engagement rate" value="—" hint="No channel connected" /></div><div className="chart-panel"><h2>Performance overview</h2><div className="chart-placeholder"><span>No publishing data yet</span></div></div></section>}
      {tab === 'campaigns' && <section className="new-page"><PageTitle title="Campaigns" sub="Organize videos for every channel and campaign" /><div className="empty-panel"><div className="empty-icon">▤</div><h2>No campaigns yet</h2><p>Create a campaign to group clips by launch, client or channel.</p><button className="new-primary">＋ New campaign</button></div></section>}
      {tab === 'integrations' && <section className="new-page"><PageTitle title="API integrations" sub="Connect the tools you use to publish and automate" /><div className="integration-grid">{[['YouTube','▶','Import videos and publish clips'],['Instagram','◎','Publish reels automatically'],['TikTok','♪','Send clips to your content calendar'],['Webhooks','⌁','Trigger your own workflows']].map(x => <div className="integration-card"><span>{x[1]}</span><h3>{x[0]}</h3><p>{x[2]}</p><button className="new-secondary">Connect</button></div>)}</div></section>}
      {tab === 'calendar' && <section className="new-page"><PageTitle title="Content calendar" sub="Plan and schedule your next clips" /><div className="calendar-panel"><div className="calendar-head"><button>‹</button><h2>September 2026</h2><button>›</button></div><div className="calendar-grid">{['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(d => <b>{d}</b>)}{Array.from({length:35}, (_,i) => <div className={i === 14 ? 'today' : ''}><small>{(i % 30) + 1}</small>{i === 14 && <span>＋ Add post</span>}</div>)}</div></div></section>}
    </main>
  </div>
}

function PageTitle({ title, sub }: { title: string, sub: string }) { return <div className="new-page-title"><div><h1>{title}</h1><p>{sub}</p></div><button className="new-primary">＋ Create</button></div> }
function Metric({ label, value, hint }: { label: string, value: string, hint: string }) { return <div className="metric-card"><small>{label}</small><strong>{value}</strong><span>{hint}</span></div> }
function fmtDuration(value?: number | null): string {
  if (!value || value < 1) return '';
  const h = Math.floor(value / 3600);
  const m = Math.floor((value % 3600) / 60);
  const s = Math.floor(value % 60);
  if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}
function qualityBadge(job: JobSummary): string {
  const d = job.duration_sec || 0;
  if (d > 3600) return '4K';
  if (d > 600) return 'HD';
  return 'SD';
}
function stageLabel(stage?: string | null, pipelineStages: Array<{ id: string; label: string }> = []) {
  if (stage === 'complete') return 'Complete'
  if (stage === 'worker_queued') return 'Waiting for local downloader'
  if (stage === 'downloading') return 'Downloading'
  if (stage === 'uploading') return 'Uploading source'
  return pipelineStages.find((item) => item.id === stage)?.label || stage || 'Waiting to start'
}

function ProjectGrid({ jobs, onOpenJob, stages, activeJobId, activeStage: liveStageName, selecting = false, selectedIds = new Set<string>(), onToggle, large = false }: { jobs: JobSummary[], onOpenJob: (id: string) => void, stages: Record<string, { fraction: number; message: string }>, activeJobId: string | null, activeStage: string | null, selecting?: boolean, selectedIds?: Set<string>, onToggle?: (id: string) => void, large?: boolean }) {
  return <div className={`project-grid ${large ? 'large' : ''}`}>{jobs.length ? jobs.map(job => {
    const dur = fmtDuration(job.duration_sec);
    const quality = qualityBadge(job);
    const qColor = quality === '4K' ? '#a855f7' : quality === 'HD' ? '#10b981' : '#6b7280';
    const activeStage = job.id === activeJobId && liveStageName ? liveStageName : job.current_stage;
    const pipelineStages = job.pipeline_stages || [];
    const liveStage = job.id === activeJobId && activeStage ? stages[activeStage] : undefined;
    const activeFraction = liveStage?.fraction ?? job.stage_progress;
    const completedStages = new Set(job.completed_stages || []);
    const isComplete = job.completed || job.status === 'done';
    const isFailed = job.status === 'failed';
    const isActive = !isComplete && !isFailed;
    const statusColor = isComplete ? '#10b981' : isFailed ? '#e11d48' : '#f59e0b';
    const canDelete = !isActive;
    const selected = selectedIds.has(job.id);
    return <button className="project-card" key={job.id} title={selecting && !canDelete ? 'Active projects cannot be deleted' : undefined} onClick={() => selecting ? (canDelete && onToggle?.(job.id)) : onOpenJob(job.id)} style={selecting ? { outline: selected ? '2px solid #6c4df6' : '1px solid #e2e1e8', outlineOffset: '-1px', opacity: canDelete ? 1 : 0.62, cursor: canDelete ? 'pointer' : 'not-allowed' } : undefined}>
      <div className="project-thumb" style={job.thumbnail_url ? { backgroundImage: `linear-gradient(180deg, rgba(0,0,0,0.55) 0%, transparent 40%, transparent 55%, rgba(0,0,0,0.72) 100%), url("${job.thumbnail_url}")` } : { background: 'linear-gradient(135deg,#29283a,#7770a1)' }}>
        {selecting && <span style={{ position:'absolute', top:'8px', left:'8px', width:'18px', height:'18px', borderRadius:'50%', background: selected ? '#6c4df6' : '#fff', color: selected ? '#fff' : '#aaa', display:'grid', placeItems:'center', fontSize:'12px', fontWeight:700 }}>{selected ? '✓' : ''}</span>}
        {/* Top-left: clip count */}
        {(job.clip_count || 0) > 0 && <span style={{ position:'absolute', top:'8px', left:'8px', padding:'3px 8px', borderRadius:'5px', background:'rgba(108,77,246,0.92)', color:'#fff', fontSize:'10px', fontWeight:700, backdropFilter:'blur(4px)' }}>+{job.clip_count} Clips</span>}
        {/* Top-right: quality badge */}
        <span style={{ position:'absolute', top:'8px', right:'8px', padding:'3px 7px', borderRadius:'5px', background: isActive ? '#6c4df6' : isFailed ? '#e11d48' : qColor, color:'#fff', fontSize:'9px', fontWeight:800, letterSpacing:'0.04em' }}>{isActive ? 'PROCESSING' : isFailed ? 'FAILED' : quality}</span>
        {/* Center play */}
        <span style={{ position:'absolute', inset:0, display:'flex', alignItems:'center', justifyContent:'center', fontSize:'20px', color:'rgba(255,255,255,0.7)' }}>{isActive ? '◌' : '▶'}</span>
        {/* Bottom: title + duration */}
        <div style={{ position:'absolute', bottom:0, left:0, right:0, padding:'8px 9px 7px', display:'flex', alignItems:'flex-end', justifyContent:'space-between', gap:'6px' }}>
          <span style={{ fontSize:'11px', color:'#fff', fontWeight:600, lineHeight:1.3, overflow:'hidden', display:'-webkit-box', WebkitBoxOrient:'vertical', WebkitLineClamp:2, textShadow:'0 1px 4px rgba(0,0,0,0.6)' }}>{job.title || 'Untitled project'}</span>
          {dur && <span style={{ flexShrink:0, padding:'2px 6px', borderRadius:'4px', background:'rgba(0,0,0,0.65)', color:'#fff', fontSize:'10px', fontWeight:600, fontVariantNumeric:'tabular-nums' }}>{dur}</span>}
        </div>
      </div>
      <div className="project-info" style={{ padding:'8px 10px 10px', display:'flex', alignItems:'center', justifyContent:'space-between' }}>
        <span style={{ fontSize:'10px', color: statusColor, fontWeight:600, display:'flex', alignItems:'center', gap:'4px' }}>
          <span style={{ width:'6px', height:'6px', borderRadius:'50%', background: statusColor, display:'inline-block' }} />
          {isComplete ? 'Completed' : isFailed ? `Failed · ${stageLabel(activeStage, pipelineStages)}` : stageLabel(activeStage, pipelineStages)}
        </span>
        {isComplete && <span style={{ fontSize:'10px', color:'#9a9ba4' }}>{job.clip_count} clips</span>}
      </div>
      {isActive && <div style={{ padding:'0 10px 10px', textAlign:'left' }}>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', fontSize:'10px', color:'#6c4df6', marginBottom:'6px' }}><span>{liveStage?.message || stageLabel(activeStage, pipelineStages)}</span>{typeof activeFraction === 'number' && activeFraction >= 0 && <b>{Math.round(activeFraction * 100)}%</b>}</div>
        <div style={{ display:'flex', gap:'3px', flexWrap:'wrap' }}>{pipelineStages.map(({ id, label }) => <span key={id} title={label} style={{ width:'7px', height:'7px', borderRadius:'50%', background: completedStages.has(id) ? '#10b981' : activeStage === id ? '#6c4df6' : '#e4e3ea' }} />)}</div>
      </div>}
      {isFailed && job.error && <div style={{ padding:'0 10px 10px', color:'#be123c', fontSize:'10px', textAlign:'left', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{job.error}</div>}
    </button>
  }) : <div className="empty-projects">Your generated videos will appear here.</div>}
  </div>
}
