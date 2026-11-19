import { useState } from 'react'
import TraceView from '../components/TraceView.jsx'
import { Bar, More, SafeLink, Score, Source, Tabs, Tag, plainText } from '../components/ui.jsx'

const SEV_TONE = { high: 'risk', medium: 'warn', low: '' }
const SOURCE_NAMES = { arxiv: 'arXiv', semantic_scholar: 'Semantic Scholar', openalex: 'OpenAlex' }
const cweUrl = (cwe) => `https://cwe.mitre.org/data/definitions/${String(cwe).split('-')[1]}.html`

function authors(list, n = 3) {
  const a = (list || []).filter(Boolean)
  return a.slice(0, n).join(', ') + (a.length > n ? ' et al.' : '')
}

function Code({ code, start = 1, mark, tone = '' }) {
  const lines = String(code || '').replace(/\n$/, '').split('\n')
  return (
    <div className={`codebox ${tone}`}>
      <pre>{lines.map((l, i) => (
        <div className="ln" key={i} style={start + i === mark ? { background: 'color-mix(in srgb, var(--risk) 12%, transparent)' } : undefined}>
          <span>{start ? start + i : ''}</span><span>{l || ' '}</span>
        </div>
      ))}</pre>
    </div>
  )
}

function Cwe({ id }) {
  return <SafeLink href={cweUrl(id)}><span className="mono tiny">{id}</span></SafeLink>
}

function Where({ f }) {
  return <span className="mono tiny muted">{f.file_path}:{f.line}{f.symbol ? ` · ${f.symbol}()` : ''}</span>
}

function Overview({ out, goTo }) {
  const r = out.readiness || {}
  const c = out.counts || {}
  const v = out.verification || {}
  const top = (out.findings || [])[0]
  const papers = (out.research || []).reduce((n, g) => n + g.papers.length, 0)
  const tone = r.score >= 85 ? 'good' : r.score >= 60 ? 'warn' : 'risk'
  return (
    <div className="stack-lg">
      <div className="card pad-lg verdict">
        <div className="stack" style={{ gap: 10 }}>
          <div className="eyebrow">Launch readiness</div>
          <Score value={r.score ?? 0} max={100} tone={tone} />
          <div className={`state ${tone}`}>{r.band}</div>
        </div>
        <div className="stack">
          <p style={{ margin: 0, fontSize: 18, lineHeight: 1.5 }}>{out.summary}</p>
          <div className="row tiny">
            <Tag tone="risk">{c.high || 0} high</Tag>
            <Tag tone="warn">{c.medium || 0} medium</Tag>
            <Tag>{c.low || 0} low</Tag>
            <Tag tone="good">Read-only, nothing edited</Tag>
          </div>
          <More label="How is this computed?">
            <p className="small muted" style={{ marginTop: 0 }}>{r.formula} Computed in code, no AI.</p>
            <table className="tbl">
              <tbody>
                {(r.penalties || []).map((p) => (
                  <tr key={p.type}><td>{p.title}</td><td><Tag tone={SEV_TONE[p.severity]}>{p.severity}</Tag></td><td className="mono tiny">x{p.count}</td><td className="mono tiny">-{p.points}</td></tr>
                ))}
              </tbody>
            </table>
          </More>
        </div>
      </div>

      <div className="grid g3">
        <button type="button" className="card pad stack" style={{ textAlign: 'left', cursor: 'pointer', gap: 6 }} onClick={() => goTo('points')}>
          <div className="eyebrow" style={{ color: 'var(--risk)' }}>Most serious</div>
          {top ? (
            <>
              <div style={{ fontWeight: 600 }}>{top.title}</div>
              <Where f={top} />
              <div className="small muted clamp-3">{top.scenario}</div>
            </>
          ) : <div className="small muted">No failure points found.</div>}
        </button>
        <button type="button" className="card pad stack" style={{ textAlign: 'left', cursor: 'pointer', gap: 6 }} onClick={() => goTo('research')}>
          <div className="eyebrow accent">Research papers</div>
          <div className="row" style={{ alignItems: 'baseline', gap: 6 }}><span className="display" style={{ fontSize: 40, lineHeight: 1 }}>{papers}</span><span className="muted small">papers</span></div>
          <div className="small muted">on {(out.research || []).filter((g) => g.papers.length).length} kinds of failure, from {out.research_backend}</div>
        </button>
        <button type="button" className="card pad stack" style={{ textAlign: 'left', cursor: 'pointer', gap: 6 }} onClick={() => goTo('fixes')}>
          <div className="eyebrow">Fixes checked in code</div>
          {v.fixes_checked ? (
            <>
              <div className="row" style={{ alignItems: 'baseline', gap: 6 }}><span className="display" style={{ fontSize: 40, lineHeight: 1 }}>{v.failures_removed}</span><span className="muted small">of {v.fixes_checked} remove the problem</span></div>
              <div className="small muted">{v.fixes_compiling}/{v.fixes_checked} parse as Python</div>
            </>
          ) : <div className="small muted">Standard fixes shown ({(out.fixes || []).length}). AI fixes were not available.</div>}
        </button>
      </div>

      <div className="card pad stack">
        <div className="row between"><h3>Kinds of failure found</h3><span className="tiny muted">CWE = MITRE's public list of software weaknesses</span></div>
        <div className="table-wrap">
          <table className="tbl">
            <thead><tr><th>Failure</th><th>Weakness</th><th>Level</th><th>Found</th></tr></thead>
            <tbody>
              {(out.failure_types || []).map((t) => (
                <tr key={t.type}>
                  <td><div style={{ fontWeight: 600 }}>{t.title}</div><div className="tiny muted">{t.why}</div></td>
                  <td><Cwe id={t.cwe} /><div className="tiny muted">{t.cwe_name}</div></td>
                  <td><Tag tone={SEV_TONE[t.severity]}>{t.severity}</Tag></td>
                  <td className="mono">{t.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <More label={`All ${(out.checks_catalog || []).length} checks that ran`}>
          <div className="row tiny">{(out.checks_catalog || []).map((k) => <Tag key={k.type}>{k.title} · {k.cwe}</Tag>)}</div>
        </More>
      </div>
    </div>
  )
}

function Point({ f }) {
  return (
    <div className="card pad stack">
      <div className="row between">
        <div className="row">
          <span className="mono" style={{ fontWeight: 600 }}>{f.id}</span>
          <strong style={{ fontWeight: 650 }}>{f.title}</strong>
          <Tag tone={SEV_TONE[f.severity]}>{f.severity}</Tag>
          <Cwe id={f.cwe} />
        </div>
        <Where f={f} />
      </div>
      <div className="mono small soft" style={{ padding: '6px 10px', overflowX: 'auto', whiteSpace: 'pre' }}>{f.code_line}</div>
      <div className="small"><strong style={{ fontWeight: 600 }}>If it fails: </strong>{f.scenario}</div>
      {(f.callers || []).length > 0 && (
        <div className="row tiny">
          <span className="muted">Reached from</span>
          {f.callers.map((c, i) => <Tag key={i}>{c.symbol}() · {c.file}</Tag>)}
          {(f.entrypoints || []).length > 0 && <Tag tone="risk">{f.entrypoints.length} entry point{f.entrypoints.length > 1 ? 's' : ''}</Tag>}
        </div>
      )}
      <More label="Show the code">
        <Code code={f.context_code} start={f.context_start} mark={f.line} />
      </More>
    </div>
  )
}

function Points({ out }) {
  const [level, setLevel] = useState('all')
  const list = (out.findings || []).filter((f) => level === 'all' || f.severity === level)
  return (
    <div className="stack-lg">
      <div className="row">
        {['all', 'high', 'medium', 'low'].map((l) => (
          <button key={l} className={`chip ${level === l ? 'on' : ''}`} onClick={() => setLevel(l)}>
            {l === 'all' ? `All (${(out.findings || []).length})` : `${l} (${(out.counts || {})[l] || 0})`}
          </button>
        ))}
        <span className="tiny muted">"If it fails" is built from the call graph, not by AI.</span>
      </div>
      {list.map((f) => <Point key={f.id} f={f} />)}
      {!list.length && <div className="empty">Nothing at this level.</div>}
    </div>
  )
}

function Research({ out }) {
  const groups = out.research || []
  return (
    <div className="stack-lg">
      <div className="card pad small muted">
        For each kind of failure, papers are searched live on arXiv, Semantic Scholar and OpenAlex. A paper is kept only if its title or abstract names that failure, then ranked by text similarity. The highlighted sentence is copied from the abstract.
      </div>
      {groups.map((g) => {
        const t = (out.failure_types || []).find((x) => x.type === g.type) || {}
        return (
          <div key={g.type} className="card pad stack">
            <div className="row between">
              <div className="row"><h3>{g.title}</h3><Cwe id={t.cwe} /><Tag tone={SEV_TONE[t.severity]}>{t.count} found</Tag></div>
              <span className="tiny muted">Searched: {g.queries.join(' · ')}</span>
            </div>
            {g.papers.map((p) => (
              <div key={p.ref} className="paper">
                <span className="ref">{p.ref}</span>
                <div className="stack" style={{ gap: 4 }}>
                  <SafeLink href={p.url}><span className="paper-title">{p.title}</span></SafeLink>
                  <div className="tiny muted">{authors(p.authors)}{p.year ? ` · ${p.year}` : ''}{p.venue ? ` · ${p.venue}` : ''} · {SOURCE_NAMES[p.source] || p.source}{p.citation_count ? ` · ${p.citation_count} citations` : ''}</div>
                  {p.key_sentence && <div className="small" style={{ borderLeft: '3px solid var(--line)', paddingLeft: 10 }}>{p.key_sentence}</div>}
                  <div className="paper-links">
                    <SafeLink href={p.url}>Open paper</SafeLink>
                    {p.pdf_url && <SafeLink href={p.pdf_url}>PDF</SafeLink>}
                    {p.doi && <SafeLink href={`https://doi.org/${p.doi}`}>DOI</SafeLink>}
                  </div>
                  <More label="Abstract and reference">
                    <p className="small" style={{ marginTop: 0 }}>{p.abstract || 'No abstract available.'}</p>
                    <div className="mono tiny muted">{p.ieee}</div>
                  </More>
                </div>
                <div className="sim stack" style={{ gap: 4 }}>
                  <span className="tiny muted">Match {Math.round(p.similarity * 100)}%</span>
                  <Bar value={p.similarity * 100} max={100} tone="good" />
                </div>
              </div>
            ))}
            {!g.papers.length && <div className="small muted">No paper that names this failure was found. Nothing was invented in its place.</div>}
            {g.dropped > 0 && <div className="tiny muted">{g.dropped} other search result{g.dropped > 1 ? 's' : ''} did not name this failure and {g.dropped > 1 ? 'were' : 'was'} left out.</div>}
          </div>
        )
      })}
      {!groups.length && <div className="empty">No paper search ran.</div>}
      {(out.notes || []).length > 0 && <More label="Notes"><ul className="list small">{out.notes.map((n, i) => <li key={i}>{plainText(n)}</li>)}</ul></More>}
    </div>
  )
}

function FixCard({ x, f }) {
  const ai = x.generated_by === 'llm'
  const k = x.checks || {}
  return (
    <div className="card pad-lg stack">
      <div className="row between">
        <div className="row">
          <span className="mono" style={{ fontWeight: 600 }}>{x.id}</span>
          <strong style={{ fontWeight: 650 }}>{f?.title}</strong>
          {f && <Tag tone={SEV_TONE[f.severity]}>{f.severity}</Tag>}
        </div>
        <div className="row">{f && <Where f={f} />}<Source value={ai ? 'llm' : 'fallback'} /></div>
      </div>
      <p className="small" style={{ margin: 0 }}>{x.what_can_go_wrong}</p>
      {x.research_note && (
        <div className="soft small" style={{ padding: '10px 12px' }}>
          <strong style={{ fontWeight: 600 }}>What research says: </strong>{x.research_note}
          {ai && x.cited_refs?.length > 0 && <span className="tiny muted"> (papers on the Research tab)</span>}
        </div>
      )}
      {ai && (
        <div className="row" style={{ gap: 6 }}>
          <span className={`check ${k.compiles ? 'ok' : 'no'}`}>{k.compiles ? '✓' : '✗'} Parses as Python</span>
          <span className={`check ${k.failure_gone ? 'ok' : 'no'}`}>{k.failure_gone ? '✓' : '✗'} Same check passes now</span>
          <span className={`check ${k.citations_valid ? 'ok' : 'no'}`}>{k.citations_valid ? '✓' : '✗'} Citations point to real results</span>
          {k.abstract_support !== null && k.abstract_support !== undefined && <span className="check">{Math.round(k.abstract_support * 100)}% of the note's words are in the cited abstracts</span>}
        </div>
      )}
      {ai && x.fixed_code ? (
        <div className="grid g2">
          <div className="stack" style={{ gap: 6 }}><div className="tiny muted">Code now</div><Code code={f?.context_code} start={f?.context_start} mark={f?.line} tone="before" /></div>
          <div className="stack" style={{ gap: 6 }}><div className="tiny muted">Suggested version (not applied)</div><Code code={x.fixed_code} start={0} tone="after" /></div>
        </div>
      ) : (
        <>
          <div className="small"><strong style={{ fontWeight: 600 }}>Standard fix: </strong>{x.fix_hint}</div>
          {f && <More label="Show the code"><Code code={f.context_code} start={f.context_start} mark={f.line} /></More>}
        </>
      )}
    </div>
  )
}

function Fixes({ out }) {
  const byId = Object.fromEntries((out.findings || []).map((f) => [f.id, f]))
  const v = out.verification || {}
  return (
    <div className="stack-lg">
      <div className="row tiny">
        <span className="muted">One fix per kind of failure, most serious first. Every AI fix is checked in code: it must parse, the same failure check must pass on it, and each citation must point to a paper that was retrieved.</span>
        {v.citations_removed > 0 && <Tag tone="warn">{v.citations_removed} invalid citation(s) removed</Tag>}
      </div>
      {(out.fixes || []).map((x) => <FixCard key={x.id} x={x} f={byId[x.id]} />)}
      {!(out.fixes || []).length && <div className="empty">No failure points, so nothing to fix.</div>}
      {out.fallback_reason && <div className="tiny muted">AI fixes not available: {plainText(out.fallback_reason)}</div>}
    </div>
  )
}

export default function FailureResult({ run }) {
  const state = run.result
  const out = state.final_output || {}
  const [tab, setTab] = useState('overview')
  if (out.type === 'error' || out.error) {
    return <div className="card pad"><h3>Could not run</h3><p className="small muted">{out.error}</p></div>
  }
  const papers = (out.research || []).reduce((n, g) => n + g.papers.length, 0)
  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'points', label: 'Failure points', count: (out.findings || []).length },
    { id: 'research', label: 'Research', count: papers },
    { id: 'fixes', label: 'Fixes', count: (out.fixes || []).length },
    { id: 'trace', label: 'How it ran' },
  ]
  return (
    <div className="stack-lg fade-in">
      <div className="eyebrow">Report · session {state.session_id}</div>
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === 'overview' && <Overview out={out} goTo={setTab} />}
      {tab === 'points' && <Points out={out} />}
      {tab === 'research' && <Research out={out} />}
      {tab === 'fixes' && <Fixes out={out} />}
      {tab === 'trace' && <TraceView state={state} calls={run.calls} />}
    </div>
  )
}
