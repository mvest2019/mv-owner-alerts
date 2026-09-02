# -*- coding: utf-8 -*-
"""Live commodity prices. Front-month NYMEX futures, quoted intraday.

WHY NOT THE EXISTING FEED
  tools/price-feed in the redesign repo pulls EIA dnav spreadsheets and its own ticker.json
  says what that means:

      "basis": "End-of-day spot settlements. Not live prices."
      as_of: 2026-07-20   generated: 2026-07-29   lag_days: 8

  So the alert headed "Know the same day" was reporting a settlement published the week
  before. For a price alert that claims to have touched an owner's estimate today, an 8-day-old
  number is the wrong number.

THE PREVIOUS-CLOSE TRAP
  meta.chartPreviousClose is the close BEFORE the requested range, not yesterday's. Ask for
  5 days and compute against it and an ordinary session reports as an 8% move - measured:
  CL=F showed +8.13% against a 5-day-old close where the day's actual move was a fraction of
  that. The previous close is taken from the daily series itself, one bar back from the last.

NO KEY, AND A HARD FAIL
  If the quote cannot be fetched the price alert is DROPPED, not defaulted. A stale or invented
  price on a page that tells someone their minerals moved in value is worse than no price row.
"""
import json
import ssl
import time
import urllib.request

_CACHE = {"at": 0.0, "data": None}

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MineralView-alerts/1.0"}
_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1mo&interval=1d"


def _ctx():
    c = ssl.create_default_context()
    # Corporate TLS interception behind the VPN presents its own chain. This client reads a
    # public quote endpoint and sends no credential, so pinning buys nothing here.
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _quote(symbol, timeout):
    raw = urllib.request.urlopen(
        urllib.request.Request(_CHART % symbol, headers=_UA),
        timeout=timeout, context=_ctx()).read()
    res = json.loads(raw.decode("utf-8"))["chart"]["result"][0]
    meta = res["meta"]
    price = meta.get("regularMarketPrice")
    if price is None:
        raise ValueError("no regularMarketPrice for %s" % symbol)

    # Previous close from the series, not from meta - see the module docstring.
    closes = [c for c in (res.get("indicators", {}).get("quote", [{}])[0].get("close") or [])
              if c is not None]
    prev = closes[-2] if len(closes) >= 2 else meta.get("previousClose")
    pct = ((price - prev) / prev * 100.0) if prev else None
    return {
        "price": round(float(price), 4),
        "prev_close": round(float(prev), 4) if prev else None,
        "change_pct": round(pct, 2) if pct is not None else None,
        "as_of_epoch": meta.get("regularMarketTime"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "currency": meta.get("currency"),
    }


def live(cfg, force=False):
    """-> {key: quote} for every configured symbol that answered. Never raises.

    Cached for cache_seconds: the panel reads prices once per build and a lookup of the same
    owner twice in a minute should not hit the quote endpoint twice.
    """
    pc = cfg["prices"]
    now = time.time()
    if not force and _CACHE["data"] and (now - _CACHE["at"]) < pc.get("cache_seconds", 60):
        return _CACHE["data"]

    out = {}
    for spec in pc["symbols"]:
        try:
            q = _quote(spec["symbol"], pc.get("timeout_seconds", 20))
            q.update({"label": spec["label"], "unit": spec["unit"],
                      "desc": spec["desc"], "symbol": spec["symbol"]})
            out[spec["key"]] = q
        except Exception as exc:
            out[spec["key"]] = {"label": spec["label"], "unit": spec["unit"],
                                "desc": spec["desc"], "symbol": spec["symbol"],
                                "error": "%s: %s" % (type(exc).__name__, str(exc)[:120])}
    _CACHE["at"], _CACHE["data"] = now, out
    return out


def display(q):
    """A price formatted the way its unit is quoted. Gas is three decimals, crude is two."""
    if not q or q.get("price") is None:
        return "-"
    return ("$%.3f" if "MMBtu" in (q.get("unit") or "") else "$%.2f") % q["price"]
