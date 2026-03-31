import { useState } from 'react'
import type { RuleNode } from '../types'
import OperatorBadge from './OperatorBadge'

interface TreeNodeProps {
  node: RuleNode
  depth: number
  expandAll?: boolean
}

export default function TreeNode({ node, depth, expandAll }: TreeNodeProps) {
  if (!node) return null
  const isLeaf = !node.rules || node.rules.length === 0
  const [expanded, setExpanded] = useState(expandAll ?? depth < 2)

  const handleToggle = () => {
    if (!isLeaf) setExpanded((prev) => !prev)
  }

  // Determine border color based on node type
  const borderColor = isLeaf
    ? 'border-gray-300'
    : node.operator === 'AND'
      ? 'border-blue-400'
      : 'border-amber-400'

  return (
    <div className={`ml-${depth > 0 ? '4' : '0'}`} style={{ marginLeft: depth > 0 ? depth * 16 : 0 }}>
      <div
        className={`flex items-start gap-2 py-1.5 px-2 rounded-md border-l-2 ${borderColor} hover:bg-gray-50 transition-colors cursor-pointer`}
        onClick={handleToggle}
      >
        {/* Expand/Collapse indicator */}
        <span className="flex-shrink-0 w-4 text-gray-400 text-sm select-none mt-0.5">
          {isLeaf ? (
            <span className="text-green-500 text-xs">{'\u25CF'}</span>
          ) : expanded ? (
            '\u25BC'
          ) : (
            '\u25B6'
          )}
        </span>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-xs text-gray-400">{node.rule_id}</span>
            {node.operator && <OperatorBadge operator={node.operator} />}
          </div>
          <p className="text-sm text-gray-700 mt-0.5 leading-relaxed">{node.rule_text}</p>
        </div>
      </div>

      {/* Children */}
      {!isLeaf && expanded && (
        <div className="mt-1">
          {node.rules!.map((child) => (
            <TreeNode
              key={child.rule_id}
              node={child}
              depth={depth + 1}
              expandAll={expandAll}
            />
          ))}
        </div>
      )}
    </div>
  )
}
