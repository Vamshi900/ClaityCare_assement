import { useState, useEffect } from 'react'
import { api } from '../api/client'

export function useText(policyId: string | null) {
  const [text, setText] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!policyId) {
      setText(null)
      return
    }

    let cancelled = false

    async function fetchText() {
      setLoading(true)
      setError(null)
      try {
        const data = await api.getPolicyText(policyId!)
        if (!cancelled) setText(data)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to fetch text')
          setText(null)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchText()
    return () => {
      cancelled = true
    }
  }, [policyId])

  return { text, loading, error }
}
