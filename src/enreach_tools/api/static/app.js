(() => {
  // Grid with virtual scrolling, column reorder, filters, and global search
  const API_BASE = ""; // same origin

  // Elements
  const $tabs = document.getElementById("tabs");
  const $q = document.getElementById("q");
  const $reload = document.getElementById("reload");
  const $updateBtn = document.getElementById("updateBtn");
  const $summary = document.getElementById("summary");
  const $hideBtn = document.getElementById("hideBtn");
  const $fieldsPanel = document.getElementById("fields-panel");
  const $fieldsSearch = document.getElementById("fields-search");
  const $fieldsList = document.getElementById("fields-list");
  const $hideAll = document.getElementById("hide-all");
  const $showAll = document.getElementById("show-all");
  const $fieldsCollapse = document.getElementById("fields-collapse");
  const $progressPanel = document.getElementById("progress-panel");
  const $progressClose = document.getElementById("progress-close");
  const $progressLog = document.getElementById("progress-log");
  const $density = document.getElementById("density");
  const $downloadCsv = document.getElementById("downloadCsv");
  const $headerScroll = document.getElementById("header-scroll");
  const $headerRow = document.getElementById("header-row");
  const $filterRow = document.getElementById("filter-row");
  const $headerRows = document.querySelector("#header-scroll .header-rows");
  const $body = document.getElementById("body");
  const $bodyScroll = document.getElementById("body-scroll");
  const $canvas = document.getElementById("canvas");
  const $rows = document.getElementById("rows");

  // State
  let rows = [];
  let view = [];
  let columns = [];
  let colWidths = [];
  let colFilters = {}; // per column string
  let colVisible = {}; // column -> boolean (default true)
  // Sorting (multi-sort)
  // Array of { key: string, dir: 'asc'|'desc' }
  let sortRules = [];
  let dataset = "devices";
  let dragSrcIndex = -1; // global src index for DnD across headers
  // Density
  const ROW_COMFORT = 36;
  const ROW_COMPACT = 28;
  let rowHeight = ROW_COMFORT;

  // Virtualization
  const OVERSCAN = 6; // rows
  let viewportHeight = 0;
  let totalHeight = 0;
  let startIndex = 0;
  let endIndex = 0;
  let raf = null;

  // Persist keys
  const keyCols = (ds) => `airtbl_cols_${ds}`;
  const keyWidths = (ds) => `airtbl_colw_${ds}`;
  const keyFilters = (ds) => `airtbl_filt_${ds}`;
  const keyVisible = (ds) => `airtbl_vis_${ds}`;
  const keyDensity = () => `airtbl_density`;

  // Utils
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const debounce = (fn, ms = 150) => {
    let t = 0;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  };
  const naturalCmp = (a, b) => {
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    const na = Number(a), nb = Number(b);
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
    return String(a).localeCompare(String(b), undefined, { sensitivity: "base", numeric: true });
  };

  // Layout helpers
  function getVisibleColumns() {
    const vis = [];
    for (const c of columns) {
      if (colVisible[c] === false) continue;
      vis.push(c);
    }
    // ensure at least one column visible
    if (vis.length === 0 && columns.length) vis.push(columns[0]);
    return vis;
  }

  let contentWidth = 0; // sum of visible column widths
  let gridTemplate = '';
  function updateTemplates() {
    // Fixed column widths so header and body align; default width 180px
    if (colWidths.length !== columns.length) {
      colWidths = columns.map((_, i) => colWidths[i] || 180);
    }
    const vis = getVisibleColumns();
    const tpl = vis.map((c) => {
      const idx = columns.indexOf(c);
      const w = colWidths[idx] || 180;
      return `${Math.max(80, Math.floor(w))}px`;
    }).join(" ");
    gridTemplate = tpl;
    $headerRow.style.gridTemplateColumns = tpl;
    $filterRow.style.gridTemplateColumns = tpl;
    // Horizontal size for scrollers
    contentWidth = vis.reduce((a, c) => a + (colWidths[columns.indexOf(c)] || 180), 0);
    $canvas.style.width = `${contentWidth}px`;
    $rows.style.width = `${contentWidth}px`;
    if ($headerRows) $headerRows.style.width = `${contentWidth}px`;
  }

  function computeView() {
    // Global quick search
    const q = ($q.value || "").trim().toLowerCase();
    const hasQ = q.length > 0;
    // Column filters
    const activeCols = Object.entries(colFilters).filter(([_, v]) => (v || "").trim() !== "");

    view = rows.filter((r) => {
      for (const [col, val] of activeCols) {
        const needle = String(val).toLowerCase();
        const hay = r[col] == null ? "" : String(r[col]).toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      if (!hasQ) return true;
      for (const k in r) {
        const v = r[k];
        if (v != null && String(v).toLowerCase().includes(q)) return true;
      }
      return false;
    });
    // Multi-sort across visible columns
    const effective = sortRules.filter(r => colVisible[r.key] !== false);
    if (effective.length) {
      view.sort((a, b) => {
        for (const r of effective) {
          const c = naturalCmp(a[r.key], b[r.key]);
          if (c !== 0) return r.dir === 'asc' ? c : -c;
        }
        return 0;
      });
    }
    totalHeight = view.length * rowHeight;
    $canvas.style.height = `${totalHeight}px`;
    updateSummary();
  }

  function updateSummary() {
    const sortTxt = sortRules.length ?
      ` • sort: ` + sortRules.map(r => `${r.key} (${r.dir})`).join(", ") : '';
    $summary.textContent = `${view.length} of ${rows.length} rows` + sortTxt;
  }

  // Rendering
  function renderHeader() {
    $headerRow.innerHTML = "";
    const vis = getVisibleColumns();
    vis.forEach((col) => {
      const i = columns.indexOf(col);
      const el = document.createElement("div");
      el.className = "col";
      if (vis[0] === col) el.classList.add('pinned');
      el.draggable = true;
      el.dataset.index = String(i);
      el.dataset.key = col;
      const label = document.createElement("div");
      label.className = "label sort";
      const dot = document.createElement("span");
      dot.className = "handle";
      label.appendChild(dot);
      const text = document.createElement("span");
      text.textContent = col;
      label.appendChild(text);
      el.appendChild(label);
      // Resizer handle
      const res = document.createElement('div');
      res.className = 'resizer';
      let startX = 0, startW = 0, moving = false;
      const onMove = (e) => {
        const dx = (e.clientX || 0) - startX;
        const w = clamp(startW + dx, 80, 640);
        colWidths[i] = w;
        document.body.classList.add('resizing');
        updateTemplates();
        renderVisible();
      };
      const onUp = () => {
        if (moving) {
          moving = false;
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
          document.body.classList.remove('resizing');
          persistWidths();
        }
      };
      res.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();
        startX = e.clientX || 0;
        startW = colWidths[i] || 180;
        moving = true;
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp, { once: true });
      });
      el.appendChild(res);
      const sr = sortRules.find(r => r.key === col);
      if (sr) el.classList.add(sr.dir === "asc" ? "sort-asc" : "sort-desc");
      // Sort toggle
      el.addEventListener("click", (ev) => {
        if (ev.detail === 0) return; // avoid synthetic
        const shift = ev.shiftKey;
        const idx = sortRules.findIndex(r => r.key === col);
        if (!shift) {
          if (idx === 0) {
            // toggle primary
            sortRules[0].dir = sortRules[0].dir === 'asc' ? 'desc' : 'asc';
          } else {
            sortRules = [{ key: col, dir: 'asc' }];
          }
        } else {
          if (idx === -1) sortRules.push({ key: col, dir: 'asc' });
          else sortRules[idx].dir = sortRules[idx].dir === 'asc' ? 'desc' : 'asc';
        }
        computeView();
        renderVisible();
        renderHeader();
        updateURLDebounced();
      });
      // Drag & drop reorder
      el.addEventListener("dragstart", (e) => {
        dragSrcIndex = i;
        el.classList.add("dragging");
        try {
          e.dataTransfer?.setData("text/plain", String(i));
          if (e.dataTransfer) {
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.dropEffect = "move";
          }
        } catch {}
        e.dataTransfer?.setDragImage(el, 10, 10);
      });
      el.addEventListener("dragend", () => {
        el.classList.remove("dragging");
        dragSrcIndex = -1;
      });
      el.addEventListener("dragover", (e) => {
        e.preventDefault();
        const rect = el.getBoundingClientRect();
        const mid = rect.left + rect.width / 2;
        el.classList.toggle("drop-left", e.clientX < mid);
        el.classList.toggle("drop-right", e.clientX >= mid);
      });
      el.addEventListener("dragleave", () => {
        el.classList.remove("drop-left", "drop-right");
      });
      el.addEventListener("drop", (e) => {
        e.preventDefault();
        el.classList.remove("drop-left", "drop-right");
        const src = dragSrcIndex;
        const target = i;
        if (src === -1 || target === -1 || src === target) return;
        const rect = el.getBoundingClientRect();
        const insertLeft = e.clientX < rect.left + rect.width / 2;
        // Compute new order
        const arr = columns.slice();
        const widths = colWidths.slice();
        const [moved] = arr.splice(src, 1);
        const [movedW] = widths.splice(src, 1);
        const insertAt = src < target ? (insertLeft ? target - 1 : target) : (insertLeft ? target : target + 1);
        const pos = clamp(insertAt, 0, arr.length);
        arr.splice(pos, 0, moved);
        widths.splice(pos, 0, movedW);
        columns = arr;
        colWidths = widths;
        persistColumns();
        persistWidths();
        renderHeader();
        renderFilters();
        updateTemplates();
        renderVisible();
        updateURLDebounced();
      });
      $headerRow.appendChild(el);
    });
  }

  function renderFilters() {
    $filterRow.innerHTML = "";
    const vis = getVisibleColumns();
    vis.forEach((col, i) => {
      const wrap = document.createElement("div");
      wrap.className = "col";
      if (i === 0) wrap.classList.add('pinned');
      const input = document.createElement("input");
      input.className = "filter";
      input.type = "text";
      input.placeholder = "filter";
      input.value = colFilters[col] || "";
      input.addEventListener("input", debounce(() => {
        colFilters[col] = input.value;
        persistFilters();
        computeView();
        renderVisible();
        updateURLDebounced();
      }, 180));
      wrap.appendChild(input);
      $filterRow.appendChild(wrap);
    });
  }

  function renderVisible() {
    if (!view.length) {
      $rows.innerHTML = '';
      $rows.style.top = `0px`;
      return;
    }
    const scrollTop = $bodyScroll.scrollTop | 0;
    startIndex = clamp(Math.floor(scrollTop / rowHeight) - OVERSCAN, 0, Math.max(0, view.length - 1));
    const visibleCount = Math.ceil(viewportHeight / rowHeight) + OVERSCAN * 2;
    endIndex = clamp(startIndex + visibleCount, startIndex, view.length);

    // Position rows container
    const offsetY = startIndex * rowHeight;
    $rows.style.top = `${offsetY}px`;

    // Build rows
    const frag = document.createDocumentFragment();
    const vis = getVisibleColumns();
    for (let i = startIndex; i < endIndex; i++) {
      const r = view[i];
      const rowEl = document.createElement("div");
      rowEl.className = "row";
      rowEl.style.height = `${rowHeight - 1}px`;
      rowEl.style.display = 'grid';
      rowEl.style.gridTemplateColumns = gridTemplate;
      rowEl.style.width = `${contentWidth}px`;
      vis.forEach((col, ci) => {
        const cell = document.createElement("div");
        cell.className = "cell";
        if (ci === 0) cell.classList.add('pinned');
        const v = r[col];
        cell.textContent = v == null ? "" : String(v);
        cell.title = cell.textContent;
        rowEl.appendChild(cell);
      });
      frag.appendChild(rowEl);
    }
    $rows.innerHTML = '';
    $rows.appendChild(frag);
  }

  // Scrolling & resize
  let syncing = false;
  $bodyScroll.addEventListener('scroll', () => {
    if (!syncing) {
      syncing = true;
      // Sync header's scrollLeft to body (header scrollbar hidden via CSS)
      if ($headerScroll) $headerScroll.scrollLeft = $bodyScroll.scrollLeft;
      if (!raf) raf = requestAnimationFrame(() => { raf = null; renderVisible(); });
      syncing = false;
    }
  });
  // Keep header and body scroll in sync when user drags the header area (rare)
  $headerScroll.addEventListener('scroll', () => {
    if (!syncing) {
      syncing = true;
      if ($bodyScroll) $bodyScroll.scrollLeft = $headerScroll.scrollLeft;
      syncing = false;
    }
  });

  const resizeObs = new ResizeObserver(() => {
    viewportHeight = $bodyScroll.clientHeight;
    updateTemplates();
    computeView();
    renderVisible();
  });
  resizeObs.observe($body);

  // Density select
  function applyDensity(val) {
    if (val === 'compact') rowHeight = ROW_COMPACT; else rowHeight = ROW_COMFORT;
    try { localStorage.setItem(keyDensity(), rowHeight === ROW_COMPACT ? 'compact' : 'comfortable'); } catch {}
    computeView();
    renderVisible();
    updateURLDebounced();
  }
  if ($density) {
    // Load saved density
    try { const d = localStorage.getItem(keyDensity()); if (d) { $density.value = d; applyDensity(d); } } catch {}
    $density.addEventListener('change', () => applyDensity($density.value));
  }

  // Persistence
  function persistColumns() {
    try { localStorage.setItem(keyCols(dataset), JSON.stringify(columns)); } catch {}
  }
  function persistWidths() {
    try {
      const map = {};
      for (let i = 0; i < columns.length; i++) map[columns[i]] = colWidths[i];
      localStorage.setItem(keyWidths(dataset), JSON.stringify(map));
    } catch {}
  }
  function loadColumns(headers) {
    try {
      const raw = localStorage.getItem(keyCols(dataset));
      if (!raw) return headers.slice();
      const arr = JSON.parse(raw);
      const set = new Set(headers);
      return Array.isArray(arr) ? arr.filter((c) => set.has(c)) : headers.slice();
    } catch { return headers.slice(); }
  }
  function loadWidths() {
    try {
      const raw = localStorage.getItem(keyWidths(dataset));
      if (!raw) return {};
      const obj = JSON.parse(raw);
      return obj && typeof obj === 'object' ? obj : {};
    } catch { return {}; }
  }
  function persistFilters() {
    try { localStorage.setItem(keyFilters(dataset), JSON.stringify(colFilters)); } catch {}
  }
  function persistVisible() {
    try { localStorage.setItem(keyVisible(dataset), JSON.stringify(colVisible)); } catch {}
  }
  function loadFilters() {
    try {
      const raw = localStorage.getItem(keyFilters(dataset));
      if (!raw) return {};
      const obj = JSON.parse(raw);
      return obj && typeof obj === 'object' ? obj : {};
    } catch { return {}; }
  }

  // Shareable view via URL (?view=...)
  function serializeView() {
    const state = {
      ds: dataset,
      columns,
      visible: Object.fromEntries(columns.map(c => [c, colVisible[c] !== false])),
      filters: colFilters,
      sort: sortRules,
      density: rowHeight === ROW_COMPACT ? 'compact' : 'comfortable',
    };
    return encodeURIComponent(JSON.stringify(state));
  }
  function applyViewState(state) {
    try {
      if (!state || typeof state !== 'object') return;
      if (state.ds && typeof state.ds === 'string') dataset = state.ds;
      if (Array.isArray(state.columns)) {
        const set = new Set(columns);
        const ordered = state.columns.filter(c => set.has(c));
        const rest = columns.filter(c => !ordered.includes(c));
        columns = ordered.concat(rest);
      }
      if (state.visible && typeof state.visible === 'object') {
        colVisible = {};
        for (const c of columns) colVisible[c] = state.visible[c] !== false;
      }
      if (state.filters && typeof state.filters === 'object') {
        colFilters = {};
        for (const c in state.filters) if (columns.includes(c)) colFilters[c] = state.filters[c];
      }
      if (Array.isArray(state.sort)) {
        sortRules = state.sort.filter(s => s && typeof s.key === 'string' && (s.dir === 'asc' || s.dir === 'desc'));
      }
      if (state.density === 'compact') rowHeight = ROW_COMPACT; else if (state.density === 'comfortable') rowHeight = ROW_COMFORT;
    } catch {}
  }
  const updateURLDebounced = debounce(() => {
    try {
      const url = new URL(window.location.href);
      url.searchParams.set('view', serializeView());
      history.replaceState(null, '', url.toString());
    } catch {}
  }, 250);

  // Data
  async function fetchData() {
    // dataset already set by tab click
    $summary.textContent = 'Loading…';
    try {
      // optional: get column order hint from backend
      let preferred = [];
      try {
        const or = await fetch(`${API_BASE}/column-order`);
        if (or.ok) preferred = await or.json();
      } catch {}

      const url = `${API_BASE}/${dataset === 'all' ? 'all' : dataset}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const data = await res.json();
      rows = Array.isArray(data) ? data : [];
      const headers = rows.length ? Object.keys(rows[0]) : [];
      // Column order: prefer saved, else preferred, else natural
      let saved = loadColumns(headers);
      if (preferred && preferred.length) {
        const orderIdx = new Map(preferred.map((h, i) => [h, i]));
        columns = saved.slice().sort((a, b) => (orderIdx.get(a) ?? 1e9) - (orderIdx.get(b) ?? 1e9));
      } else {
        columns = saved;
      }
      colFilters = loadFilters();
      // Visibility: default all true; keep only known headers
      try {
        const raw = localStorage.getItem(keyVisible(dataset));
        const vis = raw ? JSON.parse(raw) : {};
        colVisible = {};
        for (const c of columns) {
          colVisible[c] = vis[c] !== false; // default true
        }
      } catch { colVisible = Object.fromEntries(columns.map((c) => [c, true])); }
      // Reset sort when dataset changes
      sortRules = [];
      // Initialize widths (use saved mapping where available)
      const savedW = loadWidths();
      colWidths = columns.map((c) => {
        const w = Number(savedW[c]);
        return Number.isFinite(w) ? clamp(w, 80, 640) : 180;
      });

      // Render skeleton
      updateTemplates();
      // Apply view from URL once (if provided)
      if (!window.__appliedViewFromURL) {
        try {
          const p = new URL(window.location.href).searchParams.get('view');
          if (p) {
            const st = JSON.parse(decodeURIComponent(p));
            applyViewState(st);
            // Update active tab UI to reflect dataset from URL
            if ($tabs) {
              $tabs.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-ds') === dataset));
            }
            if ($density) $density.value = (rowHeight === ROW_COMPACT ? 'compact' : 'comfortable');
          }
        } catch {}
        window.__appliedViewFromURL = true;
      }
      renderHeader();
      renderFilters();
      computeView();
      // Scroll to top
      $bodyScroll.scrollTop = 0;
      renderVisible();
      if (!rows.length) {
        $rows.innerHTML = `<div class="empty">No data found.</div>`;
      }
      updateURLDebounced();
    } catch (e) {
      console.error(e);
      $summary.textContent = `Error loading data: ${e.message || e}`;
      rows = []; view = []; columns = []; colFilters = {}; sortRules = [];
      $headerRow.innerHTML = '';
      $filterRow.innerHTML = '';
      $rows.innerHTML = `<div class="empty">Could not load data.</div>`;
    }
  }

  // Events
  $reload.addEventListener('click', () => { fetchData(); updateURLDebounced(); });
  $q.addEventListener('input', debounce(() => { computeView(); renderVisible(); }, 160));
  $q.addEventListener('input', updateURLDebounced);

  // Stream export logs to the progress panel
  async function runExportFor(ds) {
    const url = `${API_BASE}/export/stream?dataset=${encodeURIComponent(ds === 'all' ? 'all' : ds)}`;
    if ($progressPanel && $progressLog) {
      $progressLog.textContent = '';
      $progressPanel.hidden = false;
    }
    if ($updateBtn) $updateBtn.disabled = true;
    let ok = true;
    let logText = '';
    try {
      const res = await fetch(url, { method: 'GET' });
      if (!res.ok || !res.body) throw new Error(`${res.status} ${res.statusText}`);
      const reader = res.body.getReader();
      const td = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if ($progressLog) {
          const chunk = td.decode(value, { stream: true });
          $progressLog.textContent += chunk;
          logText += chunk;
          $progressLog.scrollTop = $progressLog.scrollHeight;
        }
      }
      // Check exit code footer like "[exit 1]"
      const m = /\[exit\s+(\d+)\]/.exec(logText);
      if (m && Number(m[1]) !== 0) ok = false;
    } catch (e) {
      ok = false;
      if ($progressLog) $progressLog.textContent += `\n[error] ${e && e.message ? e.message : e}\n`;
    } finally {
      if ($updateBtn) $updateBtn.disabled = false;
      if (ok) {
        await fetchData();
        if ($progressPanel) $progressPanel.hidden = true;
      } else {
        // Keep the panel open so the user can read errors
        if ($progressLog) $progressLog.scrollTop = $progressLog.scrollHeight;
      }
    }
  }
  $updateBtn?.addEventListener('click', async () => {
    const label = dataset === 'all' ? 'All (merge)' : (dataset.charAt(0).toUpperCase() + dataset.slice(1));
    if (!confirm(`Run export for "${label}" now?`)) return;
    await runExportFor(dataset);
  });
  $progressClose?.addEventListener('click', () => { if ($progressPanel) $progressPanel.hidden = true; });

  // Download CSV of filtered view
  function toCsvValue(v) {
    if (v == null) return '';
    const s = String(v);
    if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  }
  $downloadCsv?.addEventListener('click', () => {
    const vis = getVisibleColumns();
    const lines = [];
    lines.push(vis.map(toCsvValue).join(','));
    for (const r of view) {
      lines.push(vis.map(c => toCsvValue(r[c])).join(','));
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    const ts = new Date().toISOString().replace(/[:T]/g, '-').slice(0,19);
    a.download = `${dataset || 'data'}_filtered_${ts}.csv`;
    a.href = URL.createObjectURL(blob);
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  });

  // Tabs: dataset switch
  $tabs?.addEventListener('click', (e) => {
    const btn = e.target.closest('.tab');
    if (!btn) return;
    const ds = btn.getAttribute('data-ds');
    if (!ds || ds === dataset) return;
    dataset = ds;
    // Active state
    $tabs.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t === btn));
    fetchData();
    updateURLDebounced();
  });

  // Hide fields panel
  function rebuildFieldsPanel() {
    $fieldsList.innerHTML = '';
    const q = ($fieldsSearch.value || '').toLowerCase();
    const frag = document.createDocumentFragment();
    for (const c of columns) {
      if (q && !c.toLowerCase().includes(q)) continue;
      const item = document.createElement('div');
      item.className = 'field-item';
      const tog = document.createElement('button');
      tog.type = 'button';
      tog.className = 'toggle' + (colVisible[c] === false ? '' : ' on');
      tog.setAttribute('role', 'switch');
      tog.setAttribute('aria-checked', colVisible[c] === false ? 'false' : 'true');
      tog.setAttribute('aria-label', `Toggle visibility for ${c}`);
      const pinnedFirst = getVisibleColumns()[0];
      const isPinned = pinnedFirst === c;
      if (isPinned && (colVisible[c] !== false)) {
        tog.setAttribute('aria-disabled', 'true');
      }
      tog.addEventListener('click', () => {
        if (tog.getAttribute('aria-disabled') === 'true') return;
        const newState = !(colVisible[c] !== false);
        colVisible[c] = newState;
        // Ensure at least one visible
        const vis = getVisibleColumns();
        if (vis.length === 0) { colVisible[c] = true; return; }
        persistVisible();
        updateTemplates();
        renderHeader();
        renderFilters();
        computeView();
        renderVisible();
        tog.setAttribute('aria-checked', colVisible[c] === false ? 'false' : 'true');
        rebuildFieldsPanel();
        updateURLDebounced();
      });
      const name = document.createElement('div');
      name.className = 'field-name';
      name.textContent = c;
      item.appendChild(tog);
      item.appendChild(name);
      frag.appendChild(item);
    }
    $fieldsList.appendChild(frag);
    refreshToggleList();
  }
  // Keyboard navigation within fields panel
  let toggleNodes = [];
  function refreshToggleList() {
    toggleNodes = Array.from($fieldsList.querySelectorAll('button.toggle'));
  }
  function focusToggleAt(i) {
    if (!toggleNodes.length) return;
    const idx = Math.max(0, Math.min(toggleNodes.length - 1, i));
    const node = toggleNodes[idx];
    node.focus();
  }
  function currentToggleIndex() {
    const active = document.activeElement;
    return toggleNodes.findIndex((n) => n === active);
  }
  $fieldsPanel?.addEventListener('keydown', (e) => {
    if ($fieldsPanel.hidden) return;
    // Allow Esc to close (handled below)
    if (['ArrowDown','ArrowUp','ArrowLeft','ArrowRight','Home','End','PageDown','PageUp'].includes(e.key)) e.preventDefault();
    const idx = currentToggleIndex();
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
      focusToggleAt((idx === -1 ? 0 : idx + 1));
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
      focusToggleAt((idx === -1 ? 0 : idx - 1));
    } else if (e.key === 'Home') {
      focusToggleAt(0);
    } else if (e.key === 'End') {
      focusToggleAt(toggleNodes.length - 1);
    } else if (e.key === 'PageDown') {
      focusToggleAt((idx === -1 ? 0 : idx + 10));
    } else if (e.key === 'PageUp') {
      focusToggleAt((idx === -1 ? 0 : idx - 10));
    }
  });
  $hideBtn?.addEventListener('click', () => {
    $fieldsPanel.hidden = !$fieldsPanel.hidden;
    if (!$fieldsPanel.hidden) {
      $fieldsSearch.value = '';
      rebuildFieldsPanel();
      setTimeout(() => $fieldsSearch?.focus(), 0);
    }
  });
  $fieldsCollapse?.addEventListener('click', () => { $fieldsPanel.hidden = true; });
  $fieldsSearch?.addEventListener('input', () => rebuildFieldsPanel());
  $hideAll?.addEventListener('click', () => {
    const visCols = getVisibleColumns();
    const keep = visCols[0] || columns[0]; // keep at least first
    for (const c of columns) colVisible[c] = false;
    if (keep) colVisible[keep] = true;
    persistVisible();
    updateTemplates(); renderHeader(); renderFilters(); computeView(); renderVisible(); rebuildFieldsPanel(); updateURLDebounced();
  });
  $showAll?.addEventListener('click', () => {
    for (const c of columns) colVisible[c] = true;
    persistVisible();
    updateTemplates(); renderHeader(); renderFilters(); computeView(); renderVisible(); rebuildFieldsPanel(); updateURLDebounced();
  });
  // Utility: detect if event occurred inside element, resilient to re-render
  function eventWithin(el, e) {
    if (!el) return false;
    const path = e.composedPath ? e.composedPath() : null;
    if (path && Array.isArray(path)) return path.includes(el);
    return el.contains(e.target);
  }
  document.addEventListener('click', (e) => {
    if ($fieldsPanel.hidden) return;
    const withinPanel = eventWithin($fieldsPanel, e);
    const onToggleBtn = eventWithin($hideBtn, e);
    if (!withinPanel && !onToggleBtn) $fieldsPanel.hidden = true;
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$fieldsPanel.hidden) {
      e.preventDefault();
      $fieldsPanel.hidden = true;
    }
  });

  // Init
  // Ensure fields panel is closed on load
  if ($fieldsPanel) $fieldsPanel.hidden = true;
  // Read dataset from URL view before first fetch
  try {
    const p = new URL(window.location.href).searchParams.get('view');
    if (p) {
      const st = JSON.parse(decodeURIComponent(p));
      if (st && typeof st === 'object' && typeof st.ds === 'string') dataset = st.ds;
    }
  } catch {}
  // Set initial tab active
  $tabs?.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-ds') === dataset));
  fetchData();

  // Keyboard hotkeys
  function isTypingTarget(el) {
    return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);
  }
  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented) return;
    const tgt = e.target;
    if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      if (!isTypingTarget(tgt)) {
        e.preventDefault();
        $q?.focus();
      }
    } else if ((e.key === 'h' || e.key === 'H') && !e.ctrlKey && !e.metaKey && !e.altKey) {
      if (!isTypingTarget(tgt)) {
        e.preventDefault();
        $hideBtn?.click();
      }
    } else if ((e.key === 'r' || e.key === 'R') && !e.ctrlKey && !e.metaKey && !e.altKey) {
      if (!isTypingTarget(tgt)) {
        e.preventDefault();
        fetchData();
      }
    }
  });
})();
