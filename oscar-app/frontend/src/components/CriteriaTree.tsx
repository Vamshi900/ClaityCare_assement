import { useState } from 'react'
import type { CriteriaTree as CriteriaTreeType } from '../types'
import TreeNode from './TreeNode'

interface CriteriaTreeProps {
  tree: CriteriaTreeType
}

export default function CriteriaTree({ tree }: CriteriaTreeProps) {
  const [expandAll, setExpandAll] = useState<boolean | undefined>(undefined)

  // Handle various tree shapes — some have title/insurance_name, some don't
  const rootNode = tree?.rules ?? tree
  if (!rootNode) return <div className="text-gray-400 text-sm">No tree data available</div>

  return (
    <div className="mt-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-lg font-semibold text-gray-800">{tree?.title || 'Initial Criteria Tree'}</h3>
          <p className="text-xs text-gray-500">{tree?.insurance_name || 'Oscar Health'}</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setExpandAll(true)}
            className="text-xs px-3 py-1 rounded border border-gray-300 text-gray-600 hover:bg-gray-100 transition-colors"
          >
            Expand All
          </button>
          <button
            onClick={() => setExpandAll(false)}
            className="text-xs px-3 py-1 rounded border border-gray-300 text-gray-600 hover:bg-gray-100 transition-colors"
          >
            Collapse All
          </button>
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <TreeNode
          key={expandAll === undefined ? 'default' : String(expandAll)}
          node={rootNode as any}
          depth={0}
          expandAll={expandAll}
        />
      </div>
    </div>
  )
}
