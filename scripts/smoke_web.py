"""Exercise a launch instance; use only a public example, never print edit tokens."""
import argparse
import json
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import xml.etree.ElementTree as ET

BASE = "http://127.0.0.1:8765"


def call(path, payload=None, method=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Edit-Token"] = token
    request = Request(BASE + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method=method)
    with urlopen(request, timeout=10) as response:
        return response.read()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=BASE)
    args = parser.parse_args()
    BASE = args.base_url.rstrip("/")
    health = json.loads(call("/healthz"))
    assert health["version"] == "0.12.0"
    start = time.monotonic()
    job = json.loads(call("/api/jobs", {"repo_url": "https://github.com/mher/flower"}))
    path = f"/api/diagrams/{job['id']}"
    while time.monotonic() - start < 90:
        state = json.loads(call(f"/api/jobs/{job['id']}"))
        if state["status"] == "failed":
            raise RuntimeError(state["error"])
        if state["status"] == "complete":
            break
        time.sleep(0.5)
    else:
        raise TimeoutError("Generation did not complete within 90 seconds")
    xml = call(path + "/download").decode()
    assert ET.fromstring(xml).tag == "mxfile"
    edited = xml + "\n"
    assert json.loads(call(path, {"xml": edited}, method="PUT", token=job["edit_token"]))["status"] == "saved"
    assert call(path + "/download").decode() == edited
    try:
        call(path, {"xml": xml}, method="PUT")
    except HTTPError as exc:
        assert exc.code == 403
    else:
        raise AssertionError("Unauthenticated write succeeded")
    assert b"svg" in call(path + "/preview.svg")
    print(json.dumps({"status": "passed", "version": health["version"], "repository": "mher/flower", "seconds": round(time.monotonic()-start, 2), "checks": ["generate", "poll", "download mxfile", "authorized save", "saved download", "reject unauthorized save", "SVG preview"]}))
