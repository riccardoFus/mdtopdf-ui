/* ==========================================================================
   MD → PDF Studio — frontend application
   Local-only SPA: editor, live PDF preview, profiles, settings, export.
   ========================================================================== */

/* ------------------------------ PDF.js loader ---------------------------- */
let pdfjsLib = null;
try {
  pdfjsLib = await import('/static/vendor/pdfjs/pdf.min.mjs');
  pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/vendor/pdfjs/pdf.worker.min.mjs';
} catch (error) {
  console.warn('PDF.js non disponibile, uso il visualizzatore PDF del browser.', error);
}

/* ------------------------------ DOM helpers ------------------------------ */
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const dom = {
  tabs: $('#tabs'),
  editor: $('#editor'),
  editorScroll: $('#editorScroll'),
  editorGutter: $('#editorGutter'),
  lineNumbers: $('#lineNumbers'),
  highlight: $('#highlight'),
  editorStats: $('#editorStats'),
  docName: $('#docName'),
  docPath: $('#docPath'),
  dirtyDot: $('#dirtyDot'),
  saveState: $('#saveState'),
  workspace: $('#workspace'),
  splitter: $('#splitter'),

  previewPane: $('#previewPane'),
  previewScroll: $('#previewScroll'),
  previewPages: $('#previewPages'),
  previewEmpty: $('#previewEmpty'),
  previewStatus: $('#previewStatus'),
  previewEngine: $('#previewEngine'),
  previewWarnings: $('#previewWarnings'),
  btnWarnings: $('#btnWarnings'),
  pdfFallback: $('#pdfFallback'),
  pageNumber: $('#pageNumber'),
  pageTotal: $('#pageTotal'),
  zoomLabel: $('#zoomLabel'),
  btnFitWidth: $('#btnFitWidth'),

  settingsDrawer: $('#settingsDrawer'),
  drawerScrim: $('#drawerScrim'),
  profileSelect: $('#profileSelect'),
  themeSelect: $('#themeSelect'),
  customThemeName: $('#customThemeName'),
  engineStatus: $('#engineStatus'),
  outputDirHelp: $('#outputDirHelp'),
  factDraft: $('#factDraft'),
  factState: $('#factState'),
  factLog: $('#factLog'),

  btnExport: $('#btnExport'),
  btnSave: $('#btnSave'),
  btnOpen: $('#btnOpen'),
  btnNew: $('#btnNew'),
  btnBatch: $('#btnBatch'),
  btnLogs: $('#btnLogs'),
  btnSettings: $('#btnSettings'),

  fileInput: $('#fileInput'),
  imageInput: $('#imageInput'),
  coverLogoInput: $('#coverLogoInput'),
  profileImportInput: $('#profileImportInput'),

  toasts: $('#toasts'),
  dropOverlay: $('#dropOverlay'),
  promptDialog: $('#promptDialog'),
  promptTitle: $('#promptTitle'),
  promptMessage: $('#promptMessage'),
  promptLabel: $('#promptLabel'),
  promptInput: $('#promptInput'),
  promptConfirm: $('#promptConfirm'),
  confirmDialog: $('#confirmDialog'),
  confirmTitle: $('#confirmTitle'),
  confirmMessage: $('#confirmMessage'),
  confirmOk: $('#confirmOk'),
  batchDialog: $('#batchDialog'),
  logsDialog: $('#logsDialog'),
  shortcutsDialog: $('#shortcutsDialog'),
  batchFiles: $('#batchFiles'),
  batchList: $('#batchList'),
  batchResults: $('#batchResults'),
  btnRunBatch: $('#btnRunBatch'),
  logTable: $('#logTable tbody'),
  themeSelectWrap: $('#themeSelect'),
};

const WELCOME_MARKDOWN = `# Benvenuto in MD → PDF Studio

Un ambiente **locale** per trasformare Markdown in PDF, con anteprima fedele e controllo completo della formattazione.

## Come iniziare

1. Scrivi o incolla il tuo Markdown qui a sinistra.
2. Regola tipografia, margini e tema dal pannello **Impostazioni**.
3. Premi **Esporta PDF** (oppure \`Ctrl+E\`).

> L’anteprima a destra è generata dagli stessi byte del PDF finale: ciò che vedi è ciò che esporti.

## Elementi supportati

| Elemento | Stato | Note |
|:---------|:-----:|------|
| Titoli H1–H6 | ✓ | anchor e TOC automatici |
| Tabelle | ✓ | allineamento colonne |
| Checklist | ✓ | - [x] / - [ ] |
| Note a piè di pagina | ✓ | sintassi Markdown |
| Codice | ✓ | evidenziazione + numeri riga |

- [x] Editor con highlighting
- [x] Preview paginata e zoom
- [ ] Il tuo prossimo documento

~~~python
def convert(markdown: str) -> bytes:
    return render_pdf(markdown)

print("Pronto.")
~~~

## Diagrammi e formule

~~~mermaid
flowchart LR
  MD[Markdown] --> PDF[PDF]
  MD --> HTML[HTML]
  HTML --> PDF
~~~

Formula inline: $E = mc^2$. Formula in blocco:

$$
\frac{a}{b} = \sqrt{c}
$$

<!-- pagebreak -->

## Pagina successiva

Usa \`<!-- pagebreak -->\` oppure \`\\newpage\` per controllare le interruzioni di pagina.

Una nota a piè di pagina[^1] e un po’ di testo italiano con accenti: perché, è, à, ù, ò. Emoji: 🚀 ✨ 📄

[^1]: Le note sono generate automaticamente e collegate al testo.
`;

/* ------------------------------ Global state ----------------------------- */
const state = {
  config: null,
  settings: null,
  tabs: [],
  activeId: null,
  profiles: [],
  builtinProfiles: [],
  themes: {},
  customThemes: {},
  preview: {
    pdfDoc: null,
    lastPdf: null,
    total: 0,
    page: 1,
    zoom: 100,
    fit: true,
    requestId: 0,
    renderToken: 0,
    abort: null,
    renderTasks: [],
    fallbackUrl: null,
    lastError: '',
    lastErrorAt: 0,
  },
  lastPreviewSettings: null,
  lastPreviewMeta: null,
  uploadCounter: 0,
  ready: false,
  persistTimer: null,
  previewTimer: null,
  draftTimer: null,
  tabsTimer: null,
  resizeTimer: null,
  settingsOpen: false,
  lastHF: null,
  batch: [],
  lastExport: null,
};

window.__studio = {
  state,
  api: (...args) => api(...args),
  runPreview: (...args) => runPreview(...args),
  exportPdf: (...args) => exportPdf(...args),
  updateSetting: (path, value) => {
    setSetting(path, value);
    syncControlValues();
    schedulePreview(20);
    schedulePersistSettings();
  },
  version: '1.5.0',
  ready: false,
};

/* ------------------------------ Utilities -------------------------------- */
function deepClone(value) {
  if (typeof structuredClone === 'function') return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

function getPath(object, path) {
  return path.split('.').reduce((acc, key) => (acc == null ? undefined : acc[key]), object);
}

function setPath(object, path, value) {
  const parts = path.split('.');
  let cursor = object;
  for (let i = 0; i < parts.length - 1; i += 1) {
    if (typeof cursor[parts[i]] !== 'object' || cursor[parts[i]] === null) cursor[parts[i]] = {};
    cursor = cursor[parts[i]];
  }
  cursor[parts[parts.length - 1]] = value;
}

function setSetting(path, value) {
  setPath(state.settings, path, value);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function unescapeHtml(value) {
  const el = document.createElement('textarea');
  el.innerHTML = value;
  return el.value;
}

function stem(name) {
  return String(name || 'documento').replace(/\.(md|markdown|mdown|txt)$/i, '') || 'documento';
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function nowTime() {
  return new Date().toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
}

function debounce(fn, delay) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

function activeTab() {
  return state.tabs.find((tab) => tab.id === state.activeId) || null;
}

function outputName(tab = activeTab()) {
  const configured = String(state.settings?.document?.filename || '').trim();
  if (configured && configured !== 'documento') return configured.replace(/\.pdf$/i, '');
  return stem(tab?.name || 'documento');
}

async function api(path, options = {}) {
  const config = { ...options };
  config.headers = { ...(options.headers || {}) };
  if (options.body && typeof options.body !== 'string' && !(options.body instanceof FormData)) {
    config.body = JSON.stringify(options.body);
  }
  if (!(options.body instanceof FormData)) {
    config.headers['Content-Type'] = 'application/json';
  }
  const response = await fetch(path, config);
  const contentType = response.headers.get('content-type') || '';
  let payload = null;
  if (contentType.includes('application/json')) {
    payload = await response.json().catch(() => null);
  } else {
    payload = await response.text().catch(() => '');
  }
  if (!response.ok) {
    let detail = payload?.detail ?? payload;
    if (Array.isArray(detail)) {
      detail = detail.map((item) => item.msg || JSON.stringify(item)).join('; ');
    }
    if (detail && typeof detail === 'object') detail = JSON.stringify(detail);
    const error = new Error(detail || `Errore HTTP ${response.status}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

/* ------------------------------ Toasts ----------------------------------- */
function toast(type, title, message = '', options = {}) {
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  const icons = { info: 'i', success: '✓', warning: '!', error: '×' };
  node.innerHTML = `
    <span class="toast-icon">${escapeHtml(icons[type] || 'i')}</span>
    <div class="toast-body">
      <div class="toast-title">${escapeHtml(title)}</div>
      ${message ? `<div class="toast-msg">${escapeHtml(message)}</div>` : ''}
      <div class="toast-actions"></div>
    </div>
    <button class="toast-close" aria-label="Chiudi notifica">×</button>`;
  const actions = $('.toast-actions', node);
  (options.actions || []).forEach((action) => {
    if (action.href) {
      const link = document.createElement('a');
      link.href = action.href;
      link.textContent = action.label;
      if (action.download) link.download = action.download;
      if (action.blank) { link.target = '_blank'; link.rel = 'noopener'; }
      actions.appendChild(link);
    } else {
      const button = document.createElement('button');
      button.className = 'link-btn';
      button.textContent = action.label;
      button.addEventListener('click', () => { action.onClick?.(); node.remove(); });
      actions.appendChild(button);
    }
  });
  if (!(options.actions || []).length) actions.remove();
  const close = () => {
    node.classList.add('leaving');
    setTimeout(() => node.remove(), 190);
  };
  $('.toast-close', node).addEventListener('click', close);
  dom.toasts.appendChild(node);
  const timeout = options.timeout ?? (type === 'error' ? 9000 : 6000);
  if (timeout) setTimeout(close, timeout);
  while (dom.toasts.children.length > 6) dom.toasts.firstElementChild.remove();
  return node;
}

function toastError(error, title = 'Operazione non riuscita') {
  const message = error instanceof Error ? error.message : String(error);
  return toast('error', title, message);
}

/* ------------------------------ Dialogs ---------------------------------- */
function openPrompt({ title, message = '', label = 'Valore', value = '', placeholder = '', confirmText = 'Conferma' }) {
  return new Promise((resolve) => {
    dom.promptTitle.textContent = title;
    dom.promptMessage.textContent = message;
    dom.promptMessage.hidden = !message;
    dom.promptLabel.textContent = label;
    dom.promptInput.value = value;
    dom.promptInput.placeholder = placeholder;
    dom.promptConfirm.textContent = confirmText;
    dom.promptDialog.returnValue = '';
    const onKey = (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        dom.promptDialog.close('confirm');
      }
    };
    const onClose = () => {
      dom.promptInput.removeEventListener('keydown', onKey);
      resolve(dom.promptDialog.returnValue === 'confirm' ? dom.promptInput.value.trim() : null);
    };
    dom.promptInput.addEventListener('keydown', onKey);
    dom.promptDialog.addEventListener('close', onClose, { once: true });
    dom.promptDialog.showModal();
    setTimeout(() => { dom.promptInput.focus(); dom.promptInput.select(); }, 30);
  });
}

function openConfirm({ title = 'Confermi?', message = '', confirmText = 'Conferma', danger = true }) {
  return new Promise((resolve) => {
    dom.confirmTitle.textContent = title;
    dom.confirmMessage.textContent = message;
    dom.confirmOk.textContent = confirmText;
    dom.confirmOk.className = `btn ${danger ? 'danger' : 'primary'}`;
    dom.confirmDialog.returnValue = '';
    const onKey = (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        dom.confirmDialog.close('confirm');
      }
    };
    const onClose = () => {
      dom.confirmDialog.removeEventListener('keydown', onKey);
      resolve(dom.confirmDialog.returnValue === 'confirm');
    };
    dom.confirmDialog.addEventListener('keydown', onKey);
    dom.confirmDialog.addEventListener('close', onClose, { once: true });
    dom.confirmDialog.showModal();
  });
}

function closeDialog(id) {
  const dialog = document.getElementById(id);
  if (dialog?.open) dialog.close();
}

/* ------------------------------ Settings binding ------------------------- */
function refreshConditionalFields() {
  const pageSize = getPath(state.settings, 'layout.pageSize');
  $('#customSizeFields')?.classList.toggle('hidden', pageSize !== 'custom');
  const outputDir = getPath(state.settings, 'pdf.outputDir') || '';
  if (dom.outputDirHelp) {
    const target = outputDir || state.config?.outputDir || 'output/';
    dom.outputDirHelp.innerHTML = `Copia automatica e batch in: <code>${escapeHtml(target)}</code>. Il PDF principale usa il dialogo di sistema (o del browser come fallback).`;
  }
  const coverEnabled = getPath(state.settings, 'layout.cover.enabled');
  $('.cover-fields')?.classList.toggle('is-dim', !coverEnabled);
  const markEnabled = getPath(state.settings, 'layout.watermark.enabled');
  $('.watermark-fields')?.classList.toggle('is-dim', !markEnabled);
  updateEngineStatus();
}

function updateEngineStatus() {
  if (!dom.engineStatus || !state.config?.engine) return;
  const engine = state.config.engine;
  const pieces = [];
  let dotClass = 'engine-dot';
  if (engine.weasyprint) pieces.push('WeasyPrint disponibile');
  else pieces.push('WeasyPrint non disponibile');
  if (engine.chromium) pieces.push('Chromium disponibile');
  else pieces.push('Chromium non disponibile');
  pieces.push(engine.rich ? 'Mermaid/LaTeX attivi' : 'Mermaid/LaTeX non disponibili');
  pieces.push(state.config?.desktopDialog ? 'Dialogo di sistema' : 'Dialogo browser');
  if (!engine.weasyprint && !engine.chromium) dotClass += ' bad';
  else if (!engine.weasyprint || !engine.rich) dotClass += ' warn';
  dom.engineStatus.innerHTML = `<span class="${dotClass}"></span><span>${pieces.join(' · ')}</span>`;
}

function syncControlValues() {
  if (!state.settings) return;
  $$('[data-setting]').forEach((input) => {
    const value = getPath(state.settings, input.dataset.setting);
    if (value === undefined) return;
    if (input.type === 'checkbox') input.checked = Boolean(value);
    else input.value = value;
  });
  // Font selects may not contain a custom family yet.
  $$('select[data-font-select]').forEach((select) => {
    const value = getPath(state.settings, select.dataset.setting);
    if (value && !Array.from(select.options).some((option) => option.value === value)) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    }
    select.value = value;
  });
  const themeName = getPath(state.settings, 'theme.name') || 'light';
  if (dom.themeSelect) {
    if (!Array.from(dom.themeSelect.options).some((option) => option.value === themeName)) {
      const option = document.createElement('option');
      option.value = themeName;
      option.textContent = themeName;
      dom.themeSelect.appendChild(option);
    }
    dom.themeSelect.value = themeName;
  }
  refreshConditionalFields();
  updateStats();
}

function markDirty(dirty = true) {
  const tab = activeTab();
  if (!tab) return;
  tab.dirty = dirty;
  dom.dirtyDot.classList.toggle('visible', dirty);
  const tabNode = $(`.tab[data-id="${tab.id}"]`, dom.tabs);
  tabNode?.classList.toggle('dirty-tab', dirty);
  const dirtyMark = tabNode?.querySelector('.dirty');
  if (dirtyMark) dirtyMark.hidden = !dirty;
  dom.saveState.textContent = dirty ? 'modifiche non salvate' : 'salvato';
}

let lastSettingsError = '';
function handleSettingsError(error) {
  const message = error instanceof Error ? error.message : String(error);
  if (message !== lastSettingsError) {
    lastSettingsError = message;
    toastError(error, 'Impostazione non valida');
  }
}

function schedulePersistSettings() {
  clearTimeout(state.persistTimer);
  state.persistTimer = setTimeout(async () => {
    try {
      await api('/api/settings', { method: 'POST', body: { settings: state.settings } });
      lastSettingsError = '';
    } catch (error) {
      handleSettingsError(error);
    }
  }, 700);
}

async function persistSettingsNow() {
  clearTimeout(state.persistTimer);
  try {
    await api('/api/settings', { method: 'POST', body: { settings: state.settings } });
  } catch (error) {
    handleSettingsError(error);
  }
}

function controlsAreValid() {
  return $$('[data-setting]').every((input) => {
    if (input.type === 'number' || input.type === 'range') {
      if (input.validity?.badInput || input.validity?.rangeUnderflow || input.validity?.rangeOverflow) return false;
    }
    return true;
  });
}

function handleSettingInput(event) {
  const input = event.target.closest('[data-setting]');
  if (!input || !state.settings) return;
  const path = input.dataset.setting;
  let value;
  if (input.type === 'checkbox') value = input.checked;
  else if (input.type === 'number' || input.type === 'range') value = Number(input.value);
  else value = input.value;
  if (typeof value === 'number' && !Number.isFinite(value)) return;
  setSetting(path, value);

  if (path.startsWith('theme.') && path !== 'theme.name') {
    setSetting('theme.name', 'custom');
    if (dom.themeSelect && !Array.from(dom.themeSelect.options).some((o) => o.value === 'custom')) {
      const option = document.createElement('option');
      option.value = 'custom';
      option.textContent = 'Personalizzato';
      dom.themeSelect.appendChild(option);
    }
    if (dom.themeSelect) dom.themeSelect.value = 'custom';
  }

  // Keep paired range/number controls in sync without touching the focused one.
  $$(`[data-setting="${path}"]`).forEach((peer) => {
    if (peer === input) return;
    if (peer.type === 'checkbox') peer.checked = Boolean(value);
    else if (peer.type !== 'range' || input.type !== 'range') peer.value = value;
  });

  if (path === 'layout.pageSize' || path === 'layout.cover.enabled' || path === 'layout.watermark.enabled' || path === 'pdf.outputDir') {
    refreshConditionalFields();
  }
  if (path === 'document.filename') {
    updateDocMeta();
  }
  schedulePreview(380);
  schedulePersistSettings();
}

/* ------------------------------ Fonts / themes --------------------------- */
function populateFontSelects() {
  const fonts = state.config?.fonts || ['DejaVu Sans', 'DejaVu Serif', 'DejaVu Sans Mono'];
  $$('select[data-font-select]').forEach((select) => {
    const current = getPath(state.settings, select.dataset.setting);
    select.innerHTML = '';
    fonts.forEach((font) => {
      const option = document.createElement('option');
      option.value = font;
      option.textContent = font;
      select.appendChild(option);
    });
    if (current && !fonts.includes(current)) {
      const option = document.createElement('option');
      option.value = current;
      option.textContent = current;
      select.appendChild(option);
    }
    select.value = current;
  });
}

function populateThemeSelect() {
  if (!dom.themeSelect) return;
  const presets = state.config?.themePresets || Object.keys(state.config?.themes || {});
  const custom = state.customThemes || {};
  dom.themeSelect.innerHTML = '';
  const presetGroup = document.createElement('optgroup');
  presetGroup.label = 'Predefiniti';
  presets.forEach((name) => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name.charAt(0).toUpperCase() + name.slice(1);
    presetGroup.appendChild(option);
  });
  dom.themeSelect.appendChild(presetGroup);
  const customNames = Object.keys(custom);
  if (customNames.length) {
    const customGroup = document.createElement('optgroup');
    customGroup.label = 'Personalizzati';
    customNames.forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      customGroup.appendChild(option);
    });
    dom.themeSelect.appendChild(customGroup);
  }
  const option = document.createElement('option');
  option.value = 'custom';
  option.textContent = 'Personalizzato (colori correnti)';
  dom.themeSelect.appendChild(option);
  dom.themeSelect.value = getPath(state.settings, 'theme.name') || 'light';
  if (!Array.from(dom.themeSelect.options).some((o) => o.value === dom.themeSelect.value)) {
    dom.themeSelect.value = 'custom';
  }
}

function applyTheme(name) {
  if (name === 'custom') return;
  const colors = state.config?.themes?.[name];
  if (!colors) return;
  Object.assign(state.settings.theme, colors, { name });
  syncControlValues();
  dom.themeSelect.value = name;
  schedulePreview(60);
  schedulePersistSettings();
  toast('info', 'Tema applicato', name);
}

async function saveCustomTheme() {
  const name = (dom.customThemeName?.value || '').trim();
  if (!name) {
    toast('warning', 'Nome mancante', 'Inserisci un nome per il tema personalizzato.');
    dom.customThemeName?.focus();
    return;
  }
  try {
    const payload = {
      name,
      colors: Object.fromEntries(
        ['text', 'muted', 'link', 'headings', 'border', 'codeBg', 'codeText', 'blockquoteBg', 'tableHeaderBg', 'background']
          .map((key) => [key, state.settings.theme[key]]),
      ),
    };
    const response = await api('/api/themes', { method: 'POST', body: payload });
    state.customThemes[name] = response.theme.colors;
    state.config.themes[name] = response.theme.colors;
    state.settings.theme.name = name;
    populateThemeSelect();
    dom.themeSelect.value = name;
    schedulePersistSettings();
    dom.customThemeName.value = '';
    toast('success', 'Tema salvato', `“${name}” è ora disponibile nel selettore.`);
  } catch (error) {
    toastError(error, 'Impossibile salvare il tema');
  }
}

async function deleteSelectedTheme() {
  const name = dom.themeSelect?.value;
  if (!name || !state.customThemes[name]) {
    toast('warning', 'Nessun tema personalizzato selezionato', 'Seleziona un tema salvato da te per eliminarlo.');
    return;
  }
  const ok = await openConfirm({
    title: 'Eliminare il tema?',
    message: `Il tema “${name}” verrà rimosso. I documenti già esportati non cambiano.`,
    confirmText: 'Elimina tema',
  });
  if (!ok) return;
  try {
    await api(`/api/themes/${encodeURIComponent(name)}`, { method: 'DELETE' });
    delete state.customThemes[name];
    delete state.config.themes[name];
    if (state.settings.theme.name === name) {
      state.settings.theme.name = 'light';
      Object.assign(state.settings.theme, state.config.themes.light || {}, { name: 'light' });
      syncControlValues();
      schedulePreview(40);
    }
    state.config.customThemes = state.customThemes;
    populateThemeSelect();
    toast('success', 'Tema eliminato', name);
  } catch (error) {
    toastError(error, 'Impossibile eliminare il tema');
  }
}

/* ------------------------------ Profiles --------------------------------- */
function populateProfileSelect() {
  if (!dom.profileSelect) return;
  const previous = dom.profileSelect.value;
  dom.profileSelect.innerHTML = '';
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = '— scegli un profilo —';
  dom.profileSelect.appendChild(placeholder);

  if (state.builtinProfiles.length) {
    const group = document.createElement('optgroup');
    group.label = 'Predefiniti';
    state.builtinProfiles.forEach((profile) => {
      const option = document.createElement('option');
      option.value = `builtin:${profile.name}`;
      option.textContent = profile.name;
      group.appendChild(option);
    });
    dom.profileSelect.appendChild(group);
  }
  if (state.profiles.length) {
    const group = document.createElement('optgroup');
    group.label = 'I miei profili';
    state.profiles.forEach((profile) => {
      const option = document.createElement('option');
      option.value = `user:${profile.name}`;
      option.textContent = profile.name;
      group.appendChild(option);
    });
    dom.profileSelect.appendChild(group);
  }
  if (previous) dom.profileSelect.value = previous;
}

function selectedProfile() {
  const value = dom.profileSelect?.value || '';
  if (!value) return null;
  const [kind, ...rest] = value.split(':');
  const name = rest.join(':');
  if (kind === 'builtin') {
    return { kind, name, profile: state.builtinProfiles.find((item) => item.name === name) };
  }
  return { kind, name, profile: state.profiles.find((item) => item.name === name) };
}

async function refreshProfiles() {
  const response = await api('/api/profiles');
  state.profiles = response.profiles || [];
  state.builtinProfiles = response.builtinProfiles || [];
  populateProfileSelect();
}

function applySettingsObject(settings, message = '') {
  state.settings = deepClone(settings);
  syncControlValues();
  populateThemeSelect();
  schedulePreview(40);
  persistSettingsNow();
  if (message) toast('success', message);
}

async function loadSelectedProfile() {
  const selected = selectedProfile();
  if (!selected) {
    toast('warning', 'Nessun profilo selezionato', 'Scegli un profilo dal menu a tendina.');
    return;
  }
  if (!selected.profile) {
    toast('error', 'Profilo non trovato', selected.name);
    return;
  }
  try {
    applySettingsObject(selected.profile.settings, `Profilo “${selected.name}” applicato.`);
    dom.profileSelect.value = `${selected.kind}:${selected.name}`;
  } catch (error) {
    toastError(error, 'Impossibile applicare il profilo');
  }
}

async function saveProfile() {
  const name = await openPrompt({
    title: 'Salva profilo',
    message: 'Salva tutte le impostazioni correnti come profilo riutilizzabile.',
    label: 'Nome del profilo',
    value: selectedProfile()?.name || 'Mio profilo',
    confirmText: 'Salva profilo',
  });
  if (!name) return;
  try {
    const response = await api('/api/profiles', { method: 'POST', body: { name, settings: state.settings } });
    await refreshProfiles();
    dom.profileSelect.value = `user:${response.profile.name}`;
    dom.profileSelect.value = `user:${response.profile.name}`;
    toast('success', 'Profilo salvato', response.profile.name);
  } catch (error) {
    toastError(error, 'Impossibile salvare il profilo');
  }
}

async function duplicateProfile() {
  const selected = selectedProfile();
  const sourceSettings = selected?.profile?.settings || state.settings;
  const baseName = selected?.name || 'Profilo';
  const name = await openPrompt({
    title: 'Duplica profilo',
    message: 'Crea una copia indipendente del profilo selezionato (o delle impostazioni correnti).',
    label: 'Nome del nuovo profilo',
    value: `${baseName} (copia)`,
    confirmText: 'Duplica',
  });
  if (!name) return;
  try {
    const response = await api('/api/profiles', { method: 'POST', body: { name, settings: sourceSettings } });
    await refreshProfiles();
    dom.profileSelect.value = `user:${response.profile.name}`;
    toast('success', 'Profilo duplicato', response.profile.name);
  } catch (error) {
    toastError(error, 'Impossibile duplicare il profilo');
  }
}

async function renameProfile() {
  const selected = selectedProfile();
  if (!selected || selected.kind !== 'user') {
    toast('warning', 'Profilo non modificabile', 'I profili predefiniti non possono essere rinominati. Duplicali per modificarli.');
    return;
  }
  const name = await openPrompt({
    title: 'Rinomina profilo',
    message: `Nuovo nome per “${selected.name}”.`,
    label: 'Nome',
    value: selected.name,
    confirmText: 'Rinomina',
  });
  if (!name || name === selected.name) return;
  try {
    await api(`/api/profiles/${encodeURIComponent(selected.name)}/rename`, {
      method: 'POST',
      body: { newName: name },
    });
    await refreshProfiles();
    dom.profileSelect.value = `user:${name}`;
    toast('success', 'Profilo rinominato', name);
  } catch (error) {
    toastError(error, 'Impossibile rinominare il profilo');
  }
}

async function deleteProfile() {
  const selected = selectedProfile();
  if (!selected || selected.kind !== 'user') {
    toast('warning', 'Profilo non eliminabile', 'I profili predefiniti sono di sola lettura. Puoi eliminare solo i tuoi profili.');
    return;
  }
  const ok = await openConfirm({
    title: 'Eliminare il profilo?',
    message: `Il profilo “${selected.name}” verrà eliminato definitivamente.`,
    confirmText: 'Elimina',
  });
  if (!ok) return;
  try {
    await api(`/api/profiles/${encodeURIComponent(selected.name)}`, { method: 'DELETE' });
    await refreshProfiles();
    dom.profileSelect.value = '';
    toast('success', 'Profilo eliminato', selected.name);
  } catch (error) {
    toastError(error, 'Impossibile eliminare il profilo');
  }
}

async function exportProfile() {
  const selected = selectedProfile();
  try {
    if (selected) {
      const link = document.createElement('a');
      link.href = `/api/profiles/${encodeURIComponent(selected.name)}/export`;
      link.download = `profilo-${selected.name}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      toast('info', 'Profilo esportato', `Scaricamento di “${selected.name}” avviato.`);
      return;
    }
    const payload = {
      format: 'md-to-pdf-studio-profile',
      version: 1,
      name: 'Profilo corrente',
      settings: state.settings,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'profilo-corrente.json';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    toast('info', 'Profilo esportato', 'Le impostazioni correnti sono state scaricate in JSON.');
  } catch (error) {
    toastError(error, 'Impossibile esportare il profilo');
  }
}

function importProfileFile(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const data = JSON.parse(String(reader.result || '{}'));
      const body = data.profile ? { profile: data.profile } : { name: data.name || file.name.replace(/\.json$/i, ''), settings: data.settings || data };
      const response = await api('/api/profiles/import', { method: 'POST', body });
      await refreshProfiles();
      dom.profileSelect.value = `user:${response.profile.name}`;
      toast('success', 'Profilo importato', response.profile.name);
    } catch (error) {
      toastError(error, 'File profilo non valido');
    }
  };
  reader.readAsText(file);
}

async function resetAllSettings() {
  const ok = await openConfirm({
    title: 'Ripristinare le impostazioni?',
    message: 'Tutte le impostazioni correnti torneranno ai valori predefiniti. I profili salvati non saranno toccati.',
    confirmText: 'Ripristina',
  });
  if (!ok) return;
  try {
    const response = await api('/api/settings/reset', { method: 'POST', body: {} });
    applySettingsObject(response.settings, 'Impostazioni predefinite ripristinate.');
    dom.profileSelect.value = '';
    populateThemeSelect();
  } catch (error) {
    toastError(error, 'Impossibile ripristinare le impostazioni');
  }
}

/* ------------------------------ Tabs & editor ---------------------------- */
function newTab({ name = 'Senza titolo.md', content = '', path = null, baseDir = null, dirty = false } = {}) {
  const tab = {
    id: (crypto.randomUUID ? crypto.randomUUID() : `tab-${Date.now()}-${Math.random()}`),
    name,
    content,
    path,
    baseDir,
    dirty,
  };
  state.tabs.push(tab);
  state.activeId = tab.id;
  return tab;
}

function renderTabs() {
  dom.tabs.innerHTML = '';
  state.tabs.forEach((tab) => {
    const node = document.createElement('div');
    node.className = `tab${tab.id === state.activeId ? ' active' : ''}`;
    node.dataset.id = tab.id;
    node.setAttribute('role', 'tab');
    node.setAttribute('aria-selected', tab.id === state.activeId ? 'true' : 'false');
    node.tabIndex = 0;
    node.innerHTML = `
      <span class="tab-name">${escapeHtml(tab.name)}</span>
      <span class="dirty" ${tab.dirty ? '' : 'hidden'}></span>
      <button class="tab-close" title="Chiudi ${escapeHtml(tab.name)}" aria-label="Chiudi ${escapeHtml(tab.name)}">×</button>`;
    node.addEventListener('click', (event) => {
      if (event.target.closest('.tab-close')) {
        event.stopPropagation();
        closeTab(tab.id);
        return;
      }
      activateTab(tab.id);
    });
    node.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activateTab(tab.id); }
      if (event.key === 'Delete') closeTab(tab.id);
    });
    node.title = tab.path || tab.name;
    dom.tabs.appendChild(node);
  });
}

function updateDocMeta() {
  const tab = activeTab();
  if (!tab) return;
  dom.docName.textContent = tab.name;
  dom.docPath.textContent = tab.path || (tab.baseDir ? `base: ${tab.baseDir}` : 'bozza locale');
  dom.dirtyDot.classList.toggle('visible', Boolean(tab.dirty));
  document.title = `${stem(tab.name)} — MD → PDF Studio`;
}

function activateTab(id) {
  const next = state.tabs.find((tab) => tab.id === id);
  if (!next) return;
  const previous = activeTab();
  if (previous && previous.id !== next.id) saveDraftNow(previous);
  state.activeId = id;
  dom.editor.value = next.content;
  dom.editor.scrollTop = 0;
  dom.editorScroll.scrollTop = 0;
  if (!state.settings.document.filename || state.settings.document.filename === 'documento' ||
      (previous && state.settings.document.filename === stem(previous.name))) {
    state.settings.document.filename = stem(next.name);
    syncControlValues();
    schedulePersistSettings();
  }
  renderTabs();
  updateDocMeta();
  updateEditorView();
  markDirty(Boolean(next.dirty));
  schedulePreview(50);
  saveTabsLocal();
}

async function closeTab(id) {
  const index = state.tabs.findIndex((tab) => tab.id === id);
  if (index < 0) return;
  const tab = state.tabs[index];
  if (tab.dirty && tab.content.trim()) {
    const ok = await openConfirm({
      title: 'Chiudere il documento?',
      message: `“${tab.name}” contiene modifiche non salvate su disco. La bozza automatica resta disponibile.`,
      confirmText: 'Chiudi comunque',
    });
    if (!ok) return;
  }
  state.tabs.splice(index, 1);
  if (!state.tabs.length) {
    newTab({ name: 'Senza titolo.md', content: '' });
  } else if (state.activeId === id) {
    state.activeId = state.tabs[Math.max(0, index - 1)].id;
  }
  activateTab(state.activeId);
  saveTabsLocal();
}

function updateEditorView() {
  updateHighlight();
  updateStats();
  resizeEditor();
}

function updateStats() {
  const text = dom.editor.value || '';
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  dom.editorStats.textContent = `${words.toLocaleString('it-IT')} ${words === 1 ? 'parola' : 'parole'} · ${text.length.toLocaleString('it-IT')} caratteri`;
}

function updateHighlight() {
  dom.highlight.innerHTML = highlightMarkdown(dom.editor.value || '');
  updateLineNumbers();
}

function updateLineNumbers() {
  const count = String(dom.editor.value || '').split('\n').length;
  dom.lineNumbers.innerHTML = Array.from({ length: count }, (_, index) => `<div>${index + 1}</div>`).join('');
}

function resizeEditor() {
  dom.editor.style.height = 'auto';
  const height = Math.max(dom.editor.scrollHeight, dom.editorScroll.clientHeight);
  dom.editor.style.height = `${height}px`;
  dom.highlight.style.height = `${height}px`;
  dom.editorGutter.style.height = `${height}px`;
}

/* Lightweight Markdown highlighter. It renders an overlay behind the
   transparent textarea and never changes glyph widths (colours only). */
function highlightMarkdown(text) {
  const lines = String(text).split('\n');
  const output = [];
  let inFence = false;
  let fenceMarker = '';
  let inFrontmatter = false;
  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index];
    let escaped = escapeHtml(raw);

    if (index === 0 && /^---\s*$/.test(raw)) {
      inFrontmatter = true;
      output.push(`<span class="tok-front">${escaped}</span>`);
      continue;
    }
    if (inFrontmatter) {
      output.push(`<span class="tok-front">${escaped}</span>`);
      if (/^---\s*$/.test(raw)) inFrontmatter = false;
      continue;
    }

    const fenceMatch = raw.match(/^\s*(`{3,}|~{3,})(.*)$/);
    if (fenceMatch) {
      if (!inFence) { inFence = true; fenceMarker = fenceMatch[1][0]; }
      else if (fenceMatch[1][0] === fenceMarker) { inFence = false; }
      output.push(`<span class="tok-fence">${escaped}</span>`);
      continue;
    }
    if (inFence) {
      output.push(`<span class="tok-code">${escaped || ' '}</span>`);
      continue;
    }

    const heading = raw.match(/^(\s*)(#{1,6})(\s+)(.*)$/);
    if (heading) {
      output.push(`${escapeHtml(heading[1])}<span class="tok-heading-mark">${escapeHtml(heading[2])}</span>${escapeHtml(heading[3])}<span class="tok-heading">${highlightInline(escapeHtml(heading[4]))}</span>`);
      continue;
    }

    const quoteRaw = raw.match(/^(\s*)(>\s?)(.*)$/);
    if (quoteRaw) {
      output.push(`${escapeHtml(quoteRaw[1])}<span class="tok-quote-mark">&gt;${escapeHtml(quoteRaw[2].slice(1))}</span><span class="tok-quote">${highlightInline(escapeHtml(quoteRaw[3]))}</span>`);
      continue;
    }

    const list = raw.match(/^(\s*)([-*+]|\d+[.)])(\s+)(.*)$/);
    if (list) {
      let rest = list[4];
      let task = '';
      const taskMatch = rest.match(/^(\[[ xX]\])(\s+)(.*)$/);
      if (taskMatch) {
        task = `<span class="tok-task">${escapeHtml(taskMatch[1])}</span>${escapeHtml(taskMatch[2])}`;
        rest = taskMatch[3];
      }
      output.push(`${escapeHtml(list[1])}<span class="tok-list-mark">${escapeHtml(list[2])}</span>${escapeHtml(list[3])}${task}${highlightInline(escapeHtml(rest))}`);
      continue;
    }

    if (/^\s*\|/.test(raw)) {
      output.push(`<span class="tok-table">${escaped}</span>`);
      continue;
    }
    if (/^\s*&lt;!--.*--&gt;\s*$/.test(escaped)) {
      output.push(`<span class="tok-comment">${escaped}</span>`);
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(raw)) {
      output.push(`<span class="tok-hr">${escaped}</span>`);
      continue;
    }
    if (/\\(newpage|pagebreak)\s*$/i.test(raw)) {
      output.push(`<span class="tok-keyword">${escaped}</span>`);
      continue;
    }
    output.push(highlightInline(escaped));
  }
  return output.join('\n') + '\n';
}

function highlightInline(escaped) {
  if (!escaped) return '';
  const pattern = /(`[^`\n]+`|!\[[^\]]*\]\([^)]*\)|\[[^\]]*\]\([^)]*\)|\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~|\*[^*\n]+\*|_[^_\n]+_|(?:https?:\/\/|www\.)[^\s<]+)/g;
  return escaped.replace(pattern, (match) => {
    if (match.startsWith('`')) return `<span class="tok-code-inline">${match}</span>`;
    if (match.startsWith('![') || match.startsWith('[')) return `<span class="tok-link">${match}</span>`;
    if (match.startsWith('**') || match.startsWith('__')) return `<span class="tok-bold">${match}</span>`;
    if (match.startsWith('~~')) return `<span class="tok-strike">${match}</span>`;
    if (match.startsWith('*') || match.startsWith('_')) return `<span class="tok-italic">${match}</span>`;
    return `<span class="tok-url">${match}</span>`;
  });
}

function insertAtCursor(text) {
  const start = dom.editor.selectionStart ?? dom.editor.value.length;
  const end = dom.editor.selectionEnd ?? start;
  const value = dom.editor.value;
  dom.editor.value = value.slice(0, start) + text + value.slice(end);
  dom.editor.selectionStart = dom.editor.selectionEnd = start + text.length;
  dom.editor.dispatchEvent(new Event('input', { bubbles: true }));
  dom.editor.focus();
}

function saveTabsLocal() {
  clearTimeout(state.tabsTimer);
  state.tabsTimer = setTimeout(() => {
    try {
      localStorage.setItem('md2pdf.tabs.v1', JSON.stringify({
        tabs: state.tabs.map((tab) => ({ id: tab.id, name: tab.name, content: tab.content, path: tab.path, baseDir: tab.baseDir, dirty: tab.dirty })),
        activeId: state.activeId,
      }));
      localStorage.setItem('md2pdf.settings.v1', JSON.stringify(state.settings));
    } catch (error) {
      console.warn('Salvataggio locale non disponibile:', error);
    }
  }, 400);
}

let draftSaveTimer = null;
function saveDraftSoon() {
  clearTimeout(draftSaveTimer);
  draftSaveTimer = setTimeout(() => saveDraftNow(), 1000);
}

async function saveDraftNow(tab = activeTab()) {
  if (!tab) return;
  try {
    await api('/api/draft', { method: 'POST', body: { content: tab.content } });
    dom.saveState.textContent = `bozza salvata ${nowTime()}`;
  } catch (error) {
    dom.saveState.textContent = 'bozza non salvata';
  }
}

/* ------------------------------ File operations -------------------------- */
function isMarkdownFile(file) {
  return /\.(md|markdown|mdown|txt)$/i.test(file.name || '');
}

async function openFiles(fileList) {
  const files = Array.from(fileList || []).filter(isMarkdownFile);
  if (!files.length) {
    toast('warning', 'Nessun file Markdown', 'Formati accettati: .md, .markdown, .mdown, .txt.');
    return;
  }
  for (const file of files) {
    try {
      const content = await file.text();
      const tab = newTab({ name: file.name, content, path: null, baseDir: null, dirty: false });
      state.activeId = tab.id;
      toast('info', 'File aperto', `${file.name} · ${formatBytes(file.size)}`);
    } catch (error) {
      toastError(error, `Impossibile leggere ${file.name}`);
    }
  }
  activateTab(state.activeId);
  dom.fileInput.value = '';
}

async function openPath() {
  const path = await openPrompt({
    title: 'Apri da percorso',
    message: 'Inserisci il percorso assoluto di un file Markdown. In questo modo le immagini relative vengono risolte correttamente.',
    label: 'Percorso del file',
    placeholder: '/home/utente/Documenti/report.md',
    confirmText: 'Apri',
  });
  if (!path) return;
  try {
    const response = await api('/api/open', { method: 'POST', body: { path } });
    const tab = newTab({
      name: response.name,
      content: response.content,
      path: response.path,
      baseDir: response.baseDir,
      dirty: false,
    });
    state.activeId = tab.id;
    state.settings.document.filename = stem(response.name);
    activateTab(tab.id);
    schedulePersistSettings();
    toast('success', 'File aperto', response.path);
  } catch (error) {
    toastError(error, 'Impossibile aprire il file');
  }
}

async function saveAs() {
  const tab = activeTab();
  if (!tab) return;
  const defaultPath = tab.path || `${tab.baseDir || '~'}/${stem(tab.name)}.md`;
  const path = await openPrompt({
    title: 'Salva con nome',
    message: 'Il file Markdown verrà scritto nel percorso indicato. La cartella deve esistere.',
    label: 'Percorso completo',
    value: defaultPath,
    confirmText: 'Salva',
  });
  if (!path) return;
  try {
    const response = await api('/api/save', { method: 'POST', body: { path, content: tab.content } });
    tab.path = response.path;
    tab.baseDir = response.baseDir;
    tab.name = response.name;
    tab.dirty = false;
    renderTabs();
    updateDocMeta();
    markDirty(false);
    saveTabsLocal();
    toast('success', 'Documento salvato', response.path);
  } catch (error) {
    toastError(error, 'Impossibile salvare il documento');
  }
}

async function saveCurrent() {
  const tab = activeTab();
  if (!tab) return;
  if (!tab.path) {
    await saveAs();
    return;
  }
  try {
    const response = await api('/api/save', { method: 'POST', body: { path: tab.path, content: tab.content } });
    tab.dirty = false;
    tab.baseDir = response.baseDir;
    markDirty(false);
    saveTabsLocal();
    toast('success', 'Documento salvato', response.path);
  } catch (error) {
    toastError(error, 'Impossibile salvare il documento');
  }
}

async function uploadImage(file, target = 'markdown') {
  if (!file) return;
  const form = new FormData();
  form.append('file', file);
  try {
    const response = await api('/api/assets', { method: 'POST', body: form });
    if (target === 'cover') {
      setSetting('layout.cover.logo', response.path);
      state.settings.layout.cover.enabled = true;
      syncControlValues();
      schedulePreview(40);
      schedulePersistSettings();
      toast('success', 'Logo caricato', response.path);
      return;
    }
    const alt = file.name.replace(/\.[^.]+$/, '');
    insertAtCursor(`\n![${alt}](${response.path})\n`);
    toast('success', 'Immagine inserita', response.path);
  } catch (error) {
    toastError(error, 'Caricamento immagine non riuscito');
  }
}

async function loadExample() {
  try {
    const response = await api('/api/example');
    const tab = newTab({ name: response.name, content: response.content, path: null, baseDir: response.baseDir });
    state.activeId = tab.id;
    state.settings.document.filename = 'demo';
    activateTab(tab.id);
    schedulePersistSettings();
    toast('success', 'Esempio caricato', 'Documento dimostrativo con tabelle, codice, TOC, immagini e note.');
  } catch (error) {
    toastError(error, 'Impossibile caricare l’esempio');
  }
}

/* ------------------------------ Preview ---------------------------------- */
function schedulePreview(delay = 380) {
  clearTimeout(state.previewTimer);
  state.previewTimer = setTimeout(() => { state.previewTimer = null; runPreview(); }, delay);
}

function clearPreview(message = 'In attesa del documento…') {
  state.preview.requestId += 1;
  if (state.preview.abort) { state.preview.abort.abort(); state.preview.abort = null; }
  dom.previewPane.classList.remove('busy');
  state.preview.total = 0;
  state.preview.page = 1;
  state.preview.lastPdf = null;
  dom.previewPages.innerHTML = '';
  dom.previewEmpty.hidden = false;
  dom.pdfFallback.hidden = true;
  dom.pageNumber.value = '1';
  dom.pageTotal.textContent = '0';
  dom.previewStatus.textContent = message;
  dom.previewWarnings.hidden = true;
  dom.btnWarnings.hidden = true;
  if (state.preview.pdfDoc) {
    state.preview.pdfDoc.destroy().catch(() => {});
    state.preview.pdfDoc = null;
  }
}

async function runPreview() {
  const tab = activeTab();
  if (!tab) { clearPreview(); return; }
  if (!tab.content.trim()) { clearPreview('Documento vuoto: scrivi qualcosa per vedere l’anteprima.'); return; }
  if (!controlsAreValid()) {
    dom.previewStatus.textContent = 'Controlla i valori evidenziati nelle impostazioni.';
    return;
  }

  const requestId = ++state.preview.requestId;
  if (state.preview.abort) state.preview.abort.abort();
  const controller = new AbortController();
  state.preview.abort = controller;
  dom.previewPane.classList.add('busy');
  dom.previewStatus.textContent = 'Conversione in corso…';

  const settings = deepClone(state.settings);
  const filename = outputName(tab);
  const started = performance.now();
  try {
    const response = await fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        markdown: tab.content,
        settings,
        filename,
        base_dir: tab.baseDir || null,
      }),
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = Array.isArray(payload?.detail)
        ? payload.detail.map((item) => item.msg || JSON.stringify(item)).join('; ')
        : payload?.detail;
      throw new Error(detail || `Errore HTTP ${response.status}`);
    }
    if (requestId !== state.preview.requestId) return;

    state.lastPreviewSettings = settings;
    state.lastPreviewMeta = payload;
    state.preview.total = payload.pageCount || 0;
    dom.pageTotal.textContent = String(state.preview.total);
    dom.pageNumber.max = String(Math.max(1, state.preview.total));
    dom.previewEngine.textContent = payload.marp
      ? `Marp ${payload.marpSize || '16:9'}`
      : (payload.engine === 'weasyprint' ? 'WeasyPrint' : 'Chromium');
    renderWarnings(payload.warnings || []);

    await renderPdfPayload(payload.pdf, { page: state.preview.page });
    if (requestId !== state.preview.requestId) return;

    const totalMs = payload.durationMs ?? Math.round(performance.now() - started);
    const unit = payload.marp ? 'slide' : (payload.pageCount === 1 ? 'pagina' : 'pagine');
    dom.previewStatus.textContent = `${payload.pageCount} ${unit} · ${totalMs} ms · ${payload.engine === 'weasyprint' ? 'WeasyPrint' : 'Chromium'}${payload.marp ? ' · Marp' : ''}`;
    state.preview.lastError = '';
  } catch (error) {
    if (error.name === 'AbortError') return;
    if (requestId !== state.preview.requestId) return;
    dom.previewStatus.textContent = `Errore: ${error.message}`;
    const now = Date.now();
    if (error.message !== state.preview.lastError || now - state.preview.lastErrorAt > 5000) {
      state.preview.lastError = error.message;
      state.preview.lastErrorAt = now;
      toastError(error, 'Conversione non riuscita');
    }
  } finally {
    if (requestId === state.preview.requestId) {
      dom.previewPane.classList.remove('busy');
      state.preview.abort = null;
    }
  }
}

function renderWarnings(warnings) {
  const meaningful = warnings.filter((warning) => warning && warning.message);
  if (!meaningful.length) {
    dom.btnWarnings.hidden = true;
    dom.previewWarnings.hidden = true;
    dom.previewWarnings.innerHTML = '';
    return;
  }
  dom.btnWarnings.hidden = false;
  dom.btnWarnings.textContent = `${meaningful.length} ${meaningful.length === 1 ? 'avviso' : 'avvisi'}`;
  dom.previewWarnings.innerHTML = `<ul>${meaningful.map((warning) => `<li><span class="warn-level">${escapeHtml(warning.level || 'warning')}</span>${escapeHtml(warning.message)}</li>`).join('')}</ul>`;
}

function base64ToBytes(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function pageZoomScale(page, containerWidth) {
  if (state.preview.fit) {
    const base = page.getViewport({ scale: 1 });
    return Math.max(0.15, (containerWidth - 56) / base.width);
  }
  return (96 / 72) * (state.preview.zoom / 100);
}

async function renderPdfPayload(base64, { page = 1 } = {}) {
  if (!pdfjsLib) return renderFallbackPdf(base64, page);
  const token = ++state.preview.renderToken;
  state.preview.renderTasks.forEach((task) => { try { task.cancel(); } catch (error) { /* noop */ } });
  state.preview.renderTasks = [];
  state.preview.lastPdf = base64;
  dom.pdfFallback.hidden = true;
  dom.pdfFallback.src = '';

  const loadingTask = pdfjsLib.getDocument({ data: base64ToBytes(base64) });
  const doc = await loadingTask.promise;
  if (token !== state.preview.renderToken) { doc.destroy(); return; }

  const previousDoc = state.preview.pdfDoc;
  state.preview.pdfDoc = doc;
  state.preview.total = doc.numPages;
  dom.pageTotal.textContent = String(doc.numPages);
  dom.pageNumber.max = String(doc.numPages);
  dom.previewPages.innerHTML = '';
  dom.previewEmpty.hidden = doc.numPages > 0;

  const containerWidth = Math.max(320, dom.previewScroll.clientWidth - 52);
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const wrappers = [];

  for (let pageNumber = 1; pageNumber <= doc.numPages; pageNumber += 1) {
    if (token !== state.preview.renderToken) { doc.destroy(); return; }
    const pageProxy = await doc.getPage(pageNumber);
    const cssScale = pageZoomScale(pageProxy, containerWidth);
    const viewport = pageProxy.getViewport({ scale: cssScale * dpr });
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.floor(viewport.width));
    canvas.height = Math.max(1, Math.floor(viewport.height));
    canvas.style.width = `${Math.floor(viewport.width / dpr)}px`;
    canvas.style.height = `${Math.floor(viewport.height / dpr)}px`;
    const wrapper = document.createElement('div');
    wrapper.className = 'pdf-page';
    wrapper.dataset.page = String(pageNumber);
    wrapper.appendChild(canvas);
    const tag = document.createElement('span');
    tag.className = 'page-tag';
    tag.textContent = `${pageNumber} / ${doc.numPages}`;
    wrapper.appendChild(tag);
    dom.previewPages.appendChild(wrapper);
    const context = canvas.getContext('2d', { alpha: false });
    context.save();
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.restore();
    const renderTask = pageProxy.render({ canvasContext: context, viewport });
    state.preview.renderTasks.push(renderTask);
    try {
      await renderTask.promise;
    } catch (error) {
      if (error?.name !== 'RenderingCancelledException') throw error;
    }
    wrappers.push(wrapper);
  }

  if (token !== state.preview.renderToken) { doc.destroy(); return; }
  if (previousDoc && previousDoc !== doc) previousDoc.destroy().catch(() => {});
  state.preview.renderTasks = [];

  const target = Math.min(Math.max(1, page), doc.numPages);
  goToPage(target, { smooth: false });
  updatePageFromScroll();
}

function renderFallbackPdf(base64, page = 1) {
  const bytes = base64ToBytes(base64);
  const blob = new Blob([bytes], { type: 'application/pdf' });
  if (state.preview.fallbackUrl) URL.revokeObjectURL(state.preview.fallbackUrl);
  state.preview.fallbackUrl = URL.createObjectURL(blob);
  dom.previewPages.innerHTML = '';
  dom.previewEmpty.hidden = true;
  dom.pdfFallback.hidden = false;
  dom.pdfFallback.src = state.preview.fallbackUrl;
  state.preview.total = Number(dom.pageTotal.textContent) || state.preview.total;
  dom.previewStatus.textContent = 'Anteprima con visualizzatore PDF del browser (PDF.js non disponibile).';
}

function currentPreviewPages() {
  return $$('.pdf-page', dom.previewPages);
}

function updatePageFromScroll() {
  const pages = currentPreviewPages();
  if (!pages.length) return;
  const containerTop = dom.previewScroll.getBoundingClientRect().top;
  let current = 1;
  pages.forEach((page, index) => {
    const relativeTop = page.getBoundingClientRect().top - containerTop;
    if (relativeTop <= 120) current = index + 1;
  });
  state.preview.page = current;
  if (document.activeElement !== dom.pageNumber) dom.pageNumber.value = String(current);
}

function goToPage(page, { smooth = true } = {}) {
  const pages = currentPreviewPages();
  if (!pages.length) return;
  const target = Math.min(Math.max(1, Number(page) || 1), pages.length);
  const element = pages[target - 1];
  const rect = element.getBoundingClientRect();
  const containerRect = dom.previewScroll.getBoundingClientRect();
  const top = dom.previewScroll.scrollTop + (rect.top - containerRect.top) - 18;
  state.preview.page = target;
  dom.pageNumber.value = String(target);
  dom.previewScroll.scrollTo({ top: Math.max(0, top), behavior: smooth ? 'smooth' : 'auto' });
}

function rerenderForZoom() {
  if (!state.preview.lastPdf) return;
  const page = state.preview.page || 1;
  renderPdfPayload(state.preview.lastPdf, { page }).catch((error) => toastError(error, 'Rendering anteprima non riuscito'));
}

function setZoom(percent) {
  state.preview.zoom = Math.min(300, Math.max(25, Math.round(percent)));
  state.preview.fit = false;
  dom.zoomLabel.textContent = `${state.preview.zoom}%`;
  dom.btnFitWidth.classList.remove('active');
  dom.btnFitWidth.setAttribute('aria-pressed', 'false');
  rerenderForZoom();
}

function setFitWidth() {
  state.preview.fit = true;
  dom.btnFitWidth.classList.add('active');
  dom.btnFitWidth.setAttribute('aria-pressed', 'true');
  dom.zoomLabel.textContent = 'Auto';
  rerenderForZoom();
}

/* ------------------------------ Export ----------------------------------- */
function setButtonBusy(button, busy) {
  if (!button) return;
  button.classList.toggle('loading', busy);
  button.disabled = busy;
}

function exportPayload(tab) {
  return {
    markdown: tab.content,
    settings: state.settings,
    filename: outputName(tab),
    base_dir: tab.baseDir || null,
    output_dir: state.settings.pdf?.outputDir || null,
    save_copy: true,
  };
}

function showExportSuccess(response) {
  const savedTo = response.savedTo || response.path || response.filename || 'PDF';
  const copyHint = response.copyPath ? ` · copia automatica: ${response.copyPath}` : '';
  const pages = response.marp
    ? `${response.pageCount} slide`
    : (response.pageCount === 1 ? '1 pagina' : `${response.pageCount} pagine`);
  toast('success', 'PDF esportato', `${savedTo} · ${pages}${copyHint}`, {
    timeout: 9000,
    actions: [
      ...(response.copyUrl ? [{ label: 'Apri copia automatica', href: response.copyUrl, blank: true }] : []),
      ...(response.copyPath ? [{
        label: 'Copia percorso copia',
        onClick: () => navigator.clipboard?.writeText(response.copyPath).then(() => toast('info', 'Percorso copiato')),
      }] : []),
      ...(response.path && response.method === 'desktop' ? [{
        label: 'Copia percorso PDF',
        onClick: () => navigator.clipboard?.writeText(response.path).then(() => toast('info', 'Percorso copiato')),
      }] : []),
    ],
  });
  if (response.warnings?.length) {
    toast('warning', `${response.warnings.length} ${response.warnings.length === 1 ? 'avviso' : 'avvisi'} durante la conversione`, response.warnings[0].message, { timeout: 8000 });
  }
}

/* Native OS dialog opened by the local server: works in Firefox too. */
async function exportWithDesktopDialog(tab) {
  setButtonBusy(dom.btnExport, true);
  try {
    const response = await api('/api/export-dialog', { method: 'POST', body: exportPayload(tab) });
    if (response.canceled) return true;
    if (response.dialogUnavailable) {
      toast('warning', 'Dialogo di sistema non disponibile', response.detail || 'Uso il dialogo del browser.');
      return false;
    }
    state.lastExport = { ...response, method: 'desktop' };
    showExportSuccess({ ...response, savedTo: response.path, method: 'desktop' });
    return true;
  } catch (error) {
    if (error?.status === 404 || error?.status === 503) {
      toast('warning', 'Dialogo di sistema non disponibile', 'Uso il dialogo del browser.');
      return false;
    }
    toastError(error, 'Esportazione non riuscita');
    return true;
  } finally {
    setButtonBusy(dom.btnExport, false);
  }
}

/* Browser fallback: File System Access API where available, download otherwise. */
async function exportWithBrowserPicker(tab) {
  setButtonBusy(dom.btnExport, true);
  let usedPicker = false;
  try {
    let handle = null;
    if (typeof window.showSaveFilePicker === 'function') {
      try {
        handle = await window.showSaveFilePicker({
          suggestedName: `${outputName(tab)}.pdf`,
          types: [{ description: 'Documento PDF', accept: { 'application/pdf': ['.pdf'] } }],
        });
        usedPicker = true;
      } catch (error) {
        if (error?.name === 'AbortError') return;
        handle = null;
        usedPicker = false;
      }
    }

    const response = await api('/api/export', { method: 'POST', body: exportPayload(tab) });
    const bytes = base64ToBytes(response.pdf);
    const blob = new Blob([bytes], { type: 'application/pdf' });
    let savedName = response.filename || `${outputName(tab)}.pdf`;

    if (handle) {
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      savedName = handle.name || savedName;
    } else {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = savedName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    }

    const result = { ...response, savedTo: savedName, method: usedPicker ? 'picker' : 'download' };
    state.lastExport = result;
    showExportSuccess(result);
  } catch (error) {
    toastError(error, 'Esportazione non riuscita');
  } finally {
    setButtonBusy(dom.btnExport, false);
  }
}

async function exportPdf() {
  const tab = activeTab();
  if (!tab) { toast('warning', 'Nessun documento', 'Apri o crea un documento prima di esportare.'); return; }
  if (!tab.content.trim()) { toast('warning', 'Documento vuoto', 'Scrivi del Markdown prima di esportare.'); return; }
  if (state.config?.desktopDialog) {
    const handled = await exportWithDesktopDialog(tab);
    if (handled) return;
  }
  await exportWithBrowserPicker(tab);
}

/* ------------------------------ Batch ------------------------------------ */
async function handleBatchFiles(fileList) {
  const files = Array.from(fileList || []).filter(isMarkdownFile);
  for (const file of files) {
    try {
      const markdown = await file.text();
      state.batch.push({ name: file.name, markdown, size: file.size });
    } catch (error) {
      toastError(error, `Impossibile leggere ${file.name}`);
    }
  }
  renderBatchList();
}

function renderBatchList() {
  dom.batchList.innerHTML = state.batch.map((file, index) => `
    <li>
      <span>${escapeHtml(file.name)}</span>
      <span class="file-size">${formatBytes(file.size)}</span>
      <button class="link-btn danger" data-remove-batch="${index}" aria-label="Rimuovi ${escapeHtml(file.name)}">Rimuovi</button>
    </li>`).join('');
  dom.btnRunBatch.disabled = state.batch.length === 0;
  $$('[data-remove-batch]', dom.batchList).forEach((button) => {
    button.addEventListener('click', () => {
      state.batch.splice(Number(button.dataset.removeBatch), 1);
      renderBatchList();
    });
  });
}

async function runBatch() {
  if (!state.batch.length) return;
  setButtonBusy(dom.btnRunBatch, true);
  dom.batchResults.hidden = false;
  dom.batchResults.innerHTML = '<div class="file-size">Conversione in corso…</div>';
  try {
    const response = await api('/api/batch', {
      method: 'POST',
      body: {
        files: state.batch.map((file) => ({ name: file.name, markdown: file.markdown })),
        settings: state.settings,
        output_dir: state.settings.pdf?.outputDir || null,
      },
    });
    dom.batchResults.innerHTML = response.results.map((result) => `
      <div class="batch-result ${result.ok ? 'ok' : 'err'}">
        <span class="status">${result.ok ? '✓' : '×'}</span>
        <span class="detail">
          <strong>${escapeHtml(result.name)}</strong><br>
          ${result.ok
            ? `${result.pageCount} pagine · ${result.durationMs} ms${result.url ? ` · <a href="${escapeHtml(result.url)}" target="_blank" rel="noopener">Apri PDF</a>` : ''}<br><span class="file-size">${escapeHtml(result.path)}</span>`
            : escapeHtml(result.error || 'Errore sconosciuto')}
        </span>
      </div>`).join('');
    const okCount = response.results.filter((item) => item.ok).length;
    toast(okCount === response.results.length ? 'success' : 'warning', 'Batch completato', `${okCount} di ${response.results.length} PDF esportati in ${response.outputDir}.`, { timeout: 9000 });
  } catch (error) {
    dom.batchResults.innerHTML = '';
    toastError(error, 'Batch non riuscito');
  } finally {
    setButtonBusy(dom.btnRunBatch, false);
  }
}

/* ------------------------------ Logs ------------------------------------- */
async function openLogs() {
  dom.logsDialog.showModal();
  await refreshLogs();
}

async function refreshLogs() {
  try {
    const response = await api('/api/logs?limit=150');
    const logs = response.logs || [];
    dom.logTable.innerHTML = logs.length
      ? logs.map((entry) => `
        <tr>
          <td>${escapeHtml((entry.timestamp || '').replace('T', ' '))}</td>
          <td>${escapeHtml(entry.filename || '—')}</td>
          <td class="${entry.status === 'ok' ? 'log-ok' : 'log-err'}">${entry.status === 'ok' ? 'OK' : 'ERRORE'}</td>
          <td>${entry.pages ?? '—'}</td>
          <td>${entry.durationMs ?? '—'} ms</td>
          <td>${escapeHtml(entry.engine || '—')}</td>
          <td title="${escapeHtml(entry.path || entry.message || '')}">${escapeHtml(entry.path || entry.message || '')}</td>
        </tr>`).join('')
      : '<tr><td colspan="7" style="text-align:center;color:#647a99;padding:20px">Nessuna conversione registrata.</td></tr>';
  } catch (error) {
    toastError(error, 'Impossibile leggere i log');
  }
}

/* ------------------------------ Settings drawer -------------------------- */
function setSettingsOpen(open) {
  state.settingsOpen = open;
  document.body.classList.toggle('settings-open', open);
  dom.settingsDrawer.setAttribute('aria-hidden', open ? 'false' : 'true');
  dom.drawerScrim.hidden = !open;
  if (open) {
    setTimeout(() => {
      if (state.preview.fit) rerenderForZoom();
    }, 260);
  }
}

function switchSettingsPanel(panel) {
  $$('.settings-tab').forEach((tab) => tab.classList.toggle('active', tab.dataset.panel === panel));
  $$('.settings-panel').forEach((section) => section.classList.toggle('active', section.dataset.panel === panel));
}

/* ------------------------------ Initialization --------------------------- */
async function loadConfig() {
  state.config = await api('/api/config');
  state.settings = deepClone(state.config.settings);
  state.profiles = state.config.profiles || [];
  state.builtinProfiles = state.config.builtinProfiles || [];
  state.customThemes = state.config.customThemes || {};
  state.themes = state.config.themes || {};
  populateFontSelects();
  populateThemeSelect();
  populateProfileSelect();
  syncControlValues();
  dom.factDraft.textContent = state.config.draftPath || '—';
  dom.factState.textContent = state.config.stateDir || '—';
  const engine = state.config.engine || {};
  dom.factLog.textContent = `${engine.weasyprint ? 'WeasyPrint pronto' : engine.chromium ? 'Chromium pronto' : 'nessun motore'} · Mermaid/LaTeX ${engine.rich ? 'attivi' : 'non disponibili'}`;
  if (state.config.limits) dom.pageNumber.max = '1';
}

async function restoreDocuments() {
  let restored = null;
  try {
    const raw = localStorage.getItem('md2pdf.tabs.v1');
    if (raw) restored = JSON.parse(raw);
  } catch (error) {
    restored = null;
  }
  if (restored && Array.isArray(restored.tabs) && restored.tabs.length) {
    state.tabs = restored.tabs
      .filter((tab) => tab && typeof tab.content === 'string')
      .map((tab) => ({
        id: tab.id || (crypto.randomUUID ? crypto.randomUUID() : `tab-${Date.now()}-${Math.random()}`),
        name: tab.name || 'Senza titolo.md',
        content: tab.content,
        path: tab.path || null,
        baseDir: tab.baseDir || null,
        dirty: Boolean(tab.dirty),
      }));
    if (!state.tabs.length) restored = null;
    else state.activeId = restored.activeId && state.tabs.some((tab) => tab.id === restored.activeId)
      ? restored.activeId
      : state.tabs[0].id;
  }
  if (!restored || !state.tabs.length) {
    let draft = '';
    try {
      const response = await api('/api/draft');
      draft = response.content || '';
    } catch (error) {
      draft = '';
    }
    if (draft.trim()) {
      newTab({ name: 'bozza.md', content: draft, path: null, baseDir: null, dirty: false });
      state.settings.document.filename = 'bozza';
    } else {
      newTab({ name: 'Benvenuto.md', content: WELCOME_MARKDOWN, path: null, baseDir: null, dirty: false });
      state.settings.document.filename = 'benvenuto';
    }
  }
  if (!state.settings.document.filename || state.settings.document.filename === 'documento') {
    state.settings.document.filename = stem(activeTab()?.name);
    syncControlValues();
  }
  activateTab(state.activeId);
  renderTabs();
  updateDocMeta();
}

function bindEvents() {
  // Generic settings controls
  document.addEventListener('input', (event) => {
    if (event.target.closest('[data-setting]')) handleSettingInput(event);
  });
  document.addEventListener('change', (event) => {
    const input = event.target.closest('[data-setting]');
    if (!input) return;
    if (input.type === 'number' || input.type === 'range') {
      const before = input.value;
      if (input.validity?.rangeUnderflow) input.value = input.min;
      if (input.validity?.rangeOverflow) input.value = input.max;
      if (input.value !== before) input.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });
  document.addEventListener('focusin', (event) => {
    const input = event.target.closest('[data-hf]');
    if (input) state.lastHF = input;
  });

  // Editor
  dom.editor.addEventListener('input', () => {
    const tab = activeTab();
    if (!tab) return;
    tab.content = dom.editor.value;
    tab.dirty = true;
    markDirty(true);
    updateHighlight();
    updateStats();
    resizeEditor();
    schedulePreview(380);
    saveDraftSoon();
    saveTabsLocal();
  });
  dom.editor.addEventListener('keydown', (event) => {
    if (event.key === 'Tab') {
      event.preventDefault();
      insertAtCursor('  ');
    }
  });
  dom.editor.addEventListener('scroll', () => {
    // The gutter and highlight are in the same scroll container; only the
    // textarea can scroll internally after resize, so keep them aligned.
    dom.highlight.scrollTop = dom.editor.scrollTop;
    dom.highlight.scrollLeft = dom.editor.scrollLeft;
  });

  // Top actions
  dom.btnNew.addEventListener('click', () => {
    const tab = newTab({ name: 'Senza titolo.md', content: '', path: null, baseDir: null, dirty: false });
    state.settings.document.filename = stem(tab.name);
    syncControlValues();
    activateTab(tab.id);
    dom.editor.focus();
  });
  dom.btnOpen.addEventListener('click', () => dom.fileInput.click());
  dom.btnSave.addEventListener('click', saveCurrent);
  dom.btnExport.addEventListener('click', exportPdf);
  dom.btnBatch.addEventListener('click', () => { dom.batchResults.hidden = true; dom.batchDialog.showModal(); });
  dom.btnLogs.addEventListener('click', openLogs);
  dom.btnSettings.addEventListener('click', () => setSettingsOpen(!state.settingsOpen));
  $('#btnCloseSettings').addEventListener('click', () => setSettingsOpen(false));
  dom.drawerScrim.addEventListener('click', () => setSettingsOpen(false));

  $('#btnExample').addEventListener('click', loadExample);
  $('#btnOpenPath').addEventListener('click', openPath);
  $('#btnSaveAs').addEventListener('click', saveAs);
  $('#btnInsertImage').addEventListener('click', () => dom.imageInput.click());
  $('#btnCoverLogo').addEventListener('click', () => dom.coverLogoInput.click());

  dom.fileInput.addEventListener('change', () => openFiles(dom.fileInput.files));
  dom.imageInput.addEventListener('change', () => {
    const file = dom.imageInput.files?.[0];
    dom.imageInput.value = '';
    if (file) uploadImage(file, 'markdown');
  });
  dom.coverLogoInput.addEventListener('change', () => {
    const file = dom.coverLogoInput.files?.[0];
    dom.coverLogoInput.value = '';
    if (file) uploadImage(file, 'cover');
  });
  dom.profileImportInput.addEventListener('change', () => {
    const file = dom.profileImportInput.files?.[0];
    dom.profileImportInput.value = '';
    if (file) importProfileFile(file);
  });

  // Settings drawer
  $$('.settings-tab').forEach((tab) => tab.addEventListener('click', () => switchSettingsPanel(tab.dataset.panel)));
  dom.profileSelect.addEventListener('change', () => {});
  $('#btnLoadProfile').addEventListener('click', loadSelectedProfile);
  $('#btnSaveProfile').addEventListener('click', saveProfile);
  $('#btnDuplicateProfile').addEventListener('click', duplicateProfile);
  $('#btnRenameProfile').addEventListener('click', renameProfile);
  $('#btnDeleteProfile').addEventListener('click', deleteProfile);
  $('#btnExportProfile').addEventListener('click', exportProfile);
  $('#btnImportProfile').addEventListener('click', () => dom.profileImportInput.click());
  $('#btnResetSettings').addEventListener('click', resetAllSettings);
  $('#btnShortcuts').addEventListener('click', () => dom.shortcutsDialog.showModal());

  dom.themeSelect.addEventListener('change', () => applyTheme(dom.themeSelect.value));
  $('#btnSaveTheme').addEventListener('click', saveCustomTheme);
  $('#btnDeleteTheme').addEventListener('click', deleteSelectedTheme);

  $$('#hfVariables .chip').forEach((chip) => {
    chip.addEventListener('click', (event) => {
      event.preventDefault();
      const target = state.lastHF || $('[data-setting="headerFooter.footerCenter"]');
      if (!target) return;
      const variable = chip.dataset.var;
      const start = target.selectionStart ?? target.value.length;
      const end = target.selectionEnd ?? start;
      target.value = target.value.slice(0, start) + variable + target.value.slice(end);
      target.focus();
      target.selectionStart = target.selectionEnd = start + variable.length;
      target.dispatchEvent(new Event('input', { bubbles: true }));
    });
  });

  // Preview controls
  $('#btnPrevPage').addEventListener('click', () => goToPage(state.preview.page - 1));
  $('#btnNextPage').addEventListener('click', () => goToPage(state.preview.page + 1));
  dom.pageNumber.addEventListener('change', () => goToPage(dom.pageNumber.value));
  dom.pageNumber.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); goToPage(dom.pageNumber.value); }
  });
  dom.previewScroll.addEventListener('scroll', () => {
    if (!state.preview.fit && !state.preview.pdfDoc) return;
    window.requestAnimationFrame(updatePageFromScroll);
  });
  $('#btnZoomIn').addEventListener('click', () => setZoom((state.preview.fit ? 100 : state.preview.zoom) + 10));
  $('#btnZoomOut').addEventListener('click', () => setZoom((state.preview.fit ? 100 : state.preview.zoom) - 10));
  $('#btnZoomReset').addEventListener('click', () => setZoom(100));
  dom.btnFitWidth.addEventListener('click', setFitWidth);
  $('#btnRefreshPreview').addEventListener('click', () => runPreview());
  dom.previewScroll.addEventListener('wheel', (event) => {
    if (!event.ctrlKey) return;
    event.preventDefault();
    setZoom((state.preview.fit ? 100 : state.preview.zoom) + (event.deltaY < 0 ? 10 : -10));
  }, { passive: false });
  dom.btnWarnings.addEventListener('click', () => {
    dom.previewWarnings.hidden = !dom.previewWarnings.hidden;
  });

  // Batch dialog
  dom.batchFiles.addEventListener('change', () => handleBatchFiles(dom.batchFiles.files));
  const dropZone = $('#batchDrop');
  dropZone.addEventListener('dragover', (event) => { event.preventDefault(); dropZone.classList.add('dragover'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone.addEventListener('drop', (event) => {
    event.preventDefault();
    dropZone.classList.remove('dragover');
    handleBatchFiles(event.dataTransfer.files);
  });
  dom.btnRunBatch.addEventListener('click', runBatch);

  // Logs dialog
  $('#btnClearLogs').addEventListener('click', async () => {
    const ok = await openConfirm({ title: 'Svuotare i log?', message: 'La cronologia delle conversioni verrà eliminata.', confirmText: 'Svuota' });
    if (!ok) return;
    try {
      await api('/api/logs', { method: 'DELETE' });
      await refreshLogs();
      toast('success', 'Log svuotati');
    } catch (error) {
      toastError(error);
    }
  });

  // Dialog close buttons and backdrop
  $$('[data-close-dialog]').forEach((button) => {
    button.addEventListener('click', () => closeDialog(button.dataset.closeDialog));
  });
  $$('dialog').forEach((dialog) => {
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  // Drag & drop documents anywhere
  let dragDepth = 0;
  window.addEventListener('dragenter', (event) => {
    if (!Array.from(event.dataTransfer?.types || []).includes('Files')) return;
    dragDepth += 1;
    document.body.classList.add('dragging');
  });
  window.addEventListener('dragleave', () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) document.body.classList.remove('dragging');
  });
  window.addEventListener('dragover', (event) => {
    if (Array.from(event.dataTransfer?.types || []).includes('Files')) event.preventDefault();
  });
  window.addEventListener('drop', (event) => {
    if (!event.dataTransfer?.files?.length) return;
    if (event.target.closest('#batchDrop')) return;
    event.preventDefault();
    dragDepth = 0;
    document.body.classList.remove('dragging');
    openFiles(event.dataTransfer.files);
  });

  // Splitter
  let dragging = false;
  dom.splitter.addEventListener('pointerdown', (event) => {
    if (window.innerWidth <= 980) return;
    dragging = true;
    document.body.classList.add('resizing');
    dom.splitter.setPointerCapture?.(event.pointerId);
  });
  window.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    const rect = dom.workspace.getBoundingClientRect();
    const percent = ((event.clientX - rect.left) / rect.width) * 100;
    const clamped = Math.min(72, Math.max(26, percent));
    document.documentElement.style.setProperty('--editor-width', `${clamped}%`);
  });
  window.addEventListener('pointerup', () => {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove('resizing');
    try { localStorage.setItem('md2pdf.editorWidth', document.documentElement.style.getPropertyValue('--editor-width')); } catch (error) { /* noop */ }
    clearTimeout(state.resizeTimer);
    state.resizeTimer = setTimeout(() => { if (state.preview.fit) rerenderForZoom(); }, 180);
  });
  dom.splitter.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const rect = dom.workspace.getBoundingClientRect();
    const current = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--editor-width')) || 50;
    const next = Math.min(72, Math.max(26, current + (event.key === 'ArrowRight' ? 2 : -2)));
    document.documentElement.style.setProperty('--editor-width', `${next}%`);
    clearTimeout(state.resizeTimer);
    state.resizeTimer = setTimeout(() => { if (state.preview.fit) rerenderForZoom(); }, 180);
  });

  window.addEventListener('resize', () => {
    clearTimeout(state.resizeTimer);
    state.resizeTimer = setTimeout(() => {
      resizeEditor();
      if (state.preview.fit) rerenderForZoom();
    }, 200);
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.settingsOpen) {
      setSettingsOpen(false);
      return;
    }
    if (!(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLowerCase();
    if (key === 's') { event.preventDefault(); saveCurrent(); }
    else if (key === 'e') { event.preventDefault(); exportPdf(); }
    else if (key === 'p') { event.preventDefault(); runPreview(); }
    else if (key === 'o') { event.preventDefault(); dom.fileInput.click(); }
    else if (key === 'n') { event.preventDefault(); dom.btnNew.click(); }
    else if (key === ',') { event.preventDefault(); setSettingsOpen(!state.settingsOpen); }
    else if (key === '+' || key === '=') { event.preventDefault(); setZoom((state.preview.fit ? 100 : state.preview.zoom) + 10); }
    else if (key === '-') { event.preventDefault(); setZoom((state.preview.fit ? 100 : state.preview.zoom) - 10); }
  });

  // Warn before losing unsaved work.
  window.addEventListener('beforeunload', (event) => {
    if (state.tabs.some((tab) => tab.dirty)) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
}

async function boot() {
  try {
    const savedWidth = localStorage.getItem('md2pdf.editorWidth');
    if (savedWidth) document.documentElement.style.setProperty('--editor-width', savedWidth);
    await loadConfig();
    bindEvents();
    await restoreDocuments();
    dom.btnFitWidth.classList.add('active');
    dom.zoomLabel.textContent = 'Auto';
    state.ready = true;
    window.__studio.ready = true;
    schedulePreview(80);
    saveTabsLocal();
  } catch (error) {
    console.warn('Avvio non riuscito', error);
    toast('error', 'Avvio non riuscito', error.message || String(error), { timeout: 0 });
  }
}

boot();
