import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { keys } from '@/lib/queries'
import type { Job, JobStatus } from '@/lib/types'

export interface StreamState {
  log: string
  status: JobStatus | null
  connected: boolean
}

/**
 * Follow a job's log live over SSE (/jobs/:id/stream). Falls back to polling
 * the job record if the stream cannot be opened. The log starts empty: the jobs list carries no
 * logs, and the stream replays the whole log from offset 0 (a finished job's log comes from useJob).
 */
export function useJobStream(job: Job | undefined): StreamState {
  const [state, setState] = useState<StreamState>({ log: '', status: job?.status ?? null, connected: false })
  const qc = useQueryClient()
  const id = job?.id
  const active = job ? job.status === 'running' || job.status === 'pending' : false

  useEffect(() => {
    if (!job) return
    setState({ log: '', status: job.status, connected: false })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  useEffect(() => {
    if (id == null || !active) return
    let closed = false
    let poll: ReturnType<typeof setInterval> | null = null
    const es = new EventSource(`/api/jobs/${id}/stream?offset=0`)
    let log = ''

    es.addEventListener('open', () => setState((s) => ({ ...s, connected: true })))
    es.addEventListener('log', (e) => {
      const data = JSON.parse((e as MessageEvent).data) as { offset: number; chunk: string }
      log += data.chunk
      setState((s) => ({ ...s, log }))
    })
    es.addEventListener('status', (e) => {
      const data = JSON.parse((e as MessageEvent).data) as { status: JobStatus }
      setState((s) => ({ ...s, status: data.status }))
    })
    es.addEventListener('end', (e) => {
      const data = JSON.parse((e as MessageEvent).data) as { status: JobStatus }
      setState((s) => ({ ...s, status: data.status, connected: false }))
      es.close()
      qc.invalidateQueries({ queryKey: keys.jobs })
      qc.invalidateQueries({ queryKey: keys.job(id) })
      qc.invalidateQueries({ queryKey: keys.jobStats(id) })
      // The runner has just upserted this run's listings: the verbale needs them fresh.
      qc.invalidateQueries({ queryKey: keys.listings })
    })
    es.onerror = () => {
      if (closed) return
      es.close()
      setState((s) => ({ ...s, connected: false }))
      // Fallback: poll the job record.
      poll = setInterval(async () => {
        try {
          const j = await api.job(id)
          setState({ log: j.log ?? '', status: j.status, connected: false })
          qc.setQueryData(keys.job(id), j)
          if (j.status === 'done' || j.status === 'failed') {
            if (poll) clearInterval(poll)
            qc.invalidateQueries({ queryKey: keys.jobs })
            qc.invalidateQueries({ queryKey: keys.jobStats(id) })
            qc.invalidateQueries({ queryKey: keys.listings })
          }
        } catch {
          /* keep trying */
        }
      }, 2000)
    }
    return () => {
      closed = true
      es.close()
      if (poll) clearInterval(poll)
    }
  }, [id, active, qc])

  return state
}
