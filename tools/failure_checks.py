"""
Failure-point checks for the Failure Simulator (plain code, no AI).

Each check is a fixed rule over the Python syntax tree (AST). Every failure type
is mapped to its CWE entry (MITRE's public catalogue of software weaknesses) and
to a research topic, which the Failure Simulator uses to find papers that study
that kind of failure. The checks only read code; nothing is run.
"""

import ast
import re
import textwrap
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

SEVERITY_POINTS = {"high": 8, "medium": 4, "low": 1}
# A repeated failure type costs points at most this many times (the score
# should reflect how many kinds of risk there are, not how long the repo is).
MAX_COUNTED_PER_TYPE = 2

# key -> what it is, why it matters, how it is usually fixed, and what to search for.
FAILURE_TYPES: Dict[str, Dict[str, Any]] = {
    "no_timeout": {
        "title": "Network call without a timeout",
        "cwe": "CWE-1088", "cwe_name": "Synchronous Access of Remote Resource without Timeout",
        "severity": "high",
        "why": "If the other server is slow or down, this call waits forever and the request hangs with it.",
        "fix": "Pass a timeout (for example timeout=5) and handle the timeout error.",
        "scenario": "The remote server stops answering. {symbol} waits with no time limit, so {entry} hangs too. "
                    "After a few such requests every worker is stuck and the whole app stops answering.",
        "queries": ["timeout bugs cloud systems", "timeout issues distributed systems"], "must": ["timeout"],
        "topic": "timeout bugs: missing or wrong timeouts cause hangs and outages in cloud and distributed systems",
    },
    "ignored_error": {
        "title": "Error is silently ignored",
        "cwe": "CWE-390", "cwe_name": "Detection of Error Condition Without Action",
        "severity": "high",
        "why": "The error is caught and thrown away, so nobody learns that something failed.",
        "fix": "Log the error, then retry, return a clear error, or let it fail loudly.",
        "scenario": "{symbol} hits an error. It is caught and dropped, so {entry} carries on with missing data "
                    "and nothing shows up in the logs.",
        "queries": ["simple testing can prevent most critical failures", "exception handling bugs empirical study"], "must": ["error", "exception"],
        "topic": "incorrect handling of errors and ignored exceptions lead to catastrophic failures in distributed systems",
    },
    "bare_except": {
        "title": "Catches every possible error",
        "cwe": "CWE-396", "cwe_name": "Declaration of Catch for Generic Exception",
        "severity": "medium",
        "why": "A bare except also catches typos and real bugs, so they are hidden instead of fixed.",
        "fix": "Catch only the errors you expect (for example requests.RequestException) and log them.",
        "scenario": "A typo or a real bug inside the try block in {symbol} is treated like a normal failure, "
                    "so {entry} gives a wrong answer instead of an error you can see and fix.",
        "queries": ["exception handling anti-patterns", "exception handling practices empirical study"], "must": ["exception"],
        "topic": "exception handling anti-patterns such as generic catch blocks in software projects",
    },
    "sql_injection": {
        "title": "SQL built from user text",
        "cwe": "CWE-89", "cwe_name": "SQL Injection",
        "severity": "high",
        "why": "Text from the user becomes part of the SQL command, so a crafted value can read or delete data.",
        "fix": "Use placeholders (? or %s) and pass the values separately.",
        "scenario": "A user sends a value like ' OR '1'='1. The query in {symbol} then matches every row, "
                    "so {entry} returns other users' data.",
        "queries": ["SQL injection detection", "SQL injection prevention web applications"], "must": ["sql"],
        "topic": "SQL injection attacks on web applications and how to detect and prevent them",
    },
    "hardcoded_secret": {
        "title": "Secret written into the code",
        "cwe": "CWE-798", "cwe_name": "Use of Hard-coded Credentials",
        "severity": "high",
        "why": "Anyone who can read the code, or the GitHub repo, can use this key.",
        "fix": "Read it from an environment variable or a secrets manager, and replace the leaked key.",
        "scenario": "The repo is shared or pushed to GitHub. Anyone who reads {file} can use this key "
                    "until it is replaced.",
        "queries": ["secrets leaked source code repositories", "hard-coded credentials detection"], "must": ["secret", "credential", "password", "key"],
        "topic": "secrets such as API keys and passwords leaked in source code repositories",
    },
    "unsafe_deserialization": {
        "title": "Unsafe loading of stored data",
        "cwe": "CWE-502", "cwe_name": "Deserialization of Untrusted Data",
        "severity": "high",
        "why": "Loading pickle (or unsafe YAML) data that someone else can change lets them run code on the server.",
        "fix": "Use json or yaml.safe_load; never unpickle data you did not create yourself.",
        "scenario": "Someone changes the stored data that {symbol} loads. Unpickling it runs their code on the server.",
        "queries": ["deserialization vulnerabilities", "pickle deserialization python security"], "must": ["deserializ", "pickle", "serializ"],
        "topic": "insecure deserialization vulnerabilities that allow remote code execution",
    },
    "code_injection": {
        "title": "Runs text as code",
        "cwe": "CWE-95", "cwe_name": "Eval Injection",
        "severity": "high",
        "why": "eval/exec run whatever text they get; if a user controls part of it, they control the server.",
        "fix": "Parse the input instead (for example json.loads or ast.literal_eval).",
        "scenario": "A user sends text that reaches eval/exec in {symbol}. It runs as Python on the server.",
        "queries": ["code injection eval", "eval function security javascript"], "must": [r"\beval\b", "code injection"],
        "topic": "code injection through eval in dynamic languages such as Python and JavaScript",
    },
    "shell_injection": {
        "title": "Runs a shell command built from text",
        "cwe": "CWE-78", "cwe_name": "OS Command Injection",
        "severity": "high",
        "why": "With shell=True or os.system, a crafted value can add its own commands.",
        "fix": "Call subprocess.run with a list of arguments and shell=False.",
        "scenario": "A value with ; or && reaches the command in {symbol}. The shell runs the extra command too.",
        "queries": ["command injection vulnerabilities", "OS command injection detection"], "must": ["command injection", "shell", "command"],
        "topic": "operating system command injection vulnerabilities and their detection",
    },
    "resource_leak": {
        "title": "File opened and never closed",
        "cwe": "CWE-772", "cwe_name": "Missing Release of Resource after Effective Lifetime",
        "severity": "medium",
        "why": "Each call leaves a file handle open; under load the process runs out of them.",
        "fix": "Open the file with a with-block so it is always closed.",
        "scenario": "Under load, {symbol} opens a file on every request and never closes it. "
                    "The process runs out of file handles and new requests start failing.",
        "queries": ["resource leak detection", "resource leak bugs empirical study"], "must": ["leak"],
        "topic": "resource leaks such as unclosed files and connections in software and how to detect them",
    },
    "debug_mode": {
        "title": "Debug mode switched on",
        "cwe": "CWE-489", "cwe_name": "Active Debug Code",
        "severity": "medium",
        "why": "Debug pages show code and settings to anyone, and some debuggers can run commands.",
        "fix": "Read the debug flag from the environment and keep it off in production.",
        "scenario": "The app goes live with debug on. Any error shows a page with code and settings to the visitor.",
        "queries": ["security misconfiguration detection", "misconfiguration web application security"], "must": ["misconfig", "configuration", "debug"],
        "topic": "security misconfiguration of web applications such as debug mode left on in production",
    },
    "assert_check": {
        "title": "Check done with assert",
        "cwe": "CWE-617", "cwe_name": "Reachable Assertion",
        "severity": "low",
        "why": "Python drops assert statements when started with -O, so the check can silently disappear.",
        "fix": "Use an if-statement that raises a clear error.",
        "scenario": "The app is started with python -O. The assert in {symbol} is removed, so its check never runs.",
        "queries": ["assertions production code", "assert statements software reliability"], "must": ["assert"],
        "topic": "use of assertions in production code and their effect on software failures",
    },
}

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "request"}
_HTTP_MODULES = {"requests", "httpx"}
_SQL_METHODS = {"execute", "executemany", "executescript", "raw"}
_SECRET_NAME = re.compile(r"(pass(word|wd)?|secret|api_?key|token|private_?key|access_?key|client_?secret)$", re.I)
_PLACEHOLDER = re.compile(r"change|your|example|xxx|dummy|placeholder|<|\{|^\*+$", re.I)


@dataclass
class Finding:
    id: str
    type: str
    file_path: str
    line: int
    symbol: str = ""
    code_line: str = ""
    context_start: int = 0
    context_code: str = ""
    callers: List[Dict[str, Any]] = field(default_factory=list)
    entrypoints: List[str] = field(default_factory=list)
    scenario: str = ""

    def to_dict(self) -> Dict[str, Any]:
        info = FAILURE_TYPES[self.type]
        return {**asdict(self), "title": info["title"], "severity": info["severity"], "cwe": info["cwe"]}


def mentions_topic(text: str, failure_type: str) -> bool:
    """A paper counts as relevant only if its title or abstract names the failure (word patterns, no AI)."""
    text = (text or "").lower()
    return any(re.search(pattern, text) for pattern in FAILURE_TYPES[failure_type]["must"])


def is_test_file(path: str) -> bool:
    parts = path.replace("\\", "/").lower().split("/")
    name = parts[-1]
    return name.startswith("test_") or name.endswith("_test.py") or "tests" in parts or "test" in parts or name == "conftest.py"


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _builds_string(node: ast.AST) -> bool:
    """True for f"..{x}..", "..." % x, "..." + x and "...".format(x)."""
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
        sides = (node.left, node.right)
        has_text = any(isinstance(s, ast.Constant) and isinstance(s.value, str) or isinstance(s, ast.JoinedStr) for s in sides)
        has_value = any(not isinstance(s, ast.Constant) for s in sides)
        return has_text and has_value or _builds_string(node.left)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str)
    return False


def _only_ignores(body: List[ast.stmt]) -> bool:
    """A handler body that does nothing with the error: pass, continue, ... or a bare return."""
    for stmt in body:
        if isinstance(stmt, (ast.Pass, ast.Continue)):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # a docstring or ...
        if isinstance(stmt, ast.Return) and (stmt.value is None or isinstance(stmt.value, ast.Constant) and stmt.value.value is None):
            continue
        return False
    return True


def scan_source(source: str, path: str) -> List[Tuple[str, int, str]]:
    """Returns (type, line, extra) for every failure point in one file."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    hits: List[Tuple[str, int, str]] = []
    with_items = {id(item.context_expr) for node in ast.walk(tree) if isinstance(node, (ast.With, ast.AsyncWith)) for item in node.items}

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            short = name.split(".")[-1]
            kwargs = {k.arg for k in node.keywords}
            has_star = None in kwargs
            root = name.split(".")[0]
            if ((root in _HTTP_MODULES and short in _HTTP_METHODS and name.count(".") == 1) or short == "urlopen") \
                    and "timeout" not in kwargs and not has_star and not (short == "urlopen" and len(node.args) >= 3):
                hits.append(("no_timeout", node.lineno, name))
            elif isinstance(node.func, ast.Attribute) and short in _SQL_METHODS and node.args and _builds_string(node.args[0]):
                hits.append(("sql_injection", node.lineno, name))
            elif name in ("pickle.loads", "pickle.load", "marshal.loads", "dill.loads", "cPickle.loads") or \
                    (name in ("yaml.load", "yaml.load_all") and "Loader" not in kwargs and len(node.args) < 2):
                hits.append(("unsafe_deserialization", node.lineno, name))
            elif name in ("eval", "exec"):
                hits.append(("code_injection", node.lineno, name))
            elif name in ("os.system", "os.popen") or (root == "subprocess" and any(
                    k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords)):
                hits.append(("shell_injection", node.lineno, name))
            elif short == "run" and any(k.arg == "debug" and isinstance(k.value, ast.Constant) and k.value.value is True
                                        for k in node.keywords):
                hits.append(("debug_mode", node.lineno, name))
        elif isinstance(node, ast.ExceptHandler):
            broad = node.type is None or _dotted(node.type) in ("BaseException", "Exception")
            if _only_ignores(node.body):
                hits.append(("ignored_error", node.lineno, "except"))
            elif node.type is None or _dotted(node.type) == "BaseException":
                hits.append(("bare_except", node.lineno, "except"))
            del broad
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            for target in targets:
                tname = _dotted(target).split(".")[-1]
                if not tname:
                    continue
                if isinstance(value, ast.Constant) and isinstance(value.value, str) and _SECRET_NAME.search(tname) \
                        and len(value.value) >= 8 and " " not in value.value and not _PLACEHOLDER.search(value.value):
                    hits.append(("hardcoded_secret", node.lineno, value.value))
                elif tname == "DEBUG" and isinstance(value, ast.Constant) and value.value is True:
                    hits.append(("debug_mode", node.lineno, tname))
                elif isinstance(value, ast.Call) and _dotted(value.func) == "open" and id(value) not in with_items:
                    hits.append(("resource_leak", node.lineno, "open"))
        elif isinstance(node, ast.Assert):
            hits.append(("assert_check", node.lineno, "assert"))
    seen, out = set(), []
    for hit in sorted(hits, key=lambda h: (h[1], h[0])):
        if (hit[0], hit[1]) not in seen:
            seen.add((hit[0], hit[1]))
            out.append(hit)
    return out


def mask_secret(text: str, secret: str) -> str:
    return text.replace(secret, secret[:4] + "*" * max(4, len(secret) - 4)) if secret else text


def readiness(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Launch readiness out of 100, computed from the findings (no AI)."""
    per_type: Dict[str, int] = {}
    for f in findings:
        per_type[f["type"]] = per_type.get(f["type"], 0) + 1
    penalties = []
    for key, count in sorted(per_type.items(), key=lambda kv: -SEVERITY_POINTS[FAILURE_TYPES[kv[0]]["severity"]]):
        severity = FAILURE_TYPES[key]["severity"]
        counted = min(count, MAX_COUNTED_PER_TYPE)
        penalties.append({"type": key, "title": FAILURE_TYPES[key]["title"], "severity": severity,
                          "count": count, "points": SEVERITY_POINTS[severity] * counted})
    score = max(0, 100 - sum(p["points"] for p in penalties))
    band = "Ready for launch" if score >= 85 else "Fix before launch" if score >= 60 else "Not ready for launch"
    return {
        "score": score, "band": band, "penalties": penalties,
        "formula": f"100 minus {SEVERITY_POINTS['high']} points per high, {SEVERITY_POINTS['medium']} per medium and "
                   f"{SEVERITY_POINTS['low']} per low failure point (each kind counted at most {MAX_COUNTED_PER_TYPE} times).",
    }


def fixed_code_check(code: str, failure_type: str) -> Dict[str, bool]:
    """Checks a suggested fix: it parses, and the same failure check no longer fires on it."""
    text = textwrap.dedent(code or "").strip("\n")
    if not text:
        return {"compiles": False, "failure_gone": False}
    try:
        ast.parse(text)
    except SyntaxError:
        return {"compiles": False, "failure_gone": False}
    still = [h for h in scan_source(text, "fix.py") if h[0] == failure_type]
    return {"compiles": True, "failure_gone": not still}
