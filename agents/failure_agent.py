"""
Failure Simulator: finds the places where a startup's code is likely to fail,
shows how far each failure would spread, and links every kind of failure to
research papers that study it.

Steps (each one is a trace step, so the UI shows real progress):
1. Failure Scanner  (code)      : fixed AST checks, each mapped to a CWE weakness type.
2. Failure Spread   (code)      : call graph, who calls the failing function and which entry points it reaches,
                                  plus a short "what happens if it fails" scenario built from those facts.
3. Failure Research (live search): papers from arXiv, Semantic Scholar and OpenAlex per failure type,
                                  kept only if they name the failure, ranked by text similarity.
4. Fix Advisor      (1 AI call) : a fix for the top failure points, with a note on what the papers found.
5. Fix Critic       (code)      : each fix must parse, the same check must no longer fire on it, and
                                  every [R] citation must point to a paper that was actually retrieved.
The readiness score is computed in code from the findings.
"""

import json
import logging
import os
import re
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from agents.prior_art_agent import clean_citations, embed_texts, support_ratio
from agents.workflow_state import AgentWorkflowState
from core.config import settings
from core.llm import AGENT_MAX_TOKENS, llm_client
from tools import failure_checks as checks
from tools.paper_search import ieee_reference, search_papers

logger = logging.getLogger(__name__)

MAX_FINDINGS = 40          # shown in the report
MAX_RESEARCH_TYPES = 5     # failure types that get a paper search
PAPERS_PER_TYPE = 3
MAX_FIXES = 5              # failure points sent to the Fix Advisor
CONTEXT_MAX_LINES = 30
ABSTRACT_CHARS = 450

FIX_PROMPT = """You help a student startup fix failure points that a code scanner found.
For each failure point you get: its id, the kind of failure, the CWE weakness id, the code (with line numbers) and up to 3 research papers [R1], [R2], [R3] about this kind of failure (title and part of the abstract).

Return JSON only:
{"fixes": [{"id": "F1", "what_can_go_wrong": "1 or 2 short sentences about what fails for the users", "fixed_code": "the corrected code, same lines, plain Python without line numbers", "research_note": "1 or 2 sentences on what the papers found about this kind of failure, citing them like [R1]"}]}
Rules:
- fixed_code must be valid Python and must remove the failure point. Keep it short; change only what is needed.
- research_note may only use facts from the given abstracts. If no paper is given, return an empty research_note.
- No markdown, no extra keys."""


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if len(s.strip()) > 30]


def key_sentence(abstract: str, topic: str) -> str:
    """The abstract sentence that shares the most words with the failure topic (no AI)."""
    best, best_score = "", -1.0
    for sentence in _sentences(abstract)[:12]:
        score = support_ratio(topic, sentence)
        if score > best_score:
            best, best_score = sentence, score
    return best[:300]


class FailureSimulatorAgent:
    def __init__(self, searcher=search_papers):
        self.llm = llm_client
        self.searcher = searcher
        self.research_enabled: Optional[bool] = None  # None: follow PRIOR_ART_ENABLED (tests set it)

    # ------------------------------------------------------------ 1. scan

    @staticmethod
    def scan(index, repo_path: str) -> Tuple[List[checks.Finding], int, Dict[str, int]]:
        findings: List[checks.Finding] = []
        scanned = 0
        skipped_tests = 0
        for rel in index.file_list:
            if checks.is_test_file(rel):
                skipped_tests += 1
                continue
            path = os.path.join(repo_path, rel)
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    source = handle.read()
            except OSError:
                continue
            scanned += 1
            lines = source.splitlines()
            hits = checks.scan_source(source, rel)
            secrets = [extra for kind, _, extra in hits if kind == "hardcoded_secret"]
            chunks = [c for c in index.get_file_chunks(rel) if c.chunk_type == "function"]
            for kind, line, extra in hits:
                owner = None
                for chunk in chunks:  # innermost function that holds the line
                    if chunk.start_line <= line <= chunk.end_line and (owner is None or chunk.start_line >= owner.start_line):
                        owner = chunk
                if owner and owner.end_line - owner.start_line < CONTEXT_MAX_LINES:
                    start, end = owner.start_line, owner.end_line
                else:
                    start, end = max(1, line - 4), min(len(lines), line + 4)
                context = "\n".join(lines[start - 1:end])
                code_line = lines[line - 1] if 0 < line <= len(lines) else ""
                for secret in secrets:
                    context, code_line = checks.mask_secret(context, secret), checks.mask_secret(code_line, secret)
                findings.append(checks.Finding(
                    id="", type=kind, file_path=rel, line=line, symbol=owner.name if owner else "",
                    code_line=code_line.strip(), context_start=start, context_code=context,
                ))
        rank = {"high": 0, "medium": 1, "low": 2}
        findings.sort(key=lambda f: (rank[checks.FAILURE_TYPES[f.type]["severity"]], f.file_path, f.line))
        for n, f in enumerate(findings, start=1):
            f.id = f"F{n}"
        return findings, scanned, {"test_files_skipped": skipped_tests}

    # ------------------------------------------------------------ 2. spread

    @staticmethod
    def spread(index, findings: List[checks.Finding]) -> None:
        """Who is hit when this code fails: callers from the call graph, and a scenario built from them."""
        from agents.change_impact_agent import ChangeImpactAgent

        impact_agent = ChangeImpactAgent(codebase_index=index)
        cache: Dict[Tuple[str, str], Any] = {}
        for f in findings:
            target = f.symbol.split(".")[-1]
            callers: List[Dict[str, Any]] = []
            entries: List[str] = []
            if target:
                key = (target, f.file_path)
                if key not in cache:
                    try:
                        cache[key] = impact_agent.analyze_impact(target_symbol=target, target_file=f.file_path).to_dict()
                    except Exception as err:  # pragma: no cover
                        logger.debug(f"[Failure] impact skipped for {target}: {err}")
                        cache[key] = {}
                impact = cache[key]
                for c in (impact.get("direct_callers") or []) + (impact.get("indirect_callers") or []):
                    if not c.get("is_test"):
                        callers.append({"symbol": c["symbol_name"], "file": c["file_path"], "line": c["line"], "depth": c["depth"]})
                entries = [e for e in impact.get("affected_entrypoints") or [] if e]
                if impact_agent._is_entrypoint(f.file_path, target) and target not in " ".join(entries):
                    entries.insert(0, f"{f.file_path}:{target}")
            f.callers = callers[:8]
            f.entrypoints = entries[:5]
            entry_name = (entries[0].split(":")[-1] if entries else (callers[-1]["symbol"] if callers else "")) or ""
            symbol = f"{f.symbol}()" if f.symbol else f"this line in {f.file_path}"
            entry = f"{entry_name}()" if entry_name and entry_name != f.symbol else "the feature that uses it"
            f.scenario = checks.FAILURE_TYPES[f.type]["scenario"].format(symbol=symbol, entry=entry, file=f.file_path)

    # ------------------------------------------------------------ 3. research

    def research(self, types: List[str]) -> Tuple[List[Dict[str, Any]], List[str], str]:
        """Live paper search per failure type. Returns (groups, notes, backend label)."""
        notes: List[str] = []
        enabled = settings.prior_art_enabled if self.research_enabled is None else self.research_enabled
        if not enabled:
            return [], ["Paper search is switched off (PRIOR_ART_ENABLED=0)."], "off"

        def one(kind: str):
            info = checks.FAILURE_TYPES[kind]
            try:
                return kind, self.searcher(info["queries"], per_source=5)
            except Exception as err:
                return kind, err

        groups: List[Dict[str, Any]] = []
        sources: set = set()
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="failure-papers") as pool:
            results = list(pool.map(one, types))
        similarity_backend = ""
        for kind, result in results:
            info = checks.FAILURE_TYPES[kind]
            if isinstance(result, Exception):
                notes.append(f"Paper search for '{info['title']}' failed ({str(result)[:80]}).")
                continue
            sources.update(result.sources_ok)
            if result.from_cache:
                notes.append(f"Papers for '{info['title']}' came from the 7-day cache of an earlier live search.")
            relevant = [p for p in result.papers if p.title and checks.mentions_topic(f"{p.title} {p.abstract}", kind)]
            dropped = len([p for p in result.papers if p.title]) - len(relevant)
            if not relevant:
                notes.append(f"No paper that names '{info['title'].lower()}' was found; nothing was invented in its place.")
                groups.append({"type": kind, "title": info["title"], "queries": info["queries"], "papers": [], "dropped": dropped})
                continue
            vectors, similarity_backend = embed_texts([info["topic"]] + [f"{p.title}. {p.abstract[:1500]}" for p in relevant])
            sims = (vectors[1:] @ vectors[0]).tolist()
            ranked = sorted(zip(sims, relevant), key=lambda pair: -pair[0])[:PAPERS_PER_TYPE]
            papers = []
            for n, (sim, p) in enumerate(ranked, start=1):
                papers.append({
                    "ref": f"R{n}", "title": p.title, "authors": p.authors[:4], "year": p.year, "venue": p.venue,
                    "url": p.url, "pdf_url": p.pdf_url, "doi": p.doi, "source": p.source,
                    "citation_count": p.citation_count, "similarity": round(float(sim), 3),
                    "abstract": p.abstract[:900], "key_sentence": key_sentence(p.abstract, info["topic"]),
                    "ieee": ieee_reference(p, n),
                })
            groups.append({"type": kind, "title": info["title"], "queries": info["queries"], "papers": papers, "dropped": dropped})
        if similarity_backend == "TF-IDF":
            notes.append("Papers were ranked with TF-IDF word overlap (the MiniLM model was not available).")
        names = {"arxiv": "arXiv", "semantic_scholar": "Semantic Scholar", "openalex": "OpenAlex"}
        return groups, notes, " + ".join(names.get(x, x) for x in sorted(sources)) or "unavailable"

    # ------------------------------------------------------------ 4 + 5. fixes

    @staticmethod
    def pick_for_fixes(findings: List[checks.Finding]) -> List[checks.Finding]:
        """Most severe first, one per failure type before repeating a type."""
        picked, seen = [], set()
        for f in findings:
            if f.type not in seen:
                picked.append(f)
                seen.add(f.type)
        return picked[:MAX_FIXES]

    def advise(self, picked: List[checks.Finding], papers_by_type: Dict[str, List[Dict[str, Any]]]):
        """One AI call for every picked failure point. Returns (fixes by id, source, reason, model)."""
        if not picked:
            return {}, "deterministic", "", ""
        blocks = []
        for f in picked:
            info = checks.FAILURE_TYPES[f.type]
            numbered = "\n".join(f"{f.context_start + i:>4} | {line}" for i, line in enumerate(f.context_code.splitlines()))
            refs = "\n".join(f"[{p['ref']}] {p['title']} ({p['year'] or 'n.d.'}): {p['abstract'][:ABSTRACT_CHARS]}"
                             for p in papers_by_type.get(f.type, []))
            blocks.append(f"### {f.id}: {info['title']} ({info['cwe']} {info['cwe_name']}) in {f.file_path}, line {f.line}\n"
                          f"```\n{numbered}\n```\nPapers:\n{refs or '(none found)'}")
        try:
            raw = self.llm.generate_json(
                [{"role": "system", "content": FIX_PROMPT}, {"role": "user", "content": "\n\n".join(blocks)}],
                temperature=0.2, max_tokens=AGENT_MAX_TOKENS["failure_fix"],
            )
        except Exception as err:
            return {}, "fallback", str(err)[:200], ""
        fixes = {}
        for item in raw.get("fixes") or []:
            if isinstance(item, dict) and str(item.get("id", "")).strip() in {f.id for f in picked}:
                fixes[str(item["id"]).strip()] = item
        if not fixes:
            return {}, "fallback", "The fix answer held no usable fixes.", ""
        return fixes, "llm", "", ""

    @staticmethod
    def critic(f: checks.Finding, item: Optional[Dict[str, Any]], papers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Checks one suggested fix in code. A fix that fails a check is shown with that result, not hidden."""
        info = checks.FAILURE_TYPES[f.type]
        if not item:
            note = ""
            if papers:
                top = papers[0]
                note = f"Closest paper: \"{top['title']}\" ({top['year'] or 'n.d.'}). From its abstract: {top['key_sentence']}"
            return {"id": f.id, "what_can_go_wrong": info["why"], "fixed_code": "", "fix_hint": info["fix"],
                    "research_note": note, "cited_refs": [r["ref"] for r in papers[:1]], "generated_by": "fallback",
                    "checks": {"compiles": None, "failure_gone": None, "citations_valid": True, "abstract_support": None}}
        code = textwrap.dedent(str(item.get("fixed_code") or "")).strip("\n")
        code = re.sub(r"^\s*\d+\s*\|\s?", "", code, flags=re.MULTILINE) if re.match(r"^\s*\d+\s*\|", code) else code
        code_checks = checks.fixed_code_check(code, f.type)
        note_raw = re.sub(r"\[R(\d+)\]", r"[\1]", str(item.get("research_note") or "").strip())
        note, removed, cited = clean_citations(note_raw, len(papers))
        note = re.sub(r"\[(\d+)\]", r"[R\1]", note)
        cited_papers = [papers[n - 1] for n in cited]
        support = round(sum(support_ratio(note, p["abstract"]) for p in cited_papers) / len(cited_papers), 2) if cited_papers else None
        if note and not cited_papers:
            note, support = "", None  # a research claim with no retrieved paper behind it is dropped
        return {"id": f.id, "what_can_go_wrong": str(item.get("what_can_go_wrong") or info["why"])[:400],
                "fixed_code": code[:3000], "fix_hint": info["fix"], "research_note": note[:600],
                "cited_refs": [f"R{n}" for n in cited], "generated_by": "llm",
                "checks": {**code_checks, "citations_valid": removed == 0, "abstract_support": support,
                           "citations_removed": removed}}

    # ------------------------------------------------------------ pipeline

    def run(self, index, repo_path: str, state: AgentWorkflowState, step) -> Dict[str, Any]:
        """`step(name, fn)` is the orchestrator's guarded step runner (cancel + crash fallback)."""
        started = time.time()
        findings, scanned, scan_notes = step("Failure Scanner", lambda: self.scan(index, repo_path))
        by_type: Dict[str, int] = {}
        for f in findings:
            by_type[f.type] = by_type.get(f.type, 0) + 1
        state.add_trace(
            "Failure Scanner",
            f"Checked {scanned} Python files: {len(findings)} failure point(s) of {len(by_type)} kind(s)",
            status="completed", duration_ms=int((time.time() - started) * 1000),
            output_summary=", ".join(f"{checks.FAILURE_TYPES[k]['title']} x{v}" for k, v in by_type.items())[:240],
            details={"tool": f"{len(checks.FAILURE_TYPES)} fixed AST checks, each mapped to a CWE (no AI)",
                     "test_files_skipped": scan_notes["test_files_skipped"]},
        )

        started = time.time()
        step("Failure Spread", lambda: self.spread(index, findings))
        reached = sorted({e for f in findings for e in f.entrypoints})
        state.add_trace(
            "Failure Spread",
            f"Traced callers for {sum(1 for f in findings if f.symbol)} failure point(s); {len(reached)} entry point(s) can be hit",
            duration_ms=int((time.time() - started) * 1000),
            details={"tool": "AST call graph (no AI)", "entrypoints": reached[:10]},
        )

        weight = {"high": 3, "medium": 2, "low": 1}
        type_order = sorted(by_type, key=lambda k: (-weight[checks.FAILURE_TYPES[k]["severity"]] * min(by_type[k], 3), k))
        started = time.time()
        groups, research_notes, backend = step("Failure Research", lambda: self.research(type_order[:MAX_RESEARCH_TYPES]))
        papers_found = sum(len(g["papers"]) for g in groups)
        state.add_trace(
            "Failure Research",
            f"{papers_found} paper(s) for {sum(1 for g in groups if g['papers'])} failure type(s) from {backend}",
            status="completed" if papers_found else "warning",
            duration_ms=int((time.time() - started) * 1000),
            details={"tool": "arXiv, Semantic Scholar, OpenAlex; kept only papers that name the failure",
                     "queries": {g["type"]: g["queries"] for g in groups}},
        )
        papers_by_type = {g["type"]: g["papers"] for g in groups}

        picked = self.pick_for_fixes(findings)
        started = time.time()
        fixes_raw, source, reason, _ = step("Fix Advisor", lambda: self.advise(picked, papers_by_type))
        state.add_trace(
            "Fix Advisor",
            (f"AI suggested fixes for {len(fixes_raw)} of {len(picked)} failure point(s)" if source == "llm"
             else "No failure points to fix" if source == "deterministic"
             else f"AI not available ({reason[:100]}); showing the standard fix for each kind instead"),
            status="warning" if source == "fallback" else "completed",
            duration_ms=int((time.time() - started) * 1000),
            details={"tool": "AI model, 1 call" if source != "deterministic" else "none", "source": source,
                     **({"fallback_reason": reason} if reason else {})},
        )

        started = time.time()
        fixes = [self.critic(f, fixes_raw.get(f.id), papers_by_type.get(f.type, [])) for f in picked]
        ai_fixes = [x for x in fixes if x["generated_by"] == "llm"]
        verification = {
            "fixes_checked": len(ai_fixes),
            "fixes_compiling": sum(1 for x in ai_fixes if x["checks"]["compiles"]),
            "failures_removed": sum(1 for x in ai_fixes if x["checks"]["failure_gone"]),
            "citations_removed": sum(x["checks"].get("citations_removed", 0) for x in ai_fixes),
            "notes_with_papers": sum(1 for x in fixes if x["research_note"] and x["cited_refs"]),
        }
        supports = [x["checks"]["abstract_support"] for x in ai_fixes if x["checks"]["abstract_support"] is not None]
        verification["avg_abstract_support"] = round(sum(supports) / len(supports), 2) if supports else None
        state.add_trace(
            "Fix Critic",
            (f"{verification['fixes_compiling']}/{len(ai_fixes)} fixes parse, {verification['failures_removed']}/{len(ai_fixes)} remove the "
             f"failure point, {verification['citations_removed']} invalid citation(s) removed") if ai_fixes
            else "Nothing to verify (no AI fixes)",
            status="completed" if not ai_fixes or verification["failures_removed"] == len(ai_fixes) else "warning",
            duration_ms=int((time.time() - started) * 1000),
            details={"tool": "Python parser + the same failure checks + citation check (no AI)", **verification},
        )

        finding_dicts = [f.to_dict() for f in findings[:MAX_FINDINGS]]
        score = checks.readiness([f.to_dict() for f in findings])
        counts = {s: sum(1 for f in findings if checks.FAILURE_TYPES[f.type]["severity"] == s) for s in ("high", "medium", "low")}
        types = []
        for key in type_order:
            info = checks.FAILURE_TYPES[key]
            types.append({"type": key, "title": info["title"], "cwe": info["cwe"], "cwe_name": info["cwe_name"],
                          "cwe_url": f"https://cwe.mitre.org/data/definitions/{info['cwe'].split('-')[1]}.html",
                          "severity": info["severity"], "why": info["why"], "fix": info["fix"], "count": by_type[key]})
        return {
            "type": "failure_analysis",
            "summary": (f"{len(findings)} failure points of {len(by_type)} kinds in {scanned} files. "
                        f"Launch readiness {score['score']}/100: {score['band'].lower()}.") if findings
                       else f"No failure points found by the {len(checks.FAILURE_TYPES)} checks in {scanned} files.",
            "readiness": score,
            "counts": {**counts, "total": len(findings), "files_scanned": scanned, "test_files_skipped": scan_notes["test_files_skipped"]},
            "failure_types": types,
            "findings": finding_dicts,
            "research": groups,
            "research_backend": backend,
            "fixes": fixes,
            "verification": verification,
            "notes": research_notes,
            "checks_catalog": [{"type": k, "title": v["title"], "cwe": v["cwe"], "severity": v["severity"]}
                               for k, v in checks.FAILURE_TYPES.items()],
            "generation_source": source if source != "deterministic" else "deterministic",
            "fallback_reason": reason,
            "provenance": {"findings": "deterministic", "readiness": "deterministic", "spread": "deterministic",
                           "research": "live search" if papers_found else "none", "fixes": source},
            "local_repo_path": repo_path,
            "indexed_summary": index.get_summary(),
        }


failure_simulator = FailureSimulatorAgent()
