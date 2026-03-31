import { useState, useMemo } from 'react'
import type { Policy } from '../types'
import PolicyCard from './PolicyCard'

const STATUS_PRIORITY: Record<string, number> = {
  validated: 0,
  extracted: 1,
  extracting: 2,
  extraction_failed: 3,
  downloaded: 4,
  downloading: 5,
  download_failed: 6,
  discovered: 7,
}

const FILTER_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'structured', label: 'Structured' },
  { value: 'downloaded', label: 'Downloaded' },
  { value: 'failed', label: 'Failed' },
]

interface PolicyListProps {
  policies: Policy[]
  search: string
  onSearchChange: (value: string) => void
  selectedId: string | null
  onSelect: (id: string) => void
  loading: boolean
}

export default function PolicyList({
  policies,
  search,
  onSearchChange,
  selectedId,
  onSelect,
  loading,
}: PolicyListProps) {
  const [filter, setFilter] = useState('all')

  const sortedAndFiltered = useMemo(() => {
    let filtered = policies
    if (filter === 'structured') {
      filtered = policies.filter(p => p.status === 'validated' || p.status === 'extracted')
    } else if (filter === 'downloaded') {
      filtered = policies.filter(p => p.status === 'downloaded')
    } else if (filter === 'failed') {
      filtered = policies.filter(p => p.status === 'extraction_failed' || p.status === 'download_failed')
    }
    return [...filtered].sort((a, b) => {
      const pa = STATUS_PRIORITY[a.status] ?? 9
      const pb = STATUS_PRIORITY[b.status] ?? 9
      if (pa !== pb) return pa - pb
      return (a.guideline_code || a.title).localeCompare(b.guideline_code || b.title)
    })
  }, [policies, filter])

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Search + Filter */}
      <div className="px-3 py-2 border-b border-gray-200 space-y-2">
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search policies..."
          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
        />
        <div className="flex gap-1">
          {FILTER_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => setFilter(opt.value)}
              className={`text-xs px-2 py-1 rounded-md transition-colors ${
                filter === opt.value
                  ? 'bg-blue-500 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {opt.label}
              {opt.value === 'all' && ` (${policies.length})`}
              {opt.value === 'structured' && ` (${policies.filter(p => p.status === 'validated' || p.status === 'extracted').length})`}
              {opt.value === 'failed' && ` (${policies.filter(p => p.status === 'extraction_failed' || p.status === 'download_failed').length})`}
            </button>
          ))}
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-6 w-6 border-2 border-gray-300 border-t-blue-500" />
          </div>
        ) : sortedAndFiltered.length === 0 ? (
          <div className="px-4 py-12 text-center">
            <p className="text-sm text-gray-500">No policies found.</p>
            <p className="text-xs text-gray-400 mt-1">
              {filter !== 'all' ? 'Try a different filter.' : 'Run Discovery first.'}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {sortedAndFiltered.map((policy) => (
              <PolicyCard
                key={policy.id}
                policy={policy}
                selected={policy.id === selectedId}
                onClick={() => onSelect(policy.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
