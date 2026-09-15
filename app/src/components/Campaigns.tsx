import { useEffect, useState } from 'react'
import { api } from '../api'

interface Props { onBack: () => void; onOpenProject: (jobId: string) => void }

function fmtDate(value: unknown) {
  if (typeof value !== 'number') return null
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value * 1000))
}

export default function Campaigns({ onBack, onOpenProject }: Props) {
  const [campaigns, setCampaigns] = useState<any[]>([])
  const [active, setActive] = useState<any | null>(null)
  const [selectedVideo, setSelectedVideo] = useState<any | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function loadCampaigns() {
    setLoading(true)
    try { setCampaigns(await api.listCampaigns() as any[]) } catch (err) { setError(err instanceof Error ? err.message : 'Could not load campaigns.') } finally { setLoading(false) }
  }
  useEffect(() => { void loadCampaigns() }, [])
  async function openCampaign(campaign: any) {
    try { setActive(await api.getCampaign(campaign.id) as any); setSelectedVideo(null) } catch (err) { setError(err instanceof Error ? err.message : 'Could not open campaign.') }
  }

  if (selectedVideo && active) return <div className="campaign-page"><header className="campaign-header"><button className="detail-back" onClick={() => setSelectedVideo(null)}>Back to videos</button><div className="detail-breadcrumb">Campaigns <span>/</span> {active.name} <span>/</span> {selectedVideo.title || 'Video'}</div></header><main className="campaign-main campaign-video-detail"><p className="new-eyebrow">CAMPAIGN VIDEO</p><h1>{selectedVideo.title || selectedVideo.video_url || 'Untitled video'}</h1>{selectedVideo.thumbnail_path && <img className="campaign-detail-thumb" src={api.fileUrl(selectedVideo.thumbnail_path)} alt="" />}{selectedVideo.transcript_excerpt && <article><p className="campaign-label">Transcript excerpt</p><p>{selectedVideo.transcript_excerpt}</p></article>}<div className="campaign-video-facts"><span>{selectedVideo.channel || 'Source video'}</span>{selectedVideo.duration_sec && <span>{Math.round(selectedVideo.duration_sec)}s</span>}{selectedVideo.clip_count !== undefined && <span>{selectedVideo.clip_count} clips</span>}</div><div className="campaign-detail-actions">{selectedVideo.job_id && <button className="new-primary" onClick={() => onOpenProject(selectedVideo.job_id)}>Open generated clips</button>}{selectedVideo.video_url && <a className="detail-outline" href={selectedVideo.video_url} target="_blank" rel="noreferrer">Open source</a>}</div></main></div>

  if (active) {
    const videos = active.videos ?? []
    return <div className="campaign-page"><header className="campaign-header"><button className="detail-back" onClick={() => setActive(null)}>Back to campaigns</button><div className="detail-breadcrumb">Campaigns <span>/</span> {active.name}</div><button className="new-primary" onClick={() => setActive(null)}>All campaigns</button></header><main className="campaign-main"><section className="campaign-title"><div><p className="new-eyebrow">CAMPAIGN</p><h1>{active.name}</h1>{active.description && <p>{active.description}</p>}</div><div className="campaign-count"><strong>{videos.length}</strong><span>videos</span></div></section><div className="campaign-subhead"><div><h2>Videos</h2><p>Source videos and their generated clip work</p></div></div>{videos.length ? <div className="campaign-video-grid">{videos.map((video: any) => <button className="campaign-video-card" key={video.id ?? video.video_url} onClick={() => setSelectedVideo(video)}><div className="campaign-video-preview">{video.thumbnail_path ? <img src={api.fileUrl(video.thumbnail_path)} alt="" /> : <span>▶</span>}{video.duration_sec && <small>{Math.round(video.duration_sec)}s</small>}</div><div><b>{video.title || video.video_url || 'Untitled video'}</b><p>{video.channel || video.status || 'Campaign source'}</p><span>{video.clip_count ?? 0} clips {video.job_id ? '· ready to review' : ''}</span></div></button>)}</div> : <div className="campaign-empty">No videos have been added to this campaign yet.</div>}</main></div>
  }

  return <div className="campaign-page"><header className="campaign-header"><button className="detail-back" onClick={onBack}>Back to home</button><div className="detail-breadcrumb">Home <span>/</span> Campaigns</div></header><main className="campaign-main"><section className="campaign-title"><div><p className="new-eyebrow">CAMPAIGNS</p><h1>Campaign workspace</h1><p>Review the source videos and clips already organized around each campaign.</p></div></section>{error && <p className="campaign-error">{error}</p>}{loading ? <p className="campaign-empty">Loading campaigns...</p> : campaigns.length ? <div className="campaign-grid">{campaigns.map((campaign) => <button className="campaign-card" key={campaign.id} onClick={() => void openCampaign(campaign)}><div className="campaign-card-mark">{String(campaign.name || 'C').slice(0, 1).toUpperCase()}</div><div><b>{campaign.name}</b>{campaign.description && <p>{campaign.description}</p>}<span>{campaign.video_count ?? campaign.videos_count ?? 0} videos {campaign.clip_count !== undefined ? `· ${campaign.clip_count} clips` : ''}</span></div>{fmtDate(campaign.updated_at ?? campaign.created_at) && <time>{fmtDate(campaign.updated_at ?? campaign.created_at)}</time>}</button>)}</div> : <div className="campaign-empty">No campaigns yet.</div>}</main></div>
}
