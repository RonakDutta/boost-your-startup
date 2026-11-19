"""
App designs for the Prototype Builder.

The AI fills in a short JSON design (what kind of app, its fields, sample
records and the rule it applies) and this module turns that design into the
three idea-specific files: features.py, static/index.html and test_features.py.
One small AI call instead of a long code-writing call, and the generated code
is the same tested code every time, so the tests pass.

Kinds of app (the AI picks one, or "custom" for the old full-code path):
- monitor : readings per group (flat, meter, device); unusual values are flagged.
- review  : people submit text or code; it is scored against simple checks.
- tracker : items move through statuses (complaints, orders, tasks).
- booking : people book a slot of a resource on a day; double bookings are refused.

Without the AI, `default_design()` picks a kind from keywords in the idea and
fills a plain design (the build is then labelled as a fallback).
"""

import html
import json
import keyword
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

KINDS = ("monitor", "review", "tracker", "booking")
FIELD_TYPES = ("text", "long_text", "number", "choice", "date")
# Keys the generated code adds to every record, so no field may use them.
RESERVED = {"id", "status", "note", "score", "results", "group", "day_param"}

DESIGN_PROMPT = """You design a small working web app that shows a startup idea's main job.
You do not write code. You fill in a JSON design and a code generator builds the app, its page and its tests.

Pick the kind that fits the idea best:
- "monitor": readings are recorded per group (flat, meter, machine, patient) and unusual values are flagged.
  rule: {"group_field": "<text field>", "value_field": "<number field>", "unit": "kWh", "mode": "spike" or "threshold", "warn": 1.5, "alert": 2}
  (spike: warn/alert are multiples of that group's usual value; threshold: absolute values of the reading)
- "review": people submit text or code and it is scored against 3 to 6 simple checks.
  rule: {"text_field": "<long_text field>", "pass_mark": 70, "checks": [{"label": "No debug prints", "kind": "not_contains", "value": "print("}]}
  check kinds: contains, not_contains, max_line_length, min_words, max_words, max_lines
- "tracker": items move through statuses (complaints, orders, tasks, requests).
  rule: {"statuses": ["open", "in progress", "resolved"]}  (3 or 4, the last one means done)
- "booking": people book a slot of a resource on a day; double bookings are refused.
  rule: {"resource_field": "<choice field>", "day_field": "<date field>", "slot_field": "<choice field>"}
- "custom": only if none of these can show the idea at all.

Return only this JSON:
{"kind": "...", "app_name": "2 to 4 words", "tagline": "one short line", "entity": "singular noun, e.g. Reading",
 "entity_plural": "e.g. Readings", "action": "button text, e.g. Add reading",
 "fields": [{"name": "snake_case", "label": "Label", "type": "text|long_text|number|choice|date", "choices": ["only for choice"], "min": 0, "max": 1000}],
 "seed": [4 to 6 records, each with a value for every field],
 "rule": {...},
 "look": {"theme": "blue|teal|amber|indigo|green|rose|slate", "layout": "dashboard|sidebar|banner", "header": "light|accent|dark"}}
- 3 to 5 fields; every *_field in the rule must be one of them.
- Seed records: realistic names, places and numbers for this idea's users in India, dates in the last two weeks. No Alice/Bob, foo or test.
- For review, seed texts are short (under 6 lines) and some pass and some fail the checks.
- look: colours that suit the idea (water: teal or blue, energy: amber, health: rose, farming: green, code: indigo)."""


# ---------------------------------------------------------------- helpers

def _slug(text: str, fallback: str) -> str:
    words = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return "-".join(words[:3]) or fallback


def _ident(text: str, fallback: str) -> str:
    name = re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")[:30] or fallback
    if name[0].isdigit():
        name = "f_" + name
    if keyword.iskeyword(name) or name in RESERVED or name.startswith("model_") or name in {"schema", "json", "dict", "copy", "fields", "construct"}:
        name += "_value"
    return name


def _label(text: Any, fallback: str, limit: int = 40) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:limit] or fallback


def _short(text: Any, limit: int = 90) -> str:
    """Cuts at a word boundary, not mid-word."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "..."


def _num(value: Any, default: float) -> float:
    try:
        out = float(value)
        return out if out == out and abs(out) < 1e9 else default  # NaN / huge
    except (TypeError, ValueError):
        return default


def _clean(value: float) -> Any:
    return int(value) if float(value).is_integer() else round(value, 2)


def _today() -> date:
    return date.today()


# ---------------------------------------------------------------- normalise

def _norm_fields(raw: Any) -> List[Dict[str, Any]]:
    fields, seen = [], set()
    for i, f in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(f, dict):
            continue
        name = _ident(f.get("name") or f.get("label"), f"field_{i + 1}")
        if name in seen:
            continue
        kind = str(f.get("type") or "text").lower()
        kind = kind if kind in FIELD_TYPES else ("number" if kind in ("int", "float", "integer") else "text")
        field = {"name": name, "label": _label(f.get("label"), name.replace("_", " ").capitalize()), "type": kind}
        if kind == "choice":
            choices = []
            for c in f.get("choices") or []:
                c = _label(c, "", 40)
                if c and c not in choices:
                    choices.append(c)
            if len(choices) < 2:
                field["type"] = "text"
            else:
                field["choices"] = choices[:8]
        if field["type"] == "number":
            low, high = _num(f.get("min"), 0), _num(f.get("max"), 100000)
            field["min"], field["max"] = _clean(low), _clean(high if high > low else low + 100000)
        seen.add(name)
        fields.append(field)
    return fields[:5]


def _find(fields, name, types) -> Optional[Dict[str, Any]]:
    want = _ident(name, "") if name else ""
    for f in fields:
        if f["name"] == want and f["type"] in types:
            return f
    for f in fields:
        if f["type"] in types:
            return f
    return None


def _ensure(fields, name, types, new) -> Dict[str, Any]:
    found = _find(fields, name, types)
    if found:
        return found
    taken = {f["name"] for f in fields}
    while new["name"] in taken:
        new["name"] += "_2"
    if len(fields) >= 5:
        fields.pop()
    fields.append(new)
    return new


def _example(field: Dict[str, Any], i: int) -> Any:
    kind = field["type"]
    if kind == "number":
        low, high = field["min"], field["max"]
        return _clean(min(high, max(low, low + (high - low) * 0.1 * (i % 5 + 1) / 5)))
    if kind == "choice":
        return field["choices"][i % len(field["choices"])]
    if kind == "date":
        return (_today() - timedelta(days=i)).isoformat()
    if kind == "long_text":
        return f"{field['label']} entry {i + 1}"
    return f"{field['label']} {i + 1}"


def _coerce(field: Dict[str, Any], value: Any) -> Any:
    """Returns a valid value for the field, or raises ValueError."""
    kind = field["type"]
    if kind == "number":
        out = _num(value, float("nan"))
        if out != out or not field["min"] <= out <= field["max"]:
            raise ValueError
        return _clean(out)
    if kind == "choice":
        value = str(value)
        if value not in field["choices"]:
            raise ValueError
        return value
    if kind == "date":
        return date.fromisoformat(str(value)[:10]).isoformat()
    text = str(value if value is not None else "").strip()
    limit = 4000 if kind == "long_text" else 80
    if not text or len(text) > limit:
        raise ValueError
    return text


THEMES = ("blue", "teal", "amber", "indigo", "green", "rose", "slate")
LAYOUTS = ("dashboard", "sidebar", "banner")
HEADERS = ("light", "accent", "dark")
_THEME_WORDS = (("teal", r"water|leak|pipe|ocean|clean"), ("amber", r"energy|power|electric|solar|kwh|food|canteen"),
                ("indigo", r"code|program|lab|student|review|exam"), ("green", r"farm|crop|tractor|plant|waste|green|agri"),
                ("rose", r"health|patient|hospital|clinic|blood|doctor"), ("slate", r"complaint|ticket|hostel|admin"))


# Default layout and header for each colour, so ideas with different colours also get different pages.
_THEME_LOOK = {"teal": ("dashboard", "dark"), "amber": ("banner", "light"), "indigo": ("sidebar", "accent"),
               "green": ("sidebar", "light"), "rose": ("banner", "dark"), "slate": ("dashboard", "accent")}


def _stable(text: str) -> int:
    """Same idea, same number (Python's hash() changes between runs)."""
    return sum((i + 1) * ord(c) for i, c in enumerate(text or ""))


def pick_look(design: Dict[str, Any], spec: Dict[str, Any], kind: str) -> Dict[str, str]:
    """The AI's choice when valid; otherwise colours from words in the idea and a layout from the idea text."""
    look = design.get("look") if isinstance(design.get("look"), dict) else {}
    text = spec_text(spec).lower()
    seed = _stable(spec.get("title", "") + kind)
    theme = str(look.get("theme", "")).lower()
    if theme not in THEMES:
        theme = next((t for t, words in _THEME_WORDS if re.search(words, text)), THEMES[seed % len(THEMES)])
    default_layout, default_header = _THEME_LOOK.get(theme, (LAYOUTS[(seed // 7) % 3], HEADERS[(seed // 3) % 3]))
    layout = str(look.get("layout", "")).lower()
    if layout not in LAYOUTS:
        layout = default_layout
    header = str(look.get("header", "")).lower()
    if header not in HEADERS:
        header = default_header
    if layout == "banner":
        header = "light" if header == "accent" else header  # the banner already carries the colour
    return {"theme": theme, "layout": layout, "header": header}


def normalize(design: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    """Cleans an AI design into one the generator can always build. Raises ValueError for 'custom' or junk."""
    if not isinstance(design, dict):
        raise ValueError("The design was not a JSON object.")
    kind = str(design.get("kind") or "").lower().strip()
    if kind not in KINDS:
        raise ValueError(f"No built-in app shape for kind '{kind or 'none'}'.")
    rule_in = design.get("rule") if isinstance(design.get("rule"), dict) else {}
    fields = _norm_fields(design.get("fields"))
    entity = _label(design.get("entity"), "Record", 24)
    plural = _label(design.get("entity_plural"), entity + "s", 24)
    rule: Dict[str, Any] = {}

    if kind == "monitor":
        group = _ensure(fields, rule_in.get("group_field"), ("text", "choice"), {"name": "location", "label": "Location", "type": "text"})
        if group["type"] == "choice":  # tests add a new group, so it stays free text
            group["type"] = "text"
            group.pop("choices", None)
        value = _ensure(fields, rule_in.get("value_field"), ("number",), {"name": "reading", "label": "Reading", "type": "number", "min": 0, "max": 100000})
        mode = "threshold" if str(rule_in.get("mode")).lower() == "threshold" else "spike"
        warn, alert = _num(rule_in.get("warn"), 1.5 if mode == "spike" else value["max"] * 0.6), _num(rule_in.get("alert"), 0)
        if mode == "spike":
            warn = warn if 1.05 <= warn <= 10 else 1.5
            alert = alert if warn < alert <= 20 else round(warn + 0.5, 2)
        else:
            warn = warn if value["min"] < warn < value["max"] else _clean(value["min"] + (value["max"] - value["min"]) * 0.6)
            alert = alert if warn < alert <= value["max"] else _clean(min(value["max"], warn * 1.5) if warn > 0 else value["max"])
            if alert <= warn:
                alert = value["max"]
                warn = _clean((value["min"] + alert) / 2)
        rule = {"group_field": group["name"], "value_field": value["name"], "unit": _label(rule_in.get("unit"), "", 12),
                "mode": mode, "warn": _clean(warn), "alert": _clean(alert)}
    elif kind == "review":
        text = _ensure(fields, rule_in.get("text_field"), ("long_text",), {"name": "content", "label": "Content", "type": "long_text"})
        checks = []
        for c in rule_in.get("checks") or []:
            if not isinstance(c, dict):
                continue
            ckind = str(c.get("kind") or "").lower()
            if ckind in ("contains", "not_contains"):
                value_text = str(c.get("value") or "")[:40]
                if not value_text.strip():
                    continue
                cval: Any = value_text
            elif ckind in ("max_line_length", "min_words", "max_words", "max_lines"):
                cval = int(_num(c.get("value"), 0))
                if cval < 1:
                    continue
            else:
                continue
            check = {"label": _label(c.get("label"), ckind.replace("_", " "), 50), "kind": ckind, "value": cval}
            opposite = {"contains": "not_contains", "not_contains": "contains"}.get(ckind)
            if any(k["kind"] == opposite and str(k["value"]).lower() == str(cval).lower() for k in checks):
                continue  # a check and its opposite can never both pass
            checks.append(check)
        if not checks:
            checks = [{"label": "At least 20 words", "kind": "min_words", "value": 20},
                      {"label": "Lines under 100 characters", "kind": "max_line_length", "value": 100}]
        rule = {"text_field": text["name"], "pass_mark": int(min(100, max(1, _num(rule_in.get("pass_mark"), 70)))), "checks": checks[:6]}
    elif kind == "tracker":
        statuses = []
        for s in rule_in.get("statuses") or []:
            s = _label(s, "", 24).lower()
            if s and s not in statuses:
                statuses.append(s)
        rule = {"statuses": statuses[:4] if len(statuses) >= 2 else ["open", "in progress", "done"]}
    else:  # booking
        resource = _ensure(fields, rule_in.get("resource_field"), ("choice",), {"name": "resource", "label": "Resource", "type": "choice", "choices": ["Room 1", "Room 2"]})
        slot = _find([f for f in fields if f is not resource], rule_in.get("slot_field"), ("choice",))
        if slot is None:
            slot = _ensure(fields, "slot", ("__none__",), {"name": "slot", "label": "Time slot", "type": "choice",
                                                          "choices": ["09:00", "11:00", "14:00", "16:00", "18:00"]})
        day = _ensure(fields, rule_in.get("day_field"), ("date",), {"name": "day", "label": "Day", "type": "date"})
        rule = {"resource_field": resource["name"], "slot_field": slot["name"], "day_field": day["name"]}

    if not any(f["type"] in ("text", "long_text") for f in fields) and len(fields) < 5:
        fields.insert(0, {"name": "name", "label": "Name", "type": "text"})

    seed, taken = [], set()
    for row in design.get("seed") or []:
        if not isinstance(row, dict):
            continue
        try:
            clean = {f["name"]: _coerce(f, row.get(f["name"], row.get(f["label"]))) for f in fields}
        except (ValueError, TypeError):
            continue
        if kind == "booking":
            key = (clean[rule["resource_field"]], clean[rule["day_field"]], clean[rule["slot_field"]])
            if key in taken:
                continue
            taken.add(key)
        if kind == "tracker":
            status = _label(row.get("status"), "", 24).lower()
            clean["status"] = status if status in rule["statuses"] else rule["statuses"][0]
        seed.append(clean)
    i = 0
    while len(seed) < 3:
        row = {f["name"]: _example(f, i + len(seed)) for f in fields}
        if kind == "booking":
            row[rule["slot_field"]] = next(f for f in fields if f["name"] == rule["slot_field"])["choices"][len(seed) % 2]
        i += 1
        seed.append(row)

    return {
        "kind": kind,
        "app_name": _label(design.get("app_name"), spec.get("title") or "Prototype", 40),
        "tagline": _short(design.get("tagline") or spec.get("value") or spec.get("problem") or ""),
        "entity": entity,
        "entity_plural": plural,
        "action": _label(design.get("action"), f"Add {entity.lower()}", 30),
        "fields": fields,
        "seed": seed[:12],
        "rule": rule,
        "look": pick_look(design, spec, kind),
    }


# ---------------------------------------------------------------- default design (no AI)

_KEYWORDS = {
    "monitor": ("meter", "sensor", "monitor", "reading", "iot", "leak", "spike", "energy", "power", "water",
                "consumption", "usage", "temperature", "air quality", "pollution", "esp32", "lorawan", "telemetry"),
    "review": ("review", "submission", "grade", "grading", "lint", "plagiarism", "essay", "assignment",
               "resume", "code quality", "feedback on", "evaluate code"),
    "booking": ("book", "booking", "slot", "appointment", "reserve", "reservation", "schedule", "rent", "hire"),
    "tracker": ("complaint", "ticket", "track", "order", "request", "issue", "task", "status", "delivery",
                "inventory", "lost and found", "report"),
}


def pick_kind(text: str) -> Optional[str]:
    """Keyword vote over the idea text. None when nothing matches."""
    text = (text or "").lower()
    scores = {k: sum(text.count(w) for w in words) for k, words in _KEYWORDS.items()}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] else None


def spec_text(spec: Dict[str, Any]) -> str:
    parts = [spec.get("title", ""), spec.get("problem", ""), spec.get("value", "")]
    parts += [f"{r.get('title', '')} {r.get('description', '')}" for r in spec.get("requirements") or []]
    return " ".join(str(p) for p in parts)


def default_design(spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A plain design picked from keywords in the idea (used when the AI cannot answer)."""
    text = spec_text(spec).lower()
    kind = pick_kind(text)
    if not kind:
        return None
    flats = ["A-101", "A-102", "B-204", "C-301"]
    if kind == "monitor":
        if re.search(r"water|leak|pipe", text):
            unit, value, label = "L", "litres", "Water used (L)"
            base = [410, 365, 520, 450]
        elif re.search(r"energy|power|electric|kwh|current", text):
            unit, value, label = "kWh", "energy_kwh", "Energy used (kWh)"
            base = [9.5, 7.8, 12.4, 10.6]
        else:
            unit, value, label = "", "reading", "Reading"
            base = [40, 35, 52, 45]
        seed = []
        for d in range(2, 0, -1):
            for flat, b in zip(flats, base):
                seed.append({"location": flat, value: round(b * (1 + 0.04 * ((d + len(flat)) % 3 - 1)), 1),
                             "day": (_today() - timedelta(days=d)).isoformat()})
        seed.append({"location": "B-204", value: round(base[2] * 2.3, 1), "day": _today().isoformat()})
        design = {"kind": kind, "entity": "Reading", "entity_plural": "Readings", "action": "Add reading",
                  "fields": [{"name": "location", "label": "Flat", "type": "text"},
                             {"name": value, "label": label, "type": "number", "min": 0, "max": 100000},
                             {"name": "day", "label": "Day", "type": "date"}],
                  "seed": seed, "rule": {"group_field": "location", "value_field": value, "unit": unit,
                                              "mode": "spike", "warn": 1.5, "alert": 2}}
    elif kind == "review":
        if re.search(r"code|program|lab|lint|ast", text):
            checks = [{"label": "Has a docstring", "kind": "contains", "value": '"""'},
                      {"label": "No debug print calls", "kind": "not_contains", "value": "print("},
                      {"label": "No bare except", "kind": "not_contains", "value": "except:"},
                      {"label": "Lines under 79 characters", "kind": "max_line_length", "value": 79},
                      {"label": "Under 40 lines", "kind": "max_lines", "value": 40}]
            seed = [{"student": "Riya Sharma", "title": "Lab 3: binary search",
                     "content": 'def search(items, target):\n    """Binary search on a sorted list."""\n    low, high = 0, len(items) - 1\n    while low <= high:\n        mid = (low + high) // 2\n        if items[mid] == target:\n            return mid\n        if items[mid] < target:\n            low = mid + 1\n        else:\n            high = mid - 1\n    return -1'},
                    {"student": "Aman Verma", "title": "Lab 3: bubble sort",
                     "content": "def sort(a):\n    for i in range(len(a)):\n        for j in range(len(a) - 1):\n            if a[j] > a[j + 1]:\n                a[j], a[j + 1] = a[j + 1], a[j]\n    print(a)\n    return a"},
                    {"student": "Kabir Singh", "title": "Lab 4: file reader",
                     "content": 'def read(path):\n    """Read a file."""\n    try:\n        return open(path).read()\n    except:\n        return ""'}]
            fields = [{"name": "student", "label": "Student", "type": "text"}, {"name": "title", "label": "Assignment", "type": "text"},
                      {"name": "content", "label": "Code", "type": "long_text"}]
        else:
            checks = [{"label": "At least 40 words", "kind": "min_words", "value": 40},
                      {"label": "At most 300 words", "kind": "max_words", "value": 300},
                      {"label": "No placeholder text", "kind": "not_contains", "value": "lorem"}]
            seed = []
            fields = [{"name": "author", "label": "Author", "type": "text"}, {"name": "title", "label": "Title", "type": "text"},
                      {"name": "content", "label": "Text", "type": "long_text"}]
        design = {"kind": kind, "entity": "Submission", "entity_plural": "Submissions", "action": "Check submission",
                  "fields": fields, "seed": seed, "rule": {"text_field": "content", "pass_mark": 70, "checks": checks}}
    elif kind == "booking":
        design = {"kind": kind, "entity": "Booking", "entity_plural": "Bookings", "action": "Book",
                  "fields": [{"name": "name", "label": "Name", "type": "text"},
                             {"name": "resource", "label": "Resource", "type": "choice", "choices": ["Unit 1", "Unit 2", "Unit 3"]},
                             {"name": "day", "label": "Day", "type": "date"},
                             {"name": "slot", "label": "Slot", "type": "choice", "choices": ["07:00", "10:00", "13:00", "16:00"]}],
                  "seed": [{"name": n, "resource": f"Unit {i % 3 + 1}", "day": (_today() + timedelta(days=i % 2)).isoformat(),
                            "slot": ["07:00", "10:00", "13:00", "16:00"][i % 4]}
                           for i, n in enumerate(["Ramesh Yadav", "Sunita Devi", "Harpreet Gill", "Mohan Patil"])],
                  "rule": {"resource_field": "resource", "day_field": "day", "slot_field": "slot"}}
    else:
        reqs = [r.get("title", "") for r in spec.get("requirements") or [] if r.get("title")]
        design = {"kind": kind, "entity": "Request", "entity_plural": "Requests", "action": "Add request",
                  "fields": [{"name": "title", "label": "Title", "type": "text"},
                             {"name": "raised_by", "label": "Raised by", "type": "text"},
                             {"name": "area", "label": "Area", "type": "text"}],
                  "seed": [{"title": t[:80], "raised_by": n, "area": a, "status": s} for t, n, a, s in zip(
                      reqs + ["Street light not working", "Water supply low", "Garbage not collected"],
                      ["Neha Gupta", "Arjun Mehta", "Pooja Nair", "Vikram Rao"], ["Block A", "Block B", "Block C", "Block A"],
                      ["open", "in progress", "done", "open"])],
                  "rule": {"statuses": ["open", "in progress", "done"]}}
    design["app_name"] = spec.get("title") or "Prototype"
    design["tagline"] = _short(spec.get("value") or spec.get("problem") or "")
    return normalize(design, spec)


# ---------------------------------------------------------------- features.py

_PY_TYPE = {"text": "str", "long_text": "str", "number": "float", "choice": "str", "date": "date"}


def _model_line(f: Dict[str, Any]) -> str:
    if f["type"] == "number":
        return f'    {f["name"]}: float = Field(ge={f["min"]!r}, le={f["max"]!r})'
    if f["type"] == "date":
        return f'    {f["name"]}: date'
    limit = 4000 if f["type"] == "long_text" else 80
    return f'    {f["name"]}: str = Field(min_length=1, max_length={limit})'


def _features(d: Dict[str, Any]) -> str:
    kind, rule, fields = d["kind"], d["rule"], d["fields"]
    path = _slug(d["entity_plural"], "records")
    fn = path.replace("-", "_")
    model = "New" + re.sub(r"[^A-Za-z0-9]", "", d["entity"].title()) or "NewRecord"
    if model == "New":
        model = "NewRecord"
    choices = {f["name"]: f["choices"] for f in fields if f["type"] == "choice"}
    doc = f'{d["app_name"]} API: {d["tagline"]}'.replace('"', "'").replace("\\", "")
    needs_date = kind == "booking" or any(f["type"] == "date" for f in fields)
    imports = (["from datetime import date"] if needs_date else []) + (
        ["from statistics import mean"] if kind in ("monitor", "review") else []) + [
        "from typing import Dict, List" + (", Optional" if kind == "booking" else "")]
    out = [f'"""{doc}"""', "\n".join(imports) + "\n"]
    out.append("from fastapi import APIRouter, HTTPException\nfrom pydantic import BaseModel, Field\n")
    out.append('router = APIRouter(prefix="/api")\n')
    if kind == "monitor":
        out.append(f'GROUP = {rule["group_field"]!r}\nVALUE = {rule["value_field"]!r}\nUNIT = {rule["unit"]!r}')
        if rule["mode"] == "spike":
            out.append(f'WARN_TIMES = {rule["warn"]!r}  # this many times the usual reading\nALERT_TIMES = {rule["alert"]!r}\n')
        else:
            out.append(f'WARN_AT = {rule["warn"]!r}\nALERT_AT = {rule["alert"]!r}\n')
    elif kind == "review":
        out.append(f'TEXT = {rule["text_field"]!r}\nPASS_MARK = {rule["pass_mark"]!r}')
        out.append("CHECKS = [\n" + "".join(f"    {c!r},\n" for c in rule["checks"]) + "]\n")
    elif kind == "tracker":
        out.append(f'STATUSES = {rule["statuses"]!r}\nDONE = STATUSES[-1]\n')
    else:
        out.append(f'RESOURCE = {rule["resource_field"]!r}\nDAY = {rule["day_field"]!r}\nSLOT = {rule["slot_field"]!r}')
    out.append(f"CHOICES: Dict[str, List[str]] = {choices!r}\n")
    out.append(f"{fn.upper()}: List[dict] = []\n")
    out.append(f"\nclass {model}(BaseModel):\n" + "\n".join(_model_line(f) for f in fields) + "\n")
    if kind == "tracker":
        out.append("\nclass StatusChange(BaseModel):\n    status: str\n")
    out.append(f'''
def _check_choices(data: dict) -> None:
    for name, allowed in CHOICES.items():
        if data.get(name) not in allowed:
            raise HTTPException(status_code=422, detail=f"{{name}} must be one of: {{', '.join(allowed)}}")
''')
    R = fn.upper()
    if kind == "monitor" and rule["mode"] == "spike":
        out.append(f'''
def evaluate(record: dict) -> dict:
    """Compares a reading with the usual reading of the same group."""
    history = [r[VALUE] for r in {R} if r[GROUP] == record[GROUP]]
    if not history:
        return {{"status": "normal", "note": "first reading"}}
    usual = mean(history)
    if usual <= 0:
        return {{"status": "normal", "note": "no usual value yet"}}
    times = record[VALUE] / usual
    note = f"{{times:.1f}}x the usual {{round(usual, 1)}} {{UNIT}}".strip()
    if times >= ALERT_TIMES:
        return {{"status": "alert", "note": note}}
    if times >= WARN_TIMES:
        return {{"status": "high", "note": note}}
    return {{"status": "normal", "note": note}}
''')
    elif kind == "monitor":
        out.append('''
def evaluate(record: dict) -> dict:
    """Compares a reading with the fixed warning and alert levels."""
    value = record[VALUE]
    if value >= ALERT_AT:
        return {"status": "alert", "note": f"at or above the alert level {ALERT_AT} {UNIT}".strip()}
    if value >= WARN_AT:
        return {"status": "high", "note": f"above the warning level {WARN_AT} {UNIT}".strip()}
    return {"status": "normal", "note": "within limits"}
''')
    elif kind == "review":
        out.append('''
def _passes(check: dict, text: str) -> bool:
    kind, value = check["kind"], check["value"]
    lines = text.splitlines() or [""]
    if kind == "contains":
        return str(value).lower() in text.lower()
    if kind == "not_contains":
        return str(value).lower() not in text.lower()
    if kind == "max_line_length":
        return all(len(line) <= value for line in lines)
    if kind == "max_lines":
        return len(lines) <= value
    if kind == "min_words":
        return len(text.split()) >= value
    if kind == "max_words":
        return len(text.split()) <= value
    return False


def evaluate(record: dict) -> dict:
    """Runs every check on the submitted text and scores it out of 100."""
    results = [{"label": c["label"], "passed": _passes(c, record[TEXT])} for c in CHECKS]
    score = round(100 * sum(r["passed"] for r in results) / len(results)) if results else 100
    return {"score": score, "status": "pass" if score >= PASS_MARK else "needs work", "results": results}
''')
    elif kind == "tracker":
        out.append('''
def evaluate(record: dict) -> dict:
    return {"status": record.get("status") if record.get("status") in STATUSES else STATUSES[0]}
''')
    else:
        out.append(f'''
def evaluate(record: dict) -> dict:
    return {{"status": "confirmed"}}


def _taken(data: dict) -> bool:
    return any(r[RESOURCE] == data[RESOURCE] and r[DAY] == data[DAY] and r[SLOT] == data[SLOT] for r in {R})
''')
    out.append(f'''
def _add(data: dict) -> dict:
    record = {{"id": max([r["id"] for r in {R}], default=0) + 1, **data}}
    record.update(evaluate(record))
    {R}.append(record)
    return record


for _row in {d["seed"]!r}:
    _add(_row)


@router.get("/{path}")
def list_{fn}():
    """Newest first."""
    return list(reversed({R}))


@router.post("/{path}", status_code=201)
def add_{fn}(new: {model}):
    data = new.model_dump(mode="json")
    _check_choices(data)
''')
    if kind == "booking":
        out.append('''    if _taken(data):
        raise HTTPException(status_code=409, detail="That slot is already booked. Pick another slot.")
''')
    out.append(f"    return _add(data)\n")

    if kind == "monitor":
        out.append(f'''

@router.get("/groups")
def by_group():
    """One row per group: number of readings, average, latest and alerts."""
    groups: Dict[str, List[dict]] = {{}}
    for r in {R}:
        groups.setdefault(r[GROUP], []).append(r)
    rows = [{{"group": name, "readings": len(rs), "average": round(mean(r[VALUE] for r in rs), 2),
             "latest": rs[-1][VALUE], "alerts": sum(r["status"] == "alert" for r in rs)}} for name, rs in groups.items()]
    return sorted(rows, key=lambda row: (-row["alerts"], row["group"]))


@router.get("/summary")
def summary():
    values = [r[VALUE] for r in {R}]
    return {{"count": len(values), "alerts": sum(r["status"] == "alert" for r in {R}),
            "average": round(mean(values), 2) if values else 0}}
''')
    elif kind == "review":
        out.append(f'''

@router.get("/checks")
def checks():
    return {{"checks": CHECKS, "pass_mark": PASS_MARK}}


@router.get("/summary")
def summary():
    scores = [r["score"] for r in {R}]
    passing = sum(r["status"] == "pass" for r in {R})
    return {{"count": len(scores), "average": round(mean(scores)) if scores else 0,
            "pass_rate": round(100 * passing / len(scores)) if scores else 0}}
''')
    elif kind == "tracker":
        out.append(f'''

@router.patch("/{path}/{{item_id}}")
def change_status(item_id: int, change: StatusChange):
    if change.status not in STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of: {{', '.join(STATUSES)}}")
    for r in {R}:
        if r["id"] == item_id:
            r["status"] = change.status
            return r
    raise HTTPException(status_code=404, detail="Not found")


@router.get("/summary")
def summary():
    by_status = {{s: sum(r["status"] == s for r in {R}) for s in STATUSES}}
    total = len({R})
    return {{"count": total, "open": total - by_status[DONE], "done_percent": round(100 * by_status[DONE] / total) if total else 0,
            "by_status": by_status}}
''')
    else:
        out.append(f'''

@router.get("/availability")
def availability(day: Optional[str] = None):
    """Free slots of every resource on one day (today by default)."""
    try:
        day = date.fromisoformat(day).isoformat() if day else date.today().isoformat()
    except ValueError:
        raise HTTPException(status_code=422, detail="day must look like 2025-01-31")
    rows = []
    for resource in CHOICES[RESOURCE]:
        booked = {{r[SLOT] for r in {R} if r[RESOURCE] == resource and r[DAY] == day}}
        rows.append({{"resource": resource, "free": [s for s in CHOICES[SLOT] if s not in booked], "booked": len(booked)}})
    return {{"day": day, "resources": rows}}


@router.get("/summary")
def summary():
    today = date.today().isoformat()
    booked_today = sum(r[DAY] == today for r in {R})
    return {{"count": len({R}), "today": booked_today,
            "free_today": len(CHOICES[RESOURCE]) * len(CHOICES[SLOT]) - booked_today}}
''')
    return "\n".join(out)


# ---------------------------------------------------------------- tests

def _valid_payload(d: Dict[str, Any]) -> Dict[str, Any]:
    row = {f["name"]: d["seed"][0][f["name"]] for f in d["fields"]}
    rule = d["rule"]
    if d["kind"] == "booking":
        row[rule["day_field"]] = "2031-03-14"
    if d["kind"] == "monitor":
        row[rule["group_field"]] = "Check group"
    return row


def _review_good_text(d: Dict[str, Any]) -> Optional[str]:
    """A text that passes every check, or None when the checks cannot all pass together."""
    lines = []
    for c in d["rule"]["checks"]:
        if c["kind"] == "contains":
            lines.append(str(c["value"]))
    words = max([c["value"] for c in d["rule"]["checks"] if c["kind"] == "min_words"] or [0])
    if words:
        lines.append(" ".join(["word"] * words))
    text = "\n".join(lines) or "ok"
    for c in d["rule"]["checks"]:
        v, ok = c["value"], True
        all_lines = text.splitlines() or [""]
        if c["kind"] == "contains":
            ok = str(v).lower() in text.lower()
        elif c["kind"] == "not_contains":
            ok = str(v).lower() not in text.lower()
        elif c["kind"] == "max_line_length":
            ok = all(len(line) <= v for line in all_lines)
        elif c["kind"] == "max_lines":
            ok = len(all_lines) <= v
        elif c["kind"] == "min_words":
            ok = len(text.split()) >= v
        elif c["kind"] == "max_words":
            ok = len(text.split()) <= v
        if not ok:
            return None
    return text


def _tests(d: Dict[str, Any]) -> str:
    kind, rule = d["kind"], d["rule"]
    path = "/api/" + _slug(d["entity_plural"], "records")
    valid = _valid_payload(d)
    text_field = next((f["name"] for f in d["fields"] if f["type"] in ("text", "long_text")), None)
    bad = dict(valid, **{text_field: ""}) if text_field else {}
    out = [f'''"""Tests for the {d["app_name"].replace('"', "")} prototype API."""
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)
VALID = {valid!r}


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_page_loads():
    page = client.get("/")
    assert page.status_code == 200
    assert "<html" in page.text.lower()


def test_list_has_sample_data():
    assert len(client.get("{path}").json()) >= 3


def test_add_and_list():
    created = client.post("{path}", json=VALID)
    assert created.status_code == 201
    ids = [r["id"] for r in client.get("{path}").json()]
    assert created.json()["id"] in ids


def test_bad_input_is_rejected():
    assert client.post("{path}", json={bad!r}).status_code == 422


def test_summary():
    summary = client.get("/api/summary").json()
    assert summary["count"] >= 3
''']
    if kind == "monitor":
        g, v = rule["group_field"], rule["value_field"]
        field = next(f for f in d["fields"] if f["name"] == v)
        if rule["mode"] == "spike":
            base = _clean(min(field["max"] / (rule["alert"] * 2), max(field["min"], 10)))
            if base <= 0:
                base = _clean(field["max"] / (rule["alert"] * 4))
            high = _clean(min(field["max"], base * rule["alert"] * 1.2))
            out.append(f'''

def test_unusual_reading_is_flagged():
    usual = dict(VALID, **{{{g!r}: "Spike check", {v!r}: {base!r}}})
    client.post("{path}", json=usual)
    client.post("{path}", json=usual)
    spike = client.post("{path}", json=dict(usual, **{{{v!r}: {high!r}}})).json()
    assert spike["status"] == "alert"
    normal = client.post("{path}", json=usual).json()
    assert normal["status"] != "alert"


def test_groups_summary():
    rows = client.get("/api/groups").json()
    assert rows and {{"group", "readings", "average", "alerts"}} <= set(rows[0])
''')
        else:
            out.append(f'''

def test_reading_above_alert_level_is_flagged():
    high = client.post("{path}", json=dict(VALID, **{{{v!r}: {rule["alert"]!r}}})).json()
    assert high["status"] == "alert"
    low = client.post("{path}", json=dict(VALID, **{{{v!r}: {field["min"]!r}}})).json()
    assert low["status"] == "normal"


def test_groups_summary():
    rows = client.get("/api/groups").json()
    assert rows and {{"group", "readings", "average", "alerts"}} <= set(rows[0])
''')
    elif kind == "review":
        t = rule["text_field"]
        out.append(f'''

def test_every_check_is_scored():
    result = client.post("{path}", json=VALID).json()
    assert len(result["results"]) == {len(rule["checks"])}
    assert 0 <= result["score"] <= 100
''')
        good = _review_good_text(d)
        if good is not None and len(good) <= 4000:
            out.append(f'''

def test_text_that_meets_every_check_passes():
    result = client.post("{path}", json=dict(VALID, **{{{t!r}: {good!r}}})).json()
    assert result["score"] == 100
    assert result["status"] == "pass"
''')
        bad_check = next((c for c in rule["checks"] if c["kind"] == "not_contains"), None)
        if bad_check:
            out.append(f'''

def test_failed_check_is_reported():
    result = client.post("{path}", json=dict(VALID, **{{{t!r}: {(str(bad_check["value"]) + " here")!r}}})).json()
    failed = [r["label"] for r in result["results"] if not r["passed"]]
    assert {bad_check["label"]!r} in failed
''')
    elif kind == "tracker":
        out.append(f'''

def test_status_can_change():
    item = client.post("{path}", json=VALID).json()
    assert item["status"] == {rule["statuses"][0]!r}
    changed = client.patch(f"{path}/{{item['id']}}", json={{"status": {rule["statuses"][-1]!r}}})
    assert changed.json()["status"] == {rule["statuses"][-1]!r}


def test_unknown_item_and_status():
    assert client.patch("{path}/99999", json={{"status": {rule["statuses"][0]!r}}}).status_code == 404
    item = client.post("{path}", json=VALID).json()
    assert client.patch(f"{path}/{{item['id']}}", json={{"status": "nonsense"}}).status_code == 422
''')
    else:
        r, s, day = rule["resource_field"], rule["slot_field"], rule["day_field"]
        out.append(f'''

def test_double_booking_is_refused():
    booking = dict(VALID, **{{{day!r}: "2031-05-20"}})
    assert client.post("{path}", json=booking).status_code == 201
    assert client.post("{path}", json=booking).status_code == 409


def test_availability_drops_after_a_booking():
    def free():
        rows = client.get("/api/availability", params={{"day": "2031-06-02"}}).json()["resources"]
        return sum(len(row["free"]) for row in rows)
    before = free()
    client.post("{path}", json=dict(VALID, **{{{day!r}: "2031-06-02"}}))
    assert free() == before - 1
''')
    return "".join(out)


# ---------------------------------------------------------------- page

_STATS = {
    "monitor": lambda d: [("count", d["entity_plural"]), ("alerts", "Alerts"),
                          ("average", f"Average{' (' + d['rule']['unit'] + ')' if d['rule']['unit'] else ''}")],
    "review": lambda d: [("count", d["entity_plural"]), ("average", "Average score"), ("pass_rate", "Passing (%)")],
    "tracker": lambda d: [("count", d["entity_plural"]), ("open", "Still open"), ("done_percent", "Done (%)")],
    "booking": lambda d: [("count", d["entity_plural"]), ("today", "Booked today"), ("free_today", "Free slots today")],
}
_SIDE_TITLE = {"monitor": "By {group}", "review": "What we check", "tracker": "By status", "booking": "Free slots"}

_JS_COMMON = r"""
async function api(path, options) {
  const res = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, options));
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = body.detail;
    throw new Error(Array.isArray(d) ? d.map((x) => (x.loc || []).slice(-1)[0] + ": " + x.msg).join("; ") : (d || res.status));
  }
  return body;
}
function el(tag, text, cls) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; }
function tag(value) { return el("span", value, "tag " + (APP.tones[value] || "")); }
function buildForm() {
  const form = document.getElementById("form");
  for (const f of APP.fields) {
    const wrap = el("label", f.label, "field");
    let input;
    if (f.type === "choice") {
      input = document.createElement("select");
      for (const c of f.choices) input.append(el("option", c));
    } else if (f.type === "long_text") {
      input = document.createElement("textarea");
      input.rows = 6;
      input.style.fontFamily = "Consolas, Menlo, monospace";
    } else {
      input = document.createElement("input");
      input.type = f.type === "number" ? "number" : f.type === "date" ? "date" : "text";
      if (f.type === "number") { input.step = "any"; input.min = f.min; input.max = f.max; }
      if (f.type === "date") input.value = new Date().toISOString().slice(0, 10);
      if (f.list) input.setAttribute("list", "options-" + f.name);
    }
    input.name = f.name;
    input.required = true;
    wrap.append(input);
    if (f.list) { const dl = el("datalist"); dl.id = "options-" + f.name; wrap.append(dl); }
    form.append(wrap);
  }
  const button = el("button", APP.action, "btn primary");
  button.type = "submit";
  form.append(button);
}
function readForm() {
  const data = {};
  for (const f of APP.fields) {
    const v = document.getElementById("form").elements[f.name].value;
    data[f.name] = f.type === "number" ? Number(v) : v;
  }
  return data;
}
function fillTable(rows) {
  const head = document.getElementById("head");
  head.replaceChildren(...APP.columns.map((c) => el("th", c.label)));
  const body = document.getElementById("rows");
  body.replaceChildren();
  if (!rows.length) { const tr = el("tr"); const td = el("td", "Nothing yet.", "empty"); td.colSpan = APP.columns.length; tr.append(td); body.append(tr); }
  for (const r of rows) {
    const tr = el("tr");
    for (const c of APP.columns) {
      const td = el("td");
      if (c.cell) td.append(c.cell(r)); else if (c.tag) td.append(tag(r[c.key])); else td.textContent = r[c.key] ?? "";
      if (c.mono) td.style.fontFamily = "Consolas, Menlo, monospace";
      tr.append(td);
    }
    body.append(tr);
  }
}
async function load() {
  const [rows, summary] = await Promise.all([api(APP.list), api("/api/summary")]);
  for (const [key] of APP.stats) document.getElementById("stat-" + key).textContent = summary[key];
  fillTable(rows);
  await side(rows, summary);
}
document.getElementById("form").onsubmit = async (e) => {
  e.preventDefault();
  const error = document.getElementById("error");
  try {
    const created = await api(APP.list, { method: "POST", body: JSON.stringify(readForm()) });
    error.textContent = "";
    for (const f of APP.fields) if (f.type === "long_text" || f.type === "text") document.getElementById("form").elements[f.name].value = "";
    document.getElementById("latest").textContent = latestText(created);
    load();
  } catch (err) { error.textContent = err.message; }
};
buildForm();
load();
"""

_JS_KIND = {
    "monitor": r"""
async function side() {
  const groups = await api("/api/groups");
  const list = document.getElementById("options-" + APP.group);
  if (list) list.replaceChildren(...groups.map((g) => { const o = el("option"); o.value = g.group; return o; }));
  const max = Math.max(1, ...groups.map((g) => g.average));
  const box = document.getElementById("side");
  box.replaceChildren();
  for (const g of groups) {
    const row = el("div", "", "list-row");
    const name = el("div", "", "row");
    name.append(el("strong", g.group), el("span", g.readings + " readings, avg " + g.average + " " + APP.unit, "muted"));
    if (g.alerts) name.append(el("span", g.alerts + " alert" + (g.alerts > 1 ? "s" : ""), "tag bad"));
    const bar = el("div", "", "bar"); const fill = el("span"); fill.style.width = Math.round(100 * g.average / max) + "%"; bar.append(fill);
    row.append(name, bar);
    box.append(row);
  }
}
function latestText(r) { return "Saved. Status: " + r.status + " (" + r.note + ")."; }
""",
    "review": r"""
let rules = null;
async function side(rows) {
  if (!rules) rules = await api("/api/checks");
  const box = document.getElementById("side");
  box.replaceChildren(el("p", "Pass mark: " + rules.pass_mark + " out of 100", "muted"));
  const latest = rows[0];
  for (const c of rules.checks) {
    const row = el("div", "", "row list-row");
    const result = latest && latest.results.find((x) => x.label === c.label);
    if (result) row.append(el("span", result.passed ? "pass" : "fail", "tag " + (result.passed ? "good" : "bad")));
    row.append(el("span", c.label));
    box.append(row);
  }
  if (latest) box.append(el("p", "Results shown for the newest " + APP.entity.toLowerCase() + ".", "muted"));
}
function latestText(r) { return "Checked. Score " + r.score + "/100: " + r.status + "."; }
""",
    "tracker": r"""
async function side(rows, summary) {
  const box = document.getElementById("side");
  box.replaceChildren();
  const total = Math.max(1, summary.count);
  for (const [status, n] of Object.entries(summary.by_status)) {
    const row = el("div", "", "list-row");
    const name = el("div", "", "row"); name.append(tag(status), el("span", n + "", "muted"));
    const bar = el("div", "", "bar"); const fill = el("span"); fill.style.width = Math.round(100 * n / total) + "%"; bar.append(fill);
    row.append(name, bar); box.append(row);
  }
}
function statusPicker(r) {
  const s = document.createElement("select");
  for (const v of APP.statuses) { const o = el("option", v); o.value = v; o.selected = v === r.status; s.append(o); }
  s.onchange = async () => { await api(APP.list + "/" + r.id, { method: "PATCH", body: JSON.stringify({ status: s.value }) }); load(); };
  return s;
}
APP.columns.push({ label: "Status", cell: statusPicker });
function latestText(r) { return "Added as " + r.status + "."; }
""",
    "booking": r"""
async function side() {
  const picker = document.getElementById("form").elements[APP.day];
  const data = await api("/api/availability?day=" + encodeURIComponent(picker.value || ""));
  const box = document.getElementById("side");
  box.replaceChildren(el("p", "On " + data.day, "muted"));
  for (const r of data.resources) {
    const row = el("div", "", "list-row");
    const head = el("div", "", "row"); head.append(el("strong", r.resource), el("span", r.free.length + " free", "muted"));
    const slots = el("div", "", "row");
    for (const s of r.free) slots.append(el("span", s, "tag good"));
    if (!r.free.length) slots.append(el("span", "Fully booked", "tag bad"));
    row.append(head, slots); box.append(row);
  }
}
document.getElementById("form").addEventListener("change", (e) => { if (e.target.name === APP.day) side(); });
function latestText(r) { return "Booked. Booking number " + r.id + "."; }
""",
}


def _page(d: Dict[str, Any]) -> str:
    kind, rule = d["kind"], d["rule"]
    path = "/api/" + _slug(d["entity_plural"], "records")
    fields = []
    for f in d["fields"]:
        entry = {"name": f["name"], "label": f["label"], "type": f["type"]}
        if f["type"] == "choice":
            entry["choices"] = f["choices"]
        if f["type"] == "number":
            entry.update(min=f["min"], max=f["max"])
        if kind == "monitor" and f["name"] == rule["group_field"]:
            entry["list"] = True
        fields.append(entry)
    columns = [{"key": "id", "label": "#"}]
    for f in d["fields"]:
        if f["type"] != "long_text":
            columns.append({"key": f["name"], "label": f["label"]})
    tones: Dict[str, str] = {}
    if kind == "monitor":
        columns += [{"key": "status", "label": "Status", "tag": True}, {"key": "note", "label": "Why"}]
        tones = {"normal": "good", "high": "warn", "alert": "bad"}
    elif kind == "review":
        columns += [{"key": "score", "label": "Score"}, {"key": "status", "label": "Result", "tag": True}]
        tones = {"pass": "good", "needs work": "warn"}
    elif kind == "booking":
        columns.append({"key": "status", "label": "Status", "tag": True})
        tones = {"confirmed": "good"}
    else:
        tones = {s: ("good" if s == rule["statuses"][-1] else "warn" if i else "") for i, s in enumerate(rule["statuses"])}
    stats = _STATS[kind](d)
    app = {"list": path, "fields": fields, "columns": columns, "tones": tones, "stats": stats,
           "action": d["action"], "entity": d["entity"]}
    if kind == "monitor":
        app.update(group=rule["group_field"], unit=rule["unit"])
    if kind == "tracker":
        app["statuses"] = rule["statuses"]
    if kind == "booking":
        app["day"] = rule["day_field"]
    group_label = next((f["label"] for f in d["fields"] if f["name"] == rule.get("group_field")), "group")
    side_title = _SIDE_TITLE[kind].format(group=group_label.lower())
    e = html.escape
    look = d.get("look") or {"theme": "blue", "layout": "dashboard", "header": "light"}
    stat_cards = "\n".join(
        f'      <div class="card"><div class="muted">{e(label)}</div><div class="stat" id="stat-{key}">0</div></div>'
        for key, label in stats)
    config = json.dumps(app, indent=1, ensure_ascii=False).replace("</", "<\\/")
    form_card = (f'<div class="card"><h2>{e(d["action"])}</h2><form id="form"></form>'
                 f'<p class="error" id="error"></p><p class="muted" id="latest"></p></div>')
    side_card = f'<div class="card"><h2>{e(side_title)}</h2><div id="side"></div></div>'
    table_card = (f'<div class="card"><h2>{e(d["entity_plural"])}</h2><div style="overflow-x:auto"><table>'
                  f'<thead><tr id="head"></tr></thead><tbody id="rows"></tbody></table></div></div>')
    header = (f'<header class="top"><div class="wrap"><span class="brand">{e(d["app_name"])}</span>'
              f'<span class="muted">{e(d["tagline"])}</span></div></header>')
    if look["layout"] == "sidebar":
        body = f"""{header}
<main class="wrap">
  <div class="side-layout">
    <aside>
      {form_card}
      {side_card}
    </aside>
    <section>
      <div class="grid">
{stat_cards}
      </div>
      {table_card}
    </section>
  </div>
</main>"""
    elif look["layout"] == "banner":
        brand = f'<span class="brand">{e(d["app_name"])}</span>'
        body = f"""<header class="top"><div class="wrap">{brand}<span class="muted">{e(d["entity_plural"])}</span></div></header>
<section class="banner"><div class="wrap"><h1>{e(d["app_name"])}</h1><p class="muted">{e(d["tagline"])}</p></div></section>
<main class="wrap">
  <div class="grid banner-stats">
{stat_cards}
  </div>
  {form_card.replace('<form id="form">', '<form id="form" class="form-inline">')}
  <div class="cols">
    {table_card}
    {side_card}
  </div>
</main>"""
    else:
        body = f"""{header}
<main class="wrap">
  <div class="grid">
{stat_cards.replace('class="card"', 'class="card accent-line"')}
  </div>
  <div class="cols">
    {form_card}
    {side_card}
  </div>
  {table_card}
</main>"""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(d["app_name"])}</title>
<link rel="stylesheet" href="/static/base.css">
</head>
<body data-theme="{look["theme"]}" data-layout="{look["layout"]}" data-header="{look["header"]}">
{body}
<script>
const APP = {config};
{_JS_KIND[kind].strip()}
{_JS_COMMON.strip()}
</script>
</body>
</html>
"""


def render(design: Dict[str, Any]) -> Dict[str, str]:
    """The three idea-specific files for a normalised design."""
    return {"features.py": _features(design), "static/index.html": _page(design), "test_features.py": _tests(design)}
