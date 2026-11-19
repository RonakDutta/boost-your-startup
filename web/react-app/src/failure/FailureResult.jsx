import { useState } from 'react'
import TraceView from '../components/TraceView.jsx'
import { Bar, More, SafeLink, Score, Source, Tabs, Tag, plainText, useScrollTo } from '../components/ui.jsx'
import { Columns, FlowGraph, HBars, SplitBar, yearColumns } from '../components/charts.jsx'

const SEV_TONE = { high: 'risk', medium: 'warn', low: '' }
const SEV_CHART = { high: 'risk', medium: 'warn', low: 'low' }
const SEV_RANK = { high: 0, medium: 1, low: 2 }
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

/** Entry points -> functions that hold failure points -> kinds of failure. */
function SpreadGraph({ out, goTo }) {
  const findings = out.findings || []
  const entries = new Map(), funcs = new Map(), kinds = new Map(), edges = new Set()
  for (const f of findings) {
    const fid = `f:${f.file_path}:${f.symbol}`
    const worst = funcs.get(fid)?.sev
    if (!funcs.has(fid) || SEV_RANK[f.severity] < SEV_RANK[worst]) {
      funcs.set(fid, { id: fid, label: f.symbol ? `${f.symbol}()` : f.file_path, sub: f.symbol ? f.file_path : 'module settings', tone: SEV_CHART[f.severity], sev: f.severity })
    }
    kinds.set(`k:${f.type}`, { id: `k:${f.type}`, label: f.title, sub: f.cwe, tone: SEV_CHART[f.severity] })
    edges.add(`${fid}|k:${f.type}`)
    for (const e of f.entrypoints || []) {
      const [file, name] = e.includes(':') ? e.split(':') : ['', e]
      if (name === f.symbol) continue
      entries.set(`e:${e}`, { id: `e:${e}`, label: `${name}()`, sub: file, tone: 'accent' })
      edges.add(`e:${e}|${fid}`)
    }
  }
  const columns = [
    { title: 'Entry points (what users call)', nodes: [...entries.values()] },
    { title: 'Code with a failure point', nodes: [...funcs.values()].sort((x, y) => SEV_RANK[x.sev] - SEV_RANK[y.sev]) },
    { title: 'Kind of failure', nodes: [...kinds.values()] },
  ].filter((c) => c.nodes.length)
  if (!findings.length) return null
  return (
    <div className="card pad stack">
      <div className="row between"><h3>How a failure spreads</h3><span className="tiny muted">From the call graph, no AI. Hover a box to follow its path, click it for details.</span></div>
      <FlowGraph columns={columns} edges={[...edges].map((e) => e.split('|'))} onPick={(n) => {
        const [kind, ...rest] = n.id.split(':')
        const value = rest.join(':')
        if (kind === 'k') goTo('points', { by: 'type', value, label: n.label })
        else if (kind === 'f') goTo('points', { by: 'func', value, label: n.label })
        else goTo('points', { by: 'entry', value, label: `reached from ${n.label}` })
      }} />
    </div>
  )
}

function Overview({ out, goTo }) {
  const r = out.readiness || {}
  const c = out.counts || {}
  const v = out.verification || {}
  const groups = out.research || []
  const papers = groups.reduce((n, g) => n + g.papers.length, 0)
  const tone = r.score >= 85 ? 'good' : r.score >= 60 ? 'warn' : 'risk'
  const lost = (sev) => (r.penalties || []).filter((p) => p.severity === sev).reduce((n, p) => n + p.points, 0)
  const byFile = {}
  for (const f of out.findings || []) {
    const row = byFile[f.file_path] || (byFile[f.file_path] = { high: 0, medium: 0, low: 0 })
    row[f.severity] += 1
  }
  const fileRows = Object.entries(byFile)
    .map(([file, n]) => ({ key: file, label: file, value: n.high + n.medium + n.low,
      parts: [{ value: n.high, tone: 'risk' }, { value: n.medium, tone: 'warn' }, { value: n.low, tone: 'low' }],
      tip: `${file}: ${n.high} high, ${n.medium} medium, ${n.low} low. Click for details` }))
    .sort((x, y) => y.value - x.value)
  return (
    <div className="stack-lg">
      <div className="card pad-lg verdict">
        <div className="stack" style={{ gap: 10 }}>
          <div className="eyebrow">Launch readiness</div>
          <Score value={r.score ?? 0} max={100} tone={tone} />
          <div className={`state ${tone}`}>{r.band}</div>
        </div>
        <div className="stack">
          <div className="eyebrow">Where the 100 points went</div>
          <SplitBar unit=" pts" total={100} parts={[
            { label: 'Score left', value: r.score ?? 0, tone: 'good' },
            { label: `High (${c.high || 0} found)`, value: lost('high'), tone: 'risk' },
            { label: `Medium (${c.medium || 0})`, value: lost('medium'), tone: 'warn' },
            { label: `Low (${c.low || 0})`, value: lost('low'), tone: 'low' },
          ]} />
          <More label="How is this computed?">
            <p className="small muted" style={{ marginTop: 0 }}>{r.formula} Computed in code, no AI.</p>
          </More>
        </div>
      </div>

      <div className="grid g2">
        <div className="card pad stack">
          <h3>Failure points by kind</h3>
          <HBars rows={(out.failure_types || []).map((t) => ({ key: t.type, label: t.title, sub: t.cwe, value: t.count, tone: SEV_CHART[t.severity],
            tip: `${t.title} (${t.cwe}): ${t.count} found, ${t.severity}. Click for details` }))}
            onPick={(r) => goTo('points', { by: 'type', value: r.key, label: r.label })}
            legend={[{ label: 'High', tone: 'risk' }, { label: 'Medium', tone: 'warn' }, { label: 'Low', tone: 'low' }]} />
        </div>
        <div className="card pad stack">
          <div className="row between"><h3>Where they are</h3><span className="tiny muted">{c.files_scanned} files scanned</span></div>
          <HBars rows={fileRows} labelWidth={170} onPick={(r) => goTo('points', { by: 'file', value: r.key, label: r.key })} legend={[{ label: 'High', tone: 'risk' }, { label: 'Medium', tone: 'warn' }, { label: 'Low', tone: 'low' }]} />
        </div>
      </div>

      <SpreadGraph out={out} goTo={goTo} />

      <div className="grid g3">
        <button type="button" className="card stat" style={{ textAlign: 'left', cursor: 'pointer' }} onClick={() => goTo('research')}>
          <div className="value">{papers}</div>
          <div className="label">research papers on {groups.filter((g) => g.papers.length).length} kinds of failure</div>
        </button>
        <button type="button" className="card stat" style={{ textAlign: 'left', cursor: 'pointer' }} onClick={() => goTo('fixes')}>
          <div className="value">{v.fixes_checked ? <>{v.failures_removed}<small>/ {v.fixes_checked}</small></> : (out.fixes || []).length}</div>
          <div className="label">{v.fixes_checked ? 'AI fixes that remove the problem (checked in code)' : 'standard fixes (AI fixes not available)'}</div>
        </button>
        <div className="card stat">
          <div className="value">{(out.checks_catalog || []).length}</div>
          <div className="label">checks run, each a CWE weakness type</div>
        </div>
      </div>

      <div className="card pad"><More label="Table view: every kind with its CWE entry">
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
      </More></div>
    </div>
  )
}

function Point({ f, goTo, hasFix }) {
  return (
    <div className="card pad stack" id={`point-${f.id}`}>
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
      <div className="row">
        <More label="Show the code">
          <Code code={f.context_code} start={f.context_start} mark={f.line} />
        </More>
        <button type="button" className="chip" onClick={() => goTo('research', { by: 'type', value: f.type, label: f.title })}>Research on this</button>
        {hasFix && <button type="button" className="chip" onClick={() => goTo('fixes', { by: 'type', value: f.type, label: f.title })}>See the fix</button>}
      </div>
    </div>
  )
}

const MATCH = {
  type: (f, v) => f.type === v,
  func: (f, v) => `${f.file_path}:${f.symbol}` === v,
  file: (f, v) => f.file_path === v,
  entry: (f, v) => (f.entrypoints || []).includes(v),
}

function Points({ out, focus, goTo }) {
  const [level, setLevel] = useState('all')
  const all = out.findings || []
  const focused = focus ? all.filter((f) => MATCH[focus.by]?.(f, focus.value)) : all
  const list = focused.filter((f) => level === 'all' || f.severity === level)
  const fixed = new Set((out.fixes || []).map((x) => (all.find((f) => f.id === x.id) || {}).type))
  return (
    <div className="stack-lg">
      {focus && (
        <div className="focus-bar">
          <span>Showing {focused.length} failure point{focused.length === 1 ? '' : 's'}: <strong>{focus.label}</strong></span>
          <button type="button" className="chip" onClick={() => goTo('points')}>Show all {all.length}</button>
        </div>
      )}
      <div className="row">
        {['all', 'high', 'medium', 'low'].map((l) => (
          <button key={l} className={`chip ${level === l ? 'on' : ''}`} onClick={() => setLevel(l)}>
            {l === 'all' ? `All (${focused.length})` : `${l} (${focused.filter((f) => f.severity === l).length})`}
          </button>
        ))}
        <span className="tiny muted">"If it fails" is built from the call graph, not by AI.</span>
      </div>
      {list.map((f) => <Point key={f.id} f={f} goTo={goTo} hasFix={fixed.has(f.type)} />)}
      {!list.length && <div className="empty">Nothing at this level.</div>}
    </div>
  )
}

function Research({ out, focus, goTo }) {
  const picked = focus?.by === 'type' ? focus.value : null
  useScrollTo(`research-${picked}`, !!picked)
  const groups = out.research || []
  const all = groups.flatMap((g) => g.papers.map((p) => ({ ...p, kind: g.title })))
  const yearData = yearColumns(all)
  const span = all.map((p) => p.year).filter(Boolean).sort((a, b) => a - b)
  return (
    <div className="stack-lg">
      {all.length > 0 && (
        <div className="grid g2">
          <div className="card pad stack">
            <div className="row between"><h3>Results that named the failure</h3><span className="tiny muted">live from {out.research_backend}</span></div>
            <HBars rows={groups.map((g) => {
              const t = (out.failure_types || []).find((x) => x.type === g.type) || {}
              const relevant = g.relevant ?? g.papers.length
              return { key: g.type, label: g.title, sub: t.cwe, value: relevant + g.dropped,
                parts: [{ value: g.papers.length, tone: 'accent' }, { value: relevant - g.papers.length, tone: 'info' }, { value: g.dropped, tone: 'var(--line-strong)' }],
                display: `${relevant} of ${relevant + g.dropped}`,
                tip: `${g.title}: ${relevant + g.dropped} results, ${relevant} named the failure, best ${g.papers.length} shown` }
            })} onPick={(r) => goTo('research', { by: 'type', value: r.key, label: r.label })}
            legend={[{ label: 'Shown (best match)', tone: 'accent' }, { label: 'Also named the failure', tone: 'info' }, { label: 'Left out', tone: 'var(--line-strong)' }]} />
          </div>
          <div className="card pad stack">
            <div className="row between"><h3>When they were published</h3><span className="tiny muted">{all.length} papers, {span[0]} to {span[span.length - 1]}</span></div>
            <Columns data={yearData} height={130} />
          </div>
        </div>
      )}
      <div className="tiny muted">A paper is kept only if its title or abstract names the failure, then ranked by text similarity. The quoted line is copied from the abstract.</div>
      {groups.map((g) => {
        const t = (out.failure_types || []).find((x) => x.type === g.type) || {}
        return (
          <div key={g.type} id={`research-${g.type}`} className={`card pad stack ${picked === g.type ? 'picked' : ''}`}>
            <div className="row between">
              <div className="row"><h3>{g.title}</h3><Cwe id={t.cwe} />
                <button type="button" className="chip" onClick={() => goTo('points', { by: 'type', value: g.type, label: g.title })}>{t.count} found in your code</button></div>
              <span className="tiny muted">Searched: {g.queries.join(' · ')}</span>
            </div>
            {g.papers.map((p, i) => (
              <div key={p.ref} className="paper">
                <span className="ref">{p.ref}</span>
                <div className="stack" style={{ gap: 4 }}>
                  <SafeLink href={p.url}><span className="paper-title">{p.title}</span></SafeLink>
                  <div className="tiny muted">{authors(p.authors)}{p.year ? ` · ${p.year}` : ''} · {SOURCE_NAMES[p.source] || p.source}{p.citation_count ? ` · ${p.citation_count} citations` : ''}</div>
                  {i === 0 && p.key_sentence && <div className="small" style={{ borderLeft: '3px solid var(--accent)', paddingLeft: 10 }}>{p.key_sentence}</div>}
                  <More label="Abstract, links and reference">
                    {i > 0 && p.key_sentence && <p className="small" style={{ marginTop: 0, borderLeft: '3px solid var(--line)', paddingLeft: 10 }}>{p.key_sentence}</p>}
                    <p className="small" style={{ marginTop: 0 }}>{p.abstract || 'No abstract available.'}</p>
                    <div className="paper-links" style={{ marginBottom: 6 }}>
                      <SafeLink href={p.url}>Open paper</SafeLink>
                      {p.pdf_url && <SafeLink href={p.pdf_url}>PDF</SafeLink>}
                      {p.doi && <SafeLink href={`https://doi.org/${p.doi}`}>DOI</SafeLink>}
                    </div>
                    <div className="mono tiny muted">{p.ieee}</div>
                  </More>
                </div>
                <div className="sim stack" style={{ gap: 4 }}>
                  <span className="tiny muted">Match {Math.round(p.similarity * 100)}%</span>
                  <Bar value={p.similarity * 100} max={Math.max(...g.papers.map((x) => x.similarity * 100), 1)} tone="good" />
                </div>
              </div>
            ))}
            {!g.papers.length && <div className="small muted">No paper that names this failure was found. Nothing was invented in its place.</div>}
          </div>
        )
      })}
      {!groups.length && <div className="empty">No paper search ran.</div>}
      {(out.notes || []).length > 0 && <More label="Notes"><ul className="list small">{out.notes.map((n, i) => <li key={i}>{plainText(n)}</li>)}</ul></More>}
    </div>
  )
}

function FixCard({ x, f, picked }) {
  const ai = x.generated_by === 'llm'
  const k = x.checks || {}
  return (
    <div className={`card pad-lg stack ${picked ? 'picked' : ''}`} id={`fix-${f?.type}`}>
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

function Fixes({ out, focus }) {
  const byId = Object.fromEntries((out.findings || []).map((f) => [f.id, f]))
  const picked = focus?.by === 'type' ? focus.value : null
  useScrollTo(`fix-${picked}`, !!picked)
  const v = out.verification || {}
  return (
    <div className="stack-lg">
      {v.fixes_checked > 0 && (
        <div className="card pad stack">
          <div className="row between"><h3>Fix checks, run in code</h3>{v.citations_removed > 0 && <Tag tone="warn">{v.citations_removed} invalid citation(s) removed</Tag>}</div>
          <HBars max={v.fixes_checked} rows={[
            { label: 'Parses as Python', value: v.fixes_compiling, display: `${v.fixes_compiling}/${v.fixes_checked}`, tone: 'good' },
            { label: 'Same check passes now', value: v.failures_removed, display: `${v.failures_removed}/${v.fixes_checked}`, tone: 'good' },
            { label: 'Notes backed by a paper', value: v.notes_with_papers, display: `${v.notes_with_papers}/${(out.fixes || []).length}`, tone: 'accent' },
          ]} />
        </div>
      )}
      <div className="tiny muted">One fix per kind of failure, most serious first. Nothing is applied to your files.</div>
      {(out.fixes || []).map((x) => <FixCard key={x.id} x={x} f={byId[x.id]} picked={picked && byId[x.id]?.type === picked} />)}
      {!(out.fixes || []).length && <div className="empty">No failure points, so nothing to fix.</div>}
      {out.fallback_reason && <div className="tiny muted">AI fixes not available: {plainText(out.fallback_reason)}</div>}
    </div>
  )
}

export default function FailureResult({ run }) {
  const state = run.result
  const out = state.final_output || {}
  const [tab, setTab] = useState('overview')
  const [focus, setFocus] = useState(null)
  if (out.type === 'error' || out.error) {
    return <div className="card pad"><h3>Could not run</h3><p className="small muted">{out.error}</p></div>
  }
  // Clicking a chart item opens a tab focused on that item.
  const go = (id, f = null) => { setTab(id); setFocus(f) }
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
      <Tabs tabs={tabs} value={tab} onChange={(id) => go(id)} />
      {tab === 'overview' && <Overview out={out} goTo={go} />}
      {tab === 'points' && <Points out={out} focus={focus} goTo={go} />}
      {tab === 'research' && <Research out={out} focus={focus} goTo={go} />}
      {tab === 'fixes' && <Fixes out={out} focus={focus} />}
      {tab === 'trace' && <TraceView state={state} calls={run.calls} />}
    </div>
  )
}
