import { useCallback, useEffect, useRef, useState } from 'react'
import { api, listen } from './api'
import type { GenerationConfig, JobResults, PipelineEvent, ProjectLifecycle } from './types'
import { useStudioJobs } from './useStudioJobs'
import Studio from './components/Studio'
import Loop from './components/Loop'
import { Analytics } from './components/Analytics'
import { Queue } from './components/Queue'
import { TranscribeQueue } from './components/TranscribeQueue'
import ProjectClips from './components/ProjectClips'
import ProjectLifecycleDetail from './components/ProjectLifecycleDetail'
import ClipDetails from './components/ClipDetails'
import ClipEditor from './components/ClipEditor'
import Campaigns from './components/Campaigns'
import { AnalyzerVideos, AnalyzerVideoDetail, CreatorSources, CreatorSourceDetail, ResearchQueue } from './components/Analyzer'
import './styles.css'

type View = 'boot' | 'studio' | 'project-detail' | 'project' | 'clip-details' | 'clip-editor' | 'loop' | 'analytics' | 'campaigns' | 'queue' | 'transcribe_queue' | 'analyzer' | 'analyzer-detail' | 'analyzer-sources' | 'analyzer-source-detail' | 'analyzer-research-queue'

export default function App() {
  const [view, setView] = useState<View>('boot')
  const { jobs, jobsLoading, jobsError, refreshJobs } = useStudioJobs()
  const [activeJob, setActiveJob] = useState<string | null>(null)
  const [results, setResults] = useState<JobResults | null>(null)
  const [lifecycle, setLifecycle] = useState<ProjectLifecycle | null>(null)
  const [selectedClip, setSelectedClip] = useState(0)
  const [stages, setStages] = useState<Record<string, { fraction: number; message: string }>>({})
  const [activeStage, setActiveStage] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [prefilledSource, setPrefilledSource] = useState<string>('')
  const [analyzerJobId, setAnalyzerJobId] = useState<string | null>(null)
  const [creatorSourceId, setCreatorSourceId] = useState<number | null>(null)
  
  const unlistenRef = useRef<(() => void) | null>(null)
  const activeJobRef = useRef<string | null>(null)
  activeJobRef.current = activeJob

  useEffect(() => {
    if (view === 'studio') void refreshJobs()
  }, [view, refreshJobs])

  useEffect(() => {
    setView('studio')
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
      if (payload.source === 'queue' || payload.source === 'research_queue') return

      if (payload.event === 'job' && payload.job_id) {
        setActiveJob(payload.job_id)
        setActiveStage(null)
        setResults(null)
      } else if (payload.event === 'progress' && payload.stage) {
        if (!payload.job_id || !activeJobRef.current || payload.job_id === activeJobRef.current) {
          if (payload.job_id && !activeJobRef.current) {
            setActiveJob(payload.job_id)
          }
          setActiveStage(payload.stage)
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
            setView('project')
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
    async (source: string, llm: string, geminiModel: string, captions: string, asrModel: string, captionColor: string = 'white', generationConfig?: GenerationConfig) => {
      setRunning(true)
      setRunError(null)
      setStages({})
      setActiveStage(null)
      setResults(null)
      setActiveJob(null)
      try {
        const res = await api.runJob(source, llm, geminiModel, captions, asrModel, captionColor, generationConfig)
        if (res && (res as any).job_id) {
          setActiveJob((res as any).job_id)
          await refreshJobs()
        }
      } catch (err: any) {
        setRunning(false)
        setRunError(err.message || 'Failed to start job')
      }
    },
    [refreshJobs]
  )

  const startUpload = useCallback(
    async (file: File, llm: string, geminiModel: string, captions: string, asrModel: string, generationConfig?: GenerationConfig) => {
      setRunning(true)
      setRunError(null)
      setStages({})
      setActiveStage(null)
      setResults(null)
      setActiveJob(null)
      try {
        const res = await api.uploadVideo(file, llm, geminiModel, captions, asrModel, generationConfig)
        if (res && (res as any).job_id) {
          setActiveJob((res as any).job_id)
          await refreshJobs()
        }
      } catch (err: any) {
        setRunning(false)
        setRunError(err.message || 'Upload failed')
      }
    },
    [refreshJobs]
  )

  const openJob = useCallback(async (jobId: string, replaceHistory = false) => {
    const [r, detail] = await Promise.all([api.jobResults(jobId), api.jobLifecycle(jobId)])
    setActiveJob(jobId)
    setResults(r)
    setLifecycle(detail)
    const completed = detail.status === 'done' || detail.rendered
    window.history[replaceHistory || completed ? 'replaceState' : 'pushState'](null, '', `#project/${encodeURIComponent(jobId)}/${completed ? 'clips' : 'lifecycle'}`)
    setView(completed ? 'project' : 'project-detail')
  }, [])

  useEffect(() => {
    const openFromHash = () => {
      const match = window.location.hash.match(/^#project\/([^/]+)(?:\/(?:lifecycle|clips))?$/)
      if (match) void openJob(decodeURIComponent(match[1]), true)
    }
    openFromHash()
    window.addEventListener('popstate', openFromHash)
    return () => window.removeEventListener('popstate', openFromHash)
  }, [openJob])

  const handleGoToStudio = useCallback((url: string, jobId?: string) => {
    if (jobId) {
      openJob(jobId)
    } else {
      setPrefilledSource(url)
      setRunError(null)
      setResults(null)
      setActiveJob(null)
      setView('studio')
    }
  }, [openJob])

  const deleteProjects = useCallback(async (jobIds: string[]) => {
    for (const jobId of jobIds) await api.deleteJob(jobId)
    if (activeJob && jobIds.includes(activeJob)) {
      setActiveJob(null)
      setLifecycle(null)
      setResults(null)
      setView('studio')
    }
    await refreshJobs()
  }, [activeJob, refreshJobs])

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

  if (view === 'project' && results) {
    return <ProjectClips
      results={results}
      onBack={() => setView('studio')}
      onOpenClipDetails={(clipIndex) => { setSelectedClip(clipIndex); setView('clip-details') }}
      onEditClip={(clipIndex) => { setSelectedClip(clipIndex); setView('clip-editor') }}
      onOpenAnalytics={() => setView('analytics')}
      onOpenCampaigns={() => setView('campaigns')}
      onOpenLoop={() => setView('loop')}
      onOpenQueue={() => setView('queue')}
      onOpenTranscribeQueue={() => setView('transcribe_queue')}
    />
  }

  if (view === 'project-detail' && lifecycle) {
    return <ProjectLifecycleDetail
      lifecycle={lifecycle}
      activeJobId={activeJob}
      activeStage={activeStage}
      liveStages={stages}
      onBack={() => setView('studio')}
      onCompleted={() => { window.history.replaceState(null, '', `#project/${encodeURIComponent(lifecycle.job_id)}/clips`); setView('project') }}
      onDelete={async () => {
        await deleteProjects([lifecycle.job_id])
      }}
    />
  }

  if (view === 'clip-details' && results) {
    return <ClipDetails
      results={results}
      clipIndex={selectedClip}
      onBack={() => setView('project')}
      onEdit={() => setView('clip-editor')}
    />
  }

  if (view === 'clip-editor' && results) {
    return <div className="clip-editor-page"><ClipEditor jobId={results.job_id} clipIndex={selectedClip} onClose={() => setView('clip-details')} onRendered={() => { void api.jobResults(results.job_id).then(setResults) }} /></div>
  }

  if (view === 'campaigns') {
    return <Campaigns
      onBack={() => setView('studio')}
      onOpenProject={async (jobId) => {
        const campaignResults = await api.jobResults(jobId)
        setActiveJob(jobId)
        setResults(campaignResults)
        setView('project')
      }}
    />
  }

  if (view === 'analyzer') {
    return <AnalyzerVideos
      onBack={() => setView('studio')}
      onOpen={(jobId) => { setAnalyzerJobId(jobId); setView('analyzer-detail') }}
      onSources={() => setView('analyzer-sources')}
      onQueue={() => setView('analyzer-research-queue')}
    />
  }

  if (view === 'analyzer-detail' && analyzerJobId) {
    return <AnalyzerVideoDetail
      jobId={analyzerJobId}
      onBack={() => setView('analyzer')}
      onHome={() => setView('studio')}
      onSources={() => setView('analyzer-sources')}
      onQueue={() => setView('analyzer-research-queue')}
    />
  }

  if (view === 'analyzer-sources') {
    return <CreatorSources onBack={() => setView('analyzer')} onQueue={() => setView('analyzer-research-queue')} onOpen={(id) => { setCreatorSourceId(id); setView('analyzer-source-detail') }} />
  }

  if (view === 'analyzer-source-detail' && creatorSourceId !== null) {
    return <CreatorSourceDetail creatorId={creatorSourceId} onBack={() => setView('analyzer-sources')} onHome={() => setView('studio')} onQueue={() => setView('analyzer-research-queue')} />
  }

  if (view === 'analyzer-research-queue') {
    return <ResearchQueue onBack={() => setView('analyzer')} onSources={() => setView('analyzer-sources')} onOpen={(jobId) => { setAnalyzerJobId(jobId); setView('analyzer-detail') }} />
  }

  return (
    <Studio
      jobs={jobs}
      jobsLoading={jobsLoading}
      jobsError={jobsError}
      running={running}
      stages={stages}
      activeJobId={activeJob}
      activeStage={activeStage}
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
      onOpenAnalyzer={() => {
        setPrefilledSource('')
        setView('analyzer')
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
          await deleteProjects([id])
        }
      }}
      onDeleteJobs={deleteProjects}
    />
  )
}
