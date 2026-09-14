import { useCallback, useRef, useState } from 'react'
import { api } from './api'
import type { JobSummary } from './types'

const CACHE_KEY = 'clipizator.studio.rendered-jobs.v1'

function cachedJobs(): JobSummary[] {
  try {
    const cached = JSON.parse(sessionStorage.getItem(CACHE_KEY) || '[]')
    return Array.isArray(cached) ? cached.filter(job => job?.rendered && job.clip_count > 0) : []
  } catch {
    return []
  }
}

export function useStudioJobs() {
  const [jobs, setJobs] = useState<JobSummary[]>(cachedJobs)
  const [jobsLoading, setLoading] = useState(true)
  const [jobsError, setError] = useState<string | null>(null)
  const pending = useRef<Promise<void> | null>(null)

  const refreshJobs = useCallback(() => {
    if (pending.current) return pending.current
    setLoading(true)
    pending.current = api.listJobs().then(next => {
      setJobs(next)
      setError(null)
      try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(next)) } catch { /* Storage may be disabled. */ }
    }).catch(() => {
      // Keep the last successful list visible during a backend restart.
      setError('Could not refresh sessions. Reopen Studio to retry.')
    }).finally(() => {
      setLoading(false)
      pending.current = null
    })
    return pending.current
  }, [])

  return { jobs, jobsLoading, jobsError, refreshJobs }
}
