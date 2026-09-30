# Dashboard Styling & UI Conventions

**Last Updated:** 2026-09-28 (Trade Dashboard v6.11.1)

This is the house style of the Trade Dashboard, a Flask app. It covers the look, the page
structure, and the frontend behaviour. It is written so that it can be handed to a **new**
Flask project, which will not have this repository, and produce dashboards that look and
behave the same.

It is self-contained. Everything needed is below: the design rules, a complete stylesheet,
a Jinja base template, shared JavaScript helpers, an example page and an example Flask
blueprint.

> **For an AI assistant reading this in another project:** treat the **Rules** sections as
> binding. Copy the reference files in [section 12](#12-reference-files) into the project
> as-is, then build every page from `base.html`. Paste the block in
> [section 13](#13-claudemd-snippet-for-the-new-project) into that project's `CLAUDE.md` so
> the rules persist across sessions.

---

## 1. Design philosophy

The whole look fits in one sentence: **white cards on a light gray page, system font, a
single blue, and color only where it means something.**

1. **Simple and clean, mostly without color.** Structure comes from white surfaces, soft
   shadows, and 1px light-gray borders, not from colored backgrounds. Most of the page is
   white, `#f8f9fa` and gray text.
2. **Color is semantic, never decorative.** Only a few things get color:
   - **Blue `#007bff`**: primary actions, the active nav item, focus, the selected tab.
   - **Green `#28a745` and red `#dc3545`**: positive and negative numbers (P&L), success and
     failure, safe and dangerous.
   - **Pale tints** (the alert palette): status messages, chips, warnings.
   - **Selection highlight `#d6e6ff`**: the rows or cells the user has picked.
   If an element has no meaning to convey, it stays neutral gray.
3. **No gradients, no dark blocks, no new accent colors.** A blue-to-purple gradient and a
   dark `#212529` panel were both removed from this app because they were the heaviest
   things on their pages. Each page uses one blue, `#007bff`.
4. **Built on Bootstrap 4's palette, but without Bootstrap.** The hex values are Bootstrap
   4's (primary, secondary, success, danger, and the alert tints), but there is no
   framework. It is a small hand-written stylesheet with no build step and no CDN.
5. **Dense but calm.** These are data dashboards: tables of numbers, stat tiles, forms.
   Font sizes step down (24 → 20 → 14 → 13 → 12 → 11px) instead of adding weight or color.
6. **Consistency across pages matters more than any one page.** Every page has the same
   header, the same nav, the same section cards and the same buttons. A user moving between
   pages should see only the content change.

---

## 2. Design tokens

### 2.1 Colors

| Token | Hex | Used for |
|---|---|---|
| Page background | `#f8f9fa` | `body` |
| Surface | `#ffffff` | header, sections, modals, table containers |
| Muted surface | `#f8f9fa` | cards, stat tiles, table headers, row hover |
| Border | `#dee2e6` | cards, tab underline |
| Light border | `#e9ecef` | stat tiles, dividers, sub-menu track |
| Row line | `#eeeeee` | table row separators |
| Input border | `#dddddd` | inputs, selects |
| Text | `#333333` | headings, body text, values |
| Muted text | `#666666` | subtitles, labels, loading text |
| Faint text | `#888888` | hints (`<small>`), empty states |
| Subtle text | `#495057` | sub-menu buttons, notes |
| **Primary** | `#007bff` (hover `#0056b3`) | primary buttons, active nav/tab/sub-menu, focus |
| **Secondary** | `#6c757d` (hover `#5a6268`) | nav buttons, secondary buttons, Back |
| **Success** | `#28a745` (hover `#218838`) | positive values, success buttons, "on/safe" |
| **Danger** | `#dc3545` (hover `#c82333`) | negative values, destructive buttons, Cancel, "live/armed" |
| **Warning** | `#ffc107` | warning badge, unsaved-change border |
| Disabled | `#cccccc` | disabled buttons |
| Selection | `#d6e6ff` | selected table rows or cells |

**Tint palette** (pale background / border / text), used by alerts and chips:

| Meaning | Background | Border | Text |
|---|---|---|---|
| Success | `#d4edda` | `#c3e6cb` | `#155724` |
| Error | `#f8d7da` | `#f5c6cb` | `#721c24` |
| Warning | `#fff3cd` | `#ffeaa7` | `#856404` |
| Info (transient) | `#d1ecf1` | `#bee5eb` | `#0c5460` |
| Info (explanatory box) | `#e7f3ff` | `#b6d4fe` | `#084298` |
| Blue chip | `#cce5ff` | none | `#004085` |
| Neutral chip | `#e2e3e5` | none | `#383d41` |
| Hero panel | `#e3f2fd` | `#bbdefb` | headline `#0d47a1`, labels `#546e7a` |
| Unsaved change | `#fff8e1` | `#ffc107` | inherit |

### 2.2 Typography

- **Font stack:** `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`,
  the OS's native UI font. No web fonts.
- **Scale:**

| Element | Size | Weight | Color |
|---|---|---|---|
| Page title `h1` (in header) | browser default (2em) | bold | `#333` |
| Page subtitle | 14px | normal | `#666` |
| Section title `h2` | 20px | bold | `#333` |
| Card title `h3` | browser default | bold | `#333` |
| Stat tile value | 24px | 700 | `#333` or green/red |
| Body / inputs | 14px | normal | `#333` |
| Tables (dense) | 13px | normal | `#333` |
| Form labels | 13px | 500 | `#333` |
| Stat labels, badges, sub-menu | 12px | 500-700 | `#666` |
| Hints (`small`), chips | 11px | normal/600 | `#888` |

- Stat labels and badges use `text-transform: uppercase`.
- Numbers in tables use `font-variant-numeric: tabular-nums` so the columns line up.

### 2.3 Spacing, radius, shadow

- **Spacing unit is 5px.** The common values are 5, 10, 15 and 20px. Page padding, section
  padding and the gap between sections are all **20px**, and grid gaps are 15-20px.
- **Radius:** 8px for sections, cards, the header and modals. 6px for inner panels and the
  sub-menu track. 4px for buttons, inputs, badges and alerts. 3px for chips. 50% for dots.
- **Shadow:** `0 2px 4px rgba(0,0,0,0.1)` on the header and sections (the only elevation
  level on the page). Modals get `0 8px 24px rgba(0,0,0,0.2)`.
- **Max width:** the container is `1400px` and centered. Pages dominated by wide tables use
  `1600px`.

---

## 3. Page anatomy

Every page has the same vertical structure:

```
┌──────────────────────────────────────────────────────────────────────┐
│ .header                                                              │
│ ┌ .header-top ─────────────────────────────────────────────────────┐ │
│ │ Page Title                         [Nav1] [Nav2] [Nav3] [Nav4]   │ │
│ │ One-line description               (.nav-buttons, active=blue)   │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│ ┌ .header-bottom (optional) ───────────────────────────────────────┐ │
│ │                                   ⟨ Sub1 | Sub2 | Sub3 ⟩ .sub-menu│ │
│ └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
  #statusMessages   ← transient alerts appear here
┌ .section ────────────────────────────────────────────────────────────┐
│ Section Title (h2)                         [actions]  (.section-header)│
│ ...content: stat grid / form / table / tabs...                        │
└──────────────────────────────────────────────────────────────────────┘
┌ .section ────────────────────────────────────────────────────────────┐
│ ...                                                                  │
└──────────────────────────────────────────────────────────────────────┘
  (modals live at the end of <body>, outside .container)
```

Rules:

- **Browser tab title: `<App Prefix> - <Page Name>`.** Every page's `<title>` starts with
  one short prefix naming the app by the system it fronts, then ` - `, then the page name:
  `Schwab - Trade Desk`, `Crypto - Market Dashboard`. The prefix is what tells the apps
  apart in a crowded tab strip, so:
  - it goes **first** - the end of a title is the part the browser truncates;
  - it is **identical on every page** of the app, including server-rendered utility pages
    (OAuth callbacks, error pages);
  - it appears **once** - `Schwab - Authentication Status`, never
    `Schwab - Schwab Authentication Status` - and nothing follows the page name (no
    `- MyApp` suffix);
  - the page name is the page's `h1` text (less the prefix, if the `h1` carries it too),
    shortened if it is long.

  The prefix is defined once, as `APP_TITLE_PREFIX` in `app.py`, and `base.html` applies
  it; pages set only `page_title`. A project not yet on `base.html` types the prefix into
  every `<title>` by hand, and every new page must too.
- **One `.header` per page**, always first. The title is on the left and the top nav on the
  right. The subtitle is one short sentence saying what the page is for.
- **Content lives in `.section` cards.** Each card is a white panel with one job and an `h2`
  title. Sections are separate cards, never nested.
- **Section actions go on the right of the section title**, in a `.section-header` row:
  the Refresh button, filters, "+ Add", and the status line.
- **`#statusMessages`** sits directly under the header on every page. Transient
  success/error messages go there, not in `alert()`.
- **Modals are siblings of `.container`**, placed at the end of `<body>`.

---

## 4. Navigation: three tiers

The three tiers look different on purpose, so a user can always tell *where* they are from
*what they are looking at*.

| Tier | Component | Looks like | Placement | Moves between |
|---|---|---|---|---|
| 1 | `.nav-buttons` | solid gray buttons, active is solid blue | header, top right | major app sections (page loads) |
| 2 | `.sub-menu` | small buttons in a light-gray pill track, active is blue | header bottom, **or** right side of the first section's title | sibling pages within one section (page loads) |
| 3 | `.tabs` / `.tab` | text tabs with a 3px blue underline | top of a section's content | panels within one page (no page load) |

### Rules

- 🚨 **Top nav is reserved for major sections. Do not add a button to it without explicit
  permission from the user.** A new feature gets a sub-menu entry or a button inside its own
  section, not a top-nav button.
- The top nav is **identical on every page**: same items, same order. Only the `active`
  class moves. Generate it from one list (see `NAV_ITEMS` in
  [section 12.4](#124-flask-wiring-apppy)) so it cannot drift.
- Every page in a section repeats that section's sub-menu, with its own entry marked
  `active`.
- Page-specific navigation, such as a "Back to list" link or a filter, goes in the content
  area and lines up with the section title. It never goes in the header.
- Tabs switch panels in place (`display` toggle). If a "tab" loads a different URL, it is a
  sub-menu, not a tab.

---

## 5. Components

The CSS for all of these is in [section 12.1](#121-staticcssdashboardcss). This section
covers **when** to use each one, with its markup.

### 5.1 Section with header actions

```html
<div class="section">
    <div class="section-header">
        <h2>Open Positions</h2>
        <div class="section-actions">
            <span id="positionsStatus" class="status-line"></span>
            <button class="btn secondary" id="refreshBtn" onclick="refreshPositions()">Refresh</button>
            <button class="btn success" onclick="openModal('addModal')">+ Add</button>
        </div>
    </div>
    <!-- content -->
</div>
```

### 5.2 Stat tiles (KPI row)

This is the row of summary numbers at the top of a dashboard. Put it in its own `.section`
with no title, or at the top of the first section.

```html
<div class="stat-grid">
    <div class="stat-card"><div class="value" id="statOpen">-</div><div class="label">Open Positions</div></div>
    <div class="stat-card"><div class="value" id="statPL">-</div><div class="label">Total P&amp;L</div></div>
</div>
```

Set the value's color from its sign: `el.className = 'value ' + signClass(v)`. Use green and
red only on values that have a direction (P&L, change). Counts stay `#333`.

### 5.3 Hero panel

This is a pale blue band for the one headline figure on a page, such as account value. Use
at most one per page. It is the only large tinted surface allowed.

```html
<div class="hero">
    <div class="hero-headline">
        <div class="label">Account Value</div>
        <div class="value" id="heroValue">-</div>
    </div>
    <div class="hero-metrics">
        <div class="hero-metric"><div class="value" id="heroCash">-</div><div class="label">Cash</div></div>
        <div class="hero-metric"><div class="value" id="heroDay">-</div><div class="label">Day Change</div></div>
    </div>
</div>
```

### 5.4 Cards and grid

A `.card` is a gray, bordered panel **inside** a section, used to group related controls or
facts side by side. `.grid` lays cards out responsively (min 250px, one column on mobile).

```html
<div class="grid">
    <div class="card"><h3>Settings</h3> ... </div>
    <div class="card"><h3>Status</h3> ... </div>
</div>
```

### 5.5 Forms

- Wrap each field in `.form-group`: label on top, full-width input, and an optional
  `<small>` hint underneath.
- Use `.controls-grid` for a horizontal filter or control bar. It lays fields out in
  auto-fit columns bottom-aligned, so a button in the last cell lines up with the inputs.
  Give that cell an empty `<label>&nbsp;</label>`.
- Use `.form-row` for two fields side by side in a modal.
- `.form-actions` is a right-aligned button row. Add `.split` to put the first child on the
  left (wizards).
- Add `.has-changes` to an input whose value differs from what was saved (amber border and
  tint), and enable Save only while something has changed.

```html
<div class="controls-grid">
    <div class="form-group">
        <label for="symbol">Symbol</label>
        <input type="text" id="symbol" placeholder="e.g. AAPL" autocomplete="off">
        <small>Underlying stock symbol</small>
    </div>
    <div class="form-group">
        <label for="range">Range</label>
        <select id="range"><option>30 days</option><option>90 days</option></select>
    </div>
    <div class="form-group">
        <label>&nbsp;</label>
        <button class="btn" onclick="load()">Load</button>
    </div>
</div>
```

### 5.6 Buttons

| Class | Color | Use for |
|---|---|---|
| `.btn` | blue | the primary action in a group (Load, Save, Next) |
| `.btn.success` | green | create or commit (+ Add, Submit, Place order) |
| `.btn.secondary` | gray | neutral or secondary (Refresh, View, Back, Reset) |
| `.btn.danger` | red | destructive (Delete, Close position) **and every wizard Cancel** |
| `.btn.small` | (modifier) | buttons inside table rows |
| `:disabled` | light gray | unavailable, or in flight |

- **One primary (blue or green) button per group.** Everything else is secondary.
- **In-flight state:** disable the button and change its label ("Refresh" becomes
  "Refreshing..."), then restore both in `finally`. Use `setBusy()` from
  [section 12.3](#123-staticjsdashboardjs).
- Destructive actions get a `confirm()` naming exactly what will happen, or a modal with an
  explicit acknowledgement checkbox for anything irreversible or real-money.

### 5.7 Tables

- Wrap tables in `.table-wrap` (horizontal scroll on narrow screens). For long lists, use
  `.table-scroll` (max height 520px with a sticky header).
- **Text columns are left-aligned. Number columns are right-aligned** (`class="num"` on both
  `th` and `td`).
- Use `table.compact` for dense numeric tables (13px, tighter padding, no wrapping).
- Use `<strong>` for the row's identifying cell (symbol or name).
- **Every table body has an explicit state row**: "Loading...", "No positions yet.", or the
  error in red. Never leave it blank. Use `<td colspan="N" class="empty">`, with `N`
  matching the header column count.
- Row actions are `.btn.small` in the last column, secondary (gray) unless destructive.
- Selected rows get `class="selected"` (`#d6e6ff`). Row hover is `#f8f9fa`.

```html
<div class="table-wrap">
    <table class="compact">
        <thead><tr>
            <th>Symbol</th><th>Status</th><th class="num">Qty</th><th class="num">P&amp;L</th><th></th>
        </tr></thead>
        <tbody id="positionsBody">
            <tr><td colspan="5" class="empty">Loading...</td></tr>
        </tbody>
    </table>
</div>
```

### 5.8 Badges vs chips

These are two strengths of label, so the page does not scream:

- **`.badge`** (solid fill, white uppercase text). Use it for a small number of
  **high-signal states** that must stand out: `LIVE` versus `PAPER`, `FAILED`. Variants:
  `primary`, `success`, `danger`, `warning`, `secondary`.
- **`.chip`** (pale tint, colored text). Use it for **routine status labels in table rows**:
  `OPEN`, `CLOSED`, `EXPIRED`, `BULL`, `BEAR`. Variants: `success`, `danger`, `warning`,
  `info`, and the neutral default.

A table column full of solid badges is too loud. Use chips there.

### 5.9 Messages: alerts, info box, note, status line

| Component | Lifetime | Use for |
|---|---|---|
| `#statusMessages` + `showSuccess/showError/...` | transient (3-5s) | the result of an action the user just took |
| `.alert.alert-{success,error,warning,info}` | persistent | inline messages that stay (validation errors, blockers) |
| `.info-box` | permanent | a paragraph at the top of a section explaining what it does and why |
| `.note` | permanent | informational, non-blocking commentary (gray left bar) |
| `.status-line` | until the next action | small gray text beside a Refresh button: "Updated 10:42:03" or "Updated 5, skipped 2 (no quote)" |
| `.banner-error` | until resolved | a page-level problem such as an expired login, with a link to fix it |

**Blockers versus notes:** if something *prevents* an action, show it as an
`.alert.alert-warning` with a list and disable the action button. If it only *informs*,
show it as a `.note`. Never block on a note.

### 5.10 Modals

```html
<div class="modal-overlay" id="addModal">
    <div class="modal">
        <h3>Add Symbol</h3>
        <div class="form-group">
            <label for="addSymbol">Symbol</label>
            <input type="text" id="addSymbol">
        </div>
        <div class="alert alert-error" id="addError" hidden></div>
        <div class="form-actions">
            <button class="btn secondary" onclick="closeModal('addModal')">Cancel</button>
            <button class="btn success" onclick="submitAdd()">Add</button>
        </div>
    </div>
</div>
```

- Open and close with `openModal(id)` / `closeModal(id)`, which toggle `.active`. Use one
  convention everywhere.
- Use `.modal.wide` (900px) for wizards and tables, and the default (520px) for small
  forms. Content scrolls inside the modal (max 90vh).
- Clicking the overlay or pressing Escape closes it (handled in `dashboard.js`).
- Show errors **inside** the modal, next to the form, not behind it.

### 5.11 Multi-step wizards

This is a step indicator at the top, one `.wizard-content` panel per step, and a strict
button layout.

🚨 **Wizard button rule:** Back on the **left** (gray, hidden on step 1), then Cancel
(**always red**) and Next/Submit (blue or green, **rightmost**) grouped on the right.

```html
<div class="wizard-steps">
    <div class="wizard-step active" data-step="0"><div class="step-number">1</div><div class="step-label">Symbol</div></div>
    <div class="wizard-step" data-step="1"><div class="step-number">2</div><div class="step-label">Details</div></div>
    <div class="wizard-step" data-step="2"><div class="step-number">3</div><div class="step-label">Review</div></div>
</div>

<!-- Step 1: no Back -->
<div class="wizard-content active" data-step="0">
    ...
    <div class="form-actions">
        <button class="btn danger" onclick="closeModal('wizardModal')">Cancel</button>
        <button class="btn" onclick="wizardGo(1)">Next: Details</button>
    </div>
</div>

<!-- Middle / final steps: Back left, Cancel + Next right -->
<div class="wizard-content" data-step="1">
    ...
    <div class="form-actions split">
        <button class="btn secondary" onclick="wizardGo(0)">Back</button>
        <div>
            <button class="btn danger" onclick="closeModal('wizardModal')">Cancel</button>
            <button class="btn" onclick="wizardGo(2)">Next: Review</button>
        </div>
    </div>
</div>
```

Completed steps turn green, the current step is blue, and future steps are gray. Name the
next step on the Next button ("Next: Review"). The final button says what it does ("Place
Order", "Save"), not "Finish".

### 5.12 Toggle switch

```html
<label class="toggle-switch risk">
    <input type="checkbox" id="liveToggle" onchange="setMode(this.checked)">
    <span class="toggle-slider"></span>
</label>
<span class="toggle-label" id="liveLabel">PAPER</span>
```

- The default toggle is gray when off and blue when on.
- **`.risk`** is for safety switches: green when off (safe) and red when on (armed or live).
  Turning a risk switch **on** always requires a `confirm()` that says what becomes
  possible.

### 5.13 Other small components

- **Status dot:** `<span class="status-dot green"></span>System Online`. Colors are
  `green`, `yellow`, `red` and `gray`, used in health and status lists.
- **Progress bar:** `.progress-bar > .progress-bar-fill[style="width:75%"]`.
- **Loading:** `.loading` (centered muted text), or a `.spinner` above it for full-section
  loads.
- **Empty state:** `.empty-state`, a centered sentence saying what is empty and how to fill
  it ("No symbols. Add one with + Add.").
- **Collapsible:** an `h2.collapsible-header` followed by `.collapsible-content`, toggled by
  `toggleCollapsible(headerEl)`. The ▼ rotates when collapsed.
- **Segmented filter** (All / Open / Closed): `.segmented` has the same look as `.sub-menu`,
  but its buttons filter in place instead of navigating.

---

## 6. Frontend behaviour conventions

These matter as much as the CSS. They are what make the dashboards feel reliable.

### 6.1 Page lifecycle

1. Flask renders a **static template with no data**. Every table shows "Loading...".
2. On `DOMContentLoaded`, the page's inline script calls its `load*()` functions, which
   `fetch` JSON from `/api/...` and render.
3. User actions call the API, then re-render from the response (or reload).

Page-specific JS is inline in the template (`{% block scripts %}`). Shared helpers live in
`static/js/dashboard.js`. No frontend framework, no bundler: plain JS with `fetch`,
template literals and `innerHTML`.

### 6.2 API envelope

Every JSON endpoint returns:

```json
{ "success": true,  "...payload fields...": "..." }
{ "success": false, "error": "Human-readable reason" }
```

with a matching HTTP status (200 or 4xx/5xx). The `api()` helper throws on
`success: false`, on a non-2xx status, **and** on a non-JSON body. A proxy's HTML 502 page
must become a readable error, not a `JSON.parse` crash.

### 6.3 🚨 No fallbacks

**Never invent a value in the frontend to cover for a missing backend value.**

```js
// BAD - hides a backend bug behind plausible-looking data
const pl = data.total_pl || 0;
const price = data.price ?? estimatePrice(row);

// GOOD - if the backend didn't send it, the page shows NaN/undefined and the bug is visible
const pl = data.total_pl;
```

- Formatting is fine (`toFixed`, `toLocaleString`). Inventing the number is not.
- A value that is **intentionally** absent comes from the server as `null` and renders as
  an em dash (`—`), ideally with a note explaining why. `undefined` (the field is missing
  entirely) must render visibly broken.
- The same rule applies on the server: if a price fetch fails, **skip** the row and report
  it. Never write a zero or a guess.

### 6.4 The server computes, the page formats

All business math (totals, ratios, P&L, breakevens) is computed **once, on the server**, and
returned by the API. The page formats it and never re-derives it. This keeps the numbers
on-screen and in the database identical, and gives the logic one place to live.

### 6.5 Refresh and partial results

- A Refresh button shows its status in a `.status-line` beside it: "Refreshing...", then
  "Updated 10:42:03".
- **Partial success reads as partial:** "Updated 5, skipped 2 (no quote)". It never reads
  as a clean success.
- **A failed refresh never clears data already on screen.** Show the error in the status
  line and leave the last good data visible.
- Remember that "reload from the database" and "fetch fresh data from the source" are
  different operations. If both exist, give them different buttons and labels.

### 6.6 Rendering

- Build rows with template literals and assign `innerHTML` once per table. Do not append
  per row.
- **Escape anything from the server or the user** with `escapeHtml()` before interpolating
  it into HTML.
- Money is `$1,234.56`, and negative money is `-$1,234.56` (sign before the `$`). Prefix a
  signed change with `+`. P&L cells get `signClass(v)`.
- Dates: format from **local** date parts. `toISOString()` converts to UTC and rolls the day
  over for users west of UTC in the evening. Use `localDateISO()`.
- Show times as `toLocaleTimeString()` in status lines.

### 6.7 Confirmations

- Use `confirm()` for reversible or low-stakes destructive actions. The message names the
  object: `Remove AAPL from the watchlist?`
- Use a modal with an **acknowledgement checkbox** that enables the submit button for
  anything irreversible or that touches real money or external systems. Put a red-bordered
  banner in the modal stating what will happen.

---

## 7. Flask structure

```
app.py                      # creates app, registers blueprints, context processor for nav
config.py                   # env-driven config
routes/
    <feature>_routes.py     # one blueprint per feature: page route + its /api routes
utils/
    <feature>_manager.py    # business logic; routes stay thin
templates/
    base.html               # the ONLY place the header/nav markup lives
    <feature>.html          # {% extends "base.html" %}
static/
    css/dashboard.css       # the ONLY shared stylesheet
    js/dashboard.js         # shared helpers
```

- **One blueprint per feature.** It holds the page route (`/feature`, which only calls
  `render_template`) and that feature's JSON routes (`/api/feature/...`).
- **Page routes pass no data.** The page loads everything from the API, so the same
  endpoints serve the UI, tests and scripts.
- **Routes stay thin.** Validation and math live in `utils/`, and the route turns results
  and exceptions into the envelope.
- Put **`ProxyFix`** on the app when deploying behind nginx, so generated URLs use the
  public scheme and host.

### File conventions

- Every source file starts with a header comment: app name and version, file path, and a
  one-line description. Update the version when you change the file.
- Every file ends with an EOF marker: `<!-- EOF - name.html -->`, `""" EOF - name.py """`,
  `/* EOF - name.css */`, `// EOF - name.js`.

---

## 8. Responsive behaviour

There is one breakpoint, **768px**:

- The header stacks: title above, nav full-width, centered and wrapping.
- `.grid`, `.form-row` and any page-specific two-column layout become one column.
- Section padding drops to 15px, and table cell padding to 8px.
- Tabs and wizard steps wrap or stack.
- Tables scroll horizontally inside `.table-wrap`. The page body never scrolls sideways.

These are desktop-first dashboards. Mobile only has to stay usable, not optimized.

---

## 9. Accessibility minimums

- Every input has a `<label for>`.
- Keep a visible focus state. The stylesheet replaces the browser outline with a blue border
  and a soft ring. Never remove focus styling without a replacement.
- Color is never the only signal. P&L carries its sign (`-$120.00`), and status chips carry
  text.
- Use `<button>` for actions and `<a>` for navigation (the top nav and sub-menu are links
  styled as buttons, so middle-click and "open in new tab" work).

---

## 10. Differences from this repo's `templates/html-template.html`

If `html-template.html` from the original project is passed along with this document,
**this document wins**. The reference files below are a cleaned-up consolidation of what
the live pages actually use. The deliberate differences are:

| Original | Here | Why |
|---|---|---|
| CSS copied into every template's `<style>` | one `static/css/dashboard.css` | the copies drifted (container 1400 vs 1600, button padding, `h2` margins) |
| Header and nav markup copied into every page | `base.html` with Jinja blocks, nav from one list | one place to change the nav |
| `.success` / `.error` / `.info` / `.warning` as bare alert classes | `.alert.alert-success`, etc. | the bare `.success` leaked its padding, border and dark-green text into `.btn.success` |
| Nav items are `<button onclick="location.href=...">` | `<a class>` styled identically | same look, and middle-click / new tab work |
| `.btn` has `margin-right` / `margin-bottom` | no margins; containers use `gap` | margins misaligned button groups |
| `.tabs button` (10px 20px) and `.mode-tab` (12px 30px, 16px) | one `.tab` using the larger mode-tab style | the newer pages all use the larger one |
| Modals opened with `style.display='flex'` **or** `.active` | `.active` only | one convention |
| Wizard Cancel uses inline `style="background:#dc3545"` | `.btn.danger` | same color, no inline style |
| `outline: none` on focus with only a border change | border plus a soft focus ring | keyboard users can see focus |
| No global `box-sizing` | `*, *::before, *::after { box-sizing: border-box }` | `width:100%` inputs with padding overflowed |

Everything else (palette, spacing, radii, shadow, font, header layout, sub-menu, stat
tiles, status messages and their timings) is unchanged.

---

## 11. New page checklist

- [ ] `{% extends "base.html" %}` with `{% set active_nav = '...' %}`, `page_title` and
      `page_subtitle`
- [ ] Browser tab reads `<App Prefix> - <Page Name>` (from `base.html`; never hand-typed)
- [ ] Sub-menu (if the section has sibling pages) with this page marked `active`
- [ ] Content in `.section` cards; actions in `.section-header` on the right
- [ ] Every table body starts with a "Loading..." row and has empty and error states
- [ ] Numbers right-aligned (`.num`), P&L colored with `signClass()`
- [ ] All data loaded through `api()`; no values invented when a field is missing
- [ ] Busy state on every async button; partial results reported as partial
- [ ] Server data passed through `escapeHtml()` before it goes into `innerHTML`
- [ ] Wizard buttons follow the Back / Cancel(red) / Next layout
- [ ] No new top-nav button unless the user explicitly asked for one
- [ ] File header with version, and the EOF marker

---

## 12. Reference files

Copy these into the new project verbatim, then replace `MyApp` and the nav items.

### 12.1 `static/css/dashboard.css`

```css
/*
MyApp v1.0.0
File: static/css/dashboard.css
Description: Shared dashboard stylesheet - the only stylesheet. Page-specific additions go in
             a page's {% block styles %} and must reuse these tokens.
*/

/* ======================= TOKENS ======================= */
:root {
    --bg: #f8f9fa;
    --surface: #ffffff;
    --surface-muted: #f8f9fa;
    --border: #dee2e6;
    --border-light: #e9ecef;
    --row-line: #eeeeee;
    --input-border: #dddddd;

    --text: #333333;
    --text-muted: #666666;
    --text-faint: #888888;
    --text-subtle: #495057;

    --primary: #007bff;
    --primary-hover: #0056b3;
    --secondary: #6c757d;
    --secondary-hover: #5a6268;
    --success: #28a745;
    --success-hover: #218838;
    --danger: #dc3545;
    --danger-hover: #c82333;
    --warning: #ffc107;
    --disabled: #cccccc;
    --selected: #d6e6ff;

    --radius-lg: 8px;
    --radius-md: 6px;
    --radius-sm: 4px;
    --shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    --shadow-modal: 0 8px 24px rgba(0, 0, 0, 0.2);
    --focus-ring: 0 0 0 2px rgba(0, 123, 255, 0.25);

    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

/* ======================= BASE ======================= */
*, *::before, *::after { box-sizing: border-box; }

body {
    font-family: var(--font);
    margin: 0;
    padding: 20px;
    background-color: var(--bg);
    color: var(--text);
}

button, input, select, textarea { font-family: inherit; }

a { color: var(--primary); }

.container { max-width: 1400px; margin: 0 auto; }
.container.wide { max-width: 1600px; }

/* ======================= HEADER + TOP NAV ======================= */
.header {
    background: var(--surface);
    padding: 20px;
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow);
    margin-bottom: 20px;
}

.header-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 15px;
}

.header h1 { margin: 0; color: var(--text); }
.header p { margin: 5px 0 0 0; color: var(--text-muted); font-size: 14px; }

.header-bottom {
    display: flex;
    justify-content: flex-end;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--border-light);
}

.nav-buttons { display: flex; gap: 10px; flex-wrap: wrap; }

.nav-buttons a {
    display: inline-block;
    background: var(--secondary);
    color: white;
    text-decoration: none;
    padding: 10px 20px;
    border-radius: var(--radius-sm);
    font-size: 14px;
    font-weight: 500;
}

.nav-buttons a:hover { background: var(--secondary-hover); }
.nav-buttons a.active { background: var(--primary); }

/* ======================= SUB-MENU / SEGMENTED ======================= */
/* .sub-menu navigates between sibling pages; .segmented filters in place. Same look. */
.sub-menu, .segmented {
    display: inline-flex;
    gap: 8px;
    background: var(--border-light);
    padding: 6px;
    border-radius: var(--radius-md);
}

.sub-menu a, .sub-menu button, .segmented button {
    background: transparent;
    color: var(--text-subtle);
    border: none;
    text-decoration: none;
    padding: 6px 14px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    font-weight: 500;
    font-size: 12px;
}

.sub-menu a:hover, .sub-menu button:hover, .segmented button:hover { background: var(--border); }

.sub-menu a.active, .sub-menu button.active, .segmented button.active {
    background: var(--primary);
    color: white;
}

/* ======================= SECTIONS ======================= */
.section {
    background: var(--surface);
    border-radius: var(--radius-lg);
    padding: 20px;
    margin-bottom: 20px;
    box-shadow: var(--shadow);
}

.section h2 { margin: 0 0 15px 0; color: var(--text); font-size: 20px; }

.section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 15px;
}

.section-header h2 { margin: 0; }

.section-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }

.status-line { font-size: 12px; color: var(--text-muted); }

/* ======================= STAT TILES ======================= */
.stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 15px;
}

.stat-card {
    background: var(--surface-muted);
    border: 1px solid var(--border-light);
    border-radius: var(--radius-lg);
    padding: 15px;
    text-align: center;
}

.stat-card .value { font-size: 24px; font-weight: 700; color: var(--text); }

.stat-card .label {
    font-size: 12px;
    color: var(--text-muted);
    margin-top: 5px;
    text-transform: uppercase;
}

/* ======================= HERO PANEL (max one per page) ======================= */
.hero {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 20px;
    padding: 20px;
    background: #e3f2fd;
    border: 1px solid #bbdefb;
    border-radius: var(--radius-lg);
    margin-bottom: 20px;
}

.hero-headline .value { font-size: 28px; font-weight: 700; color: #0d47a1; }
.hero .label { font-size: 11px; color: #546e7a; text-transform: uppercase; margin-top: 4px; }

.hero-metrics {
    flex: 1 1 400px;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 15px;
}

.hero-metric { text-align: center; }
.hero-metric .value { font-size: 20px; font-weight: 700; color: var(--text); }

/* ======================= SEMANTIC VALUE COLORS ======================= */
/* Compound selectors so they out-specify component rules like .stat-card .value */
.positive, .value.positive, td.positive { color: var(--success); }
.negative, .value.negative, td.negative { color: var(--danger); }
.neutral, .value.neutral, td.neutral { color: var(--text-muted); }
td.positive, td.negative { font-weight: 600; }

/* ======================= CARDS + GRID ======================= */
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 20px;
}

.card {
    background: var(--surface-muted);
    padding: 20px;
    border-radius: var(--radius-lg);
    border: 1px solid var(--border);
}

.card h3 { margin: 0 0 15px 0; color: var(--text); }

/* ======================= FORMS ======================= */
.form-group { margin-bottom: 15px; }

.form-group label {
    display: block;
    margin-bottom: 5px;
    font-weight: 500;
    font-size: 13px;
    color: var(--text);
}

.form-group input,
.form-group select,
.form-group textarea {
    width: 100%;
    padding: 8px 12px;
    border: 1px solid var(--input-border);
    border-radius: var(--radius-sm);
    font-size: 14px;
    background: white;
}

.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus {
    outline: none;
    border-color: var(--primary);
    box-shadow: var(--focus-ring);
}

.form-group small { display: block; color: var(--text-faint); font-size: 11px; margin-top: 4px; }

.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }

.controls-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 15px;
    align-items: end;
}

.controls-grid .form-group { margin-bottom: 0; }

.form-actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 10px;
    margin-top: 20px;
}

.form-actions.split { justify-content: space-between; }
.form-actions > div { display: flex; gap: 10px; }

.has-changes { border-color: var(--warning) !important; background: #fff8e1 !important; }

/* ======================= BUTTONS ======================= */
.btn {
    display: inline-block;
    background: var(--primary);
    color: white;
    border: none;
    padding: 10px 15px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    font-weight: 500;
    font-size: 14px;
    text-decoration: none;
    white-space: nowrap;
}

.btn:hover { background: var(--primary-hover); }
.btn:focus-visible { outline: none; box-shadow: var(--focus-ring); }

.btn.secondary { background: var(--secondary); }
.btn.secondary:hover { background: var(--secondary-hover); }
.btn.success { background: var(--success); }
.btn.success:hover { background: var(--success-hover); }
.btn.danger { background: var(--danger); }
.btn.danger:hover { background: var(--danger-hover); }

.btn.small { padding: 5px 10px; font-size: 12px; }

.btn:disabled, .btn:disabled:hover { background: var(--disabled); cursor: not-allowed; }

/* ======================= TABLES ======================= */
.table-wrap { overflow-x: auto; }

.table-scroll {
    max-height: 520px;
    overflow: auto;
    border: 1px solid var(--border-light);
    border-radius: var(--radius-md);
}

.table-scroll th { position: sticky; top: 0; z-index: 2; }

table { width: 100%; border-collapse: collapse; }

th, td { padding: 12px; text-align: left; border-bottom: 1px solid var(--row-line); }

th { background: var(--surface-muted); font-weight: 600; color: var(--text); }

tbody tr:hover { background: var(--surface-muted); }
tbody tr.selected, tbody tr.selected:hover { background: var(--selected); }

th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }

table.compact th, table.compact td { padding: 8px 10px; font-size: 13px; white-space: nowrap; }
table.compact td.wrap { white-space: normal; }

td.empty { text-align: center; color: var(--text-faint); padding: 26px; }
td.empty.error-text { color: var(--danger); }

/* ======================= BADGES (solid, high-signal) ======================= */
.badge {
    display: inline-block;
    padding: 4px 8px;
    font-size: 12px;
    font-weight: 700;
    border-radius: var(--radius-sm);
    text-transform: uppercase;
    color: white;
    background: var(--secondary);
}

.badge.primary { background: var(--primary); }
.badge.success { background: var(--success); }
.badge.danger { background: var(--danger); }
.badge.warning { background: var(--warning); color: var(--text); }
.badge.secondary { background: var(--secondary); }

/* ======================= CHIPS (pale, routine status) ======================= */
.chip {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    font-size: 11px;
    font-weight: 600;
    background: #e2e3e5;
    color: #383d41;
}

.chip.success { background: #d4edda; color: #155724; }
.chip.danger { background: #f8d7da; color: #721c24; }
.chip.warning { background: #fff3cd; color: #856404; }
.chip.info { background: #cce5ff; color: #004085; }

/* ======================= ALERTS + MESSAGES ======================= */
.alert {
    padding: 12px;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    margin: 10px 0;
}

.alert-success { background: #d4edda; border-color: #c3e6cb; color: #155724; }
.alert-error { background: #f8d7da; border-color: #f5c6cb; color: #721c24; }
.alert-warning { background: #fff3cd; border-color: #ffeaa7; color: #856404; }
.alert-info { background: #d1ecf1; border-color: #bee5eb; color: #0c5460; }
.alert ul { margin: 6px 0 0 18px; padding: 0; }

.info-box {
    background: #e7f3ff;
    border: 1px solid #b6d4fe;
    border-radius: var(--radius-md);
    padding: 15px;
    margin-bottom: 20px;
    color: #084298;
    font-size: 14px;
}

.info-box strong:first-child { display: block; margin-bottom: 5px; }

.note {
    background: var(--surface-muted);
    border: 1px solid var(--border-light);
    border-left: 3px solid var(--secondary);
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    color: var(--text-subtle);
    padding: 10px 12px;
    margin: 12px 0;
    font-size: 13px;
}

.banner-error {
    display: flex;
    align-items: center;
    gap: 10px;
    background: #f8d7da;
    border: 1px solid #f5c6cb;
    color: #721c24;
    padding: 12px 15px;
    border-radius: var(--radius-sm);
    margin-bottom: 20px;
}

.banner-error a { color: #721c24; font-weight: 600; }

/* ======================= TABS (in-page panels) ======================= */
.tabs {
    display: flex;
    flex-wrap: wrap;
    margin-bottom: 20px;
    border-bottom: 2px solid var(--border-light);
}

.tab {
    padding: 12px 30px;
    border: none;
    background: transparent;
    cursor: pointer;
    font-size: 16px;
    font-weight: 500;
    color: var(--text-muted);
    border-bottom: 3px solid transparent;
    margin-bottom: -2px;
    transition: all 0.2s;
}

.tab:hover { color: var(--text); background: var(--surface-muted); }
.tab.active { color: var(--primary); border-bottom-color: var(--primary); }

/* ======================= MODALS ======================= */
.modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 2000;
}

.modal-overlay.active { display: flex; }

.modal {
    background: white;
    border-radius: var(--radius-lg);
    padding: 25px;
    width: 94%;
    max-width: 520px;
    max-height: 90vh;
    overflow-y: auto;
    box-shadow: var(--shadow-modal);
}

.modal.wide { max-width: 900px; }
.modal h3 { margin: 0 0 20px 0; color: var(--text); }
.modal .form-actions { padding-top: 15px; border-top: 1px solid var(--row-line); }

.danger-banner {
    background: #fdecea;
    border: 2px solid var(--danger);
    border-radius: var(--radius-md);
    padding: 12px 14px;
    margin: 14px 0;
    font-size: 13px;
    color: #8b1a1a;
}

/* ======================= WIZARD ======================= */
.wizard-steps {
    display: flex;
    margin-bottom: 25px;
    padding-bottom: 15px;
    border-bottom: 2px solid var(--border-light);
}

.wizard-step { flex: 1; text-align: center; padding: 10px; }

.wizard-step .step-number {
    width: 30px;
    height: 30px;
    border-radius: 50%;
    background: var(--border-light);
    color: var(--text-muted);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    margin-bottom: 5px;
}

.wizard-step .step-label { font-size: 12px; color: var(--text-muted); }
.wizard-step.active .step-number { background: var(--primary); color: white; }
.wizard-step.active .step-label { color: var(--primary); font-weight: 600; }
.wizard-step.completed .step-number { background: var(--success); color: white; }

.wizard-content { display: none; }
.wizard-content.active { display: block; }

/* ======================= TOGGLE SWITCH ======================= */
.toggle-switch { position: relative; display: inline-block; width: 60px; height: 30px; vertical-align: middle; }
.toggle-switch input { opacity: 0; width: 0; height: 0; }

.toggle-slider {
    position: absolute;
    inset: 0;
    cursor: pointer;
    background-color: var(--secondary);
    border-radius: 30px;
    transition: 0.3s;
}

.toggle-slider::before {
    content: "";
    position: absolute;
    height: 22px;
    width: 22px;
    left: 4px;
    bottom: 4px;
    background-color: white;
    border-radius: 50%;
    transition: 0.3s;
}

.toggle-switch input:checked + .toggle-slider { background-color: var(--primary); }
.toggle-switch input:checked + .toggle-slider::before { transform: translateX(30px); }
.toggle-switch input:focus-visible + .toggle-slider { box-shadow: var(--focus-ring); }

/* Safety switch: green = off/safe, red = on/armed */
.toggle-switch.risk .toggle-slider { background-color: var(--success); }
.toggle-switch.risk input:checked + .toggle-slider { background-color: var(--danger); }

.toggle-label { display: inline-block; margin-left: 10px; font-weight: 600; font-size: 14px; vertical-align: middle; }

/* ======================= COLLAPSIBLE ======================= */
.collapsible-header { cursor: pointer; user-select: none; }
.collapsible-header::after { content: "\25BC"; float: right; font-size: 12px; transition: transform 0.3s; }
.collapsible-header.collapsed::after { transform: rotate(-90deg); }
.collapsible-content { overflow: hidden; transition: max-height 0.3s ease-out, opacity 0.3s ease-out; }
.collapsible-content.collapsed { max-height: 0 !important; opacity: 0; }

/* ======================= SMALL COMPONENTS ======================= */
.status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 8px; background: var(--secondary); }
.status-dot.green { background: var(--success); }
.status-dot.yellow { background: var(--warning); }
.status-dot.red { background: var(--danger); }
.status-dot.gray { background: var(--secondary); }

.progress-bar { width: 100%; height: 8px; background: var(--border-light); border-radius: var(--radius-sm); overflow: hidden; }
.progress-bar-fill { height: 100%; background: var(--primary); transition: width 0.3s ease; }

.loading { text-align: center; padding: 20px; color: var(--text-muted); }
.empty-state { text-align: center; padding: 40px; color: var(--text-muted); }

.spinner {
    width: 30px;
    height: 30px;
    margin: 0 auto 15px;
    border: 3px solid #f3f3f3;
    border-top-color: var(--primary);
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* ======================= UTILITIES ======================= */
.text-center { text-align: center; }
.text-right { text-align: right; }
.text-muted { color: var(--text-muted); }
.text-primary { color: var(--primary); }
.font-bold { font-weight: 700; }
.mb-0 { margin-bottom: 0; }
.mb-1 { margin-bottom: 10px; }
.mb-2 { margin-bottom: 20px; }
.mt-0 { margin-top: 0; }
.mt-1 { margin-top: 10px; }
.mt-2 { margin-top: 20px; }
.d-flex { display: flex; }
.justify-between { justify-content: space-between; }
.align-center { align-items: center; }
.gap-1 { gap: 10px; }
.gap-2 { gap: 20px; }
[hidden] { display: none !important; }

/* ======================= RESPONSIVE ======================= */
@media (max-width: 768px) {
    .header-top { flex-direction: column; align-items: flex-start; }
    .nav-buttons { width: 100%; justify-content: center; }
    .header-bottom { justify-content: center; }
    .grid, .form-row { grid-template-columns: 1fr; }
    .section { padding: 15px; }
    th, td { padding: 8px; }
    .tab { padding: 10px 16px; font-size: 14px; }
    .wizard-steps { flex-direction: column; }
}

/* EOF - dashboard.css */
```

### 12.2 `templates/base.html`

```html
<!--
MyApp v1.0.0
File: templates/base.html
Description: Base layout - header, top nav, status area. Every page extends this.
Child templates set: active_nav, page_title, page_subtitle; optional header_bottom, styles, scripts.
-->
{% set active_nav = active_nav | default('') %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ APP_TITLE_PREFIX }} - {% block title %}{{ self.page_title() }}{% endblock %}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/dashboard.css') }}">
    {% block styles %}{% endblock %}
</head>
<body>
    <div class="container{% block container_class %}{% endblock %}">
        <!-- STANDARD HEADER -->
        <div class="header">
            <div class="header-top">
                <div>
                    <h1>{% block page_title %}{% endblock %}</h1>
                    <p>{% block page_subtitle %}{% endblock %}</p>
                </div>
                <nav class="nav-buttons">
                    {% for item in NAV_ITEMS %}
                    <a id="nav-{{ item.key }}" href="{{ item.url }}"
                       class="{{ 'active' if item.key == active_nav else '' }}">{{ item.label }}</a>
                    {% endfor %}
                </nav>
            </div>
            {% block header_bottom %}{% endblock %}
        </div>

        <!-- TRANSIENT STATUS MESSAGES -->
        <div id="statusMessages"></div>

        {% block content %}{% endblock %}
    </div>

    {% block modals %}{% endblock %}

    <script src="{{ url_for('static', filename='js/dashboard.js') }}"></script>
    {% block scripts %}{% endblock %}
</body>
</html>

<!-- EOF - base.html -->
```

### 12.3 `static/js/dashboard.js`

```js
/*
MyApp v1.0.0
File: static/js/dashboard.js
Description: Shared dashboard helpers - API envelope, status messages, formatting, modals,
             tabs, wizards, collapsibles. Page-specific code stays inline in each template.
*/

// ---------- API ----------
// Every endpoint returns { success: true, ... } or { success: false, error }.
// Throws on success:false, on non-2xx, and on a non-JSON body (e.g. a proxy's HTML 502).
async function api(url, options = {}) {
    const opts = { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } };
    if (opts.body !== undefined && typeof opts.body !== 'string') {
        opts.body = JSON.stringify(opts.body);
    }
    const resp = await fetch(url, opts);
    const text = await resp.text();
    let data;
    try {
        data = JSON.parse(text);
    } catch (e) {
        throw new Error(`HTTP ${resp.status}: ${text.slice(0, 200)}`);
    }
    if (!resp.ok || !data.success) {
        throw new Error(data.error || `HTTP ${resp.status}`);
    }
    return data;
}

// ---------- Status messages (under the header) ----------
const STATUS_DURATIONS = { success: 3000, error: 5000, warning: 4000, info: 4000 };
let statusTimer = null;

function showStatus(message, type = 'info') {
    const el = document.getElementById('statusMessages');
    el.innerHTML = `<div class="alert alert-${type}">${escapeHtml(message)}</div>`;
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => { el.innerHTML = ''; }, STATUS_DURATIONS[type]);
}
const showSuccess = (m) => showStatus(m, 'success');
const showError = (m) => showStatus(m, 'error');
const showWarning = (m) => showStatus(m, 'warning');
const showInfo = (m) => showStatus(m, 'info');

// ---------- Busy buttons ----------
// Usage: const done = setBusy(btn, 'Refreshing...'); try { ... } finally { done(); }
function setBusy(button, busyLabel) {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = busyLabel;
    return () => { button.disabled = false; button.textContent = original; };
}

// ---------- Formatting (formats values; never invents them) ----------
function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// null = the server deliberately has no value -> em dash.
// undefined = the field is missing -> "$NaN", visibly broken (no-fallbacks rule).
function formatMoney(value, decimals = 2) {
    if (value === null) return '—';
    const n = Number(value);
    const abs = Math.abs(n).toLocaleString(undefined, {
        minimumFractionDigits: decimals, maximumFractionDigits: decimals,
    });
    return (n < 0 ? '-$' : '$') + abs;
}

function formatSignedMoney(value, decimals = 2) {
    if (value === null) return '—';
    return (Number(value) > 0 ? '+' : '') + formatMoney(value, decimals);
}

function formatPercent(value, decimals = 1) {
    if (value === null) return '—';
    return Number(value).toFixed(decimals) + '%';
}

function signClass(value) {
    if (value === null) return 'neutral';
    const n = Number(value);
    return n > 0 ? 'positive' : (n < 0 ? 'negative' : 'neutral');
}

// YYYY-MM-DD from LOCAL date parts. toISOString() is UTC and rolls the day over
// for anyone west of UTC in the evening.
function localDateISO(date = new Date()) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

// Standard "state row" for a table body: Loading... / empty / error.
function tableMessage(tbody, colspan, message, isError = false) {
    tbody.innerHTML = `<tr><td colspan="${colspan}" class="empty${isError ? ' error-text' : ''}">${escapeHtml(message)}</td></tr>`;
}

// ---------- Modals ----------
function openModal(id) { document.getElementById(id).classList.add('active'); }
function closeModal(id) { document.getElementById(id).classList.remove('active'); }

document.addEventListener('click', (e) => {
    if (e.target.classList && e.target.classList.contains('modal-overlay')) {
        e.target.classList.remove('active');
    }
});
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.active').forEach((m) => m.classList.remove('active'));
    }
});

// ---------- Tabs ----------
// Markup: <div class="tabs"><button class="tab" data-tab="a">..</button></div>
//         <div class="tab-panel" data-tab="a">..</div>
function switchTab(name) {
    document.querySelectorAll('.tab[data-tab]').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
    document.querySelectorAll('.tab-panel[data-tab]').forEach((p) => { p.hidden = p.dataset.tab !== name; });
}

// ---------- Wizard (within one modal/container) ----------
function wizardGo(step, root = document) {
    root.querySelectorAll('.wizard-content').forEach((c) => c.classList.toggle('active', Number(c.dataset.step) === step));
    root.querySelectorAll('.wizard-step').forEach((s) => {
        const n = Number(s.dataset.step);
        s.classList.toggle('active', n === step);
        s.classList.toggle('completed', n < step);
    });
}

// ---------- Collapsible ----------
// Markup: <h2 class="collapsible-header" onclick="toggleCollapsible(this)">..</h2>
//         <div class="collapsible-content">..</div>
function toggleCollapsible(header) {
    const content = header.nextElementSibling;
    const collapsing = !content.classList.contains('collapsed');
    header.classList.toggle('collapsed', collapsing);
    // Start from a real height so max-height has something to animate from/to
    content.style.maxHeight = content.scrollHeight + 'px';
    requestAnimationFrame(() => {
        content.classList.toggle('collapsed', collapsing);
        if (!collapsing) {
            // Once open, drop the fixed height so later content changes are not clipped
            content.addEventListener('transitionend', () => { content.style.maxHeight = ''; }, { once: true });
        }
    });
}

// EOF - dashboard.js
```

### 12.4 Flask wiring (`app.py`)

```python
"""
MyApp v1.0.0
File: app.py
Description: Flask entry point - registers blueprints and the shared top-nav list.
"""

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from routes.positions_routes import positions_bp

app = Flask(__name__, template_folder="templates", static_folder="static")

# Behind nginx: trust X-Forwarded-Proto/Host so url_for builds public https:// URLs
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.register_blueprint(positions_bp)

# Every browser tab title starts with this (section 3): "<prefix> - <page title>".
# Name the system the app fronts, and keep it short - it is what tells apps apart in the tab strip.
APP_TITLE_PREFIX = "MyApp"

# The ONE definition of the top nav. Major sections only - do not add entries
# without the owner's explicit approval.
NAV_ITEMS = [
    {"key": "dashboard", "label": "Dashboard", "url": "/"},
    {"key": "positions", "label": "Positions", "url": "/positions"},
    {"key": "reports", "label": "Reports", "url": "/reports"},
    {"key": "logs", "label": "Logs", "url": "/logs"},
]


@app.context_processor
def inject_nav():
    return {"NAV_ITEMS": NAV_ITEMS, "APP_TITLE_PREFIX": APP_TITLE_PREFIX}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

""" EOF - app.py """
```

### 12.5 Example blueprint (`routes/positions_routes.py`)

```python
"""
MyApp v1.0.0
File: routes/positions_routes.py
Description: Positions page + JSON API. The page route renders an empty shell; all data
             comes from /api/positions/*. Math lives in utils/positions_manager.py.
"""

import logging

from flask import Blueprint, jsonify, render_template, request

from utils import positions_manager

positions_bp = Blueprint("positions", __name__)


@positions_bp.route("/positions")
def positions_page():
    return render_template("positions.html")


@positions_bp.route("/api/positions", methods=["GET"])
def list_positions():
    try:
        status = request.args.get("status", "OPEN")
        positions = positions_manager.get_positions(status)
        stats = positions_manager.get_stats()  # server computes every figure
        return jsonify({"success": True, "positions": positions, "stats": stats})
    except Exception as e:
        logging.exception("list_positions failed")
        return jsonify({"success": False, "error": str(e)}), 500


@positions_bp.route("/api/positions/refresh", methods=["POST"])
def refresh_positions():
    """Re-price open positions. A failed quote SKIPS the row - never writes a substitute."""
    try:
        result = positions_manager.refresh_prices()
        return jsonify({
            "success": True,
            "updated": result.updated,
            "skipped": result.skipped,
            "errors": result.errors,
        })
    except Exception as e:
        logging.exception("refresh_positions failed")
        return jsonify({"success": False, "error": str(e)}), 500


@positions_bp.route("/api/positions/<int:position_id>", methods=["DELETE"])
def delete_position(position_id):
    try:
        if not positions_manager.delete_position(position_id):
            return jsonify({"success": False, "error": f"Position {position_id} not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        logging.exception("delete_position failed")
        return jsonify({"success": False, "error": str(e)}), 500

""" EOF - positions_routes.py """
```

### 12.6 Example page (`templates/positions.html`)

This shows the conventions together: sub-menu, stat tiles, a section with actions, a table
with its state rows, a refresh that reports partial results, a modal, and escaping.

```html
<!--
MyApp v1.0.0
File: templates/positions.html
Description: Positions dashboard - stat tiles, open positions table, refresh, delete.
-->
{% extends "base.html" %}
{% set active_nav = 'positions' %}

{% block page_title %}Positions{% endblock %}
{% block page_subtitle %}Track open positions and their P&amp;L{% endblock %}

{% block header_bottom %}
<div class="header-bottom">
    <nav class="sub-menu">
        <a href="/positions" class="active">Open</a>
        <a href="/positions/history">History</a>
        <a href="/positions/settings">Settings</a>
    </nav>
</div>
{% endblock %}

{% block content %}
<div class="section">
    <div class="stat-grid">
        <div class="stat-card"><div class="value" id="statOpen">-</div><div class="label">Open</div></div>
        <div class="stat-card"><div class="value" id="statInvested">-</div><div class="label">Invested</div></div>
        <div class="stat-card"><div class="value" id="statPL">-</div><div class="label">Unrealized P&amp;L</div></div>
    </div>
</div>

<div class="section">
    <div class="section-header">
        <h2>Open Positions</h2>
        <div class="section-actions">
            <span class="status-line" id="positionsStatus"></span>
            <button class="btn secondary" id="refreshBtn" onclick="refreshPrices()">Refresh Prices</button>
            <button class="btn success" onclick="openModal('addModal')">+ Add</button>
        </div>
    </div>
    <div class="table-wrap">
        <table class="compact">
            <thead><tr>
                <th>Symbol</th><th>Status</th><th class="num">Qty</th>
                <th class="num">Cost</th><th class="num">Value</th><th class="num">P&amp;L</th><th></th>
            </tr></thead>
            <tbody id="positionsBody"><tr><td colspan="7" class="empty">Loading...</td></tr></tbody>
        </table>
    </div>
</div>
{% endblock %}

{% block modals %}
<div class="modal-overlay" id="addModal">
    <div class="modal">
        <h3>Add Position</h3>
        <div class="form-row">
            <div class="form-group">
                <label for="addSymbol">Symbol</label>
                <input type="text" id="addSymbol" autocomplete="off">
            </div>
            <div class="form-group">
                <label for="addQty">Quantity</label>
                <input type="number" id="addQty" min="1" step="1">
            </div>
        </div>
        <div class="alert alert-error" id="addError" hidden></div>
        <div class="form-actions">
            <button class="btn secondary" onclick="closeModal('addModal')">Cancel</button>
            <button class="btn success" id="addBtn" onclick="submitAdd()">Add</button>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
    const COLS = 7;
    let positions = [];

    async function loadPositions() {
        const body = document.getElementById('positionsBody');
        try {
            const data = await api('/api/positions?status=OPEN');
            positions = data.positions;
            renderStats(data.stats);
            renderPositions(data.positions);
            document.getElementById('positionsStatus').textContent =
                'Updated ' + new Date().toLocaleTimeString();
        } catch (e) {
            // Keep whatever was on screen if we already had rows; only replace the placeholder
            if (!body.querySelector('tr[data-id]')) tableMessage(body, COLS, e.message, true);
            showError('Failed to load positions: ' + e.message);
        }
    }

    function renderStats(s) {
        document.getElementById('statOpen').textContent = s.open_count;
        document.getElementById('statInvested').textContent = formatMoney(s.invested);
        const pl = document.getElementById('statPL');
        pl.textContent = formatSignedMoney(s.unrealized_pl);
        pl.className = 'value ' + signClass(s.unrealized_pl);
    }

    function renderPositions(rows) {
        const body = document.getElementById('positionsBody');
        if (!rows.length) { tableMessage(body, COLS, 'No open positions. Add one with + Add.'); return; }
        body.innerHTML = rows.map((p) => `
            <tr data-id="${p.Id}">
                <td><strong>${escapeHtml(p.Symbol)}</strong></td>
                <td><span class="chip success">${escapeHtml(p.Status)}</span></td>
                <td class="num">${p.Quantity}</td>
                <td class="num">${formatMoney(p.CostBasis)}</td>
                <td class="num">${formatMoney(p.CurrentValue)}</td>
                <td class="num ${signClass(p.UnrealizedPL)}">${formatSignedMoney(p.UnrealizedPL)}</td>
                <td class="num"><button class="btn small danger" onclick="deletePosition(${p.Id})">Delete</button></td>
            </tr>`).join('');
    }

    async function refreshPrices() {
        const status = document.getElementById('positionsStatus');
        const done = setBusy(document.getElementById('refreshBtn'), 'Refreshing...');
        status.textContent = 'Refreshing prices...';
        try {
            const r = await api('/api/positions/refresh', { method: 'POST' });
            await loadPositions();
            // Partial success reads as partial - never as a clean success
            status.textContent = r.skipped
                ? `Updated ${r.updated}, skipped ${r.skipped} (no quote)`
                : `Updated ${r.updated} position(s)`;
        } catch (e) {
            status.textContent = 'Refresh failed: ' + e.message;   // table left as-is
        } finally {
            done();
        }
    }

    // Pass only the numeric id through onclick; look the rest up. Interpolating strings into
    // an inline handler is an injection risk even when HTML-escaped.
    async function deletePosition(id) {
        const symbol = positions.find((p) => p.Id === id).Symbol;
        if (!confirm(`Delete the ${symbol} position (#${id})? This cannot be undone.`)) return;
        try {
            await api(`/api/positions/${id}`, { method: 'DELETE' });
            showSuccess(`Deleted ${symbol}`);
            loadPositions();
        } catch (e) {
            showError(e.message);
        }
    }

    async function submitAdd() {
        const err = document.getElementById('addError');
        err.hidden = true;
        const done = setBusy(document.getElementById('addBtn'), 'Adding...');
        try {
            await api('/api/positions', {
                method: 'POST',
                body: {
                    symbol: document.getElementById('addSymbol').value.trim().toUpperCase(),
                    quantity: Number(document.getElementById('addQty').value),
                },
            });
            closeModal('addModal');
            showSuccess('Position added');
            loadPositions();
        } catch (e) {
            err.textContent = e.message;   // error stays inside the modal
            err.hidden = false;
        } finally {
            done();
        }
    }

    document.addEventListener('DOMContentLoaded', loadPositions);
</script>
{% endblock %}

<!-- EOF - positions.html -->
```

---

## 13. `CLAUDE.md` snippet for the new project

Paste this into the new project's `CLAUDE.md` so the conventions persist:

```markdown
## UI Styling (see docs/STYLING.md - binding)

- All pages extend `templates/base.html`; the only stylesheet is `static/css/dashboard.css`,
  shared JS is `static/js/dashboard.js`. Do not copy header/nav markup or base CSS into pages.
- Look: white `.section` cards on #f8f9fa, system font, one blue (#007bff). Color is
  semantic only (blue = primary/active, green/red = positive/negative, pale tints = status).
  No gradients, no dark panels, no new accent colors.
- TAB TITLES: every `<title>` is `<App Prefix> - <Page Name>` - prefix first, same on every
  page (utility/OAuth pages too), set once as APP_TITLE_PREFIX and applied by base.html.
- 🚨 TOP NAV: never add a top-nav entry (NAV_ITEMS in app.py) without explicit permission.
  Sibling pages use the `.sub-menu`; in-page panels use `.tabs`.
- 🚨 NO FALLBACKS: never write `value || 0` or estimate a missing backend value in the
  frontend. Missing data must look broken. Intentional absence comes from the server as
  null and renders as an em dash.
- The server computes all figures; the page only formats them.
- API envelope: `{success: true, ...}` / `{success: false, error}`. Use the `api()` helper.
- Tables: numbers right-aligned (`.num`), explicit Loading/empty/error row, `.btn.small` row
  actions. Escape server data with `escapeHtml()` before putting it in innerHTML.
- Async buttons use `setBusy()`; refreshes report partial results as partial and never
  clear on-screen data on error.
- 🚨 WIZARDS: Back (gray, left, hidden on step 1) | Cancel (`.btn.danger`, always red) +
  Next/Submit (rightmost, blue/green), grouped on the right.
- Every file has a version header comment and an EOF marker.
```

<!-- EOF - STYLING.md -->
