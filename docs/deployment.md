# Small public demo deployment

Use the existing Docker image on a host that supports a persistent filesystem.
This Python/thread-pool application is not a static site or a Cloudflare Worker.
Do not deploy team machines, existing private job data, or repository history as demo content.

Recommended launch settings:

```text
HOST=0.0.0.0
PORT=8000
REPO2DRAWIO_DATA_DIR=/data
REPO2DRAWIO_ALLOW_PRIVATE=false
REPO2DRAWIO_WORKERS=2
REPO2DRAWIO_MAX_PENDING=8
REPO2DRAWIO_MAX_JOBS=500
REPO2DRAWIO_RATE_LIMIT=3
```

Run **one process and one replica**; admission limits are in-process. Terminate HTTPS
at the hosting provider. Trust proxy headers only from the provider's actual proxy
addresses; never accept arbitrary forwarded IPs from the Internet. Without trusted
proxy configuration the per-client quota becomes a shared proxy quota (safe but restrictive).
Use provider edge rate limits for an Internet-facing deployment and set a spending cap.

Mount a fresh persistent volume at `/data`. Examples are bundled and do not consume
generation quota or need GitHub access. Jobs stop being admitted at the storage count
limit; the app never deletes existing results automatically. 500 jobs can require
several GB including edited files. Define retention and notify users before deletion.

Before announcing, verify HTTPS `/healthz`, all three `/examples/*` pages, generation
of a small public repo, local example edits/download, and a generated result's save.
Links to generated diagrams are bearer-style view links, not authenticated private
documents. Edit links additionally grant save access. The hosted public demo should
reject PATs; private-repository use stays with trusted self-hosting.

The editor runs at `embed.diagrams.net` in an iframe and receives diagram XML in the
browser. Logo assets and Google fonts also require network access. This is not a
fully offline editor. Provide downloads as the fallback when the embedded editor is blocked.

GitHub unauthenticated API limits can interrupt generation. This implementation does
not silently apply a server owner's personal token. Instant examples continue working.

## Measurement

Use hosting-provider analytics for visits and tagged campaign URLs (`utm_source=geeknews`,
`threads`, `reddit`, `velog`). Compare with GitHub repository traffic and daily stars.
Do not claim exact per-channel star attribution: GitHub does not expose that conversion.
Track generation successes/failures from job metadata locally; do not export repository
URLs, XML, PATs, or edit tokens to analytics. No analytics service is connected yet.
