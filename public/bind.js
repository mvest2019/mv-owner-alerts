/* Binds live alerts into the redesign build's own Alerts route.
 *
 * WHAT THIS IS NOT: a second alerts page. alerts.html is the repo's assembled artifact with its
 * sidebar, top header, avatar menu, four view densities and funnel-state cycler intact. This
 * file only replaces the hard-coded sample rows with measured ones.
 *
 * WHY BIND RATHER THAN REBUILD: the repo assembles v42.html from modules under owner/src/ and
 * check_build.py asserts byte-identity, so a hand edit would be silently overwritten on the next
 * assemble - and it would fork the design, which is the one thing a data layer must not do.
 *
 * THE UI'S OWN MACHINERY IS USED, NOT REPLACED. All of these already exist in the artifact:
 *
 *     setViewTier('ultra'|'simple'|'detailed'|'pro')   the four densities
 *     mvSetFunnelState('unclaimed'|'claimed'|'paid'…)  the plan states
 *     alFilter(cat) · alSearch(q) · alApply()          the category filter and search
 *     alMarkAllRead(btn) · mvAlertsBadge(n)            read state and the sidebar badge
 *     mvWatchLedger() · MV_WATCH                       the "what you're paying for" panel
 *
 * Re-implementing any of them would have produced controls that looked right and drove nothing.
 * The rows are rendered in THEIR markup - .al-row[data-alcat], .al-ico, .chip, .gloss - so
 * alApply() filters them, alSearch() searches them and alMarkAllRead() marks them, unchanged.
 *
 * MV_WATCH is the object their ledger reads. In the artifact its four figures are hardcoded with
 * the collection each one wires to named in a comment. That comment says "when the feeds land,
 * this object is the only thing that changes" - so this file changes exactly that object and
 * then calls their own mvWatchLedger(). Nothing about the panel is reimplemented.
 */
'use strict';

(function () {

  var STATE = { data: null, tier: null, plan: 'premium', poll: null, painted: false,
                read: {}, dismissed: {} };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function num(v) { return (v == null || isNaN(v)) ? '—' : Number(v).toLocaleString(); }

  var WORD = ['zero','one','two','three','four','five','six','seven','eight','nine','ten',
              'eleven','twelve'];
  function word(i) { return WORD[i] !== undefined ? WORD[i] : Number(i).toLocaleString(); }
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

  /* A date the reader can check. The human distance goes BESIDE it, never instead of it -
     "2 days ago" alone is unverifiable, and the date is what they compare to their own
     records. */
  var MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  function dstr(iso) {
    if (!iso) return '—';
    var d = new Date(iso + (String(iso).length <= 10 ? 'T00:00:00' : ''));
    if (isNaN(d)) return esc(iso);
    return MON[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
  }

  /* ---------------------------------------------------------------- progress
     The artifact has no loading state for a data fetch, so one is added rather than leaving
     the sample rows on screen looking live for twenty seconds. */
  function banner(html, kind) {
    var sec = document.querySelector('section[data-route="app-alerts"]');
    if (!sec) return;
    var el = $('mvBindNote');
    if (!el) {
      el = document.createElement('div');
      el.id = 'mvBindNote';
      el.style.cssText = 'margin:12px 0;padding:11px 15px;border-radius:11px;font-size:13px;' +
        'line-height:1.5;border:1px solid var(--line);background:#fff';
      sec.insertBefore(el, sec.firstChild);
    }
    el.style.borderColor = kind === 'err' ? '#f6c8c8' : (kind === 'ok' ? '#cdeadd' : 'var(--line)');
    el.style.background = kind === 'err' ? 'var(--red-bg)' : (kind === 'ok' ? '#f4fdf9' : '#fff');
    el.style.color = kind === 'err' ? '#7f1d1d' : 'var(--slate)';
    el.innerHTML = html;
  }
  function clearBanner() { var el = $('mvBindNote'); if (el) el.remove(); }

  /* ---------------------------------------------------------------- the evidence card
     Built from the evidence the server already sent with each alert, so opening a row is
     instant and offline. The figures are computed server-side and only formatted here: the UI
     must never be a second place a number is worked out, or there are two definitions of it. */
  function bars(series) {
    if (!series || series.length < 2) return '';
    var max = Math.max.apply(null, series.map(function (s) { return s.value || 0; })) || 1;
    return '<div class="mvb-spark">' + series.map(function (s) {
      var h = Math.max(3, Math.round((s.value || 0) / max * 44));
      return '<i style="height:' + h + 'px" class="' + (s.on ? 'on' : '') + '" title="' +
             esc(s.label + ' · ' + num(s.value)) + '"></i>';
    }).join('') + '</div><div class="mvb-sparx">' + series.map(function (s) {
      return '<span>' + esc(String(s.label).slice(0, 5)) + '</span>';
    }).join('') + '</div>';
  }

  function evidenceHTML(ev) {
    if (!ev) return '<p class="tiny muted">No detail recorded.</p>';
    var rows = (ev.rows || []).map(function (r) {
      return '<tr><th>' + esc(r.k) + '</th><td>' + esc(r.v) + '</td>' +
             '<td class="nt">' + esc(r.note || '') + '</td></tr>';
    }).join('');
    return '<div class="mvb-ev">' +
      '<p class="mvb-why">' + esc(ev.why) + '</p>' +
      (rows ? '<table class="mvb-tbl">' + rows + '</table>' : '') +
      bars(ev.series) +
      (ev.method ? '<p class="mvb-how"><span>How this was measured</span>' +
                   esc(ev.method) + '</p>' : '') +
    '</div>';
  }

  /* ---------------------------------------------------------------- one row, in THEIR markup */
  function rowHTML(a, i) {
    var unread = !STATE.read[a.id];
    var chans = (a.channels || []).join(' + ');
    var acts = (a.actions || []).map(function (x) {
      if (x.dismiss) {
        return '<button type="button" class="btn btn-ghost btn-sm" data-mvdismiss="' +
               esc(a.id) + '">' + esc(x.label) + '</button>';
      }
      return '<a class="btn ' + (x.primary ? 'btn-primary' : 'btn-ghost') + ' btn-sm" href="' +
             esc(x.href || '#') + '">' + esc(x.label) + '</a>';
    }).join('');

    /* .v33-pri-badge.u is what THEIR mvAlertCounts() looks for to count the
       action-recommended rows. Rendering it here means their ledger arithmetic works on these
       rows without a line of it being reimplemented. */
    var pri = a.delivery_class === 'urgent'
      ? '<span class="v33-pri-badge u" style="display:none">urgent</span>' : '';

    return '<div class="al-row' + (unread ? ' unreadal' : '') + ' mvb-row" data-alcat="' +
        esc(a.category) + '" data-mvid="' + esc(a.id) + '" data-i="' + i + '"' +
        ' role="button" tabindex="0" aria-expanded="false">' +
      pri +
      '<span class="al-ico ' + esc(a.icon_class || '') + '">' + esc(a.icon || '•') + '</span>' +
      '<div style="flex:1;min-width:0">' +
        '<div class="between" style="flex-wrap:wrap;gap:6px">' +
          '<strong class="small">' + esc(a.title) + '</strong>' +
          '<span class="tiny muted num">' +
            '<span class="chip ' + esc(a.class_chip) + '" style="font-size:9px">' +
              esc(a.class_label) + '</span> ' +
            '<span class="gloss" tabindex="0" data-def="' + esc(a.why) + '">why?</span>' +
            ' · event ' + esc(dstr(a.event_date)) +
            ' · detected ' + esc(dstr(a.detected)) +
            (chans ? ' · ' + esc(chans) : '') +
            (a.lease_count ? ' · ' + num(a.lease_count) + ' leases' : '') +
          '</span>' +
        '</div>' +
        '<p class="tiny muted" style="margin:3px 0 7px">' + esc(a.body) + '</p>' +
        (acts ? '<div class="flex" style="flex-wrap:wrap">' + acts + '</div>' : '') +
        '<span class="mvb-src">' + esc(a.public) +
          (a.reworded ? ' · wording by AI' : '') + '</span>' +
        '<div class="mvb-slot"></div>' +
      '</div>' +
      '<span class="mvb-chev" aria-hidden="true">⌄</span>' +
    '</div>';
  }

  /* One row open at a time: every row open is a wall of text, and the point of an inbox is
     that it is scannable at a glance. */
  function toggleRow(el) {
    var open = el.classList.contains('open');
    [].forEach.call(document.querySelectorAll('.mvb-row.open'), function (o) {
      o.classList.remove('open');
      o.setAttribute('aria-expanded', 'false');
      o.querySelector('.mvb-slot').innerHTML = '';
    });
    if (open) return;
    var slot = el.querySelector('.mvb-slot');
    slot.innerHTML = evidenceHTML(STATE.data.alerts[+el.dataset.i].evidence);
    el.classList.add('open');
    el.setAttribute('aria-expanded', 'true');
    markRead(el.dataset.mvid, el);
  }

  /* Per-viewer only. Real read state belongs on the alert row server-side - there is no column
     for it today, and the README says so rather than this pretending to be the feature. */
  function markRead(id, el) {
    if (!id || STATE.read[id]) return;
    STATE.read[id] = 1;
    try { localStorage.setItem('mvb_read', JSON.stringify(STATE.read)); } catch (e) {}
    if (el) el.classList.remove('unreadal');
    paintLedger();
  }

  function live() {
    return (STATE.data.alerts || []).filter(function (a) { return !STATE.dismissed[a.id]; });
  }

  /* ---------------------------------------------------------------- their ledger, live figures
     MV_WATCH and mvWatchLedger() are theirs. This sets the four figures and calls their
     function, so the filter counts, the ledger tiles and the prose all stay one derivation. */
  function paintLedger() {
    var d = STATE.data, rows = live();
    var unread = rows.filter(function (a) { return !STATE.read[a.id]; }).length;

    if (window.MV_WATCH) {
      window.MV_WATCH.counties = d.watch.counties;
      window.MV_WATCH.adjacent = d.watch.adjacent;
      window.MV_WATCH.permits = d.watch.permits;
      window.MV_WATCH.production = d.watch.production;
      window.MV_WATCH.leases = d.watch.leases;
    }
    if (typeof window.mvLeaseCount !== 'function') {
      window.mvLeaseCount = function () { return d.watch.leases; };
    }
    if (typeof window.mvWatchLedger === 'function') {
      try { window.mvWatchLedger(); } catch (e) {}
    }
    if (typeof window.mvAlertsBadge === 'function') {
      try { window.mvAlertsBadge(unread); } catch (e) {}
    }

    /* Their ledger fills [data-aw] and .alf-n from the rows. Anything it did not reach - the
       tiles whose figure is not in MV_WATCH - is filled here from the same payload. */
    var c = { all: rows.length, money: 0, activity: 0, community: 0, model: 0, action: 0 };
    rows.forEach(function (a) {
      c[a.category] = (c[a.category] || 0) + 1;
      if (a.delivery_class === 'urgent') c.action++;
    });
    var map = { leases: num(d.watch.leases), counties: num(d.watch.counties),
                adjacent: num(d.watch.adjacent), permits: num(d.watch.permits),
                production: num(d.watch.production), alerts: c.all,
                alertsPhrase: word(c.all) + ' alert' + (c.all === 1 ? '' : 's'),
                actionPhrase: c.action === 1 ? 'one of which asks'
                                             : word(c.action) + ' of which ask',
                actionWord: cap(word(c.action)),
                actionVerb: c.action === 1 ? 'asks' : 'ask',
                restWord: word(Math.max(0, c.all - c.action)) };
    Object.keys(map).forEach(function (k) {
      [].forEach.call(document.querySelectorAll('[data-aw="' + k + '"]'), function (el) {
        el.textContent = map[k];
      });
    });
    [].forEach.call(document.querySelectorAll('[data-alf]'), function (b) {
      var n = b.querySelector('.alf-n');
      var k = b.dataset.alf;
      if (n) n.textContent = k === 'all' ? c.all : (c[k] || 0);
    });
    return c;
  }

  /* ---------------------------------------------------------------- the whole route */
  function paint() {
    var d = STATE.data, sec = document.querySelector('section[data-route="app-alerts"]');
    if (!sec || !d) return;

    var listEl = $('alList');
    if (!listEl) return;
    var rows = live();
    listEl.innerHTML = rows.map(function (a) {
      return rowHTML(a, d.alerts.indexOf(a));
    }).join('') || '<p class="tiny muted">No alerts on this record.</p>';

    var c = paintLedger();

    /* The sample panel a visitor sees before claiming shows the SAME alerts, read-only - it is
       a preview of this inbox, not a different one, so what they were shown is what they get. */
    var smp = sec.querySelector('.smp-wrap .stack');
    if (smp) {
      smp.innerHTML = rows.slice(0, 3).map(function (a) {
        return '<div class="card card-pad" style="border-left:4px solid ' +
          (a.delivery_class === 'urgent' ? '#d9a441' : 'var(--green)') +
          ';padding:10px 14px"><strong class="small">' + esc(a.icon + ' ' + a.title) +
          '</strong><p class="tiny muted" style="margin-top:2px">' + esc(a.body) + '</p></div>';
      }).join('');
    }

    /* ULTRA: one status, one action, one reassurance. */
    var urgent = rows.filter(function (a) { return a.delivery_class === 'urgent'; })[0];
    var uh = sec.querySelector('.ultra-hero');
    if (uh) {
      var head = uh.querySelector('.u-headline'), st = uh.querySelector('.u-status');
      var cta = uh.querySelector('.btn'), notes = uh.querySelectorAll('.u-note');
      if (head) head.innerHTML = urgent ? 'One thing when you have <strong>a minute</strong>'
                                        : 'Nothing needs you <strong>today</strong>';
      if (st) st.textContent = urgent ? urgent.body
        : 'We read the public record on your ' + num(d.watch.leases) + ' leases this morning. ' +
          c.all + ' thing' + (c.all === 1 ? '' : 's') + ' changed, and none asks anything of you.';
      if (cta) {
        cta.textContent = urgent ? 'Run the included check' : 'See what changed';
        cta.setAttribute('href', urgent ? (urgent.deep_link || '#/app/audit') : '#/app/leases');
      }
      if (notes.length) {
        notes[notes.length - 1].textContent = 'We read the public record on your ' +
          num(d.watch.leases) + ' leases every day. Most days there is nothing to tell you — ' +
          'and we will still have looked. That quiet is the service working, not the service ' +
          'asleep.';
      }
    }

    /* ESSENTIALS: the one-line summary. */
    var sh = sec.querySelector('.simple-hero p');
    if (sh) {
      sh.innerHTML = c.all + ' thing' + (c.all === 1 ? '' : 's') + ' changed across your ' +
        num(d.watch.leases) + ' leases' +
        (urgent ? ', and <strong>one asks something of you</strong>: <strong>' +
                  esc(urgent.title) + '</strong>. The other ' + word(c.all - 1) +
                  ' are good news, neighbours at work, or context.'
                : ', and <strong>none asks anything of you</strong>. All ' + word(c.all) +
                  ' are good news, neighbours at work, or context.');
    }

    /* PROFESSIONAL: the method note, in this owner's own figures. */
    var pro = sec.querySelector('.mv-alwatch .tier-p');
    if (pro) {
      pro.innerHTML = '<strong>Professional note — how the watch is built.</strong> ' +
        'A daily sweep of RRC production, permit, completion, status and operator filings ' +
        'matched against all ' + num(d.watch.leases) + ' of your lease numbers and the radius ' +
        'lists around them (' + num(d.watch.adjacent) + ' adjacent leases, ' +
        num(d.watch.permits) + ' standing permits), plus the live NYMEX front-month feed, your ' +
        'private group threads and the new-well probability model (' + num(d.watch.modelled) +
        ' of your leases are modelled). Production is read on demand from the monthly volumes ' +
        'rather than a pre-computed copy, so it is never staler than the record itself — newest ' +
        'reported month ' + esc(d.as_of_label) + '. Every alert is measured across the whole ' +
        'position, not one lease, and carries both its event date and the date we detected it.';
    }

    /* The owner's identity in the chrome, and the roll caveat that goes with it. */
    var who = d.owner.ownername + ' · record #' + d.owner.ownernumber;
    [].forEach.call(document.querySelectorAll('.av-name, #avName'), function (el) {
      el.textContent = d.owner.ownername;
    });
    [].forEach.call(document.querySelectorAll('.av-sub, #avSub'), function (el) {
      el.textContent = num(d.owner.lease_count) + ' leases · ' +
        (d.owner.counties || []).slice(0, 2).join(', ');
    });

    banner('<strong>' + esc(who) + '</strong> — ' + num(d.owner.lease_count) +
      ' claimed leases in ' + esc((d.owner.counties || []).join(', ')) + ', ' + d.owner.year +
      ' roll. Every alert below is measured across all ' + num(d.owner.lease_count) +
      ' of them.<br><span class="tiny muted">' +
      (d.writer === 'ai' ? 'Wording by ' + esc(d.model || 'AI') + ' from measured figures'
                         : 'Measured wording' + (d.writer_note ? ' — ' + esc(d.writer_note) : '')) +
      ' · production as of ' + esc(d.as_of_label) + ' · ' + num(d.name_matches) +
      ' other owner records share this name and are not counted here' +
      (d.cached ? ' · from this session’s cache' : '') + '</span>', 'ok');

    STATE.painted = true;
  }

  /* ---------------------------------------------------------------- events
     Delegated at the document, because their router replaces the route's DOM on navigation and
     a listener bound to a row would be lost the first time someone visits another page. */
  document.addEventListener('click', function (e) {
    var d = e.target.closest('[data-mvdismiss]');
    if (d) {
      e.stopPropagation();
      STATE.dismissed[d.dataset.mvdismiss] = 1;
      try { localStorage.setItem('mvb_dismissed', JSON.stringify(STATE.dismissed)); } catch (x) {}
      paint();
      return;
    }
    if (e.target.closest('.gloss') || e.target.closest('a.btn') ||
        e.target.closest('button.btn')) return;
    var row = e.target.closest('.mvb-row');
    if (row && STATE.data) toggleRow(row);
  }, true);

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var row = e.target.closest && e.target.closest('.mvb-row');
    if (row && STATE.data) { e.preventDefault(); toggleRow(row); }
  });

  /* ---------------------------------------------------------------- fetch
     A build is a job on the server, so this polls it and shows each source as it lands. A
     twenty-second silent spinner over sample rows is indistinguishable from a broken page. */
  function watch(jobId) {
    STATE.poll = setInterval(function () {
      fetch('/api/job/' + jobId).then(function (r) { return r.json(); }).then(function (j) {
        var last = (j.steps || []).slice(-1)[0];
        if (j.result) { STATE.data = j.result; paint(); }
        if (j.state === 'running') {
          if (!STATE.painted) {
            banner('<strong>Reading the public record…</strong><br>' +
              '<span class="tiny muted">' +
              esc(last ? last.text : 'starting') + '</span>');
          }
          return;
        }
        clearInterval(STATE.poll);
        if (j.state === 'error') {
          banner('<strong>Could not build the alerts</strong><br><span class="tiny">' +
                 esc(j.error) + '</span>', 'err');
        }
      }).catch(function (err) {
        clearInterval(STATE.poll);
        banner('<strong>Lost the local server</strong><br><span class="tiny">' +
               esc(String(err)) + '</span>', 'err');
      });
    }, 700);
  }

  function start(fresh) {
    if (STATE.poll) clearInterval(STATE.poll);
    STATE.painted = false;
    banner('<strong>Reading the public record…</strong>');
    fetch('/api/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan: STATE.plan, fresh: !!fresh })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) { banner('<strong>Rejected</strong> ' + esc(res.j.error), 'err'); return; }
        watch(res.j.job_id);
      }).catch(function (err) {
        banner('<strong>Could not reach the local server</strong><br><span class="tiny">' +
               esc(String(err)) + '</span>', 'err');
      });
  }

  /* ---------------------------------------------------------------- boot
     The artifact's scripts run on DOMContentLoaded and build the route's DOM, so this waits for
     #alList to exist rather than racing it. Polling beats a fixed delay: a fixed delay is a
     guess that works on one machine. */
  function whenReady(fn) {
    var tries = 0;
    (function probe() {
      if ($('alList')) return fn();
      if (++tries > 200) return;                    // ~20s, then give up quietly
      setTimeout(probe, 100);
    })();
  }

  /* ---------------------------------------------------------------- styles
     Only the four things the artifact has no class for: the expand chevron, the evidence card,
     its table and its sparkline. Everything else reuses their tokens and their classes, so a
     change to the design system reaches this page too. Injected from here rather than added to
     the artifact, so re-running the build step does not need to know about it. */
  (function () {
    var css = document.createElement('style');
    css.id = 'mvbCss';
    css.textContent = [
      '.mvb-row{cursor:pointer;transition:border-color .16s,box-shadow .16s,transform .16s}',
      '.mvb-row:hover{border-color:var(--green);transform:translateY(-1px);',
        'box-shadow:var(--shadow-lg)}',
      '.mvb-row:focus-visible{outline:2px solid var(--green);outline-offset:2px}',
      '.mvb-chev{flex:none;align-self:center;color:#9aa3af;font-size:17px;line-height:1;',
        'transition:transform .22s,color .16s}',
      '.mvb-row:hover .mvb-chev{color:var(--green-deep)}',
      '.mvb-row.open .mvb-chev{transform:rotate(180deg);color:var(--green-deep)}',
      '.mvb-src{display:block;font-size:10.5px;color:#9aa3af;margin-top:6px}',
      '.mvb-ev{margin-top:12px;padding-top:13px;border-top:1px dashed var(--line)}',
      '.mvb-why{margin:0 0 12px;font-size:12.5px;line-height:1.62;color:var(--slate)}',
      '.mvb-tbl{width:100%;border-collapse:collapse;font-size:12px}',
      '.mvb-tbl th{text-align:left;font-weight:600;color:var(--muted);',
        'padding:6px 12px 6px 0;white-space:nowrap;vertical-align:top;width:1%}',
      '.mvb-tbl td{padding:6px 0;color:var(--ink);font-weight:700;',
        'font-variant-numeric:tabular-nums;white-space:nowrap}',
      '.mvb-tbl td.nt{padding-left:12px;color:var(--muted);font-weight:500;',
        'white-space:normal;width:100%}',
      '.mvb-tbl tr+tr th,.mvb-tbl tr+tr td{border-top:1px solid #eef1f4}',
      '.mvb-how{margin:13px 0 0;font-size:11.5px;line-height:1.6;color:var(--muted);',
        'background:#fafbfc;border:1px solid #eef1f4;border-radius:9px;padding:10px 12px}',
      '.mvb-how span{display:block;font-weight:700;color:var(--slate);letter-spacing:.03em;',
        'text-transform:uppercase;font-size:9.5px;margin-bottom:4px}',
      '.mvb-spark{display:flex;align-items:flex-end;gap:4px;height:46px;margin:14px 0 0}',
      '.mvb-spark i{flex:1;min-width:5px;border-radius:3px 3px 0 0;background:#dfe6ec}',
      '.mvb-spark i.on{background:var(--green-deep)}',
      '.mvb-sparx{display:flex;gap:4px;margin-top:5px}',
      '.mvb-sparx span{flex:1;min-width:5px;text-align:center;font-size:9px;color:#9aa3af;',
        'overflow:hidden;white-space:nowrap}'
    ].join('');
    document.head.appendChild(css);
  })();

  try { STATE.read = JSON.parse(localStorage.getItem('mvb_read') || '{}'); } catch (e) {}
  try { STATE.dismissed = JSON.parse(localStorage.getItem('mvb_dismissed') || '{}'); } catch (e) {}

  document.addEventListener('DOMContentLoaded', function () {
    whenReady(function () {
      /* Their own tier control, driven with their own function - never a reimplementation. */
      fetch('/api/health').then(function (r) { return r.json(); }).then(function (h) {
        STATE.plan = (h.ui && h.ui.default_plan) || 'premium';
        var tier = (h.ui && h.ui.default_tier) || 'detailed';
        try { tier = localStorage.getItem('mv_view_tier') || tier; } catch (e) {}
        if (typeof window.setViewTier === 'function') { try { setViewTier(tier); } catch (e) {} }
        var fs = (h.ui && h.ui.plan_state && h.ui.plan_state[STATE.plan]) || 'paid';
        if (typeof window.mvSetFunnelState === 'function') {
          try { mvSetFunnelState(fs); } catch (e) {}
        }
        start(false);
      }).catch(function () { start(false); });
    });
  });

  window.mvbReload = function () { start(true); };   // console escape hatch for a fresh read
})();
