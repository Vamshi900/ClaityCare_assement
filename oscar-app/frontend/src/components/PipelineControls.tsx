import { useState } from 'react'
import { api } from '../api/client'

interface PipelineControlsProps {
  onJobStarted: () => void
}

export default function PipelineControls({ onJobStarted }: PipelineControlsProps) {
  const [sourceUrl, setSourceUrl] = useState('')
  const [loadingType, setLoadingType] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const runJob = async (type: string) => {
    try {
      setLoadingType(type)
      setError(null)
      await api.createJob(type, sourceUrl || undefined)
      // Give the backend a moment to start processing, then refresh
      setTimeout(() => {
        onJobStarted()
      }, 3000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start job')
    } finally {
      setLoadingType(null)
    }
  }

  return (
    <div className="px-3 py-3 border-b border-gray-200 bg-white">
      <input
        type="text"
        value={sourceUrl}
        onChange={(e) => setSourceUrl(e.target.value)}
        placeholder="Source URL (default: Oscar Medical)"
        className="w-full px-3 py-1.5 text-xs border border-gray-300 rounded-md mb-2 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent"
      />
      <div className="flex gap-1.5">
        <button
          onClick={() => runJob('discover')}
          disabled={loadingType !== null}
          className="flex-1 text-xs font-medium px-2 py-1.5 rounded-md bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loadingType === 'discover' ? (
            <span className="flex items-center justify-center gap-1">
              <span className="animate-spin inline-block w-3 h-3 border border-white border-t-transparent rounded-full" />
              Running
            </span>
          ) : (
            '1. Discover'
          )}
        </button>
        <button
          onClick={() => runJob('download')}
          disabled={loadingType !== null}
          className="flex-1 text-xs font-medium px-2 py-1.5 rounded-md bg-green-500 text-white hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loadingType === 'download' ? (
            <span className="flex items-center justify-center gap-1">
              <span className="animate-spin inline-block w-3 h-3 border border-white border-t-transparent rounded-full" />
              Running
            </span>
          ) : (
            '2. Download'
          )}
        </button>
        <button
          onClick={() => runJob('structure')}
          disabled={loadingType !== null}
          className="flex-1 text-xs font-medium px-2 py-1.5 rounded-md bg-purple-500 text-white hover:bg-purple-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loadingType === 'structure' ? (
            <span className="flex items-center justify-center gap-1">
              <span className="animate-spin inline-block w-3 h-3 border border-white border-t-transparent rounded-full" />
              Running
            </span>
          ) : (
            '3. Structure'
          )}
        </button>
      </div>
      {error && (
        <p className="text-xs text-red-500 mt-1.5">{error}</p>
      )}
    </div>
  )
}
