# -*- coding: utf-8 -*-
"""Gemini rewrites the WORDING. It never decides what is true.

WHAT THE MODEL IS FOR, AND WHAT IT IS NOT FOR
  alerts.py has already decided what is true and what matters. The model's whole job is wording:
  turn a measured finding into a sentence a mineral owner reads once and understands. It is a
  writer here, not an analyst.

  That boundary is enforced, not requested. Asking a model nicely not to invent a figure works
  nearly every time, and "nearly" is the problem on a product that sells data accuracy - one
  invented production month is worse than a hundred plain sentences.

THE GUARD
  Every numeric token in the output must already appear in the finding it was rewriting. A model
  that rounds 12.2% to 12% fails and is replaced by the measured prose - deliberately strict,
  because "close enough" is exactly how a figure drifts.

  It cannot invent a source either: the source line is never asked for. It is carried across
  from the alert afterwards, so whatever comes back, the attribution under each row still names
  the filing the number actually came from.

BUDGET IS PER PLAN
  free     0 alerts reworded. Measured prose, and the footer says so.
  pro      the top 3 by rank.
  premium  all of them.
  One HTTP call per panel either way - the alerts go in one batched prompt, never one request
  each. A panel of nine alerts costs one call, not nine.
"""
import json
import re
import ssl
import urllib.error
import urllib.request

_NUM = re.compile(r"\d[\d,]*\.?\d*")


def _tokens(text):
    """Every number in a string, normalised so 1,234 and 1234 compare equal."""
    out = set()
    for raw in _NUM.findall(text or ""):
        t = raw.replace(",", "").rstrip(".")
        if not t:
            continue
        out.add(t)
        if t.endswith(".0"):
            out.add(t[:-2])
        if "." in t:
            out.add(t.split(".")[0])
    return out


def _allowed(alert):
    ok = set()
    for field in ("title", "body", "source", "why"):
        ok |= _tokens(alert.get(field, ""))
    ev = alert.get("evidence") or {}
    for row in ev.get("rows", []):
        ok |= _tokens(str(row.get("v", ""))) | _tokens(str(row.get("note", "")))
    ok |= _tokens(ev.get("method", "")) | _tokens(ev.get("why", ""))
    # Rounding a supplied figure is the one liberty allowed: 12.24 -> 12.2 -> 12.
    for t in list(ok):
        if "." in t:
            head, tail = t.split(".", 1)
            ok.add(head)
            if len(tail) > 1:
                try:
                    ok.add("%.1f" % float(t))
                except ValueError:
                    pass
    ok |= {str(n) for n in range(0, 13)}
    return ok


def _ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _prompt(alerts, facts):
    own = facts["owner"]["identity"]
    lines = [
        "You are writing the Alerts inbox on a Texas mineral-owner portal.",
        "The reader owns mineral rights. They are not an engineer and not a trader.",
        "Plain English, no jargon, no hedging, no marketing tone, no exclamation marks.",
        "",
        "OWNER: %s, record #%s" % (own.get("ownername", ""), own.get("ownernumber", "")),
        "PRODUCTION AS OF: %s. This is the newest month reported to the state, not today."
        % facts["window"]["as_of_label"],
        "",
        "Rewrite each alert below. Keep the order. Do not merge, drop, add or reorder them.",
        "",
        "HARD RULES",
        "  1. Use ONLY the numbers given for that alert. Do not compute, round, combine or infer",
        "     any new figure. A number not written in the alert may not appear in your output.",
        "  2. No unsupported adjectives: no 'strong', 'significant', 'concerning', 'exciting'.",
        "  3. Never imply the owner was underpaid, owed money, or should buy, sell or lease.",
        "  4. 'title' is at most 12 words and states the fact. 'body' is 1-2 sentences, at most",
        "     45 words, and explains what it means for the reader.",
        "  5. SENTENCE CASE, never Title Case. Capitalise the first word and proper nouns only.",
        "     'Payment check worth running on 102 leases' - NOT 'Payment Check On 102 Leases'.",
        "     Lease and operator names keep the capitalisation they are given.",
        "  6. Every alert covers the WHOLE portfolio. Keep the lease count in the title where one",
        "     is given - never rewrite 'across 102 of your 103 leases' down to a single lease.",
        "  7. If nothing moved, say so plainly. A quiet week is a real finding.",
        "",
        "OUTPUT",
        "  A JSON array of exactly %d objects, in the given order, each with keys \"title\" and"
        % len(alerts),
        "  \"body\". No markdown, no code fence, no commentary. JSON only.",
        "",
        "ALERTS",
    ]
    for i, a in enumerate(alerts, 1):
        lines.append("%d. [%s / %s] %s | %s" % (i, a["category"], a["delivery_class"],
                                                a["title"], a["body"]))
    return "\n".join(lines)


def _call(prompt, cfg):
    ai = cfg["ai"]
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": ai.get("temperature", 0.35),
            "maxOutputTokens": ai.get("max_output_tokens", 1600),
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        ai["endpoint"] % ai["model"],
        data=json.dumps(body).encode("utf-8"),
        headers={"x-goog-api-key": ai["api_key"], "Content-Type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=ai.get("timeout_seconds", 45),
                                 context=_ctx()).read().decode("utf-8")
    d = json.loads(raw)
    cand = (d.get("candidates") or [None])[0]
    if not cand:
        raise ValueError("no candidate in response: %s" % str(d)[:200])
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    usage = d.get("usageMetadata", {})
    return text, usage


def _extract(text):
    """The first balanced [...] in the output. Survives a stray preamble or code fence."""
    start = text.find("[")
    if start < 0:
        raise ValueError("no JSON array in model output")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unbalanced JSON array in model output")


def rewrite(alerts, facts, cfg, plan, log=None):
    """-> (alerts, writer, note, usage). Never raises; falls back to the measured prose."""
    def say(msg, state="done"):
        if log:
            log(msg, state)

    ai = cfg["ai"]
    budget = ai.get("plan_budget", {}).get(plan, 0)
    if not ai.get("enabled", True) or budget <= 0 or not ai.get("api_key"):
        why = ("the %s plan uses measured wording" % plan) if budget <= 0 else "AI disabled"
        return alerts, "measured", why, {}

    target = alerts[:budget]
    if not target:
        return alerts, "measured", "nothing to rewrite", {}

    try:
        say("wording %d of %d alert(s) with %s (%s plan)"
            % (len(target), len(alerts), ai["model"], plan))
        text, usage = _call(_prompt(target, facts), cfg)
        rows = _extract(text)
        if not isinstance(rows, list) or len(rows) != len(target):
            raise ValueError("model returned %s rows, expected %d"
                             % (len(rows) if isinstance(rows, list) else "?", len(target)))

        rewritten = 0
        for a, row in zip(target, rows):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title", "")).strip()
            body = str(row.get("body", "")).strip()
            if not title or not body:
                continue
            if len(title.split()) > 14 or len(body.split()) > 55:
                continue
            invented = _tokens(title + " " + body) - _allowed(a)
            if invented:
                say("kept measured wording on '%s' - it invented %s"
                    % (a["id"], ", ".join(sorted(invented)[:3])), "warn")
                continue
            a["title"], a["body"], a["reworded"] = title, body, True
            rewritten += 1

        say("%d alert(s) reworded, %d token(s)" % (rewritten, usage.get("totalTokenCount", 0)))
        return alerts, ("ai" if rewritten else "measured"), \
            ("%d of %d reworded" % (rewritten, len(alerts))), usage

    except urllib.error.HTTPError as exc:
        note = "AI HTTP %s" % exc.code
    except Exception as exc:
        note = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    say("AI unavailable - %s" % note, "warn")
    return alerts, "measured", note, {}
