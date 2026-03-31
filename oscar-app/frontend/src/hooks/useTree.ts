import { useState, useEffect } from 'react'
import type { CriteriaTree } from '../types'
import { api } from '../api/client'

export function useTree(policyId: string | null, version?: number) {
  const [tree, setTree] = useState<CriteriaTree | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!policyId) {
      setTree(null)
      return
    }

    let cancelled = false

    async function fetchTree() {
      setLoading(true)
      setError(null)
      try {
        const data = await api.getPolicyTree(policyId!, version)
        if (!cancelled) setTree(data)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to fetch tree')
          setTree(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchTree()
    return () => {
      cancelled = true
    }
  }, [policyId, version])

  return { tree, loading, error }
}
