# -*- coding: utf-8 -*-
"""Local server for the Mineral View owner Alerts route.

    python server.py            then open http://127.0.0.1:8746

Serves web/alerts.html - the redesign build's own owner portal, shell intact - and the live
alerts that bind.js drops into its app-alerts route.

Standard library only, apart from pymongo. START.bat has to work on a machine where nothing has
been set up, and every dependency is one more thing that can be missing at the moment someone is
trying to look at their alerts.

THE OWNER IS LOCKED. There is no record picker and no owner parameter: this serves Brown Jon S's
alerts, built from every one of their claimed leases. A dropdown of 225 other people's records is
not part of the product, and `ownernumber` is a county key that 30% of the roll shares - so the
owner is resolved by number AND name, once, from config.

A build is a JOB, not a request. Reading six sources takes about twenty seconds; a single
blocking POST would sit behind a browser timeout with sample rows still on screen looking live.
The job runs on a thread, the page polls it, and each source appears as it lands.

The alerts are PUBLISHED AS SOON AS THEY ARE MEASURED. The model only rewrites wording, so
holding the page back for it would mean seconds of spinner over an answer that already existed.
"""
import datetime
import json
import os
import sys
import threading
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mv import alerts as alerts_mod          # noqa: E402
from mv import collect as collector          # noqa: E402
from mv import db, owner as owner_mod, summarize   # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")
PAGE = "alerts.html"

JOBS, JOBS_LOCK = {}, threading.Lock()

# Finished panels, keyed by plan. Deliberately in-memory: production posts monthly and prices
# move by the minute, so a cached panel is safe for a few minutes and wrong for a week.
# Restarting clears it, which is the right expiry for a tool left open all day. The page labels
# a cached panel rather than serving it as fresh.
CACHE, CACHE_LOCK = {}, threading.Lock()

# The name -> owner-records resolution, cached for the process. It depends only on (name, year),
# neither of which can change while the server runs, and the record-refresh alert needs the
# count. Measured at ~6s a call against the owner roll.
_RECORDS, _RECORDS_LOCK = {}, threading.Lock()

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8", ".json": "application/json",
        ".svg": "image/svg+xml", ".ico": "image/x-icon", ".png": "image/png",
        ".jpg": "image/jpeg", ".webp": "image/webp", ".woff2": "font/woff2"}


def _jsonable(o):
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    return str(o)


def records(cfg):
    key = (cfg["owner"]["name"], cfg["owner"]["year"])
    with _RECORDS_LOCK:
        hit = _RECORDS.get(key)
    if hit is None:
        hit = owner_mod.resolve_records(db.coll("owners"), key[0], key[1])
        with _RECORDS_LOCK:
            _RECORDS[key] = hit
    return hit


def _new_job():
    jid = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[jid] = {"id": jid, "state": "running", "steps": [], "result": None, "error": None}
    return jid


def _step(jid, text, state="done"):
    with JOBS_LOCK:
        j = JOBS.get(jid)
        if j is not None:
            j["steps"].append({"text": text, "state": state})


def _publish(jid, payload):
    with JOBS_LOCK:
        j = JOBS.get(jid)
        if j is not None:
            j["result"] = payload


def _payload(facts, alist, plan, writer, note, usage, cfg, cached=False, pending=False):
    own = facts["owner"]
    c = alerts_mod.counts(alist)
    rad, prob, prod = facts["radius"], facts["probability"], facts["production"]
    return {
        "owner": {
            "ownernumber": own["identity"]["ownernumber"],
            "ownername": own["identity"].get("ownername", ""),
            "year": own["year"],
            "lease_count": own["lease_count"],
            "county_count": own["county_count"],
            "counties": own["counties"],
            "appraised_total": own["appraised_total"],
            "interest_total": own["interest_total"],
        },
        "watch": {
            "leases": own["lease_count"],
            "counties": own["county_count"],
            "adjacent": rad["adjacent_count"],
            "permits": rad["permit_count"],
            "production": prod["filings_read"],
            "producing": prod["producing_leases"],
            "modelled": prob["count"],
            "alerts": c["all"],
            "action": c["action"],
        },
        "counts": c,
        "alerts": alist,
        "prices": facts["prices"],
        "as_of_label": prod["as_of_label"],
        "as_of": prod["as_of"],
        "built_at": facts["window"]["built_at"],
        "today": facts["window"]["today"],
        "plan": plan,
        "writer": writer,
        "writer_note": note,
        "model": cfg["ai"]["model"],
        "usage": usage,
        "cached": cached,
        "pending_model": pending,
        "name_matches": facts.get("name_matches", 0),
        "name_counties": facts.get("name_counties", 0),
    }


def _run(jid, plan, fresh):
    try:
        cfg = db.config()
        ownernumber = cfg["owner"]["default_ownernumber"]

        if not fresh:
            with CACHE_LOCK:
                hit = CACHE.get(plan)
            if hit:
                _step(jid, "served from this session's cache")
                out = dict(hit)
                out["cached"] = True
                _publish(jid, out)
                with JOBS_LOCK:
                    JOBS[jid]["state"] = "done"
                return

        ok, msg = db.ping()
        if not ok:
            raise RuntimeError(msg)
        _step(jid, "MongoDB reachable")

        facts = collector.collect(cfg, ownernumber,
                                  log=lambda m, s="done": _step(jid, m, s))

        recs = records(cfg)
        facts["name_matches"] = max(0, len(recs) - 1)
        facts["name_counties"] = len({c for r in recs for c in r["counties"]})
        _step(jid, "name check: %d other record(s) share this name and are excluded"
              % facts["name_matches"])

        alist = alerts_mod.build(facts, cfg)
        _step(jid, "%d alert(s) measured across all %d lease(s)"
              % (len(alist), facts["owner"]["lease_count"]))

        _publish(jid, _payload(facts, alist, plan, "measured",
                               "the model is rewriting these now", {}, cfg, pending=True))

        alist, writer, note, usage = summarize.rewrite(
            alist, facts, cfg, plan, log=lambda m, s="done": _step(jid, m, s))

        final = _payload(facts, alist, plan, writer, note, usage, cfg)
        with CACHE_LOCK:
            CACHE[plan] = final
        _publish(jid, final)
        with JOBS_LOCK:
            JOBS[jid]["state"] = "done"

    except Exception as exc:
        traceback.print_exc()
        with JOBS_LOCK:
            JOBS[jid]["state"] = "error"
            JOBS[jid]["error"] = "%s: %s" % (type(exc).__name__, exc)


class Handler(BaseHTTPRequestHandler):
    server_version = "MVOwnerAlerts/2.0"

    def log_message(self, fmt, *args):
        if "/api/job/" not in (self.path or ""):   # polling would drown the console
            sys.stderr.write("  %s\n" % (fmt % args))

    def _send(self, code, body, ctype="application/json"):
        """Write the response in chunks, and survive a client that goes away.

        THE PAGE IS 3.2 MB AND A SINGLE write() OF IT DOES NOT SURVIVE.

          The first version handed the whole artifact to wfile.write() in one call. The browser
          reported ERR_CONNECTION_RESET and rendered a TRUNCATED document - styles and most of
          the markup arrived, the closing <script src="/bind.js"> did not. So the page looked
          completely normal, kept the artifact's sample rows, and bound nothing. Nothing in the
          server log said anything was wrong: from its side the write had been accepted.

          That is the worst shape a bug can take on this page - a plausible screen full of
          fictional alerts - so the body is written in 256 KB chunks and a disconnect mid-write
          is caught rather than raised into the handler.
        """
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, default=_jsonable).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        view = memoryview(body)
        step = 256 * 1024
        try:
            for i in range(0, len(view), step):
                self.wfile.write(view[i:i + step])
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # The reader navigated away or reloaded mid-transfer. Normal, and not an error the
            # handler should turn into a stack trace.
            pass

    def do_HEAD(self):
        # The preview harness probes with HEAD; BaseHTTPRequestHandler answers 501 without this
        # and the log fills with errors that look like a fault in the app.
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        path = (self.path or "/").split("?")[0]

        if path.startswith("/api/job/"):
            with JOBS_LOCK:
                job = JOBS.get(path.rsplit("/", 1)[-1])
            return self._send(200 if job else 404, job or {"error": "no such job"})

        if path == "/api/health":
            ok, msg = db.ping()
            cfg = db.config()
            return self._send(200, {
                "mongo": ok, "detail": msg,
                "ui": {k: v for k, v in cfg["ui"].items() if not k.startswith("_")},
                "owner": {"name": cfg["owner"]["name"],
                          "ownernumber": cfg["owner"]["default_ownernumber"],
                          "year": cfg["owner"]["year"],
                          "scope": cfg["owner"].get("scope", "record")},
                "ai": bool(cfg["ai"].get("api_key")), "model": cfg["ai"]["model"]})

        rel = PAGE if path == "/" else path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB, rel))
        if not full.startswith(WEB) or not os.path.isfile(full):
            return self._send(404, {"error": "not found: %s" % rel})
        with open(full, "rb") as fh:
            data = fh.read()
        return self._send(200, data, MIME.get(os.path.splitext(full)[1], "text/plain"))

    def do_POST(self):
        if (self.path or "").split("?")[0] != "/api/run":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"error": "bad JSON"})

        cfg = db.config()
        plan = str(body.get("plan") or cfg["ui"]["default_plan"])
        if plan not in [p["key"] for p in cfg["ui"]["plans"]]:
            return self._send(400, {"error": "unknown plan %r" % plan})

        jid = _new_job()
        threading.Thread(target=_run, args=(jid, plan, bool(body.get("fresh"))),
                         daemon=True).start()
        return self._send(200, {"job_id": jid})


def main():
    cfg = db.config()
    host, port = cfg["server"]["host"], cfg["server"]["port"]
    page = os.path.join(WEB, PAGE)
    if not os.path.isfile(page):
        print("web/%s is missing. Build it first:\n    python tools/build_alerts.py" % PAGE)
        raise SystemExit(1)

    ok, msg = db.ping()
    print("Mineral View - owner Alerts")
    print("  MongoDB : %s" % ("connected" if ok else "NOT REACHABLE"))
    if not ok:
        print("            %s" % msg.replace("\n", "\n            "))
    print("  AI      : %s (%s)" % (cfg["ai"]["model"],
                                   "key present" if cfg["ai"].get("api_key") else "NO KEY"))
    print("  Owner   : %s, record #%s - all claimed leases, %s roll"
          % (cfg["owner"]["name"], cfg["owner"]["default_ownernumber"], cfg["owner"]["year"]))
    print("  Page    : web/%s (%.2f MB, shell intact)" % (PAGE, os.path.getsize(page) / 1e6))
    print("  Open    : http://%s:%d\n" % (host, port))
    try:
        webbrowser.open("http://%s:%d" % (host, port))
    except Exception:
        pass
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
