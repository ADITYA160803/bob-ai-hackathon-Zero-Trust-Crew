/**
 * frontend/src/components/Timeline.tsx
 *
 * Chronological event timeline from AnalysisResult.timeline.
 * Each event shows timestamp + description with evidence sourcing.
 */
import type { TimelineEvent } from '../types'

function fmtDate(ts: string) {
  return new Date(ts).toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

interface TimelineProps {
  events: TimelineEvent[]
}

export default function Timeline({ events }: TimelineProps) {
  if (!events || events.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-text-muted text-sm">
        No timeline events available.
      </div>
    )
  }

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
