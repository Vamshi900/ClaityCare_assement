import { useState, useEffect, useCallback } from 'react'
import type { PolicyDetail as PolicyDetailType } from '../types'
import { api } from '../api/client'
import { useTree } from '../hooks/useTree'
import { useVersions } from '../hooks/useVersions'
import { useText } from '../hooks/useText'
import CriteriaTree from './CriteriaTree'
import StateBar from './StateBar'

interface PolicyDetailProps {
  policyId: string | null
}

type TabId = 'tree' | 'text' | 'metadata'

export default function PolicyDetail({ policyId }: PolicyDetailProps) {
  const [policy, setPolicy] = useState<PolicyDetailType | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<TabId>('tree')
  const [selectedVersion, setSelectedVersion] = useState<number | undefined>(undefined)
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const hasTree = policy?.has_structured_tree
  const status = policy?.status || 'discovered'

  const { tree, loading: treeLoading, error: treeError } = useTree(
    policyId && hasTree ? policyId : null,
    selectedVersion
  )
  const { versions } = useVersions(
    policyId && hasTree ? policyId : null
  )
  const { text, loading: textLoading, error: textError } = useText(
    policyId && activeTab === 'text' && (status === 'extracted' || status === 'validated' || hasTree) ? policyId : null
  )

  const fetchPolicy = useCallback(async () => {
    if (!policyId) {
      setPolicy(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await api.getPolicy(policyId)
      setPolicy(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch policy')
      setPolicy(null)
    } finally {
      setLoading(false)
    }
  }, [policyId])

  useEffect(() => {
    setActiveTab('tree')
    setSelectedVersion(undefined)
    setActionError(null)
    fetchPolicy()
  }, [fetchPolicy])

  const handleExtract = async () => {
    if (!policyId) return
    setActionLoading(true)
    setActionError(null)
    try {
      await api.extractPolicy(policyId)
      // Give backend a moment to start, then refresh
      setTimeout(() => fetchPolicy(), 2000)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Extraction failed')
    } finally {
      setActionLoading(false)
    }
  }

  const handleRetry = async () => {
    if (!policyId) return
    setActionLoading(true)
    setActionError(null)
    try {
      await api.retryPolicy(policyId)
      setTimeout(() => fetchPolicy(), 2000)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Retry failed')
    } finally {
      setActionLoading(false)
    }
  }

  if (!policyId) {
    return (
      <div className="flex-1 flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="text-4xl text-gray-300 mb-3">&#128209;</div>
          <p className="text-gray-500 text-sm">Select a policy to view details</p>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-gray-300 border-t-blue-500" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-500 text-sm font-medium">Error loading policy</p>
          <p className="text-gray-400 text-xs mt-1">{error}</p>
        </div>
      </div>
    )
  }

  if (!policy) return null

  const currentVersion = versions.find(v => v.is_current)
  const totalVersions = versions.length
  const showTextTab = status === 'extracted' || status === 'validated' || hasTree
  const showMetadataTab = totalVersions > 0

  const tabs: { id: TabId; label: string; show: boolean }[] = [
    { id: 'tree', label: 'Tree', show: true },
    { id: 'text', label: 'Text', show: !!showTextTab },
    { id: 'metadata', label: 'Metadata', show: !!showMetadataTab },
  ]

  const canExtract = status === 'downloaded'
  const canRetry = status === 'download_failed' || status === 'extraction_failed'
  const canReextract = status === 'extracted' || status === 'validated'

  return (
    <div className="flex-1 overflow-y-auto p-6">
      {/* Header */}
      <div className="mb-2">
        <h2 className="text-xl font-bold text-gray-800">{policy.title}</h2>
        {policy.guideline_code && (
          <p className="font-mono text-sm text-gray-500 mt-1">{policy.guideline_code}</p>
        )}
        <div className="flex items-center gap-4 mt-3">
          <a
            href={policy.pdf_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-blue-600 hover:text-blue-800 underline"
          >
            View PDF
          </a>
          <a
            href={policy.source_page_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-blue-600 hover:text-blue-800 underline"
          >
            Source Page
          </a>
          <span className="text-xs text-gray-400">
            Discovered {new Date(policy.discovered_at).toLocaleDateString()}
          </span>
        </div>
      </div>

      {/* State Bar */}
      <StateBar status={status} />

      {/* Action Buttons */}
      <div className="flex items-center gap-2 mb-4">
        {canExtract && (
          <button
            onClick={handleExtract}
            disabled={actionLoading}
            className="text-xs font-medium px-3 py-1.5 rounded-md bg-purple-500 text-white hover:bg-purple-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {actionLoading ? 'Starting...' : 'Extract Now'}
          </button>
        )}
        {canReextract && (
          <button
            onClick={handleExtract}
            disabled={actionLoading}
            className="text-xs font-medium px-3 py-1.5 rounded-md bg-purple-100 text-purple-700 hover:bg-purple-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {actionLoading ? 'Starting...' : 'Re-extract \u21BB'}
          </button>
        )}
        {canRetry && (
          <button
            onClick={handleRetry}
            disabled={actionLoading}
            className="text-xs font-medium px-3 py-1.5 rounded-md bg-red-100 text-red-700 hover:bg-red-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {actionLoading ? 'Retrying...' : 'Retry'}
          </button>
        )}
        {totalVersions > 1 && currentVersion && (
          <span className="text-xs text-gray-500 ml-2">
            v{currentVersion.version} of {totalVersions}
            {' | '}
            <select
              value={selectedVersion ?? ''}
              onChange={(e) => setSelectedVersion(e.target.value ? Number(e.target.value) : undefined)}
              className="text-xs border border-gray-300 rounded px-1 py-0.5"
            >
              <option value="">Latest</option>
              {versions.map(v => (
                <option key={v.version} value={v.version}>v{v.version}</option>
              ))}
            </select>
          </span>
        )}
      </div>

      {actionError && (
        <div className="mb-4 text-xs text-red-600 bg-red-50 px-3 py-2 rounded">
          {actionError}
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-gray-200 mb-4">
        {tabs.filter(t => t.show).map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`text-sm font-medium px-4 py-2 -mb-px transition-colors ${
              activeTab === tab.id
                ? 'border-b-2 border-blue-500 text-blue-600'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'tree' && (
        <TreeTabContent
          policy={policy}
          status={status}
          tree={tree}
          treeLoading={treeLoading}
          treeError={treeError}
          onExtract={handleExtract}
          onRetry={handleRetry}
          actionLoading={actionLoading}
        />
      )}

      {activeTab === 'text' && (
        <TextTabContent
          text={text}
          loading={textLoading}
          error={textError}
        />
      )}

      {activeTab === 'metadata' && (
        <MetadataTabContent
          versions={versions}
          currentVersion={currentVersion ?? null}
          selectedVersion={selectedVersion}
        />
      )}
    </div>
  )
}

/* ---- Sub-components for tab content ---- */

function TreeTabContent({
  policy,
  status,
  tree,
  treeLoading,
  treeError,
  onExtract,
  onRetry,
  actionLoading,
}: {
  policy: PolicyDetailType
  status: string
  tree: import('../types').CriteriaTree | null
  treeLoading: boolean
  treeError: string | null
  onExtract: () => void
  onRetry: () => void
  actionLoading: boolean
}) {
  if (policy.has_structured_tree) {
    if (treeLoading) {
      return (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-6 w-6 border-2 border-gray-300 border-t-blue-500" />
        </div>
      )
    }
    if (treeError) {
      return (
        <div className="text-center py-8">
          <p className="text-red-500 text-sm">Failed to load criteria tree</p>
          <p className="text-gray-400 text-xs mt-1">{treeError}</p>
        </div>
      )
    }
    if (tree) {
      return <CriteriaTree tree={tree} />
    }
    return null
  }

  // No tree yet -- show status-based message
  return (
    <div className="border border-dashed border-gray-300 rounded-lg p-8 text-center">
      {(status === 'discovered' || status === 'downloading') && (
        <>
          <p className="text-gray-500 text-sm font-medium">Download the PDF first, then extract.</p>
          {status === 'downloading' && (
            <div className="flex items-center justify-center gap-2 mt-3">
              <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 border-t-blue-500" />
              <span className="text-xs text-blue-600">Downloading...</span>
            </div>
          )}
        </>
      )}

      {status === 'downloaded' && (
        <>
          <p className="text-gray-500 text-sm font-medium">Ready for extraction.</p>
          <button
            onClick={onExtract}
            disabled={actionLoading}
            className="mt-3 text-xs font-medium px-4 py-2 rounded-md bg-purple-500 text-white hover:bg-purple-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {actionLoading ? 'Starting...' : 'Extract Now'}
          </button>
        </>
      )}

      {status === 'extracting' && (
        <div className="flex flex-col items-center gap-2">
          <div className="animate-spin rounded-full h-6 w-6 border-2 border-gray-300 border-t-purple-500" />
          <p className="text-purple-600 text-sm font-medium">Extraction in progress...</p>
        </div>
      )}

      {status === 'extraction_failed' && (
        <>
          <p className="text-red-500 text-sm font-medium">
            Extraction failed{policy.structured_json === null ? '' : ''}
          </p>
          <button
            onClick={onRetry}
            disabled={actionLoading}
            className="mt-3 text-xs font-medium px-4 py-2 rounded-md bg-red-100 text-red-700 hover:bg-red-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {actionLoading ? 'Retrying...' : 'Retry'}
          </button>
        </>
      )}

      {status === 'download_failed' && (
        <>
          <p className="text-red-500 text-sm font-medium">Download failed.</p>
          <button
            onClick={onRetry}
            disabled={actionLoading}
            className="mt-3 text-xs font-medium px-4 py-2 rounded-md bg-red-100 text-red-700 hover:bg-red-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {actionLoading ? 'Retrying...' : 'Retry'}
          </button>
        </>
      )}
    </div>
  )
}

function TextTabContent({
  text,
  loading,
  error,
}: {
  text: string | null
  loading: boolean
  error: string | null
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-6 w-6 border-2 border-gray-300 border-t-blue-500" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-red-500 text-sm">Failed to load text</p>
        <p className="text-gray-400 text-xs mt-1">{error}</p>
      </div>
    )
  }

  if (!text) {
    return (
      <div className="text-center py-8 text-gray-400 text-sm">
        No extracted text available.
      </div>
    )
  }

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-lg overflow-auto max-h-[600px]">
      <pre className="p-4 text-xs text-gray-700 whitespace-pre-wrap font-mono leading-relaxed">
        <code>{text}</code>
      </pre>
    </div>
  )
}

function MetadataTabContent({
  versions,
  currentVersion,
  selectedVersion,
}: {
  versions: import('../types').ExtractionVersion[]
  currentVersion: import('../types').ExtractionVersion | null
  selectedVersion: number | undefined
}) {
  const displayVersion = selectedVersion !== undefined
    ? versions.find(v => v.version === selectedVersion) ?? currentVersion
    : currentVersion

  if (!displayVersion) {
    return (
      <div className="text-center py-8 text-gray-400 text-sm">
        No extraction metadata available.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h4 className="text-sm font-semibold text-gray-700 mb-3">Extraction Info</h4>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          <dt className="text-gray-500">Version</dt>
          <dd className="text-gray-800 font-medium">
            v{displayVersion.version}
            {displayVersion.is_current && (
              <span className="ml-1 text-green-600">(current)</span>
            )}
          </dd>

          <dt className="text-gray-500">Extracted At</dt>
          <dd className="text-gray-800">
            {new Date(displayVersion.structured_at).toLocaleString()}
          </dd>

          {displayVersion.validation_error && (
            <>
              <dt className="text-gray-500">Validation Error</dt>
              <dd className="text-red-600">{displayVersion.validation_error}</dd>
            </>
          )}
        </dl>
      </div>

      {displayVersion.llm_metadata && (
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <h4 className="text-sm font-semibold text-gray-700 mb-3">LLM Metadata</h4>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
            {Object.entries(displayVersion.llm_metadata).map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-gray-500">{key}</dt>
                <dd className="text-gray-800 break-all">
                  {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {versions.length > 1 && (
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <h4 className="text-sm font-semibold text-gray-700 mb-3">Version History</h4>
          <div className="space-y-1">
            {versions.map(v => (
              <div key={v.version} className={`flex items-center justify-between text-xs px-2 py-1.5 rounded ${
                v.version === displayVersion.version ? 'bg-blue-50' : 'hover:bg-gray-50'
              }`}>
                <span className="text-gray-700 font-medium">
                  v{v.version}
                  {v.is_current && <span className="ml-1 text-green-600">(current)</span>}
                </span>
                <span className="text-gray-400">
                  {new Date(v.structured_at).toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
