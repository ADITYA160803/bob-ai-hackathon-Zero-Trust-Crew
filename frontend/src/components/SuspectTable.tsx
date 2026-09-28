/**
 * frontend/src/components/SuspectTable.tsx
 *
 * Sortable table of suspected actors from AnalysisResult.roles.
 * Columns: name/ID, role, risk score, reasons.
 * Roles are indicators only — not conclusions of guilt.
 */
import { useMemo, useState } from 'react'
import type { GraphNode, RoleScore, RoleType } from '../types'

const ROLE_COLOR: Record<RoleType | 'UNKNOWN', string> = {
  KINGPIN: '#EF4444',
  HANDLER: '#A78BFA',
  MULE: '#F59E0B',
  OPERATOR: '#F472B6',
  VICTIM: '#60A5FA',
  UNKNOWN: '#64748B',
}

type SortKey = 'label' | 'role' | 'score'
type SortDir = 'asc' | 'desc'

interface SuspectTableProps {
  roles: RoleScore[]
  nodes: GraphNode[]
  onSelect?: (n: GraphNode) => void
  /** If true, include VICTIMs in the table. Default: false. */
  showVictims?: boolean
}

export default function SuspectTable({
  roles,
  nodes,
  onSelect,
  showVictims = false,
}: SuspectTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('score')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const nodeMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])

  const rows = useMemo(() => {
    const filtered = showVictims ? roles : roles.filter((r) => r.role !== 'VICTIM')
    return [...filtered].sort((a, b) => {
      const nodeA = nodeMap.get(a.node_id)
      const nodeB = nodeMap.get(b.node_id)
      let cmp = 0
      if (sortKey === 'label') {
        cmp = (nodeA?.label ?? a.node_id).localeCompare(nodeB?.label ?? b.node_id)
      } else if (sortKey === 'role') {
        cmp = a.role.localeCompare(b.role)
      } else {
        cmp = a.score - b.score
      }
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [roles, nodeMap, sortKey, sortDir, showVictims])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const SortBtn = ({ k, label }: { k: SortKey; label: string }) => (
    <button
      onClick={() => toggleSort(k)}
      className="flex items-center gap-1 hover:text-primary transition-colors"
    >
      {label}
      <span className="text-[10px]">
        {sortKey === k ? (sortDir === 'asc' ? '↑' : '↓') : '↕'}
      </span>
    </button>
  )

  if (rows.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-muted text-sm">
        No suspect data available.
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="font-heading text-lg font-semibold mb-1 text-text">Suspected Actors</h2>
      <p className="text-xs text-text-muted mb-4">
        Roles are risk indicators only. Not conclusions of guilt. Verify before legal action.
      </p>
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-border text-text-muted">
            <th className="text-left px-3 py-2 font-medium">
              <SortBtn k="label" label="Name / ID" />
            </th>
            <th className="text-left px-3 py-2 font-medium">
              <SortBtn k="role" label="Suspected Role" />
            </th>
            <th className="text-left px-3 py-2 font-medium">
              <SortBtn k="score" label="Risk Score" />
            </th>
            <th className="text-left px-3 py-2 font-medium">Evidence Indicators</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const n = nodeMap.get(r.node_id)
            const color = ROLE_COLOR[r.role] ?? ROLE_COLOR.UNKNOWN
            const pct = Math.round(r.score * 100)
            return (
              <tr
                key={r.node_id}
                className="border-b border-border hover:bg-surface-2 cursor-pointer transition-colors"
                onClick={() => n && onSelect?.(n)}
              >
                <td className="px-3 py-2">
                  <span className="font-medium text-text">{n?.label ?? r.node_id}</span>
                  <span className="block font-mono text-[10px] text-text-muted">{r.node_id}</span>
                </td>
                <td className="px-3 py-2">
                  <span
                    className="px-2 py-0.5 rounded-full text-[10px] font-medium"
                    style={{ color, backgroundColor: `${color}22`, border: `1px solid ${color}44` }}
                  >
                    {r.role.charAt(0) + r.role.slice(1).toLowerCase()}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-16 bg-surface-2 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${pct}%`, backgroundColor: color }}
                      />
                    </div>
                    <span className="font-mono text-[10px]" style={{ color }}>
                      {pct}%
                    </span>
                  </div>
                </td>
                <td className="px-3 py-2 text-text-muted">
                  {r.why.slice(0, 2).join('; ')}
                  {r.why.length > 2 && (
                    <span className="text-primary"> +{r.why.length - 2} more</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
