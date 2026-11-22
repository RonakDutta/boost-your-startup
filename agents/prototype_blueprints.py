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
- shop    : an online store with a cart; price, bulk discount, tax, delivery,
            minimum order and stock are computed on the server.
- split   : a group shares costs; balances and "who pays whom" are computed.
- listing : a directory people filter and rate from 1 to 5 stars.

Without the AI, `default_design()` picks a kind from keywords in the idea and
fills a plain design (the build is then labelled as a fallback).
"""

import html
import json
import keyword
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

KINDS = ("monitor", "review", "tracker", "booking", "shop", "split", "listing")
FIELD_TYPES = ("text", "long_text", "number", "choice", "date")
# Keys the generated code adds to every record, so no field may use them.
RESERVED = {"id", "status", "note", "score", "results", "group", "day_param", "ratings", "rating", "reviews", "share"}

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
- "shop": an online store; people browse products, add them to a cart and order. Price, bulk discount, tax, delivery and stock are computed in code.
  fields: product name (text), category (choice), price (number), stock (number), plus up to 4 product details (material, size, unit, minimum order).
  rule: {"name_field": "...", "category_field": "...", "price_field": "...", "stock_field": "...", "unit_field": "<optional choice field>",
  "moq_field": "<optional number field: minimum order>", "currency": "₹", "tax_percent": 18, "bulk": [{"min_qty": 50, "off_percent": 5}],
  "delivery_fee": 100, "free_delivery_over": 5000}
- "split": a group shares costs; every expense is split equally and the app shows who owes whom.
  rule: {"payer_field": "<choice field whose choices are the members>", "amount_field": "<number field>", "currency": "₹"}
- "listing": a directory people filter and rate from 1 to 5 stars (tutors, PGs, mechanics, mess, clinics).
  rule: {"name_field": "<text field>", "category_field": "<choice field>"}; seed records may have "ratings": [5, 4, 4]
- "custom": only if none of these can show the idea at all.

Return only this JSON:
{"kind": "...", "app_name": "2 to 4 words", "tagline": "one short line", "entity": "singular noun, e.g. Reading",
 "entity_plural": "e.g. Readings", "action": "button text, e.g. Add reading",
 "fields": [{"name": "snake_case", "label": "Label", "type": "text|long_text|number|choice|date", "choices": ["only for choice"], "min": 0, "max": 1000}],
 "seed": [4 to 6 records (shop: 6 to 10 products), each with a value for every field],
 "rule": {...},
 "look": {"theme": "blue|teal|amber|indigo|green|rose|slate|orange", "layout": "dashboard|sidebar|banner", "header": "light|accent|dark"}}
- 3 to 5 fields (shop: up to 8); every *_field in the rule must be one of them.
- Seed records: realistic names, places and numbers for this idea's users in India, dates in the last two weeks. No Alice/Bob, foo or test.
- For review, seed texts are short (under 6 lines) and some pass and some fail the checks.
- look: colours that suit the idea (water: teal or blue, energy: amber, health: rose, farming: green, code: indigo, shops: orange or slate)."""


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


def _name(text: Any, limit: int = 48) -> str:
    """App name, cut at a word boundary (never mid-word) and without a dangling small word."""
    text = re.sub(r"\s+", " ", str(text or "")).strip() or "Prototype"
    if len(text) <= limit:
        return text
    words = text[:limit + 1].split(" ")[:-1] or [text[:limit]]
    while len(words) > 1 and words[-1].lower() in ("and", "or", "for", "of", "the", "a", "an", "with", "to", "in"):
        words.pop()
    return " ".join(words)


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

def _norm_fields(raw: Any, limit: int = 5) -> List[Dict[str, Any]]:
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
    return fields[:limit]


def _find(fields, name, types, skip=()) -> Optional[Dict[str, Any]]:
    want = _ident(name, "") if name else ""
    free = [f for f in fields if f["name"] not in skip]
    for f in free:
        if f["name"] == want and f["type"] in types:
            return f
    for f in free:
        if f["type"] in types:
            return f
    return None


def _ensure(fields, name, types, new, keep=(), limit=5) -> Dict[str, Any]:
    """The field the rule names (or the first of the right type); otherwise `new` is added.
    Fields in `keep` are already used by the rule: they are never matched again or dropped."""
    found = _find(fields, name, types, keep)
    if found:
        return found
    taken = {f["name"] for f in fields}
    while new["name"] in taken:
        new["name"] += "_2"
    if len(fields) >= limit:
        drop = next((f for f in reversed(fields) if f["name"] not in keep), None)
        if drop:
            fields.remove(drop)
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
        return int(round(out)) if field.get("integer") else _clean(out)
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


THEMES = ("blue", "teal", "amber", "indigo", "green", "rose", "slate", "orange")
LAYOUTS = ("dashboard", "sidebar", "banner")
HEADERS = ("light", "accent", "dark")
_THEME_WORDS = (("orange", r"rubber|latex|tyre|gasket|hardware|handloom|craft|spice"), ("teal", r"water|leak|pipe|ocean|clean"), ("amber", r"energy|power|electric|solar|kwh|food|canteen"),
                ("indigo", r"code|program|lab|student|review|exam"), ("green", r"farm|crop|tractor|plant|waste|green|agri"),
                ("rose", r"health|patient|hospital|clinic|blood|doctor"), ("slate", r"complaint|ticket|hostel|admin"))


# Default layout and header for each colour, so ideas with different colours also get different pages.
_THEME_LOOK = {"teal": ("dashboard", "dark"), "amber": ("banner", "light"), "indigo": ("sidebar", "accent"),
               "green": ("sidebar", "light"), "rose": ("banner", "dark"), "slate": ("dashboard", "accent"),
               "orange": ("banner", "dark")}


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
    if kind == "shop":
        layout = "store"  # the shop has its own page: catalogue, cart and orders
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
    limit = 8 if kind == "shop" else 5
    fields = _norm_fields(design.get("fields"), limit)
    entity = _label(design.get("entity"), "Record", 24)
    plural = _label(design.get("entity_plural"), entity + "s", 24)
    rule: Dict[str, Any] = {}

    if kind == "monitor":
        group = _ensure(fields, rule_in.get("group_field"), ("text", "choice"), {"name": "location", "label": "Location", "type": "text"})
        if group["type"] == "choice":  # tests add a new group, so it stays free text
            group["type"] = "text"
            group.pop("choices", None)
        value = _ensure(fields, rule_in.get("value_field"), ("number",), {"name": "reading", "label": "Reading", "type": "number", "min": 0, "max": 100000},
                        keep={group["name"]})
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
    elif kind == "booking":
        resource = _ensure(fields, rule_in.get("resource_field"), ("choice",), {"name": "resource", "label": "Resource", "type": "choice", "choices": ["Room 1", "Room 2"]})
        slot = _ensure(fields, rule_in.get("slot_field"), ("choice",), {"name": "slot", "label": "Time slot", "type": "choice",
                                                                       "choices": ["09:00", "11:00", "14:00", "16:00", "18:00"]},
                       keep={resource["name"]})
        day = _ensure(fields, rule_in.get("day_field"), ("date",), {"name": "day", "label": "Day", "type": "date"},
                      keep={resource["name"], slot["name"]})
        rule = {"resource_field": resource["name"], "slot_field": slot["name"], "day_field": day["name"]}
    elif kind == "shop":
        rule = _shop_rule(fields, rule_in)
    elif kind == "split":
        members = []
        for m in rule_in.get("members") or []:
            m = _label(m, "", 30)
            if m and m not in members:
                members.append(m)
        if len(members) >= 2:  # the AI named the members but made the payer a text field
            for f in fields:
                if f["name"] == _ident(rule_in.get("payer_field"), "") and f["type"] == "text":
                    f.update(type="choice", choices=members[:8])
        payer = _ensure(fields, rule_in.get("payer_field"), ("choice",), {"name": "paid_by", "label": "Paid by", "type": "choice",
                                                                         "choices": members[:8] if len(members) >= 2 else ["Member 1", "Member 2", "Member 3"]})
        amount = _ensure(fields, rule_in.get("amount_field"), ("number",), {"name": "amount", "label": "Amount", "type": "number", "min": 1, "max": 100000},
                         keep={payer["name"]})
        amount["min"] = max(amount["min"], 0.01)
        if amount["max"] <= amount["min"]:
            amount["max"] = 100000
        rule = {"payer_field": payer["name"], "amount_field": amount["name"], "members": payer["choices"],
                "currency": _label(rule_in.get("currency"), "₹", 3)}
    else:  # listing
        name = _ensure(fields, rule_in.get("name_field"), ("text",), {"name": "name", "label": "Name", "type": "text"})
        category = _ensure(fields, rule_in.get("category_field"), ("choice",), {"name": "category", "label": "Category", "type": "choice",
                                                                               "choices": ["General", "Other"]},
                           keep={name["name"]})
        rule = {"name_field": name["name"], "category_field": category["name"]}

    if not any(f["type"] in ("text", "long_text") for f in fields) and len(fields) < limit:
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
        if kind == "listing":
            stars = row.get("ratings") if isinstance(row.get("ratings"), list) else []
            clean["ratings"] = [int(_num(x, 0)) for x in stars if 1 <= _num(x, 0) <= 5][:20]
        seed.append(clean)
    i = 0
    while len(seed) < 3:
        row = {f["name"]: _example(f, i + len(seed)) for f in fields}
        if kind == "booking":
            row[rule["slot_field"]] = next(f for f in fields if f["name"] == rule["slot_field"])["choices"][len(seed) % 2]
        if kind == "listing":
            row["ratings"] = []
        i += 1
        seed.append(row)
    if kind == "shop":
        _shop_seed_fix(seed, fields, rule)

    return {
        "kind": kind,
        "app_name": _name(design.get("app_name") or spec.get("title")),
        "tagline": _short(design.get("tagline") or spec.get("value") or spec.get("problem") or ""),
        "entity": entity,
        "entity_plural": plural,
        "action": _label(design.get("action"), f"Add {entity.lower()}", 30),
        "fields": fields,
        "seed": seed[:12],
        "rule": rule,
        "look": pick_look(design, spec, kind),
    }


def _shop_rule(fields: List[Dict[str, Any]], rule_in: Dict[str, Any]) -> Dict[str, Any]:
    """Shop: which fields are the name, category, price and stock, and the pricing settings."""
    name = _ensure(fields, rule_in.get("name_field"), ("text",), {"name": "name", "label": "Product", "type": "text"}, limit=8)
    used = {name["name"]}
    category = _ensure(fields, rule_in.get("category_field"), ("choice",), {"name": "category", "label": "Category", "type": "choice",
                                                                           "choices": ["Standard", "Premium"]}, keep=used, limit=8)
    used.add(category["name"])
    price = _ensure(fields, rule_in.get("price_field"), ("number",), {"name": "price", "label": "Price", "type": "number", "min": 1, "max": 1000000},
                    keep=used, limit=8)
    used.add(price["name"])
    stock = _ensure(fields, rule_in.get("stock_field"), ("number",), {"name": "stock", "label": "In stock", "type": "number", "min": 0, "max": 1000000},
                    keep=used, limit=8)
    used.add(stock["name"])
    moq = _find(fields, rule_in.get("moq_field"), ("number",), used) if rule_in.get("moq_field") else None
    if moq:
        used.add(moq["name"])
    unit = _find(fields, rule_in.get("unit_field"), ("choice", "text"), used) if rule_in.get("unit_field") else None
    price["min"] = max(price["min"], 0.01)
    if price["max"] <= price["min"]:
        price["max"] = 1000000
    stock.update(integer=True, min=0, max=max(int(stock["max"]), 1000))
    if moq:
        moq.update(integer=True, min=1, max=max(int(moq["max"]), 1))
    tiers, last_qty, last_off = [], 1, 0.0
    for t in rule_in.get("bulk") or []:
        if not isinstance(t, dict):
            continue
        qty, off = int(_num(t.get("min_qty"), 0)), _clean(_num(t.get("off_percent"), 0))
        if qty > last_qty and last_off < off <= 50:  # each tier: more units, bigger discount
            tiers.append({"min_qty": qty, "off_percent": off})
            last_qty, last_off = qty, off
    tax = _num(rule_in.get("tax_percent"), 18)
    fee = _num(rule_in.get("delivery_fee"), 100)
    free_over = _num(rule_in.get("free_delivery_over"), 5000)
    return {"name_field": name["name"], "category_field": category["name"], "price_field": price["name"],
            "stock_field": stock["name"], "moq_field": moq["name"] if moq else None, "unit_field": unit["name"] if unit else None,
            "unit": _label(rule_in.get("unit"), "unit", 12) if not unit else "",
            "currency": _label(rule_in.get("currency"), "₹", 3), "tax_percent": _clean(tax if 0 <= tax <= 40 else 18),
            "bulk": tiers[:3], "delivery_fee": _clean(fee if 0 <= fee <= 100000 else 100),
            "free_delivery_over": _clean(free_over if 0 <= free_over <= 10000000 else 5000),
            "low_stock_at": int(min(1000, max(1, _num(rule_in.get("low_stock_at"), 20))))}


def _shop_seed_fix(seed: List[Dict[str, Any]], fields: List[Dict[str, Any]], rule: Dict[str, Any]) -> None:
    """Integer stock and minimum order, and at least one product that can be ordered (the tests need it)."""
    stock, moq = rule["stock_field"], rule["moq_field"]
    for row in seed:
        row[stock] = int(row[stock])
        if moq:
            row[moq] = max(1, int(row[moq]))
    if not any(row[stock] >= (row[moq] if moq else 1) for row in seed):
        top = next(f for f in fields if f["name"] == stock)["max"]
        seed[0][stock] = int(min(top, max(100, seed[0][moq] if moq else 1)))


# ---------------------------------------------------------------- default design (no AI)

_KEYWORDS = {
    "monitor": ("meter", "sensor", "monitor", "reading", "iot", "leak", "spike", "energy", "power", "water",
                "consumption", "usage", "temperature", "air quality", "pollution", "esp32", "lorawan", "telemetry"),
    "review": ("review", "submission", "grade", "grading", "lint", "plagiarism", "essay", "assignment",
               "resume", "code quality", "feedback on", "evaluate code"),
    "booking": ("book a", "book the", "book slots", "booking", "slot", "appointment", "reserve", "reservation", "schedule", "rent", "hire"),
    "tracker": ("complaint", "ticket", "track", "order", "request", "issue", "task", "status", "delivery",
                "inventory", "lost and found", "report"),
    "shop": ("e-commerce", "ecommerce", "online store", "online shop", "webshop", "storefront", "shop", "sell",
             "buyer", "cart", "checkout", "catalogue", "catalog", "products", "bulk discount", "gst", "wholesale",
             "retail", "d2c", "purchase"),
    "split": ("split", "shared expense", "share expenses", "bills", "flatmate", "roommate", "owes", "owe ",
              "settle up", "group expense", "trip expense", "kitty"),
    "listing": ("directory", "listing", "rating", "rated", "find a", "find the", "nearby", "discover", "tutor",
                "mechanic", "paying guest", "local services", "compare", "stars"),
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
    elif kind == "shop":
        design = _default_shop(text)
    elif kind == "split":
        members = ["Riya", "Aman", "Kabir", "Neha"]
        rows = [("Monthly groceries, DMart", "Riya", 3240, "Groceries"), ("Electricity bill, October", "Aman", 1860, "Bills"),
                ("Wi-Fi recharge", "Kabir", 799, "Bills"), ("Vegetables and milk", "Neha", 640, "Groceries"),
                ("Pizza night", "Aman", 1150, "Food out"), ("Cooking gas cylinder", "Riya", 905, "Bills")]
        design = {"kind": kind, "entity": "Expense", "entity_plural": "Expenses", "action": "Add expense",
                  "fields": [{"name": "description", "label": "What for", "type": "text"},
                             {"name": "paid_by", "label": "Paid by", "type": "choice", "choices": members},
                             {"name": "amount", "label": "Amount (₹)", "type": "number", "min": 1, "max": 100000},
                             {"name": "category", "label": "Category", "type": "choice", "choices": ["Groceries", "Bills", "Food out", "Travel", "Other"]},
                             {"name": "day", "label": "Day", "type": "date"}],
                  "seed": [{"description": w, "paid_by": p, "amount": a, "category": c, "day": (_today() - timedelta(days=12 - 2 * i)).isoformat()}
                           for i, (w, p, a, c) in enumerate(rows)],
                  "rule": {"payer_field": "paid_by", "amount_field": "amount", "currency": "₹"}}
    elif kind == "listing":
        if re.search(r"tutor|coach|teacher|class", text):
            cats = ["Maths", "Physics", "Coding", "English"]
            rows = [("Sunita Iyer", "Maths", "Dwarka Sector 7", 600, [5, 5, 4]), ("Rohit Bansal", "Physics", "Janakpuri", 700, [4, 4]),
                    ("Code with Aditi", "Coding", "Rohini Sector 9", 900, [5, 5, 5, 4]), ("Meera Joshi", "English", "Uttam Nagar", 450, [3, 4]),
                    ("Vikas Chauhan", "Maths", "Paschim Vihar", 500, [])]
            label, price, entity = "Tutor", "Fee per hour (₹)", "Tutor"
        else:
            cats = ["Electrician", "Plumber", "Carpenter", "AC repair"]
            rows = [("Sharma Electricals", "Electrician", "Lajpat Nagar", 300, [5, 4, 5]), ("Quick Fix Plumbing", "Plumber", "Kalkaji", 250, [4, 3, 4]),
                    ("Gupta Wood Works", "Carpenter", "Govindpuri", 400, [5, 5]), ("Cool Care AC Service", "AC repair", "Nehru Place", 499, [4, 5, 4, 4]),
                    ("Ankit Electric Repair", "Electrician", "Malviya Nagar", 200, [])]
            label, price, entity = "Name", "Visit charge (₹)", "Listing"
        design = {"kind": kind, "entity": entity, "entity_plural": entity + "s", "action": f"Add {entity.lower()}",
                  "fields": [{"name": "name", "label": label, "type": "text"},
                             {"name": "category", "label": "Category", "type": "choice", "choices": cats},
                             {"name": "area", "label": "Area", "type": "text"},
                             {"name": "price", "label": price, "type": "number", "min": 0, "max": 100000}],
                  "seed": [{"name": n, "category": c, "area": a, "price": p, "ratings": r} for n, c, a, p, r in rows],
                  "rule": {"name_field": "name", "category_field": "category"}}
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


def _default_shop(text: str) -> Dict[str, Any]:
    """Sample catalogue for a shop (rubber products when the idea mentions rubber)."""
    if re.search(r"rubber|latex|gasket|o-ring|hose", text):
        cats = ["Sheets & mats", "O-rings & seals", "Hoses & tubes", "Gloves", "Industrial parts"]
        materials = ["Natural rubber", "EPDM", "Nitrile (NBR)", "Neoprene", "Silicone"]
        units = ["piece", "metre", "sq m", "pair", "kit"]
        rows = [("Natural rubber sheet, 3 mm", 0, 0, 60, 380, "sq m", 240, 5),
                ("EPDM gasket sheet, 5 mm", 0, 1, 70, 690, "sq m", 120, 5),
                ("Nitrile O-ring kit, 382 pieces", 1, 2, 70, 1450, "kit", 35, 1),
                ("Neoprene flange gasket, 4 inch", 1, 3, 65, 85, "piece", 900, 50),
                ("EPDM garden hose, 1/2 inch", 2, 1, 55, 62, "metre", 1500, 15),
                ("Silicone tube, 6 mm bore", 2, 4, 50, 48, "metre", 600, 10),
                ("Anti-fatigue rubber mat, 3 x 2 ft", 0, 0, 60, 1150, "piece", 14, 1),
                ("Nitrile work gloves", 3, 2, 45, 95, "pair", 800, 12),
                ("Rubber V-belt, B-42", 4, 3, 75, 320, "piece", 0, 2),
                ("Solid rubber trolley wheel, 8 inch", 4, 0, 80, 540, "piece", 60, 4)]
        return {"kind": "shop", "entity": "Product", "entity_plural": "Products", "action": "Add product",
                "fields": [{"name": "name", "label": "Product", "type": "text"},
                           {"name": "category", "label": "Category", "type": "choice", "choices": cats},
                           {"name": "material", "label": "Material", "type": "choice", "choices": materials},
                           {"name": "hardness", "label": "Hardness (Shore A)", "type": "number", "min": 20, "max": 95},
                           {"name": "price", "label": "Price (₹)", "type": "number", "min": 1, "max": 500000},
                           {"name": "unit", "label": "Sold per", "type": "choice", "choices": units},
                           {"name": "stock", "label": "In stock", "type": "number", "min": 0, "max": 100000},
                           {"name": "min_order", "label": "Minimum order", "type": "number", "min": 1, "max": 10000}],
                "seed": [{"name": n, "category": cats[c], "material": materials[m], "hardness": h, "price": p,
                          "unit": u, "stock": st, "min_order": mo} for n, c, m, h, p, u, st, mo in rows],
                "rule": {"name_field": "name", "category_field": "category", "price_field": "price", "stock_field": "stock",
                         "unit_field": "unit", "moq_field": "min_order", "currency": "₹", "tax_percent": 18,
                         "bulk": [{"min_qty": 50, "off_percent": 5}, {"min_qty": 200, "off_percent": 10}],
                         "delivery_fee": 150, "free_delivery_over": 10000, "low_stock_at": 20}}
    for words, preset in _SHOP_PRESETS:
        if re.search(words, text):
            break
    else:
        preset = _SHOP_PRESETS[-1][1]
    cats, (fname, flabel, fchoices), unit, rows, extra = preset
    return {"kind": "shop", "entity": "Product", "entity_plural": "Products", "action": "Add product",
            "fields": [{"name": "name", "label": "Product", "type": "text"},
                       {"name": "category", "label": "Category", "type": "choice", "choices": cats},
                       {"name": fname, "label": flabel, "type": "choice", "choices": fchoices},
                       {"name": "price", "label": "Price (₹)", "type": "number", "min": 1, "max": 500000},
                       {"name": "stock", "label": "In stock", "type": "number", "min": 0, "max": 100000}],
            "seed": [{"name": n, "category": cats[c], fname: fchoices[f], "price": pr, "stock": st} for n, c, f, pr, st in rows],
            "rule": {"name_field": "name", "category_field": "category", "price_field": "price", "stock_field": "stock",
                     "unit": unit, "currency": "₹", "tax_percent": 18, "low_stock_at": 20, **extra}}


# Sample catalogues for a shop when the AI is not available (words in the idea, catalogue).
# Each: categories, (filter field, label, choices), unit, rows (name, category, choice, price, stock), pricing.
_SHOP_PRESETS = [
    (r"cloth|apparel|fashion|saree|kurta|handloom|garment|shirt|ethnic|wear\b", (
        ["Sarees", "Kurtas", "Shirts", "Stoles"], ("fabric", "Fabric", ["Cotton", "Silk", "Linen", "Khadi", "Wool"]), "piece",
        [("Handloom cotton saree", 0, 0, 1850, 40), ("Kanchipuram silk saree", 0, 1, 6400, 12), ("Khadi straight kurta", 1, 3, 1199, 65),
         ("Block-print cotton kurta", 1, 0, 899, 120), ("Linen half-sleeve shirt", 2, 2, 1499, 80), ("Woollen winter stole", 3, 4, 2200, 0)],
        {"bulk": [{"min_qty": 10, "off_percent": 5}], "delivery_fee": 80, "free_delivery_over": 1999})),
    (r"spice|organic|food|snack|honey|tea\b|coffee|grocer|pickle|millet|farm fresh", (
        ["Spices", "Tea and coffee", "Honey and jams", "Millets"], ("pack", "Pack size", ["100 g", "250 g", "500 g", "1 kg"]), "pack",
        [("Kerala black pepper", 0, 1, 260, 150), ("Kashmiri red chilli powder", 0, 1, 180, 90), ("Nilgiri green tea", 1, 0, 240, 60),
         ("Coorg filter coffee powder", 1, 2, 390, 14), ("Wild forest honey", 2, 2, 450, 45), ("Foxtail millet", 3, 3, 160, 200)],
        {"bulk": [{"min_qty": 12, "off_percent": 5}, {"min_qty": 48, "off_percent": 10}], "delivery_fee": 50, "free_delivery_over": 799})),
    (r"electronic|gadget|mobile accessor|phone|charger|earbud|laptop accessor", (
        ["Chargers", "Cables", "Audio", "Cases"], ("warranty", "Warranty", ["6 months", "1 year", "2 years"]), "piece",
        [("20 W USB-C fast charger", 0, 1, 899, 140), ("10000 mAh power bank", 0, 1, 1499, 9), ("USB-C to USB-C cable, 1 m", 1, 0, 349, 300),
         ("Wireless earbuds", 2, 1, 1999, 55), ("Neckband earphones", 2, 0, 1299, 70), ("Clear silicone phone case", 3, 0, 299, 260)],
        {"bulk": [{"min_qty": 20, "off_percent": 8}], "delivery_fee": 49, "free_delivery_over": 999})),
    (r"book|stationery|notebook|\bpens?\b|school supplies", (
        ["Textbooks", "Notebooks", "Pens", "Art supplies"], ("level", "For", ["School", "College", "Everyone"]), "piece",
        [("Engineering Mathematics, 4th edition", 0, 1, 650, 35), ("NCERT Physics, Class 12", 0, 0, 250, 80),
         ("Long notebook, 200 pages", 1, 2, 75, 600), ("Gel pen, pack of 10", 2, 2, 120, 400),
         ("Water colour set, 24 shades", 3, 0, 340, 18), ("Lab record book", 1, 1, 95, 0)],
        {"bulk": [{"min_qty": 25, "off_percent": 5}, {"min_qty": 100, "off_percent": 12}], "delivery_fee": 40, "free_delivery_over": 499})),
    (r".", (
        ["Everyday", "Premium", "Gifts"], ("pack", "Pack", ["Single", "Pack of 3", "Box"]), "pack",
        [("Starter pack", 0, 0, 499, 120), ("Family pack", 0, 1, 899, 80), ("Gift box", 2, 2, 1299, 25),
         ("Premium pack", 1, 1, 1999, 15), ("Refill pack", 0, 0, 299, 300), ("Festive hamper", 2, 2, 2499, 0)],
        {"bulk": [{"min_qty": 10, "off_percent": 5}], "delivery_fee": 60, "free_delivery_over": 999})),
]


# ---------------------------------------------------------------- features.py

_PY_TYPE = {"text": "str", "long_text": "str", "number": "float", "choice": "str", "date": "date"}


def _model_line(f: Dict[str, Any]) -> str:
    if f["type"] == "number" and f.get("integer"):
        return f'    {f["name"]}: int = Field(ge={int(f["min"])!r}, le={int(f["max"])!r})'
    if f["type"] == "number":
        return f'    {f["name"]}: float = Field(ge={f["min"]!r}, le={f["max"]!r})'
    if f["type"] == "date":
        return f'    {f["name"]}: date'
    limit = 4000 if f["type"] == "long_text" else 80
    return f'    {f["name"]}: str = Field(min_length=1, max_length={limit})'


# Fixed routes of each kind; the records' own route may not take one of these names.
_FIXED_ROUTES = {"summary", "groups", "checks", "availability", "balances", "settle", "orders", "quote", "top", "health"}


def _path(d: Dict[str, Any]) -> str:
    """The records' route name: products for a shop, otherwise from the entity name."""
    if d["kind"] == "shop":
        return "products"
    path = _slug(d["entity_plural"], "records")
    return "records" if path in _FIXED_ROUTES else path


def _features(d: Dict[str, Any]) -> str:
    kind, rule, fields = d["kind"], d["rule"], d["fields"]
    path = _path(d)
    fn = path.replace("-", "_")
    model = "New" + re.sub(r"[^A-Za-z0-9]", "", d["entity"].title()) or "NewRecord"
    if model == "New":
        model = "NewRecord"
    choices = {f["name"]: f["choices"] for f in fields if f["type"] == "choice"}
    doc = f'{d["app_name"]} API: {d["tagline"]}'.replace('"', "'").replace("\\", "")
    needs_date = kind == "booking" or any(f["type"] == "date" for f in fields)
    dt = ["date"] if needs_date else []
    if kind == "shop":
        dt.append("datetime")
    imports = ([f"from datetime import {', '.join(dt)}"] if dt else []) + (
        ["from statistics import mean"] if kind in ("monitor", "review", "listing") else []) + [
        "from typing import Dict, List" + (", Optional" if kind in ("booking", "shop", "listing") else "")]
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
    elif kind == "booking":
        out.append(f'RESOURCE = {rule["resource_field"]!r}\nDAY = {rule["day_field"]!r}\nSLOT = {rule["slot_field"]!r}')
    elif kind == "shop":
        out.append(f'NAME = {rule["name_field"]!r}\nPRICE = {rule["price_field"]!r}\nSTOCK = {rule["stock_field"]!r}\n'
                   f'MOQ = {rule["moq_field"]!r}  # minimum order per product (None: any amount)\n'
                   f'CURRENCY = {rule["currency"]!r}\nTAX_PERCENT = {rule["tax_percent"]!r}\n'
                   f'BULK = {rule["bulk"]!r}  # bigger orders of one product get a discount\n'
                   f'DELIVERY_FEE = {rule["delivery_fee"]!r}\nFREE_DELIVERY_OVER = {rule["free_delivery_over"]!r}  # 0: never free\n'
                   f'LOW_STOCK_AT = {rule["low_stock_at"]!r}')
    elif kind == "split":
        out.append(f'PAYER = {rule["payer_field"]!r}\nAMOUNT = {rule["amount_field"]!r}\nCURRENCY = {rule["currency"]!r}')
    else:
        out.append(f'NAME = {rule["name_field"]!r}\nCATEGORY = {rule["category_field"]!r}')
    out.append(f"CHOICES: Dict[str, List[str]] = {choices!r}\n")
    if kind == "split":
        out.append("MEMBERS = CHOICES[PAYER]\n")
    out.append(f"{fn.upper()}: List[dict] = []\n")
    if kind == "shop":
        out.append("ORDERS: List[dict] = []\n")
    out.append(f"\nclass {model}(BaseModel):\n" + "\n".join(_model_line(f) for f in fields) + "\n")
    if kind == "tracker":
        out.append("\nclass StatusChange(BaseModel):\n    status: str\n")
    if kind == "shop":
        out.append('''
class CartLine(BaseModel):
    product_id: int
    qty: int = Field(ge=1, le=1000000)


class Cart(BaseModel):
    lines: List[CartLine] = Field(min_length=1, max_length=40)


class NewOrder(Cart):
    customer: str = Field(min_length=2, max_length=80)
    pincode: str = Field(pattern=r"^[1-9][0-9]{5}$")
''')
    if kind == "listing":
        out.append("\nclass Review(BaseModel):\n    stars: int = Field(ge=1, le=5)\n    comment: str = Field(default=\"\", max_length=200)\n")
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
    elif kind == "shop":
        out.append(f'''
def evaluate(record: dict) -> dict:
    """Stock label of a product."""
    if record[STOCK] <= 0:
        return {{"status": "out of stock"}}
    if record[STOCK] < LOW_STOCK_AT:
        return {{"status": "low stock"}}
    return {{"status": "in stock"}}


def _product(product_id: int) -> dict:
    for p in {R}:
        if p["id"] == product_id:
            return p
    raise HTTPException(status_code=404, detail=f"No product {{product_id}}")


def bulk_off(qty: int) -> float:
    """Discount (%) for this many units of one product."""
    off = 0
    for tier in BULK:
        if qty >= tier["min_qty"]:
            off = tier["off_percent"]
    return off


def price_cart(lines: List[dict]) -> dict:
    """Prices a cart on the server: bulk discount per product, then tax, then delivery."""
    wanted: Dict[int, int] = {{}}
    for line in lines:
        wanted[line["product_id"]] = wanted.get(line["product_id"], 0) + line["qty"]
    rows = []
    for product_id, qty in wanted.items():
        p = _product(product_id)
        if MOQ and qty < p[MOQ]:
            raise HTTPException(status_code=422, detail=f"Minimum order for {{p[NAME]}} is {{p[MOQ]}}.")
        if qty > p[STOCK]:
            raise HTTPException(status_code=409, detail=f"Only {{p[STOCK]}} left of {{p[NAME]}}.")
        gross = round(p[PRICE] * qty, 2)
        off = bulk_off(qty)
        discount = round(gross * off / 100, 2)
        rows.append({{"product_id": product_id, "name": p[NAME], "qty": qty, "price": p[PRICE], "gross": gross,
                     "off_percent": off, "discount": discount, "amount": round(gross - discount, 2)}})
    gross = round(sum(r["gross"] for r in rows), 2)
    discount = round(sum(r["discount"] for r in rows), 2)
    subtotal = round(gross - discount, 2)
    tax = round(subtotal * TAX_PERCENT / 100, 2)
    delivery = 0 if FREE_DELIVERY_OVER and subtotal >= FREE_DELIVERY_OVER else DELIVERY_FEE
    return {{"lines": rows, "items": sum(wanted.values()), "gross": gross, "discount": discount, "subtotal": subtotal,
            "tax_percent": TAX_PERCENT, "tax": tax, "delivery": delivery, "total": round(subtotal + tax + delivery, 2),
            "free_delivery_over": FREE_DELIVERY_OVER, "currency": CURRENCY}}


def _place(customer: str, pincode: str, lines: List[dict]) -> dict:
    quote = price_cart(lines)
    for row in quote["lines"]:
        p = _product(row["product_id"])
        p[STOCK] -= row["qty"]
        p.update(evaluate(p))
    order = {{"id": len(ORDERS) + 1, "customer": customer, "pincode": pincode,
             "placed": datetime.now().strftime("%Y-%m-%d %H:%M"), "status": "confirmed", **quote}}
    ORDERS.append(order)
    return order
''')
    elif kind == "split":
        out.append('''
def evaluate(record: dict) -> dict:
    """Every expense is shared equally by all members."""
    return {"share": round(record[AMOUNT] / len(MEMBERS), 2)}


def _balances() -> Dict[str, float]:
    total = sum(r[AMOUNT] for r in EXPENSES_PLACEHOLDER)
    share = total / len(MEMBERS)
    paid = {m: sum(r[AMOUNT] for r in EXPENSES_PLACEHOLDER if r[PAYER] == m) for m in MEMBERS}
    return {m: paid[m] - share for m in MEMBERS}
'''.replace("EXPENSES_PLACEHOLDER", R))
    elif kind == "listing":
        out.append('''
def evaluate(record: dict) -> dict:
    """Average of the star ratings (1 to 5)."""
    stars = list(record.get("ratings") or [])
    average = round(mean(stars), 1) if stars else 0
    label = "new" if not stars else "top rated" if average >= 4.5 and len(stars) >= 3 else "rated"
    return {"ratings": stars, "rating": average, "reviews": len(stars), "status": label}
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

{_list_route(d, path, fn, R)}


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
    elif kind == "booking":
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
    elif kind == "shop":
        out.append(f'''

@router.post("/quote")
def quote(cart: Cart):
    """Prices a cart without ordering it."""
    return price_cart(cart.model_dump()["lines"])


@router.post("/orders", status_code=201)
def place_order(order: NewOrder):
    data = order.model_dump()
    return _place(data["customer"], data["pincode"], data["lines"])


@router.get("/orders")
def list_orders():
    """Newest first."""
    return list(reversed(ORDERS))


for _order in {_shop_seed_orders(d)!r}:
    try:
        _place(**_order)
    except HTTPException:
        pass


@router.get("/summary")
def summary():
    return {{"count": len({R}), "orders": len(ORDERS), "revenue": round(sum(o["total"] for o in ORDERS), 2),
            "low_stock": sum(p["status"] != "in stock" for p in {R})}}
''')
    elif kind == "split":
        out.append(f'''

@router.get("/balances")
def balances():
    """What each member paid, their equal share and the difference (+ gets money back, - owes)."""
    total = sum(r[AMOUNT] for r in {R})
    share = round(total / len(MEMBERS), 2)
    rows = []
    for member, balance in _balances().items():
        paid = sum(r[AMOUNT] for r in {R} if r[PAYER] == member)
        rows.append({{"member": member, "paid": round(paid, 2), "share": share, "balance": round(balance, 2)}})
    return sorted(rows, key=lambda row: -row["balance"])


@router.get("/settle")
def settle():
    """Fewest simple payments that bring every balance to zero (largest debt pays largest credit first)."""
    owe = sorted(([m, -b] for m, b in _balances().items() if b < -0.005), key=lambda x: -x[1])
    get = sorted(([m, b] for m, b in _balances().items() if b > 0.005), key=lambda x: -x[1])
    payments, i, j = [], 0, 0
    while i < len(owe) and j < len(get):
        amount = min(owe[i][1], get[j][1])
        if amount > 0.005:
            payments.append({{"from": owe[i][0], "to": get[j][0], "amount": round(amount, 2)}})
        owe[i][1] -= amount
        get[j][1] -= amount
        if owe[i][1] <= 0.005:
            i += 1
        if get[j][1] <= 0.005:
            j += 1
    return payments


@router.get("/summary")
def summary():
    total = round(sum(r[AMOUNT] for r in {R}), 2)
    return {{"count": len({R}), "total": total, "per_person": round(total / len(MEMBERS), 2), "currency": CURRENCY}}
''')
    else:  # listing
        out.append(f'''

@router.post("/{path}/{{item_id}}/reviews", status_code=201)
def add_review(item_id: int, review: Review):
    for r in {R}:
        if r["id"] == item_id:
            r["ratings"].append(review.stars)
            r.update(evaluate(r))
            return r
    raise HTTPException(status_code=404, detail="Not found")


@router.get("/top")
def top():
    """Best rated first (at least one review)."""
    rated = [r for r in {R} if r["reviews"]]
    return sorted(rated, key=lambda r: (-r["rating"], -r["reviews"]))[:5]


@router.get("/summary")
def summary():
    stars = [s for r in {R} for s in r["ratings"]]
    return {{"count": len({R}), "reviews": len(stars), "average_rating": round(mean(stars), 1) if stars else 0}}
''')
    return "\n".join(out)


def _list_route(d: Dict[str, Any], path: str, fn: str, R: str) -> str:
    """GET route of the records (catalogue order for a shop, filters for a shop or a listing)."""
    kind, rule = d["kind"], d["rule"]
    if kind == "shop":
        return f'''
@router.get("/{path}")
def list_{fn}(category: Optional[str] = None, q: Optional[str] = None):
    """Catalogue order; optional category and search text."""
    rows = [p for p in {R} if not category or p[{rule["category_field"]!r}] == category]
    if q:
        rows = [p for p in rows if q.lower() in p[NAME].lower()]
    return rows
'''
    if kind == "listing":
        return f'''
@router.get("/{path}")
def list_{fn}(category: Optional[str] = None, q: Optional[str] = None, sort: str = "rating"):
    """Filtered by category and search text; best rated first (sort=newest for newest first)."""
    rows = [r for r in {R} if not category or r[CATEGORY] == category]
    if q:
        rows = [r for r in rows if q.lower() in r[NAME].lower()]
    if sort == "newest":
        return list(reversed(rows))
    return sorted(rows, key=lambda r: (-r["rating"], -r["reviews"], r["id"]))
'''
    return f'''
@router.get("/{path}")
def list_{fn}():
    """Newest first."""
    return list(reversed({R}))
'''


_BUYERS = [("Kottayam Auto Works", "686001"), ("Sharma Pump House", "141003"), ("Priya Menon", "560034"), ("Rahul Khanna", "411014")]


def _shop_seed_orders(d: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Two sample orders so the orders list and revenue are not empty (stock goes down by real code)."""
    rule, orders = d["rule"], []
    stock, moq = rule["stock_field"], rule["moq_field"]
    orderable = [(i + 1, row) for i, row in enumerate(d["seed"]) if row[stock] >= 2 * (row[moq] if moq else 1)]
    for n, (customer, pincode) in enumerate(_BUYERS[:2]):
        picks = orderable[n::2][:2]
        if picks:
            orders.append({"customer": customer, "pincode": pincode,
                           "lines": [{"product_id": pid, "qty": row[moq] if moq else 1} for pid, row in picks]})
    return orders


# ---------------------------------------------------------------- tests

def _valid_payload(d: Dict[str, Any]) -> Dict[str, Any]:
    row = {f["name"]: d["seed"][0][f["name"]] for f in d["fields"]}
    rule = d["rule"]
    if d["kind"] == "booking":
        row[rule["day_field"]] = "2031-03-14"
    if d["kind"] == "monitor":
        row[rule["group_field"]] = "Check group"
    if d["kind"] == "shop":
        stock = next(f for f in d["fields"] if f["name"] == rule["stock_field"])
        row[rule["stock_field"]] = int(min(stock["max"], 1000))
        if rule["moq_field"]:
            row[rule["moq_field"]] = 1
    return row


def _shop_quote(rule: Dict[str, Any], price: float, qty: int) -> Dict[str, Any]:
    """The same pricing as the generated price_cart(), for the expected numbers in the tests."""
    gross = round(price * qty, 2)
    off = 0
    for tier in rule["bulk"]:
        if qty >= tier["min_qty"]:
            off = tier["off_percent"]
    discount = round(gross * off / 100, 2)
    subtotal = round(gross - discount, 2)
    tax = round(subtotal * rule["tax_percent"] / 100, 2)
    free = rule["free_delivery_over"]
    delivery = 0 if free and subtotal >= free else rule["delivery_fee"]
    return {"discount": discount, "subtotal": subtotal, "tax": tax, "delivery": delivery, "total": round(subtotal + tax + delivery, 2)}


def _shop_stock_after_seed_orders(d: Dict[str, Any]) -> List[int]:
    stock = [row[d["rule"]["stock_field"]] for row in d["seed"]]
    for order in _shop_seed_orders(d):
        for line in order["lines"]:
            stock[line["product_id"] - 1] -= line["qty"]
    return stock


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
    path = "/api/" + _path(d)
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
    elif kind == "shop":
        out.append(_shop_tests(d, path))
    elif kind == "split":
        pf = rule["payer_field"]
        out.append(f'''

def test_balances_add_up_to_zero():
    rows = client.get("/api/balances").json()
    assert len(rows) == {len(rule["members"])}
    assert abs(sum(r["balance"] for r in rows)) < 0.05


def test_settle_up_clears_every_balance():
    client.post("{path}", json=VALID)
    left = {{r["member"]: r["balance"] for r in client.get("/api/balances").json()}}
    for pay in client.get("/api/settle").json():
        left[pay["from"]] += pay["amount"]
        left[pay["to"]] -= pay["amount"]
    assert all(abs(v) < 0.05 for v in left.values())


def test_payer_must_be_a_member():
    assert client.post("{path}", json=dict(VALID, **{{{pf!r}: "Someone else"}})).status_code == 422
''')
    elif kind == "listing":
        cat = rule["category_field"]
        other = next(f for f in d["fields"] if f["name"] == cat)["choices"][-1]
        out.append(f'''

def test_review_updates_the_rating():
    item = client.post("{path}", json=VALID).json()
    assert item["reviews"] == 0
    client.post(f"{path}/{{item['id']}}/reviews", json={{"stars": 5}})
    rated = client.post(f"{path}/{{item['id']}}/reviews", json={{"stars": 2, "comment": "Came late"}}).json()
    assert rated["reviews"] == 2 and rated["rating"] == 3.5


def test_bad_review_and_unknown_item():
    assert client.post("{path}/1/reviews", json={{"stars": 6}}).status_code == 422
    assert client.post("{path}/99999/reviews", json={{"stars": 4}}).status_code == 404


def test_filter_by_category():
    rows = client.get("{path}", params={{"category": {other!r}}}).json()
    assert all(r[{cat!r}] == {other!r} for r in rows)
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


def _shop_tests(d: Dict[str, Any], path: str) -> str:
    rule = d["rule"]
    price_f, stock_f, moq_f = rule["price_field"], rule["stock_field"], rule["moq_field"]
    left = _shop_stock_after_seed_orders(d)
    # The product with the most stock left; order enough for the first bulk discount when possible.
    i = max(range(len(left)), key=lambda k: left[k])
    row = d["seed"][i]
    least = row[moq_f] if moq_f else 1
    qty = max(least, rule["bulk"][0]["min_qty"]) if rule["bulk"] else least
    if qty > left[i]:
        qty = least
    out = []
    if left[i] >= qty:
        q = _shop_quote(rule, row[price_f], qty)
        out.append(f'''

def test_quote_applies_bulk_discount_tax_and_delivery():
    quote = client.post("/api/quote", json={{"lines": [{{"product_id": {i + 1}, "qty": {qty}}}]}}).json()
    assert quote["discount"] == {q["discount"]!r} and quote["subtotal"] == {q["subtotal"]!r}
    assert quote["tax"] == {q["tax"]!r} and quote["delivery"] == {q["delivery"]!r}
    assert quote["total"] == {q["total"]!r}
''')
    out.append(f'''

def test_order_reduces_stock_and_overselling_is_refused():
    product = client.post("{path}", json=dict(VALID, **{{{stock_f!r}: 30}})).json()
    order = client.post("/api/orders", json={{"customer": "Test Buyer", "pincode": "682001",
                                              "lines": [{{"product_id": product["id"], "qty": 20}}]}})
    assert order.status_code == 201
    stock = next(p for p in client.get("{path}").json() if p["id"] == product["id"])[{stock_f!r}]
    assert stock == 10
    again = client.post("/api/orders", json={{"customer": "Test Buyer", "pincode": "682001",
                                              "lines": [{{"product_id": product["id"], "qty": 11}}]}})
    assert again.status_code == 409


def test_bad_pincode_and_unknown_product():
    line = {{"product_id": 1, "qty": 1}}
    assert client.post("/api/orders", json={{"customer": "Test Buyer", "pincode": "12", "lines": [line]}}).status_code == 422
    assert client.post("/api/quote", json={{"lines": [{{"product_id": 99999, "qty": 1}}]}}).status_code == 404


def test_orders_are_listed_and_counted():
    before = client.get("/api/summary").json()["orders"]
    product = client.post("{path}", json=VALID).json()
    client.post("/api/orders", json={{"customer": "Test Buyer", "pincode": "682001", "lines": [{{"product_id": product["id"], "qty": 1}}]}})
    assert client.get("/api/summary").json()["orders"] == before + 1
    assert client.get("/api/orders").json()[0]["customer"] == "Test Buyer"
''')
    if moq_f:
        moq_max = next(f for f in d["fields"] if f["name"] == moq_f)["max"]
        if moq_max >= 5:
            out.append(f'''

def test_minimum_order_is_enforced():
    product = client.post("{path}", json=dict(VALID, **{{{moq_f!r}: 5}})).json()
    small = client.post("/api/quote", json={{"lines": [{{"product_id": product["id"], "qty": 4}}]}})
    assert small.status_code == 422
''')
    return "".join(out)


# ---------------------------------------------------------------- page

_STATS = {
    "monitor": lambda d: [("count", d["entity_plural"]), ("alerts", "Alerts"),
                          ("average", f"Average{' (' + d['rule']['unit'] + ')' if d['rule']['unit'] else ''}")],
    "review": lambda d: [("count", d["entity_plural"]), ("average", "Average score"), ("pass_rate", "Passing (%)")],
    "tracker": lambda d: [("count", d["entity_plural"]), ("open", "Still open"), ("done_percent", "Done (%)")],
    "booking": lambda d: [("count", d["entity_plural"]), ("today", "Booked today"), ("free_today", "Free slots today")],
    "split": lambda d: [("count", d["entity_plural"]), ("total", f"Total spent ({d['rule']['currency']})"),
                        ("per_person", f"Each person's share ({d['rule']['currency']})")],
    "listing": lambda d: [("count", d["entity_plural"]), ("reviews", "Reviews"), ("average_rating", "Average rating (out of 5)")],
}
_SIDE_TITLE = {"monitor": "By {group}", "review": "What we check", "tracker": "By status", "booking": "Free slots",
               "split": "Who owes whom", "listing": "Top rated"}

_JS_HELPERS = r"""
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
function money(v) { const n = Number(v); const d = Number.isInteger(n) ? 0 : 2; return (APP.currency || "") + n.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }); }
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
      if (f.type === "number") { input.step = f.integer ? "1" : "any"; input.min = f.min; input.max = f.max; }
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
"""

_JS_COMMON = r"""
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
    "split": r"""
async function side() {
  const [rows, pays] = await Promise.all([api("/api/balances"), api("/api/settle")]);
  const box = document.getElementById("side");
  box.replaceChildren();
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.balance)));
  for (const r of rows) {
    const row = el("div", "", "list-row");
    const head = el("div", "", "row spread");
    const gets = r.balance >= 0;
    head.append(el("strong", r.member), el("span", (gets ? "gets back " : "owes ") + money(Math.abs(r.balance)), "tag " + (gets ? "good" : "bad")));
    const bar = el("div", "", "bar" + (gets ? "" : " neg")); const fill = el("span"); fill.style.width = Math.round(100 * Math.abs(r.balance) / max) + "%"; bar.append(fill);
    row.append(head, el("div", "Paid " + money(r.paid) + ", share " + money(r.share), "muted"), bar);
    box.append(row);
  }
  box.append(el("h3", "Settle up"));
  if (!pays.length) box.append(el("p", "Everyone is even.", "muted"));
  for (const p of pays) {
    const row = el("div", "", "row spread list-row");
    row.append(el("span", p.from + " pays " + p.to), el("strong", money(p.amount)));
    box.append(row);
  }
}
APP.columns.push({ label: "Each pays", cell: (r) => el("span", money(r.share)) });
function latestText(r) { return "Added. Each person's share: " + money(r.share) + "."; }
""",
    "listing": r"""
async function side() {
  const rows = await api("/api/top");
  const box = document.getElementById("side");
  box.replaceChildren();
  if (!rows.length) box.append(el("p", "No reviews yet.", "muted"));
  for (const r of rows) {
    const row = el("div", "", "list-row");
    const head = el("div", "", "row spread");
    head.append(el("strong", r[APP.name]), el("span", r.rating + " / 5 (" + r.reviews + ")", "muted"));
    const bar = el("div", "", "bar"); const fill = el("span"); fill.style.width = Math.round(100 * r.rating / 5) + "%"; bar.append(fill);
    row.append(head, bar); box.append(row);
  }
}
function stars(r) {
  const wrap = el("span", "", "stars");
  const full = Math.round(r.rating);
  wrap.append(el("b", "★".repeat(full)), el("i", "★".repeat(5 - full)), el("br"), el("span", r.reviews ? r.rating + " (" + r.reviews + ") " : "no reviews ", "muted"));
  if (r.status !== "rated") wrap.append(tag(r.status));
  return wrap;
}
function ratePicker(r) {
  const s = document.createElement("select");
  s.append(el("option", "Rate"));
  for (const n of [5, 4, 3, 2, 1]) { const o = el("option", n + " star" + (n > 1 ? "s" : "")); o.value = n; s.append(o); }
  s.onchange = async () => { await api(APP.list + "/" + r.id + "/reviews", { method: "POST", body: JSON.stringify({ stars: Number(s.value) }) }); load(); };
  return s;
}
APP.columns.push({ label: "Rating", cell: stars }, { label: "Rate", cell: ratePicker });
function latestText(r) { return "Added. Rate it from the list."; }
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


def _mark(name: str) -> str:
    """Two letters for the square logo mark."""
    words = re.findall(r"[A-Za-z0-9]+", name or "")
    return ((words[0][0] + (words[1][0] if len(words) > 1 else words[0][1:2])) if words else "P").upper()


_JS_SHOP = r"""
const cart = {};
let products = [], category = "", search = "", sortBy = "";
const picks = {};
const TINTS = ["#2f3337", "#3d4a5c", "#5b3a29", "#2f4f3a", "#4a3b5c", "#6b2f2f"];
const SHAPE_WORDS = [["ring", /o-ring|ring\b|seal|gasket|washer/], ["wheel", /tyre|tire|wheel|castor/],
  ["device", /charger|earbud|earphone|phone|power bank|speaker|cable|laptop|watch/], ["hose", /hose|tube|pipe|wire/],
  ["shirt", /saree|kurta|shirt|stole|dress|t-shirt|jacket|sweater/], ["book", /book|edition|ncert|class \d/],
  ["glove", /glove/], ["belt", /belt|strip|band|tape/], ["mat", /\bmats?\b|floor|carpet|tile/], ["sheet", /sheet|pad|roll|board|panel|fabric|cloth/],
  ["bottle", /bottle|jar|oil|juice|honey|sauce|soap|shampoo|coffee|tea\b/], ["bag", /bag|pouch|sack|pepper|chilli|masala|spice|millet|rice|flour|dal\b/]];
const SHAPES = {
  ring: [["circle", { cx: 60, cy: 40, r: 24, fill: "none", stroke: "C", "stroke-width": 11 }], ["circle", { cx: 60, cy: 40, r: 26, class: "hl", "stroke-width": 1.5 }]],
  wheel: [["circle", { cx: 60, cy: 40, r: 27, fill: "none", stroke: "C", "stroke-width": 12 }], ["circle", { cx: 60, cy: 40, r: 30, class: "hl", "stroke-width": 3, "stroke-dasharray": "3 5" }], ["circle", { cx: 60, cy: 40, r: 9, class: "acc" }]],
  hose: [["path", { d: "M16 60 C16 20 54 20 54 40 S92 62 92 30", fill: "none", stroke: "C", "stroke-width": 10, "stroke-linecap": "round" }], ["rect", { x: 86, y: 14, width: 12, height: 12, rx: 2, class: "acc" }]],
  glove: [["rect", { x: 44, y: 36, width: 36, height: 30, rx: 8, fill: "C" }], ["rect", { x: 44, y: 14, width: 8, height: 30, rx: 4, fill: "C" }], ["rect", { x: 53, y: 9, width: 8, height: 32, rx: 4, fill: "C" }], ["rect", { x: 62, y: 10, width: 8, height: 32, rx: 4, fill: "C" }], ["rect", { x: 71, y: 15, width: 8, height: 28, rx: 4, fill: "C" }], ["rect", { x: 28, y: 40, width: 22, height: 9, rx: 4.5, fill: "C", transform: "rotate(-35 39 44)" }], ["rect", { x: 44, y: 62, width: 36, height: 9, rx: 2, class: "acc" }]],
  belt: [["rect", { x: 16, y: 22, width: 88, height: 36, rx: 18, fill: "none", stroke: "C", "stroke-width": 9 }], ["rect", { x: 16, y: 22, width: 88, height: 36, rx: 18, class: "hl", "stroke-width": 2, "stroke-dasharray": "4 6" }]],
  mat: [["rect", { x: 20, y: 18, width: 80, height: 46, rx: 3, fill: "C" }], ["path", { d: "M32 18v46M44 18v46M56 18v46M68 18v46M80 18v46M92 18v46M20 30h80M20 42h80M20 54h80", class: "hl", "stroke-width": 1.5 }]],
  sheet: [["polygon", { points: "20,40 76,40 100,24 44,24", fill: "C", opacity: 0.45 }], ["polygon", { points: "20,48 76,48 100,32 44,32", fill: "C", opacity: 0.7 }], ["polygon", { points: "20,58 76,58 100,42 44,42", fill: "C" }], ["path", { d: "M20 58h56l24-16", class: "hl", "stroke-width": 1.5 }]],
  bottle: [["rect", { x: 48, y: 24, width: 24, height: 46, rx: 6, fill: "C" }], ["rect", { x: 54, y: 11, width: 12, height: 14, rx: 2, class: "acc" }], ["rect", { x: 48, y: 40, width: 24, height: 14, fill: "#fff", opacity: 0.3 }]],
  bag: [["path", { d: "M30 30h60l-6 40H36z", fill: "C" }], ["path", { d: "M48 30v-6a12 12 0 0 1 24 0v6", fill: "none", stroke: "C", "stroke-width": 4 }], ["rect", { x: 30, y: 30, width: 60, height: 6, class: "acc" }]],
  shirt: [["path", { d: "M44 14l10-4q6 8 12 0l10 4 18 14-8 11-8-6v38H42V33l-8 6-8-11z", fill: "C" }], ["path", { d: "M54 10q6 10 12 0", class: "hl", "stroke-width": 2 }], ["rect", { x: 66, y: 36, width: 9, height: 8, rx: 1, class: "acc" }]],
  book: [["rect", { x: 36, y: 12, width: 50, height: 58, rx: 3, fill: "C" }], ["rect", { x: 36, y: 12, width: 8, height: 58, class: "acc" }], ["path", { d: "M52 28h26M52 36h26M52 44h18", class: "hl", "stroke-width": 2 }]],
  device: [["rect", { x: 44, y: 8, width: 32, height: 64, rx: 6, fill: "C" }], ["rect", { x: 48, y: 15, width: 24, height: 46, rx: 2, fill: "#fff", opacity: 0.22 }], ["circle", { cx: 60, cy: 66, r: 2.5, class: "acc" }]],
  box: [["polygon", { points: "60,12 94,26 60,40 26,26", class: "acc" }], ["polygon", { points: "26,26 60,40 60,70 26,56", fill: "C" }], ["polygon", { points: "60,40 94,26 94,56 60,70", fill: "C", opacity: 0.8 }]],
};
function svg(name, attrs) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
}
function thumb(p) {
  const text = (p[APP.name] + " " + p[APP.category]).toLowerCase();
  const shape = (SHAPE_WORDS.find(([, re]) => re.test(text)) || ["box"])[0];
  const first = APP.filters[0];
  const tint = TINTS[first ? Math.max(0, first.choices.indexOf(p[first.name])) % TINTS.length : 0];
  const box = svg("svg", { viewBox: "0 0 120 80", "aria-hidden": "true" });
  for (const [name, a] of SHAPES[shape]) {
    const attrs = Object.assign({}, a);
    for (const k of ["fill", "stroke"]) if (attrs[k] === "C") attrs[k] = tint;
    box.append(svg(name, attrs));
  }
  return box;
}
function unitOf(p) { return APP.unit_field ? p[APP.unit_field] : APP.unit; }
function stockTag(p) {
  const n = p[APP.stock];
  if (n <= 0) return el("span", "Out of stock", "tag bad");
  return el("span", (p.status === "low stock" ? "Only " + n + " left" : "In stock: " + n), "tag " + (p.status === "low stock" ? "warn" : "good"));
}
function cartLines() { return Object.keys(cart).map((id) => ({ product_id: Number(id), qty: cart[id] })); }
function visible() {
  const rows = products.filter((p) => (!category || p[APP.category] === category)
    && (!search || p[APP.name].toLowerCase().includes(search))
    && APP.filters.every((f) => !picks[f.name] || p[f.name] === picks[f.name]));
  if (sortBy === "low") rows.sort((a, b) => a[APP.price] - b[APP.price]);
  if (sortBy === "high") rows.sort((a, b) => b[APP.price] - a[APP.price]);
  if (sortBy === "name") rows.sort((a, b) => a[APP.name].localeCompare(b[APP.name]));
  return rows;
}
function renderTabs() {
  const tabs = document.getElementById("cats");
  tabs.replaceChildren();
  for (const c of [""].concat(APP.categories)) {
    const n = products.filter((p) => !c || p[APP.category] === c).length;
    const b = el("button", (c || "All") + " (" + n + ")", c === category ? "on" : "");
    b.type = "button";
    b.onclick = () => { category = c; renderTabs(); renderProducts(); };
    tabs.append(b);
  }
}
function renderFilters() {
  const box = document.getElementById("filters");
  for (const f of APP.filters) {
    const s = document.createElement("select");
    s.append(el("option", f.label + ": all"));
    s.options[0].value = "";
    for (const c of f.choices) s.append(el("option", c));
    s.onchange = () => { picks[f.name] = s.value; renderProducts(); };
    box.append(s);
  }
  const sort = document.createElement("select");
  for (const [v, t] of [["", "Sort: catalogue"], ["low", "Price: low to high"], ["high", "Price: high to low"], ["name", "Name: A to Z"]]) { const o = el("option", t); o.value = v; sort.append(o); }
  sort.onchange = () => { sortBy = sort.value; renderProducts(); };
  box.append(sort, el("span", "", "muted count"));
}
function renderProducts() {
  const rows = visible();
  document.querySelector("#filters .count").textContent = rows.length + " of " + products.length + " " + APP.entity_plural.toLowerCase();
  const grid = document.getElementById("products");
  grid.replaceChildren();
  if (!rows.length) grid.append(el("p", "Nothing matches. Clear the search or pick another category.", "empty"));
  for (const p of rows) {
    const card = el("article", "", "product");
    const t = el("div", "", "thumb");
    t.append(thumb(p));
    const body = el("div", "", "p-body");
    body.append(el("div", p[APP.category], "muted"), el("h3", p[APP.name]));
    const specs = APP.specs.map((f) => f.label + ": " + p[f.name]).join(" · ");
    if (specs) body.append(el("div", specs, "muted"));
    const price = el("div", "", "price");
    price.append(el("strong", money(p[APP.price])), el("span", " / " + unitOf(p), "muted"));
    const stock = el("div", "", "row");
    stock.append(stockTag(p));
    const least = APP.moq ? p[APP.moq] : 1;
    if (APP.moq && least > 1) stock.append(el("span", "Min. order " + least, "muted"));
    const buy = el("div", "", "buy");
    const qty = document.createElement("input");
    Object.assign(qty, { type: "number", min: least, step: 1, value: least, className: "qty" });
    qty.setAttribute("aria-label", "Quantity");
    const add = el("button", p[APP.stock] > 0 ? "Add to cart" : "Sold out", "btn primary");
    add.type = "button";
    add.disabled = p[APP.stock] <= 0;
    add.onclick = () => { const n = Math.floor(Number(qty.value)); if (n > 0) { cart[p.id] = (cart[p.id] || 0) + n; renderCart(); } };
    buy.append(qty, add);
    body.append(price, stock, buy);
    card.append(t, body);
    grid.append(card);
  }
}
let quoteSeq = 0;
async function renderCart() {
  const ids = Object.keys(cart);
  document.getElementById("cart-count").textContent = ids.reduce((n, id) => n + cart[id], 0);
  const lines = document.getElementById("cart-lines");
  const totals = document.getElementById("totals");
  const error = document.getElementById("cart-error");
  lines.replaceChildren();
  totals.replaceChildren();
  error.textContent = "";
  document.getElementById("checkout").hidden = !ids.length;
  if (!ids.length) { lines.append(el("p", "Your cart is empty. Add products from the list.", "muted")); return; }
  for (const id of ids) {
    const p = products.find((x) => x.id === Number(id));
    if (!p) continue;
    const row = el("div", "", "cart-line");
    const name = el("div");
    name.append(el("strong", p[APP.name]), el("div", money(p[APP.price]) + " / " + unitOf(p), "muted"));
    const amount = el("div", "", "amount");
    amount.id = "amount-" + id;
    const controls = el("div", "", "row");
    const qty = document.createElement("input");
    Object.assign(qty, { type: "number", min: 1, step: 1, value: cart[id], className: "qty" });
    qty.setAttribute("aria-label", "Quantity");
    qty.onchange = () => { const n = Math.floor(Number(qty.value)); if (n > 0) cart[id] = n; else delete cart[id]; renderCart(); };
    const remove = el("button", "Remove", "btn small");
    remove.type = "button";
    remove.onclick = () => { delete cart[id]; renderCart(); };
    controls.append(qty, remove);
    row.append(name, amount, controls);
    lines.append(row);
  }
  const seq = ++quoteSeq;
  try {
    const q = await api("/api/quote", { method: "POST", body: JSON.stringify({ lines: cartLines() }) });
    if (seq !== quoteSeq) return;
    for (const l of q.lines) {
      const a = document.getElementById("amount-" + l.product_id);
      if (!a) continue;
      a.append(el("strong", money(l.amount)));
      if (l.off_percent) a.append(el("div", l.off_percent + "% bulk off", "save"));
    }
    const add = (label, value, cls) => { const r = el("div", "", "total-row " + (cls || "")); r.append(el("span", label), el("span", value)); totals.append(r); };
    add("Items (" + q.items + ")", money(q.gross));
    if (q.discount) add("Bulk discount", "- " + money(q.discount), "save");
    add("Subtotal", money(q.subtotal));
    add(APP.tax_label + " " + q.tax_percent + "%", money(q.tax));
    add("Delivery", q.delivery ? money(q.delivery) : "Free");
    add("Total", money(q.total), "grand");
    if (q.free_delivery_over && q.delivery) totals.append(el("p", "Add " + money(q.free_delivery_over - q.subtotal) + " more for free delivery.", "muted"));
  } catch (err) {
    if (seq === quoteSeq) error.textContent = err.message;
  }
}
async function loadOrders() {
  const rows = await api("/api/orders");
  const body = document.getElementById("orders");
  body.replaceChildren();
  if (!rows.length) { const tr = el("tr"); const td = el("td", "No orders yet.", "empty"); td.colSpan = 6; tr.append(td); body.append(tr); }
  for (const o of rows) {
    const tr = el("tr");
    for (const v of ["#" + o.id, o.customer, o.pincode, o.items, money(o.total), o.placed]) tr.append(el("td", String(v)));
    body.append(tr);
  }
}
async function refresh() {
  const [rows, summary] = await Promise.all([api(APP.list), api("/api/summary")]);
  products = rows;
  document.getElementById("stat-count").textContent = summary.count;
  document.getElementById("stat-orders").textContent = summary.orders;
  document.getElementById("stat-revenue").textContent = money(summary.revenue);
  document.getElementById("stat-low_stock").textContent = summary.low_stock;
  renderTabs();
  renderProducts();
  renderCart();
  loadOrders();
}
function facts() {
  const box = document.getElementById("facts");
  const items = [];
  if (APP.bulk.length) items.push(["Bulk discount", APP.bulk.map((t) => t.off_percent + "% off from " + t.min_qty + " units").join(", ")]);
  items.push([APP.tax_label, APP.tax_percent + "% on the subtotal"]);
  items.push(["Delivery", APP.free_over ? money(APP.delivery_fee) + ", free over " + money(APP.free_over) : money(APP.delivery_fee) + " per order"]);
  items.push(["Stock", APP.moq ? "Live, with a minimum order per product" : "Live, reduced on every order"]);
  for (const [b, t] of items) { const f = el("div", "", "fact"); f.append(el("b", b), el("span", t)); box.append(f); }
}
document.getElementById("search").oninput = (e) => { search = e.target.value.trim().toLowerCase(); renderProducts(); };
document.getElementById("checkout").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  try {
    const order = await api("/api/orders", { method: "POST", body: JSON.stringify({ customer: f.customer.value, pincode: f.pincode.value, lines: cartLines() }) });
    for (const id of Object.keys(cart)) delete cart[id];
    e.target.reset();
    await refresh();
    document.getElementById("placed").textContent = "Order #" + order.id + " placed: " + money(order.total) + ". Stock updated.";
  } catch (err) { document.getElementById("cart-error").textContent = err.message; }
};
document.getElementById("form").onsubmit = async (e) => {
  e.preventDefault();
  const error = document.getElementById("error");
  try {
    const p = await api(APP.list, { method: "POST", body: JSON.stringify(readForm()) });
    error.textContent = "";
    document.getElementById("latest").textContent = "Added " + p[APP.name] + " to the catalogue.";
    refresh();
  } catch (err) { error.textContent = err.message; }
};
buildForm();
renderFilters();
facts();
refresh();
"""


def _shop_page(d: Dict[str, Any]) -> str:
    rule, e = d["rule"], html.escape
    named = {rule["name_field"], rule["category_field"], rule["price_field"], rule["stock_field"], rule["moq_field"], rule["unit_field"]}
    fields = []
    for f in d["fields"]:
        entry = {"name": f["name"], "label": f["label"], "type": f["type"]}
        if f["type"] == "choice":
            entry["choices"] = f["choices"]
        if f["type"] == "number":
            entry.update(min=f["min"], max=f["max"], integer=bool(f.get("integer")))
        fields.append(entry)
    category = next(f for f in d["fields"] if f["name"] == rule["category_field"])
    app = {"list": "/api/products", "fields": fields, "action": d["action"], "entity_plural": d["entity_plural"],
           "name": rule["name_field"], "category": rule["category_field"], "categories": category["choices"],
           "price": rule["price_field"], "stock": rule["stock_field"], "moq": rule["moq_field"], "unit_field": rule["unit_field"],
           "unit": rule["unit"], "currency": rule["currency"], "tax_label": "GST" if rule["currency"] == "₹" else "Tax",
           "tax_percent": rule["tax_percent"], "bulk": rule["bulk"], "delivery_fee": rule["delivery_fee"],
           "free_over": rule["free_delivery_over"],
           "filters": [{"name": f["name"], "label": f["label"], "choices": f["choices"]}
                       for f in d["fields"] if f["type"] == "choice" and f["name"] not in named],
           "specs": [{"name": f["name"], "label": f["label"]} for f in d["fields"]
                     if f["name"] not in named and f["type"] in ("number", "text")]}
    config = json.dumps(app, indent=1, ensure_ascii=False).replace("</", "<\\/")
    look = d.get("look") or {"theme": "orange", "header": "dark"}
    stats = [("count", d["entity_plural"]), ("orders", "Orders"), ("revenue", "Revenue"), ("low_stock", "Low or out of stock")]
    stat_cards = "\n".join(f'    <div class="card"><div class="muted">{e(label)}</div><div class="stat" id="stat-{key}">0</div></div>'
                           for key, label in stats)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(d["app_name"])}</title>
<link rel="stylesheet" href="/static/base.css">
</head>
<body data-theme="{look["theme"]}" data-layout="store" data-header="{look["header"]}">
<header class="top store-top"><div class="wrap">
  <span class="brand"><span class="mark">{e(_mark(d["app_name"]))}</span>{e(d["app_name"])}</span>
  <input id="search" type="search" placeholder="Search {e(d["entity_plural"].lower())}" aria-label="Search">
  <a class="btn cart-btn" href="#cart">Cart: <b id="cart-count">0</b></a>
</div></header>
<section class="hero"><div class="wrap">
  <div><h1>{e(d["app_name"])}</h1><p class="muted">{e(d["tagline"])}</p></div>
  <div class="facts" id="facts"></div>
</div></section>
<main class="wrap">
  <div class="grid stats">
{stat_cards}
  </div>
  <div class="store">
    <section>
      <div class="tabs" id="cats"></div>
      <div class="row filters" id="filters"></div>
      <div class="products" id="products"></div>
    </section>
    <aside class="card cart" id="cart">
      <h2>Your cart</h2>
      <div id="cart-lines"></div>
      <div id="totals"></div>
      <form id="checkout" hidden>
        <label class="field">Name or company<input name="customer" required minlength="2" maxlength="80"></label>
        <label class="field">Delivery pincode<input name="pincode" required pattern="[1-9][0-9]{{5}}" inputmode="numeric" title="6-digit pincode"></label>
        <button class="btn primary wide" type="submit">Place order</button>
      </form>
      <p class="error" id="cart-error"></p>
      <p class="ok" id="placed"></p>
    </aside>
  </div>
  <div class="cols">
    <div class="card"><h2>Recent orders</h2><div style="overflow-x:auto"><table>
      <thead><tr><th>Order</th><th>Customer</th><th>Pincode</th><th>Units</th><th>Total</th><th>Placed</th></tr></thead>
      <tbody id="orders"></tbody></table></div></div>
    <div class="card"><h2>Seller: {e(d["action"].lower())}</h2><form id="form" class="form-inline"></form>
      <p class="error" id="error"></p><p class="muted" id="latest"></p></div>
  </div>
</main>
<footer class="site-foot wrap">Prototype. Prices, discounts, {e(app["tax_label"])} and stock are worked out on the server.</footer>
<script>
const APP = {config};
{_JS_HELPERS.strip()}
{_JS_SHOP.strip()}
</script>
</body>
</html>
"""


def _page(d: Dict[str, Any]) -> str:
    kind, rule = d["kind"], d["rule"]
    if kind == "shop":
        return _shop_page(d)
    path = "/api/" + _path(d)
    fields = []
    for f in d["fields"]:
        entry = {"name": f["name"], "label": f["label"], "type": f["type"]}
        if f["type"] == "choice":
            entry["choices"] = f["choices"]
        if f["type"] == "number":
            entry.update(min=f["min"], max=f["max"], integer=bool(f.get("integer")))
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
    elif kind == "listing":
        tones = {"top rated": "good", "rated": "", "new": "warn"}
    elif kind == "split":
        tones = {}
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
    if kind == "split":
        app["currency"] = rule["currency"]
    if kind == "listing":
        app["name"] = rule["name_field"]
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
{_JS_HELPERS.strip()}
{_JS_KIND[kind].strip()}
{_JS_COMMON.strip()}
</script>
</body>
</html>
"""


def render(design: Dict[str, Any]) -> Dict[str, str]:
    """The three idea-specific files for a normalised design."""
    return {"features.py": _features(design), "static/index.html": _page(design), "test_features.py": _tests(design)}
