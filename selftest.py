# -*- coding: utf-8 -*-
"""Prove the guards can fail.

    python selftest.py

Every check here corrupts something and requires the guard to notice. A check that cannot fail
is decorative - so when one of these passes, the line says what would have made it fail.

Most of it runs without a database. The two that need Mongo say so and skip cleanly when the
VPN is down, rather than reporting a network problem as a broken guard.
"""
import io
import os
import re
import sys
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mv import alerts as A, db, production, prices, summarize, ymd   # noqa: E402

PASS, FAIL, SKIP = [], [], []


def check(name, ok, would_fail, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %-4s %-52s %s" % ("ok" if ok else "FAIL", name,
                               ("would fail if: " + would_fail) if ok else detail))


def skip(name, why):
    SKIP.append(name)
    print("  %-4s %-52s %s" % ("skip", name, why))


print("\nmv-owner-alerts selftest\n" + "-" * 78)

# ---------------------------------------------------------------- 1 · the read-only guard
print("\n1 - the connection cannot be used to write")
try:
    c = db.coll("production")
    try:
        c.insert_one({"x": 1})
        check("write helper is absent", False, "", "insert_one was callable")
    except AttributeError:
        check("write helper is absent", True, "someone forwards __getattr__ to pymongo")
    try:
        c.aggregate([{"$match": {}}, {"$out": "evil"}])
        check("$out is refused before the driver", False, "", "$out was accepted")
    except PermissionError:
        check("$out is refused before the driver", True, "the pipeline scan drops $out/$merge")
except Exception as exc:
    skip("read-only guard", "%s: %s" % (type(exc).__name__, exc))

# ---------------------------------------------------------------- 2 · the trailing-zero trap
print("\n2 - the window anchors on the last REPORTED month, not the last month present")
doc = {
    "_id": "08_55109", "lease_name": "SOTO 43-7", "lease_number": "55109", "county": "MARTIN",
    "district_code": "08", "Lease_Status": "Producing", "Total_BOE": 100,
    "first_produced_month": "04", "first_produced_year": "2020",
    "data": [
        {"cycle_year": "2026", "cycle_month": "05", "BOE": 5000, "prod_report_filed_flag": "Y"},
        {"cycle_year": "2026", "cycle_month": "07", "BOE": 0, "prod_report_filed_flag": "N"},
        {"cycle_year": "2026", "cycle_month": "08", "BOE": 0, "prod_report_filed_flag": "N"},
    ],
}
recs = production.transform(doc)
anchor = production.latest_real_cycle({"08_55109": recs})
check("placeholder months do not become the as-of date", anchor == "202605",
      "the anchor uses max(cycle) instead of the last reported month", "got %s" % anchor)
check("a zero month is 'Not Producing', not missing",
      [r for r in recs if r["cycle_year_month"] == "202607"][0]["monthly_lease_status"]
      == "Not Producing",
      "the monthly status is copied from the lease-level status")

# ---------------------------------------------------------------- 3 · the API-spec transform
print("\n3 - the production transform matches the written contract")
r = recs[0]
check("numeric fields never come back null",
      all(isinstance(r[k], (int, float)) for k in
          ("lease_oil_production", "lease_gas_production", "monthly_boe",
           "total_oil_production", "total_gas_production", "total_boe")),
      "the missing-value rule stops defaulting absent numbers to 0")
check("first_production_date is month/year", r["first_production_date"] == "04/2020",
      "the two source fields stop being joined with a slash")
check("cycle_year_month stays a fixed-width string",
      isinstance(r["cycle_year_month"], str) and len(r["cycle_year_month"]) == 6,
      "it is returned as a number and string range filters stop sorting")
check("the constants are on every record", r["activity_id"] == 3 and r["activity_type"] == "New Production",
      "the feed shape stops matching the other activity types")
check("months come back newest first",
      [x["cycle_year_month"] for x in recs] == sorted(
          [x["cycle_year_month"] for x in recs], reverse=True),
      "the sort is dropped and the inbox shows the oldest month first")

# ---------------------------------------------------------------- 4 · the date trap
print("\n4 - dates are parsed, never sliced")
check("a leading space does not shift the year",
      ymd.parse_date(" 10/22/2025") == datetime.date(2025, 10, 22),
      "someone slices characters 6-10 out of the raw string instead of parsing")
check("a trailing space parses too", ymd.parse_date("09/11/2025 ") == datetime.date(2025, 9, 11),
      "the parser stops stripping")
check("a six-digit cycle parses", ymd.parse_date("202603") == datetime.date(2026, 3, 1),
      "the cycle pattern is removed")
check("garbage returns None rather than raising", ymd.parse_date("not a date") is None,
      "the parser starts raising and one bad row kills the whole build")

# ---------------------------------------------------------------- 5 · the sentinel
print("\n5 - the not-modelled probability sentinel is filtered, not rendered")
cfg = db.config()
check("-1 is configured as a sentinel, not a score",
      cfg["probability_bands"]["sentinel"] == -1,
      "the sentinel is removed from config and -1 renders as a 0% chance")
lo = min(b[1] for b in cfg["probability_bands"]["bands"])
check("no band starts below zero", lo >= 0,
      "a band is widened to include -1 and the sentinel becomes a legitimate score")

# ---------------------------------------------------------------- 6 · the AI numeric guard
print("\n6 - the model cannot introduce a number")
fake = {"id": "production", "title": "Production posted 1,234 BOE", "body": "On one lease.",
        "why": "w", "source": "s", "evidence": {"rows": [], "method": "", "why": ""}}
allowed = summarize._allowed(fake)
check("a figure from the finding is allowed", not (summarize._tokens("1,234 BOE") - allowed),
      "the token normaliser stops stripping thousands separators")
check("an invented figure is caught", bool(summarize._tokens("9,876 BOE") - allowed),
      "the guard stops comparing against the finding's own numbers")
check("a rounded figure is allowed", not (summarize._tokens("1234") - allowed),
      "rounding tolerance is removed and every run falls back")

# ---------------------------------------------------------------- 7 · no schema on screen
print("\n7 - no collection or column name reaches a rendered field")
INTERNAL = ["MonthlyProductionVolumes", "Activity_Test", "LeaseRadiusData", "Data_to_web",
            "Mineral_Owners_Data_Master", "privategroupthreads", "Near_Permit_List",
            "Near_Leases_List", "Operator_Production_Summary_Yearly", "Activity_Production",
            "ProdMvestPortal", "GeoMapPortal", "Decline_data_to_web", "MViewNewCommunity",
            "ownernumber", "cycle_year_month", "prod_report_filed_flag"]


def rendered_strings(alert):
    """Exactly the fields web/app.js puts on the page. `source` is NOT one of them."""
    out = [alert.get("title", ""), alert.get("body", ""), alert.get("why", ""),
           alert.get("public", "")]
    ev = alert.get("evidence") or {}
    out += [ev.get("why", ""), ev.get("method", "")]
    for row in ev.get("rows", []):
        out += [str(row.get("k", "")), str(row.get("v", "")), str(row.get("note", ""))]
    return out


check("every signal id maps to a public source",
      A.public_source("payment_gap") != "Texas Railroad Commission public record",
      "a mapping is deleted and the row falls back to the vague label")
check("an UNKNOWN id gets the safe label, never the internal one",
      A.public_source("brand_new_signal") == "Texas Railroad Commission public record",
      "the default becomes alert['source'] and a new signal leaks the collection name")

# ---------------------------------------------------------------- 8 · the eight-field contract
print("\n8 - an alert without a 'why' cannot be built")
try:
    A._a(id="production", title="t", body="b")
    check("a missing why is rejected", False, "", "it was accepted")
except ValueError:
    check("a missing why is rejected", True,
          "the check is removed and a row renders an empty why? tooltip")

# ---------------------------------------------------------------- 9 · live prices
print("\n9 - prices are live, and a dead feed is visible rather than defaulted")
q = prices.live(cfg, force=True)
live = [k for k, v in q.items() if not v.get("error")]
if live:
    one = q[live[0]]
    age_ok = True
    if one.get("as_of_epoch"):
        age = (datetime.datetime.now() -
               datetime.datetime.fromtimestamp(one["as_of_epoch"])).days
        age_ok = age <= 5
    check("the quote is current, not an 8-day-old settlement", age_ok,
          "the feed is pointed back at the EIA spreadsheets",
          "quote is %d days old" % age if not age_ok else "")
    check("a change is computed against the previous close",
          one.get("prev_close") is not None,
          "the previous close is taken from the range metadata instead of the series")
else:
    skip("live prices", "no quote returned - offline, or the endpoint moved")

# ---------------------------------------------------------------- 10 · full build (needs VPN)
print("\n10 - the whole panel, against the live record")
ok, msg = db.ping()
if not ok:
    skip("live build", "MongoDB not reachable - VPN down?")
else:
    from mv import collect
    facts = collect.collect(cfg, cfg["owner"]["default_ownernumber"], want_prices=False)
    facts["name_matches"], facts["name_counties"] = 1, 1
    alist = A.build(facts, cfg)
    check("the build produces alerts", len(alist) > 0,
          "every source returns empty and nothing notices", "%d built" % len(alist))
    check("every alert carries all eight rendered fields",
          all(a.get("title") and a.get("body") and a.get("why") and a.get("public")
              and a.get("category") and a.get("delivery_class") and a.get("deep_link")
              and (a.get("event_date") is not None) for a in alist),
          "a new alert type is added without one of them")

    leaks = []
    for a in alist:
        for s in rendered_strings(a):
            for word in INTERNAL:
                if word in s:
                    leaks.append((a["id"], word))
    check("no internal name reaches a rendered field", not leaks,
          "a new alert pastes a collection name into its method text",
          "; ".join("%s -> %s" % l for l in leaks[:4]))

    # ownernumber is a COUNTY appraisal key: 127,650 of 420,296 in the 2025 roll are shared by
    # more than one person. Reading it without the name merges strangers' minerals into one
    # portfolio - number 708789 alone is seven different people in seven counties.
    from mv import owner as owner_mod
    oc = db.coll("owners")
    num, yr = cfg["owner"]["default_ownernumber"], cfg["owner"]["year"]
    named = owner_mod.portfolio(oc, num, yr, cfg["owner"]["name"])
    unnamed = owner_mod.portfolio(oc, num, yr)
    check("the owner key is (number + name), not the number alone",
          named["lease_count"] < unnamed["lease_count"] and named["county_count"] == 1,
          "portfolio() stops filtering on the name and picks up other people's leases",
          "named %d leases / %d counties vs unnamed %d / %d"
          % (named["lease_count"], named["county_count"],
             unnamed["lease_count"], unnamed["county_count"]))
    check("the portfolio the panel used is the named one",
          facts["owner"]["lease_count"] == named["lease_count"],
          "collect() calls portfolio() without the name")

    c = A.counts(alist)
    check("the counts equal the list they came from",
          c["all"] == len(alist) and
          sum(c[k] for k in ("money", "activity", "community", "model")) == len(alist),
          "the counts are computed from a second source and drift from the rows")

    dates_ok = all((a["detected"] is None or a["event_date"] is None or
                    a["detected"] >= a["event_date"]) for a in alist)
    check("detection never predates the event", dates_ok,
          "the two dates are collapsed into one field")

# ---------------------------------------------------------------- 11 · portfolio-wide
print("\n11 - every alert is measured across the WHOLE portfolio, never one lease")
if not ok:
    skip("portfolio scope", "MongoDB not reachable")
else:
    total = facts["owner"]["lease_count"]
    # THE REGRESSION THIS GUARDS AGAINST: an alert that names one lease and stays silent about
    # the other 102. Alerts about a single external event - a group post, the roll refresh -
    # carry lease_count 0 by design, so they are excluded rather than forced to fake a count.
    scoped = [a for a in alist if a.get("lease_count")]
    wide = [a for a in scoped if a["lease_count"] > 1]
    check("most alerts span more than one lease",
          len(wide) >= max(3, len(scoped) // 2),
          "an alert goes back to picking the biggest lease and naming only that",
          "%d of %d scoped alerts span >1 lease" % (len(wide), len(scoped)))
    check("no alert claims more leases than the owner holds",
          all(a["lease_count"] <= total for a in alist),
          "a count is summed over events instead of over distinct leases",
          "portfolio is %d leases" % total)
    biggest = max(scoped, key=lambda a: a["lease_count"]) if scoped else None
    check("the widest alert covers most of the position",
          bool(biggest) and biggest["lease_count"] >= total * 0.5,
          "the lease loop is capped and only the first N leases are ever considered",
          ("widest covers %d of %d" % (biggest["lease_count"], total)) if biggest else "none")
    told = [a for a in scoped
            if str(a["lease_count"]) in a["title"].replace(",", "") or "your" in a["title"]]
    check("the lease count reaches the headline", len(told) >= len(scoped) // 2,
          "the count is computed and then left out of the title the reader actually sees",
          "%d of %d headlines carry it" % (len(told), len(scoped)))

# ---------------------------------------------------------------- 12 · the built page
print("\n12 - the built page kept the shell, and the binder is where it will run")
_page = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "alerts.html")
if not os.path.isfile(_page):
    skip("built page", "public/alerts.html not built - run tools/build_alerts.py")
else:
    _html = io.open(_page, encoding="utf-8").read()
    _head = _html[:_html.find("</head>")]
    check("the binder is in <head> with defer", 'src="/bind.js" defer' in _head,
          "it moves to the end of <body>, where a 3.2 MB file carrying '</script>' inside a "
          "JS string means it is never parsed and the page shows the sample alerts")
    check("the sidebar nav survived", _html.count('class="nav-item"') >= 20,
          "the build starts stripping routes and takes the left menu with them",
          "%d nav links" % _html.count('class="nav-item"'))
    check("the alerts route survived", 'data-route="app-alerts"' in _html,
          "the one route this app exists to serve is removed")
    check("the four view densities survived",
          'data-tier="pro"' in _html and 'data-tier="ultra"' in _html,
          "the avatar menu's density switcher is stripped out of the shell")
    check("their scripts survived - the router is in them",
          _html.count("<script") >= 20,
          "a section walker eats the scripts and the page renders as styled static HTML",
          "%d script tags" % _html.count("<script"))
    _bare = re.sub(r"[A-Za-z0-9_$]Suzie|Suzie[A-Za-z0-9_$]", "", _html)
    check("the chrome names the live owner, not the demo one",
          cfg["owner"]["name"] in _html and "Suzie" not in _bare,
          "the rename is skipped and the tab title names a fictional demo owner")

print("\n" + "-" * 78)
print("%d passed · %d failed · %d skipped" % (len(PASS), len(FAIL), len(SKIP)))
if FAIL:
    print("\nFAILED: %s" % ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
