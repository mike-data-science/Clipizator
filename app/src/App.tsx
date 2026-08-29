import { useCallback, useEffect, useRef, useState } from 'react'
import { api, listen } from './api'
import type { JobResults, JobSummary, PipelineEvent, SetupState } from './types'
import Onboarding from './components/Onboarding'
import Studio from './components/Studio'
import Review from './components/Review'
import Loop from './components/Loop'
import { Analytics } from './components/Analytics'
import { Queue } from './components/Queue'
import { TranscribeQueue } from './components/TranscribeQueue'
import './styles.css'

type View = 'boot' | 'onboarding' | 'studio' | 'review' | 'loop' | 'analytics' | 'queue' | 'transcribe_queue'

export default function App() {
  const [view, setView] = useState<View>('boot')
  const [setup, setSetup] = useState<SetupState | null>(null)
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [activeJob, setActiveJob] = useState<string | null>(null)
  const [results, setResults] = useState<JobResults | null>(null)
  const [stages, setStages] = useState<Record<string, { fraction: number; message: string }>>({})
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [prefilledSource, setPrefilledSource] = useState<string>('')
  
  const unlistenRef = useRef<(() => void) | null>(null)
  const activeJobRef = useRef<string | null>(null)
  activeJobRef.current = activeJob

  const refreshJobs = useCallback(() => {
    api.listJobs().then(setJobs).catch(() => setJobs([]))
  }, [])

  useEffect(() => {
    api.setupState()
      .then((s) => {
        setSetup(s)
        setView(s.onboarded ? 'analytics' : 'onboarding')
      })
      .catch((err) => {
        console.error('Failed to connect to backend:', err)
        setRunError('Cannot connect to the backend server. Is it running?')
      })
    refreshJobs()
  }, [refreshJobs])

  // Instagram loop: opportunistic sync on launch + hourly while open
  // (decision #12 — no background process, the app's own uptime is the
  // schedule). Fire-and-forget; the Loop screen re-reads on entry.
  useEffect(() => {
    const kick = () => {
      api
        .igStatus()
        .then((s) => (s.connected ? api.igSync() : null))
        .catch(() => null)
    }
    kick()
    const timer = window.setInterval(kick, 60 * 60 * 1000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    let disposed = false
    listen<PipelineEvent>('pipeline-event', ({ payload }: any) => {
      // Background queue jobs shouldn't hijack the Studio UI
      if (payload.source === 'queue') return

      if (payload.event === 'job' && payload.job_id) {
        setActiveJob(payload.job_id)
        setResults(null)
      } else if (payload.event === 'progress' && payload.stage) {
        if (!payload.job_id || !activeJobRef.current || payload.job_id === activeJobRef.current) {
          if (payload.job_id && !activeJobRef.current) {
            setActiveJob(payload.job_id)
          }
          setStages((prev) => ({
            ...prev,
            [payload.stage!]: {
              fraction: payload.fraction ?? -1,
              message: payload.message ?? ''
            }
          }))
        }
      } else if (payload.event === 'result') {
        setRunning(false)
        refreshJobs()
        const targetJobId = payload.job_id || activeJobRef.current
        if (payload.ok && targetJobId) {
          api.jobResults(targetJobId).then((r) => {
            setResults(r)
            setView('review')
          })
        } else if (!payload.ok) {
          setRunError(String(payload.error ?? 'Pipeline failed'))
        }
      } else if (payload.event === 'exited') {
        setRunning(false)
        setRunError('The pipeline exited unexpectedly. Resume the job to continue from its last checkpoint.')
      }
    }).then((un) => {
      if (disposed) un()
      else unlistenRef.current = un
    })
    return () => {
      disposed = true
      unlistenRef.current?.()
    }
  }, [refreshJobs])

  const startRun = useCallback(
    async (source: string, llm: string, geminiModel: string, captions: string, asrModel: string) => {
      setRunning(true)
      setRunError(null)
      setStages({})
      setResults(null)
      setActiveJob(null)
      try {
        const res = await api.runJob(source, llm, geminiModel, captions, asrModel)
        if (res && (res as any).job_id) {
          setActiveJob((res as any).job_id)
        }
      } catch (err: any) {
        setRunning(false)
        setRunError(err.message || 'Failed to start job')
      }
    },
    []
  )

  const startUpload = useCallback(
    async (file: File, llm: string, geminiModel: string, captions: string, asrModel: string) => {
      setRunning(true)
      setRunError(null)
      setStages({})
      setResults(null)
      setActiveJob(null)
      try {
        await api.uploadVideo(file, llm, geminiModel, captions, asrModel)
      } catch (err: any) {
        setRunning(false)
        setRunError(err.message || 'Upload failed')
      }
    },
    []
  )

  const openJob = useCallback(async (jobId: string) => {
    const r = await api.jobResults(jobId)
    setActiveJob(jobId)
    setResults(r)
    if (r.render?.outputs?.length) setView('review')
  }, [])

  const handleGoToStudio = useCallback((url: string) => {
    setPrefilledSource(url)
    setRunError(null)
    setResults(null)
    setActiveJob(null)
    setView('studio')
  }, [])

  if (view === 'boot') {
    return (
      <div className="boot" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', padding: '20px', textAlign: 'center' }}>
        {runError ? (
          <div style={{ color: 'var(--red)' }}>
            <p style={{ fontWeight: 'bold', marginBottom: '8px' }}>Error</p>
            <p>{runError}</p>
          </div>
        ) : (
          <p style={{ color: 'var(--faint)' }}>Loading...</p>
        )}
      </div>
    )
  }

  if (view === 'onboarding' && setup) {
    return (
      <Onboarding
        onDone={() => {
          api.markOnboarded()
          setSetup({ ...setup, onboarded: true })
          setView('analytics')
        }}
      />
    )
  }

  if (view === 'loop') {
    return <Loop onBack={() => setView('studio')} />
  }

  if (view === 'analytics') {
    return <Analytics 
      onBack={() => setView('studio')} 
      onSendToStudio={handleGoToStudio}
    />
  }

  if (view === 'queue') {
    return <Queue
      onSendToStudio={handleGoToStudio}
    />
  }

  if (view === 'transcribe_queue') {
    return <TranscribeQueue
      onSendToStudio={handleGoToStudio}
    />
  }

  if (view === 'review' && results) {
    return (
      <Review
        results={results}
        onBack={() => {
          setView('studio')
          refreshJobs()
        }}
        onRestyle={(captions, camera) => {
          setRunning(true)
          setRunError(null)
          setStages({})
          setActiveJob(results.job_id)
          setView('studio')
          api.resumeJob(results.job_id, undefined, captions, camera)
        }}
      />
    )
  }
  return (
    <Studio
      jobs={jobs}
      running={running}
      stages={stages}
      error={runError}
      initialSource={prefilledSource}
      onRun={startRun}
      onUpload={startUpload}
      onOpenLoop={() => {
        setPrefilledSource('')
        setView('loop')
      }}
      onOpenAnalytics={() => {
        setPrefilledSource('')
        setView('analytics')
      }}
      onOpenQueue={() => {
        setPrefilledSource('')
        setView('queue')
      }}
      onOpenTranscribeQueue={() => {
        setPrefilledSource('')
        setView('transcribe_queue')
      }}
      onOpenJob={openJob}
      onResume={(id, llm, geminiModel, asrModel) => {
        setRunning(true)
        setRunError(null)
        setStages({})
        setActiveJob(id)
        api.resumeJob(id, llm, geminiModel, undefined, undefined, asrModel)
      }}
      onDeleteJob={async (id) => {
        if (confirm('Are you sure you want to delete this session?')) {
          await api.deleteJob(id)
          if (activeJob === id) {
            setActiveJob(null)
            setView('studio')
          }
          refreshJobs()
        }
      }}
    />
  )
}
