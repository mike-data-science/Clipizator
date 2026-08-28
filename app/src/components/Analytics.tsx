import { useEffect, useState } from 'react'
import { api, listen } from '../api'
import type { Campaign, CampaignFull, CampaignMoment } from '../types'

function formatResolution(width?: number, height?: number): string {
  if (!width || !height) return 'Not probed'
  let label = `${height}p`
  if (width >= 3840 || height >= 2160) label = '4K'
  else if (width >= 2560 || height >= 1440) label = '2K'
  return `${label} (${width} × ${height})`
}

export function Analytics({ onBack, onSendToStudio }: { onBack: () => void, onSendToStudio?: (url: string) => void }) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [campaign, setCampaign] = useState<CampaignFull | null>(null)
  const [loading, setLoading] = useState(false)
  
  // Create state
  const [showAddModal, setShowAddModal] = useState(false)
  const [newName, setNewName] = useState('')
  const [newReward, setNewReward] = useState('')
  const [newRules, setNewRules] = useState('')
  const [newVideos, setNewVideos] = useState('')
  // Unified Add Media state
  const [showAddMediaModal, setShowAddMediaModal] = useState(false)
  const [addMediaType, setAddMediaType] = useState<'source' | 'mine' | 'competitor' | 'hashtag'>('source')
  const [addMediaUrls, setAddMediaUrls] = useState('')
  const [addMediaHashtag, setAddMediaHashtag] = useState('')
  const [addMediaSettings, setAddMediaSettings] = useState({
    download: true,
    transcribe: true,
    analyze: true
  })
  const [selectedClip, setSelectedClip] = useState<any>(null)
  const [selectedVideo, setSelectedVideo] = useState<any>(null)
  const [refreshingVideoId, setRefreshingVideoId] = useState<number | null>(null)
  
  // Video filter state
  const [videoFilter, setVideoFilter] = useState<'all' | 'source' | 'mine' | 'competitor'>('all')
  const [_csvUploading, _setCsvUploading] = useState(false)
  void _csvUploading; void _setCsvUploading;
  
  // Extraction progress state
  const [extractMsg, setExtractMsg] = useState<string | null>(null)
  const [analyzeMsg, setAnalyzeMsg] = useState<string | null>(null)
  const [clipAnalysisMsg, setClipAnalysisMsg] = useState<string | null>(null)

  const [_transcripts, _setTranscripts] = useState<any[]>([])
  const [_expandedVideoId, _setExpandedVideoId] = useState<number | null>(null)
  const [_expandedClipId, _setExpandedClipId] = useState<number | null>(null)
  void _transcripts; void _setTranscripts; void _expandedVideoId; void _setExpandedVideoId; void _expandedClipId; void _setExpandedClipId;
  
  // Analyzer AI state
  const [videoRanking, setVideoRanking] = useState<any[]>([])
  const [hookRecs, setHookRecs] = useState<any>(null)
  const [insights, setInsights] = useState<{ feedback?: { total: number; approvals: number; rejections: number; net: number } } | null>(null)
  const [selectedMatchVideo, setSelectedMatchVideo] = useState<any>(null)
  const [competitorMatches, setCompetitorMatches] = useState<any[]>([])
  const [improvingHookFor, setImprovingHookFor] = useState<number | null>(null)
  const [improvedHooks, setImprovedHooks] = useState<Record<number, { visual_hooks: string[], audio_hooks: string[] }>>({})
  
  // Social Hub state
  const [igData, setIgData] = useState<{ connected: boolean, username?: string | null, error?: string, clips?: any[] }>({ connected: false })
  const [igAppId, setIgAppId] = useState('')
  const [igAppSecret, setIgAppSecret] = useState('')

  const [_selectedVideoUrls] = useState<Set<string>>(new Set())
  void _selectedVideoUrls;
  const [activeTab, setActiveTab] = useState<'overview' | 'videos' | 'social'>('overview')

  useEffect(() => {
    loadCampaigns()
  }, [])

  useEffect(() => {
    if (activeId) {
      loadCampaign(activeId)
      
      // Listen for background pipeline events for this campaign
      let unlisten: (() => void) | undefined
      let disposed = false
      
      listen('pipeline-event', ({ payload }: any) => {
        if (payload.campaign_id === activeId) {
          if (payload.stage === 'transcripts') {
            if (payload.event === 'progress') {
              setExtractMsg(payload.message)
            } else if (payload.event === 'result') {
              setExtractMsg(null)
              loadCampaign(activeId)
            }
          } else if (payload.stage === 'analysis') {
            if (payload.event === 'progress') {
              setAnalyzeMsg(payload.message)
            } else if (payload.event === 'result') {
              setAnalyzeMsg(null)
              loadCampaign(activeId)
            }
          } else if (payload.stage === 'analysis_prepared') {
            if (payload.event === 'result') {
              setAnalyzeMsg(payload.message)
            }
          } else if (payload.stage === 'clip_analysis') {
            if (payload.event === 'progress') {
              setClipAnalysisMsg(payload.message)
            } else if (payload.event === 'result') {
              setClipAnalysisMsg(null)
              if (!payload.ok) {
                alert("Error analyzing clip: " + payload.error)
              }
              loadCampaign(activeId)
            }
          } else if (payload.stage === 'clip_analysis_started') {
            loadCampaign(activeId)
          }
        }
      }).then(un => {
        if (disposed) un()
        else unlisten = un
      })
      
      return () => {
        disposed = true
        unlisten?.()
      }
    }
  }, [activeId])

  async function loadCampaigns() {
    try {
      const data = await api.listCampaigns()
      setCampaigns(data)
    } catch (err) {
      console.error('Failed to load campaigns:', err)
    }
  }

  async function loadCampaign(id: string) {
    setLoading(true)
    try {
      const data = await api.getCampaign(id)
      setCampaign(data)
      
      // Fetch transcripts in the background for displaying them
      api.getCampaignTranscripts(id).then(_setTranscripts).catch(console.error)
      // Fetch analyzer data
      api.getVideoRanking(id).then(setVideoRanking).catch(console.error)
      api.getHookRecommendations(id).then(setHookRecs).catch(console.error)
      api.getCampaignInsights(id).then(setInsights).catch(console.error)
      
    } catch (err) {
      console.error('Failed to load campaign:', err)
    } finally {
      setLoading(false)
    }
  }

  async function loadCompetitorMatches(videoUrl: string) {
    if (!activeId) return
    setLoading(true)
    try {
      const data = await api.getCompetitorMatches(activeId, videoUrl)
      setCompetitorMatches(data)
      const v = campaign?.videos.find(x => x.video_url === videoUrl)
      setSelectedMatchVideo(v)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  async function refreshCampaignVideo(video: any) {
    if (!activeId || !video.id || !confirm('Re-download this source and rebuild all clips?')) return
    setRefreshingVideoId(video.id)
    try {
      await api.refreshCampaignVideo(activeId, video.id)
      alert('Source refresh and re-render started. Keep this campaign open to watch progress.')
      setSelectedVideo(null)
      loadCampaign(activeId)
    } catch (err) {
      alert('Could not refresh video: ' + err)
    } finally {
      setRefreshingVideoId(null)
    }
  }

  async function handleImproveHook(matchIndex: number, transcript: string, visualHook: string) {
    if (!activeId) return
    setImprovingHookFor(matchIndex)
    try {
      const res = await api.improveHook(activeId, transcript, visualHook || '')
      setImprovedHooks(prev => ({ ...prev, [matchIndex]: res }))
    } catch (err) {
      console.error(err)
    } finally {
      setImprovingHookFor(null)
    }
  }

  async function loadIgOverview() {
    try {
      const data = await api.igOverview()
      setIgData(data)
    } catch (err) {
      console.error(err)
    }
  }

  useEffect(() => {
    if (activeTab === 'social') {
      loadIgOverview()
    }
  }, [activeTab])

  async function handleIgConnect(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      await api.igConnect(igAppId, igAppSecret)
      await loadIgOverview()
    } catch (err) {
      console.error(err)
      alert("Failed to connect Instagram")
    } finally {
      setLoading(false)
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!newName.trim()) return
    try {
      setLoading(true)
      const c = await api.createCampaign(newName.trim(), newReward.trim(), newRules.trim())
      
      // If videos were provided, add them immediately
      if (newVideos.trim()) {
        const urls = newVideos.split(/[\s,]+/).filter(url => url.trim().length > 0)
        if (urls.length > 0) {
          await Promise.all(urls.map(url => api.addCampaignVideo(c.id, url.trim())))
        }
      }
      
      setNewName('')
      setNewReward('')
      setNewRules('')
      setNewVideos('')
      setShowAddModal(false)
      
      await loadCampaigns()
      setActiveId(c.id)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  async function handleAddMediaSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!addMediaUrls.trim() || !activeId) return
    
    const urls = addMediaUrls.split(/[\s,]+/).filter(url => url.trim().length > 0)
    if (urls.length === 0) return

    try {
      setLoading(true)
      
      if (addMediaType === 'hashtag') {
        const hashtag = addMediaHashtag.startsWith('#') ? addMediaHashtag : `#${addMediaHashtag}`
        await api.searchHashtag(activeId, hashtag)
        alert(`Started background search for ${hashtag}. Clips will appear in the Videos tab soon!`)
      } else if (addMediaType === 'source') {
        await Promise.all(urls.map(url => api.addCampaignVideo(activeId, url.trim())))
      } else {
        // Clips
        await Promise.all(urls.map(url => api.analyzeClip(activeId, url.trim(), addMediaType, addMediaSettings)))
      }
      
      setAddMediaUrls('')
      setAddMediaHashtag('')
      setShowAddMediaModal(false)
      await loadCampaign(activeId)
    } catch (err) {
      console.error('Error adding media:', err)
      alert("Failed to add media.")
    } finally {
      setLoading(false)
    }
  }

  async function handleCsvUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !activeId) return
    try {
      const res = await api.importAnalyticsCsv(activeId, file)
      alert(`Updated analytics for ${res.updated} clips!`)
      loadCampaign(activeId)
    } catch (err) {
      console.error(err)
      alert('Failed to import CSV')
    } finally {
      e.target.value = ''
    }
  }
  void handleCsvUpload;

  if (!activeId || !campaign) {
    return (
      <div className="analytics-layout" style={{ flexDirection: 'column', background: 'var(--bg)' }}>
        {/* Top Header */}
        <header style={{ padding: '24px 40px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--panel)', zIndex: 10 }}>
          <h1 style={{ margin: 0, fontSize: '24px', fontWeight: 700, letterSpacing: '-0.5px' }}>Campaigns</h1>
          <button 
            onClick={onBack} 
            style={{ padding: '8px 16px', background: 'var(--bg)', color: 'var(--fg)', border: '1px solid var(--border)', borderRadius: '20px', fontSize: '13px', cursor: 'pointer', fontWeight: 600, transition: 'all 0.2s' }}
            onMouseOver={e => e.currentTarget.style.background = 'var(--border)'}
            onMouseOut={e => e.currentTarget.style.background = 'var(--bg)'}
          >
            → Open Studio
          </button>
        </header>

        {/* Dashboard Grid */}
        <div style={{ flex: 1, padding: '40px', overflowY: 'auto' }}>
          
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '24px', maxWidth: '1200px', margin: '0 auto' }}>
            {/* Add New Campaign Card (Button) */}
            <div 
              onClick={() => setShowAddModal(true)}
              style={{
                background: 'rgba(255, 170, 0, 0.05)',
                border: '2px dashed rgba(255, 170, 0, 0.3)',
                borderRadius: '16px',
                padding: '32px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '16px',
                cursor: 'pointer',
                transition: 'all 0.3s ease',
                minHeight: '200px'
              }}
              onMouseOver={e => {
                e.currentTarget.style.background = 'rgba(255, 170, 0, 0.1)';
                e.currentTarget.style.borderColor = 'rgba(255, 170, 0, 0.6)';
                e.currentTarget.style.transform = 'translateY(-4px)';
              }}
              onMouseOut={e => {
                e.currentTarget.style.background = 'rgba(255, 170, 0, 0.05)';
                e.currentTarget.style.borderColor = 'rgba(255, 170, 0, 0.3)';
                e.currentTarget.style.transform = 'none';
              }}
            >
              <div style={{ width: '48px', height: '48px', borderRadius: '50%', background: 'var(--primary)', color: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '24px', fontWeight: 300 }}>+</div>
              <div style={{ fontWeight: 600, fontSize: '16px', color: 'var(--primary)' }}>Create Campaign</div>
            </div>

            {/* Campaign Cards */}
            {campaigns.map(c => (
              <div 
                key={c.id} 
                onClick={() => setActiveId(c.id)}
                style={{
                  background: 'var(--panel)',
                  border: '1px solid var(--border)',
                  borderRadius: '16px',
                  padding: '24px',
                  cursor: 'pointer',
                  transition: 'all 0.3s ease',
                  display: 'flex',
                  flexDirection: 'column',
                  position: 'relative',
                  overflow: 'hidden',
                  minHeight: '200px',
                  boxShadow: '0 4px 20px rgba(0,0,0,0.2)'
                }}
                onMouseOver={e => {
                  e.currentTarget.style.transform = 'translateY(-4px)';
                  e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.2)';
                }}
                onMouseOut={e => {
                  e.currentTarget.style.transform = 'none';
                  e.currentTarget.style.borderColor = 'var(--border)';
                }}
              >
                <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '4px', background: 'linear-gradient(90deg, var(--primary), #ff6b6b)' }} />
                <h3 style={{ fontSize: '20px', marginBottom: '8px', fontWeight: 600 }}>{c.name}</h3>
                
                <div style={{ display: 'flex', gap: '16px', marginTop: 'auto', paddingTop: '20px', borderTop: '1px solid var(--border)' }}>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <span style={{ fontSize: '24px', fontWeight: 700, color: 'var(--fg)' }}>{c.video_count || 0}</span>
                    <span style={{ fontSize: '12px', color: 'var(--dim)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Videos</span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <span style={{ fontSize: '24px', fontWeight: 700, color: 'var(--primary)' }}>{c.clip_count || 0}</span>
                    <span style={{ fontSize: '12px', color: 'var(--dim)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>Clips</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Glassmorphic Add Modal */}
        {showAddModal && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(8px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
            <div style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: '24px', padding: '40px', width: '100%', maxWidth: '500px', boxShadow: '0 24px 48px rgba(0,0,0,0.4)', position: 'relative' }}>
              <button 
                onClick={() => setShowAddModal(false)}
                style={{ position: 'absolute', top: '24px', right: '24px', background: 'transparent', border: 'none', color: 'var(--dim)', fontSize: '24px', cursor: 'pointer' }}
              >×</button>
              
              <h2 style={{ fontSize: '24px', marginBottom: '8px', fontWeight: 700 }}>New Campaign</h2>
              <p style={{ color: 'var(--dim)', fontSize: '14px', marginBottom: '32px' }}>Set up a new pipeline to extract and analyze clips.</p>
              
              <form onSubmit={handleCreate} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--fg)' }}>Campaign Name</label>
                  <input 
                    value={newName} 
                    onChange={e => setNewName(e.target.value)} 
                    placeholder="e.g. Summer Outreach" 
                    style={{ padding: '12px 16px', borderRadius: '12px', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--fg)', fontSize: '14px' }}
                    required
                  />
                </div>
                
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--fg)' }}>Reward / Budget</label>
                  <input 
                    value={newReward} 
                    onChange={e => setNewReward(e.target.value)} 
                    placeholder="e.g. $500 per approved clip" 
                    style={{ padding: '12px 16px', borderRadius: '12px', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--fg)', fontSize: '14px' }}
                  />
                </div>
                
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--fg)' }}>Campaign Rules</label>
                  <textarea 
                    value={newRules} 
                    onChange={e => setNewRules(e.target.value)} 
                    placeholder="Provide specific guidelines, do's and don'ts..." 
                    style={{ padding: '12px 16px', borderRadius: '12px', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--fg)', fontSize: '14px', minHeight: '80px', resize: 'vertical' }}
                  />
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--fg)' }}>Source Videos (Optional)</label>
                  <textarea 
                    value={newVideos} 
                    onChange={e => setNewVideos(e.target.value)} 
                    placeholder="Paste YouTube URLs here (separated by spaces or newlines)..." 
                    style={{ padding: '12px 16px', borderRadius: '12px', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--fg)', fontSize: '14px', minHeight: '80px', resize: 'vertical' }}
                  />
                </div>
                
                <button 
                  type="submit" 
                  disabled={loading}
                  style={{ 
                    marginTop: '12px', padding: '16px', borderRadius: '12px', background: 'var(--primary)', color: '#000', fontSize: '15px', fontWeight: 600, border: 'none', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.7 : 1, transition: 'all 0.2s' 
                  }}
                >
                  {loading ? 'Creating...' : 'Create Campaign'}
                </button>
              </form>
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="analytics-layout">
      <div className="campaign-sidebar" style={{ width: '240px', padding: '24px 16px' }}>
        <button onClick={() => setActiveId(null)} className="btn-back" style={{ marginBottom: '24px', width: '100%', justifyContent: 'center' }}>
          ← Back to Dashboard
        </button>
        <h3 style={{ paddingLeft: '8px', fontSize: '14px', textTransform: 'uppercase', letterSpacing: '1px', color: 'var(--dim)' }}>Other Campaigns</h3>
        
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', overflowY: 'auto' }}>
          {campaigns.map(c => (
            <div 
              key={c.id} 
              onClick={() => setActiveId(c.id)}
              style={{
                padding: '10px 12px',
                borderRadius: '8px',
                cursor: 'pointer',
                background: c.id === activeId ? 'rgba(255, 170, 0, 0.1)' : 'transparent',
                color: c.id === activeId ? 'var(--primary)' : 'var(--fg)',
                fontWeight: c.id === activeId ? 600 : 400,
                transition: 'background 0.2s'
              }}
              onMouseOver={e => { if (c.id !== activeId) e.currentTarget.style.background = 'var(--bg)' }}
              onMouseOut={e => { if (c.id !== activeId) e.currentTarget.style.background = 'transparent' }}
            >
              {c.name}
            </div>
          ))}
        </div>
      </div>

      <div className="campaign-content" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
        <header className="campaign-header" style={{ padding: '24px 32px', borderBottom: '1px solid var(--border)', background: 'var(--panel)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ fontSize: '24px', fontWeight: 700, margin: 0 }}>{campaign.name}</h2>
        </header>
        
        {loading && <div className="loading">Loading campaign data...</div>}
        
        {(extractMsg || analyzeMsg) && (
          <section className="deck" style={{ marginTop: 0, marginBottom: '24px', maxWidth: '100%' }}>
            {extractMsg && (
              <div className="deck-row live">
                <span className="deck-name mono">TRANSCRIPTS</span>
                <div className="deck-bar">
                  <div className="deck-fill indeterminate" />
                </div>
                <span className="deck-msg">{extractMsg}</span>
              </div>
            )}
            {analyzeMsg && (
              <div className="deck-row live">
                <span className="deck-name mono">ANALYSIS</span>
                <div className="deck-bar">
                  <div className="deck-fill indeterminate" />
                </div>
                <span className="deck-msg">{analyzeMsg}</span>
              </div>
            )}
            {clipAnalysisMsg && (
              <div className="deck-row live">
                <span className="deck-name mono">CLIP EXTRACTION</span>
                <div className="deck-bar">
                  <div className="deck-fill indeterminate" />
                </div>
                <span className="deck-msg">{clipAnalysisMsg}</span>
              </div>
            )}
          </section>
        )}

        <div className="tabs" style={{ display: 'flex', gap: '24px', padding: '0 32px', borderBottom: '1px solid var(--border)', background: 'var(--panel)' }}>
          <button 
            style={{ padding: '16px 4px', background: 'none', border: 'none', borderBottom: activeTab === 'overview' ? '2px solid var(--amber)' : '2px solid transparent', color: activeTab === 'overview' ? 'var(--amber)' : 'var(--dim)', cursor: 'pointer', fontWeight: 600, fontSize: '14px', transition: 'all 0.2s' }} 
            onClick={() => setActiveTab('overview')}
          >
            Overview
          </button>
          <button 
            style={{ padding: '16px 4px', background: 'none', border: 'none', borderBottom: activeTab === 'videos' ? '2px solid var(--amber)' : '2px solid transparent', color: activeTab === 'videos' ? 'var(--amber)' : 'var(--dim)', cursor: 'pointer', fontWeight: 600, fontSize: '14px', transition: 'all 0.2s' }} 
            onClick={() => setActiveTab('videos')}
          >
            Videos
          </button>
          <button 
            style={{ padding: '16px 4px', background: 'none', border: 'none', borderBottom: activeTab === 'social' ? '2px solid var(--amber)' : '2px solid transparent', color: activeTab === 'social' ? 'var(--amber)' : 'var(--dim)', cursor: 'pointer', fontWeight: 600, fontSize: '14px', transition: 'all 0.2s' }} 
            onClick={() => setActiveTab('social')}
          >
            Social Hub
          </button>
        </div>

        <div className="campaign-dashboard" style={{ flex: 1, overflowY: 'auto', padding: '32px' }}>
          {activeTab === 'overview' && (
            <div style={{ display: 'grid', gap: '32px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
                <section className="glass-panel" style={{ padding: '24px', borderRadius: '16px' }}>
                  <h3 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '16px', color: 'var(--text)' }}>Campaign Info</h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    {campaign.description && (
                      <div>
                        <div style={{ fontSize: '12px', color: 'var(--dim)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '4px' }}>Reward / Budget</div>
                        <div style={{ fontSize: '16px', fontWeight: 500, color: 'var(--green)' }}>{campaign.description}</div>
                      </div>
                    )}
                    <div>
                      <div style={{ fontSize: '12px', color: 'var(--dim)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '4px' }}>Rules</div>
                      <div style={{ fontSize: '14px', color: 'var(--text)', whiteSpace: 'pre-wrap', background: 'rgba(0,0,0,0.2)', padding: '12px', borderRadius: '8px', border: '1px solid var(--glass-border)' }}>
                        {campaign.rules || 'No rules specified.'}
                      </div>
                    </div>
                  </div>
                </section>
                
                <section className="glass-panel" style={{ padding: '24px', borderRadius: '16px' }}>
                  <h3 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '16px', color: 'var(--text)' }}>Metrics Overview</h3>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                    <div style={{ background: 'rgba(0,0,0,0.2)', padding: '16px', borderRadius: '12px', border: '1px solid var(--glass-border)' }}>
                      <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--amber)' }}>{campaign.videos.length}</div>
                      <div style={{ fontSize: '12px', color: 'var(--dim)', textTransform: 'uppercase' }}>Source Videos</div>
                    </div>
                    <div style={{ background: 'rgba(0,0,0,0.2)', padding: '16px', borderRadius: '12px', border: '1px solid var(--glass-border)' }}>
                      <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--amber)' }}>{campaign.clips.length}</div>
                      <div style={{ fontSize: '12px', color: 'var(--dim)', textTransform: 'uppercase' }}>Total Clips</div>
                    </div>
                    <div style={{ background: 'rgba(0,0,0,0.2)', padding: '16px', borderRadius: '12px', border: '1px solid var(--glass-border)' }}>
                      <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--green)' }}>
                        {campaign.clips.filter(c => c.role === 'mine').length}
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--dim)', textTransform: 'uppercase' }}>Our Clips</div>
                    </div>
                    <div style={{ background: 'rgba(0,0,0,0.2)', padding: '16px', borderRadius: '12px', border: '1px solid var(--glass-border)' }}>
                      <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--red)' }}>
                        {campaign.clips.filter(c => c.role === 'competitor').length}
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--dim)', textTransform: 'uppercase' }}>Competitor Clips</div>
                    </div>
                    <div style={{ background: 'rgba(0,0,0,0.2)', padding: '16px', borderRadius: '12px', border: '1px solid var(--glass-border)' }}>
                      <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--green)' }}>
                        {insights?.feedback?.approvals ?? 0}
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--dim)', textTransform: 'uppercase' }}>Approved Reviews</div>
                    </div>
                    <div style={{ background: 'rgba(0,0,0,0.2)', padding: '16px', borderRadius: '12px', border: '1px solid var(--glass-border)' }}>
                      <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--red)' }}>
                        {insights?.feedback?.rejections ?? 0}
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--dim)', textTransform: 'uppercase' }}>Rejected Reviews</div>
                    </div>
                  </div>
                </section>
              </div>

              {campaign.moments.length > 0 && (
                <section className="glass-panel" style={{ padding: '24px', borderRadius: '16px' }}>
                  <h3 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '16px', color: 'var(--text)' }}>Top Moment Recommendations</h3>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '16px' }}>
                    {campaign.moments.slice(0, 3).map((m: CampaignMoment) => {
                      const sourceVideo = campaign.videos.find(v => v.video_url === m.video_url);
                      return (
                        <div key={m.id} style={{ background: 'rgba(0,0,0,0.2)', padding: '16px', borderRadius: '12px', border: '1px solid var(--glass-border)' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                            <div style={{ fontSize: '11px', color: 'var(--amber)', fontWeight: 600 }}>{sourceVideo?.title || 'Unknown Video'}</div>
                            <div style={{ background: 'var(--amber)', color: '#000', padding: '2px 6px', borderRadius: '4px', fontSize: '10px', fontWeight: 700 }}>
                              Score: {(m.recommendation_score || 0).toFixed(1)}
                            </div>
                          </div>
                          <div style={{ fontSize: '13px', color: 'var(--text)', marginBottom: '12px', lineHeight: '1.4', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                            "{m.transcript_text}"
                          </div>
                          {m.feedback_adjustment ? (
                            <div style={{ fontSize: '11px', color: m.feedback_adjustment > 0 ? 'var(--green)' : 'var(--red)' }}>
                              Feedback bias: {m.feedback_adjustment > 0 ? '+' : ''}{m.feedback_adjustment.toFixed(1)}
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                </section>
              )}

              {/* Analyzer Video Ranking */}
              {videoRanking.length > 0 && (
                <section className="glass-panel" style={{ padding: '24px', borderRadius: '16px' }}>
                  <h3 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '16px', color: 'var(--text)' }}>Analyzer: Video Ranking</h3>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '16px' }}>
                    {videoRanking.map((vr, i) => {
                      const sourceVideo = campaign.videos.find(v => v.video_url === vr.video_url);
                      return (
                        <div key={vr.video_url} style={{ display: 'flex', alignItems: 'center', background: 'rgba(0,0,0,0.2)', padding: '16px', borderRadius: '12px', border: '1px solid var(--glass-border)' }}>
                          <div style={{ fontSize: '24px', fontWeight: 800, color: i === 0 ? 'var(--amber)' : 'var(--dim)', marginRight: '16px', minWidth: '24px' }}>
                            #{i + 1}
                          </div>
                          <div style={{ flex: 1 }}>
                            <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text)', marginBottom: '4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '200px' }}>
                              {sourceVideo?.title || 'Unknown Video'}
                            </div>
                            <div style={{ fontSize: '12px', color: 'var(--dim)' }}>
                              Potential Clips: <strong style={{ color: 'var(--green)' }}>{vr.clip_potential}</strong>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </section>
              )}

              {/* AI Best Ideas */}
              {hookRecs && (
                <section className="glass-panel" style={{ padding: '24px', borderRadius: '16px', background: 'linear-gradient(135deg, rgba(255,170,0,0.05), rgba(0,0,0,0.4))' }}>
                  <h3 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '16px', color: 'var(--amber)' }}>✨ AI Best Ideas: Hook Strategy</h3>
                  <p style={{ fontSize: '14px', color: 'var(--text)', lineHeight: '1.6', marginBottom: '16px' }}>
                    {hookRecs.recommendation}
                  </p>
                  <div style={{ display: 'flex', gap: '24px' }}>
                    <div>
                      <div style={{ fontSize: '12px', color: 'var(--dim)', textTransform: 'uppercase', marginBottom: '4px' }}>Visual Hook Success</div>
                      <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text)' }}>{hookRecs.visual_score}%</div>
                    </div>
                    <div>
                      <div style={{ fontSize: '12px', color: 'var(--dim)', textTransform: 'uppercase', marginBottom: '4px' }}>Audio Hook Success</div>
                      <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--text)' }}>{hookRecs.audio_score}%</div>
                    </div>
                  </div>
                </section>
              )}
            </div>
          )}

          {activeTab === 'social' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <section className="glass-panel" style={{ padding: '32px', borderRadius: '16px', background: 'var(--panel)' }}>
                <h3 style={{ fontSize: '20px', fontWeight: 700, marginBottom: '16px', color: 'var(--text)' }}>Instagram Analytics</h3>
                
                {!igData.connected ? (
                  <form onSubmit={handleIgConnect} style={{ display: 'flex', flexDirection: 'column', gap: '16px', maxWidth: '400px' }}>
                    <p style={{ color: 'var(--dim)', fontSize: '14px', marginBottom: '8px' }}>
                      Connect your Meta App to pull real-time Reels performance data directly from your Instagram account.
                    </p>
                    <input 
                      type="text" 
                      placeholder="Meta App ID" 
                      value={igAppId}
                      onChange={e => setIgAppId(e.target.value)}
                      style={{ padding: '12px 16px', borderRadius: '8px', border: '1px solid var(--glass-border)', background: 'rgba(0,0,0,0.2)', color: 'var(--text)' }}
                      required
                    />
                    <input 
                      type="password" 
                      placeholder="Meta App Secret" 
                      value={igAppSecret}
                      onChange={e => setIgAppSecret(e.target.value)}
                      style={{ padding: '12px 16px', borderRadius: '8px', border: '1px solid var(--glass-border)', background: 'rgba(0,0,0,0.2)', color: 'var(--text)' }}
                      required
                    />
                    <button type="submit" disabled={loading} style={{ padding: '12px 16px', borderRadius: '8px', background: 'var(--amber)', color: '#000', fontWeight: 600, cursor: 'pointer', border: 'none' }}>
                      {loading ? 'Connecting...' : 'Connect Instagram'}
                    </button>
                  </form>
                ) : (
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
                      <div style={{ fontSize: '16px', color: 'var(--green)' }}>✓ Connected as <strong>@{igData.username}</strong></div>
                      <button onClick={loadIgOverview} style={{ padding: '8px 16px', borderRadius: '8px', background: 'rgba(255,255,255,0.1)', border: '1px solid var(--glass-border)', color: 'var(--text)', cursor: 'pointer' }}>Refresh Sync</button>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: '20px' }}>
                      {igData.clips && igData.clips.map(c => (
                        <div key={c.id} style={{ background: 'rgba(0,0,0,0.3)', borderRadius: '12px', overflow: 'hidden', border: '1px solid var(--glass-border)' }}>
                          <div style={{ width: '100%', aspectRatio: '9/16', background: '#000', position: 'relative' }}>
                            {c.thumbnail ? <img src={c.thumbnail} alt="thumb" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : <div style={{ padding: '20px', color: 'var(--dim)', textAlign: 'center' }}>No Thumb</div>}
                            <div style={{ position: 'absolute', bottom: '8px', right: '8px', background: 'rgba(0,0,0,0.8)', padding: '4px 8px', borderRadius: '6px', fontSize: '12px', color: '#fff', fontWeight: 600 }}>
                              👁 {c.views}
                            </div>
                          </div>
                          <div style={{ padding: '16px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                              <span style={{ fontSize: '12px', color: 'var(--dim)' }}>Likes: <strong style={{ color: 'var(--fg)' }}>{c.likes}</strong></span>
                              <span style={{ fontSize: '12px', color: 'var(--dim)' }}>Reach: <strong style={{ color: 'var(--fg)' }}>{c.reach}</strong></span>
                            </div>
                            {c.permalink && (
                              <a href={c.permalink} target="_blank" rel="noreferrer" style={{ fontSize: '12px', color: 'var(--amber)', textDecoration: 'none' }}>View on Instagram →</a>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </section>
            </div>
          )}

          {activeTab === 'videos' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--panel-2)', padding: '16px', borderRadius: '16px', border: '1px solid var(--glass-border)' }}>
                <div style={{ display: 'flex', gap: '8px' }}>
                  {(['all', 'source', 'mine', 'competitor'] as const).map(filter => (
                    <button
                      key={filter}
                      onClick={() => setVideoFilter(filter)}
                      style={{
                        padding: '8px 16px',
                        borderRadius: '20px',
                        fontSize: '13px',
                        fontWeight: 600,
                        textTransform: 'capitalize',
                        background: videoFilter === filter ? 'var(--amber)' : 'rgba(255,255,255,0.05)',
                        color: videoFilter === filter ? '#000' : 'var(--dim)',
                        border: videoFilter === filter ? '1px solid var(--amber)' : '1px solid var(--glass-border)',
                        cursor: 'pointer',
                        transition: 'all 0.2s'
                      }}
                    >
                      {filter === 'source' ? 'Campaign Source' : filter === 'mine' ? 'Our Clips' : filter === 'competitor' ? 'Competitors' : 'All Media'}
                    </button>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: '12px' }}>
                  <label style={{ padding: '10px 20px', borderRadius: '20px', background: 'rgba(255,255,255,0.1)', color: 'var(--text)', fontSize: '14px', fontWeight: 600, border: '1px solid var(--glass-border)', cursor: 'pointer', display: 'flex', alignItems: 'center', transition: 'background 0.2s' }}>
                    Import CSV
                    <input type="file" accept=".csv" style={{ display: 'none' }} onChange={async (e) => {
                      if (e.target.files && e.target.files[0]) {
                        try {
                          await api.importAnalyticsCsv(activeId, e.target.files[0]);
                          alert("CSV imported successfully! Analytics updated.");
                          loadCampaign(activeId);
                        } catch (err) {
                          alert("Failed to import CSV: " + err);
                        }
                      }
                    }} />
                  </label>
                  <button 
                    onClick={() => setShowAddMediaModal(true)}
                    style={{ padding: '10px 20px', borderRadius: '20px', background: 'var(--amber)', color: '#000', fontSize: '14px', fontWeight: 600, border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px', boxShadow: '0 4px 12px rgba(255, 178, 36, 0.3)' }}
                  >
                    <span style={{ fontSize: '18px', lineHeight: 1 }}>+</span> Add Media
                  </button>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '24px' }}>
                {(videoFilter === 'all' || videoFilter === 'source') && campaign.videos.map(v => {
                  const getYoutubeId = (url: string) => {
                    const match = url.match(/(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([^&?]+)/);
                    return match ? match[1] : null;
                  };
                  const ytid = getYoutubeId(v.video_url);
                  return (
                    <div 
                      key={`v-${v.id}`}
                      className="glass-panel"
                      onClick={() => {
                        setSelectedVideo(v);
                      }}
                      style={{
                        borderRadius: '16px',
                        overflow: 'hidden',
                        cursor: (v.has_ingest && v.has_asr) ? 'pointer' : 'default',
                        transition: 'transform 0.2s, box-shadow 0.2s',
                        display: 'flex',
                        flexDirection: 'column'
                      }}
                      onMouseOver={e => { if (v.has_ingest && v.has_asr) e.currentTarget.style.transform = 'translateY(-4px)'; }}
                      onMouseOut={e => { e.currentTarget.style.transform = 'none'; }}
                    >
                      <div style={{ position: 'relative', width: '100%', aspectRatio: '16/9', background: '#000' }}>
                        {ytid ? (
                          <img src={`https://img.youtube.com/vi/${ytid}/mqdefault.jpg`} style={{ width: '100%', height: '100%', objectFit: 'cover' }} alt="thumbnail" />
                        ) : (
                          <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', color: 'var(--dim)' }}>No thumb</div>
                        )}
                        <div style={{ position: 'absolute', top: '8px', left: '8px', background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', color: '#fff', padding: '4px 8px', borderRadius: '4px', fontSize: '10px', fontWeight: 700, textTransform: 'uppercase', border: '1px solid rgba(255,255,255,0.2)' }}>
                          Source
                        </div>
                        {v.duration_sec && (
                          <div style={{ position: 'absolute', bottom: '8px', right: '8px', background: 'rgba(0,0,0,0.8)', color: '#fff', padding: '4px 8px', borderRadius: '6px', fontSize: '12px', fontWeight: 600 }}>
                            {Math.floor(v.duration_sec / 60)}:{(v.duration_sec % 60).toString().padStart(2, '0')}
                          </div>
                        )}
                      </div>
                      <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', flex: 1, background: 'rgba(0,0,0,0.3)' }}>
                        <h3 style={{ fontSize: '14px', marginBottom: '8px', lineHeight: '1.4', fontWeight: 600, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{v.title || v.video_url}</h3>
                        <div style={{ fontSize: '12px', color: 'var(--dim)', marginBottom: '16px' }}>{v.channel || 'Unknown Channel'}</div>
                        <div style={{ marginTop: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: (v.has_ingest && v.has_asr) ? 'var(--green)' : 'var(--amber)' }}>
                            <span>●</span> {(v.has_ingest && v.has_asr) ? 'Ready for Studio' : 'Processing...'}
                          </div>
                          {(videoFilter === 'all' || videoFilter === 'source') && (
                            <button
                              onClick={(e) => { e.stopPropagation(); loadCompetitorMatches(v.video_url); }}
                              style={{ padding: '4px 8px', fontSize: '11px', background: 'rgba(255,255,255,0.1)', border: '1px solid var(--glass-border)', borderRadius: '4px', color: 'var(--text)', cursor: 'pointer' }}
                            >
                              AI Matches
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
                
                {['all', 'mine', 'competitor'].includes(videoFilter) && campaign.clips.filter(c => videoFilter === 'all' || c.role === videoFilter).map(c => (
                  <div 
                    key={`c-${c.id}`} 
                    className="glass-panel" 
                    onClick={() => setSelectedClip(c)}
                    style={{ borderRadius: '16px', overflow: 'hidden', display: 'flex', flexDirection: 'column', cursor: 'pointer', transition: 'transform 0.2s, box-shadow 0.2s' }}
                    onMouseOver={e => { e.currentTarget.style.transform = 'translateY(-4px)'; }}
                    onMouseOut={e => { e.currentTarget.style.transform = 'none'; }}
                  >
                    <div style={{ display: 'flex', padding: '16px', gap: '16px', background: 'rgba(0,0,0,0.3)' }}>
                      <div style={{ width: '72px', flexShrink: 0, aspectRatio: '9/16', background: '#000', borderRadius: '8px', overflow: 'hidden', position: 'relative' }}>
                        {c.thumbnail_path ? (
                          <img src={c.thumbnail_path.includes('campaigns') ? api.fileUrl(`campaigns/${c.thumbnail_path.split(/campaigns[/\\]/)[1].replace(/\\/g, '/')}`) : c.thumbnail_path} style={{ width: '100%', height: '100%', objectFit: 'cover' }} alt="thumb" />
                        ) : (
                          <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '10px', color: 'var(--dim)' }}>No thumb</div>
                        )}
                      </div>
                      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '4px' }}>
                          <div style={{ background: c.role === 'mine' ? 'rgba(61, 214, 163, 0.2)' : 'rgba(255, 92, 73, 0.2)', color: c.role === 'mine' ? 'var(--green)' : 'var(--red)', padding: '2px 6px', borderRadius: '4px', fontSize: '9px', fontWeight: 700, textTransform: 'uppercase' }}>
                            {c.role === 'mine' ? 'Our Clip' : 'Competitor'}
                          </div>
                        </div>
                        <div style={{ fontWeight: 600, fontSize: '13px', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', marginBottom: '4px', color: 'var(--text)' }}>
                          {c.title || c.clip_url}
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--dim)', marginBottom: '8px' }}>{(c as any).channel || 'Unknown Channel'}</div>
                        <div style={{ marginTop: 'auto', display: 'flex', gap: '12px', fontSize: '12px', color: 'var(--dim)', alignItems: 'center' }}>
                          <span><strong style={{ color: 'var(--text)' }}>{c.views || 0}</strong> views</span>
                          <span><strong style={{ color: 'var(--text)' }}>{c.likes || 0}</strong> likes</span>
                          {c.clip_url && (
                            <a href={c.clip_url} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 'auto', color: 'var(--amber)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '4px' }}>
                              Source ↗
                            </a>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
      
      {/* Add Media Modal */}
      {showAddMediaModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', backdropFilter: 'blur(12px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div className="glass-panel" style={{ borderRadius: '24px', padding: '40px', width: '100%', maxWidth: '500px', position: 'relative' }}>
            <button 
              onClick={() => setShowAddMediaModal(false)}
              style={{ position: 'absolute', top: '24px', right: '24px', background: 'transparent', border: 'none', color: 'var(--dim)', fontSize: '24px', cursor: 'pointer' }}
            >×</button>
            
            <h2 style={{ fontSize: '24px', marginBottom: '8px', fontWeight: 700, color: 'var(--text)' }}>Add Media</h2>
            <p style={{ color: 'var(--dim)', fontSize: '14px', marginBottom: '32px' }}>Import new videos or shorts to analyze within this campaign.</p>
            
            <form onSubmit={handleAddMediaSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)' }}>Video Type</label>
                <select 
                  value={addMediaType} 
                  onChange={e => setAddMediaType(e.target.value as any)}
                  style={{ padding: '14px 16px', borderRadius: '12px', border: '1px solid var(--glass-border)', background: 'rgba(0,0,0,0.3)', color: 'var(--text)', fontSize: '14px', outline: 'none' }}
                >
                  <option value="source">Campaign Source Video (Long-form)</option>
                  <option value="mine">Our Clip / Lovable Campaign Video (Short)</option>
                  <option value="competitor">Competitor Clip (Short)</option>
                  <option value="hashtag">Hashtag Search (Automated)</option>
                </select>
              </div>
              
              {addMediaType === 'hashtag' ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)' }}>Hashtag</label>
                  <input 
                    type="text"
                    value={addMediaHashtag} 
                    onChange={e => setAddMediaHashtag(e.target.value)} 
                    placeholder="e.g. #productivity" 
                    style={{ padding: '14px 16px', borderRadius: '12px', border: '1px solid var(--glass-border)', background: 'rgba(0,0,0,0.3)', color: 'var(--text)', fontSize: '14px', outline: 'none' }}
                    required
                  />
                  <p style={{ fontSize: '12px', color: 'var(--dim)', margin: 0 }}>We will automatically find the top shorts and ingest them into the campaign.</p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)' }}>URLs (YouTube, TikTok, Instagram)</label>
                  <textarea 
                    value={addMediaUrls} 
                    onChange={e => setAddMediaUrls(e.target.value)} 
                    placeholder="Paste one or more URLs here..." 
                    style={{ padding: '14px 16px', borderRadius: '12px', border: '1px solid var(--glass-border)', background: 'rgba(0,0,0,0.3)', color: 'var(--text)', fontSize: '14px', minHeight: '100px', resize: 'vertical', outline: 'none' }}
                    required
                  />
                </div>
              )}
              
              {addMediaType !== 'source' && addMediaType !== 'hashtag' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', background: 'rgba(0,0,0,0.2)', padding: '16px', borderRadius: '12px', border: '1px solid var(--glass-border)' }}>
                  <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text)' }}>Automation Settings</label>
                  
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '14px', color: 'var(--dim)', cursor: 'pointer' }}>
                    <input 
                      type="checkbox" 
                      checked={addMediaSettings.download} 
                      onChange={e => setAddMediaSettings(s => ({ ...s, download: e.target.checked }))}
                    />
                    Download Video (Required for frames & audio)
                  </label>
                  
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '14px', color: 'var(--dim)', cursor: 'pointer' }}>
                    <input 
                      type="checkbox" 
                      checked={addMediaSettings.transcribe} 
                      onChange={e => setAddMediaSettings(s => ({ ...s, transcribe: e.target.checked }))}
                    />
                    Transcribe Audio (AI hook detection)
                  </label>

                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '14px', color: 'var(--dim)', cursor: 'pointer' }}>
                    <input 
                      type="checkbox" 
                      checked={addMediaSettings.analyze} 
                      onChange={e => setAddMediaSettings(s => ({ ...s, analyze: e.target.checked }))}
                    />
                    Analyze (OCR & metadata)
                  </label>
                </div>
              )}
              
              <button 
                type="submit" 
                disabled={loading}
                style={{ 
                  marginTop: '12px', padding: '16px', borderRadius: '12px', background: 'var(--amber)', color: '#000', fontSize: '15px', fontWeight: 600, border: 'none', cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.7 : 1, transition: 'all 0.2s', boxShadow: '0 4px 16px rgba(255, 178, 36, 0.3)' 
                }}
              >
                {loading ? 'Adding...' : 'Add Media'}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* AI Matches Modal */}
      {selectedMatchVideo && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.8)', backdropFilter: 'blur(8px)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: 'var(--panel)', padding: '32px', borderRadius: '16px', border: '1px solid var(--glass-border)', width: '600px', maxWidth: '90%', maxHeight: '80vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <h2 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: 'var(--text)' }}>AI Competitor Matches</h2>
              <button onClick={() => { setSelectedMatchVideo(null); setCompetitorMatches([]); }} style={{ background: 'none', border: 'none', color: 'var(--dim)', cursor: 'pointer', fontSize: '24px' }}>&times;</button>
            </div>
            
            <div style={{ fontSize: '14px', color: 'var(--dim)', marginBottom: '24px' }}>
              Comparing against source: <strong style={{ color: 'var(--amber)' }}>{selectedMatchVideo.title || selectedMatchVideo.video_url}</strong>
            </div>

            {loading ? (
              <div style={{ padding: '40px', textAlign: 'center', color: 'var(--amber)' }}>Analyzing matches...</div>
            ) : competitorMatches.length === 0 ? (
              <div style={{ padding: '40px', textAlign: 'center', color: 'var(--dim)', background: 'rgba(0,0,0,0.2)', borderRadius: '12px' }}>
                No competitor clips found matching this source video's transcript.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {competitorMatches.map((m, i) => (
                  <div key={i} style={{ background: 'rgba(255, 170, 0, 0.05)', border: '1px solid rgba(255, 170, 0, 0.2)', padding: '16px', borderRadius: '12px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                      <span style={{ fontSize: '12px', color: 'var(--amber)', fontWeight: 600 }}>Match Found (Confidence: {(m.confidence * 100).toFixed(1)}%)</span>
                      <span style={{ fontSize: '12px', color: 'var(--dim)' }}>{m.start_sec.toFixed(1)}s - {m.end_sec.toFixed(1)}s</span>
                    </div>
                    
                    {m.visual_hook && (
                      <div style={{ marginBottom: '12px' }}>
                        <div style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--dim)', marginBottom: '4px' }}>Visual Hook (Tesseract OCR):</div>
                        <div style={{ fontSize: '13px', background: 'rgba(255, 255, 255, 0.05)', padding: '8px', borderRadius: '4px', color: '#fff', borderLeft: '2px solid var(--amber)' }}>
                          {m.visual_hook}
                        </div>
                      </div>
                    )}
                    
                    <div>
                      <div style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--dim)', marginBottom: '4px' }}>Matched Transcript:</div>
                      <div style={{ fontSize: '13px', color: 'var(--dim)', fontStyle: 'italic', marginBottom: '16px' }}>
                        "...{m.matched_in_video}..."
                      </div>
                    </div>
                    
                    {improvedHooks[i] ? (
                      <div style={{ background: 'rgba(255,255,255,0.05)', padding: '12px', borderRadius: '8px' }}>
                        <h4 style={{ fontSize: '12px', color: 'var(--amber)', textTransform: 'uppercase', marginBottom: '8px' }}>✨ Better Visual Hooks (Text)</h4>
                        <ul style={{ margin: 0, paddingLeft: '16px', color: 'var(--text)', fontSize: '13px', marginBottom: '12px' }}>
                          {improvedHooks[i].visual_hooks.map((h, idx) => <li key={idx} style={{ marginBottom: '4px' }}>{h}</li>)}
                        </ul>
                        <h4 style={{ fontSize: '12px', color: 'var(--amber)', textTransform: 'uppercase', marginBottom: '8px' }}>✨ Better Audio Hooks (Script)</h4>
                        <ul style={{ margin: 0, paddingLeft: '16px', color: 'var(--text)', fontSize: '13px' }}>
                          {improvedHooks[i].audio_hooks.map((h, idx) => <li key={idx} style={{ marginBottom: '4px' }}>{h}</li>)}
                        </ul>
                      </div>
                    ) : (
                      <button 
                        onClick={() => handleImproveHook(i, m.matched_in_video, m.visual_hook || '')}
                        disabled={improvingHookFor === i}
                        style={{ padding: '8px 12px', fontSize: '12px', background: 'rgba(255, 170, 0, 0.1)', border: '1px solid var(--amber)', color: 'var(--amber)', borderRadius: '6px', cursor: improvingHookFor === i ? 'not-allowed' : 'pointer', fontWeight: 600, transition: 'all 0.2s' }}
                      >
                        {improvingHookFor === i ? 'Thinking...' : '✨ Improve Idea with AI'}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Selected Video Modal */}
      {selectedVideo && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.8)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setSelectedVideo(null)}>
          <div className="glass-panel" style={{ width: '600px', maxWidth: '90vw', maxHeight: '90vh', overflowY: 'auto', borderRadius: '16px', padding: '24px' }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
              <div style={{ background: 'rgba(255,255,255,0.1)', color: 'var(--text)', padding: '4px 8px', borderRadius: '4px', fontSize: '10px', fontWeight: 700, textTransform: 'uppercase' }}>
                Video Info
              </div>
              <button onClick={() => setSelectedVideo(null)} style={{ background: 'none', border: 'none', color: 'var(--dim)', fontSize: '24px', cursor: 'pointer' }}>×</button>
            </div>
            
            <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text)', marginBottom: '8px' }}>{selectedVideo.title || selectedVideo.video_url}</h2>
            <div style={{ fontSize: '14px', color: 'var(--dim)', marginBottom: '16px' }}>{selectedVideo.channel || 'Unknown Channel'}</div>
            
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '16px', marginBottom: '24px', background: 'rgba(0,0,0,0.2)', padding: '16px', borderRadius: '12px' }}>
              {selectedVideo.duration_sec && (
                <div>
                  <div style={{ fontSize: '11px', color: 'var(--dim)', textTransform: 'uppercase', marginBottom: '4px' }}>Duration</div>
                  <div style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text)' }}>{Math.floor(selectedVideo.duration_sec / 60)}:{(selectedVideo.duration_sec % 60).toString().padStart(2, '0')}</div>
                </div>
              )}
              <div>
                <div style={{ fontSize: '11px', color: 'var(--dim)', textTransform: 'uppercase', marginBottom: '4px' }}>Processing Status</div>
                <div style={{ fontSize: '14px', fontWeight: 600, color: (selectedVideo.has_ingest && selectedVideo.has_asr) ? 'var(--green)' : 'var(--amber)' }}>
                  {(selectedVideo.has_ingest && selectedVideo.has_asr) ? 'Ready for Studio' : 'Processing...'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--dim)', textTransform: 'uppercase', marginBottom: '4px' }}>Downloaded Resolution</div>
                <div style={{ fontSize: '18px', fontWeight: 600, color: selectedVideo.width && selectedVideo.height ? 'var(--green)' : 'var(--dim)' }}>
                  {formatResolution(selectedVideo.width, selectedVideo.height)}
                </div>
              </div>
            </div>

            {selectedVideo.media_url && (
              <div style={{ marginBottom: '24px' }}>
                <div style={{ fontSize: '11px', color: 'var(--dim)', textTransform: 'uppercase', marginBottom: '8px' }}>Downloaded Video Preview</div>
                <video src={selectedVideo.media_url} controls playsInline style={{ width: '100%', maxHeight: '320px', background: '#000', borderRadius: '8px' }} />
              </div>
            )}

            <div style={{ display: 'flex', gap: '16px', marginTop: '32px', paddingTop: '16px', borderTop: '1px solid var(--glass-border)' }}>
              <a 
                href={selectedVideo.video_url} 
                target="_blank" 
                rel="noopener noreferrer" 
                style={{ flex: 1, textAlign: 'center', padding: '12px 16px', background: 'rgba(255,255,255,0.1)', color: 'var(--text)', borderRadius: '8px', textDecoration: 'none', fontSize: '13px', fontWeight: 600 }}
              >
                Open Source URL ↗
              </a>
              
              {selectedVideo.has_asr && selectedVideo.job_id && (
                <a 
                  href={`/media/jobs/${selectedVideo.job_id}/asr.json`} 
                  target="_blank" 
                  rel="noopener noreferrer" 
                  style={{ flex: 1, textAlign: 'center', padding: '12px 16px', background: 'rgba(100,200,255,0.1)', color: '#64c8ff', border: '1px solid rgba(100,200,255,0.4)', borderRadius: '8px', textDecoration: 'none', fontSize: '13px', fontWeight: 600 }}
                >
                  View Transcript 📄
                </a>
              )}
              
              <button 
                onClick={() => {
                  if (onSendToStudio && selectedVideo.has_ingest && selectedVideo.has_asr) {
                    onSendToStudio(selectedVideo.video_url);
                    setSelectedVideo(null);
                  }
                }}
                disabled={!(selectedVideo.has_ingest && selectedVideo.has_asr)}
                style={{ flex: 1, padding: '12px 16px', background: 'rgba(61, 214, 163, 0.2)', color: 'var(--green)', border: '1px solid rgba(61, 214, 163, 0.4)', borderRadius: '8px', cursor: (selectedVideo.has_ingest && selectedVideo.has_asr) ? 'pointer' : 'not-allowed', fontSize: '13px', fontWeight: 600, opacity: (selectedVideo.has_ingest && selectedVideo.has_asr) ? 1 : 0.5 }}
              >
                Go to Studio ✂️
              </button>
            </div>
            {selectedVideo.job_id && (
              <button
                onClick={() => refreshCampaignVideo(selectedVideo)}
                disabled={refreshingVideoId === selectedVideo.id}
                style={{ width: '100%', marginTop: '12px', padding: '12px 16px', background: 'rgba(255,178,36,0.14)', color: 'var(--amber)', border: '1px solid rgba(255,178,36,0.4)', borderRadius: '8px', cursor: refreshingVideoId === selectedVideo.id ? 'wait' : 'pointer', fontSize: '13px', fontWeight: 600, opacity: refreshingVideoId === selectedVideo.id ? 0.6 : 1 }}
              >
                {refreshingVideoId === selectedVideo.id ? 'REFRESHING SOURCE…' : 'RE-DOWNLOAD & RE-RENDER WITH BEST QUALITY'}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Selected Clip Modal */}
      {selectedClip && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.8)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div className="glass-panel" style={{ width: '600px', maxWidth: '90vw', maxHeight: '90vh', overflowY: 'auto', borderRadius: '16px', padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
              <div style={{ background: selectedClip.role === 'mine' ? 'rgba(61, 214, 163, 0.2)' : 'rgba(255, 92, 73, 0.2)', color: selectedClip.role === 'mine' ? 'var(--green)' : 'var(--red)', padding: '4px 8px', borderRadius: '4px', fontSize: '10px', fontWeight: 700, textTransform: 'uppercase' }}>
                {selectedClip.role === 'mine' ? 'Our Clip' : 'Competitor'}
              </div>
              <button onClick={() => setSelectedClip(null)} style={{ background: 'none', border: 'none', color: 'var(--dim)', fontSize: '24px', cursor: 'pointer' }}>×</button>
            </div>
            
            <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text)', marginBottom: '8px' }}>{selectedClip.title || selectedClip.clip_url}</h2>
            <div style={{ fontSize: '14px', color: 'var(--dim)', marginBottom: '16px' }}>{selectedClip.channel || 'Unknown Channel'}</div>
            
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px', marginBottom: '24px', background: 'rgba(0,0,0,0.2)', padding: '16px', borderRadius: '12px' }}>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--dim)', textTransform: 'uppercase', marginBottom: '4px' }}>Views</div>
                <div style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text)' }}>{selectedClip.views || 0}</div>
              </div>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--dim)', textTransform: 'uppercase', marginBottom: '4px' }}>Likes</div>
                <div style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text)' }}>{selectedClip.likes || 0}</div>
              </div>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--dim)', textTransform: 'uppercase', marginBottom: '4px' }}>Comments</div>
                <div style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text)' }}>{selectedClip.comments || 0}</div>
              </div>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--dim)', textTransform: 'uppercase', marginBottom: '4px' }}>Shares</div>
                <div style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text)' }}>{selectedClip.shares || 0}</div>
              </div>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--dim)', textTransform: 'uppercase', marginBottom: '4px' }}>Impressions</div>
                <div style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text)' }}>{selectedClip.impressions || 0}</div>
              </div>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--dim)', textTransform: 'uppercase', marginBottom: '4px' }}>CTR</div>
                <div style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text)' }}>{selectedClip.ctr ? `${selectedClip.ctr}%` : '0%'}</div>
              </div>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--dim)', textTransform: 'uppercase', marginBottom: '4px' }}>Avg Viewed</div>
                <div style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text)' }}>{selectedClip.watch_time_pct ? `${selectedClip.watch_time_pct}%` : '0%'}</div>
              </div>
              {selectedClip.duration_sec && (
                <div>
                  <div style={{ fontSize: '11px', color: 'var(--dim)', textTransform: 'uppercase', marginBottom: '4px' }}>Duration</div>
                  <div style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text)' }}>{Math.floor(selectedClip.duration_sec / 60)}:{(selectedClip.duration_sec % 60).toString().padStart(2, '0')}</div>
                </div>
              )}
            </div>

            {selectedClip.audio_hook && (
              <div style={{ marginBottom: '24px' }}>
                <h3 style={{ fontSize: '14px', color: 'var(--amber)', marginBottom: '8px' }}>Audio Hook</h3>
                <div style={{ background: 'rgba(255,178,36,0.1)', padding: '12px', borderRadius: '8px', fontSize: '14px', fontStyle: 'italic', color: 'var(--text)' }}>
                  "{selectedClip.audio_hook}"
                </div>
              </div>
            )}

            {selectedClip.hook_text_overlay && (
              <div style={{ marginBottom: '24px' }}>
                <h3 style={{ fontSize: '14px', color: 'var(--amber)', marginBottom: '8px' }}>Visual Hook</h3>
                <div style={{ background: 'rgba(255,178,36,0.1)', padding: '12px', borderRadius: '8px', fontSize: '14px', fontStyle: 'italic', color: 'var(--text)' }}>
                  "{selectedClip.hook_text_overlay}"
                </div>
              </div>
            )}
            
            {selectedClip.transcript_excerpt && (
              <div style={{ marginBottom: '24px' }}>
                <h3 style={{ fontSize: '14px', color: 'var(--amber)', marginBottom: '8px' }}>Transcript Excerpt</h3>
                <div style={{ background: 'rgba(255,255,255,0.05)', padding: '12px', borderRadius: '8px', fontSize: '13px', lineHeight: '1.5', color: 'var(--dim)' }}>
                  {selectedClip.transcript_excerpt}...
                </div>
              </div>
            )}
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '32px', paddingTop: '16px', borderTop: '1px solid var(--glass-border)' }}>
              {selectedClip.clip_url && (
                <a href={selectedClip.clip_url} target="_blank" rel="noopener noreferrer" style={{ padding: '8px 16px', background: 'rgba(255,255,255,0.1)', color: 'var(--text)', borderRadius: '6px', textDecoration: 'none', fontSize: '13px', fontWeight: 600 }}>
                  Open Source Video ↗
                </a>
              )}
              
              <button 
                onClick={async () => {
                  if (confirm('Are you sure you want to delete this clip?')) {
                    await api.deleteCampaignClip(activeId, selectedClip.id);
                    setSelectedClip(null);
                    loadCampaign(activeId);
                  }
                }}
                style={{ padding: '8px 16px', background: 'rgba(255, 92, 73, 0.2)', color: 'var(--red)', border: '1px solid rgba(255, 92, 73, 0.4)', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}
              >
                Delete Clip
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}

function ClipCard({ clip, expanded, onToggle, onClick }: { clip: any, expanded: boolean, onToggle: () => void, onClick: () => void }) {
  void onClick;

  const getImageUrl = (path?: string) => {
    if (!path) return ''
    // If it's a full path, we need to map it to the media endpoint
    if (path.includes('campaigns')) {
      const parts = path.split(/campaigns[/\\]/)
      if (parts.length > 1) {
        return api.fileUrl(`campaigns/${parts[1].replace(/\\/g, '/')}`)
      }
    }
    return ''
  }

  return (
    <div 
      style={{ 
        border: '1px solid var(--border)', 
        borderRadius: '8px', 
        overflow: 'hidden',
        background: 'var(--panel)',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
      }}
    >
      <div 
        style={{ cursor: 'pointer', display: 'flex', padding: '12px', gap: '12px' }} 
        onClick={onToggle}
      >
        <div style={{ width: '80px', flexShrink: 0, aspectRatio: '9/16', background: '#000', borderRadius: '4px', overflow: 'hidden' }}>
          {clip.thumbnail_path ? (
            <img src={getImageUrl(clip.thumbnail_path)} style={{ width: '100%', height: '100%', objectFit: 'cover' }} alt="thumb" />
          ) : (
            <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '10px', color: 'var(--dim)' }}>No thumb</div>
          )}
        </div>
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <div style={{ fontWeight: 600, fontSize: '13px', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', marginBottom: '4px' }}>
            {clip.title || clip.clip_url}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--dim)', marginBottom: '8px' }}>
            {clip.channel || 'Unknown Channel'}
          </div>
          <div style={{ display: 'flex', gap: '12px', fontSize: '11px', color: 'var(--dim)' }}>
            <span><strong style={{ color: 'var(--fg)' }}>{clip.views || 0}</strong> views</span>
            {clip.likes !== undefined && <span><strong style={{ color: 'var(--fg)' }}>{clip.likes}</strong> likes</span>}
          </div>
        </div>
      </div>
      
      {expanded && (
        <div style={{ padding: '12px', borderTop: '1px solid var(--border)', background: 'var(--bg)', fontSize: '12px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          
          {clip.hook_text_overlay && (
            <div>
              <strong style={{ color: 'var(--dim)', fontSize: '11px', textTransform: 'uppercase' }}>Visual Hook Text:</strong>
              <div style={{ background: 'rgba(255, 235, 59, 0.1)', borderLeft: '2px solid #ffeb3b', padding: '8px', marginTop: '4px', borderRadius: '0 4px 4px 0' }}>
                {clip.hook_text_overlay}
              </div>
            </div>
          )}
          
          {clip.audio_hook && (
            <div>
              <strong style={{ color: 'var(--dim)', fontSize: '11px', textTransform: 'uppercase' }}>Audio Hook (First 5s):</strong>
              <div style={{ background: 'rgba(76, 175, 80, 0.1)', borderLeft: '2px solid #4caf50', padding: '8px', marginTop: '4px', borderRadius: '0 4px 4px 0' }}>
                {clip.audio_hook}
              </div>
            </div>
          )}
          
          {clip.role === 'mine' && (
            <div>
              <strong style={{ color: 'var(--dim)', fontSize: '11px', textTransform: 'uppercase', display: 'block', marginBottom: '8px' }}>Analytics (From Studio):</strong>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                <div style={{ background: 'var(--panel)', padding: '8px', borderRadius: '4px' }}>
                  <div style={{ color: 'var(--dim)', fontSize: '10px' }}>Avg View Dur.</div>
                  <div style={{ fontWeight: 600 }}>{clip.avg_view_duration_sec ? clip.avg_view_duration_sec + 's' : '-'}</div>
                </div>
                <div style={{ background: 'var(--panel)', padding: '8px', borderRadius: '4px' }}>
                  <div style={{ color: 'var(--dim)', fontSize: '10px' }}>Watch %</div>
                  <div style={{ fontWeight: 600 }}>{clip.watch_time_pct ? clip.watch_time_pct + '%' : '-'}</div>
                </div>
                <div style={{ background: 'var(--panel)', padding: '8px', borderRadius: '4px' }}>
                  <div style={{ color: 'var(--dim)', fontSize: '10px' }}>CTR</div>
                  <div style={{ fontWeight: 600 }}>{clip.ctr ? clip.ctr + '%' : '-'}</div>
                </div>
                <div style={{ background: 'var(--panel)', padding: '8px', borderRadius: '4px' }}>
                  <div style={{ color: 'var(--dim)', fontSize: '10px' }}>Impressions</div>
                  <div style={{ fontWeight: 600 }}>{clip.impressions || '-'}</div>
                </div>
              </div>
            </div>
          )}
          
        </div>
      )}
    </div>
  )
}
void ClipCard;
