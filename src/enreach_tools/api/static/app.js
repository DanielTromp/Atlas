(() => {
  const API_BASE = ""; // same origin
  const el = (id) => document.getElementById(id);
  const $dataset = el("dataset");
  const $limit = el("limit");
  const $search = el("search");
  const $refresh = el("refresh");
  const $columnsBtn = el("columnsBtn");
  const $updateBtn = el("updateBtn");
  const $progressPanel = el("progress-panel");
  const $progressClose = el("progress-close");
  const $progressLog = el("progress-log");
  const $colPanel = el("col-panel");
  const $colClose = el("col-close");
  const $colAll = el("col-all");
  const $colClear = el("col-clear");
  const $colReset = el("col-reset");
  const $colList = el("col-list");
  const $thead = document.querySelector("#grid thead");
  const $tbody = document.querySelector("#grid tbody");
  const $status = el("status");

  let rows = [];
  let view = [];
  let sortKey = null;
  let sortDir = "asc";
  let displayLimit = 100;
  let pageIndex = 0; // 0-based page number
  let currentDataset = "devices";
  let selectedCols = null; // null = all; [] = none
  // Column-specific filters per visible column
  let columnFilters = {};

  // Default columns (filtered to existing headers per dataset)
  const DEFAULT_COLS = [
    "Name",
    "Status",
    "Role",
    "Platform",
    "IP Address",
    "OOB IP",
    "Contacts",
    "Created",
    "Last updated",
    "Cluster",
    "Device",
  ];
  const defaultColsFor = (headers) => DEFAULT_COLS.filter((h) => headers.includes(h));

  // Optional column order loaded from backend (Systems CMDB.xlsx)
  let columnOrder = [];
  const orderHeaders = (headers) => {
    if (!columnOrder || columnOrder.length === 0) return headers.slice();
    const index = new Map(columnOrder.map((h, i) => [h, i]));
    return headers
      .map((h, i) => ({ h, i }))
      .sort((a, b) => {
        const ai = index.has(a.h) ? index.get(a.h) : 1e9;
        const bi = index.has(b.h) ? index.get(b.h) : 1e9;
        if (ai !== bi) return ai - bi;
        return a.i - b.i; // stable fallback
      })
      .map((x) => x.h);
  };

  const storageKey = (dataset) => `netbox_cols_${dataset}`;
  function loadCols(dataset, headers) {
    try {
      const raw = localStorage.getItem(storageKey(dataset));
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return null;
      return parsed.filter((h) => headers.includes(h));
    } catch {
      return null;
    }
  }
  function saveCols(dataset, cols) {
    try {
      if (cols == null) {
        localStorage.removeItem(storageKey(dataset));
      } else {
        localStorage.setItem(storageKey(dataset), JSON.stringify(cols));
      }
    } catch {}
  }

  function setStatus(msg) {
    $status.textContent = msg;
  }

  function compareValues(a, b) {
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    const na = Number(a), nb = Number(b);
    if (!Number.isNaN(na) && !Number.isNaN(nb)) {
      return na < nb ? -1 : na > nb ? 1 : 0;
    }
    return String(a).localeCompare(String(b), undefined, { sensitivity: "base" });
  }

  function computeFilteredSortedView() {
    const q = $search.value.trim().toLowerCase();
    view = rows.filter((r) => {
      // Column-specific filters (all must match)
      for (const [col, val] of Object.entries(columnFilters)) {
        const needle = (val || "").trim().toLowerCase();
        if (!needle) continue;
        const cell = r[col];
        const hay = cell == null ? "" : String(cell).toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      // Global search across all fields
      if (!q) return true;
      for (const k in r) {
        const v = r[k];
        if (v != null && String(v).toLowerCase().includes(q)) return true;
      }
      return false;
    });
    if (sortKey) {
      const dir = sortDir === "asc" ? 1 : -1;
      view.sort((a, b) => dir * compareValues(a[sortKey], b[sortKey]));
    }
  }

  function applyFilterSort() {
    computeFilteredSortedView();
    renderTable();
  }

  function renderBodyFromCurrentHeaders() {
    // Derive current visible headers from first header row (not filters)
    const ths = Array.from($thead.querySelectorAll('tr:first-child th'));
    const headersToUse = ths.map((th) => th.dataset.key).filter(Boolean);
    // Re-render body and status without rebuilding headers (preserve input focus)
    $tbody.innerHTML = "";
    const frag = document.createDocumentFragment();
    const total = view.length;
    const pageSize = Math.max(1, displayLimit);
    const start = Math.min(pageIndex * pageSize, Math.max(0, total - (total % pageSize || pageSize)));
    const end = Math.min(start + pageSize, total);
    const toRender = view.slice(start, end);
    toRender.forEach((r) => {
      const tr = document.createElement("tr");
      headersToUse.forEach((h) => {
        const td = document.createElement("td");
        const v = r[h];
        td.textContent = v == null ? "" : String(v);
        tr.appendChild(td);
      });
      frag.appendChild(tr);
    });
    $tbody.appendChild(frag);
    setStatus(`Showing ${total === 0 ? 0 : start + 1}-${end} of ${total} filtered rows (from ${rows.length} total, ${headersToUse.length} columns).`);
    updatePager(total, pageSize, pageIndex);
  }

  function renderTable() {
    const headers = rows.length ? Object.keys(rows[0]) : [];
    const ordered = orderHeaders(headers);
    const headersToUse = (selectedCols !== null)
      ? ordered.filter((h) => selectedCols.includes(h))
      : ordered;
    $thead.innerHTML = "";
    const trh = document.createElement("tr");
    headersToUse.forEach((h) => {
      const th = document.createElement("th");
      th.textContent = h;
      th.className = "th";
      th.dataset.key = h;
      if (sortKey === h) th.classList.add(sortDir === "asc" ? "sort-asc" : "sort-desc");
      th.addEventListener("click", () => {
        if (sortKey === h) {
          sortDir = sortDir === "asc" ? "desc" : "asc";
        } else {
          sortKey = h;
          sortDir = "asc";
        }
        applyFilterSort();
      });
      trh.appendChild(th);
    });
    $thead.appendChild(trh);
    // Build column filter row below headers
    // Remove filters for hidden columns
    Object.keys(columnFilters).forEach((k) => {
      if (!headersToUse.includes(k)) delete columnFilters[k];
    });
    const trf = document.createElement("tr");
    trf.className = "filters";
    headersToUse.forEach((h) => {
      const th = document.createElement("th");
      const inp = document.createElement("input");
      inp.type = "text";
      inp.className = "col-filter";
      inp.placeholder = "filter";
      inp.value = columnFilters[h] || "";
      inp.addEventListener("input", () => {
        columnFilters[h] = inp.value;
        pageIndex = 0;
        computeFilteredSortedView();
        renderBodyFromCurrentHeaders();
      });
      th.appendChild(inp);
      trf.appendChild(th);
    });
    $thead.appendChild(trf);

    $tbody.innerHTML = "";
    const frag = document.createDocumentFragment();
    const total = view.length;
    const pageSize = Math.max(1, displayLimit);
    const start = Math.min(pageIndex * pageSize, Math.max(0, total - (total % pageSize || pageSize)));
    const end = Math.min(start + pageSize, total);
    const toRender = view.slice(start, end);
    toRender.forEach((r) => {
      const tr = document.createElement("tr");
      headersToUse.forEach((h) => {
        const td = document.createElement("td");
        const v = r[h];
        td.textContent = v == null ? "" : String(v);
        tr.appendChild(td);
      });
      frag.appendChild(tr);
    });
    $tbody.appendChild(frag);
    setStatus(`Showing ${total === 0 ? 0 : start + 1}-${end} of ${total} filtered rows (from ${rows.length} total, ${headersToUse.length} columns).`);
    updatePager(total, pageSize, pageIndex);
  }

  function rebuildColumnPanel() {
    $colList.innerHTML = "";
    const headers = rows.length ? Object.keys(rows[0]) : [];
    if (!headers.length) {
      $colList.textContent = "No columns (no data).";
      return;
    }
    const saved = loadCols(currentDataset, headers);
    if (saved !== null) {
      selectedCols = saved; // [] -> none
    } else {
      const def = defaultColsFor(headers);
      selectedCols = def.length ? def : null; // defaults if present, else all
    }
    const sorted = headers
      .slice()
      .sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
    sorted.forEach((h) => {
      const id = `col_${h.replace(/[^a-zA-Z0-9_]+/g, "_")}`;
      const wrap = document.createElement("label");
      wrap.className = "col-item";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.id = id;
      cb.checked = (selectedCols !== null) ? selectedCols.includes(h) : true;
      cb.addEventListener("change", () => {
        const checks = Array.from($colList.querySelectorAll("input[type=checkbox]"));
        const chosen = checks.filter((n) => n.checked).map((n) => n.dataset.col);
        if (chosen.length === headers.length) {
          selectedCols = null;
          saveCols(currentDataset, null);
        } else {
          selectedCols = chosen; // may be []
          saveCols(currentDataset, selectedCols);
        }
        renderTable();
      });
      cb.dataset.col = h;
      const span = document.createElement("span");
      span.textContent = h;
      wrap.appendChild(cb);
      wrap.appendChild(span);
      $colList.appendChild(wrap);
    });
  }

  function updatePager(total, pageSize, currentPage) {
    const $pager = document.getElementById("pager");
    const totalPages = Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
    pageIndex = Math.min(Math.max(0, currentPage), totalPages - 1);

    const windowSize = 7;
    const half = Math.floor(windowSize / 2);
    let start = Math.max(0, pageIndex - half);
    let end = Math.min(totalPages - 1, start + windowSize - 1);
    start = Math.max(0, Math.min(start, end - windowSize + 1));

    const makeBtn = (label, targetPage, disabled = false, active = false) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "page-btn";
      if (active) b.classList.add("active");
      if (disabled) b.disabled = true;
      b.textContent = label;
      if (!disabled && !active) {
        b.addEventListener("click", () => {
          pageIndex = targetPage;
          renderTable();
        });
      }
      return b;
    };

    const frag = document.createDocumentFragment();
    frag.appendChild(makeBtn("Prev", pageIndex - 1, pageIndex <= 0));
    if (start > 0) {
      frag.appendChild(makeBtn("1", 0, false, pageIndex === 0));
      if (start > 1) {
        const span = document.createElement("span");
        span.className = "page-ellipsis";
        span.textContent = "…";
        frag.appendChild(span);
      }
    }
    for (let p = start; p <= end; p++) {
      frag.appendChild(makeBtn(String(p + 1), p, false, p === pageIndex));
    }
    if (end < totalPages - 1) {
      if (end < totalPages - 2) {
        const span = document.createElement("span");
        span.className = "page-ellipsis";
        span.textContent = "…";
        frag.appendChild(span);
      }
      frag.appendChild(makeBtn(String(totalPages), totalPages - 1, false, pageIndex === totalPages - 1));
    }
    frag.appendChild(makeBtn("Next", pageIndex + 1, pageIndex >= totalPages - 1));

    $pager.innerHTML = "";
    $pager.appendChild(frag);
  }

  async function loadData() {
    const dataset = $dataset.value;
    displayLimit = Number($limit.value || 100);
    const path = dataset === "all" ? "all" : dataset;
    const url = `${API_BASE}/${path}`; // fetch full dataset; limit client-side
    setStatus("Loading...");
    try {
      // Fetch column order (once per session; cached)
      if (!columnOrder || columnOrder.length === 0) {
        try {
          const or = await fetch(`${API_BASE}/column-order`);
          if (or.ok) {
            const arr = await or.json();
            if (Array.isArray(arr)) columnOrder = arr;
          }
        } catch {}
      }
      const res = await fetch(url);
      if (!res.ok) {
        throw new Error(`${res.status} ${res.statusText}`);
      }
      const data = await res.json();
      rows = Array.isArray(data) ? data : [];
      sortKey = null;
      sortDir = "asc";
      $search.value = "";
      pageIndex = 0;
      currentDataset = dataset;
      columnFilters = {};
      rebuildColumnPanel();
      applyFilterSort();
      if (rows.length === 0) {
        setStatus("No rows. Ensure CSVs exist in NETBOX_DATA_DIR and refresh.");
      }
    } catch (e) {
      console.error(e);
      setStatus(`Error loading data: ${e.message || e}`);
      rows = [];
      view = [];
      renderTable();
    }
  }

  $search.addEventListener("input", () => {
    pageIndex = 0;
    applyFilterSort();
  });
  $dataset.addEventListener("change", () => loadData());
  $limit.addEventListener("change", () => {
    displayLimit = Number($limit.value || 100);
    pageIndex = 0;
    renderTable();
  });
  $refresh.addEventListener("click", () => loadData());

  // Stream export logs to the progress panel
  async function runExportFor(dataset) {
    const ds = dataset === "all" ? "all" : dataset; // devices|vms|all
    const url = `${API_BASE}/export/stream?dataset=${encodeURIComponent(ds)}`;
    $progressLog.textContent = "";
    $progressPanel.hidden = false;
    $updateBtn.disabled = true;
    try {
      const res = await fetch(url, { method: "GET" });
      if (!res.ok || !res.body) {
        throw new Error(`${res.status} ${res.statusText}`);
      }
      const reader = res.body.getReader();
      const td = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        $progressLog.textContent += td.decode(value, { stream: true });
        $progressLog.scrollTop = $progressLog.scrollHeight;
      }
    } catch (e) {
      $progressLog.textContent += `\n[error] ${e && e.message ? e.message : e}\n`;
    } finally {
      $updateBtn.disabled = false;
      // Refresh dataset after completion
      await loadData();
      $progressPanel.hidden = true;
    }
  }

  // Update button workflow: confirm, stream, then refresh
  $updateBtn.addEventListener("click", async () => {
    const ds = $dataset.value;
    const label = ds === "all" ? "All (merge)" : ds.charAt(0).toUpperCase() + ds.slice(1);
    if (!confirm(`Run export for "${label}" now?`)) return;
    await runExportFor(ds);
  });
  $progressClose.addEventListener("click", () => { $progressPanel.hidden = true; });

  // Column panel actions
  $columnsBtn.addEventListener("click", () => {
    rebuildColumnPanel();
    $colPanel.hidden = !$colPanel.hidden;
  });
  $colClose.addEventListener("click", () => { $colPanel.hidden = true; });
  $colAll.addEventListener("click", () => {
    selectedCols = null; // all
    saveCols(currentDataset, null);
    $colList.querySelectorAll('input[type="checkbox"]').forEach((cb) => (cb.checked = true));
    renderTable();
  });
  $colClear.addEventListener("click", () => {
    selectedCols = []; // none
    saveCols(currentDataset, []);
    $colList.querySelectorAll('input[type="checkbox"]').forEach((cb) => (cb.checked = false));
    renderTable();
  });
  $colReset.addEventListener("click", () => {
    const headers = rows.length ? Object.keys(rows[0]) : [];
    const def = defaultColsFor(headers);
    selectedCols = def.length ? def : null;
    saveCols(currentDataset, selectedCols);
    $colList.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      const col = cb.dataset.col;
      cb.checked = selectedCols === null ? true : selectedCols.includes(col);
    });
    renderTable();
  });

  loadData();
})();
