# -*- coding: utf-8 -*-
"""Measured facts in, ranked alerts out. PORTFOLIO-WIDE, never one lease.

THE RULE THIS MODULE IS BUILT AROUND

  An alert is about the OWNER'S POSITION, not about whichever lease happened to sort first.
  The earlier version picked a single lease per alert - the biggest producer, the newest filing -
  and it read like a portfolio of one. Brown Jon S holds 103 leases; an alert that names one of
  them and stays silent about the other 102 is not an alert about their minerals.

  So every alert here answers three questions in this order:

      how many of your leases does this touch?
      which ones matter most?
      what is the total across all of them?

  A lease name appears only as an EXAMPLE of a counted set - "across 61 leases, largest three:
  A, B, C" - never as the whole finding. `_across()` builds that phrase once so no alert can
  quietly regress to a single-lease headline.

THE CONTRACT THE UI MAKES, AND THIS MODULE HAS TO KEEP

  Every alert row in the redesign's app-alerts section carries eight things, so every alert
  built here carries the same eight or it cannot render:

    title · body · category · delivery_class · why · event_date + detected · channels · deep_link

  `why` is the text behind the row's "why?" control. It is REQUIRED, never optional: the control
  is on every row, and an empty tooltip is a visible defect rather than a missing nicety.

TWO DATES, ALWAYS
  The event date comes from the filing; `detected` is when our sweep saw it. An old filing newly
  matched to the record says so. They are separate fields and are never collapsed.

DELIVERY CLASSES, FROM THE DESIGN
  urgent · digest · educational · community · account

NOTHING IS INVENTED TO FILL THE LIST
  A quiet portfolio produces a short list and the page says so.
"""
import datetime

from . import ymd

MONEY, ACTIVITY, COMMUNITY, MODEL = "money", "activity", "community", "model"
URGENT, DIGEST, EDU, COMMUNITY_CLS, ACCOUNT = "urgent", "digest", "educational", "community", "account"

CLASS_LABEL = {
    URGENT: "Urgent", DIGEST: "Important digest", EDU: "Educational",
    COMMUNITY_CLS: "Community", ACCOUNT: "Account / record update",
}
CLASS_CHIP = {
    URGENT: "chip-est", DIGEST: "chip-slate", EDU: "chip-slate",
    COMMUNITY_CLS: "chip-mint", ACCOUNT: "chip-blue",
}

TYPE_LABEL = {
    "payment_gap":     "Possible payment gap (Lease Audit)",
    "production":      "New production posted",
    "trend":           "Twelve-month production trend",
    "permit_nearby":   "New permit or completion near a lease",
    "permit_new":      "New drilling permits on your leases",
    "completion":      "New completions on your leases",
    "well_status":     "Well status changes",
    "operator_change": "Operator changes on your leases",
    "prod_swing":      "Unusual production changes",
    "price":           "Price move touched your estimate",
    "probability":     "New-well probability bands",
    "community":       "A co-owner posted in your group",
    "record_refresh":  "Owner-record roll refreshed",
    "idle":            "Leases with no production",
}


def type_label(sid):
    return TYPE_LABEL.get(sid.split(":")[0], "Alert")


# What the reader is told the number came from. Never a collection or column name: a public page
# naming our schema is disclosure, and the RRC filing is more useful to an owner anyway - they
# can go and look it up. The internal source stays in the payload for checking a figure.
PUBLIC_SOURCE = {
    "payment_gap":     "RRC Form PR - reported production months",
    "production":      "RRC Form PR - monthly production volumes",
    "trend":           "RRC Form PR - monthly production volumes",
    "permit_nearby":   "RRC Drilling Permits (W-1) - 1-mile radius",
    "permit_new":      "RRC Drilling Permits (W-1)",
    "completion":      "RRC Completions (W-2 / G-1)",
    "well_status":     "RRC well status roll",
    "operator_change": "Derived: Form P-4 operator-transfer mapping",
    "prod_swing":      "RRC Form PR - month-over-month volumes",
    "price":           "NYMEX front-month settlement feed",
    "probability":     "Derived: new-well probability model",
    "community":       "Your private lease groups",
    "record_refresh":  "County appraisal mineral-owner roll",
    "idle":            "RRC lease status roll",
}


def public_source(sid):
    """A signal with no mapping must not leak the internal string by defaulting to it."""
    return PUBLIC_SOURCE.get(sid.split(":")[0], "Texas Railroad Commission public record")


def _fmt(n, unit=""):
    if n is None:
        return "-"
    a = abs(n)
    if a >= 1e9:
        s = "%.2fB" % (n / 1e9)
    elif a >= 1e6:
        s = "%.2fM" % (n / 1e6)
    else:
        s = "{:,.0f}".format(n)
    return (s + " " + unit).strip()


def _pc(p, d=1):
    return "-" if p is None else "%+.*f%%" % (d, p)


def _n(i):
    return "{:,}".format(int(i))


def _plural(i, one, many=None):
    return one if i == 1 else (many or one + "s")


def _ev(why, rows, method, series=None):
    return {"why": why, "rows": [r for r in rows if r], "method": method, "series": series or []}


def _a(**kw):
    """One alert. Defaults keep the eight-field contract impossible to forget."""
    kw.setdefault("category", ACTIVITY)
    kw.setdefault("delivery_class", DIGEST)
    kw.setdefault("channels", ["in-app"])
    kw.setdefault("actions", [])
    kw.setdefault("weight", 0.0)
    kw.setdefault("evidence", None)
    kw.setdefault("event_date", None)
    kw.setdefault("detected", None)
    kw.setdefault("lease_count", 0)
    kw["class_label"] = CLASS_LABEL[kw["delivery_class"]]
    kw["class_chip"] = CLASS_CHIP[kw["delivery_class"]]
    kw["public"] = public_source(kw["id"])
    kw["type_label"] = type_label(kw["id"])
    if not kw.get("why"):
        raise ValueError("alert %s has no 'why' - the UI puts a why? control on every row"
                         % kw["id"])
    return kw


def build(facts, cfg):
    """-> the ranked alert list, every entry measured across the whole portfolio."""
    out = []
    own, prod, act = facts["owner"], facts["production"], facts["activity"]
    rad, prob, ops = facts["radius"], facts["probability"], facts["operators"]
    px, comm = facts["prices"], facts["community"]
    today = datetime.date.today()
    as_of, as_of_label = prod["as_of"], prod["as_of_label"]
    total_leases = own["lease_count"]

    # ---------------------------------------------------------------- shared helpers
    #
    # A lease is shown by NAME. per_lease only carries leases that have a production record, so
    # one known only to the owner roll fell through to its raw "08_29581" id - an internal key,
    # shown to the person who owns the thing.
    _names = {l["lease_id"]: l.get("lease_name") for l in own["leases"] if l.get("lease_name")}
    _county = {l["lease_id"]: l.get("county") for l in own["leases"]}

    def lname(lease_id):
        got = (prod["per_lease"].get(lease_id, {}).get("lease_name") or _names.get(lease_id))
        if got:
            return got
        num = lease_id.split("_", 1)[-1] if "_" in lease_id else lease_id
        c = _county.get(lease_id)
        return "lease %s%s" % (num, (" in %s County" % c) if c else "")

    def _across(ids, limit=3):
        """'61 of your 103 leases, largest three: A, B and C'.

        THE ANTI-REGRESSION. Every portfolio alert routes its headline through this, so the
        count is always first and a lease name can only ever appear as an example of a counted
        set. An alert cannot silently become a single-lease alert again without deleting this.
        """
        ids = list(ids)
        n = len(ids)
        head = "%s of your %s %s" % (_n(n), _n(total_leases), _plural(total_leases, "lease"))
        if not n:
            return head, ""
        shown = [lname(i) for i in ids[:limit]]
        if n == 1:
            return head, shown[0]
        if n <= limit:
            names = ", ".join(shown[:-1]) + " and " + shown[-1]
        else:
            names = ", ".join(shown) + " and %s more" % _n(n - limit)
        return head, names

    def _lease_rows(ids, value_of, note_of=None, limit=6):
        """Evidence rows: the biggest contributors, then an explicit 'and N more' line.

        The remainder line matters. A table showing six of sixty-one leases with no note reads
        as the whole set, and the reader has no way to tell.
        """
        ids = list(ids)
        rows = [{"k": lname(i), "v": value_of(i),
                 "note": (note_of(i) if note_of else "")} for i in ids[:limit]]
        if len(ids) > limit:
            rows.append({"k": "and %s more" % _n(len(ids) - limit), "v": "",
                         "note": "same finding, smaller contribution"})
        return rows

    # ================================================================ 1 · payment gap (URGENT)
    #
    # The flagship alert, and the one the subscription argument rests on. Built the only honest
    # way available: production is public, payment is not. It NEVER says an owner was underpaid.
    # It says how many of their leases the state record shows production on, and hands the rest
    # to the Lease Audit.
    paid = {}
    for lease in own["leases"]:
        lid = lease["lease_id"]
        months = [r for r in (prod["by_lease"].get(lid) or []) if r["monthly_boe"] > 0]
        if months:
            paid[lid] = months
    if paid:
        ranked = sorted(paid, key=lambda i: -sum(m["monthly_boe"] for m in paid[i]))
        head, names = _across(ranked)
        total_boe = sum(m["monthly_boe"] for ms in paid.values() for m in ms)
        total_months = sum(len(ms) for ms in paid.values())
        all_cycles = sorted({m["cycle_year_month"] for ms in paid.values() for m in ms},
                            reverse=True)
        out.append(_a(
            id="payment_gap",
            kind="check", icon="✓", icon_class="gold",
            category=MONEY, delivery_class=URGENT,
            channels=["email", "push", "in-app"],
            lease_count=len(paid),
            title="Payment check worth running on %s" % head,
            body=("The public record shows production on %s across %s reported %s, %s to %s. "
                  "Largest: %s. Whether you were paid for those months cannot be known until "
                  "your statements are compared - that is what a Lease Audit does. Worth a look, "
                  "not a panic."
                  % (head, _n(total_months), _plural(total_months, "month"),
                     ymd.cycle_pretty(all_cycles[-1]), ymd.cycle_pretty(all_cycles[0]), names)),
            why=("Why you're seeing this: produced-month versus payment questions on leases you "
                 "own are the one class we escalate immediately - it is the money check the "
                 "service exists for. Urgent alerts always reach every channel you have enabled."),
            event_date=ymd.parse_date(all_cycles[0]), detected=today,
            deep_link="#/app/audit",
            actions=[{"label": "Run your included Lease Audit", "href": "#/app/audit", "primary": True},
                     {"label": "See a sample report", "href": "#/app/audit/report"}],
            source="MonthlyProductionVolumes - reported months with BOE > 0, every claimed lease",
            weight=1000,
            evidence=_ev(
                why=("Production is a public filing. Payment is private. This reports only the "
                     "first half - the months your operators told the state they produced - "
                     "because that is the half that can be proven. Comparing it to what reached "
                     "you is the audit."),
                rows=([{"k": "Leases with production", "v": "%s of %s" % (_n(len(paid)), _n(total_leases)),
                        "note": "every claimed lease was checked, not a sample"},
                       {"k": "Reported months", "v": _n(total_months),
                        "note": "%s to %s" % (ymd.cycle_pretty(all_cycles[-1]),
                                              ymd.cycle_pretty(all_cycles[0]))},
                       {"k": "Volume in those months", "v": _fmt(total_boe, "BOE"),
                        "note": "gross lease volume - your share is that times your decimal"},
                       {"k": "Your interest across them", "v": "%.6f" % own["interest_total"],
                        "note": "summed over the %s roll" % own["year"]}] +
                      _lease_rows(ranked,
                                  lambda i: _fmt(sum(m["monthly_boe"] for m in paid[i]), "BOE"),
                                  lambda i: "%s reported %s" % (_n(len(paid[i])),
                                                                _plural(len(paid[i]), "month")))),
                method=("Every claimed lease, every month reported to the state with volume above "
                        "zero, from %s to %s. Nothing is sampled and no lease is excluded."
                        % (ymd.cycle_pretty(cfg["window"]["from_cycle"]), as_of_label)),
                series=prod["series"])))

    # ================================================================ 2 · production posted
    if prod["latest_rows"]:
        by_lease = {}
        for r in prod["latest_rows"]:
            by_lease[r["id"]] = by_lease.get(r["id"], 0.0) + r["monthly_boe"]
        ranked = sorted(by_lease, key=lambda i: -by_lease[i])
        head, names = _across(ranked)
        month_boe = sum(by_lease.values())
        op_names = sorted({(prod["per_lease"].get(i, {}).get("operator") or "").strip()
                           for i in ranked} - {""})
        out.append(_a(
            id="production",
            kind="up", icon="▤", icon_class="",
            category=ACTIVITY, delivery_class=DIGEST,
            channels=["push", "in-app"],
            lease_count=len(by_lease),
            title="New production posted on %s for %s" % (head, as_of_label),
            body=("%s reported %s across %s for %s. Largest: %s. A posting is a production "
                  "fact, not a payment."
                  % ("%s %s" % (_n(len(op_names)), _plural(len(op_names), "operator"))
                     if len(op_names) > 2 else (" and ".join(op_names) or "Your operators"),
                     _fmt(month_boe, "BOE"), head, as_of_label, names)),
            why=("Why you're seeing this: public production postings on leases you own. A "
                 "production fact, not a payment - digest-class because postings arrive in "
                 "monthly batches rather than one at a time."),
            event_date=ymd.parse_date(as_of), detected=today,
            deep_link="#/app/activities",
            actions=[{"label": "Open my leases", "href": "#/app/leases"}],
            source="MonthlyProductionVolumes - newest reported cycle, every claimed lease",
            weight=520,
            evidence=_ev(
                why=("BOE is barrels of oil equivalent - one barrel of oil, or the gas carrying "
                     "the same energy. Mineral View converts at 15 Mcf to the barrel, the ratio "
                     "the rest of the portal uses."),
                rows=([{"k": "Leases that posted", "v": "%s of %s" % (_n(len(by_lease)), _n(total_leases)),
                        "note": "in %s" % as_of_label},
                       {"k": "Total for the month", "v": _fmt(month_boe, "BOE"),
                        "note": "gross across those leases"},
                       {"k": "Operators reporting", "v": _n(len(op_names)),
                        "note": ", ".join(op_names[:4]) + (" +%d" % (len(op_names) - 4)
                                                           if len(op_names) > 4 else "")}] +
                      _lease_rows(ranked, lambda i: _fmt(by_lease[i], "BOE"),
                                  lambda i: prod["per_lease"].get(i, {}).get("operator") or "")),
                method=("Read on demand from the state's monthly production filings for your "
                        "claimed leases only, not from a pre-computed copy. The newest month with "
                        "a filed report is %s - later months exist in the record but carry no "
                        "filing yet, so they are not treated as zero production." % as_of_label),
                series=prod["series"])))

    # ================================================================ 3 · twelve-month trend
    if prod["ttm_pct"] is not None and prod["ttm_boe"]:
        p = prod["ttm_pct"]
        movers = sorted((i for i, v in prod["per_lease"].items() if v.get("ttm_boe")),
                        key=lambda i: -prod["per_lease"][i]["ttm_boe"])
        out.append(_a(
            id="trend",
            kind="up" if p >= 0 else "down", icon="📈" if p >= 0 else "📉", icon_class="",
            category=ACTIVITY, delivery_class=DIGEST,
            lease_count=len(movers),
            title="Your %s leases produced %s over the last twelve months"
                  % (_n(total_leases), _pc(p)),
            body=("%s BOE in the twelve months to %s against %s the year before, across %s "
                  "producing %s of the %s you hold."
                  % (_fmt(prod["ttm_boe"]), as_of_label, _fmt(prod["prev_ttm_boe"]),
                     _n(prod["producing_leases"]), _plural(prod["producing_leases"], "lease"),
                     _n(total_leases))),
            why=("Why you're seeing this: the direction of production across everything you own "
                 "is the single number that best predicts what your royalty does next. "
                 "Digest-class - it moves slowly and never needs same-day action."),
            event_date=ymd.parse_date(as_of), detected=today,
            deep_link="#/app/activities?tab=trend",
            actions=[{"label": "Open the trend", "href": "#/app/activities?tab=trend"}],
            source="MonthlyProductionVolumes - TTM BOE against the prior twelve months",
            weight=460 + min(abs(p), 200),
            evidence=_ev(
                why=("TTM means trailing twelve months. Comparing a rolling year against the year "
                     "before removes the seasonality that makes any single month look dramatic."),
                rows=([{"k": "Last 12 months", "v": _fmt(prod["ttm_boe"], "BOE"),
                        "note": "to %s, all leases" % as_of_label},
                       {"k": "Twelve before that", "v": _fmt(prod["prev_ttm_boe"], "BOE"), "note": ""},
                       {"k": "Change", "v": _pc(p), "note": "gross lease volume, not your share"},
                       {"k": "Last 3 months", "v": _fmt(prod["recent_boe"], "BOE"),
                        "note": "%s against %s in %s" % (prod["recent_label"],
                                                         _fmt(prod["prior_boe"]), prod["prior_label"])},
                       {"k": "Producing leases", "v": "%s of %s" % (_n(prod["producing_leases"]),
                                                                    _n(total_leases)),
                        "note": "reported volume in %s" % as_of_label}] +
                      _lease_rows(movers, lambda i: _fmt(prod["per_lease"][i]["ttm_boe"], "BOE"),
                                  lambda i: "%s · %s" % (prod["per_lease"][i].get("operator") or "-",
                                                         prod["per_lease"][i].get("status") or ""))),
                method=("Every claimed lease's monthly volume summed over the twelve cycles ending "
                        "%s, against the twelve before. Anchored on the newest month anyone "
                        "actually reported, not on today - production posts on a lag." % as_of_label),
                series=prod["series"])))

    # ================================================================ 4 · nearby permits
    if rad["permit_count"]:
        r_label = ("%g" % rad["radius_used"]) if rad["radius_used"] else "1"
        per = sorted(rad["by_lease"], key=lambda i: -len(rad["by_lease"][i]["permits"]))
        head, names = _across([i for i in per if rad["by_lease"][i]["permits"]])
        out.append(_a(
            id="permit_nearby",
            kind="flag", icon="⚑", icon_class="",
            category=ACTIVITY, delivery_class=DIGEST,
            channels=["email", "push", "in-app"],
            lease_count=rad["covered"],
            title="%s standing permits within %s mile of your leases"
                  % (_n(rad["permit_count"]), r_label),
            body=("Across %s the state record carries %s standing %s and %s neighbouring %s "
                  "inside about %s mile. Most permits sit near: %s. A neighbour's well is a "
                  "signal, not your income - but permits this close keep operators interested "
                  "in your area."
                  % (head, _n(rad["permit_count"]), _plural(rad["permit_count"], "permit"),
                     _n(rad["adjacent_count"]), _plural(rad["adjacent_count"], "lease"),
                     r_label, names)),
            why=("Why you're seeing this: activity within about a mile of leases you own. Context "
                 "for your area, not income - it can roll up weekly if you would rather not hear "
                 "about each permit."),
            event_date=ymd.parse_date(rad["rebuilt"]), detected=today,
            deep_link="#/app/map",
            actions=[{"label": "View on the map", "href": "#/app/map"}],
            source="LeaseRadiusData - the nearby permit and lease lists at the tightest radius",
            weight=430,
            evidence=_ev(
                why=("A drilling permit is a filing saying someone intends to drill. It is not a "
                     "well and not a payment. What it tells you is that your area is still worth "
                     "spending money on."),
                rows=([{"k": "Standing permits", "v": _n(rad["permit_count"]),
                        "note": "de-duplicated across all your leases"},
                       {"k": "Adjacent leases", "v": _n(rad["adjacent_count"]),
                        "note": "distinct leases, not wellbores - yours excluded"},
                       {"k": "Radius", "v": "%s mile" % r_label, "note": "the tightest ring on record"},
                       {"k": "Your leases covered", "v": "%s of %s" % (_n(rad["covered"]),
                                                                       _n(total_leases)),
                        "note": "leases carrying a radius record"},
                       {"k": "Ring rebuilt", "v": rad["rebuilt"] or "-",
                        "note": "when the radius set was last rebuilt, not when a permit was filed"}] +
                      _lease_rows(per, lambda i: _n(len(rad["by_lease"][i]["permits"])),
                                  lambda i: "%s adjacent leases"
                                            % _n(len(rad["by_lease"][i]["leases"])))),
                method=("The nearby permit and lease lists are held per lease and radius, parsed "
                        "to sets and combined, so a permit near two of your leases counts once. "
                        "The rebuild stamp is the same on every lease in the state, so it dates "
                        "the ring's last rebuild and cannot date an individual permit."))))

    # ================================================================ 5 · live price
    live = [q for q in (px.get("gas"), px.get("wti"), px.get("brent"))
            if q and not q.get("error") and q.get("change_pct") is not None]
    if live:
        thresh = cfg["prices"]["move_threshold_pct"]
        mover = max(live, key=lambda q: abs(q["change_pct"]))
        moved = abs(mover["change_pct"]) >= thresh
        stamp = mover.get("as_of_epoch")
        stamp_d = datetime.datetime.fromtimestamp(stamp) if stamp else None
        bits = ", ".join("%s %s (%s)" % (q["label"],
                                         ("$%.3f" if "MMBtu" in q["unit"] else "$%.2f") % q["price"],
                                         _pc(q["change_pct"], 2)) for q in live)
        gassy = sum(1 for v in prod["per_lease"].values()
                    if (v.get("status") or "").strip() and v.get("ttm_boe"))
        out.append(_a(
            id="price",
            kind="up" if mover["change_pct"] >= 0 else "down",
            icon="▲" if mover["change_pct"] >= 0 else "▼", icon_class="",
            category=MONEY, delivery_class=EDU,
            lease_count=total_leases,
            title=("%s %s %s - it touches every lease you own"
                   % (mover["label"], "up" if mover["change_pct"] >= 0 else "down",
                      _pc(mover["change_pct"], 2))) if moved
                  else "Prices steady - nothing moved your estimate today",
            body=("%s, quoted live on the front-month contract%s. Your estimate follows these "
                  "prices across all %s of your leases, %s of which produced in the last year."
                  % (bits, (" at %s" % stamp_d.strftime("%H:%M")) if stamp_d else "",
                     _n(total_leases), _n(gassy))),
            why=("Why you're seeing this: market context that touches your estimate. "
                 "Educational-class - no action needed, and never a signal to buy, sell or lease."),
            event_date=stamp_d.date() if stamp_d else today, detected=today,
            deep_link="#/app/briefing",
            actions=[{"label": "Why prices moved", "href": "#/app/briefing"}],
            source="NYMEX front-month futures, live intraday quote",
            weight=300 + (60 if moved else 0),
            evidence=_ev(
                why=("These are live front-month futures - the price the market is paying right "
                     "now, not a settlement published last week. Your royalty is paid on the "
                     "price your operator actually realises, which runs below the benchmark by a "
                     "local differential, so treat this as direction rather than as your cheque."),
                rows=([{"k": q["label"],
                        "v": ("$%.3f" if "MMBtu" in q["unit"] else "$%.2f") % q["price"],
                        "note": "%s - previous close %s, %s"
                                % (q["desc"], q.get("prev_close"), _pc(q.get("change_pct"), 2))}
                       for q in live] +
                      [{"k": "Leases affected", "v": _n(total_leases),
                        "note": "a price move touches the whole position, not one lease"},
                       {"k": "Quoted at",
                        "v": stamp_d.strftime("%Y-%m-%d %H:%M") if stamp_d else "-",
                        "note": "exchange time, %s" % (mover.get("exchange") or "NYMEX")},
                       {"k": "Alert threshold", "v": "%.1f%%" % thresh,
                        "note": "below this a move is noise and no alert is raised"}]),
                method=("Front-month futures quoted intraday. The change is measured against the "
                        "previous daily close from the same series - not against the exchange's "
                        "'previous close' field, which on a multi-day range is the close before "
                        "the window and reports an ordinary session as an 8% move."))))

    # ================================================================ 6 · the activity feed
    #
    # ONE alert per event TYPE, aggregated over every lease it touched - not one alert per event.
    # 294 unusual-production rows on 61 leases is one finding about the portfolio; 294 rows in an
    # inbox is a feed, and the page's own promise is that it is not a feed.
    SPEC = {
        1: dict(sid="permit_new", icon="⚑", cls_="", cat=ACTIVITY, cls=DIGEST, kind="add",
                title="%s new drilling %s across %s", noun="permit",
                why=("Why you're seeing this: permits filed on leases you own. A permit is an "
                     "intention to drill, not production - but a new well on your acreage is the "
                     "biggest upside an owner has.")),
        2: dict(sid="completion", icon="✚", cls_="", cat=ACTIVITY, cls=DIGEST, kind="add",
                title="%s new %s across %s", noun="completion",
                why=("Why you're seeing this: a completion means a well on your lease is finished "
                     "and capable of producing. It usually precedes first production by a few "
                     "months.")),
        4: dict(sid="well_status", icon="◐", cls_="", cat=ACTIVITY, cls=DIGEST, kind="flag",
                title="%s well status %s across %s", noun="change",
                why=("Why you're seeing this: wells on your leases changed status in the state "
                     "record. Shut-in, plugged and reactivated all change what a lease can pay "
                     "you.")),
        5: dict(sid="operator_change", icon="⇄", cls_="gold", cat=MONEY, cls=ACCOUNT, kind="swap",
                title="%s operator %s across %s", noun="change",
                why=("Why you're seeing this: the operator of record changed on leases you own. "
                     "Your interest does not change, but who sends your cheque - and how they run "
                     "the lease - does.")),
        6: dict(sid="prod_swing", icon="◈", cls_="", cat=MONEY, cls=DIGEST, kind="flag",
                title="%s unusual production %s across %s", noun="change",
                why=("Why you're seeing this: volumes on these leases moved far enough from the "
                     "lease's own recent pattern to be worth a look. It can be a workover, a new "
                     "well, or a reporting correction.")),
    }
    for aid, spec in SPEC.items():
        evs = act["by_type"].get(aid) or []
        if not evs:
            continue
        touched = {}
        for e in evs:
            touched.setdefault(e["lease_id"], []).append(e)
        ranked = sorted(touched, key=lambda i: -len(touched[i]))
        head, names = _across(ranked)
        dated = [e["event_date"] for e in evs if e["event_date"]]
        newest = max(dated) if dated else None
        oldest = min(dated) if dated else None
        detected = next((e["detected"] for e in evs if e.get("detected")), today)
        operators = sorted({e["operator"] for e in evs if e["operator"]})
        notes = [e["note"] for e in evs if e["note"]]

        out.append(_a(
            id=spec["sid"],
            kind=spec["kind"], icon=spec["icon"], icon_class=spec["cls_"],
            category=spec["cat"], delivery_class=spec["cls"],
            channels=["email", "push", "in-app"] if aid == 5 else ["in-app"],
            lease_count=len(touched),
            title=spec["title"] % (_n(len(evs)), _plural(len(evs), spec["noun"]), head),
            body=("%s %s recorded on %s%s. Most affected: %s.%s"
                  % (_n(len(evs)), _plural(len(evs), spec["noun"]), head,
                     (", %s to %s" % (ymd.date_pretty(oldest), ymd.date_pretty(newest)))
                     if newest and oldest and newest != oldest else "",
                     names,
                     (" Example: %s" % notes[0][:110]) if notes else "")),
            why=spec["why"],
            event_date=newest, detected=detected,
            deep_link="#/app/activities",
            actions=[{"label": "Open activities", "href": "#/app/activities"}],
            source="Activity_Test - activity_id %s, aggregated over every claimed lease" % aid,
            weight=420 - aid * 8 + (40 if aid == 5 else 0) + min(len(touched), 40),
            evidence=_ev(
                why=spec["why"].split(": ", 1)[-1],
                rows=([{"k": "Events", "v": _n(len(evs)),
                        "note": "on %s of your %s leases" % (_n(len(touched)), _n(total_leases))},
                       {"k": "Window",
                        "v": "%s to %s" % (ymd.date_pretty(oldest), ymd.date_pretty(newest))
                             if newest else "-",
                        "note": "filing dates as recorded by the state"},
                       ({"k": "Operators involved", "v": _n(len(operators)),
                         "note": ", ".join(operators[:4]) + (" +%d" % (len(operators) - 4)
                                                             if len(operators) > 4 else "")}
                        if operators else None)] +
                      _lease_rows(ranked, lambda i: _n(len(touched[i])),
                                  lambda i: (touched[i][0]["note"] or
                                             touched[i][0]["operator"] or "")[:80])),
                method=("Read from the live activity feed, filtered to every one of your claimed "
                        "lease numbers and grouped by event type. Dates are parsed rather than "
                        "sliced out of the stored string - the feed carries leading and trailing "
                        "spaces that a substring would silently mis-bucket."))))

    # ================================================================ 7 · probability bands
    if prob["scored"]:
        bands = {}
        for s in prob["scored"]:
            bands[s["category"]] = bands.get(s["category"], 0) + 1
        order = [b[0] for b in prob["bands"]][::-1]
        band_txt = ", ".join("%s in %s" % (_n(bands[b]), b) for b in order if bands.get(b))
        ranked = [s["lease_id"] for s in prob["scored"]]
        head, names = _across(ranked)
        top = prob["scored"][0]
        out.append(_a(
            id="probability",
            kind="model", icon="◈", icon_class="blue",
            category=MODEL, delivery_class=EDU,
            lease_count=prob["count"],
            title="New-well probability scored on %s" % head,
            body=("Across your position the indicator reads %s. Highest: %s at %.0f out of 100 "
                  "(%s band)%s. Directional only - we never show a made-up percentage."
                  % (band_txt, lname(top["lease_id"]), top["probability"], top["category"],
                     ", and %s %s not modelled yet"
                     % (_n(prob["unmodelled"]), _plural(prob["unmodelled"], "lease is", "leases are"))
                     if prob["unmodelled"] else "")),
            why=("Why you're seeing this: a directional model indicator across your acreage. "
                 "Educational-class - context to understand, not a prediction to act on. A new "
                 "well on your acreage is the biggest upside an owner has, which is why the "
                 "indicator is worth watching even though it is not a forecast."),
            event_date=today, detected=today,
            deep_link="#/app/leases",
            actions=[{"label": "See the why", "href": "#/app/leases"}],
            source="Data_to_web - NEW WELL PROBABILITY and its category band, every claimed lease",
            weight=280 + min(prob["count"], 40),
            evidence=_ev(
                why=("A spacing-based indicator of how likely a new well is on or beside each "
                     "lease. It is a band, not a forecast, and it says nothing about when."),
                rows=([{"k": "Leases modelled", "v": "%s of %s" % (_n(prob["count"]), _n(total_leases)),
                        "note": "%s carry the not-modelled marker" % _n(prob["unmodelled"])},
                       {"k": "Portfolio average",
                        "v": "%.1f / 100" % prob["average"] if prob["average"] is not None else "-",
                        "note": "modelled leases only"}] +
                      [{"k": b, "v": _n(bands[b]),
                        "note": next("%g-%g out of 100" % (x[1], x[2])
                                     for x in prob["bands"] if x[0] == b)}
                       for b in order if bands.get(b)] +
                      _lease_rows(ranked, lambda i: "%.0f / 100"
                                  % next(s["probability"] for s in prob["scored"]
                                         if s["lease_id"] == i),
                                  lambda i: next(s["category"] for s in prob["scored"]
                                                 if s["lease_id"] == i))),
                method=("Read per lease from the decline model's published probability and its "
                        "band, for every claimed lease. Leases carrying the not-modelled marker "
                        "are excluded entirely rather than shown as zero - telling an owner their "
                        "acreage scores nothing, when the truth is that it has not been modelled, "
                        "is the worse error."),
                series=[{"label": lname(s["lease_id"])[:6], "value": s["probability"],
                         "on": s["lease_id"] == top["lease_id"]}
                        for s in prob["scored"][:12]])))

    # ================================================================ 8 · idle leases
    #
    # The quiet finding. A lease that reported nothing is not an absence of news - for an owner
    # it is the difference between a producing position and a smaller one, and nothing else on
    # the page would ever mention it.
    idle = [l["lease_id"] for l in own["leases"]
            if prod["per_lease"].get(l["lease_id"], {}).get("latest_boe", 0) <= 0]
    if idle and prod["producing_leases"]:
        head, names = _across(idle)
        no_record = [i for i in idle if i not in prod["by_lease"]]
        out.append(_a(
            id="idle",
            kind="flag", icon="◌", icon_class="",
            category=ACTIVITY, delivery_class=EDU,
            lease_count=len(idle),
            title="%s reported no production in %s" % (head, as_of_label),
            body=("%s of your leases posted nothing for %s: %s.%s Idle is normal - a lease can "
                  "be between wells, shut in, or simply not reported yet - but it is the half of "
                  "your position that is not earning."
                  % (_n(len(idle)), as_of_label, names,
                     (" %s %s no production record at all."
                      % (_n(len(no_record)),
                         _plural(len(no_record), "lease has", "leases have")))
                     if no_record else "")),
            why=("Why you're seeing this: leases you own that reported no volume in the newest "
                 "month. Educational-class - it needs no action, but a position is easier to "
                 "read when the quiet part of it is named rather than left out."),
            event_date=ymd.parse_date(as_of), detected=today,
            deep_link="#/app/leases",
            actions=[{"label": "Open my leases", "href": "#/app/leases"}],
            source="MonthlyProductionVolumes - claimed leases with no volume in the as-of cycle",
            weight=190,
            evidence=_ev(
                why=("A lease with no volume this month is not necessarily a dead lease. It may "
                     "be awaiting a filing, shut in for work, or between wells. What it is not is "
                     "income this month."),
                rows=([{"k": "Idle this month", "v": "%s of %s" % (_n(len(idle)), _n(total_leases)),
                        "note": "no volume reported for %s" % as_of_label},
                       {"k": "Producing this month", "v": _n(prod["producing_leases"]),
                        "note": "reported volume above zero"},
                       ({"k": "No production record", "v": _n(len(no_record)),
                         "note": "never appeared in the monthly filings"} if no_record else None)] +
                      _lease_rows(idle,
                                  lambda i: prod["per_lease"].get(i, {}).get("status") or "no record",
                                  lambda i: "%s · last %s"
                                            % (prod["per_lease"].get(i, {}).get("operator") or "-",
                                               ymd.cycle_pretty(
                                                   prod["per_lease"].get(i, {}).get("latest_cycle"))
                                               if prod["per_lease"].get(i, {}).get("latest_cycle")
                                               else "never"))),
                method=("Each claimed lease's volume in the as-of cycle %s. Read from the as-of "
                        "month specifically, not from whichever row is newest - the newest row is "
                        "usually a month nobody has filed for yet, which would report the whole "
                        "portfolio as idle." % as_of_label))))

    # ================================================================ 9 · community
    if comm["threads"]:
        th = comm["threads"][0]
        out.append(_a(
            id="community",
            kind="community", icon="◉", icon_class="",
            category=COMMUNITY, delivery_class=COMMUNITY_CLS,
            channels=["push", "in-app"],
            lease_count=0,
            title="A co-owner posted in %s" % (th["group"] or "a group you belong to"),
            body=("“%s”%s"
                  % (th["title"][:150],
                     " Plus %s other recent %s."
                     % (_n(len(comm["threads"]) - 1), _plural(len(comm["threads"]) - 1, "thread"))
                     if len(comm["threads"]) > 1 else "")),
            why=("Why you're seeing this: activity in a private lease group you belong to. "
                 "Community-class - you can mute any group's notifications without leaving it."),
            event_date=th["when"], detected=today,
            deep_link="#/app/groups",
            actions=[{"label": "Open the thread", "href": "#/app/groups"}],
            source="privategroupthreads - recent threads in the owner's groups",
            weight=240,
            evidence=_ev(
                why=("Co-owners on the same lease often know things the public record does not - "
                     "who the landman called, what the operator said. The group is where that "
                     "gets shared."),
                rows=[{"k": "Thread", "v": th["title"][:70], "note": th["group"] or ""},
                      {"k": "Posted", "v": ymd.date_pretty(th["when"]),
                       "note": ymd.ago(th["when"], today)},
                      {"k": "Recent threads", "v": _n(len(comm["threads"])), "note": ""}],
                method="The most recent threads in the private groups attached to this record.")))

    # ================================================================ 10 · record refresh
    out.append(_a(
        id="record_refresh",
        kind="add", icon="✚", icon_class="gold",
        category=MONEY, delivery_class=ACCOUNT,
        lease_count=0,
        title="The %s mineral-owner roll matched %s other %s in your name"
              % (own["year"], _n(facts.get("name_matches", 0)),
                 _plural(facts.get("name_matches", 0), "record")),
        body=("Your name matches %s other owner %s in the %s roll across %s %s. A matching name "
              "is not proof - and the roll's owner number is a county key, not a person, so those "
              "records may belong to anyone. They stay possible matches until you verify by "
              "address, and none of them is counted in your %s leases."
              % (_n(facts.get("name_matches", 0)),
                 _plural(facts.get("name_matches", 0), "record"), own["year"],
                 _n(facts.get("name_counties", 0)),
                 _plural(facts.get("name_counties", 0), "county", "counties"), _n(total_leases))),
        why=("Why you're seeing this: the mineral-owner roll was refreshed and the new roll "
             "matched your name variants. This fires only on a records refresh - never as a "
             "repeating nag - and a dismissal sticks until the next refresh."),
        event_date=datetime.date(own["year"], 1, 1), detected=today,
        deep_link="#/claim",
        actions=[{"label": "Review in the claim flow", "href": "#/claim"},
                 {"label": "Not mine - dismiss for good", "dismiss": True}],
        source="Mineral_Owners_Data_Master - name matches under other owner numbers",
        weight=200,
        evidence=_ev(
            why=("The roll keys an owner by number within a county, not by name and not "
                 "statewide. A shared name is extremely common and a shared number is not rare "
                 "either, so every other record carrying your name is shown as a possible match "
                 "and nothing more."),
            rows=[{"k": "Your record", "v": "#%s" % own["identity"]["ownernumber"],
                   "note": "%s leases in %s" % (_n(total_leases),
                                                ", ".join(own["counties"][:3]) or "-")},
                  {"k": "Other records, same name", "v": _n(facts.get("name_matches", 0)),
                   "note": "across %s counties" % _n(facts.get("name_counties", 0))},
                  {"k": "Roll year", "v": str(own["year"]),
                   "note": "totals are never summed across years"},
                  {"k": "Counted in your position", "v": "0",
                   "note": "possible matches are excluded until verified"}],
            method=("Grouped by owner record number on an exact name match in the roll for a "
                    "single year. Appraised value is never summed across years - the same "
                    "interest appears in each year's roll and stacking them doubles it."))))

    out.sort(key=lambda a: -a["weight"])
    for i, a in enumerate(out):
        a["rank"] = i
    return out


def counts(alerts):
    """Category counts, derived from the SAME list the filter renders.

    The mockup's own note records that the ledger and the filter row were two hand-kept copies
    of one fact, so adding a row made the panel lie. One derivation, one truth.
    """
    c = {"all": len(alerts), "money": 0, "activity": 0, "community": 0, "model": 0, "action": 0}
    for a in alerts:
        c[a["category"]] = c.get(a["category"], 0) + 1
        if a["delivery_class"] == URGENT:
            c["action"] += 1
    return c
