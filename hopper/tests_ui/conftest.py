"""Browser smoke tests: the real page in Chromium against a live, offline Hopper server.

    pip install -r requirements-ui.txt && python -m playwright install chromium
    HOPPER_OFFLINE=1 python -m pytest tests_ui            # add --browser-channel chrome to use local Chrome
"""
import os
import tempfile
import threading

import pytest

os.environ.setdefault("HOPPER_OFFLINE", "1")                       # fixture data, no live feeds, no Claude
os.environ["HOPPER_DATA_DIR"] = tempfile.mkdtemp(prefix="hopper-ui-")  # never touch the real accounts DB

from werkzeug.serving import make_server  # noqa: E402

from app import guard  # noqa: E402
from app.server import app  # noqa: E402

# Page-load tripwires: CSP violations and uncaught errors are collected for every test.
WATCH = """
window.__csp = []; window.__errors = [];
document.addEventListener("securitypolicyviolation", e => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
window.addEventListener("error", e => window.__errors.push(String(e.message)));
window.addEventListener("unhandledrejection", e => window.__errors.push(String(e.reason)));
"""


@pytest.fixture(scope="session")
def base_url():
    server = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(autouse=True)
def _watch(page):
    guard.reset()                    # one browser making many requests isn't an abusive visitor
    page.add_init_script(WATCH)
    yield
    assert page.evaluate("window.__csp || []") == [], "Content-Security-Policy violations"
    assert page.evaluate("window.__errors || []") == [], "uncaught JavaScript errors"
