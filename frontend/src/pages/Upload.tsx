import { useState, useCallback, useRef, DragEvent, ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import type { CaseAnalysis } from '../types'

// Offline demo scenarios loaded from data/sample_analysis.json
const MOCK_SCENARIOS: Record<string, { label: string; description: string; icon: string }> = {
  s1_simswap_jamtara: {
    label: 'Jamtara SIM-Swap Ring',
    description: '14 victims · ₹12.5L · Jharkhand origin · SIM-swap + mule layering',
    icon: '📡',
  },
  s2_mule_layering: {
    label: 'Multi-Layer Mule Network',
    description: '9 victims · ₹8.2L · Delhi NCR · Fan-in/fan-out mule chain',
    icon: '🏦',
  },
  s3_vishing_kyc: {
    label: 'Vishing + KYC Fraud',
    description: '22 victims · ₹19.1L · Pan-India call centre · OTP interception',
    icon: '📞',
  },
}

interface UploadedFile {
  name: string
  size: number
  type: string
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function Upload() {
  const navigate = useNavigate()
  const [isDragging, setIsDragging] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [loadingScenario, setLoadingScenario] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const addFiles = useCallback((newFiles: FileList | File[]) => {
    const allowed = ['text/plain', 'text/csv', 'application/csv', '']
    const valid: UploadedFile[] = []
    const invalid: string[] = []

    Array.from(newFiles).forEach((f) => {
      const ext = f.name.split('.').pop()?.toLowerCase()
      if (f.type.startsWith('text/') || ext === 'csv' || ext === 'txt') {
        if (allowed.includes(f.type) || ext === 'csv' || ext === 'txt') {
          valid.push({ name: f.name, size: f.size, type: f.type || `text/${ext}` })
        }
      } else {
        invalid.push(f.name)
      }
    })

    if (invalid.length > 0) {
      setError(`Unsupported file type(s): ${invalid.join(', ')}. Only .txt and .csv accepted.`)
    } else {
      setError(null)
    }

    setFiles((prev) => {
      const names = new Set(prev.map((f) => f.name))
      return [...prev, ...valid.filter((f) => !names.has(f.name))]
    })
  }, [])

  const onDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      setIsDragging(false)
      if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
    },
    [addFiles],
  )

  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const onDragLeave = () => setIsDragging(false)

  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) addFiles(e.target.files)
  }

  const removeFile = (name: string) =>
    setFiles((prev) => prev.filter((f) => f.name !== name))

  const loadMockScenario = async (scenarioKey: string) => {
    setLoadingScenario(scenarioKey)
    setError(null)
    try {
      // Load from the data directory (served as static asset in dev via /data/)
      const res = await fetch('/data/sample_analysis.json')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: CaseAnalysis = await res.json()
      // Override scenario label for demo variety
      const enriched = {
        ...data,
        scenario: scenarioKey,
        case_title: MOCK_SCENARIOS[scenarioKey]?.label ?? data.case_title,
      }
      // Store in sessionStorage for Dashboard to read
      sessionStorage.setItem('jaal_analysis', JSON.stringify(enriched))
      navigate('/dashboard')
    } catch (err) {
      // Fallback: try relative path
      try {
        const res2 = await fetch('../data/sample_analysis.json')
        if (!res2.ok) throw new Error()
        const data: CaseAnalysis = await res2.json()
        sessionStorage.setItem('jaal_analysis', JSON.stringify(data))
        navigate('/dashboard')
      } catch {
        setError(
          'Could not load demo data. Make sure data/sample_analysis.json is served. ' +
            'In dev: copy data/ into frontend/public/data/ or run `vite --publicDir ../data`.',
        )
        setLoadingScenario(null)
      }
    }
  }

  const canAnalyze = files.length > 0 || pasteText.trim().length > 0

  const handleAnalyze = () => {
    if (!canAnalyze) return
    // For now, load mock data (backend not yet wired)
    loadMockScenario('s1_simswap_jamtara')
  }

  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-start px-4 py-12">
      {/* Header */}
      <header className="mb-10 text-center">
        <div className="inline-flex items-center gap-3 mb-3">
          <svg width="36" height="36" viewBox="0 0 36 36" fill="none" aria-hidden="true">
            <circle cx="18" cy="18" r="17" stroke="#22D3EE" strokeWidth="2" />
            <circle cx="18" cy="18" r="5" fill="#22D3EE" />
            <line x1="18" y1="1" x2="18" y2="13" stroke="#22D3EE" strokeWidth="1.5" />
            <line x1="18" y1="23" x2="18" y2="35" stroke="#22D3EE" strokeWidth="1.5" />
            <line x1="1" y1="18" x2="13" y2="18" stroke="#22D3EE" strokeWidth="1.5" />
            <line x1="23" y1="18" x2="35" y2="18" stroke="#22D3EE" strokeWidth="1.5" />
            <circle cx="8" cy="8" r="3" fill="#A78BFA" />
            <circle cx="28" cy="8" r="3" fill="#F59E0B" />
            <circle cx="8" cy="28" r="3" fill="#60A5FA" />
            <circle cx="28" cy="28" r="3" fill="#EF4444" />
          </svg>
          <h1 className="font-heading text-3xl font-bold text-text tracking-tight">JAAL</h1>
        </div>
        <p className="text-text-muted text-sm max-w-md mx-auto leading-relaxed">
          Fraud Network Analyzer — upload call logs, transaction records, or paste raw intelligence
          to extract entities, map the network, and generate an FIR-ready brief.
        </p>
      </header>

      <div className="w-full max-w-2xl space-y-5">
        {/* Drop Zone */}
        <div
          onDrop={onDrop}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onClick={() => fileInputRef.current?.click()}
          className={[
            'card cursor-pointer transition-colors duration-150 border-2 border-dashed',
            'flex flex-col items-center justify-center gap-3 py-10',
            isDragging
              ? 'border-primary bg-primary bg-opacity-5'
              : 'border-border hover:border-primary hover:bg-surface-2',
          ].join(' ')}
          role="button"
          tabIndex={0}
          aria-label="Drop zone: upload .txt or .csv files"
          onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,.csv,text/plain,text/csv"
            multiple
            className="hidden"
            onChange={onFileChange}
          />
          <svg
            width="40"
            height="40"
            viewBox="0 0 24 24"
            fill="none"
            stroke={isDragging ? '#22D3EE' : '#8B97B1'}
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          <div className="text-center">
            <p className={`text-sm font-medium ${isDragging ? 'text-primary' : 'text-text'}`}>
              {isDragging ? 'Release to upload' : 'Drop files here or click to browse'}
            </p>
            <p className="text-xs text-text-muted mt-1">
              Accepts .txt, .csv — call logs, transaction records, raw notes
            </p>
          </div>
        </div>

        {/* File list */}
        {files.length > 0 && (
          <ul className="space-y-2" aria-label="Uploaded files">
            {files.map((f) => (
              <li
                key={f.name}
                className="flex items-center justify-between bg-surface-2 border border-border rounded-input px-3 py-2 text-sm"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-text-muted shrink-0">
                    {f.name.endsWith('.csv') ? '📊' : '📄'}
                  </span>
                  <span className="text-text truncate font-medium">{f.name}</span>
                  <span className="text-text-muted mono shrink-0">{formatBytes(f.size)}</span>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    removeFile(f.name)
                  }}
                  className="text-text-muted hover:text-kingpin transition-colors ml-2 shrink-0"
                  aria-label={`Remove ${f.name}`}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}

        {/* Paste text area */}
        <div className="space-y-1">
          <label htmlFor="paste-text" className="text-xs text-text-muted font-medium uppercase tracking-wider">
            Or paste raw text / intelligence notes
          </label>
          <textarea
            id="paste-text"
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
            placeholder="Paste call records, complaint text, SMS logs, or any raw fraud intelligence here…"
            rows={6}
            className={[
              'w-full bg-surface border border-border rounded-input px-3 py-2.5',
              'text-sm text-text placeholder:text-text-muted font-body resize-y',
              'focus:outline-none focus:border-primary transition-colors duration-150',
            ].join(' ')}
          />
        </div>

        {/* Error */}
        {error && (
          <div className="border border-kingpin bg-kingpin bg-opacity-10 rounded-input px-3 py-2 text-sm text-kingpin">
            ⚠ {error}
          </div>
        )}

        {/* Analyze button */}
        <button
          onClick={handleAnalyze}
          disabled={!canAnalyze}
          className={[
            'w-full py-3 rounded-input font-heading font-semibold text-sm tracking-wide transition-all duration-150',
            canAnalyze
              ? 'bg-primary text-bg hover:opacity-90 active:opacity-75'
              : 'bg-surface-2 text-text-muted cursor-not-allowed border border-border',
          ].join(' ')}
        >
          Analyze Intelligence →
        </button>

        {/* Divider */}
        <div className="flex items-center gap-3">
          <hr className="flex-1 border-border" />
          <span className="text-xs text-text-muted">OFFLINE DEMO SCENARIOS</span>
          <hr className="flex-1 border-border" />
        </div>

        {/* Mock scenario buttons */}
        <div className="space-y-3">
          {Object.entries(MOCK_SCENARIOS).map(([key, scenario]) => (
            <button
              key={key}
              onClick={() => loadMockScenario(key)}
              disabled={loadingScenario !== null}
              className={[
                'w-full bg-surface border border-border rounded-card px-4 py-3',
                'flex items-start gap-3 text-left transition-colors duration-150',
                loadingScenario === key
                  ? 'border-primary'
                  : 'hover:border-primary hover:bg-surface-2',
                loadingScenario !== null && loadingScenario !== key
                  ? 'opacity-50 cursor-not-allowed'
                  : 'cursor-pointer',
              ].join(' ')}
              aria-label={`Load demo scenario: ${scenario.label}`}
            >
              <span className="text-xl shrink-0 mt-0.5">{scenario.icon}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-text">{scenario.label}</span>
                  {loadingScenario === key ? (
                    <span className="text-xs text-primary animate-pulse font-mono">Loading…</span>
                  ) : (
                    <span className="text-xs text-text-muted border border-border rounded px-1.5 py-0.5">
                      Demo
                    </span>
                  )}
                </div>
                <p className="text-xs text-text-muted mt-0.5">{scenario.description}</p>
              </div>
            </button>
          ))}
        </div>

        <p className="text-center text-xs text-text-muted pb-4">
          Demo scenarios load instantly from local data. No internet required.
        </p>
      </div>
    </div>
  )
}
