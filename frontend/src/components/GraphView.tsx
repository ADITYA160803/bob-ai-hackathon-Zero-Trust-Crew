import { useRef, useEffect, useCallback } from 'react'
import CytoscapeComponent from 'react-cytoscapejs'
import cytoscape, { Core, ElementDefinition } from 'cytoscape'
// @ts-expect-error – no types for cose-bilkent
import coseBilkent from 'cytoscape-cose-bilkent'
import type { Graph, GraphNode, GraphEdge, RoleType, NodeType } from '../types'

try {
  cytoscape.use(coseBilkent)
} catch {
  // already registered
}

// ── Design tokens from design.md 5.1 ──────────────────────────────────────────
const ROLE_COLOR: Record<RoleType | 'UNKNOWN', string> = {
  KINGPIN: '#EF4444',
  HANDLER: '#A78BFA',
  MULE: '#F59E0B',
  OPERATOR: '#F472B6',
  VICTIM: '#60A5FA',
  UNKNOWN: '#64748B',
}

// Min/max pixel size for nodes based on risk_score
const MIN_SIZE = 28
const MAX_SIZE = 60

// Edge types that should be dashed (calls, SMS)
const DASHED_EDGES = new Set(['CALLED', 'SMS_SENT'])
// Edge types that carry monetary amount (thickness scaling)
const MONEY_EDGES = new Set(['TRANSFERRED_TO'])

function nodeSize(riskScore: number): number {
  return MIN_SIZE + (MAX_SIZE - MIN_SIZE) * Math.max(0, Math.min(1, riskScore))
}

function edgeWidth(edge: GraphEdge): number {
  if (!MONEY_EDGES.has(edge.type)) return 1.5
  const amount = Number(edge.attrs?.amount ?? 0)
  if (amount <= 0) return 1.5
  // Scale: 50k → 2px, 200k → 5px (clamped)
  return Math.min(7, 1.5 + (amount / 50000))
}

export interface GraphViewProps {
  graph: Graph
  selectedNodeId: string | null
  onNodeSelect: (node: GraphNode | null) => void
  /** Filter: only show these roles (empty = show all) */
  roleFilter?: RoleType[]
  /** Filter: only show these node types (empty = show all) */
  typeFilter?: NodeType[]
}

function buildElements(
  graph: Graph,
  roleFilter: RoleType[],
  typeFilter: NodeType[],
): ElementDefinition[] {
  const roleSet = new Set<string>(roleFilter)
  const typeSet = new Set<string>(typeFilter)

  const visibleIds = new Set(
    graph.nodes
      .filter((n) => {
        if (roleSet.size > 0 && !roleSet.has(n.role)) return false
        if (typeSet.size > 0 && !typeSet.has(n.type)) return false
        return true
      })
      .map((n) => n.id),
  )

  const nodes: ElementDefinition[] = graph.nodes
    .filter((n) => visibleIds.has(n.id))
    .map((n) => {
      const color = ROLE_COLOR[n.role] ?? ROLE_COLOR.UNKNOWN
      const size = nodeSize(n.risk_score)
      return {
        data: {
          id: n.id,
          label: n.label,
          nodeType: n.type,
          role: n.role,
          riskScore: n.risk_score,
          color,
          size,
          _raw: n,
        },
      }
    })

  const edges: ElementDefinition[] = graph.edges
    .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
    .map((e) => ({
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        edgeType: e.type,
        width: edgeWidth(e),
        dashed: DASHED_EDGES.has(e.type),
        amount: e.attrs?.amount ?? 0,
        _raw: e,
      },
    }))

  return [...nodes, ...edges]
}

const CYTOSCAPE_STYLESHEET: cytoscape.StylesheetStyle[] = [
  {
    selector: 'node',
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    style: {
      shape: 'data(nodeShape)' as unknown as string,
      width: 'data(size)' as unknown as string,
      height: 'data(size)' as unknown as string,
      'background-color': 'data(color)' as string,
      'border-width': 1.5 as unknown as string,
      'border-color': '#2A3550',
      label: 'data(label)',
      color: '#E6EAF2',
      'font-size': 10 as unknown as string,
      'font-family': 'Inter, system-ui, sans-serif',
      'text-valign': 'bottom' as const,
      'text-halign': 'center' as const,
      'text-margin-y': 4 as unknown as string,
      'text-max-width': 80 as unknown as string,
      'text-wrap': 'ellipsis' as const,
      'min-zoomed-font-size': 8 as unknown as string,
    } as unknown as cytoscape.Css.Node,
  },
  {
    selector: 'node:selected',
    style: {
      'border-width': 3,
      'border-color': '#22D3EE',
      'border-opacity': 1,
    },
  },
  {
    selector: 'node[role="KINGPIN"]',
    style: { shape: 'ellipse' },
  },
  {
    selector: 'node[nodeType="PHONE"]',
    style: { shape: 'diamond' },
  },
  {
    selector: 'node[nodeType="DEVICE"]',
    style: { shape: 'hexagon' },
  },
  {
    selector: 'node[nodeType="BANK_ACCOUNT"], node[nodeType="UPI_ID"]',
    style: { shape: 'round-rectangle' },
  },
  {
    selector: 'node[nodeType="PERSON"]',
    style: { shape: 'ellipse' },
  },
  {
    selector: 'edge',
    style: {
      width: 'data(width)',
      'line-color': '#2A3550',
      'target-arrow-color': '#2A3550',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      'arrow-scale': 0.8,
    },
  },
  {
    selector: 'edge[edgeType="TRANSFERRED_TO"]',
    style: {
      'line-color': '#22D3EE',
      'target-arrow-color': '#22D3EE',
      opacity: 0.85,
    },
  },
  {
    selector: 'edge[edgeType="CALLED"], edge[edgeType="SMS_SENT"]',
    style: {
      'line-style': 'dashed',
      'line-dash-pattern': [6, 3],
      'line-color': '#8B97B1',
      'target-arrow-color': '#8B97B1',
      opacity: 0.7,
    },
  },
  {
    selector: 'edge[edgeType="OWNS"]',
    style: {
      'line-color': '#1B2436',
      'target-arrow-shape': 'none',
      'line-style': 'dotted',
      opacity: 0.6,
    },
  },
  {
    selector: 'edge[edgeType="SIM_IN_DEVICE"]',
    style: {
      'line-color': '#A78BFA',
      'target-arrow-color': '#A78BFA',
      'line-style': 'dashed',
      'line-dash-pattern': [4, 4],
      opacity: 0.7,
    },
  },
  {
    selector: 'edge:selected',
    style: {
      'line-color': '#22D3EE',
      'target-arrow-color': '#22D3EE',
      opacity: 1,
    },
  },
  // Dim non-connected nodes when something is selected
  {
    selector: '.dimmed',
    style: { opacity: 0.2 },
  },
]

export default function GraphView({
  graph,
  selectedNodeId,
  onNodeSelect,
  roleFilter = [],
  typeFilter = [],
}: GraphViewProps) {
  const cyRef = useRef<Core | null>(null)

  const elements = buildElements(graph, roleFilter, typeFilter)

  const handleCyReady = useCallback(
    (cy: Core) => {
      cyRef.current = cy

      // Click on node
      cy.on('tap', 'node', (evt) => {
        const raw = evt.target.data('_raw') as GraphNode
        onNodeSelect(raw)
        // Highlight connected sub-graph
        cy.elements().addClass('dimmed')
        const connected = evt.target.closedNeighborhood()
        connected.removeClass('dimmed')
      })

      // Click on background → deselect
      cy.on('tap', (evt) => {
        if (evt.target === cy) {
          cy.elements().removeClass('dimmed')
          onNodeSelect(null)
        }
      })

      // Animate layout on load
      cy.layout({
        name: 'cose-bilkent',
        animate: true,
        animationDuration: 600,
        randomize: false,
        nodeRepulsion: 6000,
        idealEdgeLength: 120,
        edgeElasticity: 0.45,
        nestingFactor: 0.1,
        gravity: 0.25,
        numIter: 2500,
        fit: true,
        padding: 32,
      } as Parameters<Core['layout']>[0]).run()
    },
    [onNodeSelect],
  )

  // Sync selected node highlight when selectedNodeId changes externally
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.nodes().unselect()
    if (selectedNodeId) {
      cy.$(`#${CSS.escape(selectedNodeId)}`).select()
    }
  }, [selectedNodeId])

  if (elements.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center bg-bg text-text-muted text-sm">
        No nodes match the current filters.
      </div>
    )
  }

  return (
    <div className="relative flex-1 min-h-0 bg-bg" aria-label="Fraud network graph">
      <CytoscapeComponent
        elements={elements}
        stylesheet={CYTOSCAPE_STYLESHEET}
        cy={handleCyReady}
        style={{ width: '100%', height: '100%' }}
        minZoom={0.2}
        maxZoom={4}
        boxSelectionEnabled={false}
        autounselectify={false}
      />

      {/* Legend */}
      <div
        className="absolute bottom-4 left-4 bg-surface border border-border rounded-card px-3 py-2 text-xs
                   space-y-1 select-none"
        aria-label="Graph legend"
      >
        <p className="text-text-muted uppercase tracking-wider text-[10px] mb-1.5">Role Legend</p>
        {(Object.entries(ROLE_COLOR) as [string, string][]).filter(([k]) => k !== 'UNKNOWN').map(
          ([role, color]) => (
            <div key={role} className="flex items-center gap-1.5">
              <span
                className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
                style={{ backgroundColor: color }}
              />
              <span className="capitalize text-text-muted">
                {role.charAt(0) + role.slice(1).toLowerCase()}
              </span>
            </div>
          ),
        )}
        <div className="border-t border-border mt-1.5 pt-1.5 space-y-1">
          <p className="text-text-muted uppercase tracking-wider text-[10px] mb-1">Edge Types</p>
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-5 h-0.5 bg-primary" />
            <span className="text-text-muted">Money flow</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-5 border-t border-dashed border-text-muted" />
            <span className="text-text-muted">Call / SMS</span>
          </div>
        </div>
      </div>

      {/* Controls hint */}
      <div className="absolute top-3 right-3 text-[10px] text-text-muted bg-surface bg-opacity-80
                      border border-border rounded px-2 py-1 select-none">
        Scroll to zoom · Drag to pan · Click node for details
      </div>
    </div>
  )
}
