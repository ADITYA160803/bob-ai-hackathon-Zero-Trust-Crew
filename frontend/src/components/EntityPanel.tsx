import type { GraphNode, GraphEdge, RoleType } from '../types'

// Role color tokens from design.md 5.1
const ROLE_COLOR: Record<RoleType | 'UNKNOWN', string> = {
  KINGPIN: '#EF4444',
  HANDLER: '#A78BFA',
  MULE: '#F59E0B',
  OPERATOR: '#F472B6',
  VICTIM: '#60A5FA',
  UNKNOWN: '#64748B',
}

const ROLE_BG: Record<RoleType | 'UNKNOWN', string> = {
  KINGPIN: 'rgba(239,68,68,0.12)',
  HANDLER: 'rgba(167,139,250,0.12)',
  MULE: 'rgba(245,158,11,0.12)',
  OPERATOR: 'rgba(244,114,182,0.12)',
  VICTIM: 'rgba(96,165,250,0.12)',
  UNKNOWN: 'rgba(100,116,139,0.12)',
}

const TYPE_ICON: Record<string, string> = {
  PERSON: '👤',
  PHONE: '📱',
  DEVICE: '💻',
  BANK_ACCOUNT: '🏦',
  UPI_ID: '💸',
  IP: '🌐',
  LOCATION: '📍',
}

function RoleBadge({ role }: { role: RoleType }) {
  const color = ROLE_COLOR[role] ?? ROLE_COLOR.UNKNOWN
  const bg = ROLE_BG[role] ?? ROLE_BG.UNKNOWN
  return (
    <span
      className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium"
      style={{ color, backgroundColor: bg, border: `1px solid ${color}44` }}
    >
      {role.charAt(0) + role.slice(1).toLowerCase()}
    </span>
  )
}

function RiskBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  let color = '#22C55E'
  if (score >= 0.7) color = '#EF4444'
  else if (score >= 0.4) color = '#FACC15'

  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-text-muted">Risk Score</span>
        <span className="font-mono" style={{ color }}>{pct}%</span>
      </div>
      <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, backgroundColor: color }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
    </div>
  )
}

function AttrRow({ label, value }: { label: string; value: string | number | boolean }) {
  const isId =
    typeof value === 'string' &&
    (label.toLowerCase().includes('account') ||
      label.toLowerCase().includes('imei') ||
      label.toLowerCase().includes('number') ||
      label.toLowerCase().includes('upi') ||
      label.toLowerCase().includes('ifsc'))

  return (
    <div className="flex justify-between gap-3 py-1.5 border-b border-border last:border-0">
      <span className="text-xs text-text-muted capitalize shrink-0">
        {label.replace(/_/g, ' ')}
      </span>
      <span
        className={`text-xs text-right break-all ${
          isId ? 'font-mono text-text' : 'text-text'
        }`}
      >
        {String(value)}
      </span>
    </div>
  )
}

interface EntityPanelProps {
  node: GraphNode | null
  /** Edges connected to this node (both inbound and outbound) */
  connectedEdges?: GraphEdge[]
  onClose?: () => void
}

export default function EntityPanel({ node, connectedEdges = [], onClose }: EntityPanelProps) {
  if (!node) {
    return (
      <aside
        className="w-full h-full flex flex-col items-center justify-center gap-3 p-6
                   bg-surface border-l border-border"
        aria-label="Entity details panel"
      >
        <svg
          width="40"
          height="40"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#2A3550"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <p className="text-xs text-text-muted text-center leading-relaxed">
          Click any node in the graph to inspect its attributes, role, and evidence sources.
        </p>
      </aside>
    )
  }

  const icon = TYPE_ICON[node.type] ?? '❓'
  const attrs = Object.entries(node.attrs ?? {}).filter(
    ([, v]) => v !== null && v !== undefined && v !== '',
  )

  // Separate inbound vs outbound edges
  const outbound = connectedEdges.filter((e) => e.source === node.id)
  const inbound = connectedEdges.filter((e) => e.target === node.id)

  return (
    <aside
      className="w-full h-full flex flex-col bg-surface border-l border-border overflow-y-auto"
      aria-label={`Entity panel: ${node.label}`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 px-4 pt-4 pb-3 border-b border-border shrink-0">
        <div className="flex items-start gap-2 min-w-0">
          <span className="text-xl mt-0.5 shrink-0">{icon}</span>
          <div className="min-w-0">
            <p className="text-sm font-medium text-text truncate leading-tight">{node.label}</p>
            <p className="text-xs text-text-muted mt-0.5">
              {node.type.replace(/_/g, ' ').toLowerCase()}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <RoleBadge role={node.role as RoleType} />
          {onClose && (
            <button
              onClick={onClose}
              className="text-text-muted hover:text-text transition-colors text-sm leading-none"
              aria-label="Close entity panel"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Risk score bar */}
      <div className="px-4 py-3 border-b border-border shrink-0">
        <RiskBar score={node.risk_score} />
      </div>

      {/* Attributes */}
      {attrs.length > 0 && (
        <section className="px-4 py-3 border-b border-border shrink-0">
          <p className="text-[10px] text-text-muted uppercase tracking-wider mb-2">Attributes</p>
          <div>
            {attrs.map(([k, v]) => (
              <AttrRow key={k} label={k} value={v} />
            ))}
          </div>
        </section>
      )}

      {/* Connections */}
      {(outbound.length > 0 || inbound.length > 0) && (
        <section className="px-4 py-3 border-b border-border shrink-0">
          <p className="text-[10px] text-text-muted uppercase tracking-wider mb-2">
            Connections ({connectedEdges.length})
          </p>
          {outbound.length > 0 && (
            <div className="mb-2">
              <p className="text-[10px] text-text-muted mb-1.5 flex items-center gap-1">
                <span className="text-primary">→</span> Outbound ({outbound.length})
              </p>
              <ul className="space-y-1">
                {outbound.map((e) => (
                  <li
                    key={e.id}
                    className="text-xs bg-surface-2 rounded px-2 py-1.5 flex justify-between gap-2"
                  >
                    <span className="text-text-muted">{e.type.replace(/_/g, ' ')}</span>
                    <span className="font-mono text-text truncate text-right">→ {e.target}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {inbound.length > 0 && (
            <div>
              <p className="text-[10px] text-text-muted mb-1.5 flex items-center gap-1">
                <span className="text-handler">←</span> Inbound ({inbound.length})
              </p>
              <ul className="space-y-1">
                {inbound.map((e) => (
                  <li
                    key={e.id}
                    className="text-xs bg-surface-2 rounded px-2 py-1.5 flex justify-between gap-2"
                  >
                    <span className="text-text-muted">{e.type.replace(/_/g, ' ')}</span>
                    <span className="font-mono text-text truncate text-right">{e.source} →</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {/* Evidence sources */}
      {node.sources?.length > 0 && (
        <section className="px-4 py-3 shrink-0">
          <p className="text-[10px] text-text-muted uppercase tracking-wider mb-2">
            Evidence Sources ({node.sources.length})
          </p>
          <ul className="space-y-1.5">
            {node.sources.map((src, i) => (
              <li key={i} className="flex items-start gap-2 text-xs">
                <span className="text-success mt-0.5 shrink-0">◈</span>
                <span className="font-mono text-text-muted break-all">{src}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Disclaimer */}
      <div className="mt-auto px-4 py-3 border-t border-border shrink-0">
        <p className="text-[10px] text-text-muted leading-relaxed italic">
          Roles are risk indicators, not conclusions of guilt. Verify before legal action.
        </p>
      </div>
    </aside>
  )
}
