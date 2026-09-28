/**
 * frontend/src/components/HierarchyView.tsx
 *
 * Tiered hierarchy view: Kingpin → Handlers → Mules/Operators → Victims
 * Reads from AnalysisResult.levels and role colors from design.md tokens.
 */
import { useMemo } from 'react'
import type { GraphNode, RoleType } from '../types'

const ROLE_COLOR: Record<RoleType | 'UNKNOWN', string> = {
  KINGPIN: '#EF4444',
  HANDLER: '#A78BFA',
  MULE: '#F59E0B',
  OPERATOR: '#F472B6',
  VICTIM: '#60A5FA',
  UNKNOWN: '#64748B',
}

const LEVEL_LABELS = ['Kingpin', 'Handlers', 'Mules / Operators', 'Victims']

interface HierarchyViewProps {
  levels: string[][]
  nodes: GraphNode[]
  onSelect?: (n: GraphNode) => void
}

export default function HierarchyView({ levels, nodes, onSelect }: HierarchyViewProps) {
  const nodeMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])

  if (!levels || levels.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-muted text-sm">
        No hierarchy data available.
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="font-heading text-lg font-semibold mb-5 text-text">
        Organizational Hierarchy
      </h2>
      <div className="space-y-6">
        {levels.map((ids, li) => (
          <div key={li}>
            <p className="text-xs text-text-muted uppercase tracking-wider mb-2">
              {LEVEL_LABELS[li] ?? `Level ${li + 1}`}
            </p>
            <div className="flex flex-wrap gap-2">
              {ids.map((id) => {
                const n = nodeMap.get(id)
                const color = n
                  ? (ROLE_COLOR[n.role as RoleType] ?? ROLE_COLOR.UNKNOWN)
                  : '#64748B'
                return (
                  <button
                    key={id}
                    onClick={() => n && onSelect?.(n)}
                    className="px-3 py-1.5 rounded-full text-xs font-medium border transition-colors
                               hover:bg-surface-2 cursor-pointer"
                    style={{ borderColor: color, color }}
                    title={n?.label ?? id}
                  >
                    {n?.label ?? id}
                  </button>
                )
              })}
            </div>
            {li < levels.length - 1 && (
              <div className="flex items-center justify-center mt-4">
                <span className="text-text-muted text-xl">↓</span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
