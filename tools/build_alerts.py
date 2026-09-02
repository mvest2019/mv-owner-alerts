#!/usr/bin/env python
"""Derive the ALERTS page from the redesign build's assembled artifact.

    python tools/build_alerts.py

Reads  web/owner-v42.html   (the repo's assembled owner portal, 48 routes)
Writes web/alerts.html      (the same portal, landing on #/app/alerts, wired to live data)

WHY A BUILD STEP RATHER THAN A HAND EDIT
  The transform is recorded as code so it can be re-run when the artifact is re-copied, and so
  every change is a line someone can read and argue with. Hand-editing a 3.2 MB generated file
  produces a result nobody can reproduce and nobody can review.

WHAT IS KEPT - AND THIS IS THE POINT OF THIS BUILD
  EVERYTHING. The sidebar with all thirteen route groups, the top header, the avatar menu with
  its four view densities, the funnel-state cycler, every <style> and every <script>.

  The dashboard build in the sibling folder strips 47 routes because it serves one screen. This
  one must not: the whole complaint about the previous alerts app was that it had no left menu,
  no top header, no view switcher and no account menu. Those live in the shell, so the shell
  stays whole and the alerts route is bound live inside it.

WHAT IS CHANGED - four things, all small
  1  the demo owner's identity in the CHROME (tab title, avatar tooltip, aria-labels)
  2  the landing route, so opening the page lands on Alerts rather than the dashboard
  3  a <script src="/bind.js"> before </body>
  4  a noindex meta, because this is a mockup served locally

THE IDENTITY REWRITE IS NOT A str.replace, AND THAT IS DELIBERATE
  The artifact contains a JavaScript function called `initSuzieMap` - 19 occurrences. Replacing
  the bare word "Suzie" turns it into `initthe ownerMap`, a syntax error that kills the <script>
  block carrying their router: no route ever renders and the page loads as styled static HTML.
  So the rewrite runs on prose contexts only and refuses to touch anything that looks like an
  identifier. `verify()` re-checks that no identifier was harmed and fails the build if one was.
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "web", "owner-v42.html")
OUT = os.path.join(HERE, "web", "alerts.html")

LANDING = "#/app/alerts"

# The demo owner written into the shell. Replaced in prose only.
DEMO_PERSON = "Suzie Smith"
DEMO_FIRST = "Suzie"
DEMO_ROLL = "SMITH, RAYMOND E"

# Identifiers that CONTAIN the demo first name and must survive untouched.
PROTECTED = ("initSuzieMap", "SuzieMap", "suzieMap")


def read():
    if not os.path.isfile(SRC):
        raise SystemExit("Missing %s - copy the assembled owner artifact there first." % SRC)
    return io.open(SRC, encoding="utf-8", newline="").read()


def rename_owner(html, owner_name, roll_name):
    """Swap the demo identity out of the chrome. Prose only, never an identifier."""
    hits = []

    # Protect the identifiers by parking them behind a token no HTML can contain.
    for i, ident in enumerate(PROTECTED):
        html = html.replace(ident, "\x00P%d\x00" % i)

    # 1 · the tab title, which a screenshot shows and a runtime bind never reaches
    html, n = re.subn(r"<title>Mineral View[^<]*</title>",
                      "<title>Alerts · Mineral View — %s</title>" % owner_name, html, count=1)
    hits.append(("tab title", n))

    # 2 · the full demo name wherever it appears as prose
    n = html.count(DEMO_PERSON)
    html = html.replace(DEMO_PERSON, owner_name)
    hits.append(("full name", n))

    # 3 · the roll spelling of the demo owner
    n = html.count(DEMO_ROLL)
    html = html.replace(DEMO_ROLL, roll_name)
    hits.append(("roll name", n))

    # 4 · the bare first name, but ONLY where it is a whole word in text or an attribute -
    #     never where it is glued to another word, which is what an identifier looks like.
    first = owner_name.split()[0]
    html, n = re.subn(r"(?<![A-Za-z0-9_$])%s(?![A-Za-z0-9_$])" % DEMO_FIRST, first, html)
    hits.append(("first name", n))

    for i, ident in enumerate(PROTECTED):
        html = html.replace("\x00P%d\x00" % i, ident)
    return html, hits


def set_landing(html):
    """Land on Alerts.

    Their router reads location.hash on load, so setting it BEFORE their scripts run is enough -
    no need to reach into the router itself. Injected right after <body ...> so it is the first
    thing that executes, and it never overrides a hash the visitor typed.
    """
    snippet = (
        "\n<script>/* build_alerts.py - land on Alerts unless the URL already names a route. "
        "Set before their router reads location.hash, so their own routing does the work. */\n"
        "if(!location.hash || location.hash === '#' || location.hash === '#/'){"
        "try{ history.replaceState(null,'','%s'); }catch(e){ location.hash='%s'; }}\n"
        "</script>\n" % (LANDING, LANDING))
    m = re.search(r"<body\b[^>]*>", html)
    if not m:
        raise SystemExit("No <body> tag found - is web/owner-v42.html the artifact?")
    return html[:m.end()] + snippet + html[m.end():]


def add_bind(html):
    """Load the binder from <head> with defer - NOT from the end of <body>.

    WHY, MEASURED. The first version appended <script src="/bind.js"> before the final </body>,
    which is the conventional place and is wrong for this file. The artifact is 3.2 MB and
    carries `'</script>'` inside JavaScript string literals; the HTML parser closes the script
    block at the first of those, and everything after it is parsed in a different context. The
    tag at the end of the file was never turned into an element:

        served by the server : 3,195,339 bytes, 1 reference to bind.js
        parsed in the browser: 54 route sections present, 18 script elements,
                               document.querySelectorAll('script[src]') -> []

    So the page looked completely normal, kept the artifact's fictional sample alerts, and bound
    nothing - a plausible screen full of another owner's data, which is the worst shape this bug
    could take.

    `defer` in <head> is immune to it: the element exists as soon as the head is parsed, and
    defer guarantees it runs after the document is parsed, so #alList is there when it does.
    """
    if "/bind.js" in html:
        return html, False
    m = re.search(r"<head\b[^>]*>", html)
    if not m:
        raise SystemExit("No <head> tag found - refusing to inject blindly.")
    tag = '\n<script src="/bind.js" defer></script>\n'
    return html[:m.end()] + tag + html[m.end():], True


def add_noindex(html):
    if 'name="robots"' in html:
        return html, False
    m = re.search(r"<head\b[^>]*>", html)
    if not m:
        raise SystemExit("No <head> tag found.")
    return (html[:m.end()] + '\n<meta name="robots" content="noindex,nofollow">\n'
            + html[m.end():], True)


def verify(html, owner_name, src):
    """Prove the build did not break what it was not meant to touch.

    A build step that silently corrupts a 3.2 MB file is worse than no build step, so each of
    these is a hard failure rather than a warning.

    BOTH THRESHOLDS HERE ARE MEASURED AGAINST THE SOURCE, not hardcoded. The first version
    asserted "at least 40 script tags" and "every PROTECTED identifier is present", and it
    failed a perfectly good build twice over: the artifact carries 20 script tags, not 40, and
    `suzieMap` was never in it at all. A gate calibrated against a guess fails honest work and
    teaches people to bypass it.
    """
    problems = []
    for ident in PROTECTED:
        # Only an identifier that WAS there can have been destroyed.
        if ident in src and ident not in html:
            problems.append("identifier %s was destroyed by the rename" % ident)
    if "\x00" in html:
        problems.append("a protection token leaked into the output")
    if DEMO_FIRST in re.sub(r"[A-Za-z0-9_$]%s|%s[A-Za-z0-9_$]" % (DEMO_FIRST, DEMO_FIRST),
                            "", html):
        problems.append("the demo first name still appears as prose")
    # The scripts are the router. Losing them is the failure mode that renders as a styled
    # static page, so the count is compared with the source rather than with a magic number.
    was, now = src.count("<script"), html.count("<script")
    if now < was:
        problems.append("%d of %d <script> tags survived - the shell has been damaged"
                        % (now, was))
    if 'data-route="app-alerts"' not in html:
        problems.append("the app-alerts route is missing")
    if 'class="nav-item"' not in html:
        problems.append("the sidebar nav is missing")
    if owner_name not in html:
        problems.append("the live owner name never made it into the chrome")
    # The binder must be in the HEAD. In the body it is silently never parsed - see add_bind().
    head = html[:html.find("</head>") if "</head>" in html else 4000]
    if 'src="/bind.js"' not in head:
        problems.append("bind.js is not in <head> - a tag at the end of body is never parsed")
    if 'src="/bind.js" defer' not in head:
        problems.append("bind.js is missing defer - it would run before #alList exists")
    return problems


def main():
    src = read()
    owner_name = sys.argv[1] if len(sys.argv) > 1 else "Brown Jon S"
    roll_name = sys.argv[2] if len(sys.argv) > 2 else "BROWN, JON S"

    print("reading  %s  (%.2f MB)" % (os.path.basename(SRC), len(src) / 1e6))
    before_scripts = src.count("<script")
    routes = len(re.findall(r'<section\b[^>]*\bdata-route="', src))
    navs = len(re.findall(r'class="nav-item"', src))
    print("         %d routes · %d nav links · %d script tags" % (routes, navs, before_scripts))

    html, hits = rename_owner(src, owner_name, roll_name)
    for what, n in hits:
        print("  renamed %-11s %d occurrence(s)" % (what, n))

    html = set_landing(html)
    print("  landing route  %s" % LANDING)
    html, added = add_bind(html)
    print("  bind.js        %s" % ("added" if added else "already present"))
    html, added = add_noindex(html)
    print("  noindex        %s" % ("added" if added else "already present"))

    problems = verify(html, owner_name, src)
    if problems:
        print("\nBUILD FAILED:")
        for p in problems:
            print("   %s" % p)
        raise SystemExit(1)

    io.open(OUT, "w", encoding="utf-8", newline="").write(html)
    print("\nwrote    %s  (%.2f MB)" % (os.path.basename(OUT), len(html) / 1e6))
    print("         %d routes · %d nav links · %d script tags — shell intact"
          % (len(re.findall(r'<section\b[^>]*\bdata-route="', html)),
             len(re.findall(r'class="nav-item"', html)), html.count("<script")))


if __name__ == "__main__":
    main()
