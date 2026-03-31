import type { Stats } from '../types'

interface StatusBarProps {
  stats: Stats | null
}

export default function StatusBar({ stats }: StatusBarProps) {
  if (!stats) return null

  return (
    <div className="px-3 py-2 border-t border-gray-200 bg-gray-50">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-500">
          <span className="font-medium text-gray-700">{stats.total_policies}</span> Policies
        </span>
        <span className="text-gray-500">
          <span className="font-medium text-gray-700">{stats.total_downloaded}</span> Downloaded
        </span>
        <span className="text-gray-500">
          <span className="font-medium text-green-600">{stats.total_structured}</span> Structured
        </span>
        {(stats.total_failed_downloads > 0 || stats.total_validation_errors > 0) && (
          <span className="text-gray-500">
            <span className="font-medium text-red-500">
              {stats.total_failed_downloads + stats.total_validation_errors}
            </span>{' '}
            Failed
          </span>
        )}
      </div>
    </div>
  )
}
