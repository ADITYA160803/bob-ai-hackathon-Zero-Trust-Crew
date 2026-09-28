import { useState } from 'react'
import type { PatternResult } from '../types'

// Design tokens mapped from design.md 5.1
const PATTERN_META: Record<
  string,
  { label: string; shortLabel: string; icon: string }
> = {
  SIM_SWAP: { label: 'SIM-Swap', shortLabel: 'SIM-Swap', icon: '📡' },
  MULE_LAYERING: { label: 'Mule Layering', shortLabel: 'Mule Layer', icon: '🏦' },
  VISHING: { label: 'Vishing / OTP Fraud', shortLabel: 'Vishing', icon: '📞' },
  PHISHING_KYC: { label: 'Phishing / KYC', shortLabel: 'Phishing', icon: '🎣' },
  INVESTMENT_TASK: { label: 'Investment / Task Scam', shortLabel: 'Task Scam', icon: '📈' },
}

function confidenceColor(c: number): string {
  if (c >= 0.8) return '#22C55E'  // success
  if (c >= 0.6) return '#FACC15'  // warning
  return '#EF4444'                // danger
}

function confidenceLabel(c: number): string {
  if (c >= 0.9) return 'Very High'
  if (c >= 0.75) return 'High'
  if (c >= 0.55) return 'Medium'
  return 'Low'
}

interface PatternBadgeProps {
  pattern: PatternResult
  /** compact: show only pill inline. default: full badge with confidence bar */
  variant?: 'compact' | 'full'
}

export default function PatternBadge({ pattern, variant = 'full' }: PatternBadgeProps) {
  const [expanded, setExpanded] = useState(false)
  const meta = PATTERN_META[pattern.type] ?? { label: pattern.type, shortLabel: pattern.type, icon: '🔍' }
  const color = confidenceColor(pattern.confidence)
  const pct = Math.round(pattern.confidence * 100)

  if (variant === 'compact') {
    return (
      <button
        onClick={() => setExpanded((v) => !v)}
        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium
                   border border-border bg-surface hover:bg-surface-2 transition-colors duration-150"
        aria-expanded={expanded}
        aria-label={`Pattern: ${meta.label}, confidence ${pct}%`}
      >
        <span>{meta.icon}</span>
        <span className="text-text">{meta.shortLabel}</span>
        <span className="font-mono text-[11px]" style={{ color }}>{pct}%</span>
        <span className="text-text-muted">{expanded ? '▲' : '▼'}</span>
      </button>
    )
  }

  return (
    <div className="card space-y-3">
      {/* Primary pattern pill + confidence */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full
                       border border-border bg-surface-2 hover:bg-surface transition-colors
                       duration-150 focus:outline-none focus:ring-1 focus:ring-primary"
            aria-expanded={expanded}
            aria-label={`Pattern: ${meta.label}. Click to ${expanded ? 'collapse' : 'expand'} reasons`}
          >
            <span className="text-base leading-none">{meta.icon}</span>
            <span className="text-sm font-medium text-text">{meta.label}</span>
            <span className="text-text-muted text-xs">{expanded ? '▲' : '▼'}</span>
          </button>

          {/* Secondary pattern tags */}
          {pattern.secondary?.map((s) => {
            const sm = PATTERN_META[s]
            if (!sm) return null
            return (
              <span
                key={s}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full
                           text-xs text-text-muted border border-border bg-surface"
              >
                {sm.icon} {sm.shortLabel}
              </span>
            )
          })}
        </div>

        {/* Confidence pct */}
        <div className="text-right shrink-0">
          <div className="font-mono text-sm font-medium" style={{ color }}>
            {pct}%
          </div>
          <div className="text-xs text-text-muted">{confidenceLabel(pattern.confidence)}</div>
        </div>
      </div>

      {/* Confidence bar */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-text-muted">Pattern confidence</span>
          <span className="text-xs font-mono" style={{ color }}>{pct}%</span>
        </div>
        <div className="h-1.5 rounded-full bg-surface-2 overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500 ease-out"
            style={{ width: `${pct}%`, backgroundColor: color }}
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
          />
        </div>
      </div>

      {/* Expanded reasons */}
      {expanded && pattern.reasons?.length > 0 && (
        <div className="pt-1 border-t border-border">
          <p className="text-xs text-text-muted uppercase tracking-wider mb-2">Detection Signals</p>
          <ul className="space-y-1.5" aria-label="Pattern reasons">
            {pattern.reasons.map((reason, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <span className="text-success mt-0.5 shrink-0 text-xs">✓</span>
                <span className="text-text leading-snug">{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
