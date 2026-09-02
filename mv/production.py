# -*- coding: utf-8 -*-
"""Production activity, computed on demand from MonthlyProductionVolumes.

THIS IS Production_Activity_API_Spec.md SECTION 4, IMPLEMENTED.

  The spec replaces the stored ProdMvestPortal.Activity_Production collection - 2,098,077
  pre-computed lease-month documents covering all 386,010 Texas leases - with a request-time
  transform over MonthlyProductionVolumes, run only for the leases a user has actually claimed.

  Everything Activity_Production served came from MonthlyProductionVolumes; nothing was
  enriched, joined or calculated from an outside source. It was a second copy of data we
  already had, in a different shape, growing by ~70,000 documents a month forever, and only as
  fresh as its last rebuild.

  The lookup is cheap because the lease id IS the _id here: "{district_code}_{lease_number}",
  e.g. "04_301329". One lease is a primary-key hit. A claimed portfolio is a handful of them.

FIELD NAMES ARE THE SPEC'S, EXACTLY
  Section 5 requires the output names to match what the stored collection served, so the
  switchover is a no-op for existing consumers. Do not "tidy" these names.

THE TRAILING-ZERO TRAP, MEASURED
  Lease 08_55109 (SOTO 43-7, Diamondback, Martin County) carries cycles 202607 and 202608 with
  BOE 0, prod_report_filed_flag "N" and record_status "New". They are placeholders for months
  that have not been reported yet, not months in which a producing Permian lease made nothing.
  latest_real_cycle() is what the window anchors on; max(cycle) would have this app open by
  announcing that Diamondback had stopped producing.
"""
from . import ymd

# Only these fields are read back. The source documents are ~190 KB each and the data[] rows
# carry allowables, dispositions, condensate and casinghead volumes we do not use - section 3
# of the spec is explicit that pulling whole rows is waste.
PROJECTION = {
    "lease_name": 1, "lease_number": 1, "county": 1, "district_code": 1,
    "current_operator_name": 1, "current_operator_number": 1, "original_operator_number": 1,
    "field_no": 1, "field_name": 1, "oil_gas_code": 1,
    "first_produced_month": 1, "first_produced_year": 1,
    "Totaloilproduction": 1, "Totalgasproduction": 1, "Total_BOE": 1, "Lease_Status": 1,
    "playtype": 1, "reservoir": 1, "lease_acres": 1, "Merged_County": 1,
    "data.cycle_year": 1, "data.cycle_month": 1, "data.cycle_year_month": 1,
    "data.lease_oil_prod_vol": 1, "data.lease_gas_prod_vol": 1, "data.BOE": 1,
    "data.lease_name": 1, "data.operator_name": 1, "data.operator_no": 1,
    "data.prod_report_filed_flag": 1,
}


def _num(v):
    """Section 4, missing-value rule: consumers must never receive null in a numeric field."""
    if v is None:
        return 0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    return f


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def transform(doc, from_cycle=None, to_cycle=None):
    """One MonthlyProductionVolumes document -> the section-4 records, newest month first."""
    if not doc:
        return []
    top_name = (doc.get("lease_name") or "").strip()
    first_production_date = ""
    fm, fy = doc.get("first_produced_month"), doc.get("first_produced_year")
    if fm and fy:
        first_production_date = "%s/%s" % (str(fm).strip(), str(fy).strip())

    base = {
        "activity_id": 3,
        "activity_type": "New Production",
        "id": doc.get("_id"),
        "lease_number": doc.get("lease_number"),
        "county": doc.get("county"),
        "district_code": doc.get("district_code"),
        "current_operator_name": doc.get("current_operator_name"),
        "current_operator_number": doc.get("current_operator_number"),
        "field_no": doc.get("field_no"),
        "field_name": doc.get("field_name"),
        "oil_gas_code": doc.get("oil_gas_code"),
        "first_production_date": first_production_date,
        "total_oil_production": _num(doc.get("Totaloilproduction")),
        "total_gas_production": _num(doc.get("Totalgasproduction")),
        "total_boe": _num(doc.get("Total_BOE")),
        "lease_status": doc.get("Lease_Status"),
    }

    out = []
    for row in doc.get("data") or []:
        cyc = ymd.cycle(row.get("cycle_year"), row.get("cycle_month")) \
            or (str(row.get("cycle_year_month") or "").strip() or None)
        if not cyc:
            continue
        # Fixed-width YYYYMM, so a string compare range-filters correctly - spec section 5.
        if from_cycle and cyc < from_cycle:
            continue
        if to_cycle and cyc > to_cycle:
            continue
        boe = _num(row.get("BOE"))
        rec = dict(base)
        rec.update({
            # Derived rule 2: some leases carry the name only on the monthly rows.
            "lease_name": top_name or (row.get("lease_name") or "").strip(),
            "cycle_year": _int(row.get("cycle_year")),      # spec: return as a number
            "cycle_month": _int(row.get("cycle_month")),    # spec: return as a number
            "cycle_year_month": cyc,                        # spec: keep as a string
            "lease_oil_production": _num(row.get("lease_oil_prod_vol")),
            "lease_gas_production": _num(row.get("lease_gas_prod_vol")),
            "monthly_boe": boe,
            # Derived rule 4. NOT the same as lease_status: a lease can be Producing overall
            # while an individual month had none. Both fields are needed.
            "monthly_lease_status": "Producing" if boe > 0 else "Not Producing",
            # Not in the spec's output list; kept internal so the window can tell an unreported
            # month from a genuinely zero one. Never rendered.
            "_reported": str(row.get("prod_report_filed_flag") or "").strip().upper() != "N",
        })
        out.append(rec)

    out.sort(key=lambda r: r["cycle_year_month"], reverse=True)   # spec: newest first
    return out


def fetch(coll, lease_ids, from_cycle="202501", to_cycle=None, workers=8, chunk=25):
    """GET /activity/production?lease_ids=...&from=... - the whole endpoint.

    Unknown lease id -> absent from the result, never an error (spec section 5): a claimed
    lease may simply have no production record.

    WHY IT IS CHUNKED AND THREADED
      Every lookup is a primary-key seek, so this is never a scan - but the documents are about
      190 KB each and a 148-lease portfolio is ~28 MB over the VPN. Measured, a single $in of
      148 ids took 19.9s; the same ids in chunks of 25 across 8 connections take a third of that.
      The work is identical - only the number of round trips in flight changes.
    """
    ids = [i for i in dict.fromkeys(lease_ids) if i]
    if not ids:
        return {}
    if len(ids) <= chunk or workers <= 1:
        return {d["_id"]: transform(d, from_cycle, to_cycle)
                for d in coll.find({"_id": {"$in": ids}}, PROJECTION)}

    from concurrent.futures import ThreadPoolExecutor
    parts = [ids[i:i + chunk] for i in range(0, len(ids), chunk)]

    def one(batch):
        return {d["_id"]: transform(d, from_cycle, to_cycle)
                for d in coll.find({"_id": {"$in": batch}}, PROJECTION)}

    got = {}
    with ThreadPoolExecutor(max_workers=min(workers, len(parts))) as ex:
        for res in ex.map(one, parts):
            got.update(res)
    return got


def latest_real_cycle(by_lease):
    """The newest cycle anyone actually reported production for.

    Not max(cycle): see the module docstring. A month is real when it was reported AND carried
    volume somewhere in the portfolio. Falls back to the newest reported month, then to the
    newest month at all, so this never returns None on a portfolio that has any rows.
    """
    produced, reported, any_cycle = [], [], []
    for recs in by_lease.values():
        for r in recs:
            any_cycle.append(r["cycle_year_month"])
            if r.get("_reported"):
                reported.append(r["cycle_year_month"])
                if r["monthly_boe"] > 0:
                    produced.append(r["cycle_year_month"])
    for pool in (produced, reported, any_cycle):
        if pool:
            return max(pool)
    return None
