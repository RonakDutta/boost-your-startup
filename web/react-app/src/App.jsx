import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { getJSON, postJSON } from './api.js'
import { useRun } from './useRun.js'
import { CODE_PIPELINE, FAILURE_PIPELINE, STARTUP_PIPELINE } from './pipelines.js'
import PipelineGraph from './components/PipelineGraph.jsx'
import RunPanel from './components/RunPanel.jsx'
import StartupResult from './startup/StartupResult.jsx'
import CodeResult from './code/CodeResult.jsx'
import FailureResult from './failure/FailureResult.jsx'
import { Tag } from './components/ui.jsx'
import Landing from './Landing.jsx'

const IDEA_EXAMPLES = [
  ['Smart water meter', 'A smart ultrasonic water meter for residential buildings using LoRaWAN to detect pipe leakages in real time and estimate daily household consumption.'],
  ['AI code reviewer', 'An automated AI peer review platform for engineering students that checks their lab code submissions for code quality, linting and AST-based standards.'],
  ['Energy spike monitor', 'A low-cost IoT energy auditing system for residential societies that detects abnormal power spikes using ESP32 with CT current sensors and alerts residents.'],
  ['Rubber products store', 'An e-commerce website for a small rubber products manufacturer in Kerala that sells rubber sheets, gaskets, O-rings, hoses and gloves online to workshops and factories, with material and hardness details, minimum order quantities, live stock, bulk discounts, GST and delivery charges by order value.'],
]
// Short answers to "a chatbot can do this too, what is different?"
const STARTUP_WHY = [
  ['Real papers, real links', 'Papers come live from arXiv, Semantic Scholar and OpenAlex. Every link opens the actual paper.'],
  ['Scores computed in code', 'The rubric and the novelty index are formulas. Same idea, same score, every time.'],
  ['Checked before it is shown', 'Invented citations are removed. The prototype is tested and started before you see it.'],
]
const FAILURE_WHY = [
  ['Checks with a name', 'Every failure point comes from a fixed check tied to a CWE entry, the public list of software weaknesses. The same code gives the same result.'],
  ['Backed by research', 'Each kind of failure is linked to real papers found live. A paper is shown only if it names that failure.'],
  ['Fixes are checked', 'A suggested fix must parse, the same check must pass on it, and every citation must point to a paper that was found.'],
]
const CODE_WHY = [
  ['Reads the whole project', 'It parses every file (AST) and builds a call graph, instead of looking at one pasted snippet.'],
  ['Every answer checked on disk', 'File, function, line numbers and quoted code are compared with the real files.'],
  ['Read-only', 'Nothing in your project is changed. Suggested fixes are compiled, not applied.'],
]

function Why({ items }) {
  return (
    <div className="stack" style={{ gap: 10 }}>
      <h3>Why not just ask a chatbot?</h3>
      <div className="why grid g3">
        {items.map(([title, text], i) => (
          <div key={title} className="card">
            <span className="num">0{i + 1}</span>
            <strong style={{ fontWeight: 650 }}>{title}</strong>
            <p>{text}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

const CODE_EXAMPLES = [
  ['Duplicate orders bug', 'Orders sometimes get processed twice when the user double clicks checkout. Where is the bug?'],
  ['Expired token crash', 'ValueError: Token expired when verify_token validates customer credentials during checkout.'],
  ['Blast radius', 'What is the blast radius if I modify verify_token in the auth module?'],
  ['Where is auth checked?', 'Where is customer authentication verified when placing an order, and how is expiry checked?'],
]

function readTheme() {
  try { return localStorage.getItem('copilot-theme') || 'light' } catch { return 'light' }
}

const TOOLS = [
  ['startup', 'Startup Assistance'],
  ['code', 'Codebase Evaluation'],
  ['failure', 'Failure Simulator'],
]

/** A small note in the corner, only when the AI engine or the server is not available. */
function EngineToast() {
  const [health, setHealth] = useState(null)
  const [closed, setClosed] = useState(() => { try { return sessionStorage.getItem('copilot-toast') || '' } catch { return '' } })
  useEffect(() => {
    let alive = true
    const load = () => getJSON('/api/health').then((h) => alive && setHealth(h)).catch(() => alive && setHealth(false))
    load()
    const t = setInterval(load, 20000)
    return () => { alive = false; clearInterval(t) }
  }, [])
  let note = null
  if (health === false) note = ['offline', 'risk', 'The server is not reachable. Start it with python app.py.']
  else if (health && !health.metrics?.llm_configured) note = ['fallback', 'warn', 'The AI engine is off. Steps that need it use built-in versions, and the results say so.']
  else if (health?.rate_limits?.all_rate_limited) note = ['busy', 'warn', 'The AI engine is busy. A run may wait a little or use labelled built-in versions.']
  if (!note || closed === note[0]) return null
  const close = () => { setClosed(note[0]); try { sessionStorage.setItem('copilot-toast', note[0]) } catch { /* private mode */ } }
  return (
    <div className={`toast ${note[1]}`} role="status">
      <span>{note[2]}</span>
      <button type="button" aria-label="Close" onClick={close}>×</button>
    </div>
  )
}

function Header({ pillar, setPillar, theme, setTheme, onHome }) {
  // The sub-tabs stick right under the header, whose height changes on phones (tabs wrap to a second row).
  const ref = useRef(null)
  useLayoutEffect(() => {
    const el = ref.current
    const set = () => document.documentElement.style.setProperty('--topbar-h', `${el.offsetHeight}px`)
    set()
    const ro = new ResizeObserver(set)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return (
    <header className="topbar" ref={ref}>
      <div className="topbar-inner">
        <button className="brand link" onClick={onHome} title="Back to the start page">
          <span className="brand-name">Boost Your Startup</span>
          <span className="brand-sub">Agentic AI Co-Pilot · minor project</span>
        </button>
        <nav className="nav-tabs" role="tablist" aria-label="Choose a tool">
          {TOOLS.map(([id, label]) => (
            <button key={id} role="tab" aria-selected={pillar === id} className={pillar === id ? 'on' : ''} onClick={() => setPillar(id)}>{label}</button>
          ))}
        </nav>
        <button className="icon-btn" aria-label="Toggle dark mode" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
          {theme === 'dark' ? '☀' : '☾'}
        </button>
      </div>
    </header>
  )
}

function RunButton({ running, onRun, onStop, disabled }) {
  return running
    ? <button className="btn" onClick={onStop}>Stop</button>
    : <button className="btn primary" disabled={disabled} onClick={onRun}>Run agents</button>
}

function StartupPage() {
  const [idea, setIdea] = useState('')
  const { run, start, stop } = useRun()
  const running = run?.phase === 'running'
  const go = () => idea.trim().length >= 15 && start({ query: idea.trim(), force_intent: 'idea_validation' })
  return (
    <div className="stack-lg">
      {!run && (
        <div className="hero">
          <div className="eyebrow accent">Startup Assistance</div>
          <h1 className="display">Is your idea worth building?</h1>
          <p>The first step to boosting your startup: seven agents check your idea against the market, real research papers and a devil's advocate, score it with a fixed rubric, and then build a small working prototype.</p>
        </div>
      )}
      <div className="card composer" style={{ marginTop: run ? 24 : 0 }}>
        <textarea className="textarea" value={idea} onChange={(e) => setIdea(e.target.value)} placeholder="Describe your idea: the problem, who has it, and how you would solve it."
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) go() }} />
        <div className="composer-foot">
          <span className="tiny muted">Try:</span>
          {IDEA_EXAMPLES.map(([label, text]) => <button key={label} className="chip" onClick={() => setIdea(text)}>{label}</button>)}
          <RunButton running={running} onRun={go} onStop={stop} disabled={idea.trim().length < 15} />
        </div>
      </div>
      {!run && (
        <div className="card pad stack">
          <div className="row between"><h3>How a run works</h3><span className="tiny muted">The same graph lights up live while it runs</span></div>
          <PipelineGraph pipeline={STARTUP_PIPELINE} events={[]} phase="idle" />
        </div>
      )}
      {!run && <Why items={STARTUP_WHY} />}
      {run && <RunPanel run={run} pipeline={STARTUP_PIPELINE} />}
      {run?.phase === 'error' && <div className="card pad small" style={{ color: 'var(--risk)' }}>{run.error}</div>}
      {run?.result && <StartupResult run={run} />}
    </div>
  )
}

function CodePage() {
  const [repo, setRepo] = useState('')
  const [scan, setScan] = useState(null)
  const [question, setQuestion] = useState('')
  const { run, start, stop } = useRun()
  const running = run?.phase === 'running'
  const isUrl = /^https?:\/\//.test(repo.trim())

  async function useDemo() {
    const data = await getJSON('/api/sample-repo-path')
    setRepo(data.path)
    inspect(data.path)
  }
  async function inspect(path = repo) {
    if (!path.trim()) return
    setScan({ busy: true })
    try {
      const res = await postJSON('/api/inspect-repo', { repo_path: path.trim() })
      setScan(res)
    } catch (err) {
      setScan({ error: err.message })
    }
  }
  const go = () => repo.trim() && question.trim() && start({ query: question.trim(), repo_path: repo.trim(), force_intent: 'codebase_analysis' })

  // "Review with Codebase Evaluation" on a generated prototype fills in this page.
  useEffect(() => {
    const onReview = (e) => { setRepo(e.detail.path); setQuestion(e.detail.question); inspect(e.detail.path) }
    window.addEventListener('copilot:review', onReview)
    return () => window.removeEventListener('copilot:review', onReview)
  })

  return (
    <div className="stack-lg">
      {!run && (
        <div className="hero">
          <div className="eyebrow accent">Codebase Evaluation</div>
          <h1 className="display">Find the bug. See what a change would break.</h1>
          <p>Point it at your startup's Python project. It reads the code structure, finds the functions behind a bug or a question, and a critic checks every answer against your real files. Nothing is edited.</p>
        </div>
      )}
      <div className="card composer" style={{ marginTop: run ? 24 : 0 }}>
        <div className="repo-row">
          <input className="input mono" value={repo} onChange={(e) => { setRepo(e.target.value); setScan(null) }} placeholder="C:/path/to/project  or  https://github.com/owner/repo" />
          <button className="btn" onClick={() => inspect()} disabled={!repo.trim() || scan?.busy}>{scan?.busy ? (isUrl ? 'Cloning...' : 'Scanning...') : 'Scan'}</button>
          <button className="btn" onClick={useDemo}>Demo repo</button>
        </div>
        {scan && !scan.busy && (
          scan.error
            ? <div className="small" style={{ color: 'var(--risk)' }}>{scan.error}</div>
            : <div className="row tiny"><Tag tone="good">{scan.summary?.total_files} files · {scan.summary?.total_chunks} functions and classes</Tag><span className="muted">{scan.is_remote ? `Cloned ${scan.repo_name}` : 'Local folder'}</span></div>
        )}
        <textarea className="textarea" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Paste an error, describe a bug, or ask what a change would break."
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) go() }} />
        <div className="composer-foot">
          <span className="tiny muted">Try:</span>
          {CODE_EXAMPLES.map(([label, text]) => <button key={label} className="chip" onClick={() => setQuestion(text)}>{label}</button>)}
          <RunButton running={running} onRun={go} onStop={stop} disabled={!repo.trim() || !question.trim()} />
        </div>
      </div>
      {!run && (
        <div className="card pad stack">
          <div className="row between"><h3>How a run works</h3><span className="tiny muted">Only one step uses AI. The rest is code you can check.</span></div>
          <PipelineGraph pipeline={CODE_PIPELINE} events={[]} phase="idle" />
        </div>
      )}
      {!run && <Why items={CODE_WHY} />}
      {run && <RunPanel run={run} pipeline={CODE_PIPELINE} />}
      {run?.phase === 'error' && <div className="card pad small" style={{ color: 'var(--risk)' }}>{run.error}</div>}
      {run?.result && <CodeResult run={run} repoPath={repo} />}
    </div>
  )
}

function FailurePage() {
  const [repo, setRepo] = useState('')
  const [scan, setScan] = useState(null)
  const { run, start, stop } = useRun()
  const running = run?.phase === 'running'
  const isUrl = /^https?:\/\//.test(repo.trim())

  async function inspect(path = repo) {
    if (!path.trim()) return
    setScan({ busy: true })
    try {
      setScan(await postJSON('/api/inspect-repo', { repo_path: path.trim() }))
    } catch (err) {
      setScan({ error: err.message })
    }
  }
  async function useDemo() {
    const data = await getJSON('/api/sample-repo-path')
    setRepo(data.startup_path)
    inspect(data.startup_path)
  }
  const go = () => repo.trim() && start({ query: 'Find failure points', repo_path: repo.trim(), force_intent: 'failure_analysis' })

  // "Check for failure points" on a generated prototype fills in this page.
  useEffect(() => {
    const onCheck = (e) => { setRepo(e.detail.path); inspect(e.detail.path) }
    window.addEventListener('copilot:failure', onCheck)
    return () => window.removeEventListener('copilot:failure', onCheck)
  })

  return (
    <div className="stack-lg">
      {!run && (
        <div className="hero">
          <div className="eyebrow accent">Failure Simulator</div>
          <h1 className="display">Will your code survive launch day?</h1>
          <p>Before your startup goes live, find the places where its code is likely to fail. See what each failure would break for your users, and what research papers say about that kind of failure.</p>
        </div>
      )}
      <div className="card composer" style={{ marginTop: run ? 24 : 0 }}>
        <div className="repo-row">
          <input className="input mono" value={repo} onChange={(e) => { setRepo(e.target.value); setScan(null) }} placeholder="C:/path/to/project  or  https://github.com/owner/repo" />
          <button className="btn" onClick={() => inspect()} disabled={!repo.trim() || scan?.busy}>{scan?.busy ? (isUrl ? 'Cloning...' : 'Scanning...') : 'Scan'}</button>
          <button className="btn" onClick={useDemo}>Demo startup repo</button>
        </div>
        {scan && !scan.busy && (
          scan.error
            ? <div className="small" style={{ color: 'var(--risk)' }}>{scan.error}</div>
            : <div className="row tiny"><Tag tone="good">{scan.summary?.total_files} files · {scan.summary?.total_chunks} functions and classes</Tag><span className="muted">{scan.is_remote ? `Cloned ${scan.repo_name}` : 'Local folder'}</span></div>
        )}
        <div className="composer-foot">
          <span className="tiny muted">Read-only: nothing in the project is changed or run.</span>
          <RunButton running={running} onRun={go} onStop={stop} disabled={!repo.trim()} />
        </div>
      </div>
      {!run && (
        <div className="card pad stack">
          <div className="row between"><h3>How a run works</h3><span className="tiny muted">Only one step uses AI. The checks, the spread and the paper search are code.</span></div>
          <PipelineGraph pipeline={FAILURE_PIPELINE} events={[]} phase="idle" />
        </div>
      )}
      {!run && <Why items={FAILURE_WHY} />}
      {!run && (
        <div className="card pad small" style={{ color: 'var(--ink-2)' }}>
          In CB Insights' 2026 study of 385 failed startups, 3% named technical issues and 3% fraud or legal problems as a reason.
          This tool checks the code side of both. The bigger reasons, such as poor product-market fit (43%), are covered by Startup Assistance.
        </div>
      )}
      {run && <RunPanel run={run} pipeline={FAILURE_PIPELINE} />}
      {run?.phase === 'error' && <div className="card pad small" style={{ color: 'var(--risk)' }}>{run.error}</div>}
      {run?.result && <FailureResult run={run} />}
    </div>
  )
}

// "#/app" (or "#/app/code") shows the tools; anything else shows the landing page.
function readRoute() {
  const hash = window.location.hash
  return { inApp: hash.startsWith('#/app'), pillar: hash === '#/app/code' ? 'code' : hash === '#/app/failure' ? 'failure' : 'startup' }
}

export default function App() {
  const [route, setRoute] = useState(readRoute)
  const [pillar, setPillarRaw] = useState(route.pillar)
  const [theme, setTheme] = useState(readTheme)
  // Each tool remembers where you were on its page, so switching tools does not leave you mid-page elsewhere.
  const scrollAt = useRef({})
  const restore = useRef(null)
  const current = useRef(pillar)
  const setPillar = (p, top) => {
    if (current.current !== p) {
      scrollAt.current[current.current] = window.scrollY
      restore.current = top ?? scrollAt.current[p] ?? 0
      current.current = p
    } else if (top !== undefined) window.scrollTo({ top, behavior: 'instant' })
    setPillarRaw(p)
  }
  useLayoutEffect(() => {
    if (restore.current !== null) { window.scrollTo({ top: restore.current, behavior: 'instant' }); restore.current = null }
  }, [pillar])
  useEffect(() => {
    const onHash = () => { const r = readRoute(); setRoute(r); if (r.inApp) setPillar(r.pillar) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const enter = (p) => { window.location.hash = p === 'code' ? '#/app/code' : p === 'failure' ? '#/app/failure' : '#/app'; window.scrollTo({ top: 0 }) }
  const home = () => { window.location.hash = ''; window.scrollTo({ top: 0 }) }
  useEffect(() => {
    const toCode = () => setPillar('code', 0)
    const toFailure = () => setPillar('failure', 0)
    window.addEventListener('copilot:review', toCode)
    window.addEventListener('copilot:failure', toFailure)
    return () => { window.removeEventListener('copilot:review', toCode); window.removeEventListener('copilot:failure', toFailure) }
  }, [])
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('copilot-theme', theme) } catch { /* private mode */ }
  }, [theme])
  if (!route.inApp) return <Landing onEnter={enter} theme={theme} setTheme={setTheme} />
  return (
    <>
      <Header pillar={pillar} setPillar={setPillar} theme={theme} setTheme={setTheme} onHome={home} />
      <EngineToast />
      <main className="shell">
        {/* Both pages stay mounted so a running review keeps going when you switch. */}
        <div hidden={pillar !== 'startup'}><StartupPage /></div>
        <div hidden={pillar !== 'code'}><CodePage /></div>
        <div hidden={pillar !== 'failure'}><FailurePage /></div>
        <footer className="foot">
          <span>Every score is computed in code. AI text is labelled, and so is built-in text.</span>
          <span>Boost Your Startup · B.Tech minor project, USAR, GGSIPU</span>
        </footer>
      </main>
    </>
  )
}
