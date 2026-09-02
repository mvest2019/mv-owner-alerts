# -*- coding: utf-8 -*-
"""Resolve a mineral owner to ONE record and its claimed leases.

THE THING THIS MODULE EXISTS TO PREVENT

  MEASURED 2026-09-02 on Mineral_Owners_Data_Master:

      ownername "Brown Jon S"  ->  3,698 rows
                               ->  243 DISTINCT ownernumber values
                               ->  124 counties

  That is not one person with a big portfolio. It is a common name, and the roll keys an owner
  by `ownernumber`, not by name. Summing the name would hand one visitor a position belonging
  to 243 different people and call it theirs - which is precisely the "possible match, not
  proof" rule the product's own claim flow is built around, broken at the source.

  So: resolve_records() lists the name's records and portfolio() reads exactly one of them.

THE YEAR TRAP
  The roll carries Year 2024 AND 2025. Appraised_Value summed across both stacks the same
  interest twice. Every read here filters to a single year, and the year is stated in the
  output so a total can never be quoted without it.
"""
from collections import OrderedDict


def _lease_id(district_code, lease_number):
    """The join key every other collection in this app uses: '{district}_{lease}'.

    MonthlyProductionVolumes, Data_to_web and LeaseRadiusData all key on it, so getting this
    right once is what makes the rest of the app primary-key seeks instead of scans.
    """
    d = (str(district_code or "")).strip()
    l = (str(lease_number or "")).strip()
    if not d or not l:
        return None
    return "%s_%s" % (d, l)


def resolve_records(coll, name, year):
    """Every owner record carrying this name, biggest first. The picker's data."""
    rows = coll.aggregate([
        {"$match": {"ownername": {"$regex": "^%s$" % name.strip(), "$options": "i"},
                    "Year": year}},
        {"$group": {
            "_id": "$ownernumber",
            "rows": {"$sum": 1},
            "counties": {"$addToSet": "$county"},
            "leases": {"$addToSet": {"$concat": [
                {"$ifNull": ["$districtcode", ""]}, "_", {"$ifNull": ["$leasenumber", ""]}]}},
            "appraised": {"$sum": {"$ifNull": ["$Appraised_Value", 0]}},
            "interest": {"$sum": {"$ifNull": ["$Interest_Value", 0]}},
            "city": {"$first": "$ownercity"},
            "address": {"$first": "$owneraddress"},
        }},
        {"$project": {
            "rows": 1, "appraised": 1, "interest": 1, "city": 1, "address": 1,
            "counties": 1,
            "county_count": {"$size": "$counties"},
            "lease_count": {"$size": "$leases"},
        }},
        {"$sort": {"lease_count": -1, "appraised": -1}},
    ])
    out = []
    for r in rows:
        cs = sorted(c for c in (r.get("counties") or []) if c)
        out.append({
            "ownernumber": r["_id"],
            "rows": r.get("rows", 0),
            "lease_count": r.get("lease_count", 0),
            "county_count": r.get("county_count", 0),
            "counties": cs,
            "county_label": ", ".join(cs[:3]) + (" +%d" % (len(cs) - 3) if len(cs) > 3 else ""),
            "appraised": round(r.get("appraised") or 0.0, 2),
            "interest": r.get("interest") or 0.0,
            "city": (r.get("city") or "").strip(),
        })
    return out


def portfolio(coll, ownernumber, year, name=None):
    """One owner record -> the leases they hold, with interest and appraised value.

    `ownernumber` IS NOT A STATEWIDE OWNER ID - THE NAME FILTER IS NOT OPTIONAL

      MEASURED on the 2025 roll: of 420,296 distinct ownernumber values, **127,650 (30.4%) are
      carried by more than one person**, and 127,415 span more than one county. It is a COUNTY
      appraisal-district owner number, so the same integer is reused by unrelated owners in
      different counties. The unique key is (county, ownernumber), not ownernumber.

      Number 708789 in the 2025 roll is seven different people:

          Martin        Brown Jon S              103 leases
          Loving        Puckett Preston I         36
          Stonewall     Mcdaniel James P           2
          Frio          Webb Frank King Sr         4
          Nolan         Hubbard William Murray     1
          Orange        Durkee Oil & Gas LLC       1
          San Patricio  Fischer Todd               1

      Reading this number without the name produced a 148-lease "portfolio" of which 45 leases
      belonged to five strangers - the exact error resolve_records() exists to prevent, made
      again one level down. Pass the name.

    A record can carry several rows for the same lease - separate interest types, or the same
    interest appraised in more than one taxing entity. They are folded per lease, and the fold
    is stated: interest is summed, appraised value is summed, and the interest types are kept
    so the UI can say which kind of interest a lease is held under.
    """
    q = {"ownernumber": ownernumber, "Year": year}
    if name:
        q["ownername"] = {"$regex": "^%s$" % name.strip(), "$options": "i"}
    cur = coll.find(
        q,
        {"ownername": 1, "owneraddress": 1, "ownercity": 1, "county": 1, "districtcode": 1,
         "leasenumber": 1, "leasename": 1, "Interest_Type": 1, "Interest_Value": 1,
         "Appraised_Value": 1, "Year": 1})

    leases = OrderedDict()
    identity = None
    row_count = 0
    for d in cur:
        row_count += 1
        if identity is None:
            identity = {
                "ownernumber": ownernumber,
                "ownername": (d.get("ownername") or "").strip(),
                "ownercity": (d.get("ownercity") or "").strip(),
                "year": d.get("Year"),
            }
        lid = _lease_id(d.get("districtcode"), d.get("leasenumber"))
        if not lid:
            continue
        e = leases.get(lid)
        if e is None:
            e = leases[lid] = {
                "lease_id": lid,
                "lease_number": (str(d.get("leasenumber") or "")).strip(),
                "district_code": (str(d.get("districtcode") or "")).strip(),
                "lease_name": (d.get("leasename") or "").strip(),
                "county": (d.get("county") or "").strip(),
                "interest": 0.0,
                "appraised": 0.0,
                "interest_types": [],
                "rows": 0,
            }
        e["rows"] += 1
        e["interest"] += float(d.get("Interest_Value") or 0.0)
        e["appraised"] += float(d.get("Appraised_Value") or 0.0)
        it = (d.get("Interest_Type") or "").strip()
        if it and it not in e["interest_types"]:
            e["interest_types"].append(it)

    for e in leases.values():
        e["interest"] = round(e["interest"], 9)
        e["appraised"] = round(e["appraised"], 2)

    ordered = sorted(leases.values(), key=lambda e: (-e["appraised"], e["lease_id"]))
    counties = sorted({e["county"] for e in ordered if e["county"]})
    return {
        "identity": identity or {"ownernumber": ownernumber, "ownername": "", "year": year},
        "leases": ordered,
        "lease_ids": [e["lease_id"] for e in ordered],
        "counties": counties,
        "county_count": len(counties),
        "lease_count": len(ordered),
        "row_count": row_count,
        # Stated with its year, always. A total without one is the year-stacking bug.
        "appraised_total": round(sum(e["appraised"] for e in ordered), 2),
        "interest_total": round(sum(e["interest"] for e in ordered), 9),
        "year": year,
    }
