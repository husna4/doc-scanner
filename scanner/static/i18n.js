// Local catalogs are loaded before the editor installs handlers or renders state.
const catalogs = {};
const storageKey = "docscanner.language";
let language = "en";
const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

export function resolveLanguage(saved, languages = [], fallback = "") {
  if (saved === "es" || saved === "en") return saved;
  for (const candidate of [...(Array.isArray(languages) ? languages : []), fallback]) {
    if (typeof candidate !== "string") continue;
    const base = candidate.toLowerCase().split("-")[0];
    if (base === "es" || base === "en") return base;
  }
  return "en";
}

export async function initializeLanguage() {
  await Promise.all(["es", "en"].map(async code => {
    const response = await fetch(`/static/locales/${code}.json`, {cache: "no-store"});
    if (!response.ok) throw new Error("Unable to load local translations");
    catalogs[code] = await response.json();
  }));
  let saved;
  try { saved = localStorage.getItem(storageKey); } catch { /* Storage may be blocked. */ }
  language = resolveLanguage(saved, navigator.languages, navigator.language);
  applyTranslations();
}

export const getLanguage = () => language;
export const hasTranslation = key => own(catalogs.en, key);

export function t(key, params = {}) {
  const template = own(catalogs[language], key) ? catalogs[language][key] : catalogs.en[key];
  if (typeof template !== "string") return key;
  return template.replace(/\{([a-zA-Z][a-zA-Z0-9_]*)\}/g, (match, name) =>
    own(params, name) ? String(params[name]) : match);
}

export function setLanguage(code) {
  if (code !== "es" && code !== "en") return;
  language = code;
  try { localStorage.setItem(storageKey, code); } catch { /* Keep the session choice in memory. */ }
  applyTranslations();
}

export function applyTranslations(root = document) {
  // data-i18n belongs on text leaves, never on a container with controls or icons.
  root.querySelectorAll("[data-i18n]").forEach(node => {
    node.textContent = t(node.dataset.i18n);
  });
  for (const attribute of ["title", "alt", "aria-label"]) {
    root.querySelectorAll(`[data-i18n-${attribute}]`).forEach(node => {
      node.setAttribute(attribute, t(node.getAttribute(`data-i18n-${attribute}`)));
    });
  }
  document.documentElement.lang = language;
  document.title = t("app.title");
}
