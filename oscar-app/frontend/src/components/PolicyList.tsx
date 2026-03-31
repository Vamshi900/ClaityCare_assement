import type { Policy } from '../types'
import PolicyCard from './PolicyCard'

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
  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Search */}
      <div className="px-3 py-2 border-b border-gray-200">
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search policies..."
          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
        />
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-6 w-6 border-2 border-gray-300 border-t-blue-500" />
          </div>
        ) : policies.length === 0 ? (
          <div className="px-4 py-12 text-center">
            <p className="text-sm text-gray-500">No policies found.</p>
            <p className="text-xs text-gray-400 mt-1">Run Discovery first.</p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {policies.map((policy) => (
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
