import PipelineGraph from './components/PipelineGraph.jsx'
import { CODE_PIPELINE, FAILURE_PIPELINE, STARTUP_PIPELINE } from './pipelines.js'

// From the project report (cover page).
const PROJECT = [
  ['Project', 'Agentic AI Co-Pilot: a multi-agent RAG system for startup assistance and codebase analysis'],
  ['Course', 'Minor Project (ARP-455)'],
  ['Student', 'Ronak Dutta, B.Tech IIoT, batch IIoT B-1'],
  ['Guide', 'Dr. Sanjay Kumar Singh, Assistant Professor'],
  ['Institute', 'USAR, GGSIPU East Delhi Campus'],
  ['Session', '2026-2027'],
]

// Facts about how the system is built. Keep them true: if the code changes, change these.
const SHEET = [
  ['AI calls per idea run', '7, plus usually 1 for a prototype'],
  ['Paper sources', 'arXiv, Semantic Scholar, OpenAlex (live)'],
  ['Idea score', '7-category rubric, computed in code'],
  ['Code search', 'BM25 keywords + MiniLM embeddings'],
  ['Failure checks', '11 fixed checks, each named by its CWE weakness type'],
  ['Research per failure', 'Live paper search; a paper is kept only if it names the failure'],
  ['Prototype', 'FastAPI + one page, tested with pytest'],
  ['Runs on', 'One Python server on this computer'],
]

// Literature survey of the report; arXiv ids checked against arxiv.org, other links opened and checked.
const PAPERS = [
  ['Lewis et al., 2020', 'Retrieval-Augmented Generation', '2005.11401', 'Answers are built from retrieved code and papers, not from memory'],
  ['Zhang et al., 2024', 'AutoCodeRover', '2404.05427', 'Code is split at function and class boundaries (AST), not into text blocks'],
  ['Jimenez et al., 2024', 'SWE-bench', '2310.06770', 'The task: point to the file and lines behind a real issue'],
  ['Shinn et al., 2023', 'Reflexion', '2303.11366', 'A critic checks the answer and allows one revision'],
  ['Wu et al., 2023', 'AutoGen', '2308.08155', 'Separate agents with one job each, such as devil\'s advocate and judge'],
  ['Yuan et al., OSDI 2014', 'Simple Testing Can Prevent Most Critical Failures', 'https://www.usenix.org/conference/osdi14/technical-sessions/presentation/yuan', 'Most catastrophic failures they studied came from badly handled errors, so ignored errors are rated high'],
  ['MITRE', 'CWE: Common Weakness Enumeration', 'https://cwe.mitre.org/', 'Every failure check is named by its public CWE weakness type'],
]

const TOOLS = [
  {
    id: 'startup',
    n: '1',
    name: 'Startup Assistance',
    line: 'Step 1. Is this idea worth building, and has someone already done it?',
    steps: [
      'Searches the market and live research papers',
      'A devil\'s advocate argues against it, a judge weighs both sides',
      'Scores it with a fixed rubric in code',
      'Writes the PRD and roadmap, then builds and tests a small prototype',
    ],
  },
  {
    id: 'code',
    n: '2',
    name: 'Codebase Evaluation',
    line: 'Step 2. Where is the bug in our code, and what breaks if we change it?',
    steps: [
      'Opens a local folder or a GitHub link',
      'Parses every file into functions and a call graph',
      'Finds the code behind a bug or a question',
      'A critic checks file, lines and quoted code against the disk',
    ],
  },
  {
    id: 'failure',
    n: '3',
    name: 'Failure Simulator',
    line: 'Step 3. Where will the code fail on launch day, and what does research say?',
    steps: [
      'Fixed checks find failure points, each named by its CWE type',
      'The call graph shows which features each failure would break',
      'Live research papers on every kind of failure found',
      'Suggested fixes, checked in code before you see them',
    ],
  },
]

const COMPARE = [
  ['Research papers', 'Can name papers that do not exist', 'Fetched live; every link opens the real paper'],
  ['Scores', 'Change each time you ask', 'Same formula in code, same score'],
  ['Code questions', 'Sees only the snippet you paste', 'Reads the whole project and checks line numbers on disk'],
  ['Prototype', 'Gives code you still have to run', 'Writes it, runs the tests, starts it, watches it'],
  ['Failure points', 'Gives general advice', 'Named checks find them; papers back each kind; every fix is checked'],
  ['When the AI fails', 'Still answers confidently', 'Falls back to plain code and says so'],
]

export default function Landing({ onEnter, theme, setTheme }) {
  return (
    <div className="landing">
      <nav className="l-nav">
        <div className="l-wrap l-nav-inner">
          <button className="l-brand" onClick={() => window.scrollTo({ top: 0 })}>
            <span>Boost Your Startup</span>
          </button>
          <div className="l-links">
            <a href="#tools">Tools</a>
            <a href="#how">How it works</a>
            <a href="#compare">Compared to a chatbot</a>
          </div>
          <button className="icon-btn" aria-label="Toggle dark mode" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
            {theme === 'dark' ? '☀' : '☾'}
          </button>
          <button className="btn primary" onClick={() => onEnter('startup')}>Open the app</button>
        </div>
      </nav>

      <header className="l-wrap l-hero">
        <div className="l-hero-text">
          <p className="l-kicker">Minor Project (ARP-455), B.Tech IIoT, USAR, GGSIPU</p>
          <h1>Boost your startup, from the first idea to launch day.</h1>
          <p className="l-lead">
            Cooperating AI agents check your idea against real research papers and build a small
            working prototype. Then they review your code and find where it would fail before launch,
            with research papers on each kind of failure. Code checks every answer before you see it.
          </p>
          <div className="row" style={{ gap: 12 }}>
            <button className="btn primary l-big" onClick={() => onEnter('startup')}>Open the app</button>
            <a className="btn l-big" href="#how">How it works</a>
          </div>
        </div>
        <table className="l-sheet" aria-label="Project details">
          <caption>Project sheet</caption>
          <tbody>
            {PROJECT.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{v}</td></tr>)}
          </tbody>
        </table>
      </header>

      <section className="l-section">
        <div className="l-wrap l-gap">
          <h2 className="l-h2">The gap it fills</h2>
          <div>
            <p className="l-gap-text">
              A student startup needs help at every stage: is the idea new, can it be built, does the
              code work, and will it hold up when real users arrive. Tools today cover one of these at
              a time, and chatbots often answer without real sources.
            </p>
            <p className="l-gap-text strong">
              Boost Your Startup covers the whole path in one place. Every answer is grounded in live
              research papers and in the real structure of the code, checked in code, and your files
              are never edited.
            </p>
          </div>
        </div>
      </section>

      <section id="tools" className="l-section">
        <div className="l-wrap">
          <h2 className="l-h2">Three tools, one startup journey</h2>
          <div className="l-tools">
            {TOOLS.map((t) => (
              <article key={t.id} className="l-tool">
                <div className="l-num">{t.n}</div>
                <h3>{t.name}</h3>
                <p className="l-tool-line">{t.line}</p>
                <ol>{t.steps.map((s) => <li key={s}>{s}</li>)}</ol>
                <button className="btn" onClick={() => onEnter(t.id)}>Open {t.name}</button>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="how" className="l-section">
        <div className="l-wrap stack-lg">
          <div>
            <h2 className="l-h2">How a run works</h2>
            <p className="l-note">These are the real agent graphs the app lights up while it runs. Boxes marked AI call a language model; the rest is plain code.</p>
          </div>
          <figure className="l-figure">
            <figcaption>Startup Assistance</figcaption>
            <PipelineGraph pipeline={STARTUP_PIPELINE} events={[]} phase="idle" />
          </figure>
          <figure className="l-figure">
            <figcaption>Codebase Evaluation</figcaption>
            <PipelineGraph pipeline={CODE_PIPELINE} events={[]} phase="idle" />
          </figure>
          <figure className="l-figure">
            <figcaption>Failure Simulator</figcaption>
            <PipelineGraph pipeline={FAILURE_PIPELINE} events={[]} phase="idle" />
          </figure>
        </div>
      </section>

      <section className="l-section">
        <div className="l-wrap l-under">
          <div>
            <h2 className="l-h2">Under the hood</h2>
            <table className="l-sheet plain" aria-label="System facts">
              <tbody>
                {SHEET.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{v}</td></tr>)}
              </tbody>
            </table>
          </div>
          <div>
            <h2 className="l-h2">Built on this research</h2>
            <table className="l-papers">
              <tbody>
                {PAPERS.map(([who, title, id, use]) => (
                  <tr key={id}>
                    <td>
                      <a href={id.startsWith('http') ? id : `https://arxiv.org/abs/${id}`} target="_blank" rel="noopener noreferrer">{title}</a>
                      <div className="tiny muted">{who}</div>
                    </td>
                    <td>{use}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section id="compare" className="l-band">
        <div className="l-wrap">
          <h2 className="l-h2">"Can't a chatbot do this?"</h2>
          <p className="l-note">Partly. This is what changes when agents, live sources and code checks work together.</p>
          <div className="l-table-wrap">
            <table className="l-compare">
              <thead><tr><th /><th>Plain chatbot</th><th>Boost Your Startup</th></tr></thead>
              <tbody>
                {COMPARE.map(([k, a, b]) => <tr key={k}><th scope="row">{k}</th><td>{a}</td><td>{b}</td></tr>)}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="l-section l-end">
        <div className="l-wrap l-end-inner">
          <h2 className="l-h2">Start with your idea. Finish launch-ready.</h2>
          <div className="row" style={{ gap: 12 }}>
            <button className="btn primary l-big" onClick={() => onEnter('startup')}>Check an idea</button>
            <button className="btn l-big" onClick={() => onEnter('code')}>Evaluate a codebase</button>
            <button className="btn l-big" onClick={() => onEnter('failure')}>Find failure points</button>
          </div>
        </div>
      </section>

      <footer className="l-wrap l-foot">
        <span>Boost Your Startup (Agentic AI Co-Pilot), by Ronak Dutta</span>
        <span>Guide: Dr. Sanjay Kumar Singh, USAR, GGSIPU</span>
      </footer>
    </div>
  )
}
