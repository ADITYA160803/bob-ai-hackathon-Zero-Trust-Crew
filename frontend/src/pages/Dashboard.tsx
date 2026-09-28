import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import type { CaseAnalysis, GraphNode, GraphEdge, RoleType, NodeType } from '../types'
import PatternBadge from '../components/PatternBadge'
import GraphView from '../components/GraphView'
import EntityPanel from '../components/EntityPanel'
import HierarchyView from '../components/HierarchyView'
import Timeline from '../components/Timeline'
import SuspectTable from '../components/SuspectTable'
import Brief from './Brief'

// ── Tab definitions ─────────────────────────────────────────────────────────
const TABS = ['Graph', 'Hierarchy', 'Timeline', 'Suspects', 'Brief'] as const
type Tab = (typeof TABS)[number]

// ── Role / type filter helpers ───────────────────────────────────────────────
const ALL_ROLES: RoleType[] = ['KINGPIN', 'HANDLER', 'MULE', 'OPERATOR', 'VICTIM', 'UNKNOWN']
const ALL_TYPES: NodeType[] = [
  'PERSON',
  'PHONE',
  'DEVICE',
  'BANK_ACCOUNT',
  'UPI_ID',
  'IP',
  'LOCATION',
]

const ROLE_COLOR: Record<RoleType | 'UNKNOWN', string> = {
  KINGPIN: '#EF4444',
  HANDLER: '#A78BFA',
  MULE: '#F59E0B',
  OPERATOR: '#F472B6',
  VICTIM: '#60A5FA',
  UNKNOWN: '#64748B',
}

function fmtInr(n: number) {
  if (n >= 1_00_000) return `₹${(n / 1_00_000).toFixed(1)}L`
  if (n >= 1_000) return `₹${(n / 1_000).toFixed(1)}K`
  return `₹${n}`
}

// ── Stat card ────────────────────────────────────────────────────────────────
function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-surface-2 border border-border rounded-card px-3 py-2 text-center min-w-[80px]">
      <div className="font-mono text-lg font-medium leading-tight" style={color ? { color } : {}}>
        {value}
      </div>
      <div className="text-[10px] text-text-muted uppercase tracking-wider mt-0.5">{label}</div>
    </div>
  )
}

// ── Filter sidebar ────────────────────────────────────────────────────────────
function FilterSidebar({
  roleFilter,
  typeFilter,
  onRoleToggle,
  onTypeToggle,
  onReset,
  nodes,
}: {
  roleFilter: RoleType[]
  typeFilter: NodeType[]
  onRoleToggle: (r: RoleType) => void
  onTypeToggle: (t: NodeType) => void
  onReset: () => void
  nodes: GraphNode[]
}) {
  const roleCounts = useMemo(() => {
    const m = new Map<string, number>()
    nodes.forEach((n) => m.set(n.role, (m.get(n.role) ?? 0) + 1))
    return m
  }, [nodes])

  const typeCounts = useMemo(() => {
    const m = new Map<string, number>()
    nodes.forEach((n) => m.set(n.type, (m.get(n.type) ?? 0) + 1))
    return m
  }, [nodes])

  const hasFilter = roleFilter.length > 0 || typeFilter.length > 0

  return (
    <aside className="w-48 shrink-0 bg-surface border-r border-border overflow-y-auto">
      <div className="px-3 py-3 border-b border-border flex items-center justify-between">
        <span className="text-xs font-medium text-text uppercase tracking-wider">Filters</span>
        {hasFilter && (
          <button
            onClick={onReset}
            className="text-[10px] text-primary hover:underline"
          >
            Reset
          </button>
        )}
      </div>

      {/* Role filter */}
      <div className="px-3 py-2 border-b border-border">
        <p className="text-[10px] text-text-muted uppercase tracking-wider mb-2">By Role</p>
        <ul className="space-y-0.5">
          {ALL_ROLES.map((role) => {
            const count = roleCounts.get(role) ?? 0
            if (count === 0) return null
            const active = roleFilter.includes(role)
            const color = ROLE_COLOR[role] ?? ROLE_COLOR.UNKNOWN
            return (
              <li key={role}>
                <button
                  onClick={() => onRoleToggle(role)}
                  className={`w-full text-left flex items-center justify-between gap-2 px-2 py-1
                             rounded text-xs transition-colors ${
                               active
                                 ? 'bg-surface-2'
                                 : 'hover:bg-surface-2'
                             }`}
                >
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span
                      className={`w-2 h-2 rounded-full shrink-0 transition-opacity ${
                        active ? 'opacity-100' : 'opacity-40'
                      }`}
                      style={{ backgroundColor: color }}
                    />
                    <span className={active ? 'text-text' : 'text-text-muted'}>
                      {role.charAt(0) + role.slice(1).toLowerCase()}
                    </span>
                  </div>
                  <span className="font-mono text-[10px] text-text-muted">{count}</span>
                </button>
              </li>
            )
          })}
        </ul>
      </div>

      {/* Type filter */}
      <div className="px-3 py-2">
        <p className="text-[10px] text-text-muted uppercase tracking-wider mb-2">By Type</p>
        <ul className="space-y-0.5">
          {ALL_TYPES.map((type) => {
            const count = typeCounts.get(type) ?? 0
            if (count === 0) return null
            const active = typeFilter.includes(type)
            return (
              <li key={type}>
                <button
                  onClick={() => onTypeToggle(type)}
                  className={`w-full text-left flex items-center justify-between gap-2 px-2 py-1
                             rounded text-xs transition-colors ${
                               active ? 'bg-surface-2' : 'hover:bg-surface-2'
                             }`}
                >
                  <span className={active ? 'text-text' : 'text-text-muted'}>
                    {type.replace(/_/g, ' ').toLowerCase()}
                  </span>
                  <span className="font-mono text-[10px] text-text-muted">{count}</span>
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </aside>
  )
}

// ── Main Dashboard ───────────────────────────────────────────────────────────
export default function Dashboard() {
  const navigate = useNavigate()
  const [data, setData] = useState<CaseAnalysis | null>(null)
  const [activeTab, setActiveTab] = useState<Tab>('Graph')
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [roleFilter, setRoleFilter] = useState<RoleType[]>([])
  const [typeFilter, setTypeFilter] = useState<NodeType[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)

  // Load data from sessionStorage (set by Upload page)
  useEffect(() => {
    const raw = sessionStorage.getItem('jaal_analysis')
    if (!raw) {
      setLoadError('No analysis data found. Please load a demo scenario from the upload page.')
      return
    }
    try {
      setData(JSON.parse(raw) as CaseAnalysis)
    } catch {
      setLoadError('Failed to parse analysis data.')
    }
  }, [])

  const connectedEdges = useMemo<GraphEdge[]>(() => {
    if (!data || !selectedNode) return []
    return data.graph.edges.filter(
      (e) => e.source === selectedNode.id || e.target === selectedNode.id,
    )
  }, [data, selectedNode])

  const toggleRole = (role: RoleType) =>
    setRoleFilter((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role],
    )

  const toggleType = (type: NodeType) =>
    setTypeFilter((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type],
    )

  // Loading / error states
  if (loadError) {
    return (
      <div className="min-h-screen bg-bg flex items-center justify-center p-8">
        <div className="card max-w-md text-center space-y-4">
          <p className="text-sm text-text-muted">{loadError}</p>
          <button onClick={() => navigate('/')} className="btn-primary">
            ← Back to Upload
          </button>
        </div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="min-h-screen bg-bg flex items-center justify-center">
        <div className="text-text-muted text-sm animate-pulse">Loading analysis…</div>
      </div>
    )
  }

  const { analysis, graph, case_title } = data

  return (
    <div className="h-screen flex flex-col bg-bg overflow-hidden">
      {/* ── Top bar ── */}
      <header className="flex items-center gap-4 px-4 py-2.5 bg-surface border-b border-border shrink-0">
        {/* Logo + title */}
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-2 shrink-0 hover:opacity-80 transition-opacity"
          aria-label="Back to upload"
        >
          <span className="font-heading text-lg font-bold text-primary tracking-tight">JAAL</span>
        </button>

        <div className="h-5 w-px bg-border" />

        <div className="min-w-0 flex-1">
          <h1 className="font-heading text-sm font-semibold text-text truncate">{case_title}</h1>
          <p className="text-[10px] font-mono text-text-muted">{data.case_id}</p>
        </div>

        {/* Pattern badge (compact) */}
        <div className="shrink-0">
          <PatternBadge pattern={analysis.pattern} variant="compact" />
        </div>

        {/* Stats */}
        <div className="hidden lg:flex items-center gap-2 shrink-0">
          <StatCard label="Loss" value={fmtInr(analysis.totals.loss_inr ?? 0)} color="#EF4444" />
          <StatCard label="Victims" value={String(analysis.totals.victims ?? '—')} />
          <StatCard label="Mules" value={String(analysis.totals.mules ?? '—')} color="#F59E0B" />
          {analysis.totals.accounts_involved != null && (
            <StatCard label="Accounts" value={String(analysis.totals.accounts_involved)} />
          )}
        </div>
      </header>

      {/* ── Tabs ── */}
      <nav className="flex items-center gap-0 px-4 bg-surface border-b border-border shrink-0"
           role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab}
            role="tab"
            aria-selected={activeTab === tab}
            onClick={() => setActiveTab(tab)}
            className={`tab ${activeTab === tab ? 'tab-active' : ''}`}
          >
            {tab}
          </button>
        ))}
      </nav>

      {/* ── Body ── */}
      <div className="flex-1 flex min-h-0">
        {/* Left sidebar: filters (only on Graph tab) */}
        {activeTab === 'Graph' && (
          <FilterSidebar
            roleFilter={roleFilter}
            typeFilter={typeFilter}
            onRoleToggle={toggleRole}
            onTypeToggle={toggleType}
            onReset={() => { setRoleFilter([]); setTypeFilter([]) }}
            nodes={graph.nodes}
          />
        )}

        {/* Center content */}
        <main
          className="flex flex-col min-h-0 flex-1"
          role="tabpanel"
          aria-label={`${activeTab} tab content`}
        >
          {activeTab === 'Graph' && (
            <GraphView
              graph={graph}
              selectedNodeId={selectedNode?.id ?? null}
              onNodeSelect={setSelectedNode}
              roleFilter={roleFilter}
              typeFilter={typeFilter}
            />
          )}
          {activeTab === 'Hierarchy' && (
            <HierarchyView
              levels={analysis.hierarchy?.levels ?? analysis.levels ?? []}
              nodes={graph.nodes}
              onSelect={(n) => { setSelectedNode(n); setActiveTab('Graph') }}
            />
          )}
          {activeTab === 'Timeline' && (
            <Timeline events={analysis.timeline ?? []} />
          )}
          {activeTab === 'Suspects' && (
            <SuspectTable
              roles={analysis.roles ?? []}
              nodes={graph.nodes}
              onSelect={(n) => { setSelectedNode(n); setActiveTab('Graph') }}
            />
          )}
          {activeTab === 'Brief' && <Brief caseId={data.case_id} />}
        </main>

        {/* Right sidebar: EntityPanel (always visible on Graph tab; also shown when node selected elsewhere) */}
        {(activeTab === 'Graph' || selectedNode) && (
          <div
            className="w-64 shrink-0 min-h-0 overflow-hidden"
            style={{ display: activeTab === 'Graph' || selectedNode ? 'flex' : 'none' }}
          >
            <EntityPanel
              node={selectedNode}
              connectedEdges={connectedEdges}
              onClose={() => setSelectedNode(null)}
            />
          </div>
        )}
      </div>
    </div>
  )
}
