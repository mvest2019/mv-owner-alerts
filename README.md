# Alerts — Brown Jon S, all 103 leases

The redesign build's own owner portal, landing on `#/app/alerts`, with the sample rows replaced
by alerts measured from the live record.

```
Double-click START.bat  →  browser opens on Alerts  →  the alerts build themselves
```

`START.bat` checks Python, installs `pymongo` if missing, builds the page if it is absent,
starts the server and opens the browser. **VPN must be up first** — `ping 10.20.30.1` is the
test; `openvpn-gui` running is not evidence of a live tunnel.

Cold build ~20 s, then instant. The measured alerts render first; the AI rewrites the wording in
place a second later, and the page says which version is on screen.

---

## 1 · The shell is theirs, whole

`web/alerts.html` is `owner-v42.html` — the repo's assembled artifact — with **nothing removed**:

| | |
|---|---|
| **Left sidebar** | 27 nav links across all route groups |
| **Top header** | the pinned value + spot bar (`#mvPinBar`) |
| **Account menu** | the avatar menu, with the **four view densities** inside it |
| **Views** | Ultra · Essentials · Detailed · Professional — driven by *their* `setViewTier()` |
| **Plans** | Free · Pro · Premium — mapped onto their funnel states by `ui.plan_state` |
| **Routes** | all 54 sections, all 20 `<script>` blocks, every `<style>` |

The sibling `dashboard/` build strips 47 routes because it serves one screen. This one must not:
the whole point was that the previous alerts app had no left menu, no header, no view switcher
and no account menu. Those live in the shell, so the shell stays whole.

`tools/build_alerts.py` changes exactly four things — the demo owner's name in the chrome, the
landing route, a `<script src="/bind.js" defer>` in `<head>`, and a `noindex` meta. It then
verifies it broke nothing and **fails the build** if it did.

`web/bind.js` uses their machinery rather than replacing it: `setViewTier`, `mvSetFunnelState`,
`alFilter`, `alSearch`, `alApply`, `alMarkAllRead`, `mvAlertsBadge`, `mvWatchLedger`. The rows
are rendered in *their* markup — `.al-row[data-alcat]`, `.al-ico`, `.chip`, `.gloss` — so their
filter filters them and their search searches them, unchanged.

`MV_WATCH` is the object their ledger reads. In the artifact its four figures are hardcoded with
the collection each wires to named in a comment: *"when the feeds land, this object is the only
thing that changes."* This file changes exactly that object and calls their own
`mvWatchLedger()`. Nothing about the panel is reimplemented.

---

## 2 · One owner, locked — and every lease of theirs

**There is no record picker.** This serves Brown Jon S. The owner is resolved once, from config,
by **number AND name**, and here is why both are needed.

```
ownername "Brown Jon S", 2025 roll
    3,698 rows · 225 owner numbers · 124 counties · 2,708 distinct leases
```

And the owner number is not a person either:

```
420,296 distinct ownernumber values in the 2025 roll
127,650 of them (30.4%) are carried by MORE THAN ONE PERSON
```

`ownernumber` is a **county appraisal-district** key. Number **708789** alone is seven people:

| County | Name | Leases |
|---|---|---:|
| Martin | **Brown Jon S** | **103** |
| Loving | Puckett Preston I | 36 |
| Stonewall | Mcdaniel James P | 2 |
| Frio | Webb Frank King Sr | 4 |
| Nolan | Hubbard William Murray | 1 |
| Orange | Durkee Oil & Gas LLC | 1 |
| San Patricio | Fischer Todd | 1 |

Reading the number alone produced a 148-lease "portfolio" of which 45 leases belonged to five
strangers. The owner key is `(ownernumber, ownername)`, `selftest.py` fails if that filter is
removed, and the page states on screen that 224 other records share the name and are excluded.

**`owner.scope`** is left configurable and is **not** `name` by default. Reading all 2,708 leases
under the name would be ~515 MB of production documents, several minutes, and would merge 225
strangers' minerals into one position.

---

## 3 · Every alert covers the whole position

This is the substantive change from the previous build, which picked one lease per alert — the
biggest producer, the newest filing — and read like a portfolio of one.

Each alert now answers three questions in this order: **how many of your leases does this touch ·
which ones matter most · what is the total across all of them.** A lease name appears only as an
example of a counted set, never as the whole finding.

Measured on this record, 2 September 2026:

| Alert | Category | Class | Leases |
|---|---|---|---:|
| Payment check worth running on 102 of your 103 leases | money | **Urgent** | 102 |
| Your 103 leases produced +82.7% over the last twelve months | activity | digest | 101 |
| New production posted on 101 of your 103 leases for May 2026 | activity | digest | 101 |
| 222 standing permits within 1 mile of your leases | activity | digest | 103 |
| 294 unusual production changes across 101 of your 103 leases | money | digest | 101 |
| Nat gas up +1.5% across your 103 leases | money | educational | 103 |
| New-well probability scored on 103 of your 103 leases | model | educational | 103 |
| 8 new completions across 8 of your 103 leases | activity | digest | 8 |
| 2 operator changes across 2 of your 103 leases | money | **account** | 2 |
| 2 of your 103 leases reported no production in May 2026 | activity | educational | 2 |
| A co-owner posted in a group you belong to | community | community | — |
| The 2025 roll matched 224 other records in your name | money | **account** | — |

`_across()` builds the count-first phrase once, so an alert cannot quietly regress to a
single-lease headline. Four checks in `selftest.py` §11 enforce it, including *"the lease count
reaches the headline"* — because a count computed and then left out of the title the reader sees
is not a portfolio alert.

**The payment-gap alert never says an owner was underpaid.** Production is public; payment is
not. It reports how many of their leases the record shows production on — the half that can be
proven — and hands the rest to the Lease Audit.

**Idle leases** are a deliberate addition. 2 of 103 reported nothing, and nothing else on the
page would ever have mentioned them. A position is easier to read when the quiet part is named.

---

## 4 · Sources

| Alert needs | Reads |
|---|---|
| Production | `MonthlyProductionVolumes` + the transform in `Production_Activity_API_Spec.md` §4 |
| Events | `Activity_Test` — 5 live types, aggregated per type over every lease |
| Nearby | `LeaseRadiusData` — permits and adjacent leases, tightest radius |
| Probability | `Data_to_web` → `NEW WELL PROBABILITY` + category band |
| Operators | `Operator_Production_Summary_Yearly` |
| Community | `privategroupthreads` |
| Prices | **live NYMEX front-month** (`CL=F`, `NG=F`, `BZ=F`), intraday |
| Owner | `Mineral_Owners_Data_Master`, number + name, single year |

Four of those correct the mockup's `DATA-CONTRACT`: it named `Activity_Production` (a 2.1M-doc
duplicate of the monthly volumes), `Adjacent_Lease_Activity` (only the lease half of the ring),
`Decline_data_to_web.new_well_probability` (**does not exist**), and the EIA ticker (8 days
stale, and its own file says *"Not live prices"*).

---

## 5 · Traps, measured not guessed

**1 · Placeholder months are not zero production.** `08_55109` carries 202607 and 202608 at BOE 0
with `filed_flag "N"`. Anchor on `max(cycle)` and the page opens by announcing Diamondback
stopped producing. The same trap bit again downstream: counting the *newest row* reported **0
producing leases** on a portfolio that made 7.88M BOE.

**2 · `-1` is "not modelled"**, on 179,231 leases. Rendering it as 0% tells an owner their
acreage has no chance of a new well.

**3 · `mongo_update_date` is one value on all 350,556 rows** — a rebuild stamp, not a change
watermark. So the alert says *standing* permits, which is what the data supports.

**4 · Dates are parsed, never sliced.** Activity strings carry leading and trailing spaces, and
the radius stamp is `"2026-07-15 15:09:40"` — a pattern anchored to end-of-string rejected it and
shipped the permit alert with no event date. §12's eight-field check caught it.

**5 · A `<script>` at the end of a 3.2 MB artifact is never parsed.** The file carries
`'</script>'` inside JavaScript string literals, so the parser closes the block early:

```
served by the server : 3,195,339 bytes, 1 reference to bind.js
parsed in the browser: 54 route sections, 18 script elements,
                       querySelectorAll('script[src]') -> []
```

The page looked completely normal and showed the artifact's fictional Ledbetter alerts. The
binder is now in `<head>` with `defer`, and two build gates keep it there.

**6 · A single `write()` of 3.2 MB does not survive.** The browser reported
`ERR_CONNECTION_RESET` and rendered a truncated document — same failure mode as above, and just
as invisible. The body is written in 256 KB chunks with a disconnect caught, not raised.

---

## 6 · The AI, budgeted by plan

`mv/alerts.py` decides what is true. Gemini rewrites the **wording**, and cannot introduce a
number: every numeric token in its output must already appear in the finding, or that row keeps
its measured prose. The source line is never taken from the model.

| Plan | Alerts reworded | Cost |
|---|---:|---|
| Free | 0 | measured prose, footer says so |
| Pro | top 3 by rank | ~830 tokens |
| Premium | all 12 | ~2,600 tokens |

**One HTTP call per panel**, not one per alert. Model `gemini-3.5-flash-lite`. Two prompt rules
exist because the model broke them: sentence case (it Title-Cased every headline) and *keep the
lease count* (it rewrote portfolio counts down to one lease). Override the key with
`MV_GEMINI_KEY` rather than editing the file.

---

## 7 · Files

```
START.bat              double-click. Builds if needed, starts, opens the browser
config.json            source map, owner lock, window, AI budget, tiers and plans
server.py              stdlib http.server. Builds are jobs; the body is chunked
selftest.py            40 checks, each able to fail
tools/build_alerts.py  owner-v42.html -> alerts.html, with its own verify gate
web/owner-v42.html     the assembled artifact, pinned
web/alerts.html        generated - do not hand-edit, re-run the build
web/bind.js            live alerts into their app-alerts route, using their machinery
mv/db.py               the one connection, and the guard that keeps it read-only
mv/ymd.py              date and cycle parsing - the spellings, and the trap
mv/owner.py            number + name -> ONE owner record and all its leases
mv/production.py       Production_Activity_API_Spec.md section 4, implemented
mv/prices.py           live front-month futures
mv/collect.py          six sources, read concurrently -> measured facts
mv/alerts.py           facts -> the portfolio-wide inbox, with evidence
mv/summarize.py        Gemini wording, numeric guard, per-plan budget
```

```bash
python selftest.py          # 40 checks
python tools/build_alerts.py   # re-derive the page after re-copying the artifact
```

---

## 8 · What is still standing in

- **Read state and dismissals are per-browser** (`localStorage`). Real read state belongs on the
  alert row server-side — there is no column for it in Postgres today.
- **"New since your last visit" is not implemented.** There is no per-member watermark, and the
  radius collection cannot support a diff (§5.3), so the permit alert says *standing* permits.
- **Channel preferences do not persist** — `user_notification_settings` has no channel dimension.
- **The 6:00 AM sweep is described, not scheduled.** This builds on demand; the sweep, the dedupe
  keys and the delivery rows are specified in `ALERTS_BACKEND_DEV_SPEC_2026-09-02.md`.
- **Screenshots must come from a real browser.** Headless Chrome never settles on this artifact —
  its auto-rotating carousels keep virtual time advancing — and the Browser pane reports a
  0-width viewport. DOM and computed-style reads are reliable; pictures are not.
