import { useState, useEffect, useCallback } from 'react'
import type { Policy, Stats } from '../types'
import { api } from '../api/client'

export function usePolicies() {
  const [policies, setPolicies] = useState<Policy[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const [policiesData, statsData] = await Promise.all([
        api.getPolicies(search || undefined),
        api.getStats(),
      ])
      setPolicies(policiesData)
      setStats(statsData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch policies')
    } finally {
      setLoading(false)
    }
  }, [search])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const refresh = useCallback(() => {
    fetchData()
  }, [fetchData])

  return { policies, stats, search, setSearch, loading, error, refresh }
}
