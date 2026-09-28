import React, { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import type { CaseAnalysis, GraphNode, GraphEdge, RoleType, NodeType } from '../types'
import PatternBadge from '../components/PatternBadge'
import GraphView from '../components/GraphView'
import EntityPanel from '../components/EntityPanel'

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

function fmt(n: number) {
  return new Intl.NumberFormat('en-IN').format(n)
}

function fmtInr(n: number) {
  if (n >= 1_00_000) return `₹${(n / 1_00_000).toFixed(1)}L`
  if (n >= 1_000) return `₹${(n / 1_000).toFixed(1)}K`
  return `₹${n}`
}

function fmtDate(ts: string) {
  return new Date(ts).toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
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

// ── Hierarchy tab ────────────────────────────────────────────────────────────
function HierarchyTab({
  levels,
  nodes,
  onSelect,
}: {
  levels: string[][]
  nodes: GraphNode[]
  onSelect: (n: GraphNode) => void
}) {
  const nodeMap = useMemo(
    () => new Map(nodes.map((n) => [n.id, n])),
    [nodes],
  )
  const levelLabels = ['Kingpin', 'Handlers', 'Mules / Operators', 'Victims']

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="font-heading text-lg font-semibold mb-5 text-text">
        Organizational Hierarchy
      </h2>
      <div className="space-y-6">
        {levels.map((ids, li) => (
          <div key={li}>
            <p className="text-xs text-text-muted uppercase tracking-wider mb-2">
              {levelLabels[li] ?? `Level ${li + 1}`}
            </p>
            <div className="flex flex-wrap gap-2">
              {ids.map((id) => {
                const n = nodeMap.get(id)
                const color = n ? ROLE_COLOR[n.role as RoleType] ?? ROLE_COLOR.UNKNOWN : '#64748B'
                return (
                  <button
                    key={id}
                    onClick={() => n && onSelect(n)}
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

// ── Timeline tab ─────────────────────────────────────────────────────────────
function TimelineTab({ events }: { events: { ts: string; event: string }[] }) {
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="font-heading text-lg font-semibold mb-5 text-text">Event Timeline</h2>
      <ol className="relative border-l border-border ml-4 space-y-0">
        {events.map((ev, i) => (
          <li key={i} className="mb-6 ml-6 relative">
            <span
              className="absolute -left-[25px] flex items-center justify-center w-4 h-4
                         rounded-full bg-surface border-2 border-primary text-[8px] text-primary font-mono"
            >
              {i + 1}
            </span>
            <time className="text-[11px] font-mono text-text-muted block mb-0.5">
              {fmtDate(ev.ts)}
            </time>
            <p className="text-sm text-text leading-snug">{ev.event}</p>
          </li>
        ))}
      </ol>
    </div>
  )
}

// ── Suspects tab ─────────────────────────────────────────────────────────────
function SuspectsTab({
  roles,
  nodes,
  onSelect,
}: {
  roles: { node_id: string; role: RoleType; score: number; why: string[] }[]
  nodes: GraphNode[]
  onSelect: (n: GraphNode) => void
}) {
  const nodeMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
  const suspects = roles.filter((r) => r.role !== 'VICTIM')

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="font-heading text-lg font-semibold mb-1 text-text">Suspected Actors</h2>
      <p className="text-xs text-text-muted mb-5">
        Roles are risk indicators. Verify before legal action.
      </p>
      <div className="space-y-3">
        {suspects.map((r) => {
          const n = nodeMap.get(r.node_id)
          const color = ROLE_COLOR[r.role] ?? ROLE_COLOR.UNKNOWN
          const pct = Math.round(r.score * 100)
          return (
            <button
              key={r.node_id}
              onClick={() => n && onSelect(n)}
              className="w-full text-left bg-surface border border-border rounded-card px-4 py-3
                         hover:border-primary transition-colors"
            >
              <div className="flex items-start justify-between gap-3 mb-2">
                <div>
                  <span className="text-sm font-medium text-text">
                    {n?.label ?? r.node_id}
                  </span>
                  <span
                    className="ml-2 text-xs px-2 py-0.5 rounded-full"
                    style={{ color, backgroundColor: `${color}22`, border: `1px solid ${color}44` }}
                  >
                    {r.role.charAt(0) + r.role.slice(1).toLowerCase()}
                  </span>
                </div>
                <span className="font-mono text-xs shrink-0" style={{ color }}>
                  {pct}%
                </span>
              </div>
              <div className="h-1 bg-surface-2 rounded-full overflow-hidden mb-2">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${pct}%`, backgroundColor: color }}
                />
              </div>
              <ul className="space-y-0.5">
                {r.why.map((w, i) => (
                  <li key={i} className="text-xs text-text-muted flex gap-1.5">
                    <span className="text-text-muted shrink-0">•</span> {w}
                  </li>
                ))}
              </ul>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Brief tab ─────────────────────────────────────────────────────────────────
function BriefTab({ data }: { data: CaseAnalysis }) {
  const { analysis, graph, case_id, case_title, created_at } = data
  const victims = graph.nodes.filter((n) => n.role === 'VICTIM')
  const accused = analysis.roles.filter((r) => r.role !== 'VICTIM')
  const transfers = graph.edges.filter((e) => e.type === 'TRANSFERRED_TO')

  return (
    <div className="flex-1 overflow-y-auto p-6 max-w-3xl mx-auto">
      {/* Disclaimer banner */}
      <div className="border border-warning bg-warning bg-opacity-10 rounded-card px-4 py-2 mb-5 text-sm text-warning">
        ⚠ AI-assisted analysis. Requires verification by the investigating officer before legal action.
      </div>

      {/* Header */}
      <h2 className="font-heading text-xl font-bold text-text mb-1">{case_title}</h2>
      <p className="text-xs font-mono text-text-muted mb-5">
        Case #{case_id} · Generated {fmtDate(created_at)}
      </p>

      <Section title="Case Summary">
        <p className="text-sm text-text leading-relaxed">
          A suspected {data.analysis.pattern.label} fraud ring was identified involving{' '}
          {analysis.totals.victims} victims and an estimated loss of{' '}
          {fmtInr(analysis.totals.loss_inr)}. The ring appears to operate from Jharkhand using
          SIM-swap techniques to intercept OTPs, layering funds through {analysis.totals.mules}{' '}
          mule accounts before reaching the kingpin.
        </p>
      </Section>

      <Section title="Complainants / Victims">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-border">
              <Th>Node ID</Th>
              <Th>Label</Th>
              <Th>Sources</Th>
            </tr>
          </thead>
          <tbody>
            {victims.map((v) => (
              <tr key={v.id} className="border-b border-border hover:bg-surface-2">
                <Td mono>{v.id}</Td>
                <Td>{v.label}</Td>
                <Td mono>{v.sources.join(', ')}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Accused & Suspected Roles">
        <p className="text-xs text-text-muted mb-2 italic">
          The following are suspected roles — indicators only. To be verified by the IO.
        </p>
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-border">
              <Th>Node ID</Th>
              <Th>Suspected Role</Th>
              <Th>Score</Th>
              <Th>Indicators</Th>
            </tr>
          </thead>
          <tbody>
            {accused.map((r) => {
              const color = ROLE_COLOR[r.role] ?? ROLE_COLOR.UNKNOWN
              return (
                <tr key={r.node_id} className="border-b border-border hover:bg-surface-2">
                  <Td mono>{r.node_id}</Td>
                  <Td>
                    <span
                      className="px-1.5 py-0.5 rounded text-[10px]"
                      style={{ color, backgroundColor: `${color}22` }}
                    >
                      {r.role}
                    </span>
                  </Td>
                  <Td mono>{Math.round(r.score * 100)}%</Td>
                  <Td>{r.why.join('; ')}</Td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </Section>

      <Section title="Financial Trail">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-border">
              <Th>Txn ID</Th>
              <Th>From</Th>
              <Th>To</Th>
              <Th>Amount</Th>
              <Th>Timestamp</Th>
              <Th>Evidence</Th>
            </tr>
          </thead>
          <tbody>
            {transfers.map((e) => (
              <tr key={e.id} className="border-b border-border hover:bg-surface-2">
                <Td mono>{e.id}</Td>
                <Td mono>{e.source}</Td>
                <Td mono>{e.target}</Td>
                <Td mono>₹{fmt(Number(e.attrs?.amount ?? 0))}</Td>
                <Td mono>
                  {e.attrs?.ts ? fmtDate(String(e.attrs.ts)) : '—'}
                </Td>
                <Td mono>{e.evidence}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Digital Evidence Table">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-border">
              <Th>Type</Th>
              <Th>Identifier</Th>
              <Th>Role</Th>
              <Th>Sources</Th>
            </tr>
          </thead>
          <tbody>
            {graph.nodes
              .filter((n) => n.type !== 'PERSON')
              .map((n) => (
                <tr key={n.id} className="border-b border-border hover:bg-surface-2">
                  <Td>{n.type.replace(/_/g, ' ')}</Td>
                  <Td mono>{n.label}</Td>
                  <Td>{n.role}</Td>
                  <Td mono>{n.sources.join(', ')}</Td>
                </tr>
              ))}
          </tbody>
        </table>
      </Section>

      <Section title="Suggested Legal Sections">
        <p className="text-xs text-text-muted mb-2 italic">
          Suggested only. To be verified with IO and legal counsel.
        </p>
        <ul className="text-sm space-y-1.5">
          {[
            'IT Act §66C — Identity theft',
            'IT Act §66D — Cheating by personation using computer resources',
            'BNS §318 — Cheating',
            'BNS §61 — Criminal conspiracy',
            'PMLA — Money laundering (mule account layering)',
          ].map((s) => (
            <li key={s} className="flex gap-2 text-text-muted">
              <span className="text-text-muted shrink-0">§</span>
              <span>{s}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Recommended Actions">
        <ol className="text-sm space-y-2 list-none">
          {[
            { priority: 'HIGH', action: `Freeze bank accounts: ${graph.nodes.filter(n=>n.type==='BANK_ACCOUNT'&&n.role!=='VICTIM').map(n=>n.label).join(', ')}` },
            { priority: 'HIGH', action: `Block SIMs / IMEIs associated with ${graph.nodes.filter(n=>n.type==='PHONE'||n.type==='DEVICE').map(n=>n.label).join(', ')}` },
            { priority: 'MED', action: 'Issue notices to HDFC, SBI, PNB, ICICI, Axis Bank for KYC and transaction records' },
            { priority: 'MED', action: 'Issue CAF (Customer Application Form) requests to Airtel, Jio for SIM swap logs' },
            { priority: 'MED', action: 'Arrest priority: Suspected Kingpin (PE_VIKRAM) → Handlers (PE_ROHIT, PE_SANJAY)' },
            { priority: 'LOW', action: 'Cross-link with NCRP portal for matching IMEI/phone patterns in other districts' },
          ].map((item, i) => (
            <li key={i} className="flex gap-3">
              <span
                className={`text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0 mt-0.5 ${
                  item.priority === 'HIGH'
                    ? 'bg-kingpin bg-opacity-20 text-kingpin'
                    : item.priority === 'MED'
                    ? 'bg-warning bg-opacity-20 text-warning'
                    : 'bg-surface-2 text-text-muted'
                }`}
              >
                {item.priority}
              </span>
              <span className="text-text leading-snug">{item.action}</span>
            </li>
          ))}
        </ol>
      </Section>

      <p className="text-xs text-text-muted italic mt-8 pb-4">
        This brief was AI-assisted. All findings are indicators and require verification by the
        Investigating Officer (IO) before any legal action is taken.
      </p>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-6">
      <h3 className="font-heading text-sm font-semibold text-text uppercase tracking-wider mb-2 pb-1 border-b border-border">
        {title}
      </h3>
      {children}
    </section>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="text-left text-[10px] text-text-muted uppercase tracking-wider py-1.5 pr-3 font-medium">
      {children}
    </th>
  )
}

function Td({ children, mono }: { children: React.ReactNode; mono?: boolean }) {
  return (
    <td className={`py-1.5 pr-3 text-text ${mono ? 'font-mono text-[11px]' : ''}`}>
      {children}
    </td>
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
          <StatCard label="Loss" value={fmtInr(analysis.totals.loss_inr)} color="#EF4444" />
          <StatCard label="Victims" value={String(analysis.totals.victims)} />
          <StatCard label="Mules" value={String(analysis.totals.mules)} color="#F59E0B" />
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
          className={`flex flex-col min-h-0 ${
            activeTab === 'Graph' ? 'flex-1' : 'flex-1'
          }`}
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
            <HierarchyTab
              levels={analysis.hierarchy.levels}
              nodes={graph.nodes}
              onSelect={(n) => { setSelectedNode(n); setActiveTab('Graph') }}
            />
          )}
          {activeTab === 'Timeline' && (
            <TimelineTab events={analysis.timeline} />
          )}
          {activeTab === 'Suspects' && (
            <SuspectsTab
              roles={analysis.roles}
              nodes={graph.nodes}
              onSelect={(n) => { setSelectedNode(n); setActiveTab('Graph') }}
            />
          )}
          {activeTab === 'Brief' && <BriefTab data={data} />}
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
