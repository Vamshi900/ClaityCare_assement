import type { Policy } from '../types'

interface PolicyCardProps {
  policy: Policy
  selected: boolean
  onClick: () => void
}

function getStatusBadge(status: string): { label: string; color: string } {
  switch (status) {
    case 'downloading':
      return { label: 'Downloading...', color: 'bg-blue-100 text-blue-700 animate-pulse' }
    case 'downloaded':
      return { label: 'Downloaded', color: 'bg-blue-100 text-blue-700' }
    case 'download_failed':
      return { label: 'Failed', color: 'bg-red-100 text-red-700' }
    case 'extracting':
      return { label: 'Extracting...', color: 'bg-purple-100 text-purple-700 animate-pulse' }
    case 'extracted':
      return { label: 'Extracted', color: 'bg-purple-100 text-purple-700' }
    case 'extraction_failed':
      return { label: 'Failed', color: 'bg-red-100 text-red-700' }
    case 'validated':
      return { label: 'Validated', color: 'bg-green-100 text-green-700' }
    case 'discovered':
    default:
      return { label: 'Discovered', color: 'bg-gray-100 text-gray-600' }
  }
}

export default function PolicyCard({ policy, selected, onClick }: PolicyCardProps) {
  const badge = getStatusBadge(policy.status)

  return (
    <div
      onClick={onClick}
      className={`px-3 py-2.5 cursor-pointer border-l-2 transition-colors ${
        selected
          ? 'border-blue-500 bg-blue-50'
          : 'border-transparent hover:bg-gray-50'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-gray-800 truncate">{policy.title}</p>
          {policy.guideline_code && (
            <p className="text-xs font-mono text-gray-400 mt-0.5">{policy.guideline_code}</p>
          )}
        </div>
        <span
          className={`text-xs px-2 py-0.5 rounded-full flex-shrink-0 ${badge.color}`}
        >
          {badge.label}
        </span>
      </div>
    </div>
  )
}
