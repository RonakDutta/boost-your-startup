import { useEffect, useState } from 'react'
import { getJSON } from '../api.js'
import { HBars } from './charts.jsx'
import { Bar, SafeLink, Tag, toneFor } from './ui.jsx'

const COVER = {
  covered: { tone: 'accent', label: 'Checked by this project' },
  partly: { tone: 'info', label: 'Partly checked' },
  none: { tone: 'var(--line-strong)', label: 'Not checked' },
}
const LEGEND = Object.values(COVER).map((c) => ({ label: c.label, tone: c.tone }))

let cache = null
function useFailureData() {
  const [data, setData] = useState(cache)
  useEffect(() => {
    if (cache) return
    getJSON('/api/startup-failure-data').then((d) => { cache = d; setData(d) }).catch(() => setData(false))
  }, [])
  return data
}

/** Signals from this idea's run for one failure reason, or null. */
function ideaSignal(id, out) {
  const cats = Object.fromEntries((out.scorecard?.categories || []).map((c) => [c.category_name, c]))
  const score = (...names) => {
    const found = names.map((n) => cats[n]).filter(Boolean)
    if (!found.length) return null
    const got = found.reduce((n, c) => n + c.score, 0)
    const max = found.reduce((n, c) => n + c.max_score, 0)
    return { kind: 'score', got, max, label: found.map((c) => c.category_name).join(' + ') }
  }
  const papers = out.prior_art?.papers || []
  switch (id) {
    case 'capital': return score('Resource Requirements')
    case 'pmf': return score('Problem Validation', 'Market Demand & Opportunity')
    case 'economics': return score('Execution & Go-To-Market')
    case 'competition': return score('Competition & Defensibility')
    case 'technical': return score('Technical Feasibility')
    case 'legal': return score('Risk Assessment & Mitigations')
    case 'pivot': return out.reconciliation?.verdict ? { kind: 'text', text: `Judge's verdict: ${out.reconciliation.verdict}` } : null
    case 'timing': {
      if (!papers.length) return null
      const recent = papers.filter((p) => p.year && p.year >= new Date().getFullYear() - 3).length
      return { kind: 'score', got: recent, max: papers.length, label: 'research papers from the last 3 years', unit: 'papers' }
    }
    default: return null
  }
}

function SourceLine({ src, verification, onVerify, busy }) {
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="tiny muted">
        Source: <SafeLink href={src.url}>{src.publisher}, "{src.title}"</SafeLink> ({src.published}). {src.sample}. {src.note}
      </div>
      <div className="row tiny">
        <button type="button" className="chip" disabled={busy} onClick={onVerify}>{busy ? 'Checking...' : 'Check against the source now'}</button>
        {verification && (verification.ok
          ? <Tag tone={verification.matching === verification.checked ? 'good' : 'warn'}>{verification.matching} of {verification.checked} figures in the report text match ({verification.checked_at})</Tag>
          : <span className="muted">Could not reach the report right now. The figures are from the copy read on {src.retrieved}.</span>)}
      </div>
    </div>
  )
}

/**
 * Why startups fail, from published survey data. With `out` (an idea run) it also
 * shows this idea's own signals for each reason; `goTo` opens the matching tab.
 */
export default function WhyStartupsFail({ out, goTo, compact = false }) {
  const data = useFailureData()
  const [picked, setPicked] = useState(null)
  const [verification, setVerification] = useState(null)
  const [busy, setBusy] = useState(false)
  if (data === false) return <div className="small muted">The startup failure data could not be loaded.</div>
  if (!data) return null
  const src = data.source
  const verify = () => {
    setBusy(true)
    getJSON('/api/startup-failure-data?verify=1').then((d) => setVerification(d.verification)).catch(() => setVerification({ ok: false }))
      .finally(() => setBusy(false))
  }
  const rows = data.reasons.map((r) => ({
    key: r.id, label: r.reason, value: r.share, unit: '%', tone: COVER[r.coverage].tone,
    tip: `${r.share}% of ${src.companies_with_reasons} failed startups: ${r.reason}. ${COVER[r.coverage].label}`,
  }))
  const sel = data.reasons.find((r) => r.id === picked)
  const TAB = { pmf: 'score', capital: 'score', economics: 'score', competition: 'market', technical: 'score', legal: 'risks', pivot: 'risks', timing: 'papers' }
  return (
    <div className="stack-lg">
      <div className="card pad stack">
        <div className="row between">
          <h3>Why startups fail</h3>
          <span className="tiny muted">share of {src.companies_with_reasons} failed startups that named each reason</span>
        </div>
        <HBars rows={rows} max={100} unit="%" labelWidth={250} legend={LEGEND} onPick={(r) => setPicked(r.key === picked ? null : r.key)} />
        {sel && (
          <div className="focus-bar" style={{ alignItems: 'flex-start' }}>
            <div className="stack" style={{ gap: 2 }}>
              <strong>{sel.reason} ({sel.share}%)</strong>
              <span>{COVER[sel.coverage].label}: {sel.covered_by}. {sel.how}</span>
            </div>
          </div>
        )}
        {!compact && !out && <SourceLine src={src} verification={verification} onVerify={verify} busy={busy} />}
        {(compact || out) && <div className="tiny muted">Source: <SafeLink href={src.url}>{src.publisher}, "{src.title}"</SafeLink> ({src.published}). Click a bar to see how this project answers it.</div>}
      </div>

      {out && (
        <div className="card pad stack">
          <div className="row between"><h3>Your idea against these reasons</h3><span className="tiny muted">from this run's scorecard, judge and papers</span></div>
          <div className="fail-rows">
            {data.reasons.map((r) => {
              const sig = ideaSignal(r.id, out)
              const pct = sig?.kind === 'score' && sig.max ? Math.round((sig.got / sig.max) * 100) : null
              return (
                <div key={r.id} className="fail-row">
                  <div className="stack" style={{ gap: 2, minWidth: 0 }}>
                    <span style={{ fontWeight: 600 }}>{r.reason}</span>
                    <span className="tiny muted">{r.share}% of failed startups</span>
                  </div>
                  <div className="stack" style={{ gap: 4, minWidth: 0 }}>
                    {sig?.kind === 'score' && (
                      <>
                        <div className="row between tiny"><span className="muted">{sig.label}</span><span className="mono">{sig.got}/{sig.max}{sig.unit ? ` ${sig.unit}` : ''}</span></div>
                        <Bar value={sig.got} max={sig.max} tone={r.id === 'timing' ? 'info' : toneFor(pct)} />
                      </>
                    )}
                    {sig?.kind === 'text' && <span className="small">{sig.text}</span>}
                    {!sig && <span className="tiny muted">{r.coverage === 'none' ? 'Not checked by this project.' : 'No signal in this run.'}</span>}
                  </div>
                  <div>{TAB[r.id] && goTo ? <button type="button" className="chip" onClick={() => goTo(TAB[r.id])}>Details</button> : null}</div>
                </div>
              )
            })}
          </div>
          <SourceLine src={src} verification={verification} onVerify={verify} busy={busy} />
        </div>
      )}
    </div>
  )
}
