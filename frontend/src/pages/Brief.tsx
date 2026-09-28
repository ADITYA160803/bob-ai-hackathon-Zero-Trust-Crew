/**
 * frontend/src/pages/Brief.tsx
 *
 * Renders the FIR case brief from the API.
 * - Fetches Markdown brief from GET /api/cases/{id}/brief?format=md
 * - Renders it with a disclaimer strip
 * - Download .md button
 * - Download PDF/HTML button (PDF if available, HTML fallback)
 */
import { useState, useEffect, useCallback } from 'react'
import { getBrief } from '../api/client'

interface BriefProps {
  caseId: string
}

function MarkdownRenderer({ md }: { md: string }) {
  // Simple markdown rendering: parse headings, bold, lists, tables, blockquotes
  const lines = md.split('\n')
  const rendered: React.ReactNode[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Headings
    if (line.startsWith('# ')) {
      rendered.push(<h1 key={i} className="font-heading text-2xl font-bold text-text mt-6 mb-3">{line.slice(2)}</h1>)
    } else if (line.startsWith('## ')) {
      rendered.push(<h2 key={i} className="font-heading text-lg font-semibold text-text mt-5 mb-2 border-b border-border pb-1">{line.slice(3)}</h2>)
    } else if (line.startsWith('### ')) {
      rendered.push(<h3 key={i} className="font-heading text-base font-semibold text-text mt-4 mb-1">{line.slice(4)}</h3>)

    // Blockquote (disclaimer)
    } else if (line.startsWith('> ')) {
      rendered.push(
        <blockquote key={i} className="border-l-4 border-warning bg-warning bg-opacity-10 px-4 py-2 my-3 text-sm text-warning rounded-r-card">
          {line.slice(2)}
        </blockquote>
      )

    // Horizontal rule
    } else if (line.startsWith('---')) {
      rendered.push(<hr key={i} className="border-border my-4" />)

    // List items
    } else if (line.match(/^[\d]+\. /)) {
      rendered.push(<li key={i} className="text-sm text-text ml-4 list-decimal my-0.5">{applyInline(line.replace(/^[\d]+\. /, ''))}</li>)
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      rendered.push(<li key={i} className="text-sm text-text ml-4 list-disc my-0.5">{applyInline(line.slice(2))}</li>)

    // Table row (starts with |)
    } else if (line.startsWith('|')) {
      const cells = line.split('|').filter((_, ci) => ci > 0 && ci < line.split('|').length - 1)
      const isHeader = lines[i + 1]?.match(/^\|[-| ]+\|$/)
      if (isHeader) {
        rendered.push(
          <tr key={i} className="border-b border-border bg-surface-2">
            {cells.map((c, ci) => <th key={ci} className="px-3 py-1.5 text-left text-xs font-semibold text-text-muted">{c.trim()}</th>)}
          </tr>
        )
        i++ // skip the separator line
      } else if (lines[i - 1]?.match(/^\|[-| ]+\|$/)) {
        // skip separator
      } else {
        rendered.push(
          <tr key={i} className="border-b border-border hover:bg-surface-2">
            {cells.map((c, ci) => <td key={ci} className="px-3 py-1.5 text-xs text-text font-mono">{c.trim()}</td>)}
          </tr>
        )
      }

    // Empty line
    } else if (line.trim() === '') {
      rendered.push(<br key={i} />)

    // Regular paragraph
    } else {
      rendered.push(<p key={i} className="text-sm text-text leading-relaxed my-1">{applyInline(line)}</p>)
    }
    i++
  }

  return (
    <div className="prose max-w-none">
      {/* Wrap table rows in a table */}
      {wrapTables(rendered)}
    </div>
  )
}

function applyInline(text: string): React.ReactNode {
  // Bold
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} className="font-semibold text-text">{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={i} className="font-mono text-[11px] bg-surface-2 px-1 py-0.5 rounded text-primary">{part.slice(1, -1)}</code>
    }
    return part
  })
}

function wrapTables(nodes: React.ReactNode[]): React.ReactNode[] {
  // Group consecutive <tr> elements into a <table>
  const result: React.ReactNode[] = []
  let tableRows: React.ReactNode[] = []

  nodes.forEach((node, i) => {
    if (node && typeof node === 'object' && 'type' in (node as any) && (node as any).type === 'tr') {
      tableRows.push(node)
    } else {
      if (tableRows.length > 0) {
        result.push(
          <div key={`table-${i}`} className="overflow-x-auto my-3">
            <table className="w-full border-collapse text-xs border border-border rounded-card overflow-hidden">
              <tbody>{tableRows}</tbody>
            </table>
          </div>
        )
        tableRows = []
      }
      result.push(node)
    }
  })
  if (tableRows.length > 0) {
    result.push(
      <div key="table-last" className="overflow-x-auto my-3">
        <table className="w-full border-collapse text-xs border border-border rounded-card overflow-hidden">
          <tbody>{tableRows}</tbody>
        </table>
      </div>
    )
  }
  return result
}

export default function Brief({ caseId }: BriefProps) {
  const [md, setMd] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    getBrief(caseId, 'md')
      .then((text) => setMd(text as string))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [caseId])

  const downloadMd = useCallback(() => {
    if (!md) return
    const blob = new Blob([md], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `jaal_brief_${caseId}.md`
    a.click()
    URL.revokeObjectURL(url)
  }, [md, caseId])

  const downloadPdfOrHtml = useCallback(async () => {
    try {
      const result = await getBrief(caseId, 'pdf')
      if (result instanceof Blob) {
        const url = URL.createObjectURL(result)
        const a = document.createElement('a')
        a.href = url
        a.download = `jaal_brief_${caseId}.pdf`
        a.click()
        URL.revokeObjectURL(url)
      } else {
        // PDF not available — get HTML
        const html = await getBrief(caseId, 'html')
        const blob = new Blob([html as string], { type: 'text/html' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `jaal_brief_${caseId}.html`
        a.click()
        URL.revokeObjectURL(url)
      }
    } catch {
      const html = await getBrief(caseId, 'html')
      const blob = new Blob([html as string], { type: 'text/html' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `jaal_brief_${caseId}.html`
      a.click()
      URL.revokeObjectURL(url)
    }
  }, [caseId])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="text-text-muted text-sm animate-pulse">Loading brief…</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex-1 p-6">
        <div className="bg-kingpin bg-opacity-10 border border-kingpin rounded-card p-4 text-sm text-kingpin">
          Failed to load brief: {error}
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto">
      {/* Disclaimer strip */}
      <div className="sticky top-0 z-10 bg-warning bg-opacity-10 border-b border-warning px-6 py-2 text-xs text-warning flex items-center gap-2">
        <span>⚠</span>
        <span>
          AI-assisted analysis. Requires verification by the investigating officer before legal action.
        </span>
      </div>

      {/* Action bar */}
      <div className="flex gap-2 px-6 py-3 border-b border-border bg-surface">
        <button
          onClick={downloadMd}
          className="text-xs px-3 py-1.5 rounded-input border border-border text-text-muted
                     hover:border-primary hover:text-primary transition-colors"
        >
          ↓ Download .md
        </button>
        <button
          onClick={downloadPdfOrHtml}
          className="text-xs px-3 py-1.5 rounded-input border border-border text-text-muted
                     hover:border-primary hover:text-primary transition-colors"
        >
          ↓ Download PDF / HTML
        </button>
      </div>

      {/* Brief content */}
      <div className="max-w-3xl mx-auto p-6">
        {md ? <MarkdownRenderer md={md} /> : <p className="text-text-muted text-sm">No brief content.</p>}
      </div>
    </div>
  )
}
