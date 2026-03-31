import { useState, useEffect } from 'react'
import type { ExtractionVersion } from '../types'
import { api } from '../api/client'

export function useVersions(policyId: string | null) {
  const [versions, setVersions] = useState<ExtractionVersion[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!policyId) {
      setVersions([])
      return
    }

    let cancelled = false

    async function fetchVersions() {
      setLoading(true)
      try {
        const data = await api.getVersions(policyId!)
        if (!cancelled) setVersions(data)
      } catch {
        if (!cancelled) setVersions([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchVersions()
    return () => {
      cancelled = true
    }
  }, [policyId])

  return { versions, loading }
}
