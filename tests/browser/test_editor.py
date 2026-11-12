import json

import pytest
from PIL import Image
from pypdf import PdfReader

from tests.conftest import FIXTURES
from tests.test_i18n import CATALOGS


def wait_idle(page):
    page.wait_for_function("window.editorState && !window.editorState().busy")
    assert page.locator("#language").is_enabled()


def upload(page, files=None):
    page.locator("#file-input").set_input_files(files or [FIXTURES / "inclinado.jpg"])
    wait_idle(page)


def select_language(page, code):
    page.locator("#language").select_option(code)
    assert page.locator("html").get_attribute("lang") == code
    assert page.title() == CATALOGS[code]["app.title"]


@pytest.mark.parametrize(
    "locale,saved,languages,fallback,expected",
    [
        ("es-MX", None, ["es-MX"], "es-MX", "es"),
        ("en-GB", None, ["en-GB"], "en-GB", "en"),
        ("es-ES", "en", ["es-ES"], "es-ES", "en"),
        ("en-US", "es", ["en-US"], "en-US", "es"),
        ("en-US", "es-MX", ["fr", "es-MX", "en-US"], "en-US", "es"),
        ("en-US", "invalid", ["fr", "en-US", "es-ES"], "es-ES", "en"),
        ("en-US", None, [], "es-ES", "es"),
        ("en-US", None, ["fr", "de"], "de", "en"),
    ],
)
def test_language_resolution(editor, locale, saved, languages, fallback, expected):
    script = f"""
      Object.defineProperty(navigator, 'languages', {{get: () => {json.dumps(languages)}}});
      Object.defineProperty(navigator, 'language', {{get: () => {json.dumps(fallback)}}});
      localStorage.clear();
      if ({json.dumps(saved)} !== null) localStorage.setItem('docscanner.language', {json.dumps(saved)});
    """
    page = editor(locale=locale, script=script)
    assert page.locator("html").get_attribute("lang") == expected
    assert page.locator("#language").input_value() == expected


def test_storage_blocked_and_session_memory(editor):
    page = editor(
        script="""
      Object.defineProperty(window, 'localStorage', {
        get() {throw new DOMException('blocked', 'SecurityError');}
      });
    """
    )
    select_language(page, "en")
    upload(page)
    assert page.locator("html").get_attribute("lang") == "en"
    assert page.locator("#scan-status").inner_text() == CATALOGS["en"]["status.detected"]


def test_write_failure_and_english_fallback(editor):
    def setup(page):
        def catalog(route):
            spanish = dict(CATALOGS["es"])
            del spanish["actions.apply"]
            route.fulfill(json=spanish)

        page.route("**/locales/es.json", catalog)

    page = editor(script="Storage.prototype.setItem = () => {throw new Error('blocked');};", setup=setup)
    assert page.locator("#apply").inner_text() == "Apply settings"
    select_language(page, "en")
    select_language(page, "es")
    assert page.locator("#apply").inner_text() == "Apply settings"


def test_language_change_preserves_complete_state_and_last_applied_status(editor):
    page = editor()
    upload(page, [FIXTURES / "inclinado.jpg", FIXTURES / "sin-documento.png"])
    select_language(page, "en")
    assert page.locator("#scan-status").inner_text() == CATALOGS["en"]["status.notDetected"]
    select_language(page, "es")
    page.locator(".page-select").first.click()
    page.locator("#crop-tab").click()
    page.locator("#filter").select_option("bw")
    page.locator("#rotate").click()
    page.locator("#coordinate-fields input").first.fill("24")
    page.locator("#long-width").select_option("1200")
    calls, navigations = [], []
    page.on("request", lambda request: calls.append(request.url) if "/api/" in request.url else None)
    page.on("framenavigated", lambda frame: navigations.append(frame.url))
    page.evaluate("""() => {
      const state = window.editorState();
      window.beforeLanguage = {
        json: JSON.stringify(state),
        pages: [...state.pages],
        files: state.pages.map(p => p.file),
        originals: state.pages.map(p => p.original),
        results: state.pages.map(p => p.result),
        preview: document.querySelector('#preview').src,
        width: document.querySelector('#long-width').value
      };
    }""")
    for code in ("en", "es", "en"):
        select_language(page, code)
        assert page.locator("#scan-status").inner_text() == CATALOGS[code]["status.pending"]
        assert page.locator("#message").inner_text() == CATALOGS[code]["notices.noDetection"]
        for control in ("#export-pdf", "#export-image", "#download-jpg", "#download-pdf"):
            assert page.locator(control).is_disabled()
        assert page.evaluate("""() => {
          const state = window.editorState(), before = window.beforeLanguage;
          return JSON.stringify(state) === before.json && state.pages.every((p, i) =>
            p === before.pages[i] && p.file === before.files[i] && p.original === before.originals[i]
            && p.result === before.results[i]) && document.querySelector('#preview').src === before.preview
            && document.querySelector('#long-width').value === before.width;
        }""")
    assert not calls and not navigations
    assert page.evaluate("window.editorState().pages[0].status.key") == "status.detected"
    page.locator("#apply").click()
    wait_idle(page)
    assert len(calls) == 1  # No duplicated event handlers after repeated language changes.
    assert page.locator("#export-pdf").is_enabled()
    assert page.locator("#scan-status").inner_text() == CATALOGS["en"]["status.manual"]


@pytest.mark.parametrize("code", ["es", "en"])
def test_all_editor_operations_and_exports(editor, code, tmp_path):
    page = editor(locale="en-US" if code == "en" else "es-ES")
    console = []
    page.on("console", lambda message: console.append(message.text) if message.type == "error" else None)
    upload(page, [FIXTURES / "inclinado.jpg", FIXTURES / "sombras.jpg"])
    assert page.locator(".page-card").count() == 2
    for mode in ("original", "grayscale", "bw", "enhanced"):
        page.locator("#filter").select_option(mode)
        page.locator("#apply").click()
        wait_idle(page)
        assert page.locator("#filter").input_value() == mode
        assert page.locator("#export-pdf").is_enabled()
    page.locator("#full-frame").click()
    page.locator("#coordinate-fields input").first.fill("2")
    page.locator("#coordinate-fields input").nth(6).fill("2")
    page.locator("#rotate").click()
    assert page.locator("#rotation-value").inner_text() == "90°"
    page.locator("#apply").click()
    wait_idle(page)
    original_width, original_height = page.evaluate(
        "[window.editorState().pages[1].width, window.editorState().pages[1].height]"
    )
    page.locator(".page-card").nth(1).locator(".page-actions button").nth(0).click()
    assert page.locator(".page-name").first.inner_text() == "sombras.jpg"
    assert page.locator(".page-card.active .page-name").inner_text() == "sombras.jpg"
    page_size = None
    for control, filename in (
        ("download-jpg", "pagina.jpg"),
        ("download-pdf", "documento.pdf"),
        ("export-pdf", "documento.pdf"),
        ("export-image", "documento-largo.jpg"),
    ):
        with page.expect_download() as download_info:
            page.locator(f"#{control}").click()
        wait_idle(page)
        download = download_info.value
        assert download.suggested_filename == filename
        target = tmp_path / f"{control}-{filename}"
        download.save_as(target)
        if filename.endswith("pdf"):
            pdf = PdfReader(target)
            assert len(pdf.pages) == (1 if control == "download-pdf" else 2)
            if control == "export-pdf":
                assert pdf.pages[0].images[0].image.size == page_size
                assert (pdf.pages[0].mediabox.width > pdf.pages[0].mediabox.height) == (
                    page_size[0] > page_size[1]
                )
        else:
            with Image.open(target) as image:
                assert image.format == "JPEG"
                if control == "download-jpg":
                    page_size = image.size
                    assert image.width == original_height and image.height < original_width
                else:
                    assert image.width == 1600 and image.height > 1600
    page.locator(".page-card").first.locator(".page-actions button").nth(2).click()
    assert page.locator(".page-name").inner_text() == "inclinado.jpg"
    page.locator(".page-actions button").nth(2).click()
    assert page.locator("#empty-state").is_visible()
    assert page.locator("#export-pdf").is_disabled()
    assert not console


def test_persistence_without_images(editor):
    page = editor()
    select_language(page, "en")
    upload(page)
    assert page.evaluate("({...localStorage})") == {"docscanner.language": "en"}
    assert page.evaluate("sessionStorage.length") == 0
    assert page.evaluate("indexedDB.databases()") == []
    page.on("dialog", lambda dialog: dialog.accept())
    page.reload()
    page.wait_for_function("window.editorState && !window.editorState().busy")
    assert page.locator("html").get_attribute("lang") == "en"
    assert page.locator(".page-card").count() == 0
    assert page.evaluate("window.editorState().pages.length") == 0


@pytest.mark.parametrize("failure", ["known", "unknown", "unexpected", "network"])
def test_busy_lock_errors_and_visible_notice_translation(editor, failure):
    page = editor()
    upload(page)
    page.locator("#rotate").click()
    held = []
    page.route("**/api/scan", lambda route: held.append(route))
    page.locator("#apply").click()
    page.wait_for_function("window.editorState().busy")
    assert page.locator("#language").is_disabled()
    assert page.locator("#busy-text").inner_text() == CATALOGS["es"]["busy.applying"]
    assert held
    if failure == "network":
        held[0].abort()
        expected = "errors.network"
    elif failure == "unexpected":
        held[0].fulfill(status=502, body="<html>private traceback</html>")
        expected = "errors.generic"
    else:
        key = "errors.longImage" if failure == "known" else "private.unknown"
        held[0].fulfill(
            status=413,
            json={"error": {"code": "limit_exceeded", "message": "private traceback", "message_key": key}},
        )
        expected = key if failure == "known" else "errors.generic"
    wait_idle(page)
    assert page.locator("#message").inner_text() == CATALOGS["es"][expected]
    select_language(page, "en")
    assert page.locator("#message").inner_text() == CATALOGS["en"][expected]
    assert page.locator("#export-pdf").is_disabled()


def test_batch_errors_keep_safe_structured_data(editor):
    page = editor()
    upload(
        page,
        [
            {"name": "<img onerror=alert(1)>.jpg", "mimeType": "image/jpeg", "buffer": b"bad"},
            {"name": "empty.jpg", "mimeType": "image/jpeg", "buffer": b""},
            {
                "name": "inclinado.jpg",
                "mimeType": "image/jpeg",
                "buffer": (FIXTURES / "inclinado.jpg").read_bytes(),
            },
        ],
    )
    assert page.locator(".page-card").count() == 1
    assert page.evaluate("window.editorState().notice.errors.length") == 2
    assert page.locator("#message img").count() == 0
    assert "El contenido no es una imagen compatible." in page.locator("#message").inner_text()
    select_language(page, "en")
    text = page.locator("#message").inner_text()
    assert "<img onerror=alert(1)>.jpg" in text
    assert "The content is not a supported image." in text
    assert "Empty files are not accepted." in text


@pytest.mark.parametrize("end", ["pointerup", "pointercancel", "lostpointercapture"])
def test_drag_language_lock_and_release(editor, end):
    page = editor()
    upload(page)
    page.locator("#crop-tab").click()
    corner = page.locator(".corner-handle").first
    corner.scroll_into_view_if_needed()
    box = corner.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    assert page.locator("#language").is_disabled()
    page.mouse.move(box["x"] + 5, box["y"] + 5)
    if end == "pointerup":
        page.mouse.up()
    else:
        page.locator("#corner-overlay").dispatch_event(end)
        page.mouse.up()
    assert page.locator("#language").is_enabled()
    assert page.locator("#export-pdf").is_disabled()


@pytest.mark.parametrize("code", ["es", "en"])
@pytest.mark.parametrize("width", [1440, 375])
def test_layout_and_visual_review_artifacts(editor, live_server, code, width):
    page = editor(locale="en-US" if code == "en" else "es-ES", viewport={"width": width, "height": 1000})
    upload(page)
    page.locator("#crop-tab").click()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    for selector in (".topbar", "#language", "#apply", "#coordinate-fields"):
        element = page.locator(selector)
        assert element.is_visible()
        box = element.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1
    page.screenshot(path=str(live_server[1] / f"editor-{code}-{width}.png"), full_page=True)


def test_health_state_and_limit_notice_translate_without_refetch(editor):
    def setup(page):
        page.route(
            "**/health",
            lambda route: route.fulfill(
                json={"version": "test", "limits": {"pages": 1, "file_bytes": 123 * 1048576}}
            ),
        )

    page = editor(setup=setup)
    upload(page, [FIXTURES / "inclinado.jpg", FIXTURES / "sombras.jpg"])
    assert page.locator("#message").inner_text() == CATALOGS["es"]["notices.pagesLimit"].format(count=1)
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    select_language(page, "en")
    assert page.locator("#file-limit").inner_text() == "Up to 123 MiB per photo · 1 pages"
    assert page.locator("#connection-status").inner_text() == "Local service · vtest"
    assert page.locator("#message").inner_text() == CATALOGS["en"]["notices.pagesLimit"].format(count=1)
    assert not requests


def test_connection_failure_notice_translates(editor):
    def setup(page):
        page.route("**/health", lambda route: route.abort())

    page = editor(setup=setup)
    select_language(page, "en")
    assert page.locator("#connection-status").inner_text() == CATALOGS["en"]["connection.unavailable"]
    assert page.locator("#message").inner_text() == CATALOGS["en"]["errors.network"]


@pytest.mark.parametrize(
    "action,path",
    [
        ("upload", "detect"),
        ("download-pdf", "export/pdf"),
        ("export-pdf", "export/pdf"),
        ("export-image", "export/image"),
    ],
)
def test_operation_locks_restore_after_errors(editor, action, path):
    page = editor(locale="en-US")
    if action != "upload":
        upload(page)
    held = []
    page.route(f"**/api/{path}", lambda route: held.append(route))
    if action == "upload":
        page.locator("#file-input").set_input_files(FIXTURES / "inclinado.jpg")
    else:
        page.locator(f"#{action}").click()
    page.wait_for_function("window.editorState().busy")
    assert page.locator("#language").is_disabled()
    assert held
    held[0].fulfill(
        status=503, json={"error": {"code": "busy", "message": "legacy", "message_key": "errors.busy"}}
    )
    wait_idle(page)
    assert CATALOGS["en"]["errors.busy"] in page.locator("#message").inner_text()
    select_language(page, "es")
    assert CATALOGS["es"]["errors.busy"] in page.locator("#message").inner_text()
