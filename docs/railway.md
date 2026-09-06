# Railway deployment

Deploy the public source repository with its Dockerfile. Attach a **fresh Railway
Volume at `/data`**: Dockerfile `VOLUME` declarations are not supported by Railway.
Do not copy private local jobs or the private repository's history into this service.

## Small public demo configuration

Use one replica in Singapore, with a 1 vCPU / 1 GB memory ceiling. These are maximum
resources, not a guaranteed monthly price. Set the deployment healthcheck to `/healthz`.

```dotenv
HOST=0.0.0.0
PORT=8000
REPO2DRAWIO_DATA_DIR=/data
REPO2DRAWIO_ALLOW_PRIVATE=false
REPO2DRAWIO_WORKERS=1
REPO2DRAWIO_MAX_PENDING=4
REPO2DRAWIO_MAX_JOBS=100
REPO2DRAWIO_RATE_LIMIT=3
```

Generate an HTTPS domain targeting port 8000. Keep the Railway management project
private; only the web service needs public networking. Do not expose a TCP proxy.
Leave serverless sleeping disabled for the initial generation and persistence checks.

Set a workspace Compute email alert at $5 and a hard limit at $10. The hard limit
applies to **all workloads in that workspace**, not only this demo. Railway Agent
usage is separate; this deployment does not use Railway Agent. Taxes and currency
conversion are outside the compute limit. A $5 monthly cost is a target, not a guarantee.

The application currently trusts only Uvicorn's default proxy addresses. Until the
provider's trusted forwarding configuration is verified, the three-per-minute quota
may be shared by visitors behind the provider proxy. Do not indiscriminately trust
client-supplied forwarding headers to work around the limit.

## Smoke check

```bash
python scripts/smoke_web.py --base-url https://YOUR-VERIFIED-DOMAIN
```

This creates one result from the public Flower repository, checks downloads, saves
an edit, and rejects an unauthorized save. Also check `/api/config` reports
`allow_private: false` and that instant examples open in the embedded editor.
Redeploy and re-read the saved result to verify the volume survives deployment.

At 100 stored jobs, generation admission stops without deleting any results.
Review storage and a user-visible retention policy before increasing that allowance.
