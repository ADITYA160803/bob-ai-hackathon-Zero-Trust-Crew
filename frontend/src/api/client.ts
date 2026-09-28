/**
 * frontend/src/api/client.ts
 *
 * API client — all backend endpoint calls go through here.
 * Base URL defaults to /api (same origin via Vite proxy) or can be
 * overridden by the VITE_API_BASE env variable.
 */

const API_BASE = ((import.meta as unknown) as { env: Record<string, string> }).env?.VITE_API_BASE ?? '/api'

// ---------------------------------------------------------------------------
// Types (mirrors backend/schemas)
// ---------------------------------------------------------------------------

export interface CreateCaseResponse {
  case_id: string
  status: 'pending' | 'done' | 'error'
}

export interface AnalyzeResponse {
  case_id?: string
  status?: string
  used_fallback?: boolean
  stats?: { chunks: number; nodes: number; edges: number }
  // When a ResolvedGraph body is provided, response is AnalysisResult
  [key: string]: unknown
}

export interface GraphResponse {
  nodes: unknown[]
  edges: unknown[]
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${API_BASE}${path}`
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options?.headers ?? {}) },
    ...options,
  })
  if (!resp.ok) {
    const detail = await resp.text()
    throw new Error(`API ${resp.status}: ${detail}`)
  }
  return resp.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Cases
// ---------------------------------------------------------------------------

export async function createCase(
  text?: string,
  files?: File[],
): Promise<CreateCaseResponse> {
  const form = new FormData()
  if (text) form.append('text', text)
  if (files) files.forEach(f => form.append('files', f))
  const resp = await fetch(`${API_BASE}/cases`, { method: 'POST', body: form })
  if (!resp.ok) throw new Error(`Create case failed: ${resp.status}`)
  return resp.json()
}

export async function analyzeCase(
  caseId: string,
  resolvedGraph?: unknown,
): Promise<AnalyzeResponse> {
  return request<AnalyzeResponse>(`/cases/${caseId}/analyze`, {
    method: 'POST',
    body: resolvedGraph ? JSON.stringify(resolvedGraph) : undefined,
    headers: resolvedGraph ? { 'Content-Type': 'application/json' } : {},
  })
}

export async function getGraph(caseId: string): Promise<GraphResponse> {
  return request<GraphResponse>(`/cases/${caseId}/graph`)
}

export async function getAnalysis(caseId: string): Promise<unknown> {
  return request<unknown>(`/cases/${caseId}/analysis`)
}

export async function getBrief(
  caseId: string,
  format: 'md' | 'html' | 'pdf' = 'md',
): Promise<string | Blob> {
  const url = `${API_BASE}/cases/${caseId}/brief?format=${format}`
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`Brief failed: ${resp.status}`)
  if (format === 'pdf') return resp.blob()
  return resp.text()
}

// ---------------------------------------------------------------------------
// Demo
// ---------------------------------------------------------------------------

export async function getDemoAnalysis(scenario: string = 'sample'): Promise<unknown> {
  return request<unknown>(`/demo/${scenario}/analysis`)
}

export async function listScenarios(): Promise<unknown> {
  return request<unknown>('/demo')
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export async function checkHealth(): Promise<{ status: string }> {
  return request<{ status: string }>('/health')
}
