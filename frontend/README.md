# FallFW - research console (frontend)

A no-build static single-page app served by nginx. It talks to the gateway REST
API and is organized around the **research** (detector evaluation) rather than
container management. Design language ported from the `proj-` project (dark
dot-grid canvas, dotted hairlines, square corners, diagonal-striped bars), with
the **Geist** font kept from the previous build.

> Replaces the previous Next.js dashboard, whose source was no longer present in
> the repo (only the compiled `.next` bundle remained).

## Layout

```
web/
  index.html            shell (loads Geist + theme.css + app.js)
  css/theme.css         all styling (proj- design tokens + components)
  js/
    app.js              shell, nav, language, system drawer, routing
    api.js              gateway REST client (base auto-resolves)
    store.js            caches + reconstructs the multi-detector picture
    format.js           detector taxonomy (families A–F), number/metric math
    charts.js           hand-rolled SVG/CSS charts (no chart lib)
    components.js        DOM helpers, toast, CSV/PNG export
    live.js             live eval channel: SSE → polling fallback
    router.js, i18n.js   hash router, PL/EN
    views/              lab, threshold, diversity, files, matrix, evaluate,
                        detectors, datasets, system
```

## Views

- **Lab** (landing) - per-dataset detector leaderboard (striped F1 bars),
  best-per-metric chips. Reconstructs the multi-detector ranking from the
  single-detector evaluations the gateway stores.
- **Threshold** - `min_fall_frames` slider; F1(threshold) curves, live re-ranking
  and a `fall_frames` histogram, all recomputed client-side (H4).
- **Diversity** - Cohen's κ matrix on error vectors, recall–FPR scatter (H3),
  double-fault ensemble-candidate explorer (Badanie B).
- **Clips** - agreement strip (hardest clips first) + filterable per-clip table,
  merged CSV export.
- **Matrix** - detector × dataset F1 with rank badges.
- **Evaluate** - launch a run and watch it live; history.
- **Detectors / Datasets** - catalogue, grouped by family.
- **System drawer** (bottom bar) - container start/stop/build, health (infra,
  demoted out of the way).

## Run locally (no Docker)

```bash
cd frontend/web
python -m http.server 8099
# open http://127.0.0.1:8099/?api=http://localhost:3000
```

The `?api=` value may be the gateway root (`http://localhost:3000`) or a full API
base (`.../api/v1`) - it's normalized and remembered in `localStorage`. The
gateway has CORS enabled, so cross-origin dev works.

## Deploy (does NOT restart the gateway)

The frontend is the only container rebuilt. Behind nginx the app uses a relative
`/api/v1` base, proxied to `gateway:5000`.

```bash
docker compose build frontend
docker compose up -d --no-deps frontend     # --no-deps => never touches gateway
# app on http://localhost:2999
```

## Live channel (SSE)

Live evaluation progress streams over SSE (`/api/v1/evaluate/<id>/stream`, plus a
per-detector `/api/v1/evaluate/<id>/progress`). `live.js` prefers SSE and falls
back to `/status` polling automatically.

## Persistence (evals survive restarts)

The gateway persists every completed/imported evaluation to
`/shared/_evaluations/*.json` (bind-mounted to `fall-framework/shared/_evaluations/`)
and reloads them on startup. So restarting/recreating the gateway **no longer
wipes the eval stats** - they come back from disk.

To seed a fresh machine with existing results, copy that folder over before
starting (or run `magisterka/badania/skrypty/wczytaj_wyniki_do_gatewaya.py`
against a writable instance).

## Preview / read-only mode (public VPS hosting)

Set **`FALLFW_PREVIEW=1`** on the gateway to host the whole app publicly while
blocking anything that runs detectors or mutates state - detection, evaluation,
per-clip **rerun**, builds, downloads, container start/stop, dataset upload.
Browsing and all results/analysis stay fully live; the UI shows a `preview ·
read-only` badge and hides the disabled controls (it auto-detects via
`/api/v1/config`). No rebuild needed to flip it.

```bash
# enable (read-only):
FALLFW_PREVIEW=1 docker compose up -d gateway
# disable (full functionality):
FALLFW_PREVIEW=0 docker compose up -d gateway
```

Typical VPS deploy: copy `shared/_evaluations/` (your results) to the box, then
`FALLFW_PREVIEW=1 docker compose up -d gateway frontend` - no detector containers
needed, so the VPS isn't hammered with builds or CPU inference.
