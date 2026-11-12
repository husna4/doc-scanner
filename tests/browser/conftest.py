import socket
import threading
import time

import pytest
import uvicorn

from scanner.api import create_app
from scanner.config import Settings
from tests.test_i18n import STATIC


@pytest.fixture(scope="session")
def live_server(request, tmp_path_factory):
    if not request.config.getoption("--editor"):
        pytest.skip("Use --editor and install the browser dependency group plus Chromium")
    directory = tmp_path_factory.mktemp("browser")
    app = create_app(Settings(), directory / "uploads")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started, "Local browser test server did not start"
            yield f"http://127.0.0.1:{sock.getsockname()[1]}", directory
        finally:
            server.should_exit = True
            thread.join(timeout=10)


@pytest.fixture(scope="module")
def chromium(live_server):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def editor(chromium, live_server):
    contexts, external, errors = [], [], []

    def create(locale="es-ES", script=None, viewport=None, setup=None):
        context = chromium.new_context(
            locale=locale, viewport=viewport or {"width": 1440, "height": 1000}, accept_downloads=True
        )
        contexts.append(context)
        if script:
            context.add_init_script(script)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: (
                external.append(request.url)
                if not request.url.startswith((live_server[0], "blob:", "data:"))
                else None
            ),
        )
        # A test-only observer reads the actual editor state without adding a production test API.
        source = (STATIC / "app.js").read_text(encoding="utf-8")
        source += (
            "\nwindow.editorState = () => ({pages, activeId, view, limits, connection, notice, busy, drag});"
        )
        page.route(
            "**/static/app.js", lambda route: route.fulfill(body=source, content_type="text/javascript")
        )
        if setup:
            setup(page)
        page.goto(live_server[0])
        page.wait_for_function(
            "window.editorState && !document.querySelector('#connection-status').textContent.includes('…')"
        )
        return page

    yield create
    for context in contexts:
        context.close()
    assert not external, external
    assert not errors, errors
