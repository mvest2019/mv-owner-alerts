# -*- coding: utf-8 -*-
"""Every source, reduced to a few KB of measured facts.

Nothing raw is carried forward. The alert builder and the model both read this dict and only
this dict, so there is exactly one definition of every figure on the page.

THE SOURCE MAP, AND WHY EACH ONE CHANGED
  production   MonthlyProductionVolumes via production.py (the API spec), NOT Activity_Production
  activity     Activity_Test - five live event types, written today, with activity_notification
  radius       LeaseRadiusData, NOT Adjacent_Lease_Activity - same key, both sides in one doc
  probability  Data_to_web 'NEW WELL PROBABILITY' - the named collection does not exist
  operator     Operator_Production_Summary_Yearly + Operator_Logos
  prices       live NYMEX front-month, NOT the 8-day-lagged EIA ticker
  community    privategroupthreads

EVERY WINDOW IS ANCHORED ON THE DATA, NEVER ON THE CLOCK.
"""
import datetime
import re

from . import owner as owner_mod
from . import prices as prices_mod
from . import production as prod_mod
from . import ymd

BOE_PER_MCF = 1.0 / 15.0   # MineralView uses 15:1, not 6:1 - verified against the portal's own
                           # MonthlyProductionVolumes totals. A 6:1 constant overstates gas 2.5x.


def _split_list(value):
    """'736104,860791' -> ['736104','860791']. These fields are comma-separated STRINGS.

    Near_Permit_List, Near_Leases_List and adjacent lists are all stored as one string, so a
    change is detected by set difference after parsing - never by comparing the strings, which
    reorder without meaning anything.
    """
    if not value:
        return []
    return [p.strip() for p in re.split(r"[,\s]+", str(value)) if p.strip()]


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- owner + leases
def identity(cfg, colls, ownernumber, log=None):
    oc = colls["owners"]
    # The name is passed deliberately - ownernumber alone is a county key, not an owner id.
    # See the measurement in owner.portfolio's docstring.
    port = owner_mod.portfolio(oc, ownernumber, cfg["owner"]["year"], cfg["owner"]["name"])
    if log:
        log("owner record %s - %d lease(s) across %d county(ies)"
            % (ownernumber, port["lease_count"], port["county_count"]))
    return port


# --------------------------------------------------------------------------- production
def production(cfg, colls, lease_ids, log=None):
    by_lease = prod_mod.fetch(colls["production"], lease_ids,
                              from_cycle=cfg["window"]["from_cycle"])
    as_of = prod_mod.latest_real_cycle(by_lease)
    if log:
        log("production: %d of %d lease(s) have a record, newest reported month %s"
            % (len(by_lease), len(lease_ids), ymd.cycle_pretty(as_of) if as_of else "none"))

    ttm = ymd.cycle_range(as_of, cfg["window"]["ttm_months"]) if as_of else []
    prev_ttm = ymd.cycle_range(ymd.cycle_shift(as_of, -cfg["window"]["ttm_months"]),
                               cfg["window"]["ttm_months"]) if as_of else []
    recent = ymd.cycle_range(as_of, cfg["window"]["recent_months"]) if as_of else []
    prior = ymd.cycle_range(ymd.cycle_shift(as_of, -cfg["window"]["recent_months"]),
                            cfg["window"]["compare_months"]) if as_of else []

    ttm_boe = prev_boe = recent_boe = prior_boe = 0.0
    latest_rows, series, per_lease = [], {}, {}
    for lid, recs in by_lease.items():
        l_ttm = 0.0
        for r in recs:
            c, b = r["cycle_year_month"], r["monthly_boe"]
            if c in ttm:
                ttm_boe += b
                l_ttm += b
            if c in prev_ttm:
                prev_boe += b
            if c in recent:
                recent_boe += b
            if c in prior:
                prior_boe += b
            if as_of and c <= as_of:
                series[c] = series.get(c, 0.0) + b
            if c == as_of and b > 0:
                latest_rows.append(r)
        head = recs[0] if recs else {}
        per_lease[lid] = {
            "ttm_boe": round(l_ttm, 2),
            "lease_name": head.get("lease_name") or "",
            "operator": head.get("current_operator_name") or "",
            "operator_no": head.get("current_operator_number") or "",
            "field_name": head.get("field_name") or "",
            "status": head.get("lease_status") or "",
            "county": head.get("county") or "",
            "total_boe": head.get("total_boe") or 0.0,
            "first_production_date": head.get("first_production_date") or "",
            "months": len(recs),
            "latest_cycle": recs[0]["cycle_year_month"] if recs else None,
            # The volume in the as-of month, NOT in recs[0]. recs[0] is the newest row present,
            # which is usually a placeholder month carrying zero - reading it reported "0
            # producing leases" on a portfolio that produced 14.23M BOE over the year.
            "latest_boe": next((r["monthly_boe"] for r in recs
                                if r["cycle_year_month"] == as_of), 0.0) if as_of else 0.0,
        }

    def pct(now, before):
        if not before:
            return None
        return (now - before) / before * 100.0

    spark = [{"label": ymd.cycle_short(c), "value": round(series.get(c, 0.0), 2),
              "on": c in recent} for c in (ttm or [])]

    latest_rows.sort(key=lambda r: r["monthly_boe"], reverse=True)
    return {
        "by_lease": by_lease,
        "per_lease": per_lease,
        "as_of": as_of,
        "as_of_label": ymd.cycle_pretty(as_of) if as_of else "no production on record",
        "ttm_boe": round(ttm_boe, 2),
        "prev_ttm_boe": round(prev_boe, 2),
        "ttm_pct": pct(ttm_boe, prev_boe),
        "recent_boe": round(recent_boe, 2),
        "prior_boe": round(prior_boe, 2),
        "recent_pct": pct(recent_boe, prior_boe),
        "recent_label": "%s-%s" % (ymd.cycle_short(recent[0]), ymd.cycle_short(recent[-1])) if recent else "-",
        "prior_label": "%s-%s" % (ymd.cycle_short(prior[0]), ymd.cycle_short(prior[-1])) if prior else "-",
        "latest_rows": latest_rows,
        "producing_leases": sum(1 for v in per_lease.values() if v["latest_boe"] > 0),
        "filings_read": sum(len(v) for v in by_lease.values()),
        "series": spark,
    }


# --------------------------------------------------------------------------- activity feed
ACTIVITY_TYPES = {
    1: "New Permit", 2: "New Completion", 3: "New Production",
    4: "Well Status Change", 5: "Operator Change", 6: "Unexpected Production Change",
}


def activity(cfg, colls, lease_ids, log=None):
    """Activity_Test, scoped to the owner's leases.

    Activity_Test keys by district_code + lease_number rather than the composite id, so the
    filter is built from the parts. Dates are pulled out and parsed in Python (see ymd), never
    sliced in the pipeline.
    """
    pairs = []
    for lid in lease_ids:
        if "_" in lid:
            d, l = lid.split("_", 1)
            pairs.append({"district_code": d, "lease_number": l})
    if not pairs:
        return {"events": [], "by_type": {}, "window_days": cfg["window"]["activity_days"]}

    cur = colls["activity"].find(
        {"$or": pairs},
        {"district_code": 1, "lease_number": 1, "lease_name": 1, "county": 1,
         "activity_type": 1, "activity_id": 1, "activity_notification": 1,
         "cycle_year_month": 1, "cycle_year": 1, "cycle_month": 1,
         "current_operator_name": 1, "current_operator_number": 1, "operator_name": 1,
         "field_name": 1, "well_number": 1, "api": 1, "well_type": 1, "well_status": 1,
         "wellbore_profile": 1, "filing_purpose": 1, "filling_purpose": 1, "permit_action": 1,
         "total_depth": 1, "status": 1, "status_number": 1, "link": 1,
         "submit_date": 1, "approved_date": 1, "completion_date": 1,
         "monthly_boe": 1, "lease_status": 1, "CreateTS": 1, "CreatedAT": 1})

    events, by_type = [], {}
    for d in cur:
        lid = "%s_%s" % (str(d.get("district_code") or "").strip(),
                         str(d.get("lease_number") or "").strip())
        aid = d.get("activity_id")
        when = (ymd.parse_date(d.get("completion_date"))
                or ymd.parse_date(d.get("approved_date"))
                or ymd.parse_date(d.get("submit_date"))
                or ymd.parse_date(d.get("cycle_year_month")))
        detected = d.get("CreateTS") or d.get("CreatedAT")
        if isinstance(detected, datetime.datetime):
            detected = detected.date()
        ev = {
            "lease_id": lid,
            "lease_name": (d.get("lease_name") or "").strip(),
            "county": (d.get("county") or "").strip(),
            "activity_id": aid,
            "activity_type": d.get("activity_type") or ACTIVITY_TYPES.get(aid, "Activity"),
            "note": (d.get("activity_notification") or "").strip(),
            "operator": (d.get("current_operator_name") or d.get("operator_name") or "").strip(),
            "well_number": (d.get("well_number") or "").strip(),
            "api": (d.get("api") or "").strip(),
            "wellbore_profile": (d.get("wellbore_profile") or "").strip(),
            "filing_purpose": (d.get("filing_purpose") or d.get("filling_purpose") or "").strip(),
            "permit_action": (d.get("permit_action") or "").strip(),
            "well_status": (d.get("well_status") or "").strip(),
            "status_number": (d.get("status_number") or "").strip(),
            "total_depth": d.get("total_depth"),
            "field_name": (d.get("field_name") or "").strip(),
            "cycle": str(d.get("cycle_year_month") or "").strip() or None,
            "monthly_boe": _f(d.get("monthly_boe")),
            "event_date": when,
            "detected": detected,
            "link": (d.get("link") or "").strip(),
        }
        events.append(ev)
        by_type.setdefault(aid, []).append(ev)

    # Newest first. An event with no parseable date sorts last rather than crashing the sort or
    # silently claiming today - a filing whose date we cannot read is not a filing from today.
    events.sort(key=lambda e: (e["event_date"] or datetime.date(1900, 1, 1)), reverse=True)
    if log:
        log("activity: %d event(s) across %d type(s) on the claimed leases"
            % (len(events), len(by_type)))
    return {"events": events, "by_type": by_type,
            "window_days": cfg["window"]["activity_days"]}


# --------------------------------------------------------------------------- radius
def radius(cfg, colls, lease_ids, log=None):
    """LeaseRadiusData - nearby permits and nearby leases, at the tightest radius on record.

    The 1-mile ring is the one the product promises ("within 1 mile"), so it is preferred and
    the radius actually used is reported rather than assumed.
    """
    cur = colls["radius"].find(
        {"main_lease": {"$in": list(lease_ids)}},
        {"main_lease": 1, "county": 1, "radius": 1, "Near_Permit_List": 1,
         "Near_Leases_List": 1, "mongo_update_date": 1})
    best, stamp = {}, None
    for d in cur:
        lid = d.get("main_lease")
        try:
            r = float(d.get("radius") or 99)
        except (TypeError, ValueError):
            r = 99.0
        cur_best = best.get(lid)
        if cur_best is None or r < cur_best["radius"]:
            best[lid] = {
                "radius": r,
                "permits": _split_list(d.get("Near_Permit_List")),
                "leases": _split_list(d.get("Near_Leases_List")),
                "county": (d.get("county") or "").strip(),
            }
        stamp = stamp or (d.get("mongo_update_date") or "").strip()

    permits, near_leases = set(), set()
    for v in best.values():
        permits.update(v["permits"])
        # Near_Leases_List entries are '{district}_{lease}_{api14}' - the lease is the first two
        # parts. Counting raw entries counts a lease once per wellbore.
        for entry in v["leases"]:
            parts = entry.split("_")
            near_leases.add("_".join(parts[:2]) if len(parts) >= 2 else entry)
    near_leases -= set(lease_ids)

    if log:
        log("radius: %d standing permit(s) and %d adjacent lease(s) within ~%s mile"
            % (len(permits), len(near_leases),
               ("%g" % min([v["radius"] for v in best.values()])) if best else "1"))
    return {
        "by_lease": best,
        "permit_count": len(permits),
        "adjacent_count": len(near_leases),
        "permits": sorted(permits),
        "adjacent": sorted(near_leases),
        "covered": len(best),
        # A single value across all 350,556 rows: this is when the collection was last rebuilt,
        # not when a row changed. Reported as a build stamp, never as a per-row change time.
        "rebuilt": stamp,
        "radius_used": min([v["radius"] for v in best.values()]) if best else None,
    }


# --------------------------------------------------------------------------- probability
def probability(cfg, colls, lease_ids, log=None):
    """Data_to_web NEW WELL PROBABILITY, with the -1 sentinel filtered at source."""
    sentinel = cfg["probability_bands"]["sentinel"]
    cur = colls["probability"].find(
        {"_id": {"$in": list(lease_ids)}},
        {"NEW WELL PROBABILITY": 1, "NEW WELL PROBABILITY CATEGORY": 1, "COUNTY": 1})
    scored, unmodelled = [], 0
    for d in cur:
        p, cat = d.get("NEW WELL PROBABILITY"), d.get("NEW WELL PROBABILITY CATEGORY")
        if p is None or p == sentinel or cat in (sentinel, "Undefined", None):
            unmodelled += 1
            continue
        scored.append({"lease_id": d["_id"], "probability": _f(p),
                       "category": str(cat), "county": (d.get("COUNTY") or "").strip()})
    scored.sort(key=lambda r: r["probability"], reverse=True)
    avg = round(sum(r["probability"] for r in scored) / len(scored), 1) if scored else None
    if log:
        log("new-well probability: %d lease(s) modelled, %d carry the not-modelled sentinel"
            % (len(scored), unmodelled))
    return {"scored": scored, "unmodelled": unmodelled, "count": len(scored),
            "average": avg, "top": scored[0] if scored else None,
            "bands": cfg["probability_bands"]["bands"]}


# --------------------------------------------------------------------------- operators
def operators(cfg, colls, per_lease, log=None):
    """Who operates the owner's leases, and how big each of them is."""
    counts = {}
    for v in per_lease.values():
        no, name = (v.get("operator_no") or "").strip(), (v.get("operator") or "").strip()
        if not no and not name:
            continue
        e = counts.setdefault(no or name, {"operator_no": no, "name": name,
                                           "leases": 0, "ttm_boe": 0.0})
        e["leases"] += 1
        e["ttm_boe"] += v.get("ttm_boe") or 0.0

    nos = [k for k in counts if k and k.isdigit()]
    if nos:
        for d in colls["operator_summary"].find(
                {"operator_no": {"$in": nos}},
                {"operator_no": 1, "operator_name": 1, "NO_Leases": 1,
                 "No_Of_Producing_County": 1, "Total_Production_BOE": 1,
                 "Current_Year_BOE_Prod": 1, "Previous_Year_BOE_Prod": 1,
                 "Production_End_Date": 1}):
            e = counts.get(d["operator_no"])
            if not e:
                continue
            e["name"] = e["name"] or (d.get("operator_name") or "").strip()
            e["statewide_leases"] = d.get("NO_Leases")
            e["statewide_counties"] = d.get("No_Of_Producing_County")
            e["statewide_boe"] = _f(d.get("Total_Production_BOE"))
            cy, py = _f(d.get("Current_Year_BOE_Prod")), _f(d.get("Previous_Year_BOE_Prod"))
            e["yoy_pct"] = ((cy - py) / py * 100.0) if py else None

    out = sorted(counts.values(), key=lambda e: (-e["leases"], -e["ttm_boe"]))
    for e in out:
        e["ttm_boe"] = round(e["ttm_boe"], 2)
    if log:
        log("operators: %d distinct operator(s) across the portfolio" % len(out))
    return {"operators": out, "count": len(out)}


# --------------------------------------------------------------------------- community
def community(cfg, colls, counties, log=None):
    """Private group threads.

    MEASURED SHAPE - the fields are not the obvious ones. privategroupthreads carries
    prvgrpName / threadSummaries[] / createdAt, with no title, subject or author field at all.
    A first pass projected title/userName/groupName, found none of them, and reported zero
    threads on a collection holding 211,164 documents. Reading the schema rather than assuming
    it is the whole fix.
    """
    try:
        cur = colls["community"].find(
            {}, {"prvgrpName": 1, "threadSummaries": 1, "createdAt": 1,
                 "updatedAt": 1, "views": 1, "url": 1}
        ).sort([("createdAt", -1)]).limit(25)
        rows = []
        for d in cur:
            when = d.get("createdAt") or d.get("updatedAt")
            if isinstance(when, datetime.datetime):
                when = when.date()
            summaries = [s for s in (d.get("threadSummaries") or []) if s]
            title = ""
            for s in summaries:
                title = (s if isinstance(s, str) else
                         (s.get("summary") or s.get("title") or s.get("text") or "")).strip()
                if title:
                    break
            rows.append({
                "title": title or (d.get("prvgrpName") or "").strip(),
                "author": "A co-owner",
                "group": (d.get("prvgrpName") or "").strip(),
                "views": d.get("views") or 0,
                "when": when,
            })
        rows = [r for r in rows if r["title"]]
        if log:
            log("community: %d thread(s) readable" % len(rows))
        return {"threads": rows[:5], "count": len(rows)}
    except Exception as exc:
        if log:
            log("community: unavailable (%s)" % type(exc).__name__, "warn")
        return {"threads": [], "count": 0, "error": str(exc)[:120]}


# --------------------------------------------------------------------------- everything
def collect(cfg, ownernumber, log=None, want_prices=True):
    from . import db
    keys = ("owners", "production", "activity", "radius", "probability",
            "operator_summary", "community")
    colls = {k: db.coll(k) for k in keys}

    port = identity(cfg, colls, ownernumber, log)
    if not port["lease_count"]:
        raise ValueError("Owner record %s has no leases in the %s roll."
                         % (ownernumber, cfg["owner"]["year"]))

    lease_ids = port["lease_ids"]

    # The five reads below share no state and no ordering, so running them in series is pure
    # wall-clock waste. MEASURED on this 148-lease record, serially: production 19.9s, activity
    # 10.8s, radius 6.7s, probability 2.0s, prices ~2s = ~41s. Concurrently the panel waits for
    # the slowest one, not the sum. Each thread gets its own cursor from the same pooled client.
    from concurrent.futures import ThreadPoolExecutor

    def _prices():
        if not want_prices:
            return {}
        return prices_mod.live(cfg)

    with ThreadPoolExecutor(max_workers=5) as ex:
        f_prod = ex.submit(production, cfg, colls, lease_ids, log)
        f_act = ex.submit(activity, cfg, colls, lease_ids, log)
        f_rad = ex.submit(radius, cfg, colls, lease_ids, log)
        f_prob = ex.submit(probability, cfg, colls, lease_ids, log)
        f_comm = ex.submit(community, cfg, colls, port["counties"], log)
        f_px = ex.submit(_prices)
        prod, act = f_prod.result(), f_act.result()
        rad, prob = f_rad.result(), f_prob.result()
        comm, px = f_comm.result(), f_px.result()

    ops = operators(cfg, colls, prod["per_lease"], log)
    if want_prices and log:
        ok = [k for k, v in px.items() if not v.get("error")]
        log("prices: %d of %d live quote(s)" % (len(ok), len(px)), "done" if ok else "warn")

    # Merge the roll's interest and appraised value onto each lease's production facts, so the
    # alert builder never has to join them a second time.
    for lease in port["leases"]:
        lease.update(prod["per_lease"].get(lease["lease_id"], {}))

    return {
        "owner": port,
        "production": prod,
        "activity": act,
        "radius": rad,
        "probability": prob,
        "operators": ops,
        "community": comm,
        "prices": px,
        "window": {
            "as_of": prod["as_of"],
            "as_of_label": prod["as_of_label"],
            "activity_days": cfg["window"]["activity_days"],
            "built_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "today": datetime.date.today().isoformat(),
        },
    }
