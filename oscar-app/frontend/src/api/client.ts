import type { Policy, PolicyDetail, CriteriaTree, Stats, Job, ExtractionVersion } from '../types'

const API_URL = import.meta.env.VITE_API_URL || `${window.location.protocol}//${window.location.hostname}:8000`

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`API error ${res.status}: ${body}`)
  }
  return res.json()
}

export const api = {
  getPolicies(search?: string): Promise<Policy[]> {
    const params = search ? `?search=${encodeURIComponent(search)}` : ''
    return request<Policy[]>(`/api/policies${params}`)
  },

  getPolicy(id: string): Promise<PolicyDetail> {
    return request<PolicyDetail>(`/api/policies/${id}`)
  },

  async getPolicyTree(id: string, version?: number): Promise<CriteriaTree> {
    const params = version !== undefined ? `?version=${version}` : ''
    const data = await request<{ structured_json: CriteriaTree }>(`/api/policies/${id}/tree${params}`)
    return data.structured_json
  },

  getPdfUrl(id: string): string {
    return `${API_URL}/api/policies/${id}/pdf-url`
  },

  extractPolicy(id: string): Promise<{ message: string }> {
    return request<{ message: string }>(`/api/policies/${id}/extract`, {
      method: 'POST',
    })
  },

  retryPolicy(id: string): Promise<{ message: string }> {
    return request<{ message: string }>(`/api/policies/${id}/retry`, {
      method: 'POST',
    })
  },

  getVersions(id: string): Promise<ExtractionVersion[]> {
    return request<ExtractionVersion[]>(`/api/policies/${id}/versions`)
  },

  async getPolicyText(id: string): Promise<string> {
    const data = await request<{ text: string }>(`/api/policies/${id}/text`)
    return data.text
  },

  getStats(): Promise<Stats> {
    return request<Stats>('/api/stats')
  },

  getJobs(): Promise<Job[]> {
    return request<Job[]>('/api/jobs')
  },

  createJob(
    type: string,
    sourceUrl?: string,
    policyIds?: string[]
  ): Promise<Job> {
    return request<Job>('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({
        type,
        source_url: sourceUrl || undefined,
        policy_ids: policyIds || undefined,
      }),
    })
  },
}
