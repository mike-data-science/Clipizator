import { useEffect, useState } from 'react'
import { api, listen } from '../api'

interface QueueItem {
  campaign_id: string
  campaign_name: string
  video_url: string
  title?: string
  job_id?: string
}

export function TranscribeQueue({ onSendToStudio }: { onSendToStudio: (url: string) => void }) {
  const [items, setItems] = useState<QueueItem[]>([])
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState<Record<string, boolean>>({})
  const [stages, setStages] = useState<Record<string, { fraction: number; message: string }>>({})
  const [completed, setCompleted] = useState<Record<string, boolean>>({})

  useEffect(() => {
    loadQueue()
  }, [])

  useEffect(() => {
    let unlisten: (() => void) | undefined
    let disposed = false
    
    listen('pipeline-event', ({ payload }: any) => {
      if (payload.event === 'progress' && payload.job_id) {
        setStages(prev => ({
          ...prev,
          [payload.job_id]: {
            fraction: payload.fraction ?? -1,
            message: payload.message ?? ''
          }
        }))
      } else if (payload.event === 'result' && payload.job_id) {
        setRunning(prev => ({ ...prev, [payload.job_id]: false }))
        setCompleted(prev => ({ ...prev, [payload.job_id]: true }))
        setStages(prev => {
          const next = { ...prev }
          delete next[payload.job_id]
          return next
        })
        loadQueue() // refresh list to see if it's still pending
      } else if (payload.event === 'exited' && payload.job_id) {
        setRunning(prev => ({ ...prev, [payload.job_id]: false }))
      }
    }).then(un => {
      if (disposed) un()
      else unlisten = un
    })
    
    return () => {
      disposed = true
      unlisten?.()
    }
  }, [])

  // Auto-run logic
  useEffect(() => {
    if (items.length === 0) return
    const currentRunning = Object.values(running).filter(Boolean).length
    if (currentRunning < 2) {
      const pending = items.find(item => !running[item.video_url] && !completed[item.job_id || ''])
      if (pending) {
        handleRunItem(pending)
      }
    }
  }, [items, running, completed])

  async function loadQueue() {
    setLoading(true)
    try {
      const data = await fetch(`/api/queue/pending_transcribe`).then(r => r.json())
      setItems(data)
    } catch (err) {
      console.error('Failed to load queue:', err)
    } finally {
      setLoading(false)
    }
  }

  async function handleRunItem(item: QueueItem) {
    if (running[item.video_url]) return
    setRunning(prev => ({ ...prev, [item.video_url]: true }))
    
    try {
      const res = await fetch(`/api/queue/run_transcribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_url: item.video_url,
          campaign_id: item.campaign_id
        })
      }).then(r => r.json())
      
      if (!res.ok) {
        throw new Error(res.error || 'Failed to start transcribe job')
      }
    } catch (err) {
      console.error(err)
      setRunning(prev => ({ ...prev, [item.video_url]: false }))
    }
  }

  return (
    <div className="analytics" style={{ flex: 1, padding: '40px', overflowY: 'auto' }}>
      <header style={{ marginBottom: '40px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <h1 style={{ fontSize: '32px', margin: '0 0 8px 0' }}>Transcribe Queue</h1>
          <p style={{ color: 'var(--dim)', margin: 0 }}>
            Videos that are downloaded but still need audio extraction (transcription).
          </p>
        </div>
        <button onClick={loadQueue} className="btn-ghost" disabled={loading}>
          {loading ? 'Refreshing...' : 'Refresh Queue'}
        </button>
      </header>
      
      {items.length === 0 ? (
        <div className="empty-state">
          <p>The queue is empty.</p>
          <p style={{ fontSize: '13px' }}>All downloaded videos have been transcribed.</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {items.map(item => {
            const isRunning = running[item.video_url]
            const isCompleted = completed[item.job_id || '']
            const stage = stages[item.job_id || '']
            
            return (
              <div 
                key={item.video_url} 
                className="dashboard-card" 
                style={{ 
                  flexDirection: 'row', 
                  alignItems: 'center', 
                  justifyContent: 'space-between', 
                  gap: '24px',
                  padding: '24px'
                }}
              >
                {(() => {
                  const ytid = item.video_url.includes('v=') ? item.video_url.split('v=')[1]?.split('&')[0] : item.video_url.split('youtu.be/')[1]?.split('?')[0];
                  return (
                    <div style={{ width: '120px', height: '68px', borderRadius: '4px', overflow: 'hidden', flexShrink: 0, background: 'var(--panel-hover)' }}>
                      {ytid && (
                        <img src={`https://img.youtube.com/vi/${ytid}/mqdefault.jpg`} style={{ width: '100%', height: '100%', objectFit: 'cover' }} alt="thumbnail" />
                      )}
                    </div>
                  );
                })()}
                <div style={{ flex: 1, textAlign: 'left' }}>
                  <h3 style={{ margin: '0 0 8px 0', fontSize: '16px', fontWeight: 600, borderBottom: 'none', paddingBottom: 0 }}>{item.title || item.video_url}</h3>
                  <div style={{ fontSize: '13px', color: 'var(--dim)', display: 'flex', gap: '16px' }}>
                    <span>Campaign: <strong style={{ color: 'var(--fg)' }}>{item.campaign_name}</strong></span>
                    <span>Status: <span style={{ color: isCompleted ? '#4caf50' : (isRunning ? 'var(--primary)' : 'var(--amber)') }}>{isCompleted ? 'Transcribed' : (isRunning ? (stage?.message || 'Transcribing...') : 'Pending')}</span></span>
                  </div>
                </div>
                
                <div style={{ minWidth: '200px', display: 'flex', flexDirection: 'column', gap: '8px', alignItems: 'flex-end' }}>
                  <div style={{ width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '6px' }}>
                    <span style={{ fontSize: '12px', color: isCompleted ? '#4caf50' : (isRunning ? 'var(--primary)' : 'var(--dim)'), fontFamily: 'monospace', fontWeight: 600 }}>
                      {isCompleted ? '100%' : isRunning && stage?.fraction !== undefined && stage.fraction >= 0 ? `${Math.floor(stage.fraction * 100)}%` : '0%'}
                    </span>
                    <div style={{ width: '100%', height: '6px', background: 'var(--border)', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{ height: '100%', background: isCompleted ? '#4caf50' : 'var(--primary)', width: isCompleted ? '100%' : `${isRunning ? Math.max(0, stage?.fraction || 0) * 100 : 0}%`, transition: 'width 0.3s' }} />
                    </div>
                  </div>
                  {isCompleted && (
                    <button 
                      onClick={() => onSendToStudio(item.video_url)} 
                      className="btn-primary"
                    >
                      Open in Studio →
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
