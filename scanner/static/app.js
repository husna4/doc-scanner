"use strict";
import {initializeLanguage, t, setLanguage, getLanguage, hasTranslation} from "./i18n.js";
await initializeLanguage();
const $ = id => document.getElementById(id);
const pages = [];
let activeId = null, busy = false, view = "result", drag = null, nextPageId = 0, limits = {pages: 20, file_bytes: 20 * 1048576};
const names = ["corners.topLeft", "corners.topRight", "corners.bottomRight", "corners.bottomLeft"];
const fullCorners = () => [[0, 0], [1, 0], [1, 1], [0, 1]];
const current = () => pages.find(p => p.id === activeId);
const copyCorners = corners => corners.map(p => [...p]);
// Keep visible notices and health state as data so language changes only render text.
let notice = null, connection = {key: "connection.checking", params: {}};
class EditorError extends Error {
  constructor(key, params = {}) { super(key); this.key = key; this.params = params; }
}
function errorData(error) {
  return error instanceof EditorError ? {key: error.key, params: error.params} : {key: "errors.generic", params: {}};
}
function serverError(error) {
  const key = error?.message_key;
  if (typeof key !== "string" || !key.startsWith("errors.") || !hasTranslation(key)) return new EditorError("errors.generic");
  // The only server parameters currently used are fixed multipart field identifiers.
  const params = {};
  if (["errors.missingFile", "errors.fileField"].includes(key)) {
    if (!["file", "files"].includes(error.params?.field)) return new EditorError("errors.generic");
    params.field = error.params.field;
  }
  return new EditorError(key, params);
}
function message(key, error = false, params = {}, errors = []) {
  notice = key ? {key, error, params, errors} : null;
  renderMessage();
}
function renderMessage() {
  const params = {...notice?.params};
  if (notice?.errors.length) {
    params.count = notice.errors.length;
    params.details = notice.errors.map(item => t("notices.batchItem", {
      filename: item.filename, reason: t(item.error.key, item.error.params)
    })).join(" · ");
  }
  $("message").textContent = notice ? t(notice.key, params) : "";
  $("message").className = notice?.error ? "error" : "";
  $("message").hidden = !notice;
}
function renderService() {
  $("file-limit").textContent = t("limits.files", {size: Math.round(limits.file_bytes / 1048576), count: limits.pages});
  $("connection-status").textContent = t(connection.key, connection.params);
}
function renderLanguageLock() { $("language").disabled = busy || drag !== null; }
async function run(label, work) {
  if (busy) return;
  busy = true; document.body.classList.add("busy"); $("file-input").disabled = true;
  $("busy-text").textContent = t(label); $("busy-indicator").hidden = false; message(""); render();
  try { await work(); } catch (error) { const data = errorData(error); message(data.key, true, data.params); }
  finally { busy = false; document.body.classList.remove("busy"); $("file-input").disabled = false; $("busy-indicator").hidden = true; render(); }
}
async function request(path, form) {
  let response;
  try { response = await fetch(path, {method: "POST", body: form, cache: "no-store"}); }
  catch { throw new EditorError("errors.network"); }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw serverError(body?.error);
  }
  return response;
}
function fileForm(file) { const form = new FormData(); form.append("file", file, file.name); return form; }
function replaceBlob(page, key, blob) {
  if (page[key + "Url"]) URL.revokeObjectURL(page[key + "Url"]);
  page[key] = blob; page[key + "Url"] = URL.createObjectURL(blob);
}
async function process(page) {
  const form = fileForm(page.file);
  form.append("filter", page.filter); form.append("rotation", page.rotation);
  if (page.manual || page.detected) form.append("corners", JSON.stringify(page.corners));
  const response = await request("/api/scan", form);
  replaceBlob(page, "result", await response.blob());
  page.dirty = false;
  page.status = {key: page.manual ? "status.manual" : page.detected ? "status.detected" : "status.notDetected", params: {}};
}
async function addFiles(files) {
  const selected = Array.from(files);
  if (!selected.length) return;
  if (pages.length + selected.length > limits.pages) { message("notices.pagesLimit", true, {count: limits.pages}); return; }
  if (selected.some(file => file.size > limits.file_bytes)) { message("notices.fileLimit", true); return; }
  await run("busy.preparing", async () => {
    const errors = [];
    for (const file of selected) {
      // IDs de interfaz, también disponibles por HTTP en la LAN (sin contexto seguro).
      const page = {id: `page-${++nextPageId}`, file, filter: "enhanced", rotation: 0, manual: false, dirty: false};
      try {
        $("busy-text").textContent = t("busy.page", {number: pages.length + 1});
        const detection = await (await request("/api/detect", fileForm(file))).json();
        Object.assign(page, {width: detection.width, height: detection.height, detected: detection.detected, corners: copyCorners(detection.corners)});
        // La previsualización orientada también funciona con HEIC en navegadores sin ese codec.
        const previewForm = fileForm(file); previewForm.append("filter", "original"); previewForm.append("auto_crop", "false");
        replaceBlob(page, "original", await (await request("/api/scan", previewForm)).blob());
        await process(page); pages.push(page); activeId = page.id; view = "result"; render();
      } catch (error) {
        for (const key of ["originalUrl", "resultUrl"]) if (page[key]) URL.revokeObjectURL(page[key]);
        errors.push({filename: file.name, error: errorData(error)});
      }
    }
    if (errors.length) message("notices.batch", true, {}, errors);
    else if (pages.some(p => !p.detected && !p.manual)) message("notices.noDetection");
  });
}
function renderPages() {
  $("pages").replaceChildren();
  pages.forEach((page, index) => {
    const item = document.createElement("li"); item.className = "page-card" + (page.id === activeId ? " active" : "");
    const select = document.createElement("button"); select.className = "page-select"; select.disabled = busy;
    select.setAttribute("aria-label", t("pages.select", {number: index + 1, filename: page.file.name}));
    const thumb = document.createElement("img"); thumb.src = page.resultUrl; thumb.alt = "";
    const name = document.createElement("span"); name.className = "page-name"; name.textContent = page.file.name + (page.dirty ? " •" : "");
    select.append(thumb, name); select.onclick = () => { activeId = page.id; render(); };
    const actions = document.createElement("div"); actions.className = "page-actions";
    const number = document.createElement("span"); number.className = "page-number"; number.textContent = String(index + 1).padStart(2, "0"); actions.append(number);
    for (const [text, label, delta] of [["↑", "actions.before", -1], ["↓", "actions.after", 1], ["×", "actions.remove", 0]]) {
      const button = document.createElement("button"); button.textContent = text; button.title = t(label, {number: index + 1}); button.setAttribute("aria-label", button.title);
      button.disabled = busy || (delta !== 0 && (index + delta < 0 || index + delta >= pages.length));
      button.onclick = () => {
        if (delta) [pages[index], pages[index + delta]] = [pages[index + delta], pages[index]];
        else { pages.splice(index, 1); URL.revokeObjectURL(page.originalUrl); URL.revokeObjectURL(page.resultUrl); if (activeId === page.id) activeId = pages[Math.min(index, pages.length - 1)]?.id || null; }
        render();
      }; actions.append(button);
    }
    item.append(select, actions); $("pages").append(item);
  });
  $("page-count").textContent = pages.length;
}
function render() {
  renderLanguageLock(); renderMessage(); renderService();
  renderPages(); const page = current();
  $("empty-state").hidden = !!page; $("image-stage").hidden = !page;
  $("page-tools").disabled = busy || !page;
  $("result-tab").disabled = $("crop-tab").disabled = busy || !page;
  const pending = pages.some(p => p.dirty);
  $("export-pdf").disabled = $("export-image").disabled = busy || !pages.length || pending;
  $("long-width").disabled = busy || !pages.length;
  $("filter-help").textContent = t(`help.${page?.filter || $("filter").value}`);
  if (!page) { $("preview").removeAttribute("src"); $("dimensions").textContent = t("view.preview"); $("scan-status").textContent = t("status.ready"); $("page-position").textContent = ""; $("coordinate-fields").replaceChildren(); return; }
  $("filter").value = page.filter;
  $("rotation-value").textContent = `${page.rotation}°`;
  $("result-tab").classList.toggle("selected", view === "result"); $("crop-tab").classList.toggle("selected", view === "crop");
  $("corner-overlay").toggleAttribute("hidden", view !== "crop"); $("image-stage").classList.toggle("crop-view", view === "crop");
  const src = view === "crop" ? page.originalUrl : page.resultUrl;
  if ($("preview").getAttribute("src") !== src) $("preview").src = src;
  $("dimensions").textContent = t("status.dimensions", {width: page.width, height: page.height});
  $("scan-status").textContent = page.dirty ? t("status.pending") : t(page.status.key, page.status.params);
  $("dirty-note").hidden = !page.dirty;
  $("download-jpg").disabled = $("download-pdf").disabled = busy || page.dirty;
  $("page-position").textContent = t("status.position", {position: pages.indexOf(page) + 1, count: pages.length});
  drawCorners();
}
function drawCorners() {
  const page = current(); if (!page) return;
  $("crop-polygon").setAttribute("points", page.corners.map(p => p.map(v => v * 1000).join(",")).join(" "));
  const svgNS = "http://www.w3.org/2000/svg";
  $("handles").replaceChildren(); $("coordinate-fields").replaceChildren();
  page.corners.forEach((pair, index) => {
    for (const hit of [true, false]) {
      const circle = document.createElementNS(svgNS, "circle");
      circle.setAttribute("cx", pair[0] * 1000); circle.setAttribute("cy", pair[1] * 1000); circle.setAttribute("r", hit ? 36 : 12);
      circle.classList.add(hit ? "corner-hit" : "corner-handle"); circle.dataset.index = index;
      $("handles").append(circle);
    }
    const label = document.createElement("label"); label.className = "coordinate-pair"; label.textContent = t(names[index]);
    const inputs = document.createElement("div");
    pair.forEach((value, axis) => {
      const input = document.createElement("input"); input.type = "number"; input.min = 0; input.max = 100; input.step = 0.1; input.value = (value * 100).toFixed(1);
      input.setAttribute("aria-label", t("corners.coordinate", {corner: t(names[index]), axis: axis === 0 ? "X" : "Y"}));
      input.oninput = () => {
        if (!input.value || !Number.isFinite(Number(input.value))) return;
        page.corners[index][axis] = Math.max(0, Math.min(100, Number(input.value))) / 100;
        markDirty(page); page.manual = true; view = "crop";
        // Mantener el campo enfocado: reconstruirlo aquí perdería la edición al cambiar el foco.
        $("preview").src = page.originalUrl; $("corner-overlay").removeAttribute("hidden");
        $("image-stage").classList.add("crop-view");
        $("crop-tab").classList.add("selected"); $("result-tab").classList.remove("selected");
        $("crop-polygon").setAttribute("points", page.corners.map(p => p.map(v => v * 1000).join(",")).join(" "));
        $("handles").querySelectorAll(`[data-index="${index}"]`).forEach(handle => {
          handle.setAttribute("cx", page.corners[index][0] * 1000);
          handle.setAttribute("cy", page.corners[index][1] * 1000);
        });
        $("scan-status").textContent = t("status.pending");
        $("dirty-note").hidden = false;
        $("download-jpg").disabled = $("download-pdf").disabled = $("export-pdf").disabled = $("export-image").disabled = true;
      };
      inputs.append(input);
    }); label.append(inputs); $("coordinate-fields").append(label);
  });
}
function markDirty(page) { page.dirty = true; }
$("corner-overlay").addEventListener("pointerdown", event => {
  if (busy || event.target.dataset.index === undefined) return;
  drag = Number(event.target.dataset.index); renderLanguageLock(); $("corner-overlay").setPointerCapture(event.pointerId); event.preventDefault();
});
$("corner-overlay").addEventListener("pointermove", event => {
  if (drag === null || busy) return;
  const rect = $("corner-overlay").getBoundingClientRect(), page = current();
  page.corners[drag] = [Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))];
  page.manual = true; markDirty(page); drawCorners(); $("scan-status").textContent = t("status.pending");
  $("dirty-note").hidden = false; $("download-jpg").disabled = $("download-pdf").disabled = $("export-pdf").disabled = $("export-image").disabled = true;
});
for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) $("corner-overlay").addEventListener(event, () => { drag = null; renderLanguageLock(); });
$("crop-tab").onclick = () => { view = "crop"; render(); }; $("result-tab").onclick = () => { view = "result"; render(); };
$("filter").onchange = () => { const page = current(); page.filter = $("filter").value; markDirty(page); render(); };
$("rotate").onclick = () => { const page = current(); page.rotation = (page.rotation + 90) % 360; markDirty(page); render(); };
$("full-frame").onclick = () => { const page = current(); page.corners = fullCorners(); page.manual = true; markDirty(page); view = "crop"; render(); };
$("apply").onclick = () => run("busy.applying", async () => { const page = current(); page.manual = true; await process(page); view = "result"; });
function download(blob, filename) { const url = URL.createObjectURL(blob), anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000); }
$("download-jpg").onclick = () => download(current().result, "pagina.jpg");
async function exportPages(list, type) {
  if (list.some(page => page.dirty)) throw new EditorError("errors.pending");
  const form = new FormData(); list.forEach((page, index) => form.append("files", page.result, `pagina-${index + 1}.jpg`));
  if (type === "image") form.append("width", $("long-width").value);
  const response = await request(`/api/export/${type}`, form);
  download(await response.blob(), type === "pdf" ? "documento.pdf" : "documento-largo.jpg");
}
$("download-pdf").onclick = () => run("busy.pdf", () => exportPages([current()], "pdf"));
$("export-pdf").onclick = () => run("busy.document", () => exportPages(pages, "pdf"));
$("export-image").onclick = () => run("busy.image", () => exportPages(pages, "image"));
$("file-input").onchange = async event => { await addFiles(event.target.files); event.target.value = ""; };
const zone = $("drop-zone");
for (const event of ["dragenter", "dragover"]) zone.addEventListener(event, e => { e.preventDefault(); if (!busy) zone.classList.add("dragging"); });
zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
zone.addEventListener("drop", event => { event.preventDefault(); zone.classList.remove("dragging"); if (!busy) addFiles(event.dataTransfer.files); });
window.addEventListener("beforeunload", event => { if (pages.length) { event.preventDefault(); event.returnValue = ""; } });
$("language").value = getLanguage();
$("language").onchange = () => {
  if (busy || drag !== null) { $("language").value = getLanguage(); return; }
  setLanguage($("language").value);
  render();
};
async function init() {
  render();
  try {
    const response = await fetch("/health", {cache: "no-store"});
    if (!response.ok) throw new Error();
    const health = await response.json();
    limits = health.limits;
    connection = {key: "connection.ready", params: {version: health.version}};
  } catch {
    connection = {key: "connection.unavailable", params: {}};
    message("errors.network", true);
  }
  render();
}
init();
