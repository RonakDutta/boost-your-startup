import { useRef, useState } from 'react'

// Small flat charts drawn with divs and SVG. Colours come from the theme tokens,
// so light and dark mode both work. Every mark shows its exact value on hover.

export const TONE = {
  risk: 'var(--risk)', warn: 'var(--warn)', good: 'var(--good)', accent: 'var(--accent)',
  info: 'var(--info)', low: 'var(--muted)', '': 'var(--accent)',
}
const color = (tone) => TONE[tone] || tone || 'var(--accent)'

/** Hover readout shared by the charts below. */
function useTip() {
  const box = useRef(null)
  const [tip, setTip] = useState(null)
  const show = (e, content) => {
    const r = box.current?.getBoundingClientRect()
    if (!r) return
    const x = (e.clientX ?? r.left + r.width / 2) - r.left
    const y = (e.clientY ?? r.top) - r.top
    setTip({ x: Math.min(Math.max(x, 70), r.width - 70), y, content })
  }
  const hide = () => setTip(null)
  const el = tip && <div className="chart-tip" style={{ left: tip.x, top: tip.y }}>{tip.content}</div>
  return { box, show, hide, el }
}

/**
 * Horizontal bars: one row per item, value at the bar's tip. A row with `parts`
 * is a stacked bar (segments split by a 2px gap); pass `legend` to name the parts.
 */
export function HBars({ rows, max, unit = '', onPick, labelWidth = 190, legend }) {
  const { box, show, hide, el } = useTip()
  const total = (r) => (r.parts ? r.parts.reduce((n, p) => n + p.value, 0) : r.value)
  const top = max || Math.max(1, ...rows.map(total))
  return (
    <div className="chart" ref={box} onMouseLeave={hide}>
      <div className="hbars" style={{ gridTemplateColumns: `minmax(0, ${labelWidth}px) minmax(0, 1fr)` }}>
        {rows.map((r, i) => (
          <div key={r.key || i} className={`hbar-row ${onPick ? 'pick' : ''}`} style={{ display: 'contents' }}
            onClick={onPick ? () => onPick(r) : undefined}>
            <div className="hbar-label" title={r.label}>
              <span>{r.label}</span>
              {r.sub && <span className="tiny muted">{r.sub}</span>}
            </div>
            <div className="hbar-track" tabIndex={0}
              onMouseMove={(e) => show(e, r.tip || `${r.label}: ${r.value}${unit}`)}
              onFocus={(e) => show(e, r.tip || `${r.label}: ${r.value}${unit}`)} onBlur={hide}>
              {r.parts ? (
                <span className="hbar-stack" style={{ width: `${Math.max(1.5, (total(r) / top) * 100)}%` }}>
                  {r.parts.filter((p) => p.value > 0).map((p, j) => <i key={j} style={{ flexGrow: p.value, background: color(p.tone) }} />)}
                </span>
              ) : <i style={{ width: `${Math.max(1.5, (r.value / top) * 100)}%`, background: color(r.tone) }} />}
              <b>{r.display ?? `${total(r)}${unit}`}</b>
            </div>
          </div>
        ))}
      </div>
      {legend && <div className="legend">{legend.map((l) => <span key={l.label}><i style={{ background: color(l.tone) }} />{l.label}</span>)}</div>}
      {el}
    </div>
  )
}

/** One whole split into parts (for example: points kept vs points lost), with a legend. */
export function SplitBar({ parts, total, unit = '' }) {
  const { box, show, hide, el } = useTip()
  const sum = total || parts.reduce((n, p) => n + p.value, 0) || 1
  return (
    <div className="chart" ref={box} onMouseLeave={hide}>
      <div className="split-bar">
        {parts.filter((p) => p.value > 0).map((p, i) => (
          <i key={i} tabIndex={0} style={{ flexGrow: p.value, background: color(p.tone) }}
            onMouseMove={(e) => show(e, `${p.label}: ${p.value}${unit}`)} onFocus={(e) => show(e, `${p.label}: ${p.value}${unit}`)} onBlur={hide} />
        ))}
      </div>
      <div className="legend">
        {parts.map((p, i) => (
          <span key={i}><i style={{ background: color(p.tone) }} />{p.label} <b>{p.value}{unit}</b></span>
        ))}
      </div>
      {el}
      <span className="sr-only">{parts.map((p) => `${p.label} ${p.value}${unit}`).join(', ')} of {sum}{unit}</span>
    </div>
  )
}

/** Vertical columns over a category axis (for example papers per year). Labels only the highest. */
export function Columns({ data, height = 120, unit = '' }) {
  const { box, show, hide, el } = useTip()
  const top = Math.max(1, ...data.map((d) => d.value))
  const peak = data.findIndex((d) => d.value === top)
  return (
    <div className="chart" ref={box} onMouseLeave={hide}>
      <div className="cols-chart" style={{ height }}>
        {data.map((d, i) => (
          <div key={d.label} className="col" tabIndex={0}
            onMouseMove={(e) => show(e, d.tip || `${d.label}: ${d.value}${unit}`)} onFocus={(e) => show(e, d.tip || `${d.label}: ${d.value}${unit}`)} onBlur={hide}>
            {i === peak && <span className="cap">{d.value}</span>}
            <i style={{ height: d.value ? `${(d.value / top) * 100}%` : 0, background: color(d.tone) }} />
          </div>
        ))}
      </div>
      <div className="cols-axis">{data.map((d) => <span key={d.label}>{d.label}</span>)}</div>
      {el}
    </div>
  )
}

/** Timeline of consecutive phases (start and length in weeks). */
export function Timeline({ items, unit = 'weeks' }) {
  const { box, show, hide, el } = useTip()
  const end = Math.max(1, ...items.map((t) => t.start + t.length))
  return (
    <div className="chart" ref={box} onMouseLeave={hide}>
      <div className="timeline">
        {items.map((t, i) => (
          <div key={i} className="tl-row">
            <div className="hbar-label"><span>{t.label}</span>{t.sub && <span className="tiny muted">{t.sub}</span>}</div>
            <div className="tl-track">
              <i tabIndex={0} style={{ left: `${(t.start / end) * 100}%`, width: `${Math.max(2, (t.length / end) * 100)}%`, background: color(t.tone) }}
                onMouseMove={(e) => show(e, `${t.label}: ${unit} ${t.start + 1} to ${t.start + t.length}`)}
                onFocus={(e) => show(e, `${t.label}: ${unit} ${t.start + 1} to ${t.start + t.length}`)} onBlur={hide} />
            </div>
          </div>
        ))}
        <div className="tl-row">
          <div />
          <div className="tl-axis"><span>Start</span><span>{unit === 'weeks' ? `Week ${end}` : end}</span></div>
        </div>
      </div>
      {el}
    </div>
  )
}

/**
 * Left-to-right graph: columns of nodes, edges between them. Hovering a node
 * highlights everything connected to it.
 * columns: [{title, nodes: [{id, label, sub, tone}]}], edges: [[fromId, toId]]
 */
export function FlowGraph({ columns, edges, onPick }) {
  const [hot, setHot] = useState(null)
  const colW = 236, gapX = 64, nodeH = 40, gapY = 10, top = 28
  const rows = Math.max(1, ...columns.map((c) => c.nodes.length))
  const height = top + rows * (nodeH + gapY) + 4
  const width = columns.length * colW + (columns.length - 1) * gapX
  const pos = {}
  columns.forEach((c, ci) => {
    const offset = ((rows - c.nodes.length) * (nodeH + gapY)) / 2
    c.nodes.forEach((n, ni) => { pos[n.id] = { x: ci * (colW + gapX), y: top + offset + ni * (nodeH + gapY) } })
  })
  const linked = new Set()
  if (hot) {
    // Everything reachable from the hovered node in either direction.
    const walk = (id, dir) => edges.forEach(([a, b]) => {
      const next = dir > 0 ? (a === id ? b : null) : (b === id ? a : null)
      if (next && !linked.has(next)) { linked.add(next); walk(next, dir) }
    })
    linked.add(hot); walk(hot, 1); walk(hot, -1)
  }
  const cut = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)
  return (
    <div className="flow-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', maxWidth: width, minWidth: 640, height: 'auto', display: 'block' }} role="img"
        aria-label={columns.map((c) => `${c.title}: ${c.nodes.map((n) => n.label).join(', ')}`).join('. ')}>
        {columns.map((c, ci) => (
          <text key={c.title} x={ci * (colW + gapX)} y={14} className="flow-title">{c.title}</text>
        ))}
        {edges.map(([a, b], i) => {
          const p = pos[a], q = pos[b]
          if (!p || !q) return null
          const x1 = p.x + colW, y1 = p.y + nodeH / 2, x2 = q.x, y2 = q.y + nodeH / 2, mx = (x1 + x2) / 2
          const on = hot && linked.has(a) && linked.has(b)
          return <path key={i} d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} fill="none"
            stroke={on ? 'var(--ink-2)' : 'var(--line-strong)'} strokeWidth={on ? 2 : 1.25} opacity={hot && !on ? 0.35 : 1} />
        })}
        {columns.flatMap((c) => c.nodes.map((n) => {
          const p = pos[n.id]
          const dim = hot && !linked.has(n.id)
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`} opacity={dim ? 0.4 : 1} style={{ cursor: onPick ? 'pointer' : 'default' }}
              onMouseEnter={() => setHot(n.id)} onMouseLeave={() => setHot(null)} onClick={onPick ? () => onPick(n) : undefined}>
              <title>{n.label}{n.sub ? ` · ${n.sub}` : ''}</title>
              <rect width={colW} height={nodeH} rx={4} fill="var(--surface)" stroke="var(--line-strong)" />
              <rect width={4} height={nodeH} rx={2} fill={color(n.tone)} />
              <text x={12} y={n.sub ? 17 : 25} className="flow-label">{cut(n.label, 30)}</text>
              {n.sub && <text x={12} y={32} className="flow-sub">{cut(n.sub, 34)}</text>}
            </g>
          )
        }))}
      </svg>
    </div>
  )
}
