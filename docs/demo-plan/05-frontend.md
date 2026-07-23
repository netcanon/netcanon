# 05 — Frontend

One static page (no build step required — plain HTML/CSS/JS or a single-file
Preact if the implementer prefers; keep it auditable). Served by Caddy at `/`.

## Page states

1. **Landing / idle** — one-paragraph pitch, a **Start demo** button, and the
   ephemerality promise up front (the canonical landing copy, verbatim):
   *“Your session runs in an isolated instance that **self-destructs within 15
   minutes** — usually the moment you leave. A tab left open but untouched is
   reclaimed after about 10 minutes of inactivity (**sooner under heavy load**),
   so keep translating to hold your session to the full 15. Nothing you paste is
   stored. [Read how we prove that →](whitepaper)”*
   (Say “self-destructs **within** 15 minutes,” never “in 15 minutes”:
   `HARD_TTL = 900 s` (15 min) is the ceiling; real teardown is near-immediate on
   leave — **≤ 2 min for a closed foreground tab, ≤ ~4 min for a throttled
   background tab** absent a beacon — and an untouched-but-open tab is reclaimed
   at `IDLE_TTL = 600 s` (10 min), sooner under heavy load.)
2. **Provisioning** (sub-second to ~3 s) — spinner; `POST /session/new`.
3. **Active** — iframe pointed at **`/i/{t}/migrate`** (the instance's own
   migrate UI — **not** bare `/i/{t}/`, which maps to the instance's blocked
   backup dashboard and 404s under the route allowlist, which covers the
   `{path}` component of `/i/{t}/{path}` exactly as it does absolute cookie-routed
   paths), plus a persistent header bar:
   - a **hard-TTL countdown** to the **15-min ceiling** (`HARD_TTL = 900 s`),
     computed **client-side as `receipt_time + ttl_seconds`** from the mint
     response — server-relative, so it is immune to client-clock skew;
     `expires_at` is informational only;
   - a separate **idle indicator** driven by `idle_remaining_seconds` (returned
     on every `/hb`), with a pre-reclaim warning **~60 s out under normal load** —
     any allowlisted translate / detect / sanitize POST resets it, so a visitor
     *actively using* the tool rides the full 15 min while an untouched tab is
     reclaimed at the idle TTL. Under a load-driven tightening (600 → 300 s) an
     already-idle tab can be reclaimed with **little or no warning** (the new
     deadline may fall before the next 30 s heartbeat delivers it) — translate to
     reset the timer;
   - an **instance-id chip** showing this session's `instance_id` (a short
     warden-assigned display id from the mint response — *not* the routing token;
     it backs live proof 5's “two profiles → two distinct instance ids”);
   - a **“destroy now”** button (`POST /session/{t}/end`) and a link to the
     whitepaper.
4. **At capacity** — on 503: friendly message + auto-retry with backoff +
   links to `docker run` one-liner and the repo (the demo failing closed is
   itself on-message). Say so honestly: *“Under heavy load, an untouched session
   may be reclaimed early to make room.”* The warden reclaims the longest-idle
   session before returning a 503, but **never one younger than the 120 s
   min-age floor** — a seconds-old mid-paste session is protected, so at true
   saturation you get the 503 rather than someone losing a live paste.
5. **Expired/destroyed** — “Instance destroyed 💥 — everything it held is
   gone.” + Start again button. Shown on hard-TTL lapse, idle reclaim, heartbeat
   loss, returning to a dead token, **or when another tab in the same browser
   started a fresh session** — because a second `POST /session/new` bearing this
   browser's valid `nc_route` cookie **destroys-and-replaces** the prior session
   (one live session per browser), the old tab's next `/hb` or translate returns
   **404** and flips here. This is the same “refreshing gets you a fresh
   instance” model, just triggered from another tab.

## Session plumbing

- Heartbeat: `setInterval(30 s)` → `POST /session/{t}/hb` with the request body
  `{"hidden": <bool>}` taken from `document.visibilityState === "hidden"`.
  **Keep heartbeating while the tab is hidden** — do *not* pause on
  `visibilitychange`, so a backgrounded-but-still-open tab isn't reaped mid-demo;
  instead **report** the visibility so the warden can apply the right stale
  threshold. The warden keys two thresholds off the last-reported visibility:
  **75 s while visible** (2 missed beats + margin) and **180 s while hidden**
  (tolerating background-timer throttling). The `/hb` response returns
  `{"idle_remaining_seconds": <int>}`, which drives the idle indicator (state 3).
  Update `hidden` on every `visibilitychange`; stop the interval only on
  `pagehide`.
- Teardown on leave: `navigator.sendBeacon('/session/'+t+'/end')` on `pagehide`
  **only**. **Not** `visibilitychange→hidden` — that fires on a mere tab-switch
  or minimize and would destroy the session during the demo's own
  copy-a-config-from-another-tab flow. sendBeacon is the mechanism that reliably
  fires on real tab close / navigation; the heartbeat-timeout reaper is the
  backstop for the cases it doesn't. Absent any beacon, reclaim is **≤ 2 min for
  a closed foreground tab** (30 s heartbeat + 75 s visible stale + 10 s reaper)
  and **≤ ~4 min for a throttled background tab** (30 s + 180 s hidden stale +
  10 s reaper) — not ≤ 60 s — and the hard TTL covers the rest (**I3**).
- Countdown computed **client-side as `receipt_time + ttl_seconds`** from the
  mint response — server-relative and therefore immune to client-clock skew;
  `expires_at` is informational only. The mint response is
  `{token, ttl_seconds, expires_at, idle_ttl_seconds, instance_id}`
  (`idle_ttl_seconds` seeds the idle indicator; `instance_id` feeds the header
  chip — see state 3).
- **The page sets no cookies, no localStorage, no analytics, and makes no
  third-party requests of any kind** — view-source stays consistent with the
  whitepaper. The one cookie in play is *not* set by this page: it is the
  warden's **routing** cookie, set on the `/session/new` mint response and
  re-stamped on the proxied instance responses so absolute-path requests reach the
  right container, as
  `Set-Cookie: nc_route=<token>; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=900`
  (the `Path=/` is load-bearing — without it RFC-6265 default-path scoping would
  keep the cookie off absolute app paths and break routing; `Max-Age=900` matches
  `HARD_TTL`). It is unreadable from JS and is disclosed in the whitepaper's
  *What we do see* ([06](06-privacy-whitepaper.md#what-we-do-see)). State (the
  token) lives in a JS variable; a refresh simply starts a new session — and so
  does starting one from another tab in the same browser (the cookie is
  browser-global, so a second mint destroys-and-replaces the first; see state 5).
  Say so in the UI (“refreshing gets you a fresh instance”).

## Content requirements

- Preload the demo textarea *inside a “try this sample” button* that pastes
  the canonical Cisco IOS-XE sample (hostname/vlan/interface/route/snmp) so a
  visitor gets the GigabitEthernet1/0/1 → ge-1/0/1 payoff in one click.
- Surface the Tier-3 banner behavior in the sample flow — the amber
  “surfaced, not silently dropped” moment is the product's core argument.
- Footer links: GitHub, PyPI, whitepaper, `docker run` one-liner.

## Accessibility / weight budget

- Total page ≤ 50 KB excluding the iframed instance UI. No fonts, no
  frameworks from CDNs. Works with JS disabled to the extent of showing the
  pitch + repo links (demo obviously needs JS).

## Deliverables

- `frontend/index.html` (+ minimal css/js, same folder)
- Caddy static-serve block
- Whitepaper page rendered from [06](06-privacy-whitepaper.md) (same styling)
