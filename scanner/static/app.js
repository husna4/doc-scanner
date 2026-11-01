"use strict";
const $ = id => document.getElementById(id);
const pages = [];
let activeId = null, busy = false, view = "result", drag = null, nextPageId = 0, limits = {pages: 20, file_bytes: 20 * 1048576};
const names = ["Superior izquierda", "Superior derecha", "Inferior derecha", "Inferior izquierda"];
const fullCorners = () => [[0, 0], [1, 0], [1, 1], [0, 1]];
const current = () => pages.find(p => p.id === activeId);
const copyCorners = corners => corners.map(p => [...p]);
const help = {original: "Conserva el color, sin mejora de iluminación.", grayscale: "Una escala de grises suave, con todos sus matices.", bw: "Umbral adaptativo para texto en blanco y negro.", enhanced: "Reduce sombras y equilibra el contraste."};

function message(text, error = false) {
  $("message").textContent = text;
  $("message").className = error ? "error" : "";
  $("message").hidden = !text;
}
async function run(label, work) {
  if (busy) return;
  busy = true; document.body.classList.add("busy"); $("file-input").disabled = true;
  $("busy-text").textContent = label; $("busy-indicator").hidden = false; message(""); render();
  try { await work(); } catch (error) { message(error.message || "No se pudo completar la operación.", true); }
  finally { busy = false; document.body.classList.remove("busy"); $("file-input").disabled = false; $("busy-indicator").hidden = true; render(); }
}
async function request(path, form) {
  let response;
  try { response = await fetch(path, {method: "POST", body: form, cache: "no-store"}); }
  catch { throw new Error("No se puede conectar con el escáner. Comprueba que sigue arrancado."); }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message || `Error del servicio (${response.status}).`);
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
  page.status = page.manual ? "Encuadre manual aplicado" : page.detected ? "Documento detectado y rectificado" : "Sin detección: imagen completa, sin filtro";
}
async function addFiles(files) {
  const selected = Array.from(files);
  if (!selected.length) return;
  if (pages.length + selected.length > limits.pages) { message(`El documento admite hasta ${limits.pages} páginas.`, true); return; }
  if (selected.some(file => file.size > limits.file_bytes)) { message("Alguna foto supera el tamaño máximo permitido.", true); return; }
  await run("Preparando tus páginas…", async () => {
    const errors = [];
    for (const file of selected) {
      // IDs de interfaz, también disponibles por HTTP en la LAN (sin contexto seguro).
      const page = {id: `page-${++nextPageId}`, file, filter: "enhanced", rotation: 0, manual: false, dirty: false};
      try {
        $("busy-text").textContent = `Preparando página ${pages.length + 1}…`;
        const detection = await (await request("/api/detect", fileForm(file))).json();
        Object.assign(page, {width: detection.width, height: detection.height, detected: detection.detected, corners: copyCorners(detection.corners)});
        // La previsualización orientada también funciona con HEIC en navegadores sin ese codec.
        const previewForm = fileForm(file); previewForm.append("filter", "original"); previewForm.append("auto_crop", "false");
        replaceBlob(page, "original", await (await request("/api/scan", previewForm)).blob());
        await process(page); pages.push(page); activeId = page.id; view = "result"; render();
      } catch (error) {
        for (const key of ["originalUrl", "resultUrl"]) if (page[key]) URL.revokeObjectURL(page[key]);
        errors.push(`${file.name}: ${error.message}`);
      }
    }
    if (errors.length) message(errors.join(" · "), true);
    else if (pages.some(p => !p.detected && !p.manual)) message("No se ha detectado el documento en alguna foto. Abre Encuadre, ajusta las cuatro esquinas y aplica los cambios.");
  });
}
function renderPages() {
  $("pages").replaceChildren();
  pages.forEach((page, index) => {
    const item = document.createElement("li"); item.className = "page-card" + (page.id === activeId ? " active" : "");
    const select = document.createElement("button"); select.className = "page-select"; select.disabled = busy;
    select.setAttribute("aria-label", `Seleccionar página ${index + 1}: ${page.file.name}`);
    const thumb = document.createElement("img"); thumb.src = page.resultUrl; thumb.alt = "";
    const name = document.createElement("span"); name.className = "page-name"; name.textContent = page.file.name + (page.dirty ? " •" : "");
    select.append(thumb, name); select.onclick = () => { activeId = page.id; render(); };
    const actions = document.createElement("div"); actions.className = "page-actions";
    const number = document.createElement("span"); number.className = "page-number"; number.textContent = String(index + 1).padStart(2, "0"); actions.append(number);
    for (const [text, label, delta] of [["↑", "Mover antes", -1], ["↓", "Mover después", 1], ["×", "Eliminar página", 0]]) {
      const button = document.createElement("button"); button.textContent = text; button.title = label; button.setAttribute("aria-label", `${label} ${index + 1}`);
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
  renderPages(); const page = current();
  $("empty-state").hidden = !!page; $("image-stage").hidden = !page;
  $("page-tools").disabled = busy || !page;
  $("result-tab").disabled = $("crop-tab").disabled = busy || !page;
  const pending = pages.some(p => p.dirty);
  $("export-pdf").disabled = $("export-image").disabled = busy || !pages.length || pending;
  $("long-width").disabled = busy || !pages.length;
  if (!page) { $("preview").removeAttribute("src"); $("dimensions").textContent = "VISTA PREVIA"; $("scan-status").textContent = "Listo para escanear"; $("page-position").textContent = ""; return; }
  $("filter").value = page.filter; $("filter-help").textContent = help[page.filter];
  $("rotation-value").textContent = `${page.rotation}°`;
  $("result-tab").classList.toggle("selected", view === "result"); $("crop-tab").classList.toggle("selected", view === "crop");
  $("corner-overlay").hidden = view !== "crop"; $("image-stage").classList.toggle("crop-view", view === "crop");
  const src = view === "crop" ? page.originalUrl : page.resultUrl;
  if ($("preview").getAttribute("src") !== src) $("preview").src = src;
  $("dimensions").textContent = `${page.width} × ${page.height} px · ORIGINAL`;
  $("scan-status").textContent = page.dirty ? "Ajustes pendientes · pulsa Aplicar ajustes" : page.status;
  $("dirty-note").hidden = !page.dirty;
  $("download-jpg").disabled = $("download-pdf").disabled = busy || page.dirty;
  $("page-position").textContent = `${pages.indexOf(page) + 1} / ${pages.length}`;
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
    const label = document.createElement("label"); label.className = "coordinate-pair"; label.textContent = names[index];
    const inputs = document.createElement("div");
    pair.forEach((value, axis) => {
      const input = document.createElement("input"); input.type = "number"; input.min = 0; input.max = 100; input.step = 0.1; input.value = (value * 100).toFixed(1);
      input.setAttribute("aria-label", `${names[index]} ${axis === 0 ? "X" : "Y"} en porcentaje`);
      input.oninput = () => {
        if (!input.value || !Number.isFinite(Number(input.value))) return;
        page.corners[index][axis] = Math.max(0, Math.min(100, Number(input.value))) / 100;
        markDirty(page); page.manual = true; view = "crop";
        // Mantener el campo enfocado: reconstruirlo aquí perdería la edición al cambiar el foco.
        $("preview").src = page.originalUrl; $("corner-overlay").hidden = false;
        $("image-stage").classList.add("crop-view");
        $("crop-tab").classList.add("selected"); $("result-tab").classList.remove("selected");
        $("crop-polygon").setAttribute("points", page.corners.map(p => p.map(v => v * 1000).join(",")).join(" "));
        $("handles").querySelectorAll(`[data-index="${index}"]`).forEach(handle => {
          handle.setAttribute("cx", page.corners[index][0] * 1000);
          handle.setAttribute("cy", page.corners[index][1] * 1000);
        });
        $("scan-status").textContent = "Ajustes pendientes · pulsa Aplicar ajustes";
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
  drag = Number(event.target.dataset.index); $("corner-overlay").setPointerCapture(event.pointerId); event.preventDefault();
});
$("corner-overlay").addEventListener("pointermove", event => {
  if (drag === null || busy) return;
  const rect = $("corner-overlay").getBoundingClientRect(), page = current();
  page.corners[drag] = [Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))];
  page.manual = true; markDirty(page); drawCorners(); $("scan-status").textContent = "Ajustes pendientes · pulsa Aplicar ajustes";
  $("dirty-note").hidden = false; $("download-jpg").disabled = $("download-pdf").disabled = $("export-pdf").disabled = $("export-image").disabled = true;
});
for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) $("corner-overlay").addEventListener(event, () => { drag = null; });
$("crop-tab").onclick = () => { view = "crop"; render(); }; $("result-tab").onclick = () => { view = "result"; render(); };
$("filter").onchange = () => { const page = current(); page.filter = $("filter").value; markDirty(page); render(); };
$("rotate").onclick = () => { const page = current(); page.rotation = (page.rotation + 90) % 360; markDirty(page); render(); };
$("full-frame").onclick = () => { const page = current(); page.corners = fullCorners(); page.manual = true; markDirty(page); view = "crop"; render(); };
$("apply").onclick = () => run("Aplicando ajustes…", async () => { const page = current(); page.manual = true; await process(page); view = "result"; });
function download(blob, filename) { const url = URL.createObjectURL(blob), anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000); }
$("download-jpg").onclick = () => download(current().result, "pagina.jpg");
async function exportPages(list, type) {
  if (list.some(page => page.dirty)) throw new Error("Aplica primero los ajustes pendientes de todas las páginas.");
  const form = new FormData(); list.forEach((page, index) => form.append("files", page.result, `pagina-${index + 1}.jpg`));
  if (type === "image") form.append("width", $("long-width").value);
  const response = await request(`/api/export/${type}`, form);
  download(await response.blob(), type === "pdf" ? "documento.pdf" : "documento-largo.jpg");
}
$("download-pdf").onclick = () => run("Preparando PDF…", () => exportPages([current()], "pdf"));
$("export-pdf").onclick = () => run("Reuniendo páginas…", () => exportPages(pages, "pdf"));
$("export-image").onclick = () => run("Creando imagen larga…", () => exportPages(pages, "image"));
$("file-input").onchange = async event => { await addFiles(event.target.files); event.target.value = ""; };
const zone = $("drop-zone");
for (const event of ["dragenter", "dragover"]) zone.addEventListener(event, e => { e.preventDefault(); if (!busy) zone.classList.add("dragging"); });
zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
zone.addEventListener("drop", event => { event.preventDefault(); zone.classList.remove("dragging"); if (!busy) addFiles(event.dataTransfer.files); });
window.addEventListener("beforeunload", event => { if (pages.length) { event.preventDefault(); event.returnValue = ""; } });
async function init() {
  try { const response = await fetch("/health", {cache: "no-store"}); if (!response.ok) throw new Error(); const health = await response.json(); limits = health.limits; $("file-limit").textContent = `Hasta ${Math.round(limits.file_bytes / 1048576)} MiB por foto · ${limits.pages} páginas`; $("connection-status").textContent = `Servicio local · v${health.version}`; }
  catch { $("connection-status").textContent = "Servicio no disponible"; message("No se ha podido conectar con el servicio.", true); }
  render();
}
init();
