(() => {
  // Grid with virtual scrolling, column reorder, filters, and global search
  const API_BASE = ""; // same origin

  // Elements
  // Page router
  const $pages = document.getElementById("pages");
  const $pageNetbox = document.getElementById("page-netbox");
  const $pageChat = document.getElementById("page-chat");
  const $pageZabbix = document.getElementById("page-zabbix");
  const $pageZhost = document.getElementById("page-zhost");
  const $pageJira = document.getElementById("page-jira");
  const $pageConfluence = document.getElementById("page-confluence");
  // Dataset tabs (inside NetBox page)
  const $dsTabs = document.getElementById("ds-tabs");
  const $q = document.getElementById("q");
  const $reload = document.getElementById("reload");
  const $updateBtn = document.getElementById("updateBtn");
  const $viewLogs = document.getElementById("viewLogs");
  const $summary = document.getElementById("summary");
  const $hideBtn = document.getElementById("hideBtn");
  const $resetFilters = document.getElementById("resetFilters");
  const $fieldsPanel = document.getElementById("fields-panel");
  const $fieldsSearch = document.getElementById("fields-search");
  const $fieldsList = document.getElementById("fields-list");
  const $hideAll = document.getElementById("hide-all");
  const $showAll = document.getElementById("show-all");
  const $fieldsCollapse = document.getElementById("fields-collapse");
  const $progressPanel = document.getElementById("progress-panel");
  const $progressClose = document.getElementById("progress-close");
  const $progressLog = document.getElementById("progress-log");
  const $resizeSE = document.getElementById("resize-se");
  const $resizeSW = document.getElementById("resize-sw");
  // Log autoscroll behavior: follow bottom unless user scrolls up
  let followTail = true;
  function atBottom(el, threshold = 24) {
    if (!el) return true;
    return (el.scrollHeight - el.scrollTop - el.clientHeight) <= threshold;
  }
  $progressLog?.addEventListener('scroll', () => {
    if (!$progressLog) return;
    // If user is near the bottom, keep following; otherwise pause follow
    followTail = atBottom($progressLog);
  });
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
  let page = 'netbox';
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
      if (!Array.isArray(arr)) return headers.slice();
      const set = new Set(headers);
      const ordered = arr.filter((c) => set.has(c));
      const rest = headers.filter((c) => !ordered.includes(c));
      // Append any new headers not present in the saved order
      return ordered.concat(rest);
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
            // Update active dataset tab UI to reflect dataset from URL
            if ($dsTabs) {
              $dsTabs.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-ds') === dataset));
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

  // Reset all column filters (does not clear global Search)
  $resetFilters?.addEventListener('click', () => {
    colFilters = {};
    persistFilters();
    renderFilters();
    computeView();
    renderVisible();
    updateURLDebounced();
  });

  // Logs panel polling helpers
  let logPollTimer = null;
  function stopLogPolling() {
    if (logPollTimer) { clearInterval(logPollTimer); logPollTimer = null; }
  }
  async function fetchLogsOnce(n = 300) {
    try {
      const res = await fetch(`${API_BASE}/logs/tail?n=${n}`);
      if (!res.ok) return;
      const data = await res.json();
      const lines = (data && Array.isArray(data.lines)) ? data.lines : [];
      if ($progressLog) {
        $progressLog.textContent = lines.join('\n');
        if (followTail) $progressLog.scrollTop = $progressLog.scrollHeight;
      }
    } catch {}
  }
  function startLogPolling(n = 300, intervalMs = 1200) {
    stopLogPolling();
    fetchLogsOnce(n);
    logPollTimer = setInterval(() => fetchLogsOnce(n), intervalMs);
  }

  // Stream export logs to the progress panel
  async function runExportFor(ds) {
    // New stream: default to following the tail
    followTail = true;
    stopLogPolling();
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
          if (followTail) $progressLog.scrollTop = $progressLog.scrollHeight;
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
        // Begin polling recent logs after a short pause
        setTimeout(() => startLogPolling(300, 1500), 600);
      }
    }
  }
  $updateBtn?.addEventListener('click', async () => {
    const label = dataset === 'all' ? 'All (merge)' : (dataset.charAt(0).toUpperCase() + dataset.slice(1));
    if (!confirm(`Run export for "${label}" now?`)) return;
    await runExportFor(dataset);
  });
  $progressClose?.addEventListener('click', () => { if ($progressPanel) $progressPanel.hidden = true; });

  // View recent logs button
  $viewLogs?.addEventListener('click', () => {
    if ($progressPanel && $progressLog) {
      $progressPanel.hidden = false;
      $progressLog.textContent = '';
      followTail = true;
      startLogPolling(300, 1500);
    }
  });

  // Stop polling when panel is hidden via Esc or programmatically
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$progressPanel.hidden) {
      $progressPanel.hidden = true;
      stopLogPolling();
    }
  });

  // Add manual resize behavior for both corners
  function setupResizeHandle(handle, mode) {
    if (!handle || !$progressPanel) return;
    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      const rect = $progressPanel.getBoundingClientRect();
      const startW = rect.width;
      const startH = rect.height;
      const startX = e.clientX || 0;
      const startY = e.clientY || 0;
      const MIN_W = 320, MIN_H = 180;
      const MAX_W = Math.max(MIN_W, window.innerWidth - 32);
      const MAX_H = Math.max(MIN_H, window.innerHeight - 80);
      const onMove = (ev) => {
        const dx = (ev.clientX || 0) - startX;
        const dy = (ev.clientY || 0) - startY;
        let newW = startW + (mode === 'se' ? dx : -dx);
        let newH = startH + dy;
        newW = Math.min(Math.max(MIN_W, newW), MAX_W);
        newH = Math.min(Math.max(MIN_H, newH), MAX_H);
        $progressPanel.style.width = Math.round(newW) + 'px';
        $progressPanel.style.height = Math.round(newH) + 'px';
        document.body.classList.add('resizing');
      };
      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        document.body.classList.remove('resizing');
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }
  setupResizeHandle($resizeSE, 'se');
  setupResizeHandle($resizeSW, 'sw');

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

  // (replaced) Dataset tab switch handled later via $dsTabs handlers

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

  // Page routing
  function showPage(p) {
    page = p;
    // Toggle page sections
    const map = { netbox: $pageNetbox, chat: $pageChat, zabbix: $pageZabbix, zhost: $pageZhost, jira: $pageJira, confluence: $pageConfluence };
    for (const k of Object.keys(map)) {
      if (!map[k]) continue;
      if (k === p) map[k].removeAttribute('hidden'); else map[k].setAttribute('hidden', '');
    }
    // Toggle tabs
    $pages?.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-page') === p));
    // Update hash
    try {
      const url = new URL(window.location.href);
      url.hash = `#${p}`;
      history.replaceState(null, '', url.toString());
    } catch {}
    // When switching into NetBox, ensure data is loaded/refreshed
    if (p === 'netbox') {
      fetchData();
    } else if (p === 'chat') {
      ensureChatSession();
      loadChatDefaults();
      refreshChatHistory();
    } else if (p === 'zabbix') {
      fetchZabbix();
    } else if (p === 'zhost') {
      // page-specific loader handled via showZabbixHost()
    }
  }
  function parseHashPage() {
    try {
      const h = (window.location.hash || '').replace(/^#/, '').trim().toLowerCase();
      if (["netbox","chat","zabbix","zhost","jira","confluence"].includes(h)) return h;
    } catch {}
    return 'netbox';
  }
  window.addEventListener('hashchange', () => showPage(parseHashPage()));
  // Attach click handlers to each top-level page button (robust against text-node targets)
  if ($pages) {
    const pgBtns = Array.from($pages.querySelectorAll('button.tab'));
    pgBtns.forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const p = btn.getAttribute('data-page') || 'netbox';
        showPage(p);
      });
    });
  }

  // Dataset tab switching (NetBox page)
  if ($dsTabs) {
    const dsBtns = Array.from($dsTabs.querySelectorAll('button.tab'));
    dsBtns.forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const ds = btn.getAttribute('data-ds') || 'devices';
        dataset = ds;
        // Toggle active
        $dsTabs.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-ds') === ds));
        fetchData();
        updateURLDebounced();
      });
    });
  }

  // Chat placeholder
  const $chatProvider = document.getElementById('chat-provider');
  const $chatModel = document.getElementById('chat-model');
  const $chatInput = document.getElementById('chat-input');
  const $chatSend = document.getElementById('chat-send');
  const $chatLog = document.getElementById('chat-log');
  let chatSessionId = null;
  function ensureChatSession() {
    if (chatSessionId) return chatSessionId;
    try { chatSessionId = localStorage.getItem('chat_session_id'); } catch {}
    if (!chatSessionId) {
      // Simple random id
      chatSessionId = 'c_' + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
      try { localStorage.setItem('chat_session_id', chatSessionId); } catch {}
    }
    return chatSessionId;
  }
  function saveChatPrefs() {
    try {
      if ($chatProvider) localStorage.setItem('chat_provider', $chatProvider.value || '');
      if ($chatModel) localStorage.setItem('chat_model', $chatModel.value || '');
      const streamEl = document.getElementById('chat-stream');
      if (streamEl) localStorage.setItem('chat_stream', streamEl.checked ? '1' : '0');
      const ctxEl = document.getElementById('chat-include-data');
      if (ctxEl) localStorage.setItem('chat_include_data', ctxEl.checked ? '1' : '0');
    } catch {}
  }
  function loadChatPrefs() {
    try {
      const prov = localStorage.getItem('chat_provider');
      const model = localStorage.getItem('chat_model');
      if (prov && $chatProvider) $chatProvider.value = prov;
      if (model && $chatModel) $chatModel.value = model;
      const streamEl = document.getElementById('chat-stream');
      const savedStream = localStorage.getItem('chat_stream');
      if (streamEl && savedStream != null) streamEl.checked = savedStream === '1';
      const ctxEl = document.getElementById('chat-include-data');
      const savedCtx = localStorage.getItem('chat_include_data');
      if (ctxEl && savedCtx != null) ctxEl.checked = savedCtx === '1';
    } catch {}
  }
  async function loadChatDefaults() {
    try {
      const res = await fetch(`${API_BASE}/chat/providers`);
      if (!res.ok) return;
      const data = await res.json();
      // Set default provider if none selected
      const dprov = data?.default_provider || 'openai';
      if ($chatProvider && !$chatProvider.value) $chatProvider.value = dprov;
      // If model empty, set default for selected provider
      const sel = $chatProvider?.value || dprov;
      const cfg = (data?.providers || []).find(p => p.id === sel);
      if ($chatModel && !$chatModel.value && cfg && cfg.default_model) $chatModel.value = cfg.default_model;
    } catch {}
  }
  function appendChat(role, text) {
    if (!$chatLog) return;
    const who = role === 'user' ? 'Jij' : 'AI';
    const div = document.createElement('div');
    div.innerHTML = `<strong>${who}:</strong> ${text}`;
    $chatLog.appendChild(div);
    $chatLog.scrollTop = $chatLog.scrollHeight;
  }
  async function refreshChatHistory() {
    const sid = ensureChatSession();
    try {
      const res = await fetch(`${API_BASE}/chat/history?session_id=${encodeURIComponent(sid)}`);
      if (!res.ok) return;
      const data = await res.json();
      const msgs = Array.isArray(data?.messages) ? data.messages : [];
      if ($chatLog) $chatLog.innerHTML = '';
      for (const m of msgs) {
        if (m && typeof m.content === 'string' && typeof m.role === 'string') appendChat(m.role, m.content);
      }
    } catch {}
  }
  async function sendChat() {
    const q = ($chatInput?.value || '').trim();
    if (!q) return;
    appendChat('user', q);
    if ($chatInput) $chatInput.value = '';
    const prov = ($chatProvider?.value || 'openai');
    const mdl = ($chatModel?.value || '');
    saveChatPrefs();
    const sid = ensureChatSession();
    const sys = 'You only provide suggestions and example text. You do not perform actions. Where possible, provide ready-to-copy text the user can paste into Jira or Confluence.';
    // Placeholder tijdens verwerken
    let placeholder = document.createElement('div');
    placeholder.innerHTML = `<em>AI is thinking…</em>`;
    $chatLog?.appendChild(placeholder);
    $chatLog?.scrollTo(0, $chatLog.scrollHeight);
    try {
      const includeData = !!document.getElementById('chat-include-data')?.checked;
      const wantStream = !!document.getElementById('chat-stream')?.checked;
      // Streaming verzoek naar /chat/stream, met fallback naar /chat/complete
      const res = wantStream ? await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: prov, model: mdl, message: q, session_id: sid, system: sys, temperature: 0.2, include_context: includeData, dataset: 'all' }),
      }) : null;
      if (!wantStream || !res || !res.ok || !res.body) {
        // Fallback to non-streaming
        const res2 = await fetch(`${API_BASE}/chat/complete`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: prov, model: mdl, message: q, session_id: sid, system: sys, temperature: 0.2, include_context: includeData, dataset: 'all' }),
        });
        const data2 = await res2.json().catch(() => ({}));
        placeholder.remove();
        if (!res2.ok) {
          appendChat('assistant', data2?.detail || `Error: ${res2.status} ${res2.statusText}`);
        } else {
          appendChat('assistant', data2?.reply || '(empty response)');
        }
        return;
      }
      // Stream tonen
      const msgDiv = document.createElement('div');
      msgDiv.innerHTML = `<strong>AI:</strong> `;
      placeholder.replaceWith(msgDiv);
      const reader = res.body.getReader();
      const td = new TextDecoder();
      let gotAny = false;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const text = td.decode(value, { stream: true });
        if (text) {
          gotAny = true;
          const span = document.createElement('span');
          span.textContent = text;
          msgDiv.appendChild(span);
          $chatLog?.scrollTo(0, $chatLog.scrollHeight);
        }
      }
      // No chunks? Fallback to complete
      if (!gotAny) {
        const res3 = await fetch(`${API_BASE}/chat/complete`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: prov, model: mdl, message: q, session_id: sid, system: sys, temperature: 0.2, include_context: includeData, dataset: 'all' }),
        });
        const data3 = await res3.json().catch(() => ({}));
        if (!res3.ok) {
          msgDiv.appendChild(document.createTextNode(data3?.detail || ` Error: ${res3.status} ${res3.statusText}`));
        } else {
          msgDiv.appendChild(document.createTextNode(data3?.reply || ''));
        }
      }
    } catch (e) {
      placeholder.remove();
      appendChat('assistant', `Error: ${e?.message || e}`);
    }
  }
  $chatSend?.addEventListener('click', () => { sendChat(); });
  $chatInput?.addEventListener('keydown', (e) => {
    // Enter = verzenden; Shift+Enter = nieuwe regel
    if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      sendChat();
    }
  });

  // Zabbix/Jira/Confluence placeholders
  // --- Zabbix helpers: GUI-like filtering ---

  // Apply Zabbix GUI-like filters to events array
  // Order of operations (important):
  // 1) Deduplicate per host + problem-prefix (text before ':'):
  //    - Keep the highest severity as the representative for the group
  //    - If severities are equal, keep the newest (highest clock)
  // 2) Apply "Show unacknowledged only" on this clean, deduplicated list
  // 3) Sort by newest first
  // opts: { unackOnly: boolean }
  function applyZabbixGuiFilter(events, opts) {
    const list = Array.isArray(events) ? events.slice() : [];
    const getNum = (v, d = 0) => { const n = Number(v); return Number.isFinite(n) ? n : d; };
    // 1) Hide duplicate Problems per host, based on prefix before ':'
    //    Key = (hostid|host) + '|' + problemPrefix
    const baseKey = (ev) => {
      const nm = String(ev?.name || '').trim();
      const i = nm.indexOf(':');
      const prefix = (i >= 0 ? nm.slice(0, i) : nm).trim();
      const hostKey = String(ev?.hostid ?? ev?.host ?? '').trim();
      if (hostKey && prefix) return `${hostKey}|${prefix}`;
      if (hostKey) return `${hostKey}|${nm}`;
      if (prefix) return `${prefix}|${String(ev?.eventid || '').trim()}`;
      return String(ev?.eventid || '').trim();
    };
    const byPrefix = new Map();
    for (const ev of list) {
      const key = baseKey(ev);
      const prev = byPrefix.get(key);
      if (!prev) { byPrefix.set(key, ev); continue; }
      const sevPrev = getNum(prev?.severity, -1);
      const sevCur = getNum(ev?.severity, -1);
      if (sevCur > sevPrev) { byPrefix.set(key, ev); continue; }
      if (sevCur < sevPrev) { continue; }
      // Same severity: prefer the newest by clock
      const cPrev = getNum(prev?.clock, 0);
      const cCur = getNum(ev?.clock, 0);
      if (cCur >= cPrev) byPrefix.set(key, ev);
    }
    let deduped = Array.from(byPrefix.values());
    // 2) Apply unacknowledged-only AFTER producing the clean list
    if (opts && opts.unackOnly) {
      deduped = deduped.filter((ev) => String(ev?.acknowledged ?? '0') === '0');
    }
    // 3) Sort newest first (like Problems view)
    deduped.sort((a, b) => getNum(b?.clock, 0) - getNum(a?.clock, 0));
    return deduped;
  }

  async function fetchZabbix() {
    const el = document.getElementById('zbx-feed');
    if (!el) return;
    el.textContent = 'Loading…';
    try {
      const systemsOnly = !!document.getElementById('zbx-systems')?.checked;
      // Build URL with optional Systems group (27) and including subgroups.
      // All other filtering is applied client-side to match the Zabbix GUI behavior.
      const params = new URLSearchParams();
      if (systemsOnly) { params.set('groupids', '27'); params.set('include_subgroups', '1'); }
      const url = `${API_BASE}/zabbix/problems?${params.toString()}`;
      const res = await fetch(url);
      if (!res.ok) {
        const t = await res.text();
        el.textContent = `Failed to load Zabbix: ${res.status} ${res.statusText} ${t || ''}`.trim();
        return;
      }
      const data = await res.json();
      let items = Array.isArray(data?.items) ? data.items : [];
      // Apply GUI-like filters before rendering
      const opts = {
        unackOnly: !!document.querySelector('#zbx-unack')?.checked,
      };
      items = applyZabbixGuiFilter(items, opts);
      if (!items.length) {
        el.textContent = 'No problems found.';
        try {
          const s = document.getElementById('zbx-stats');
          if (s) s.textContent = `0 problems — last: ${formatNowTime()}`;
        } catch {}
        return;
      }
      // Build table: Time, [ ], Severity, Status, Host, Problem, Duration
      const table = document.createElement('table');
      table.className = 'zbx-table';
      const thead = document.createElement('thead');
      thead.innerHTML = '<tr><th style="width:28px;"><input id="zbx-sel-all" type="checkbox" /></th><th>Time</th><th>Severity</th><th>Status</th><th>Host</th><th>Problem</th><th>Duration</th></tr>';
      table.appendChild(thead);
      const tbody = document.createElement('tbody');
      const sevName = (s) => ['Not classified','Information','Warning','Average','High','Disaster'][Math.max(0, Math.min(5, Number(s)||0))];
      const sevClass = (s) => ['sev-0','sev-1','sev-2','sev-3','sev-4','sev-5'][Math.max(0, Math.min(5, Number(s)||0))];
      const fmtTime = (iso) => {
        if (!iso) return '';
        // Show HH:MM:SS if today, else YYYY-MM-DD HH:MM:SS
        try {
          const d = new Date(iso.replace(' ', 'T') + 'Z');
          const now = new Date();
          const pad = (n) => String(n).padStart(2, '0');
          const sameDay = d.getUTCFullYear() === now.getUTCFullYear() && d.getUTCMonth() === now.getUTCMonth() && d.getUTCDate() === now.getUTCDate();
          if (sameDay) return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
          return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
        } catch { return iso; }
      };
      const fmtDur = (sec) => {
        sec = Math.max(0, Number(sec) || 0);
        const d = Math.floor(sec / 86400); sec -= d*86400;
        const h = Math.floor(sec / 3600); sec -= h*3600;
        const m = Math.floor(sec / 60); const s = sec - m*60;
        const parts = [];
        if (d) parts.push(`${d}d`);
        if (h) parts.push(`${h}h`);
        if (m) parts.push(`${m}m`);
        if (!d && !h) parts.push(`${s}s`);
        return parts.join(' ');
      };
      const nowSec = Math.floor(Date.now() / 1000);
      for (const it of items) {
        const tr = document.createElement('tr');
        const tdSel = document.createElement('td');
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.className = 'zbx-ev';
        cb.dataset.eventid = String(it.eventid || '');
        tdSel.appendChild(cb);
        const tdTime = document.createElement('td');
        tdTime.textContent = fmtTime(it.clock_iso) || '';
        const tdSev = document.createElement('td');
        const sev = document.createElement('span');
        sev.className = `sev ${sevClass(it.severity)}`;
        sev.textContent = sevName(it.severity);
        tdSev.appendChild(sev);
        const tdStatus = document.createElement('td');
        tdStatus.textContent = (it.status || '').toUpperCase();
        tdStatus.style.color = (it.status || '').toUpperCase() === 'RESOLVED' ? '#16a34a' : '#ef4444';
        const tdHost = document.createElement('td');
        if (it.host) {
          const a = document.createElement('a');
          a.href = '#zhost'; a.textContent = it.host; a.title = 'Bekijk hostdetails';
          a.addEventListener('click', (e) => { e.preventDefault(); showZabbixHost(it.hostid, it.host, it.host_url); });
          tdHost.appendChild(a);
        } else { tdHost.textContent = it.host || ''; }
        const tdProblem = document.createElement('td');
        if (it.problem_url) {
          const a2 = document.createElement('a');
          a2.href = it.problem_url; a2.textContent = it.name || ''; a2.target = '_blank'; a2.rel = 'noopener';
          tdProblem.appendChild(a2);
        } else { tdProblem.textContent = it.name || ''; }
        const tdDur = document.createElement('td');
        const durSec = Math.max(0, (nowSec - (Number(it.clock)||0)));
        tdDur.textContent = fmtDur(durSec);
        tr.appendChild(tdSel);
        tr.appendChild(tdTime);
        tr.appendChild(tdSev);
        tr.appendChild(tdStatus);
        tr.appendChild(tdHost);
        tr.appendChild(tdProblem);
        tr.appendChild(tdDur);
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      // Apply density class
      try {
        const dens = document.getElementById('zbx-density');
        const val = dens ? dens.value : 'comfortable';
        if (val === 'compact') table.classList.add('compact'); else table.classList.remove('compact');
      } catch {}
      el.innerHTML = '';
      el.appendChild(table);
      // Update stats: count and last refresh time
      try {
        const s = document.getElementById('zbx-stats');
        if (s) s.textContent = `${items.length} problems — last: ${formatNowTime()}`;
      } catch {}
      // Select-all behavior for main problems list
      const selAll = document.getElementById('zbx-sel-all');
      selAll?.addEventListener('change', () => {
        const boxes = el.querySelectorAll('input.zbx-ev[type="checkbox"]');
        boxes.forEach(b => { b.checked = selAll.checked; });
      });
    } catch (e) {
      el.textContent = `Error: ${e?.message || e}`;
    }
  }
  document.getElementById('zbx-refresh')?.addEventListener('click', () => { fetchZabbix(); });
  // Density persistence and control for Zabbix
  const $zbxDensity = document.getElementById('zbx-density');
  if ($zbxDensity) {
    try { const saved = localStorage.getItem('zbx_density'); if (saved) $zbxDensity.value = saved; } catch {}
    $zbxDensity.addEventListener('change', () => { try { localStorage.setItem('zbx_density', $zbxDensity.value); } catch {}; fetchZabbix(); });
  }
  // Auto refresh interval handling
  let zbxAutoTimer = null;
  function clearZbxAuto() { if (zbxAutoTimer) { clearInterval(zbxAutoTimer); zbxAutoTimer = null; } }
  function setZbxAuto(ms) {
    clearZbxAuto();
    if (ms && ms > 0) {
      zbxAutoTimer = setInterval(() => { if (page === 'zabbix') fetchZabbix(); }, ms);
    }
  }
  const $zbxRefreshSel = document.getElementById('zbx-refresh-interval');
  if ($zbxRefreshSel) {
    try {
      const saved = localStorage.getItem('zbx_refresh_interval');
      if (saved != null && $zbxRefreshSel.querySelector(`option[value="${saved}"]`)) {
        $zbxRefreshSel.value = saved;
        setZbxAuto(Number(saved));
      }
    } catch {}
    $zbxRefreshSel.addEventListener('change', () => {
      const ms = Number($zbxRefreshSel.value || '0') || 0;
      try { localStorage.setItem('zbx_refresh_interval', String(ms)); } catch {}
      setZbxAuto(ms);
    });
  }
  // Ack selected events on main Zabbix page
  document.getElementById('zbx-ack')?.addEventListener('click', async (e) => {
    e.preventDefault();
    try {
      const feed = document.getElementById('zbx-feed');
      if (!feed) { alert('No list loaded.'); return; }
      const boxes = Array.from(feed.querySelectorAll('input.zbx-ev[type="checkbox"]'));
      const ids = boxes.filter(b => b.checked).map(b => b.dataset.eventid).filter(Boolean);
      if (!ids.length) { alert('No problems selected.'); return; }
      const msg = prompt('Ack message (optional):', 'Acknowledged via Enreach Tools');
      const res = await fetch(`${API_BASE}/zabbix/ack`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ eventids: ids, message: msg || '' }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { alert(`Ack failed: ${data?.detail || res.statusText}`); return; }
      alert('Acknowledged. Refreshing list.');
      fetchZabbix();
    } catch (err) {
      alert(`Error: ${err?.message || err}`);
    }
  });
  // Persist and react to unack toggle
  const $zbxUnack = document.getElementById('zbx-unack');
  const $zbxSystems = document.getElementById('zbx-systems');
  function formatNowTime() {
    try {
      const d = new Date();
      const pad = (n) => String(n).padStart(2, '0');
      return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    } catch { return ''; }
  }
  try {
    const saved = localStorage.getItem('zbx_unack_only');
    if ($zbxUnack && saved != null) $zbxUnack.checked = saved === '1';
    const savedSystems = localStorage.getItem('zbx_systems_only');
    if ($zbxSystems && savedSystems != null) $zbxSystems.checked = savedSystems === '1';
  } catch {}
  $zbxUnack?.addEventListener('change', () => {
    try { localStorage.setItem('zbx_unack_only', $zbxUnack.checked ? '1' : '0'); } catch {}
    fetchZabbix();
  });
  $zbxSystems?.addEventListener('change', () => {
    try { localStorage.setItem('zbx_systems_only', $zbxSystems.checked ? '1' : '0'); } catch {}
    fetchZabbix();
  });

  // When changing pages, stop auto refresh unless we're on Zabbix
  const _origShowPage = showPage;
  showPage = function(p) { // eslint-disable-line no-global-assign
    _origShowPage(p);
    if (p !== 'zabbix') clearZbxAuto();
    else if ($zbxRefreshSel) setZbxAuto(Number($zbxRefreshSel.value || '0') || 0);
  };

  // Expose helpers for debugging/ESM-like usage in non-module context
  try {
    if (typeof window !== 'undefined') {
      window.applyZabbixGuiFilter = applyZabbixGuiFilter;
    }
  } catch {}

  // ---------------------------
  // Zabbix Host details page
  // ---------------------------
  const $zhostTitle = document.getElementById('zhost-title');
  const $zhostInfo = document.getElementById('zhost-info');
  const $zhostProblems = document.getElementById('zhost-problems');
  document.getElementById('zhost-back')?.addEventListener('click', (e) => { e.preventDefault(); showPage('zabbix'); });
  const $zhostOpenZbx = document.getElementById('zhost-open-zbx');

  let lastZHostId = null;

  function renderHostInfo(h) {
    if (!$zhostInfo) return;
    if (!h || typeof h !== 'object') { $zhostInfo.textContent = 'No info found.'; return; }
    const wrap = document.createElement('div');
    wrap.className = 'feed';
    const basics = document.createElement('div');
    basics.innerHTML = `<strong>Host:</strong> ${h.host || ''} &nbsp; <strong>Visible name:</strong> ${h.name || ''} &nbsp; <strong>ID:</strong> ${h.hostid || ''}`;
    wrap.appendChild(basics);
    // Groups
    const groups = Array.isArray(h.groups) ? h.groups.map(g => g?.name).filter(Boolean) : [];
    if (groups.length) {
      const div = document.createElement('div');
      div.innerHTML = `<strong>Groups:</strong> ${groups.join(', ')}`;
      wrap.appendChild(div);
    }
    // Interfaces
    const ifs = Array.isArray(h.interfaces) ? h.interfaces : [];
    if (ifs.length) {
      const tbl = document.createElement('table'); tbl.className = 'zbx-table';
      const th = document.createElement('thead'); th.innerHTML = '<tr><th>Type</th><th>IP</th><th>DNS</th><th>Port</th><th>Main</th></tr>'; tbl.appendChild(th);
      const bd = document.createElement('tbody');
      for (const it of ifs) {
        const tr = document.createElement('tr');
        const tdT = document.createElement('td'); tdT.textContent = String(it?.type || '');
        const tdIP = document.createElement('td'); tdIP.textContent = String(it?.ip || '');
        const tdDNS = document.createElement('td'); tdDNS.textContent = String(it?.dns || '');
        const tdP = document.createElement('td'); tdP.textContent = String(it?.port || '');
        const tdM = document.createElement('td'); tdM.textContent = String(it?.main || '');
        tr.appendChild(tdT); tr.appendChild(tdIP); tr.appendChild(tdDNS); tr.appendChild(tdP); tr.appendChild(tdM); bd.appendChild(tr);
      }
      tbl.appendChild(bd); wrap.appendChild(tbl);
    }
    // Inventory
    const inv = h.inventory || {};
    if (inv && Object.keys(inv).length) {
      const pre = document.createElement('pre'); pre.textContent = JSON.stringify(inv, null, 2); wrap.appendChild(pre);
    }
    $zhostInfo.innerHTML = ''; $zhostInfo.appendChild(wrap);
  }

  async function fetchZabbixHost(hostid, hostName, hostUrl) {
    if (!hostid) return;
    try {
      $zhostTitle.textContent = `Host: ${hostName || hostid}`;
      if ($zhostOpenZbx) {
        if (hostUrl) { $zhostOpenZbx.href = hostUrl; $zhostOpenZbx.removeAttribute('hidden'); }
        else { $zhostOpenZbx.setAttribute('hidden', ''); }
      }
      $zhostInfo.textContent = 'Loading…';
      const res = await fetch(`${API_BASE}/zabbix/host?hostid=${encodeURIComponent(hostid)}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { $zhostInfo.textContent = `Failed to load host: ${res.status} ${res.statusText}`; }
      else { renderHostInfo(data?.host); }
    } catch (e) {
      $zhostInfo.textContent = `Error: ${e?.message || e}`;
    }
  }

  async function fetchZabbixHostProblems(hostid) {
    if (!hostid) return;
    try {
      $zhostProblems.textContent = 'Loading…';
      const url = `${API_BASE}/zabbix/problems?hostids=${encodeURIComponent(hostid)}`;
      const res = await fetch(url);
      if (!res.ok) { const t = await res.text(); $zhostProblems.textContent = `Failed to load problems: ${res.status} ${res.statusText} ${t || ''}`.trim(); return; }
      const data = await res.json();
      const items = Array.isArray(data?.items) ? data.items : [];
      if (!items.length) {
        $zhostProblems.textContent = 'No problems found.';
        try { const s = document.getElementById('zhost-stats'); if (s) s.textContent = `0 problems — last: ${formatNowTime()}`; } catch {}
        return;
      }
      // Build simple problems table (no client-side filters)
      const table = document.createElement('table'); table.className = 'zbx-table';
      const thead = document.createElement('thead'); thead.innerHTML = '<tr><th style="width:28px;"><input id="zhost-sel-all" type="checkbox" /></th><th>Time</th><th>Severity</th><th>Status</th><th>Problem</th><th>Duration</th></tr>'; table.appendChild(thead);
      const tbody = document.createElement('tbody');
      const sevName = (s) => ['Not classified','Information','Warning','Average','High','Disaster'][Math.max(0, Math.min(5, Number(s)||0))];
      const fmtTime = (iso) => {
        if (!iso) return '';
        try { const d = new Date(iso.replace(' ', 'T') + 'Z'); const pad = (n)=> String(n).padStart(2,'0'); return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`; } catch { return iso; }
      };
      const nowSec = Math.floor(Date.now() / 1000);
      const fmtDur = (sec) => { sec = Math.max(0, Number(sec)||0); const d=Math.floor(sec/86400); sec-=d*86400; const h=Math.floor(sec/3600); sec-=h*3600; const m=Math.floor(sec/60); const s=sec-m*60; const parts=[]; if(d)parts.push(`${d}d`); if(h)parts.push(`${h}h`); if(m)parts.push(`${m}m`); if(!d && !h) parts.push(`${s}s`); return parts.join(' '); };
      for (const it of items) {
        const tr = document.createElement('tr');
        const tdSel = document.createElement('td'); const cb = document.createElement('input'); cb.type = 'checkbox'; cb.className = 'zhost-ev'; cb.dataset.eventid = String(it.eventid || ''); tdSel.appendChild(cb);
        const tdTime = document.createElement('td'); tdTime.textContent = fmtTime(it.clock_iso) || '';
        const tdSev = document.createElement('td'); tdSev.textContent = sevName(it.severity);
        const tdStatus = document.createElement('td'); tdStatus.textContent = (it.status||'').toUpperCase(); tdStatus.style.color = (it.status||'').toUpperCase()==='RESOLVED'?'#16a34a':'#ef4444';
        const tdProblem = document.createElement('td');
        if (it.problem_url) {
          const a = document.createElement('a'); a.href = it.problem_url; a.textContent = it.name || ''; a.target = '_blank'; a.rel = 'noopener'; tdProblem.appendChild(a);
        } else { tdProblem.textContent = it.name || ''; }
        const tdDur = document.createElement('td'); const durSec = Math.max(0, (nowSec - (Number(it.clock)||0))); tdDur.textContent = fmtDur(durSec);
        tr.appendChild(tdSel); tr.appendChild(tdTime); tr.appendChild(tdSev); tr.appendChild(tdStatus); tr.appendChild(tdProblem); tr.appendChild(tdDur);
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      try { const dens = document.getElementById('zbx-density'); const val = dens ? dens.value : 'comfortable'; if (val === 'compact') table.classList.add('compact'); else table.classList.remove('compact'); } catch {}
      $zhostProblems.innerHTML = ''; $zhostProblems.appendChild(table);
      try { const s = document.getElementById('zhost-stats'); if (s) s.textContent = `${items.length} problems — last: ${formatNowTime()}`; } catch {}
      // Select-all behavior
      const selAll = document.getElementById('zhost-sel-all');
      selAll?.addEventListener('change', () => {
        const boxes = $zhostProblems.querySelectorAll('input.zhost-ev[type="checkbox"]');
        boxes.forEach(b => { b.checked = selAll.checked; });
      });
    } catch (e) {
      $zhostProblems.textContent = `Error: ${e?.message || e}`;
    }
  }

  function showZabbixHost(hostid, hostName, hostUrl) {
    showPage('zhost');
    lastZHostId = hostid || null;
    try { window._lastZHostId = lastZHostId; } catch {}
    fetchZabbixHost(hostid, hostName, hostUrl);
    fetchZabbixHostProblems(hostid);
  }

  // Ack selected events on host details page
  document.getElementById('zhost-ack')?.addEventListener('click', async (e) => {
    e.preventDefault();
    try {
      const boxes = Array.from($zhostProblems.querySelectorAll('input.zhost-ev[type="checkbox"]'));
      const ids = boxes.filter(b => b.checked).map(b => b.dataset.eventid).filter(Boolean);
      if (!ids.length) { alert('No problems selected.'); return; }
      const msg = prompt('Ack message (optional):', 'Acknowledged via Enreach Tools');
      const res = await fetch(`${API_BASE}/zabbix/ack`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ eventids: ids, message: msg || '' }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { alert(`Ack failed: ${data?.detail || res.statusText}`); return; }
      alert('Acknowledged. Refreshing list.');
      if (lastZHostId) {
        fetchZabbixHostProblems(lastZHostId);
      } else {
        // Do a minimal refresh by refetching the problems via the last anchor click handler path; as a fallback, just show Zabbix then go back
        fetchZabbix();
      }
    } catch (err) {
      alert(`Error: ${err?.message || err}`);
    }
  });
  document.getElementById('jira-refresh')?.addEventListener('click', () => {
    const el = document.getElementById('jira-list');
    if (el) el.textContent = 'No Jira integration configured yet: configure token and JQL later.';
  });
  document.getElementById('conf-search')?.addEventListener('click', () => {
    const el = document.getElementById('conf-results');
    const q = (document.getElementById('conf-q')?.value || '').trim();
    if (el) el.textContent = q ? `Searching for "${q}"… (placeholder)` : 'Enter a search term.';
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
  // Set initial dataset tab active
  $dsTabs?.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-ds') === dataset));
  // Initial page from hash
  // Prepare chat defaults before showing the page (so UI sensible)
  loadChatPrefs();
  loadChatDefaults();
  const initialPage = parseHashPage();
  if (initialPage === 'chat') {
    ensureChatSession();
    refreshChatHistory();
  }
  showPage(initialPage);
  // When switching to chat, ensure session and history are loaded
  

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
