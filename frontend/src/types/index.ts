/**
 * frontend/src/types/index.ts
 *
 * TypeScript types — matches both the real AnalysisResult (backend/schemas/result.py)
 * and the shapes expected by Dashboard.tsx / components.
 */

// ---------------------------------------------------------------------------
// Enumerations
// ---------------------------------------------------------------------------

export type NodeType =
  | 'PERSON'
  | 'PHONE'
  | 'DEVICE'
  | 'BANK_ACCOUNT'
  | 'UPI_ID'
  | 'IP'
  | 'LOCATION'

export type EdgeType =
  | 'OWNS'
  | 'USES_DEVICE'
  | 'SIM_IN_DEVICE'
  | 'CALLED'
  | 'SMS_SENT'
  | 'TRANSFERRED_TO'
  | 'LOGGED_IN_FROM'

export type RoleType =
  | 'KINGPIN'
  | 'HANDLER'
  | 'MULE'
  | 'OPERATOR'
  | 'VICTIM'
  | 'UNKNOWN'

export type PatternType =
  | 'SIM_SWAP'
  | 'MULE_LAYERING'
  | 'VISHING'
  | 'PHISHING_KYC'
  | 'INVESTMENT_TASK'

// ---------------------------------------------------------------------------
// Graph entities
// ---------------------------------------------------------------------------

export interface GraphNode {
  id: string
  type: NodeType
  label: string
  attrs: Record<string, string | number | boolean>
  /** Role assigned by hierarchy scorer (present in enriched CaseAnalysis.graph) */
  role: RoleType
  /** Risk score [0,1] for sizing (present in enriched CaseAnalysis.graph) */
  risk_score: number
  sources: string[]
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  type: EdgeType
  attrs: Record<string, string | number | boolean>
  evidence: string
}

/** @alias GraphPayload — renamed but both are exported */
export interface Graph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export type GraphPayload = Graph

// ---------------------------------------------------------------------------
// Analysis sub-types
// ---------------------------------------------------------------------------

export interface NodeMetrics {
  node_id: string
  degree_centrality: number
  in_degree: number
  out_degree: number
  betweenness: number
  transfer_fan_in: number
  transfer_fan_out: number
  in_amount: number | null
  out_amount: number | null
  pass_through_ratio: number | null
  min_dwell_sec: number | null
}

export interface MetricResult {
  case_id: string
  nodes: NodeMetrics[]
}

export interface Community {
  community_id: number
  node_ids: string[]
  size: number
}

export interface CommunityResult {
  case_id: string
  communities: Community[]
  method: string
}

export interface RoleScore {
  node_id: string
  role: RoleType
  score: number
  why: string[]
}

/** @alias RoleAssignment */
export type RoleAssignment = RoleScore

export interface PatternMatch {
  type: PatternType
  confidence: number
  reasons: string[]
  /** Optional: human label derived from type */
  label?: string
  /** Optional: secondary patterns */
  secondary?: PatternType[]
}

export interface PatternResult {
  type: PatternType
  /** Derived from type — used for display */
  label: string
  secondary: PatternType[]
  confidence: number
  reasons: string[]
}

export interface TimelineEvent {
  ts: string
  event: string
}

export interface Totals {
  loss_inr: number
  victims: number
  mules: number
  operators?: number | null
  handlers?: number | null
  /** Legacy: total accounts in graph */
  accounts_involved?: number | null
}

// ---------------------------------------------------------------------------
// AnalysisResult — real API response (backend/schemas/result.py)
// AND legacy field aliases for Dashboard.tsx compatibility
// ---------------------------------------------------------------------------

export interface AnalysisResult {
  case_id: string

  // New API fields
  primary_pattern: PatternMatch | null
  all_patterns: PatternMatch[]
  roles: RoleScore[]
  levels: string[][]
  totals: Totals
  timeline: TimelineEvent[]
  metrics: MetricResult | null
  communities: CommunityResult | null

  // Legacy aliases used by Dashboard.tsx
  /** Alias for primary_pattern — used by PatternBadge (PatternResult shape) */
  pattern: PatternResult
  /** hierarchy wrapper for backwards compatibility */
  hierarchy: { levels: string[][] }
}

// ---------------------------------------------------------------------------
// CaseAnalysis — full case payload stored in sessionStorage
// ---------------------------------------------------------------------------

export interface CaseAnalysis {
  case_id: string
  case_title: string
  created_at: string
  scenario: string
  graph: Graph
  analysis: AnalysisResult
  scenarios: Record<string, string>
}
