# Data Access

What we can and cannot collect, per provider. Sources: Meta's Ad Library API page and Graph API `ads_archive`
reference (retrieved via search 2026-09-30), Meta's Ad Library tools page, the READMEs/PyPI metadata of the repos and
libraries inspected, and Apify actor pages. **Nothing here has been tested against live Meta yet.** Every
"Reliability" cell is "untested" until the vertical-slice real-data run.

## Data origin labels (used in DB and UI)

| Label | Meaning |
|---|---|
| `official_api` | Returned by Meta's Graph API. Verified public data |
| `public_ui` | Read from Meta's public Ad Library pages by our collector. Public, but unofficial and unversioned |
| `third_party` | Returned by a paid provider (e.g. Apify). Provider-supplied, we cannot verify their method |
| `user_import` | Uploaded by the user (CSV/JSON) |
| `ai_interpretation` | Produced by an AI model from the above. Interpretation, never fact |
| `estimate` | Computed by us with a stated method. Always shown with `ESTIMATE` and `CONFIDENCE`. Not in slice 1 |

## Key facts about Meta's own data

1. Official Ad Library API: per Meta, it searches ads about social issues, elections or politics delivered anywhere
   in the world in the past 7 years, and ads of any type delivered to the EU (the current Meta page also lists the UK)
   in the past year. The Graph reference states: ads that did not reach any location in the EU will only return if they
   are about social issues, elections or politics.
   **=> Normal commercial ads delivered in India are not available through the official API.**
   Access requires identity confirmation, a Meta developer account and app.
2. The public Ad Library website lets anyone search active ads across Meta products. It is a UI, not a contract.
3. Spend and impressions ranges exist for political/issue ads only. EU/UK ads add targeting and reach breakdowns.
   **Commercial ads in India: no spend, impressions or reach. Actual spend = "Not publicly available".**
4. Outside political/EU, commercial ads generally appear in the library only while active. When paused they
   disappear, and creative media URLs expire. This is why *we* must snapshot at every run. Multiple secondary sources
   and the tracker README say this; not yet confirmed by us.
5. Sources conflict on details (some say the API is EU-only, one earlier reference includes the UK). We rely on Meta's own
   pages where retrieved and mark the rest unverified.

## Provider matrix

| | MetaOfficialApiProvider | MetaPublicUiProvider | ApifyProvider (optional) | ManualImportProvider |
|---|---|---|---|---|
| Supported countries | Political/issue: worldwide. Any ad: EU (UK per Meta page) | Whatever the public library shows per country, incl. India (claimed by library; **to verify**) | Same as underlying actor; varies by actor | n/a |
| Commercial ads | **EU/UK only. Not India** | Yes (expected, to verify for India) | Yes (actor-dependent) | User-supplied |
| Political/issue | Yes (7 yrs) | Yes | Yes | User-supplied |
| Historical ads | Political 7 yrs; EU/UK 1 yr | **Active only for commercial**; history only from our own snapshots | Actor-dependent; mostly active ads | Whatever user has |
| Active ads | Yes | Yes | Yes | n/a |
| Creative data | Snapshot URL + text fields; media not a stable file | Text + image/video URLs (expiring) | Media URLs, sometimes expiring | Whatever exported |
| Ad copy | Yes | Yes (body, title, caption, link desc, CTA) | Yes | Yes |
| Landing page | Link fields on some ads | Destination URL per creative | Yes (`linkUrl`) | If present |
| Spend data | Range for political/issue; EU reach | None for commercial | Passes through what Meta exposes | n/a |
| Rate limits | Enforced by Meta (error 613). A third-party guide says 200 calls/hour, **unverified** | Unpublished; we self-throttle | Apify plan limits + per-result billing | n/a |
| Authentication | Developer token + verified identity | None (no login) | Apify API token | None |
| Terms/risk | Sanctioned by Meta | **Unofficial. Reverse-engineered internal GraphQL in the library we'd wrap. Meta terms restrict automated collection without permission (verify current text). Can break or be blocked at any time** | Shifts the operational burden to Apify; does not remove the legal question. Per-result cost | None |
| Reliability | Untested; expected stable | Untested; expected fragile (internal `doc_id`s change) | Untested; depends on actor maintainer | High |

## Provider by provider

### MetaOfficialApiProvider (built as an interface + stub in slice 1, used for EU/UK/political research)
- Can: ad ID, page ID/name, delivery dates, platforms, creative text (bodies, link titles, descriptions, captions),
  `ad_snapshot_url`, byline (political), spend/impression ranges (political/issue), EU reach/targeting (EU/UK).
- Cannot: commercial ads outside EU/UK. Includes India. Also no raw media files (snapshot URL is a rendered page).
- Why: policy scope (DSA and political transparency), not a technical gap.
- Freshness: near real time at call time; 1-year (EU/UK) or 7-year (political) retention.
- Origin label: `official_api`. Terms: Meta Platform Terms and identity verification.

### MetaPublicUiProvider (the provider that actually serves India commercial ads)
- Can (expected): all active ads for a Page in a chosen country, copy, CTA, destination URL, platforms, delivery
  start, active flag, display format, carousel cards, image/video URLs, Page picture/likes/categories.
- Cannot: spend, leads, conversions, ROAS, impressions for commercial ads, targeting, ads that are no longer running (except
  from our own earlier snapshots), private ad accounts.
- Why: Meta does not publish these for commercial ads.
- Freshness: live at run time. Media URLs expire, so we download at collection time.
- Origin label: `public_ui`. Terms/risk: unofficial. **No login, no cookies, no captcha solving, no bot-protection evasion
  in our adapter.** On a block or challenge the run stops and is logged, not retried aggressively.
- Implementation options for this adapter (see open decision D1).

### ApifyProvider (optional, off by default)
- Can/Cannot: same data envelope as the public UI. Adds paid infrastructure and per-result cost (one actor lists from
  $1.00 per 1,000 results). Field names differ by actor.
- Freshness: at actor run time. Origin label: `third_party`.
- Terms: Apify's terms + the actor author's; Meta's terms question remains.

### ManualImportProvider (slice 1, low effort, zero terms risk)
- Lets you load CSV/JSON exported elsewhere (Foreplay, Ad Library exports, your own captures). Also our test fixture path.
- Origin label: `user_import`.

## Open decisions for you (block the real-data run)

- **D1: How aggressive may the public-UI adapter be?** The library used by the tracker repo mimics a Chrome browser
  fingerprint and supports rotating proxies. Your rule says no bypassing bot protection. My proposed default: single
  IP, low request rate, no proxy rotation, stop on any challenge/block, no captcha solving. Whether even the browser
  impersonation in that library crosses your line is your call; I will not silently enable rotation.
- **D2: Wrap `meta-ads-collector` (MIT, third-party dependency) or write our own minimal client?** Wrapping is faster but
  inherits its fragility and its evasion features (which we can leave switched off). Writing our own means owning
  breakage. Recommendation: wrap it behind our interface so it is swappable.
- **D3: India-specific check.** First real run must confirm that commercial ads for an Indian Page actually appear.
