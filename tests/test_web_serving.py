"""The server serves the built React UI (web_dist) with correct asset MIME types.

These guard the bundled web UI: that the pre-built single-page app is served at
``/``, and that its JavaScript bundle is served with a JS MIME type (a browser
refuses a ``type="module"`` script otherwise, and on Windows the registry often
maps ``.js`` to ``text/plain``).
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from jutul_agent.interfaces.server.app import WEB_DIST_DIR, _ui_dir, create_app


def test_built_app_is_present_and_served() -> None:
    assert (WEB_DIST_DIR / "index.html").is_file(), (
        "run `npm run build` in interfaces/server/webapp"
    )
    assert _ui_dir() == WEB_DIST_DIR


def test_serves_the_single_page_app() -> None:
    with TestClient(create_app(ui=True)) as client:
        body = client.get("/").text
        assert '<div id="root">' in body
        match = re.search(r'assets/index-[^"\']+\.js', body)
        assert match, "index.html should reference the hashed JS bundle"
        resp = client.get("/" + match.group(0))
        assert resp.status_code == 200
        # The module script must be served as JavaScript or the browser won't run it.
        assert resp.headers["content-type"].startswith("text/javascript")


def test_no_ui_mount_when_disabled() -> None:
    with TestClient(create_app(ui=False)) as client:
        # API routes still work; the SPA is just not mounted at "/".
        assert client.get("/models").status_code == 200
        assert client.get("/").status_code == 404
