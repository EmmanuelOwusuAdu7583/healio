---
name: stitch-ui
description: Restyle or build Healio Flask templates using the Stitch AI design system (Tailwind CDN + Material Symbols + Material Design 3 tokens) that the patient-facing pages already use. Invoke when creating a new page or reworking an existing page's UI in this repo, or when asked to make a page "match the app" / "look like the rest of Healio".
---

# Stitch UI design system

Healio's patient-facing pages (login, home, weekly check-in, history, notes) were
redesigned from Stitch AI (Google) mockups into Tailwind-CDN-based Jinja templates.
This skill captures that system so new or reworked pages stay visually consistent
instead of drifting back to the old hand-written `static/css/style.css` look.

## Current state

Every page in the app has been converted to the Stitch system: `welcome.html`,
`patient_login.html`, `doctor_login.html`, `admin_login.html`,
`patient_dashboard.html`, `weekly_tracker.html`, `patient_history.html`,
`patient_notes.html`, `patient_checkin.html`, `doctor_dashboard.html`,
`patient_detail.html`, `new_patient.html`, `admin_doctors.html`.

`base.html`, `static/css/style.css`, `_patient_nav.html`, and `_doctor_nav.html`
are dead code — nothing extends or includes them anymore. They were
intentionally left in place rather than deleted (this repo isn't under git yet,
so deletion wouldn't be easily reversible) — safe to remove once you're sure
nothing needs them, or once git is initialized here.

Don't mix the two systems on one page — a page is either fully Stitch-styled
or fully old-CSS. Pick a page, convert the whole thing.

## Shared partials — always include these, don't duplicate their contents

- `templates/_stitch_head.html` — Tailwind CDN script + MD3 color/spacing/font
  token config + all custom component CSS (`.bento-card`, `.hstar-rating`,
  `.htoggle-switch`, `.star-active`, gradient/elevation helpers). This is the
  single source of truth for the design tokens — if a page needs a new token
  or component class, add it here, not inline in the page.
- `templates/_stitch_topbar.html` — fixed top app bar (Healio logo + notification
  bell). Used on every patient page except login (login has its own full-bleed
  hero layout).
- `templates/_stitch_bottomnav.html` — patient bottom nav (Home / Check-in /
  History / Notes). Reads a Jinja `active` variable (`"home"`, `"checkin"`,
  `"history"`, `"notes"`) passed from the route's `render_template(...)` call to
  highlight the current tab.
- `templates/_stitch_doctor_bottomnav.html` — doctor bottom nav (Home / Patients
  / Add), same `active` pattern (`"home"`, `"patients"`, `"add"`). Admin pages
  have no bottom nav (matches the original design — just a top header with a
  logout icon).
- `templates/_stitch_flash.html` — flash message banner styled for this system.

## Page skeleton for a new/reworked page

```jinja
<!DOCTYPE html>
<html class="light" lang="en"><head>
{% set page_title = "Healio | <Page Name>" %}
{% include "_stitch_head.html" %}
</head>
<body class="bg-surface text-on-surface font-body-md selection:bg-primary-container selection:text-on-primary-container">
{% include "_stitch_topbar.html" %}
<main class="pt-16 pb-24 px-margin-mobile md:px-margin-desktop max-w-7xl mx-auto">
  ...page content...
</main>
{% include "_stitch_bottomnav.html" %}
</body></html>
```

Important: `{% set page_title = ... %}` must come **before** the
`{% include "_stitch_head.html" %}` line — `_stitch_head.html` reads it via
`{{ page_title|default('Healio') }}`. Don't use `{% block %}` for the title;
these partials are `{% include %}`d, not `{% extends %}`d, so Jinja block
overriding doesn't apply here.

## Component conventions

- **Cards:** `class="bento-card bg-surface-container-lowest border border-outline-variant rounded-xl p-md flex flex-col gap-sm"` for content cards; add `.bento-card` to anything that should lift on hover.
- **Stat tiles:** icon in a `w-12 h-12 rounded-full bg-{color}-container/10` circle next to a label/value pair — see the three tiles at the top of `patient_dashboard.html`.
- **Star rating:** use real radio inputs (`name="satisfaction_rating"`, values 5→1 in DOM order) wrapped in `.hstar-rating` — the CSS handles the fill direction via `row-reverse` plus the `~` sibling combinator. Don't rebuild this with JS/checkboxes; the radio version is keyboard-accessible and posts a real form value.
- **Toggles:** `.htoggle-switch` wrapping a checkbox + `.htoggle-bg` + `.htoggle-dot` spans, in that order (the CSS depends on that sibling order).
- **Empty states:** dashed border card — `class="bento-card border-2 border-dashed border-outline-variant rounded-xl p-md flex flex-col items-center justify-center gap-2 text-on-surface-variant min-h-[140px]"`.

## When converting an old-CSS page

1. Read the current route in `app.py` to know exactly what Jinja variables are
   already passed in — don't invent new backend fields unless the page genuinely
   needs one (e.g. `patient_dashboard()` needed one extra query, `latest_report`,
   added for the Home stat card).
2. Preserve existing behavior: server-side search/filter JS (see
   `patient_history.html`), form field `name` attributes (must match what the
   Flask route's `request.form.get(...)` expects), and any validation.
3. Map the old page's data fields onto the bento-card / stat-tile / form
   patterns above rather than copying old CSS classes forward.
4. Test by curling the route with a real session cookie (log in via `curl -c
   cookies.txt -X POST .../login -d ...`) rather than assuming a Jinja render
   is error-free — undetected `TemplateSyntaxError`s render as Flask's debug
   traceback page, not a clean 500, and are easy to miss without checking.
5. If Flask's dev server was already running before you edited `app.py`, its
   `debug=True` reloader doesn't always pick up the change reliably in this
   environment — restart the process rather than trusting the auto-reload.
