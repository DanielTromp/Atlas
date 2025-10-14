(() => {
  // Grid with virtual scrolling, column reorder, filters, and global search
  const API_BASE = ""; // same origin

  // Theming (React-powered dropdown)
  const THEMES = [
    { id: 'enreach-light', label: 'Enreach Light' },
    { id: 'nebula', label: 'Nebula Dark' },
    { id: 'default', label: 'Neutral Light' },
  ];
  const THEME_STORAGE_KEY = 'enreach_theme_v1';
  const THEME_CLASS_PREFIX = 'theme-';
  const KNOWN_THEME_CLASSES = THEMES.map((theme) => `${THEME_CLASS_PREFIX}${theme.id}`);

  const normaliseTheme = (value) => {
    if (!value) return THEMES[0].id;
    return THEMES.some((theme) => theme.id === value) ? value : THEMES[0].id;
  };

  const applyThemeClass = (nextTheme, options = {}) => {
    const safeTheme = normaliseTheme(nextTheme);
    const body = document.body;
    if (body) {
      for (const cls of KNOWN_THEME_CLASSES) body.classList.remove(cls);
      body.classList.add(`${THEME_CLASS_PREFIX}${safeTheme}`);
    }
    if (!options.skipPersist) {
      try { localStorage.setItem(THEME_STORAGE_KEY, safeTheme); } catch (_) { /* ignore */ }
    }
    return safeTheme;
  };

  const readStoredTheme = () => {
    try { return normaliseTheme(localStorage.getItem(THEME_STORAGE_KEY)); }
    catch (_) { return THEMES[0].id; }
  };

  const initialTheme = (() => {
    const stored = readStoredTheme();
    return applyThemeClass(stored, { skipPersist: true });
  })();

  const mountThemeToggle = (root) => {
    if (!root) return;

    const fallbackSelectId = 'theme-toggle-select';

    if (window.React && window.ReactDOM && typeof window.ReactDOM.createRoot === 'function') {
      const { useEffect, useState } = window.React;
      const e = window.React.createElement;

      const ThemeToggle = () => {
        const [value, setValue] = useState(initialTheme);

        useEffect(() => {
          applyThemeClass(value);
        }, [value]);

        useEffect(() => {
          const handleStorage = (event) => {
            if (event.key === THEME_STORAGE_KEY) {
              setValue(normaliseTheme(event.newValue));
            }
          };
          window.addEventListener('storage', handleStorage);
          return () => window.removeEventListener('storage', handleStorage);
        }, []);

        return e('div', { className: 'theme-toggle' },
          e('div', { className: 'theme-toggle__meta' },
            e('label', { className: 'theme-toggle__label', htmlFor: fallbackSelectId }, 'Theme'),
            e('select', {
              id: fallbackSelectId,
              className: 'theme-toggle__select',
              value,
              onChange: (event) => setValue(normaliseTheme(event.target.value)),
            }, THEMES.map((theme) => e('option', { key: theme.id, value: theme.id }, theme.label))),
          ),
        );
      };

      window.ReactDOM.createRoot(root).render(e(ThemeToggle));
      return;
    }

    const label = document.createElement('label');
    label.className = 'theme-toggle__label';
    label.setAttribute('for', fallbackSelectId);
    label.textContent = 'Theme';

    const select = document.createElement('select');
    select.id = fallbackSelectId;
    select.className = 'theme-toggle__select';
    for (const theme of THEMES) {
      const option = document.createElement('option');
      option.value = theme.id;
      option.textContent = theme.label;
      select.append(option);
    }
    select.value = initialTheme;
    select.addEventListener('change', (event) => applyThemeClass(event.target.value));

    const handleStorage = (event) => {
      if (event.key === THEME_STORAGE_KEY) {
        const next = normaliseTheme(event.newValue);
        select.value = next;
        applyThemeClass(next, { skipPersist: true });
      }
    };
    window.addEventListener('storage', handleStorage);

    const meta = document.createElement('div');
    meta.className = 'theme-toggle__meta';
    meta.append(label, select);

    const wrapper = document.createElement('div');
    wrapper.className = 'theme-toggle';
    wrapper.append(meta);

    root.append(wrapper);
  };

  // Elements
  // Page router
  const $themeRoot = document.getElementById('theme-toggle-root');
  const $pages = document.getElementById("pages");
  const $navChat = document.querySelector('button[data-page="chat"]');
  const $navVCenter = document.querySelector('button[data-page="vcenter"]');
  const $navTools = document.querySelector('button[data-page="tools"]');
  const $navTasks = document.querySelector('button[data-page="tasks"]');
  const $navAdmin = document.querySelector('button[data-page="admin"]');
  const $pageExport = document.getElementById("page-export");
  const $pageCommvault = document.getElementById("page-commvault");
  const $pageVCenter = document.getElementById("page-vcenter");
  const $pageNetbox = document.getElementById("page-netbox");
  const $pageSearch = document.getElementById("page-search");
  const $pageTools = document.getElementById("page-tools");
  const $pageTasks = document.getElementById("page-tasks");
  const $pageChat = document.getElementById("page-chat");
  const $pageZabbix = document.getElementById("page-zabbix");
  const $pageZhost = document.getElementById("page-zhost");
  const $zbxAck = document.getElementById('zbx-ack');
  const $zhostAck = document.getElementById('zhost-ack');
  const $pageJira = document.getElementById("page-jira");
  const $pageConfluence = document.getElementById("page-confluence");
  const $pageSuggestions = document.getElementById("page-suggestions");
  const $pageSuggestionDetail = document.getElementById("page-suggestion-detail");
  const $pageAdmin = document.getElementById("page-admin");
  // Tasks elements
  const $tasksList = document.getElementById("tasks-list");
  const $tasksStatus = document.getElementById("tasks-status");
  const $tasksRefresh = document.getElementById("tasks-refresh");
  const $tasksUpdateAll = document.getElementById("tasks-update-all");
  const $tasksLayoutButtons = Array.from(document.querySelectorAll('[data-tasks-layout]'));
  // Confluence elements
  const $confQ = document.getElementById('conf-q');
  const $confSpace = document.getElementById('conf-space');
  const $confType = document.getElementById('conf-type');
  const $confLabels = document.getElementById('conf-labels');
  const $confUpdated = document.getElementById('conf-updated');
  const $confMax = document.getElementById('conf-max');
  const $confResults = document.getElementById('conf-results');
  // Jira elements
  const $jiraQ = document.getElementById('jira-q');
  const $jiraProject = document.getElementById('jira-project');
  const $jiraStatus = document.getElementById('jira-status');
  const $jiraAssignee = document.getElementById('jira-assignee');
  const $jiraPriority = document.getElementById('jira-priority');
  const $jiraType = document.getElementById('jira-type');
  const $jiraTeam = document.getElementById('jira-team');
  const $jiraUpdated = document.getElementById('jira-updated');
  const $jiraOpen = document.getElementById('jira-open');
  const $jiraMax = document.getElementById('jira-max');
  const $jiraResults = document.getElementById('jira-results');
  // Dataset tabs (inside Export page)
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
  const $commvaultTabs = document.getElementById("commvault-tabs");
  const $commvaultRefresh = document.getElementById("commvault-refresh");
  const $commvaultSummary = document.getElementById("commvault-summary");
  const $commvaultStatus = document.getElementById("commvault-status");
  const $commvaultTableBody = document.getElementById("commvault-table-body");
  const $commvaultSince = document.getElementById("commvault-since");
  const $commvaultStatusFilter = document.getElementById("commvault-status-filter");
  const $commvaultSearch = document.getElementById("commvault-search");
  const $commvaultStorageSummary = document.getElementById("commvault-storage-summary");
  const $commvaultStorageStatus = document.getElementById("commvault-storage-status");
  const $commvaultStorageTableBody = document.getElementById("commvault-storage-table-body");
  const $commvaultStorageDetail = document.getElementById("commvault-storage-detail");
  const $commvaultStorageRefresh = document.getElementById("commvault-storage-refresh");
  const $commvaultPlansSummary = document.getElementById("commvault-plans-summary");
  const $commvaultPlansStatus = document.getElementById("commvault-plans-status");
  const $vcenterTabs = document.getElementById("vcenter-tabs");
  const $vcenterRefresh = document.getElementById("vcenter-refresh");
  const $vcenterStatus = document.getElementById("vcenter-status");
  const $vcenterSearch = document.getElementById("vcenter-search");
  const $vcenterLoading = document.getElementById("vcenter-loading");
  const $vcenterError = document.getElementById("vcenter-error");
  const $vcenterEmpty = document.getElementById("vcenter-empty");
  const $vcenterTableWrapper = document.getElementById("vcenter-table-wrapper");
  const $vcenterTableHead = document.getElementById("vcenter-thead");
  const $vcenterTableBody = document.getElementById("vcenter-tbody");
  const $commvaultPlansTableBody = document.getElementById("commvault-plans-table-body");
  const $commvaultPlansRefresh = document.getElementById("commvault-plans-refresh");
  const $commvaultPlansType = document.getElementById("commvault-plans-type");
  const $commvaultServerSummary = document.getElementById("commvault-server-summary");
  const $commvaultServerQuery = document.getElementById("commvault-server-query");
  const $commvaultServerSearchBtn = document.getElementById("commvault-server-search");
  const $commvaultServerRetained = document.getElementById("commvault-server-retained");
  const $commvaultServerSince = document.getElementById("commvault-server-since");
  const $commvaultServerLimit = document.getElementById("commvault-server-limit");
  const $commvaultServerRefresh = document.getElementById("commvault-server-refresh");
  const $commvaultServerStatus = document.getElementById("commvault-server-status");
  const $commvaultServerMetrics = document.getElementById("commvault-server-metrics");
  const $commvaultServerPlanList = document.getElementById("commvault-server-plan");
  const $commvaultServerSubclientList = document.getElementById("commvault-server-subclient");
  const $commvaultServerPolicyList = document.getElementById("commvault-server-policy");
  const $commvaultServerExportButtons = document.getElementById("commvault-server-export-buttons");
  const $commvaultServerTableBody = document.getElementById("commvault-server-table-body");
  const $commvaultServerChartSize = document.getElementById("commvault-server-chart-size");
  const $commvaultServerChartSavings = document.getElementById("commvault-server-chart-savings");
  const $commvaultServerSuggestions = document.getElementById("commvault-server-suggestions");
  const $commvaultServerMetricCount = document.getElementById("commvault-server-metric-count");
  const $commvaultServerMetricWindow = document.getElementById("commvault-server-metric-window");
  const $commvaultServerMetricApp = document.getElementById("commvault-server-metric-app");
  const $commvaultServerMetricAppExtra = document.getElementById("commvault-server-metric-app-extra");
  const $commvaultServerMetricMedia = document.getElementById("commvault-server-metric-media");
  const $commvaultServerMetricMediaExtra = document.getElementById("commvault-server-metric-media-extra");
  const $commvaultServerMetricReduction = document.getElementById("commvault-server-metric-reduction");
  const $commvaultServerMetricReductionRatio = document.getElementById("commvault-server-metric-reduction-ratio");
  const $commvaultServerChartSizeUnit = document.getElementById("commvault-server-chart-size-unit");
  const commvaultPanels = Array.from(document.querySelectorAll('[data-commvault-panel]'));
  const $suggestionsButton = document.getElementById("open-suggestions");
  const $suggestionList = document.getElementById("suggestion-list");
  const $suggestionNew = document.getElementById("suggestion-new");
  const $suggestionBack = document.getElementById("suggestion-back");
  const $suggestionTitle = document.getElementById("suggestion-title");
  const $suggestionSummary = document.getElementById("suggestion-summary");
  const $suggestionClassification = document.getElementById("suggestion-classification");
  const $suggestionStatus = document.getElementById("suggestion-status");
  const $suggestionSave = document.getElementById("suggestion-save");
  const $suggestionCommentText = document.getElementById("suggestion-comment-text");
  const $suggestionCommentAdd = document.getElementById("suggestion-comment-add");
  const $suggestionComments = document.getElementById("suggestion-comments");
  const $suggestionDetailMeta = document.getElementById("suggestion-detail-meta");
  const $suggestionCommentsWrapper = document.getElementById("suggestion-comments-wrapper");
  const $suggestionDelete = document.getElementById("suggestion-delete");
  const $toolsList = document.getElementById("tools-list");
  const $toolsTags = document.getElementById("tools-tags");
  const $toolsSearch = document.getElementById("tools-search");
  const $toolsRefresh = document.getElementById("tools-refresh");
  const $toolsPreview = document.getElementById("tools-preview");
  const $toolsPreviewTitle = document.getElementById("tools-preview-title");
  const $toolsPreviewBody = document.getElementById("tools-preview-body");
  const $toolsPreviewCollapse = document.getElementById("tools-preview-collapse");
  let $chatExamples = document.getElementById("chat-examples");
  const $chatToolsPanel = document.getElementById("chat-tools-panel");
  const $chatToolsList = document.getElementById("chat-tools-list");
  const $chatToolsOpen = document.getElementById("chat-tools-open");
  const $adminSettings = document.getElementById("admin-settings");
  const adminContainers = {
    'zabbix': document.getElementById('admin-settings-zabbix'),
    'net-atlassian': document.getElementById('admin-settings-net'),
    'chat': document.getElementById('admin-settings-chat'),
    'export': document.getElementById('admin-settings-export'),
    'api': document.getElementById('admin-settings-api'),
    'backup': document.getElementById('admin-settings-backup'),
  };
  const adminPanels = {
    'zabbix': document.getElementById('admin-panel-zabbix'),
    'net-atlassian': document.getElementById('admin-panel-net'),
    'chat': document.getElementById('admin-panel-chat'),
    'export': document.getElementById('admin-panel-export'),
    'api': document.getElementById('admin-panel-api'),
    'vcenter': document.getElementById('admin-panel-vcenter'),
    'users': document.getElementById('admin-panel-users'),
    'backup': document.getElementById('admin-panel-backup'),
  };
  const adminTabs = document.querySelectorAll('#admin-tabs .admin-tab');
  const $adminStatus = document.getElementById("admin-status");
  const $adminBackupRun = document.getElementById("admin-backup-run");
  const $adminBackupType = document.getElementById("admin-backup-type");
  const $adminBackupLocalPath = document.getElementById("admin-backup-local-path");
  const $adminBackupHost = document.getElementById("admin-backup-host");
  const $adminBackupPort = document.getElementById("admin-backup-port");
  const $adminBackupUsername = document.getElementById("admin-backup-username");
  const $adminBackupPassword = document.getElementById("admin-backup-password");
  const $adminBackupKeyPath = document.getElementById("admin-backup-key-path");
  const $adminBackupRemotePath = document.getElementById("admin-backup-remote-path");
  const $adminBackupTimestamped = document.getElementById("admin-backup-timestamped");
  const $adminBackupStatus = document.getElementById("admin-backup-status");
  const $adminBackupLocalConfig = document.getElementById("admin-backup-local-config");
  const $adminBackupRemoteConfig = document.getElementById("admin-backup-remote-config");
  const $adminVCenterList = document.getElementById("admin-vcenter-list");
  const $adminVCenterAdd = document.getElementById("admin-vcenter-add");
  const $adminVCenterForm = document.getElementById("admin-vcenter-form");
  const $adminVCenterFormTitle = document.getElementById("admin-vcenter-form-title");
  const $adminVCenterId = document.getElementById("admin-vcenter-id");
  const $adminVCenterName = document.getElementById("admin-vcenter-name");
  const $adminVCenterBaseUrl = document.getElementById("admin-vcenter-base-url");
  const $adminVCenterUsername = document.getElementById("admin-vcenter-username");
  const $adminVCenterPassword = document.getElementById("admin-vcenter-password");
  const $adminVCenterPasswordHelp = document.getElementById("admin-vcenter-password-help");
  const $adminVCenterVerifySSL = document.getElementById("admin-vcenter-verify-ssl");
  const $adminVCenterSave = document.getElementById("admin-vcenter-save");
  const $adminVCenterCancel = document.getElementById("admin-vcenter-cancel");
  const $adminVCenterStatus = document.getElementById("admin-vcenter-status");
  const $adminVCenterFormStatus = document.getElementById("admin-vcenter-form-status");
  // User management elements
  const $adminUserList = document.getElementById("admin-user-list");
  const $adminUserDetail = document.getElementById("admin-user-detail");
  const $adminUserEmpty = document.getElementById("admin-user-empty");
  const $adminUserForm = document.getElementById("admin-user-form");
  const $adminUserFormTitle = document.getElementById("admin-user-form-title");
  const $adminUserUsername = document.getElementById("admin-user-username");
  const $adminUserDisplay = document.getElementById("admin-user-display");
  const $adminUserEmail = document.getElementById("admin-user-email");
  const $adminUserNewPassword = document.getElementById("admin-user-new-password");
  const $adminUserNewPasswordRow = document.getElementById("admin-user-new-password-row");
  const $adminUserRole = document.getElementById("admin-user-role");
  const $adminUserActive = document.getElementById("admin-user-active");
  const $adminUserSave = document.getElementById("admin-user-save");
  const $adminUserFormStatus = document.getElementById("admin-user-form-status");
  const $adminUserPasswordForm = document.getElementById("admin-user-password-form");
  const $adminUserPassword = document.getElementById("admin-user-password");
  const $adminUserPasswordSave = document.getElementById("admin-user-password-save");
  const $adminUserPasswordStatus = document.getElementById("admin-user-password-status");
  const $adminUserDelete = document.getElementById("admin-user-delete");
  const $adminRoleList = document.getElementById('admin-role-list');
  const $adminRoleStatus = document.getElementById('admin-role-status');
  const $adminUserCreate = document.getElementById("admin-user-create");
  const $adminUserRefresh = document.getElementById("admin-user-refresh");
  const $adminUserIncludeInactive = document.getElementById("admin-user-include-inactive");
  const $adminUserStatus = document.getElementById("admin-user-status");
  const $adminGlobalList = document.getElementById("admin-global-list");
  const $adminGlobalForm = document.getElementById("admin-global-form");
  const $adminGlobalProvider = document.getElementById("admin-global-provider");
  const $adminGlobalLabel = document.getElementById("admin-global-label");
  const $adminGlobalSecret = document.getElementById("admin-global-secret");
  const $adminGlobalSave = document.getElementById("admin-global-save");
  const $adminGlobalCancel = document.getElementById("admin-global-cancel");
  const $adminGlobalAdd = document.getElementById("admin-global-add");
  const $adminGlobalStatus = document.getElementById("admin-global-status");
  const $userMenuToggle = document.getElementById('user-menu-toggle');
  const $userMenu = document.getElementById('user-menu');
  const $userMenuName = document.getElementById('user-menu-name');
  const $userMenuRole = document.getElementById('user-menu-role');
  const $userMenuNameAlt = document.getElementById('user-menu-name-alt');
  const $userMenuRoleAlt = document.getElementById('user-menu-role-alt');
  const $pageAccount = document.getElementById('page-account');
  const $accountSubtitle = document.getElementById('account-subtitle');
  const accountTabs = Array.from(document.querySelectorAll('#account-tabs .account-tab'));
  const accountPanels = Array.from(document.querySelectorAll('.account-panel'));
  const $accountProfileForm = document.getElementById('account-profile-form');
  const $accountProfileDisplay = document.getElementById('account-profile-display');
  const $accountProfileEmail = document.getElementById('account-profile-email');
  const $accountProfileStatus = document.getElementById('account-profile-status');
  const $accountPasswordForm = document.getElementById('account-password-form');
  const $accountPasswordCurrent = document.getElementById('account-password-current');
  const $accountPasswordNew = document.getElementById('account-password-new');
  const $accountPasswordStatus = document.getElementById('account-password-status');
  const $accountPrefDataset = document.getElementById('account-pref-dataset');
  const $accountThemeMount = document.getElementById('account-theme-mount');
  const $accountApiList = document.getElementById('account-api-list');
  const $accountApiForm = document.getElementById('account-api-form');
  const $accountApiProvider = document.getElementById('account-api-provider');
  const $accountApiLabel = document.getElementById('account-api-label');
  const $accountApiSecret = document.getElementById('account-api-secret');
  const $accountApiStatus = document.getElementById('account-api-status');
  const userMenuItems = document.querySelectorAll('[data-user-action]');

  const defaultChatProviders = ['openai', 'openrouter', 'claude', 'gemini'];
  const ACCOUNT_DATASET_PREF_KEY = 'account_pref_dataset';

  const chatProvidersState = {
    items: [],
  };
  const accountState = {
    user: null,
    tab: 'profile',
    apiKeys: [],
    providers: [],
    menuOpen: false,
    prefDataset: null,
  };
  const commvaultState = {
    tab: 'backups',
    jobs: [],
    loading: false,
    lastUpdated: null,
    totalAvailable: null,
    error: null,
    limit: 0,
    sinceHours: 24,
    lastFetchMs: 0,
    lastFetchKey: null,
    statusFilter: '',
    statuses: [],
    search: '',
    searchTokens: [],
  };
  const commvaultPlansState = {
    plans: [],
    loading: false,
    error: null,
    lastFetchMs: 0,
    lastFetchKey: null,
    generatedAt: null,
    totalPlans: 0,
    planType: 'all',
    planTypes: [],
  };
  const commvaultStorageState = {
    pools: [],
    loading: false,
    error: null,
    fetchedAt: null,
    selectedId: null,
    lastFetchMs: 0,
  };
  const commvaultServerState = {
    loading: false,
    refreshing: false,
    query: '',
    clientIdentifier: '',
    selectedClientId: null,
    selectedClientName: '',
    jobs: [],
    stats: null,
    jobMetrics: null,
    summary: null,
    retainedOnly: true,
    sinceHours: 24,
    jobLimit: 500,
    suggestions: [],
    suggestionSerial: 0,
    requestSerial: 0,
    lastFetchKey: null,
    lastFetchMs: 0,
    lastIdentifier: '',
    error: null,
  };
  const commvaultChartState = new Map();
  let commvaultChartTooltip = null;
  let commvaultServerSuggestionTimer = null;
  let commvaultStatusTimeout = null;
  let commvaultPlansStatusTimeout = null;
  const ALL_VCENTER_ID = '__all__';

  const vcenterState = {
    instances: [],
    activeId: null,
    loading: false,
    error: null,
    vms: [],
    filtered: [],
    search: '',
    lastFetchAt: 0,
    meta: null,
    statusOverride: null,
  };
  const POWER_STATE_LABELS = {
    POWERED_ON: { label: 'On', className: 'on', icon: '●' },
    POWERED_OFF: { label: 'Off', className: 'off', icon: '○' },
    SUSPENDED: { label: 'Suspended', className: 'suspended', icon: '◐' },
  };

  function formatVmPowerState(vm) {
    const state = (vm?.power_state || '').toUpperCase();
    const meta = POWER_STATE_LABELS[state] || { label: state || 'Unknown', className: 'unknown', icon: '◌' };
    const badge = document.createElement('span');
    badge.className = `vcenter-state vcenter-state--${meta.className}`;
    badge.textContent = `${meta.icon} ${meta.label}`;
    badge.title = state || 'Unknown';
    return badge;
  }

  function fallbackDnsName(vm) {
    if (vm?.guest_host_name && vm.guest_host_name.trim()) return vm.guest_host_name.trim();
    const name = vm?.name;
    if (!name || typeof name !== 'string') return '';
    const trimmed = name.trim();
    if (!trimmed) return '';
    return trimmed.includes('.') ? trimmed.split('.')[0] : trimmed;
  }

  function humanizeToolsStatus(raw) {
    if (!raw || typeof raw !== 'string') return '';
    const normalized = raw.trim();
    const map = {
      toolsOk: 'OK',
      toolsOld: 'Out of date',
      toolsNotRunning: 'Not running',
      toolsNotInstalled: 'Not installed',
      toolsBlacklisted: 'Blacklisted',
      toolsTooOld: 'Too old',
      toolsTooNew: 'Too new',
    };
    if (map[normalized]) return map[normalized];
    return normalized.replace(/_/g, ' ');
  }

  function formatVmTools(vm) {
    if (!vm) return '';
    const parts = [];
    const status = humanizeToolsStatus(vm.tools_status || vm.tools_run_state || vm.tools_version_status);
    if (status) parts.push(status);
    const version = vm.tools_version && String(vm.tools_version).trim();
    if (version) parts.push(`v${version}`);
    const text = parts.length ? parts.join(' • ') : 'Unknown';
    const titleParts = [];
    if (vm.tools_version_status && vm.tools_version_status !== vm.tools_status) {
      titleParts.push(`Status: ${humanizeToolsStatus(vm.tools_version_status)}`);
    }
    if (vm.tools_install_type) {
      titleParts.push(`Install: ${String(vm.tools_install_type).trim()}`);
    }
    if (vm.tools_run_state && vm.tools_run_state !== vm.tools_status) {
      titleParts.push(`Run state: ${String(vm.tools_run_state).trim()}`);
    }
    const title = titleParts.join('\n');
    const statusClass = status ? status.toLowerCase().replace(/\s+/g, '-') : 'unknown';
    return {
      text,
      className: `vcenter-tools vcenter-tools--${statusClass}`,
      title: title || undefined,
    };
  }

  function getVmIdentifier(vm) {
    if (!vm || typeof vm !== 'object') return '';
    const candidates = [
      vm.id,
      vm.vm_id,
      vm.vmId,
      vm.vmID,
      vm.instance_uuid,
      vm.instanceUuid,
      vm.instanceUUID,
    ];
    for (let i = 0; i < candidates.length; i += 1) {
      const candidate = candidates[i];
      if (candidate == null) continue;
      const value = String(candidate).trim();
      if (value) return value;
    }
    return '';
  }

  function getVmConfigId(vm) {
    if (!vm || typeof vm !== 'object') return '';
    const candidates = [
      vm.__vcenterId,
      vm.config_id,
      vm.configId,
      vm.configID,
      vm.vcenter_config_id,
    ];
    for (let i = 0; i < candidates.length; i += 1) {
      const candidate = candidates[i];
      if (candidate == null) continue;
      const value = String(candidate).trim();
      if (value) return value;
    }
    return '';
  }

  function normalizeVCenterVm(vm) {
    if (!vm || typeof vm !== 'object') {
      return { id: '', name: '' };
    }
    const identifier = getVmIdentifier(vm);
    let displayName = '';
    if (typeof vm.name === 'string' && vm.name.trim()) {
      displayName = vm.name;
    } else {
      displayName = identifier;
    }
    return { ...vm, id: identifier, name: displayName };
  }

  function buildVCenterLink(vm) {
    const snakeUrl = typeof vm?.vcenter_url === 'string' ? vm.vcenter_url.trim() : '';
    const camelUrl = typeof vm?.vcenterUrl === 'string' ? vm.vcenterUrl.trim() : '';
    const href = snakeUrl || camelUrl;
    if (!href) return '';
    const anchor = document.createElement('a');
    anchor.href = href;
    anchor.target = '_blank';
    anchor.rel = 'noreferrer noopener';
    anchor.className = 'vcenter-link';
    anchor.title = 'Open virtual machine in vCenter (opens in new tab)';
    anchor.setAttribute('aria-label', 'Open in vCenter (opens in new tab)');
    const icon = document.createElement('img');
    icon.className = 'vcenter-link-icon';
    icon.src = 'icons/vcenter.ico?v=1';
    icon.alt = '';
    icon.width = 16;
    icon.height = 16;
    const sr = document.createElement('span');
    sr.className = 'sr-only';
    sr.textContent = 'Open in vCenter';
    anchor.append(icon, sr);
    return anchor;
  }

  function createVmNameCell(vm) {
    const identifier = getVmIdentifier(vm);
    let label = '';
    if (vm && typeof vm.name === 'string') {
      label = vm.name.trim();
    }
    if (!label) {
      label = identifier;
    }
    if (!identifier) return label;
    const derivedConfigId = getVmConfigId(vm);
    const configId = derivedConfigId
      || (vcenterState.activeId && vcenterState.activeId !== ALL_VCENTER_ID ? vcenterState.activeId : '');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'vcenter-name-link';
    button.textContent = label || identifier;
    button.dataset.vmId = identifier;
    if (configId) {
      button.dataset.vcenterId = configId;
    }
    button.addEventListener('click', () => openVCenterVmModal(vm, configId));
    return button;
  }

  function openVCenterVmModal(vm, preferredConfigId) {
    const identifier = getVmIdentifier(vm);
    let configId = '';
    if (preferredConfigId && String(preferredConfigId).trim()) {
      configId = String(preferredConfigId).trim();
    } else {
      const vmConfigId = getVmConfigId(vm);
      if (vmConfigId) {
        configId = vmConfigId;
      } else if (vcenterState.activeId && vcenterState.activeId !== ALL_VCENTER_ID) {
        configId = vcenterState.activeId;
      }
    }
    if (!identifier || !configId) return;
    const url = new URL('/app/vcenter/view.html', window.location.origin);
    url.searchParams.set('config', configId);
    url.searchParams.set('vm', identifier);
    const modal = document.createElement('div');
    modal.className = 'modal-backdrop';
    modal.innerHTML = `
      <div class="modal-dialog" role="dialog" aria-modal="true">
        <button type="button" class="modal-close" aria-label="Close">×</button>
        <div class="modal-frame">
          <iframe src="${url.toString()}" title="VM details" loading="lazy"></iframe>
        </div>
      </div>
    `;
    function dismiss() {
      document.removeEventListener('keydown', onKeyDown);
      modal.removeEventListener('click', onBackdrop);
      modal.remove();
    }
    function onKeyDown(event) {
      if (event.key === 'Escape') {
        dismiss();
      }
    }
    function onBackdrop(event) {
      if (event.target === modal || event.target.classList.contains('modal-close')) {
        dismiss();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    modal.addEventListener('click', onBackdrop);
    document.body.appendChild(modal);
  }

  function formatVCenterUpdated() {
    const generatedIso = vcenterState.meta?.generated_at;
    if (!generatedIso) return '';
    try {
      return amsDateTimeString(new Date(generatedIso));
    } catch {
      return generatedIso;
    }
  }

  function formatVmCpu(vm) {
    const count = Number(vm?.cpu_count);
    if (!Number.isFinite(count) || count <= 0) return '—';
    return `${count}`;
  }

  function formatVmMemory(vm) {
    const mib = Number(vm?.memory_mib);
    if (!Number.isFinite(mib) || mib <= 0) return '—';
    if (mib >= 1024) {
      const gib = mib / 1024;
      const formatted = gib >= 10 ? Math.round(gib).toString() : gib.toFixed(1).replace(/\.0$/, '');
      return `${formatted} GiB`;
    }
    return `${mib.toLocaleString()} MiB`;
  }

  const BASE_VCENTER_COLUMNS = [
    { label: '#', className: 'vcenter-col-index', render: (_vm, idx) => idx + 1 },
    { label: 'Display Name', className: 'vcenter-col-name', render: (vm) => createVmNameCell(vm) },
    { label: 'State', className: 'vcenter-col-state', render: (vm) => formatVmPowerState(vm) },
    { label: 'Link', className: 'vcenter-col-link', render: (vm) => buildVCenterLink(vm) },
    { label: 'DC', className: 'vcenter-col-dc', render: (vm) => vm?.datacenter || '—' },
    { label: 'Cluster', className: 'vcenter-col-cluster', render: (vm) => vm?.cluster || '—' },
    { label: 'Folder', className: 'vcenter-col-folder', render: (vm) => vm?.folder || '—' },
    { label: 'CPU', className: 'vcenter-col-cpu', render: (vm) => formatVmCpu(vm) },
    { label: 'Mem', className: 'vcenter-col-mem', render: (vm) => formatVmMemory(vm) },
    { label: 'Updated', className: 'vcenter-col-updated', render: () => formatVCenterUpdated() },
  ];

  function renderVCenterSource(vm) {
    const name = typeof vm?.__vcenterName === 'string' ? vm.__vcenterName.trim() : '';
    if (!name) {
      return vcenterState.activeId === ALL_VCENTER_ID ? '—' : '';
    }
    const pill = document.createElement('span');
    pill.className = 'vcenter-source-pill';
    pill.textContent = name;
    pill.title = `vCenter: ${name}`;
    return pill;
  }

  function getVCenterColumns() {
    const columns = BASE_VCENTER_COLUMNS.slice();
    if (vcenterState.activeId === ALL_VCENTER_ID) {
      columns.splice(1, 0, {
        label: 'vCenter',
        className: 'vcenter-col-source',
        render: (vm) => renderVCenterSource(vm),
      });
    }
    return columns;
  }

  function recalcAggregateInstanceMeta() {
    const aggregateIndex = vcenterState.instances.findIndex((inst) => inst.id === ALL_VCENTER_ID);
    if (aggregateIndex === -1) return;
    const realInstances = vcenterState.instances.filter((inst) => inst && inst.id && inst.id !== ALL_VCENTER_ID);
    let totalCount = 0;
    let hasCount = false;
    let latestDate = null;
    realInstances.forEach((inst) => {
      const count = inst?.vm_count;
      if (typeof count === 'number' && Number.isFinite(count)) {
        totalCount += count;
        hasCount = true;
      }
      const raw = inst?.last_refresh;
      if (typeof raw === 'string' && raw) {
        const dt = new Date(raw);
        if (!Number.isNaN(dt.valueOf())) {
          if (!latestDate || dt > latestDate) {
            latestDate = dt;
          }
        }
      }
    });
    const aggregateEntry = {
      ...vcenterState.instances[aggregateIndex],
      vm_count: hasCount ? totalCount : realInstances.length ? null : 0,
      last_refresh: latestDate ? latestDate.toISOString() : null,
      aggregate: true,
    };
    vcenterState.instances[aggregateIndex] = aggregateEntry;
  }
  let currentUser = null;
  const permissionState = {
    user: new Set(),
    ready: false,
  };

  function setUserPermissions(perms) {
    const next = new Set();
    if (Array.isArray(perms)) {
      perms.forEach((code) => {
        if (code && typeof code === 'string') next.add(code);
      });
    }
    permissionState.user = next;
    permissionState.ready = true;
    applyRoleRestrictions();
    if (canAccessPage('vcenter') && vcenterState.instances.length === 0) {
      loadVCenterInstances().catch(() => {});
    }
  }

  function hasPermission(code) {
    if (!permissionState.ready) return true;
    if (!code) return false;
    return permissionState.user.has(code);
  }

  function setCommvaultSearch(value) {
    const text = (value || '').trim();
    commvaultState.search = text;
    commvaultState.searchTokens = text ? text.toLowerCase().split(/\s+/).filter(Boolean) : [];
  }

  setCommvaultSearch(commvaultState.search || '');
  if ($commvaultServerSince) {
    const initialSince = Number($commvaultServerSince.value);
    commvaultServerState.sinceHours = Number.isFinite(initialSince) ? Math.max(0, initialSince) : 0;
  }
  if ($commvaultServerLimit) {
    const initialLimit = Number($commvaultServerLimit.value);
    commvaultServerState.jobLimit = Number.isFinite(initialLimit) ? Math.max(0, initialLimit) : 0;
  }
  if ($commvaultServerRetained) {
    commvaultServerState.retainedOnly = !!$commvaultServerRetained.checked;
  }

  function ensureCommvaultChartTooltip() {
    if (commvaultChartTooltip) return commvaultChartTooltip;
    const tip = document.createElement('div');
    tip.className = 'chart-tooltip';
    tip.hidden = true;
    document.body.appendChild(tip);
    commvaultChartTooltip = tip;
    return tip;
  }

  function hideCommvaultChartTooltip() {
    if (commvaultChartTooltip) {
      commvaultChartTooltip.hidden = true;
    }
  }

  function showCommvaultChartTooltip(content, clientX, clientY) {
    const tip = ensureCommvaultChartTooltip();
    tip.innerHTML = content;
    tip.hidden = false;
    const offset = 14;
    const maxWidth = window.innerWidth - 160;
    const x = Math.min(clientX + offset, maxWidth);
    const y = clientY + offset;
    tip.style.left = `${x}px`;
    tip.style.top = `${y}px`;
  }

  function registerCommvaultChart(canvas, info) {
    if (!canvas) return;
    commvaultChartState.set(canvas, info);
    if (!canvas.dataset.commvaultChartBound) {
      canvas.addEventListener('mousemove', (event) => handleCommvaultChartHover(canvas, event));
      canvas.addEventListener('mouseleave', () => { hideCommvaultChartTooltip(); });
      canvas.dataset.commvaultChartBound = '1';
    }
  }

  function handleCommvaultChartHover(canvas, event) {
    const info = commvaultChartState.get(canvas);
    if (!info || !Array.isArray(info.points) || info.points.length === 0) {
      hideCommvaultChartTooltip();
      return;
    }
    const rect = canvas.getBoundingClientRect();
    const scaleX = rect.width ? canvas.width / rect.width : 1;
    const scaleY = rect.height ? canvas.height / rect.height : 1;
    const pointerX = event.offsetX * scaleX;
    const pointerY = event.offsetY * scaleY;
    let nearest = null;
    let minDistance = Infinity;
    const maxDistance = 18 * Math.max(scaleX, scaleY);
    for (const point of info.points) {
      const dx = pointerX - point.x;
      const dy = pointerY - point.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < minDistance) {
        minDistance = dist;
        nearest = point;
      }
    }
    if (!nearest || minDistance > maxDistance) {
      hideCommvaultChartTooltip();
      return;
    }
    const valueLine = nearest.valueLabel ? `<div>${escapeHtml(nearest.valueLabel)}</div>` : '';
    const dateLine = nearest.dateLabel ? `<div class="chart-tooltip-meta">${escapeHtml(nearest.dateLabel)}</div>` : '';
    const content = `<strong>${escapeHtml(nearest.datasetLabel || 'Value')}</strong>${valueLine}${dateLine}`;
    showCommvaultChartTooltip(content, event.clientX, event.clientY);
  }

  const COMMVAULT_STORAGE_REFRESH_INTERVAL_MS = 60_000;
  const COMMVAULT_TAB_KEY = 'commvault_active_tab';
  const storedCommvaultTab = (() => {
    try {
      const value = localStorage.getItem(COMMVAULT_TAB_KEY);
      if (value === 'reports') return 'servers';
      if (value && ['backups', 'plans', 'storage', 'servers'].includes(value)) return value;
    } catch {}
    return 'backups';
  })();
  commvaultState.tab = storedCommvaultTab;

  const themeWasStored = (() => {
    try { return !!localStorage.getItem(THEME_STORAGE_KEY); }
    catch (_) { return false; }
  })();

  mountThemeToggle($themeRoot);

  if (!themeWasStored) {
    try {
      fetch(`${API_BASE}/config/ui`).then((res) => {
        if (!res.ok) return null;
        return res.json();
      }).then((data) => {
        if (!data || !data.theme_default) return;
        applyThemeClass(data.theme_default);
      }).catch(() => {});
    } catch (_) { /* ignore */ }
  }

  async function loadChatConfig() {
    try {
      const res = await fetch(`${API_BASE}/config/chat`);
      if (!res.ok) return;
      const data = await res.json();
      if (data && typeof data.system_prompt === 'string') {
        chatConfig.systemPrompt = data.system_prompt;
      }
      if (data && typeof data.temperature === 'number' && Number.isFinite(data.temperature)) {
        chatConfig.temperature = data.temperature;
      }
    } catch (_) { /* ignore */ }
  }

  function humanizeRole(role) {
    if (!role) return '';
    return role.charAt(0).toUpperCase() + role.slice(1);
  }

  function normalizeStatusMessage(input) {
    if (input == null) return '';
    if (typeof input === 'string') return input;
    if (Array.isArray(input)) {
      const parts = input.map(normalizeStatusMessage).filter(Boolean);
      return parts.join('; ');
    }
    if (typeof input === 'object') {
      if (typeof input.detail !== 'undefined') return normalizeStatusMessage(input.detail);
      if (typeof input.msg === 'string') return input.msg;
      try { return JSON.stringify(input); } catch { return String(input); }
    }
    return String(input);
  }

  function flashStatus(el, message, timeout = 3200) {
    if (!el) return;
    const text = normalizeStatusMessage(message);
    el.textContent = text;
    if (message) {
      setTimeout(() => {
        if (el.textContent === text) el.textContent = '';
      }, timeout);
    }
  }

  function providerLabel(id) {
    const map = {
      openai: 'OpenAI',
      openrouter: 'OpenRouter',
      claude: 'Claude',
      gemini: 'Gemini',
    };
    return map[id] || id?.toUpperCase() || 'Provider';
  }

  function setUserMenu(open) {
    accountState.menuOpen = !!open;
    if ($userMenu) {
      if (open) {
        $userMenu.hidden = false;
        $userMenu.classList.add('open');
      } else {
        $userMenu.classList.remove('open');
        $userMenu.hidden = true;
      }
    }
    if ($userMenuToggle) $userMenuToggle.setAttribute('aria-expanded', String(open));
  }

  function updateTopbarUser() {
    const user = accountState.user || currentUser;
    if (!user) return;
    const primary = user.display_name || user.username || 'Account';
    const subtitleId = user.username || user.email || primary;
    const secondary = humanizeRole(user.role);
    const fallback = user.username || user.display_name || primary;
    if ($userMenuName) $userMenuName.textContent = primary;
    if ($userMenuRole) $userMenuRole.textContent = secondary;
    if ($userMenuNameAlt) $userMenuNameAlt.textContent = fallback;
    if ($userMenuRoleAlt) $userMenuRoleAlt.textContent = secondary;
    if ($accountSubtitle) {
      const meta = [subtitleId];
      if (secondary) meta.push(secondary);
      $accountSubtitle.textContent = meta.join(' • ');
    }
  }

  function populateAccountForms() {
    const user = accountState.user;
    if (user) {
      if ($accountProfileDisplay) $accountProfileDisplay.value = user.display_name || '';
      if ($accountProfileEmail) $accountProfileEmail.value = user.email || '';
    }
    if ($accountPrefDataset) {
      const val = accountState.prefDataset || 'all';
      if (['all', 'devices', 'vms'].includes(val)) {
        $accountPrefDataset.value = val;
      }
    }
  }

  function updateAccountHash() {
    if (page !== 'account') return;
    try {
      const url = new URL(window.location.href);
      url.hash = `#account/${accountState.tab || 'profile'}`;
      history.replaceState(null, '', url.toString());
    } catch (_) { /* ignore */ }
  }

  function showAccountTab(tab) {
    const validTabs = ['profile', 'preferences', 'password', 'tokens'];
    if (!validTabs.includes(tab)) tab = 'profile';
    accountState.tab = tab;
    accountTabs.forEach((btn) => {
      btn.classList.toggle('active', (btn.getAttribute('data-account-tab') || 'profile') === tab);
    });
    accountPanels.forEach((panel) => {
      panel.classList.toggle('active', (panel.getAttribute('data-account-panel') || 'profile') === tab);
    });
    if (tab === 'profile') {
      populateAccountForms();
    }
    if (tab === 'tokens') {
      refreshAccountApiKeys().catch(() => {});
    }
    if (tab === 'preferences') {
      if ($accountPrefDataset && accountState.prefDataset) {
        $accountPrefDataset.value = accountState.prefDataset;
      }
    }
    updateAccountHash();
  }

  function openAccount(tab = 'profile') {
    const wanted = (tab || 'profile').toLowerCase();
    showAccountTab(wanted);
    if (page !== 'account') {
      showPage('account');
    } else {
      updateAccountHash();
    }
  }

  async function loadCurrentUser() {
    try {
      const res = await fetch(`${API_BASE}/auth/me`);
      if (!res.ok) return;
      const data = await res.json();
      currentUser = data;
      accountState.user = data;
      setUserPermissions(Array.isArray(data?.permissions) ? data.permissions : []);
      updateTopbarUser();
      populateAccountForms();
      refreshAccountApiKeys().catch(() => {});
      applyRoleRestrictions();
    } catch (_) { /* ignore */ }
  }

  async function refreshChatProviders() {
    try {
      const res = await fetch(`${API_BASE}/chat/providers`);
      if (!res.ok) return null;
      const data = await res.json();
      chatProvidersState.items = Array.isArray(data?.providers) ? data.providers : [];
      accountState.providers = chatProvidersState.items;
      renderAccountApiKeys();
      return data;
    } catch (_) {
      return null;
    }
  }

  async function refreshAccountApiKeys() {
    try {
      const res = await fetch(`${API_BASE}/profile/api-keys`);
      if (!res.ok) return;
      const data = await res.json();
      if (Array.isArray(data)) {
        accountState.apiKeys = data;
        renderAccountApiKeys();
      }
    } catch (_) { /* ignore */ }
  }

  function renderAccountApiKeys() {
    if (!$accountApiList) return;
    const providers = accountState.providers.length
      ? accountState.providers
      : defaultChatProviders.map((id) => ({ id }));

    const userKeys = Array.isArray(accountState.apiKeys) ? accountState.apiKeys : [];
    $accountApiList.innerHTML = '';

    if ($accountApiProvider) {
      const current = $accountApiProvider.value;
      $accountApiProvider.innerHTML = '';
      providers.forEach((info) => {
        if (!info || !info.id) return;
        const opt = document.createElement('option');
        opt.value = info.id;
        opt.textContent = providerLabel(info.id);
        $accountApiProvider.appendChild(opt);
      });
      if (current && Array.from($accountApiProvider.options).some((o) => o.value === current)) {
        $accountApiProvider.value = current;
      }
    }

    if (!providers.length) {
      const empty = document.createElement('div');
      empty.className = 'account-token-empty';
      empty.textContent = 'No providers available.';
      $accountApiList.appendChild(empty);
      return;
    }

    providers.forEach((info) => {
      if (!info || !info.id) return;
      const pid = info.id;
      const friendly = providerLabel(pid);
      const userKey = userKeys.find((k) => k.provider === pid) || null;
      const source = userKey ? 'user' : (info.key_source || null);
      const badgeClass = source === 'user' ? 'badge-user' : source === 'global' ? 'badge-global' : source === 'env' ? 'badge-env' : '';
      const badgeLabel = source === 'user' ? 'Your override' : source === 'global' ? 'Global default' : source === 'env' ? 'Environment' : 'None';

      const card = document.createElement('div');
      card.className = 'account-token-card';
      card.dataset.provider = pid;

      const header = document.createElement('div');
      header.className = 'account-token-card-header';
      const meta = document.createElement('div');
      meta.className = 'account-token-card-meta';
      const title = document.createElement('strong');
      title.textContent = friendly;
      const metaRow = document.createElement('span');
      metaRow.innerHTML = `Effective key: <span class="badge ${badgeClass}">${badgeLabel}</span>`;
      meta.appendChild(title);
      meta.appendChild(metaRow);
      if (userKey?.label) {
        const labelRow = document.createElement('span');
        labelRow.textContent = `Label: ${userKey.label}`;
        meta.appendChild(labelRow);
      } else if (info.label) {
        const labelRow = document.createElement('span');
        labelRow.textContent = `Label: ${info.label}`;
        meta.appendChild(labelRow);
      }
      header.appendChild(meta);

      const actions = document.createElement('div');
      actions.className = 'account-token-card-actions';
      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'btn ghost';
      editBtn.textContent = userKey ? 'Update key' : 'Add key';
      editBtn.addEventListener('click', () => {
        if ($accountApiProvider) $accountApiProvider.value = pid;
        if ($accountApiLabel) $accountApiLabel.value = userKey?.label || '';
        if ($accountApiSecret) $accountApiSecret.value = '';
        if ($accountApiSecret) $accountApiSecret.focus();
      });
      actions.appendChild(editBtn);
      if (userKey) {
        const delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'btn ghost';
        delBtn.textContent = 'Remove override';
        delBtn.addEventListener('click', () => deleteAccountApiKey(pid));
        actions.appendChild(delBtn);
      }
      header.appendChild(actions);

      card.appendChild(header);
      if (!userKey && !info.api_key) {
        const hint = document.createElement('div');
        hint.className = 'account-token-empty';
        hint.textContent = 'No key configured yet.';
        card.appendChild(hint);
      }
      $accountApiList.appendChild(card);
    });
  }

  async function deleteAccountApiKey(provider) {
    if (!provider) return;
    try {
      const res = await fetch(`${API_BASE}/profile/api-keys/${encodeURIComponent(provider)}`, { method: 'DELETE' });
      if (!res.ok) {
        const msg = await res.json().catch(() => ({}));
        flashStatus($accountApiStatus, msg?.detail || 'Failed to delete key.');
        return;
      }
      await Promise.all([
        refreshAccountApiKeys(),
        refreshChatProviders(),
      ]);
      flashStatus($accountApiStatus, 'Override removed.');
    } catch (err) {
      flashStatus($accountApiStatus, 'Unable to delete key.');
    }
  }

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
  const savedDatasetPref = (() => {
    try {
      const val = localStorage.getItem(ACCOUNT_DATASET_PREF_KEY);
      if (val && ['all', 'devices', 'vms'].includes(val)) return val;
    } catch {}
    return null;
  })();
  let dataset = savedDatasetPref || 'all';
  accountState.prefDataset = dataset;
  let page = 'export';
  const PAGE_PERSIST_KEY = 'enreach_active_page_v1';
  const ROUTABLE_PAGE_KEYS = [
    'search',
    'tools',
    'zabbix',
    'netbox',
    'jira',
    'confluence',
    'chat',
    'export',
    'commvault',
    'vcenter',
    'tasks',
    'zhost',
    'suggestions',
    'account',
    'admin',
  ];
  const ROUTABLE_PAGE_SET = new Set(ROUTABLE_PAGE_KEYS);
  const KNOWN_PAGE_KEYS = new Set([...ROUTABLE_PAGE_KEYS, 'suggestion-detail']);
  const TASK_REFRESH_CACHE_MS = 45000;
  const normalisePageValue = (value) => {
    if (!value) return null;
    const lower = String(value).toLowerCase();
    return KNOWN_PAGE_KEYS.has(lower) ? lower : null;
  };
  const persistablePage = (value) => {
    const normalised = normalisePageValue(value);
    if (!normalised) return null;
    if (normalised === 'suggestion-detail') return 'suggestions';
    if (normalised === 'zhost') return 'zabbix';
    return normalised;
  };
  const persistActivePage = (value) => {
    const storable = persistablePage(value);
    if (!storable) return;
    try { localStorage.setItem(PAGE_PERSIST_KEY, storable); } catch {}
  };
  const readPersistedPage = () => {
    try {
      const stored = localStorage.getItem(PAGE_PERSIST_KEY);
      return normalisePageValue(stored);
    } catch {
      return null;
    }
  };
  const suggestionState = {
    items: [],
    meta: { classifications: [], statuses: [] },
    current: null,
    route: { mode: 'list', id: null },
    loading: false,
  };
  const adminState = {
    settings: [],
    backup: {},
    loading: false,
    activeTab: 'zabbix',
    users: [],
    selectedUser: null,
    globalApiKeys: [],
    editingGlobalKey: false,
    roles: [],
    roleCapabilities: [],
    vcenters: [],
    vcenterLoading: false,
    editingVCenter: null,
  };
  const chatConfig = {
    systemPrompt: '',
    temperature: null,
  };
  const chatSessionsState = {
    items: [],
    active: null,
    loading: false,
  };
  const chatExamplesState = {
    items: [],
  };
  let pendingToolContext = null;
  let chatToolContextLoading = false;
  const toolsState = {
    items: [],
    loading: false,
    error: null,
    search: '',
    activeTag: 'all',
  };
  const TASKS_LAYOUT_STORAGE_KEY = 'tasks_layout_mode_v1';
  const storedTasksLayout = (() => {
    try {
      const value = localStorage.getItem(TASKS_LAYOUT_STORAGE_KEY);
      return value === 'rows' ? 'rows' : 'cards';
    } catch {
      return 'cards';
    }
  })();
  const tasksState = {
    items: [],
    loading: false,
    error: null,
    lastFetchMs: 0,
    bulkRunning: false,
    layout: storedTasksLayout,
  };
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

  function toEpochSeconds(value) {
    if (value == null) return null;
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const ts = Date.parse(value);
    if (Number.isNaN(ts)) return null;
    return Math.floor(ts / 1000);
  }

  function formatRelativeTime(epochSeconds) {
    const seconds = Number(epochSeconds);
    if (!Number.isFinite(seconds) || seconds <= 0) return 'Never';
    const nowMs = Date.now();
    const diffMs = Math.max(0, nowMs - seconds * 1000);
    const minuteMs = 60 * 1000;
    if (diffMs < minuteMs) return 'just now';
    const minutes = Math.round(diffMs / minuteMs);
    if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
    const hours = Math.round(diffMs / (60 * minuteMs));
    if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
    const days = Math.round(diffMs / (24 * 60 * minuteMs));
    if (days < 7) return `${days} day${days === 1 ? '' : 's'} ago`;
    const weeks = Math.round(days / 7);
    if (weeks < 5) return `${weeks} week${weeks === 1 ? '' : 's'} ago`;
    const date = new Date(seconds * 1000);
    if (Number.isNaN(date.valueOf())) return 'Some time ago';
    return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  }

  function formatAbsoluteDate(iso, epochSeconds) {
    if (iso) {
      const dt = new Date(iso);
      if (!Number.isNaN(dt.valueOf())) return dt.toLocaleString();
    }
    if (Number.isFinite(epochSeconds)) {
      const dt = new Date(epochSeconds * 1000);
      if (!Number.isNaN(dt.valueOf())) return dt.toLocaleString();
    }
    return 'Unknown';
  }

  function applyTaskSnapshot(target, snapshot) {
    if (!snapshot || typeof snapshot !== 'object') return;
    if ('id' in snapshot && snapshot.id) target.id = snapshot.id;
    if ('label' in snapshot && snapshot.label != null) target.label = snapshot.label;
    if ('description' in snapshot) target.description = snapshot.description ?? '';
    if ('last_updated' in snapshot) target.lastUpdated = snapshot.last_updated || null;
    if ('last_updated_epoch' in snapshot) {
      const epoch = Number(snapshot.last_updated_epoch);
      target.lastUpdatedEpoch = Number.isFinite(epoch) ? epoch : null;
    }
    if ('file_count' in snapshot) {
      const count = Number(snapshot.file_count);
      target.fileCount = Number.isFinite(count) ? count : 0;
    }
    if ('present_files' in snapshot) {
      const present = Number(snapshot.present_files);
      target.presentFiles = Number.isFinite(present) ? present : 0;
    }
    if (Array.isArray(snapshot.command)) {
      target.command = snapshot.command.slice();
    }
    if ('command_display' in snapshot) {
      target.commandDisplay = snapshot.command_display || '';
    }
    if ('can_refresh' in snapshot) {
      target.canRefresh = !!snapshot.can_refresh;
    }
    if (snapshot.context && typeof snapshot.context === 'object') {
      target.context = { ...snapshot.context };
    }
    if (snapshot.extras && typeof snapshot.extras === 'object') {
      target.extras = { ...snapshot.extras };
    }
    if ('since_source' in snapshot) {
      target.sinceSource = snapshot.since_source ?? null;
    }
    if ('since_source_modified' in snapshot) {
      target.sinceSourceModified = snapshot.since_source_modified ?? null;
    }
  }

  function mergeTaskItem(raw, prev) {
    const base = {
      id: prev?.id || raw?.id || '',
      label: prev?.label || raw?.label || raw?.id || 'Dataset',
      description: prev?.description || '',
      lastUpdated: prev?.lastUpdated || null,
      lastUpdatedEpoch: prev?.lastUpdatedEpoch ?? null,
      fileCount: prev?.fileCount ?? 0,
      presentFiles: prev?.presentFiles ?? 0,
      command: prev?.command ? prev.command.slice() : null,
      commandDisplay: prev?.commandDisplay || '',
      canRefresh: prev?.canRefresh ?? false,
      context: prev?.context ? { ...prev.context } : {},
      extras: prev?.extras ? { ...prev.extras } : {},
      sinceSource: prev?.sinceSource ?? null,
      sinceSourceModified: prev?.sinceSourceModified ?? null,
      running: prev?.running ?? false,
      statusMessage: prev?.statusMessage || '',
      statusLevel: prev?.statusLevel || '',
      output: prev?.output ? prev.output.slice() : [],
      outputOpen: prev?.outputOpen ?? false,
      lastRunAt: prev?.lastRunAt ?? null,
      lastReturnCode: prev?.lastReturnCode ?? null,
      lastSuccess: prev?.lastSuccess ?? null,
    };
    applyTaskSnapshot(base, raw);
    if (!base.id && raw?.id) base.id = raw.id;
    return base;
  }

  function computeTaskStatus(item) {
    if (item.running) {
      return { text: 'Running command…', className: 'running' };
    }
    if (item.statusMessage) {
      return { text: item.statusMessage, className: item.statusLevel || '' };
    }
    const runEpoch = toEpochSeconds(item.lastRunAt);
    if (item.lastSuccess === true) {
      const suffix = runEpoch ? ` (${formatRelativeTime(runEpoch)})` : '';
      return { text: `Last run succeeded${suffix}`, className: 'success' };
    }
    if (item.lastSuccess === false) {
      const exitCode = item.lastReturnCode ?? 'error';
      const suffix = runEpoch ? ` (${formatRelativeTime(runEpoch)})` : '';
      return { text: `Last run failed (exit ${exitCode})${suffix}`, className: 'error' };
    }
    if (Number.isFinite(item.lastUpdatedEpoch) && item.lastUpdatedEpoch) {
      return { text: `Ready · updated ${formatRelativeTime(item.lastUpdatedEpoch)}`, className: '' };
    }
    return { text: 'No cached data yet', className: '' };
  }

  function taskCardHtml(item, layout) {
    const classes = ['tasks-card'];
    if (item.running) classes.push('running');
    const isRowLayout = layout === 'rows';
    classes.push(isRowLayout ? 'tasks-card--row' : 'tasks-card--card');
    const updatedTitle = formatAbsoluteDate(item.lastUpdated, item.lastUpdatedEpoch);
    const updatedRelative = Number.isFinite(item.lastUpdatedEpoch) && item.lastUpdatedEpoch
      ? formatRelativeTime(item.lastUpdatedEpoch)
      : 'Never updated';
    const filesLabel = `${item.presentFiles ?? 0}/${item.fileCount ?? 0} file${(item.fileCount ?? 0) === 1 ? '' : 's'}`;
    const sinceLabel = item.extras && Number.isFinite(item.extras.computed_since_hours)
      ? `Window ${item.extras.computed_since_hours}h`
      : '';
    const metaPieces = [
      `<span title="${escapeHtml(updatedTitle)}">🕒 ${escapeHtml(updatedRelative)}</span>`,
      `<span>📦 ${escapeHtml(filesLabel)}</span>`,
    ];
    if (sinceLabel) metaPieces.push(`<span>⏱️ ${escapeHtml(sinceLabel)}</span>`);
    if (item.context && item.context.orphan) {
      metaPieces.push('<span>⚠️ Orphan cache</span>');
    }
    const statusInfo = computeTaskStatus(item);
    const logHtml = !isRowLayout && item.output && item.output.length
      ? `<details class="tasks-card-log"${item.outputOpen ? ' open' : ''}>
           <summary>Execution log</summary>
           <pre>${escapeHtml(item.output.join('\n'))}</pre>
         </details>`
      : '';
    const buttonDisabled = (!item.canRefresh || item.running || tasksState.bulkRunning) ? 'disabled' : '';
    const buttonLabel = item.running ? 'Updating…' : 'Update';
    if (isRowLayout) {
      return `
        <div class="${classes.join(' ')}" data-task-id="${escapeHtml(item.id)}">
          <div class="tasks-row-button">
            <button class="btn" type="button" data-task-action="run" data-task-id="${escapeHtml(item.id)}" ${buttonDisabled}>
              ${escapeHtml(buttonLabel)}
            </button>
          </div>
          <div class="tasks-row-name" title="${escapeHtml(item.label || item.id)}">${escapeHtml(item.label || item.id)}</div>
          <div class="tasks-row-meta">${metaPieces.join('')}</div>
          <div class="tasks-row-status${statusInfo.className ? ` ${statusInfo.className}` : ''}">${escapeHtml(statusInfo.text)}</div>
        </div>
      `;
    }
    return `
      <div class="${classes.join(' ')}" data-task-id="${escapeHtml(item.id)}">
        <div class="tasks-card-head">
          <h3>${escapeHtml(item.label || item.id)}</h3>
        </div>
        <div class="tasks-card-meta">${metaPieces.join('')}</div>
        <div class="tasks-card-status-line${statusInfo.className ? ` ${statusInfo.className}` : ''}">${escapeHtml(statusInfo.text)}</div>
        ${logHtml}
        <div class="tasks-card-footer">
          <button class="btn" type="button" data-task-action="run" data-task-id="${escapeHtml(item.id)}" ${buttonDisabled}>
            ${escapeHtml(buttonLabel)}
          </button>
        </div>
      </div>
    `;
  }

  function renderTasks() {
    if ($tasksStatus) {
      if (tasksState.loading && !tasksState.error) {
        $tasksStatus.textContent = 'Loading datasets…';
      } else if (tasksState.error) {
        $tasksStatus.textContent = tasksState.error;
      } else if (tasksState.items.length) {
        const count = tasksState.items.length;
        $tasksStatus.textContent = `${count} dataset${count === 1 ? '' : 's'} available.`;
      } else {
        $tasksStatus.textContent = 'No cached datasets were found.';
      }
    }
    if ($tasksUpdateAll) {
      const hasRefreshable = tasksState.items.some((item) => item.canRefresh);
      $tasksUpdateAll.disabled = !hasRefreshable || tasksState.loading || tasksState.bulkRunning;
      $tasksUpdateAll.textContent = tasksState.bulkRunning ? 'Updating…' : 'Update all';
    }
    if ($tasksList) {
      $tasksList.classList.toggle('tasks-list--rows', tasksState.layout === 'rows');
      $tasksList.classList.toggle('tasks-list--cards', tasksState.layout !== 'rows');
    }
    $tasksLayoutButtons.forEach((btn) => {
      const layoutValue = btn.getAttribute('data-tasks-layout');
      btn.classList.toggle('active', layoutValue === tasksState.layout);
    });
    if (!$tasksList) return;
    const openMap = new Map();
    $tasksList.querySelectorAll('.tasks-card-log').forEach((details) => {
      const card = details.closest('.tasks-card');
      if (card && card.dataset.taskId) {
        openMap.set(card.dataset.taskId, details.open);
      }
    });
    if (tasksState.error) {
      $tasksList.innerHTML = `<div class="tasks-empty">${escapeHtml(tasksState.error)}</div>`;
      return;
    }
    if (tasksState.loading && tasksState.items.length === 0) {
      $tasksList.innerHTML = '';
      return;
    }
    if (tasksState.items.length === 0) {
      $tasksList.innerHTML = '<div class="tasks-empty">No cached datasets were found in the data directory.</div>';
      return;
    }
    const html = tasksState.items.map((item) => {
      if (openMap.has(item.id)) {
        item.outputOpen = openMap.get(item.id);
      }
      return taskCardHtml(item, tasksState.layout);
    }).join('');
    $tasksList.innerHTML = html;
  }

  async function loadTasks(force = false) {
    if (tasksState.loading) return;
    const now = Date.now();
    if (!force && tasksState.lastFetchMs && now - tasksState.lastFetchMs < TASK_REFRESH_CACHE_MS) {
      renderTasks();
      return;
    }
    tasksState.loading = true;
    tasksState.error = null;
    renderTasks();
    try {
      const res = await fetch(`${API_BASE}/tasks/datasets`);
      if (!res.ok) {
        let message = `Request failed (${res.status})`;
        try {
          const payload = await res.json();
          if (payload && payload.detail) message = String(payload.detail);
        } catch {
          try {
            const text = await res.text();
            if (text) message = text;
          } catch {}
        }
        throw new Error(message);
      }
      const data = await res.json();
      const rows = Array.isArray(data.datasets) ? data.datasets : [];
      const prevMap = new Map(tasksState.items.map((item) => [item.id, item]));
      tasksState.items = rows.map((raw) => {
        const prev = prevMap.get(raw.id);
        return mergeTaskItem(raw, prev);
      });
      tasksState.lastFetchMs = Date.now();
    } catch (err) {
      console.error(err);
      tasksState.error = err?.message || 'Failed to load datasets.';
    } finally {
      tasksState.loading = false;
      renderTasks();
    }
  }

  async function handleTaskRefresh(datasetId) {
    const item = tasksState.items.find((entry) => entry.id === datasetId);
    if (!item || item.running) return;
    if (!item.canRefresh) {
      item.statusMessage = 'You do not have permission to refresh this dataset.';
      item.statusLevel = 'error';
      renderTasks();
      return;
    }
    item.running = true;
    item.statusMessage = '';
    item.statusLevel = '';
    item.output = [];
    item.outputOpen = true;
    renderTasks();
    try {
      const res = await fetch(`${API_BASE}/tasks/datasets/${encodeURIComponent(datasetId)}/refresh`, { method: 'POST' });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = payload?.detail;
        const message = typeof detail === 'string' ? detail : `Command failed (${res.status})`;
        item.statusMessage = message;
        item.statusLevel = 'error';
        item.lastSuccess = false;
        item.running = false;
        item.output = [];
        renderTasks();
        return;
      }
      item.running = false;
      item.output = Array.isArray(payload.output) ? payload.output : [];
      item.outputOpen = item.output.length > 0;
      item.lastRunAt = payload.completed_at || payload.started_at || new Date().toISOString();
      item.lastReturnCode = payload.return_code ?? null;
      item.lastSuccess = !!payload.success;
      if (payload.after) {
        applyTaskSnapshot(item, payload.after);
      }
      tasksState.lastFetchMs = Date.now();
      if (!item.lastSuccess) {
        const exitCode = payload.return_code ?? 'error';
        item.statusMessage = `Command failed (exit ${exitCode})`;
        item.statusLevel = 'error';
      } else {
        item.statusMessage = '';
        item.statusLevel = '';
      }
      renderTasks();
    } catch (err) {
      console.error(err);
      item.running = false;
      item.lastSuccess = false;
      item.statusMessage = err?.message || 'Failed to run command.';
      item.statusLevel = 'error';
      item.output = [];
      renderTasks();
    }
  }

  async function handleTaskRefreshAll() {
    if (tasksState.bulkRunning) return;
    const candidates = tasksState.items.filter((item) => item.canRefresh);
    if (!candidates.length) return;
    tasksState.bulkRunning = true;
    renderTasks();
    try {
      for (const item of candidates) {
        await handleTaskRefresh(item.id);
      }
    } finally {
      tasksState.bulkRunning = false;
      renderTasks();
    }
  }

  function setTasksLayout(layout) {
    const next = layout === 'rows' ? 'rows' : 'cards';
    if (tasksState.layout === next) return;
    tasksState.layout = next;
    try { localStorage.setItem(TASKS_LAYOUT_STORAGE_KEY, next); } catch {}
    renderTasks();
  }

  // Tools catalog helpers
  const TOOL_NO_TAG_KEY = '__other__';
  const DEFAULT_CHAT_EXAMPLES = [
    'Show me the latest devices added to NetBox.',
    'What are the current active alerts in Zabbix?',
    'Summarise the recent Jira incidents for Systems Infrastructure.',
    'Search Confluence for the SIP trunk failover runbook.',
  ];

  chatExamplesState.items = DEFAULT_CHAT_EXAMPLES.map((example) => ({ tool: null, example }));

  // Ensure persistent search options remain visible
  function ensurePersistentSearchOptions() {
    const $chatExamples = document.getElementById('chat-examples');
    if (!$chatExamples) return;
    
    // Always show the predefined examples
    const persistentExamples = [
      'Find the Zabbix group ID for Systems Infrastructure.',
      'Search host groups containing Voice.',
      'List the current high and disaster alerts in Zabbix.',
      'Show unacknowledged alerts for the Systems Infrastructure group.',
      'Show the Zabbix alert history for pbx-core over the past 24 hours.',
      'List resolved Zabbix alerts that mentioned packet loss this week.',
    ];
    
    // Clear and rebuild with persistent examples
    $chatExamples.innerHTML = '';
    const fragment = document.createDocumentFragment();
    
    persistentExamples.forEach(example => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chat-suggestion-btn';
      btn.textContent = example;
      btn.setAttribute('data-suggestion', example);
      btn.addEventListener('click', () => {
        insertChatPrompt(example, true);
      });
      fragment.append(btn);
    });
    
    $chatExamples.append(fragment);
  }

  const cssEscape = (value) => {
    const str = String(value ?? '');
    if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') {
      try { return CSS.escape(str); } catch { /* ignore */ }
    }
    return str.replace(/[^a-zA-Z0-9_-]/g, (ch) => `\\${ch}`);
  };

  const formatToolTag = (tag) => {
    if (!tag) return 'Other';
    if (tag === TOOL_NO_TAG_KEY) return 'Other';
    const clean = String(tag).replace(/[_-]+/g, ' ').trim();
    return clean.charAt(0).toUpperCase() + clean.slice(1);
  };

  const computeToolTagCounts = (items) => {
    const counts = new Map();
    for (const tool of items || []) {
      const tags = Array.isArray(tool?.tags) && tool.tags.length ? tool.tags : [TOOL_NO_TAG_KEY];
      for (const tag of tags) counts.set(tag, (counts.get(tag) || 0) + 1);
    }
    return counts;
  };

  const getFilteredTools = () => {
    const term = (toolsState.search || '').trim().toLowerCase();
    const activeTag = toolsState.activeTag || 'all';
    return (toolsState.items || []).filter((tool) => {
      if (activeTag !== 'all') {
        const tags = Array.isArray(tool?.tags) && tool.tags.length ? tool.tags : [TOOL_NO_TAG_KEY];
        if (activeTag === TOOL_NO_TAG_KEY) {
          if (!tags.includes(TOOL_NO_TAG_KEY)) return false;
        } else if (!tags.includes(activeTag)) {
          return false;
        }
      }
      if (!term) return true;
      const haystack = [tool?.name, tool?.summary, tool?.description, tool?.path, tool?.ai_usage];
      if (Array.isArray(tool?.tags)) haystack.push(...tool.tags);
      return haystack.some((value) => typeof value === 'string' && value.toLowerCase().includes(term));
    });
  };

  function renderToolTags() {
    if (!$toolsTags) return;
    $toolsTags.innerHTML = '';
    if (!toolsState.items.length) {
      $toolsTags.hidden = true;
      return;
    }
    $toolsTags.hidden = false;
    const counts = computeToolTagCounts(toolsState.items);
    const fragment = document.createDocumentFragment();

    const makeChip = (key, label, count) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tools-tag-chip';
      if ((toolsState.activeTag || 'all') === key) btn.classList.add('active');
      btn.textContent = `${label} (${count})`;
      btn.addEventListener('click', () => {
        if (toolsState.activeTag === key) return;
        toolsState.activeTag = key;
        hideToolPreview();
        renderTools();
      });
      fragment.append(btn);
    };

    makeChip('all', 'All', toolsState.items.length);
    const sorted = Array.from(counts.entries()).sort((a, b) => {
      const labelA = formatToolTag(a[0]).toLowerCase();
      const labelB = formatToolTag(b[0]).toLowerCase();
      return labelA.localeCompare(labelB);
    });
    for (const [tag, count] of sorted) makeChip(tag, formatToolTag(tag), count);
    $toolsTags.append(fragment);
  }

  function buildToolCurl(tool) {
    const method = String(tool?.method || 'GET').toUpperCase();
    const sample = (tool && typeof tool.sample === 'object' && tool.sample !== null) ? tool.sample : {};
    let path = tool?.path || '/';
    const isQuery = method === 'GET' || method === 'DELETE';
    if (isQuery && sample && typeof sample === 'object') {
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(sample)) {
        if (value === undefined || value === null) continue;
        params.append(String(key), String(value));
      }
      const qs = params.toString();
      if (qs) path += (path.includes('?') ? '&' : '?') + qs;
    }
    let curl = `curl -X ${method} '${path}'`;
    const sampleKeys = sample && typeof sample === 'object' ? Object.keys(sample) : [];
    const extras = [];
    if (!isQuery && sampleKeys.length) {
      curl += ` \
  -H 'Content-Type: application/json' \
  -d '${JSON.stringify(sample)}'`;
      extras.push('', '# Body', JSON.stringify(sample, null, 2));
    } else if (isQuery && sampleKeys.length) {
      extras.push('', '# Parameters', JSON.stringify(sample, null, 2));
    }
    return [curl, ...extras].join('\n');
  }

  function hideToolPreview() {
    if ($toolsPreview) $toolsPreview.hidden = true;
    if ($toolsPreviewBody) $toolsPreviewBody.textContent = '';
    if ($toolsPreviewTitle) $toolsPreviewTitle.textContent = 'Tool result';
  }

  function showToolPreview(tool, detail) {
    if (!$toolsPreview || !$toolsPreviewBody || !$toolsPreviewTitle) return;
    const method = String(detail?.method || tool?.method || 'GET').toUpperCase();
    const url = detail?.url || tool?.path || '';
    const status = detail?.status ? String(detail.status) : '';
    const ok = detail?.ok !== false;
    const body = detail?.body || '';
    const output = detail?.output || '';
    const lines = [`${method} ${url}`];
    if (body) {
      lines.push('', 'Body:');
      lines.push(typeof body === 'string' ? body : JSON.stringify(body, null, 2));
    }
    if (output) {
      lines.push('', ok ? 'Response:' : 'Response (error):');
      lines.push(typeof output === 'string' ? output : JSON.stringify(output, null, 2));
    }
    $toolsPreview.hidden = false;
    const baseTitle = tool?.name || tool?.key || tool?.path || 'Tool';
    $toolsPreviewTitle.textContent = status ? `${baseTitle} — ${status}` : baseTitle;
    $toolsPreviewBody.textContent = lines.join('\n');
  }

  function buildToolRequest(tool) {
    const method = String(tool?.method || 'GET').toUpperCase();
    const sample = tool && typeof tool.sample === 'object' && tool.sample !== null ? tool.sample : {};
    let requestPath = tool?.path || '/';
    const options = { method };
    const isQuery = method === 'GET' || method === 'DELETE';
    if (isQuery) {
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(sample)) {
        if (value === undefined || value === null) continue;
        params.append(String(key), String(value));
      }
      const qs = params.toString();
      if (qs) requestPath += (requestPath.includes('?') ? '&' : '?') + qs;
    } else if (sample && Object.keys(sample).length) {
      options.headers = { 'Content-Type': 'application/json' };
      options.body = JSON.stringify(sample);
    }
    return { requestPath, options, sample };
  }

  const truncateText = (text, limit = 1800) => {
    if (text.length <= limit) return text;
    return `${text.slice(0, limit)}\n… (truncated)`;
  };

  const formatToolValue = (value) => {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    try {
      const text = JSON.stringify(value);
      return text.length > 120 ? `${text.slice(0, 117)}…` : text;
    } catch {
      return String(value);
    }
  };

  function summariseToolItems(tool, items, limit = 5) {
    if (!Array.isArray(items) || !items.length) return 'No items returned.';
    const prefer = ['severity', 'status', 'acknowledged', 'host', 'name', 'title', 'summary', 'clock_iso', 'eventid', 'key'];
    const lines = [];
    const count = Math.min(items.length, limit);
    for (let i = 0; i < count; i += 1) {
      const item = items[i];
      if (item && typeof item === 'object') {
        const parts = [];
        for (const key of prefer) {
          if (item[key] !== undefined) {
            parts.push(`${key}: ${formatToolValue(item[key])}`);
          }
        }
        if (!parts.length) {
          const keys = Object.keys(item).slice(0, 4);
          for (const key of keys) {
            parts.push(`${key}: ${formatToolValue(item[key])}`);
          }
        }
        lines.push(`${i + 1}. ${parts.join(', ')}`);
      } else {
        lines.push(`${i + 1}. ${formatToolValue(item)}`);
      }
    }
    if (items.length > limit) {
      lines.push(`… (+${items.length - limit} more)`);
    }
    return lines.join('\n');
  }

  function summariseAckStats(items) {
    let hasAck = false;
    let unackCount = 0;
    let ackCount = 0;
    for (const item of items) {
      if (!item || typeof item !== 'object' || item.acknowledged === undefined) continue;
      hasAck = true;
      const value = item.acknowledged;
      const isAcked = value === true || value === 1 || value === '1' || value === 'true';
      if (isAcked) ackCount += 1; else unackCount += 1;
    }
    if (!hasAck) return null;
    return `Acknowledged: ${ackCount}, Unacknowledged: ${unackCount}`;
  }

  function summariseToolData(tool, data) {
    if (data === null || data === undefined) return 'No data returned.';
    if (typeof data === 'string') return data;
    if (Array.isArray(data)) {
      return summariseToolItems(tool, data);
    }
    if (typeof data === 'object') {
      if (Array.isArray(data.items)) {
        const summary = summariseToolItems(tool, data.items);
        const ackLine = summariseAckStats(data.items);
        const countLineBase = `Items returned: ${data.items.length}${data.count !== undefined ? ` (count: ${data.count})` : ''}`;
        const countLine = ackLine ? `${countLineBase} | ${ackLine}` : countLineBase;
        return `${countLine}\n${summary}`;
      }
      const keys = Object.keys(data).slice(0, 8);
      if (!keys.length) return 'No fields returned.';
      return keys.map((key) => `${key}: ${formatToolValue(data[key])}`).join('\n');
    }
    return String(data);
  }

  async function prepareToolContextForChat(tool) {
    const { requestPath, options } = buildToolRequest(tool);
    const fetchOptions = { method: options.method };
    if (options.headers) fetchOptions.headers = { ...options.headers };
    if (options.body !== undefined) fetchOptions.body = options.body;
    let res;
    let raw = '';
    try {
      res = await fetch(`${API_BASE}${requestPath}`, fetchOptions);
      raw = await res.text();
    } catch (err) {
      const error = new Error(err?.message || 'Network error while calling tool');
      error.__toolPreview = {
        method: fetchOptions.method,
        url: requestPath,
        status: error.message,
        ok: false,
        body: fetchOptions.body || null,
        output: error.message,
      };
      throw error;
    }
    const statusLine = `${res.status} ${res.statusText || ''}`.trim();
    if (!res.ok) {
      const error = new Error(raw || statusLine || 'Request failed');
      error.__toolPreview = {
        method: fetchOptions.method,
        url: requestPath,
        status: error.message,
        ok: false,
        body: fetchOptions.body || null,
        output: raw || error.message,
      };
      throw error;
    }
    let parsed = null;
    if (raw) {
      try { parsed = JSON.parse(raw); }
      catch (_) { parsed = null; }
    }
    const summary = summariseToolData(tool, parsed ?? raw);
    const previewOutput = parsed ? JSON.stringify(parsed, null, 2) : raw;
    showToolPreview(tool, {
      method: fetchOptions.method,
      url: requestPath,
      status: statusLine,
      ok: true,
      body: fetchOptions.body || null,
      output: previewOutput || '(no content)',
    });
    return {
      label: `${tool?.name || tool?.key || 'Tool'} (${fetchOptions.method} ${requestPath})`,
      text: truncateText(summary, 2000),
    };
  }

  async function copyToolEndpoint(tool, button) {
    const text = `${String(tool?.method || 'GET').toUpperCase()} ${tool?.path || '/'}`;
    const original = button?.textContent;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const tmp = document.createElement('textarea');
        tmp.value = text;
        tmp.style.position = 'fixed';
        tmp.style.opacity = '0';
        document.body.appendChild(tmp);
        tmp.select();
        document.execCommand('copy');
        document.body.removeChild(tmp);
      }
      if (button) {
        button.textContent = 'Copied';
        setTimeout(() => { button.textContent = original || 'Copy endpoint'; }, 1500);
      }
    } catch (err) {
      if (button) {
        button.textContent = 'Copy failed';
        setTimeout(() => { button.textContent = original || 'Copy endpoint'; }, 2000);
      }
    }
  }

  async function runToolSample(tool, button) {
    if (!tool) return;
    const { requestPath, options } = buildToolRequest(tool);
    const fetchOptions = { method: options.method };
    if (options.headers) fetchOptions.headers = { ...options.headers };
    if (options.body !== undefined) fetchOptions.body = options.body;

    const original = button?.textContent;
    if (button) {
      button.disabled = true;
      button.textContent = 'Running...';
    }
    try {
      const res = await fetch(`${API_BASE}${requestPath}`, fetchOptions);
      const statusLine = `${res.status} ${res.statusText || ''}`.trim();
      const raw = await res.text();
      let output = raw;
      if (raw) {
        try { output = JSON.stringify(JSON.parse(raw), null, 2); }
        catch (_) { output = raw; }
      }
      showToolPreview(tool, {
        method: fetchOptions.method,
        url: requestPath,
        status: statusLine,
        ok: res.ok,
        body: fetchOptions.body || null,
        output: output || '(no content)',
      });
      if (!res.ok) throw new Error(output || statusLine || 'Request failed');
    } catch (err) {
      const msg = err?.message || 'Unknown error';
      showToolPreview(tool, {
        method: fetchOptions.method,
        url: requestPath,
        status: msg,
        ok: false,
        body: fetchOptions.body || null,
        output: msg,
      });
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = original || 'Run sample';
      }
    }
  }

  function insertChatPrompt(text, autoSend = false) {
    if (!$chatInput) return;
    const value = String(text || '').trim();
    if (!value) return;
    $chatInput.value = value;
    $chatInput.focus();
    if (autoSend) {
      setTimeout(() => sendChat(), 120);
    }
  }

  async function useToolExample(tool, example) {
    if (!example) return;
    if (chatToolContextLoading) {
      insertChatPrompt(example, true);
      showPage('chat');
      return;
    }
    chatToolContextLoading = true;
    let statusNode = null;
    if ($chatToolsList) {
      statusNode = document.createElement('div');
      statusNode.className = 'chat-tools-status';
      statusNode.textContent = `Loading ${tool?.name || tool?.key || 'tool'} data...`;
      $chatToolsList.prepend(statusNode);
    }
    try {
      const context = await prepareToolContextForChat(tool);
      pendingToolContext = context;
    } catch (err) {
      pendingToolContext = null;
      console.error('Failed to load tool context', err);
      if (err?.__toolPreview) {
        showToolPreview(tool, err.__toolPreview);
      } else {
        showToolPreview(tool, {
          method: String(tool?.method || 'GET').toUpperCase(),
          url: tool?.path || '/',
          status: err?.message || 'Failed to load tool data',
          ok: false,
          body: null,
          output: err?.message || 'Failed to load tool data',
        });
      }
    } finally {
      if (statusNode) statusNode.remove();
      chatToolContextLoading = false;
    }
    insertChatPrompt(example, true);
    showPage('chat');
  }

  function renderTools() {
    if (!$toolsList) return;
    renderToolTags();
    $toolsList.innerHTML = '';
    if (toolsState.loading) {
      const div = document.createElement('div');
      div.className = 'tools-empty';
      div.textContent = 'Loading tools...';
      $toolsList.append(div);
      return;
    }
    if (toolsState.error) {
      const div = document.createElement('div');
      div.className = 'tools-error';
      div.textContent = toolsState.error;
      $toolsList.append(div);
      return;
    }
    const items = getFilteredTools();
    if (!items.length) {
      const div = document.createElement('div');
      div.className = 'tools-empty';
      div.textContent = toolsState.items.length ? 'No tools found for the current filters.' : 'No tools available.';
      $toolsList.append(div);
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const tool of items) {
      const card = document.createElement('article');
      card.className = 'tool-card';
      if (tool?.key) card.dataset.toolKey = tool.key;

      const header = document.createElement('div');
      header.className = 'tool-card-header';

      const headLeft = document.createElement('div');
      headLeft.className = 'tool-card-head';
      const method = document.createElement('span');
      method.className = `tool-method tool-method-${String(tool.method || 'get').toLowerCase()}`;
      method.textContent = String(tool.method || 'GET').toUpperCase();
      const name = document.createElement('h3');
      name.className = 'tool-name';
      name.textContent = tool.name || tool.key || 'Tool';
      const path = document.createElement('code');
      path.className = 'tool-path';
      path.textContent = tool.path || '/';
      headLeft.append(method, name, path);

      const tagWrap = document.createElement('div');
      tagWrap.className = 'tool-card-tags';
      const tags = Array.isArray(tool?.tags) && tool.tags.length ? tool.tags : [TOOL_NO_TAG_KEY];
      for (const tag of tags) {
        const chip = document.createElement('span');
        chip.className = 'tool-tag';
        chip.textContent = formatToolTag(tag);
        chip.addEventListener('click', () => {
          toolsState.activeTag = tag;
          hideToolPreview();
          renderTools();
        });
        tagWrap.append(chip);
      }

      header.append(headLeft, tagWrap);
      card.append(header);

      if (tool.summary) {
        const summary = document.createElement('p');
        summary.className = 'tool-summary';
        summary.textContent = tool.summary;
        card.append(summary);
      }
      if (tool.description) {
        const desc = document.createElement('p');
        desc.className = 'tool-description';
        desc.textContent = tool.description;
        card.append(desc);
      }

      if (Array.isArray(tool.parameters) && tool.parameters.length) {
        const paramSection = document.createElement('div');
        paramSection.className = 'tool-section tool-section-params';
        const title = document.createElement('h4');
        title.textContent = 'Parameters';
        const list = document.createElement('ul');
        list.className = 'tool-param-list';
        for (const param of tool.parameters) {
          const item = document.createElement('li');
          const nameCode = document.createElement('code');
          nameCode.textContent = param.name;
          item.append(nameCode);
          const metaParts = [];
          metaParts.push(param.required ? 'required' : 'optional');
          if (param.type) metaParts.push(param.type);
          if (param.default !== null && param.default !== undefined && param.default !== '') metaParts.push(`default ${param.default}`);
          if (param.example !== null && param.example !== undefined && param.example !== '') metaParts.push(`e.g. ${param.example}`);
          if (metaParts.length) {
            const meta = document.createElement('span');
            meta.className = 'tool-param-meta';
            meta.textContent = metaParts.join(' • ');
            item.append(meta);
          }
          if (param.description) {
            const desc = document.createElement('div');
            desc.className = 'tool-param-desc';
            desc.textContent = param.description;
            item.append(desc);
          }
          list.append(item);
        }
        paramSection.append(title, list);
        card.append(paramSection);
      }

      if (tool.ai_usage) {
        const ai = document.createElement('div');
        ai.className = 'tool-ai-tip';
        ai.innerHTML = `<strong>AI tip:</strong> ${tool.ai_usage}`;
        card.append(ai);
      }

      if (Array.isArray(tool.response_fields) && tool.response_fields.length) {
        const resp = document.createElement('div');
        resp.className = 'tool-response-fields';
        const label = document.createElement('span');
        label.className = 'tool-response-label';
        label.textContent = 'Key fields:';
        const fieldWrap = document.createElement('div');
        fieldWrap.className = 'tool-response-list';
        tool.response_fields.forEach((field) => {
          const code = document.createElement('code');
          code.textContent = field;
          fieldWrap.append(code);
        });
        resp.append(label, fieldWrap);
        card.append(resp);
      }

      if (tool.sample && typeof tool.sample === 'object' && Object.keys(tool.sample).length) {
        const sampleBox = document.createElement('details');
        sampleBox.className = 'tool-sample';
        const sum = document.createElement('summary');
        sum.textContent = 'Sample';
        const pre = document.createElement('pre');
        pre.className = 'tool-sample-body';
        pre.textContent = buildToolCurl(tool);
        sampleBox.append(sum, pre);
        card.append(sampleBox);
      }

      if (Array.isArray(tool.examples) && tool.examples.length) {
        const examplesSection = document.createElement('div');
        examplesSection.className = 'tool-section tool-section-examples';
        const title = document.createElement('h4');
        title.textContent = 'Examples';
        const list = document.createElement('ul');
        list.className = 'tool-example-list';
        tool.examples.forEach((example) => {
          if (!example) return;
          const item = document.createElement('li');
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'tool-example-btn';
          btn.textContent = example;
          btn.addEventListener('click', () => useToolExample(tool, example));
          item.append(btn);
          list.append(item);
        });
        examplesSection.append(title, list);
        card.append(examplesSection);
      }

      if (Array.isArray(tool.links) && tool.links.length) {
        const linkWrap = document.createElement('div');
        linkWrap.className = 'tool-links';
        tool.links.forEach((link) => {
          if (!link?.url) return;
          const a = document.createElement('a');
          a.className = 'tool-link';
          a.textContent = link.label || link.url;
          a.href = link.url;
          if (/^https?:/i.test(link.url)) {
            a.target = '_blank';
            a.rel = 'noopener';
          }
          linkWrap.append(a);
        });
        card.append(linkWrap);
      }

      const actions = document.createElement('div');
      actions.className = 'tool-card-actions';
      if (tool.sample && typeof tool.sample === 'object') {
        const runBtn = document.createElement('button');
        runBtn.type = 'button';
        runBtn.className = 'btn';
        runBtn.textContent = 'Run sample';
        runBtn.addEventListener('click', () => runToolSample(tool, runBtn));
        actions.append(runBtn);
      }
      const copyBtn = document.createElement('button');
      copyBtn.type = 'button';
      copyBtn.className = 'btn ghost';
      copyBtn.textContent = 'Copy endpoint';
      copyBtn.addEventListener('click', () => copyToolEndpoint(tool, copyBtn));
      actions.append(copyBtn);
      card.append(actions);

      fragment.append(card);
    }
    $toolsList.append(fragment);
  }

  async function loadTools(force = false) {
    if (!force && toolsState.items.length) {
      renderTools();
      updateChatToolViews();
      return;
    }
    toolsState.loading = true;
    toolsState.error = null;
    renderTools();
    hideToolPreview();
    try {
      const res = await fetch(`${API_BASE}/tools`);
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Request error (${res.status})`);
      }
      const data = await res.json();
      toolsState.items = Array.isArray(data?.tools) ? data.tools : [];
    } catch (err) {
      toolsState.items = [];
      toolsState.error = err?.message || 'Could not load tools';
    } finally {
      toolsState.loading = false;
      renderTools();
      updateChatToolViews();
    }
  }

  function collectToolExamples(limit = 6) {
    const examples = [];
    const seen = new Set();
    const addExample = (tool, example) => {
      const text = String(example || '').trim();
      if (!text) return;
      const key = text.toLowerCase();
      if (seen.has(key)) return;
      examples.push({ tool, example: text });
      seen.add(key);
    };

    for (const tool of toolsState.items || []) {
      if (!tool || !Array.isArray(tool.examples)) continue;
      for (const example of tool.examples) {
        addExample(tool, example);
        if (examples.length >= limit) return examples;
      }
    }

    if (examples.length < limit) {
      for (const fallback of DEFAULT_CHAT_EXAMPLES) {
        addExample(null, fallback);
        if (examples.length >= limit) break;
      }
    }

    return examples;
  }

  function renderChatExamples() {
    if (!$chatExamples) return;
    $chatExamples.innerHTML = '';
    const items = Array.isArray(chatExamplesState.items) ? chatExamplesState.items : [];
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'chat-examples-empty';
      empty.textContent = 'Example prompts will appear once the tool catalogue is loaded.';
      $chatExamples.append(empty);
      return;
    }
    const fragment = document.createDocumentFragment();
    items.forEach(({ example }) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chat-suggestion-btn';
      btn.textContent = example;
      btn.setAttribute('data-suggestion', example);
      fragment.append(btn);
    });
    $chatExamples.append(fragment);
    setupSuggestionButtons();
  }

  function renderChatToolsPanel() {
    if (!$chatToolsList) return;
    if (!toolsState.items.length) {
      $chatToolsList.classList.add('empty');
      $chatToolsList.textContent = 'Tools will load automatically.';
      return;
    }
    $chatToolsList.classList.remove('empty');
    $chatToolsList.innerHTML = '';
    const fragment = document.createDocumentFragment();
    for (const tool of toolsState.items) {
      if (!tool) continue;
      const item = document.createElement('div');
      item.className = 'chat-tool-item';

      const meta = document.createElement('div');
      meta.className = 'chat-tool-meta';
      const name = document.createElement('div');
      name.className = 'chat-tool-name';
      name.textContent = tool.name || tool.key || 'Tool';
      meta.append(name);
      if (tool.summary) {
        const summary = document.createElement('div');
        summary.className = 'chat-tool-summary';
        summary.textContent = tool.summary;
        meta.append(summary);
      }
      if (Array.isArray(tool.tags) && tool.tags.length) {
        const tagsWrap = document.createElement('div');
        tagsWrap.className = 'chat-tool-tags';
        tool.tags.forEach((tag) => {
          const chip = document.createElement('span');
          chip.className = 'chat-tool-chip';
          chip.textContent = formatToolTag(tag);
          tagsWrap.append(chip);
        });
        meta.append(tagsWrap);
      }
      item.append(meta);

      const actions = document.createElement('div');
      actions.className = 'chat-tool-actions';

      if (Array.isArray(tool.examples) && tool.examples.length) {
        const firstExample = tool.examples.find((ex) => String(ex || '').trim());
        if (firstExample) {
          const exampleBtn = document.createElement('button');
          exampleBtn.type = 'button';
          exampleBtn.className = 'chat-tool-suggestion';
          exampleBtn.textContent = 'Insert example';
          exampleBtn.title = String(firstExample);
          exampleBtn.addEventListener('click', () => useToolExample(tool, firstExample));
          actions.append(exampleBtn);
        }
      }

      const detailsBtn = document.createElement('button');
      detailsBtn.type = 'button';
      detailsBtn.className = 'btn ghost';
      detailsBtn.textContent = 'View details';
      detailsBtn.addEventListener('click', () => openToolInCatalogue(tool));
      actions.append(detailsBtn);

      item.append(actions);
      fragment.append(item);
    }
    $chatToolsList.append(fragment);
  }

  function highlightToolCard(key) {
    if (!key) return;
    try {
      const selectorKey = cssEscape(key);
      const card = document.querySelector(`.tool-card[data-tool-key="${selectorKey}"]`);
      if (card) {
        card.classList.add('tool-card-highlight');
        card.scrollIntoView({ behavior: 'smooth', block: 'start', inline: 'nearest' });
        setTimeout(() => card.classList.remove('tool-card-highlight'), 1600);
      }
    } catch (_) {
      // ignore
    }
  }

  function openToolInCatalogue(tool) {
    if (!tool) return;
    const value = tool.name || tool.key || '';
    toolsState.search = value;
    toolsState.activeTag = 'all';
    if ($toolsSearch) $toolsSearch.value = value;
    renderTools();
    showPage('tools');
    setTimeout(() => highlightToolCard(tool.key || value), 120);
  }

  function updateChatToolViews() {
    chatExamplesState.items = collectToolExamples(6);
    renderChatExamples();
    renderChatToolsPanel();
  }

  renderChatToolsPanel();

  // Simple markdown parser for chat messages
  function parseMarkdown(text) {
    if (!text || typeof text !== 'string') return '';
    
    let html = escapeHtml(text);
    
    // Code blocks (```code```)
    html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
    
    // Inline code (`code`)
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // Bold (**text** or __text__)
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/__(.*?)__/g, '<strong>$1</strong>');
    
    // Italic (*text* or _text_)
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    html = html.replace(/_(.*?)_/g, '<em>$1</em>');
    
    // Links [text](url)
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    
    // Headers (# ## ###)
    html = html.replace(/^### (.*$)/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.*$)/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.*$)/gm, '<h1>$1</h1>');
    
    // Lists (- item or * item) - compact handling without extra line breaks
    const lines = html.split('\n');
    const processedLines = [];
    let inList = false;
    
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const isListItem = /^[\s]*[-*]\s+(.*)$/.test(line);
      
      if (isListItem) {
        const content = line.replace(/^[\s]*[-*]\s+(.*)$/, '$1');
        if (!inList) {
          processedLines.push('<ul>');
          inList = true;
        }
        processedLines.push(`<li>${content}</li>`);
      } else {
        if (inList) {
          processedLines.push('</ul>');
          inList = false;
        }
        processedLines.push(line);
      }
    }
    
    if (inList) {
      processedLines.push('</ul>');
    }
    
    html = processedLines.join('\n');
    
    // Convert double line breaks to paragraphs, single line breaks to <br>
    html = html.replace(/\n\n+/g, '</p><p>');
    
    // Don't add <br> inside lists - remove line breaks between list items
    html = html.replace(/<\/li>\n<li>/g, '</li><li>');
    html = html.replace(/<ul>\n/g, '<ul>');
    html = html.replace(/\n<\/ul>/g, '</ul>');
    
    // Convert remaining single line breaks to <br>
    html = html.replace(/\n/g, '<br>');
    
    // Wrap in paragraph if not already wrapped
    if (!html.startsWith('<') && html.trim()) {
      html = '<p>' + html + '</p>';
    }
    
    // Clean up empty paragraphs
    html = html.replace(/<p><\/p>/g, '');
    
    return html;
  }
  const naturalCmp = (a, b) => {
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    const na = Number(a), nb = Number(b);
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
    return String(a).localeCompare(String(b), undefined, { sensitivity: "base", numeric: true });
  };

  // Amsterdam timezone helpers (Europe/Amsterdam)
  const AMSTERDAM_TZ = 'Europe/Amsterdam';
  function amsParts(date) {
    try {
      return new Intl.DateTimeFormat('nl-NL', {
        timeZone: AMSTERDAM_TZ,
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false,
      }).formatToParts(date);
    } catch { return []; }
  }
  function partsToObj(parts) {
    const obj = {};
    for (const p of parts || []) obj[p.type] = p.value;
    return obj;
  }
  function amsDateString(date) {
    const p = partsToObj(amsParts(date));
    const day = p.day || '00';
    const month = p.month || '00';
    const year = p.year || '0000';
    return `${day}-${month}-${year}`;
  }
  function amsTimeString(date, options = {}) {
    const includeSeconds = options.includeSeconds ?? false;
    const p = partsToObj(amsParts(date));
    const hour = p.hour || '00';
    const minute = p.minute || '00';
    const second = p.second || '00';
    return includeSeconds ? `${hour}:${minute}:${second}` : `${hour}:${minute}`;
  }
  function amsDateTimeString(date, options = {}) {
    return `${amsDateString(date)} ${amsTimeString(date, options)}`;
  }
  function sameAmsDay(a, b) {
    return amsDateString(a) === amsDateString(b);
  }
  function amsTzShort(date) {
    try {
      const parts = new Intl.DateTimeFormat('en-GB', { timeZone: AMSTERDAM_TZ, timeZoneName: 'long' }).formatToParts(date);
      const tz = (parts.find(p => p.type === 'timeZoneName') || {}).value || '';
      if (/summer/i.test(tz)) return 'CEST';
      if (/standard/i.test(tz)) return 'CET';
    } catch {}
    try {
      const parts = new Intl.DateTimeFormat('en-GB', { timeZone: AMSTERDAM_TZ, timeZoneName: 'short' }).formatToParts(date);
      return (parts.find(p => p.type === 'timeZoneName') || {}).value || '';
    } catch {}
    return 'CET';
  }

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

  const handleResize = () => {
    viewportHeight = $bodyScroll.clientHeight;
    updateTemplates();
    computeView();
    renderVisible();
  };
  if (typeof ResizeObserver === 'function') {
    const resizeObs = new ResizeObserver(() => handleResize());
    resizeObs.observe($body);
  } else {
    window.addEventListener('resize', handleResize);
  }

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

  // URL management: keep it clean (no ?view=... params)
  function applyViewState(state) {
    try {
      if (!state || typeof state !== 'object') return;
      if (state.ds && typeof state.ds === 'string') {
        dataset = state.ds;
        accountState.prefDataset = dataset;
        try { localStorage.setItem(ACCOUNT_DATASET_PREF_KEY, dataset); } catch {}
      }
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
      // Remove legacy 'view' param if present
      url.searchParams.delete('view');
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
      // Legacy URL view import removed; prefer localStorage persistence only
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
    if (!hasPermission('export.run')) {
      alert('You do not have permission to run exports.');
      return;
    }
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
    if (!$fieldsPanel.hidden) {
      const withinPanel = eventWithin($fieldsPanel, e);
      const onToggleBtn = eventWithin($hideBtn, e);
      if (!withinPanel && !onToggleBtn) $fieldsPanel.hidden = true;
    }
    if (accountState.menuOpen) {
      const withinMenu = eventWithin($userMenu, e) || eventWithin($userMenuToggle, e);
      if (!withinMenu) setUserMenu(false);
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      let handled = false;
      if (!$fieldsPanel.hidden) {
        $fieldsPanel.hidden = true;
        handled = true;
      }
      if (accountState.menuOpen) {
        setUserMenu(false);
        handled = true;
      }
      if ($toolsPreview && !$toolsPreview.hidden) {
        hideToolPreview();
        handled = true;
      }
      if (handled) {
        e.preventDefault();
        e.stopPropagation();
      }
    }
  });

  function canAccessPage(pageKey) {
    if (!permissionState.ready) return true;
    const key = (pageKey || '').toLowerCase();
    if (key === 'tools') return hasPermission('tools.use');
    if (key === 'chat') return hasPermission('chat.use');
    if (key === 'tasks') return hasPermission('export.run');
    if (key === 'vcenter') return hasPermission('vcenter.view') || (currentUser && currentUser.role === 'admin');
    if (key === 'admin') return currentUser && currentUser.role === 'admin';
    return true;
  }

  function nextAccessiblePage(preferred = 'search') {
    const candidates = [preferred, 'search', 'export', 'zabbix'];
    for (const candidate of candidates) {
      if (canAccessPage(candidate)) return candidate;
    }
    return 'search';
  }

  function applyRoleRestrictions() {
    if (!permissionState.ready) {
      return;
    }
    const canTools = canAccessPage('tools');
    const canChat = canAccessPage('chat');
    const canVCenter = canAccessPage('vcenter');
    const canAdmin = canAccessPage('admin');
     const canTasks = canAccessPage('tasks');
    const canRunExport = hasPermission('export.run');
    const canAck = hasPermission('zabbix.ack');

    if ($navTools) $navTools.hidden = !canTools;
    if ($navChat) $navChat.hidden = !canChat;
    if ($navVCenter) $navVCenter.hidden = !canVCenter;
    if ($navTasks) $navTasks.hidden = !canTasks;
    if ($navAdmin) $navAdmin.hidden = !canAdmin;

    if ($updateBtn) $updateBtn.disabled = !canRunExport;
    if ($zbxAck) $zbxAck.disabled = !canAck;
    if ($zhostAck) $zhostAck.disabled = !canAck;

    if (!canAccessPage(page)) {
      const fallback = nextAccessiblePage();
      if (fallback !== page) {
        showPage(fallback);
        return;
      }
    }
  }

  applyRoleRestrictions();

  // Page routing
  function showPage(p) {
    if (!canAccessPage(p)) {
      const fallback = nextAccessiblePage();
      if (fallback !== p) {
        if (permissionState.ready) {
          alert('You do not have access to that page.');
        }
        p = fallback;
      }
    }
    page = p;
    setUserMenu(false);
    persistActivePage(p);
    // Toggle page sections
    const map = {
      search: $pageSearch,
      tools: $pageTools,
      zabbix: $pageZabbix,
      netbox: $pageNetbox,
      jira: $pageJira,
      confluence: $pageConfluence,
      chat: $pageChat,
      export: $pageExport,
      commvault: $pageCommvault,
      vcenter: $pageVCenter,
      zhost: $pageZhost,
      tasks: $pageTasks,
      suggestions: $pageSuggestions,
      'suggestion-detail': $pageSuggestionDetail,
      account: $pageAccount,
      admin: $pageAdmin,
    };
    for (const k of Object.keys(map)) {
      if (!map[k]) continue;
      if (k === p) map[k].removeAttribute('hidden'); else map[k].setAttribute('hidden', '');
    }
    // Toggle tabs
    $pages?.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-page') === p));
    if (p === 'suggestion-detail') {
      const suggestionsTab = $pages?.querySelector('button.tab[data-page="suggestions"]');
      suggestionsTab?.classList.add('active');
    }
    // Update hash
    try {
      const url = new URL(window.location.href);
      let nextHash = `#${p}`;
      if (p === 'suggestions') {
        nextHash = '#suggestions';
      } else if (p === 'suggestion-detail') {
        if (suggestionState.route.mode === 'new') {
          nextHash = '#suggestions/new';
        } else if (suggestionState.route.id) {
          nextHash = `#suggestions/${suggestionState.route.id}`;
        } else {
          nextHash = '#suggestions';
        }
      }
      url.hash = nextHash;
      history.replaceState(null, '', url.toString());
    } catch {}
    if ($suggestionsButton) {
      if (p === 'suggestions' || p === 'suggestion-detail') {
        $suggestionsButton.classList.add('active');
      } else {
        $suggestionsButton.classList.remove('active');
      }
    }
    // When switching into Export, ensure data is loaded/refreshed
    if (p === 'export') {
      fetchData();
    } else if (p === 'commvault') {
      setCommvaultTab(commvaultState.tab || 'backups');
    } else if (p === 'vcenter') {
      loadVCenterInstances().catch(() => {});
    } else if (p === 'tools') {
      loadTools();
    } else if (p === 'tasks') {
      loadTasks();
    } else if (p === 'chat') {
      fetchChatSessions();
      loadChatDefaults();
      setupAutoResize();
      setupSuggestionButtons();
    } else if (p === 'zabbix') {
      fetchZabbix();
    } else if (p === 'zhost') {
      // page-specific loader handled via showZabbixHost()
    } else if (p === 'jira') {
      ensureJiraDefaults();
      // If user has previous search, auto-run
      try { const prev = localStorage.getItem('jira_last_query'); if (prev) searchJira(false); } catch { searchJira(false); }
    } else if (p === 'netbox') {
      ensureNbDefaults();
      try { const prev = localStorage.getItem('nb_last_query'); if (prev) searchNetbox(false); } catch {}
    } else if (p === 'confluence') {
      ensureConfDefaults();
      try { const prev = localStorage.getItem('conf_last_query'); if (prev) searchConfluence(false); } catch { /* noop */ }
    } else if (p === 'search') {
      // no-op; wait for user query
    } else if (p === 'admin') {
      loadAdminSettings(adminState.settings.length === 0).catch(() => {});
      setAdminTab(adminState.activeTab || 'zabbix');
      // Load users when switching to admin page
      if (adminState.activeTab === 'users' || !adminState.users.length) {
        loadAdminUsers($adminUserIncludeInactive?.checked).catch(() => {});
        loadAdminGlobalApiKeys().catch(() => {});
      }
    } else if (p === 'account') {
      if (!currentUser) loadCurrentUser();
      populateAccountForms();
      showAccountTab(accountState.tab || 'profile');
    } else if (p === 'suggestions') {
      suggestionState.route = { mode: 'list', id: null };
      loadSuggestions(true).catch(() => {});
    } else if (p === 'suggestion-detail') {
      if (suggestionState.route.mode === 'detail' && suggestionState.route.id) {
        loadSuggestionDetail(suggestionState.route.id).catch(() => {});
      } else {
        prepareNewSuggestion().catch(() => {});
      }
    }
    if (p !== 'tools') {
      hideToolPreview();
    }
    applyRoleRestrictions();
  }
  function parseHashPage() {
    try {
      const raw = (window.location.hash || '').replace(/^#/, '').trim();
      const lower = raw.toLowerCase();
      if (!raw) {
        suggestionState.route = { mode: 'list', id: null };
        accountState.tab = 'profile';
        const stored = readPersistedPage();
        return stored || 'search';
      }
      if (lower.startsWith('suggestions')) {
        const parts = raw.split('/');
        const second = parts[1] || '';
        if (second.toLowerCase() === 'new') {
          suggestionState.route = { mode: 'new', id: null };
          return 'suggestion-detail';
        }
        if (second) {
          suggestionState.route = { mode: 'detail', id: second };
          return 'suggestion-detail';
        }
        suggestionState.route = { mode: 'list', id: null };
        return 'suggestions';
      }
      if (lower.startsWith('account')) {
        const parts = raw.split('/');
        const tab = (parts[1] || '').toLowerCase();
        const valid = ['profile', 'preferences', 'password', 'tokens'];
        accountState.tab = valid.includes(tab) ? tab : 'profile';
        return 'account';
      }
      if (lower === 'admin') {
        suggestionState.route = { mode: 'list', id: null };
        return 'admin';
      }
      if (ROUTABLE_PAGE_SET.has(lower)) {
        suggestionState.route = { mode: 'list', id: null };
        if (lower === 'account') accountState.tab = 'profile';
        return lower;
      }
    } catch {}
    suggestionState.route = { mode: 'list', id: null };
    const stored = readPersistedPage();
    return stored || 'search';
  }
  window.addEventListener('hashchange', () => {
    const nextPage = parseHashPage();
    showPage(nextPage);
  });
  // Attach click handlers to each top-level page button (robust against text-node targets)
  if ($pages) {
    const pgBtns = Array.from($pages.querySelectorAll('button.tab'));
    pgBtns.forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const p = btn.getAttribute('data-page') || 'export';
        if (!canAccessPage(p)) {
          alert('You do not have access to that page.');
          return;
        }
        showPage(p);
      });
    });
  }

  // Dataset tab switching (Export page)
  if ($dsTabs) {
    const dsBtns = Array.from($dsTabs.querySelectorAll('button.tab'));
    dsBtns.forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const ds = btn.getAttribute('data-ds') || 'devices';
        dataset = ds;
        // Toggle active
        $dsTabs.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-ds') === ds));
        accountState.prefDataset = ds;
        try { localStorage.setItem(ACCOUNT_DATASET_PREF_KEY, ds); } catch {}
        if ($accountPrefDataset) $accountPrefDataset.value = ds;
        fetchData();
        updateURLDebounced();
      });
    });
  }

  $toolsSearch?.addEventListener('input', () => {
    toolsState.search = ($toolsSearch.value || '').trim();
    hideToolPreview();
    renderTools();
  });
  $toolsRefresh?.addEventListener('click', (e) => {
    e.preventDefault();
    toolsState.activeTag = 'all';
    toolsState.search = ($toolsSearch?.value || '').trim();
    hideToolPreview();
    loadTools(true);
  });
  $toolsPreviewCollapse?.addEventListener('click', (e) => {
    e.preventDefault();
    hideToolPreview();
  });
  $chatToolsOpen?.addEventListener('click', (e) => {
    e.preventDefault();
    toolsState.search = '';
    toolsState.activeTag = 'all';
    if ($toolsSearch) $toolsSearch.value = '';
    renderTools();
    showPage('tools');
  });
  $tasksUpdateAll?.addEventListener('click', async (event) => {
    event.preventDefault();
    await handleTaskRefreshAll();
  });
  $tasksLayoutButtons.forEach((btn) => {
    btn.addEventListener('click', (event) => {
      event.preventDefault();
      const layout = btn.getAttribute('data-tasks-layout');
      if (layout) setTasksLayout(layout);
    });
  });
  $tasksRefresh?.addEventListener('click', (event) => {
    event.preventDefault();
    loadTasks(true);
  });
  if ($tasksList) {
    $tasksList.addEventListener('click', (event) => {
      const runBtn = event.target.closest('button[data-task-action="run"]');
      if (!runBtn) return;
      event.preventDefault();
      const datasetId = runBtn.getAttribute('data-task-id');
      if (datasetId) {
        handleTaskRefresh(datasetId);
      }
    });
  }

  if ($userMenuToggle) {
    $userMenuToggle.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      setUserMenu(!accountState.menuOpen);
    });
  }
  userMenuItems.forEach((item) => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const action = (item.getAttribute('data-user-action') || '').toLowerCase();
      setUserMenu(false);
      switch (action) {
        case 'profile':
        case 'preferences':
        case 'password':
        case 'tokens':
          openAccount(action === 'profile' ? 'profile' : action);
          break;
        default:
          break;
      }
    });
  });

  if ($accountThemeMount) {
    mountThemeToggle($accountThemeMount);
  }

  accountTabs.forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const tab = (btn.getAttribute('data-account-tab') || 'profile').toLowerCase();
      showAccountTab(tab);
      showPage('account');
    });
  });

  if ($accountProfileForm) {
    $accountProfileForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!$accountProfileDisplay || !$accountProfileEmail) return;
      const payload = {
        display_name: $accountProfileDisplay.value.trim() || null,
        email: $accountProfileEmail.value.trim() || null,
      };
    flashStatus($accountProfileStatus, 'Saving…');
      try {
        const res = await fetch(`${API_BASE}/profile`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
        flashStatus($accountProfileStatus, data?.detail || 'Unable to save changes.');
        return;
      }
      const data = await res.json();
      currentUser = data;
      accountState.user = data;
      setUserPermissions(Array.isArray(data?.permissions) ? data.permissions : []);
      updateTopbarUser();
      populateAccountForms();
      applyRoleRestrictions();
      flashStatus($accountProfileStatus, 'Profile updated.');
    } catch (err) {
      flashStatus($accountProfileStatus, 'Unable to save changes.');
    }
  });
  }

  if ($accountPasswordForm) {
    $accountPasswordForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!$accountPasswordNew) return;
      const payload = {
        current_password: $accountPasswordCurrent?.value || null,
        new_password: $accountPasswordNew.value || '',
      };
      flashStatus($accountPasswordStatus, 'Updating…');
      try {
        const res = await fetch(`${API_BASE}/profile/password`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          flashStatus($accountPasswordStatus, data?.detail || 'Unable to update password.');
          return;
        }
        flashStatus($accountPasswordStatus, 'Password updated.');
        if ($accountPasswordCurrent) $accountPasswordCurrent.value = '';
        $accountPasswordNew.value = '';
      } catch (err) {
        flashStatus($accountPasswordStatus, 'Unable to update password.');
      }
    });
  }

  if ($accountPrefDataset) {
    $accountPrefDataset.addEventListener('change', (e) => {
      const val = ($accountPrefDataset.value || 'all').toLowerCase();
      if (!['all', 'devices', 'vms'].includes(val)) return;
      accountState.prefDataset = val;
      try { localStorage.setItem(ACCOUNT_DATASET_PREF_KEY, val); } catch {}
      if (dataset !== val) {
        const btn = $dsTabs?.querySelector(`button.tab[data-ds="${val}"]`);
        if (btn) {
          btn.click();
        } else {
          dataset = val;
          fetchData();
        }
      }
    });
  }

  if ($accountApiForm) {
    $accountApiForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!$accountApiProvider || !$accountApiSecret) return;
      const provider = ($accountApiProvider.value || '').toLowerCase();
      const secret = ($accountApiSecret.value || '').trim();
      const label = ($accountApiLabel?.value || '').trim();
      if (!provider || !secret) {
      flashStatus($accountApiStatus, 'Select provider and enter a secret.');
      return;
    }
    flashStatus($accountApiStatus, 'Saving…');
    try {
      const res = await fetch(`${API_BASE}/profile/api-keys/${encodeURIComponent(provider)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ secret, label: label || null }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        flashStatus($accountApiStatus, data?.detail || 'Unable to save key.');
        return;
      }
      $accountApiSecret.value = '';
      flashStatus($accountApiStatus, 'Key saved.');
      await Promise.all([
        refreshAccountApiKeys(),
        refreshChatProviders(),
      ]);
    } catch (err) {
      flashStatus($accountApiStatus, 'Unable to save key.');
    }
  });
  }

  // ---------------------------
  // Commvault backups
  // ---------------------------
  function setCommvaultTab(tab) {
    if (!['backups', 'plans', 'storage', 'servers'].includes(tab)) tab = 'backups';
    commvaultState.tab = tab;
    if ($commvaultTabs) {
      $commvaultTabs.querySelectorAll('button[data-commvault-tab]').forEach((btn) => {
        const btnTab = btn.getAttribute('data-commvault-tab');
        btn.classList.toggle('active', btnTab === tab);
      });
    }
    commvaultPanels.forEach((panel) => {
      if (!panel) return;
      const isActive = panel.dataset.commvaultPanel === tab;
      panel.classList.toggle('active', isActive);
      if (isActive) panel.removeAttribute('hidden'); else panel.setAttribute('hidden', '');
    });
    try { localStorage.setItem(COMMVAULT_TAB_KEY, tab); } catch {}
    if (tab === 'backups') {
      loadCommvaultData(false);
    } else if (tab === 'plans') {
      renderCommvaultPlans();
      loadCommvaultPlans(false);
    } else if (tab === 'storage') {
      renderCommvaultStorage();
      loadCommvaultStorage(false);
    } else if (tab === 'servers') {
      renderCommvaultServerState();
      if ($commvaultServerQuery) {
        try {
          $commvaultServerQuery.focus({ preventScroll: true });
        } catch (_) {
          /* ignore */
        }
      }
    }
  }

  function applyCommvaultPayload(payload) {
    const jobs = Array.isArray(payload?.jobs) ? payload.jobs : [];
    commvaultState.jobs = jobs.filter((job) => job && typeof job === 'object');
    commvaultState.lastUpdated = payload?.generated_at || null;
    const totalCached = Number(payload?.total_cached ?? payload?.total_available);
    commvaultState.totalAvailable = Number.isFinite(totalCached) && totalCached >= 0 ? totalCached : null;
    if (typeof payload?.limit === 'number') commvaultState.limit = payload.limit;
    if (typeof payload?.since_hours === 'number') commvaultState.sinceHours = payload.since_hours;
    commvaultState.sinceHours = Math.round(commvaultState.sinceHours);
    if (!Number.isFinite(commvaultState.sinceHours) || commvaultState.sinceHours < 1) {
      commvaultState.sinceHours = 24;
    } else if (commvaultState.sinceHours > 48) {
      commvaultState.sinceHours = 48;
    }
    commvaultState.error = null;

    if ($commvaultSince) {
      const desired = String(commvaultState.sinceHours);
      const hasOption = Array.from($commvaultSince.options || []).some((opt) => opt.value === desired);
      $commvaultSince.value = hasOption ? desired : '24';
      if (!hasOption) {
        commvaultState.sinceHours = Number($commvaultSince.value) || 24;
      }
    }
  }

  function setCommvaultStatus(message, isError = false, autoHideMs = 5000) {
    if (!$commvaultStatus) return;
    if (commvaultStatusTimeout) {
      clearTimeout(commvaultStatusTimeout);
      commvaultStatusTimeout = null;
    }
    if (!message) {
      $commvaultStatus.hidden = true;
      $commvaultStatus.textContent = '';
      $commvaultStatus.classList.remove('error');
      return;
    }
    $commvaultStatus.hidden = false;
    $commvaultStatus.textContent = message;
    $commvaultStatus.classList.toggle('error', !!isError);
    if (!isError && autoHideMs > 0) {
      commvaultStatusTimeout = setTimeout(() => {
        if ($commvaultStatus) {
          $commvaultStatus.hidden = true;
          $commvaultStatus.textContent = '';
          $commvaultStatus.classList.remove('error');
        }
        commvaultStatusTimeout = null;
      }, autoHideMs);
    }
  }

  function setCommvaultPlansStatus(message, isError = false, autoHideMs = 5000) {
    if (!$commvaultPlansStatus) return;
    if (commvaultPlansStatusTimeout) {
      clearTimeout(commvaultPlansStatusTimeout);
      commvaultPlansStatusTimeout = null;
    }
    if (!message) {
      $commvaultPlansStatus.hidden = true;
      $commvaultPlansStatus.textContent = '';
      $commvaultPlansStatus.classList.remove('error');
      return;
    }
    $commvaultPlansStatus.hidden = false;
    $commvaultPlansStatus.textContent = message;
    $commvaultPlansStatus.classList.toggle('error', !!isError);
    if (!isError && autoHideMs > 0) {
      commvaultPlansStatusTimeout = setTimeout(() => {
        if ($commvaultPlansStatus) {
          $commvaultPlansStatus.hidden = true;
          $commvaultPlansStatus.textContent = '';
          $commvaultPlansStatus.classList.remove('error');
        }
        commvaultPlansStatusTimeout = null;
      }, autoHideMs);
    }
  }

  function setCommvaultStorageStatus(message, isError = false) {
    if (!$commvaultStorageStatus) return;
    if (!message) {
      $commvaultStorageStatus.hidden = true;
      $commvaultStorageStatus.textContent = '';
      $commvaultStorageStatus.classList.remove('error');
      return;
    }
    $commvaultStorageStatus.hidden = false;
    $commvaultStorageStatus.textContent = message;
    $commvaultStorageStatus.classList.toggle('error', !!isError);
  }

  function formatCommvaultDate(value) {
    if (!value) return '–';
    try {
      const d = new Date(value);
      if (Number.isNaN(d.getTime())) return value;
      return `${amsDateTimeString(d)} ${amsTzShort(d)}`.trim();
    } catch {
      return value;
    }
  }

  function formatCommvaultChartDate(value) {
    if (!value) return '';
    try {
      const d = new Date(value);
      if (Number.isNaN(d.getTime())) return '';
      const formatter = new Intl.DateTimeFormat('nl-NL', {
        timeZone: AMSTERDAM_TZ,
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      });
      return formatter.format(d);
    } catch {
      return '';
    }
  }

  function formatCommvaultDuration(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return '–';
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const secs = Math.floor(value % 60);
    const parts = [];
    if (hours) parts.push(`${hours}h`);
    if (minutes) parts.push(`${minutes}m`);
    if (!hours && secs) parts.push(`${secs}s`);
    if (!parts.length) parts.push(`${secs}s`);
    return parts.join(' ');
  }

  function formatCommvaultBytes(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return '—';
    if (num === 0) return '0 B';
    if (num < 0) return '—';
    const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
    let size = num;
    let idx = 0;
    while (size >= 1024 && idx < units.length - 1) {
      size /= 1024;
      idx += 1;
    }
    const precision = size >= 100 ? 0 : size >= 10 ? 1 : 2;
    return `${size.toFixed(precision)} ${units[idx]}`;
  }

  function formatCommvaultThroughput(value) {
    const num = Number(value);
    if (!Number.isFinite(num) || num <= 0) return '–';
    const precision = num >= 100 ? 0 : num >= 10 ? 1 : 2;
    return `${num.toFixed(precision)} GB/h`;
  }

  function formatCommvaultPercent(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return '–';
    const precision = Math.abs(num) >= 10 ? 0 : 1;
    return `${num.toFixed(precision)}%`;
  }

  function formatCommvaultFiles(value) {
    const num = Number(value);
    if (!Number.isFinite(num) || num <= 0) return '–';
    return Math.round(num).toLocaleString();
  }

  function getCommvaultStatusClass(label) {
    const text = (label || '').toLowerCase();
    if (!text) return '';
    if (text.includes('fail') || text.includes('error') || text.includes('kill')) return 'status-error';
    if (text.includes('wait') || text.includes('suspend') || text.includes('queue') || text.includes('running') || text.includes('warning')) return 'status-warning';
    if (text.includes('success') || text.includes('complete') || text.includes('done')) return 'status-success';
    return '';
  }

  function commvaultMatchesSearch(job) {
    const tokens = commvaultState.searchTokens || [];
    if (!tokens.length) return true;
    if (!job || typeof job !== 'object') return false;

    const collector = [];
    const push = (value) => {
      if (value == null) return;
      if (Array.isArray(value)) {
        for (const item of value) push(item);
        return;
      }
      const str = String(value).toLowerCase();
      if (str) collector.push(str);
    };

    push(job.job_id);
    push(job.job_type);
    push(job.localized_status);
    push(job.status);
    push(job.localized_operation);
    push(job.client_name);
    push(job.destination_client_name);
    push(job.subclient_name);
    push(job.plan_name);
    push(job.storage_policy_name);
    push(job.backup_set_name);
    push(job.backup_level_name);
    push(job.application_name);
    push(job.client_groups);

    const haystack = collector.join(' ');
    if (!haystack) return false;
    return tokens.every((token) => haystack.includes(token));
  }

  function renderCommvaultStatusOptions() {
    if (!$commvaultStatusFilter) return;

    const jobsForCounts = commvaultState.jobs.filter(commvaultMatchesSearch);
    const counts = new Map();
    for (const job of jobsForCounts) {
      if (!job) continue;
      const label = (job.localized_status || job.status || 'Unknown') || 'Unknown';
      counts.set(label, (counts.get(label) || 0) + 1);
    }

    commvaultState.statuses = Array.from(counts.keys()).sort((a, b) => a.localeCompare(b));
    commvaultState.statusFilter = (commvaultState.statusFilter || '').trim();
    if (commvaultState.statusFilter && !counts.has(commvaultState.statusFilter)) {
      commvaultState.statusFilter = '';
    }

    $commvaultStatusFilter.innerHTML = '';
    const frag = document.createDocumentFragment();

    const makeChip = (label, value, total, className = '') => {
      const wrapper = document.createElement('div');
      wrapper.className = 'commvault-status-chip';
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.value = value;
      if (className) button.classList.add(className);
      button.textContent = label;
      if ((commvaultState.statusFilter || '') === value) button.classList.add('active');
      wrapper.append(button);
      const counter = document.createElement('div');
      counter.className = 'commvault-status-count';
      counter.textContent = `${total}`;
      wrapper.append(counter);
      return wrapper;
    };

    const total = jobsForCounts.length;
    const allChip = makeChip('All statuses', '', total);
    frag.append(allChip);

    for (const status of commvaultState.statuses) {
      const count = counts.get(status) || 0;
      const statusClass = getCommvaultStatusClass(status);
      const chip = makeChip(status, status, count, statusClass);
      frag.append(chip);
    }

    $commvaultStatusFilter.append(frag);

    $commvaultStatusFilter.querySelectorAll('button').forEach((btn) => {
      btn.addEventListener('click', () => {
        const value = btn.dataset.value || '';
        if ((commvaultState.statusFilter || '') === value) {
          commvaultState.statusFilter = '';
        } else {
          commvaultState.statusFilter = value;
        }
        renderCommvaultTable();
      });
    });
  }

  function commvaultMatchesStatus(job) {
    const filter = (commvaultState.statusFilter || '').toLowerCase().trim();
    if (!filter) return true;
    const label = ((job?.localized_status || job?.status || '') + '').toLowerCase().trim();
    return label === filter;
  }

  function updateCommvaultSummary(searchMatchCount, visibleCount) {
    if (!$commvaultSummary) return;
    if (commvaultState.loading) {
      $commvaultSummary.textContent = 'Loading Commvault backups…';
      return;
    }
    const updated = commvaultState.lastUpdated ? formatTimestamp(commvaultState.lastUpdated) : 'never';
    if (!commvaultState.jobs.length) {
      $commvaultSummary.textContent = `No Commvault jobs available. Last update: ${updated}.`;
      return;
    }

    const windowText = commvaultState.sinceHours > 0 ? `last ${commvaultState.sinceHours}h` : 'all time';
    const totalText = Number.isFinite(commvaultState.totalAvailable) && commvaultState.totalAvailable !== null
      ? `${commvaultState.totalAvailable}`
      : 'unknown';
    const searchNote = commvaultState.search ? ` (search: "${commvaultState.search}")` : '';
    const statusNote = commvaultState.statusFilter ? ` (status: ${commvaultState.statusFilter})` : '';

    if (typeof searchMatchCount === 'number') {
      if (searchMatchCount === 0) {
        $commvaultSummary.textContent = `No Commvault jobs match the search${searchNote}. Last update: ${updated}.`;
        return;
      }
      if (visibleCount === 0) {
        $commvaultSummary.textContent = `No Commvault jobs match status “${commvaultState.statusFilter}”${searchNote}. Last update: ${updated}.`;
        return;
      }
      $commvaultSummary.textContent = `Showing ${visibleCount} of ${searchMatchCount} matching job(s)${statusNote}${searchNote} (${windowText}), Commvault reports ${totalText} total — updated ${updated}.`;
      return;
    }

    $commvaultSummary.textContent = `Showing ${commvaultState.jobs.length} job(s)${statusNote}${searchNote} (${windowText}), Commvault reports ${totalText} total — updated ${updated}.`;
  }

  function renderCommvaultTable() {
    if (!$commvaultTableBody) return;
    if (!commvaultState.jobs.length) {
      $commvaultTableBody.innerHTML = '<tr class="empty"><td colspan="14">No Commvault jobs were found for the selected window.</td></tr>';
      updateCommvaultSummary(0, 0);
      renderCommvaultStatusOptions();
      return;
    }

    const searchFiltered = commvaultState.jobs.filter(commvaultMatchesSearch);
    const searchCount = searchFiltered.length;
    if (!searchCount) {
      $commvaultTableBody.innerHTML = '<tr class="empty"><td colspan="14">No Commvault jobs match the search terms.</td></tr>';
      updateCommvaultSummary(0, 0);
      renderCommvaultStatusOptions();
      return;
    }

    const filteredJobs = searchFiltered.filter((job) => commvaultMatchesStatus(job));
    if (!filteredJobs.length) {
      $commvaultTableBody.innerHTML = '<tr class="empty"><td colspan="14">No Commvault jobs match the selected status filter.</td></tr>';
      updateCommvaultSummary(searchCount, 0);
      renderCommvaultStatusOptions();
      return;
    }

    const rows = filteredJobs.map((job) => {
      const jobId = job?.job_id != null ? String(job.job_id) : '–';
      const jobType = job?.job_type || job?.localized_operation || '';
      const statusLabel = job?.localized_status || job?.status || 'Unknown';
      const statusClass = getCommvaultStatusClass(statusLabel);
      const percentComplete = formatCommvaultPercent(job?.percent_complete);
      const client = job?.client_name || job?.destination_client_name || '–';
      const destination = job?.destination_client_name && job.destination_client_name !== job.client_name
        ? job.destination_client_name
        : null;
      const subclient = job?.subclient_name || job?.backup_set_name || '–';
      const plan = job?.plan_name || '–';
      const policy = job?.storage_policy_name || '–';
      const start = formatCommvaultDate(job?.start_time);
      const end = formatCommvaultDate(job?.end_time);
      const duration = formatCommvaultDuration(job?.elapsed_seconds);
      const appSize = formatCommvaultBytes(job?.size_of_application_bytes);
      const mediaSize = formatCommvaultBytes(job?.size_on_media_bytes);
      const throughput = formatCommvaultThroughput(job?.average_throughput_gb_per_hr);
      const files = formatCommvaultFiles(job?.total_num_files);
      const savings = formatCommvaultPercent(job?.percent_savings);
      const statusBadge = statusLabel
        ? `<span class="status-pill${statusClass ? ` ${statusClass}` : ''}">${escapeHtml(statusLabel)}</span>`
        : '–';
      const statusExtra = percentComplete !== '–' ? `<span class="muted">${escapeHtml(percentComplete)} complete</span>` : '';
      const clientExtra = destination ? `<span class="muted">Dest: ${escapeHtml(destination)}</span>` : '';
      const jobExtra = jobType ? `<span class="muted">${escapeHtml(jobType)}</span>` : '';
      return `
        <tr>
          <td><strong>${escapeHtml(jobId)}</strong>${jobExtra}</td>
          <td>${statusBadge}${statusExtra}</td>
          <td>${client !== '–' ? escapeHtml(client) : '–'}${clientExtra}</td>
          <td>${subclient !== '–' ? escapeHtml(subclient) : '–'}</td>
          <td>${plan !== '–' ? escapeHtml(plan) : '–'}</td>
          <td>${policy !== '–' ? escapeHtml(policy) : '–'}</td>
          <td>${escapeHtml(start)}</td>
          <td>${escapeHtml(end)}</td>
          <td>${escapeHtml(duration)}</td>
          <td>${escapeHtml(appSize)}</td>
          <td>${escapeHtml(mediaSize)}</td>
          <td>${escapeHtml(throughput)}</td>
          <td>${escapeHtml(files)}</td>
          <td>${escapeHtml(savings)}</td>
        </tr>`;
    });
    $commvaultTableBody.innerHTML = rows.join('');
    updateCommvaultSummary(searchCount, filteredJobs.length);
    renderCommvaultStatusOptions();
  }

  function getFilteredCommvaultPlans(plans) {
    const list = Array.isArray(plans) ? plans : [];
    const typeFilter = (commvaultPlansState.planType || 'all').trim().toLowerCase();
    if (!typeFilter || typeFilter === 'all') return list;
    return list.filter((plan) => {
      if (!plan || typeof plan !== 'object') return false;
      const planTypeValue = (plan.plan_type || '').toString().trim().toLowerCase();
      return planTypeValue === typeFilter;
    });
  }

  function populateCommvaultPlanTypeOptions() {
    if (!$commvaultPlansType) return;
    const types = Array.isArray(commvaultPlansState.planTypes) ? commvaultPlansState.planTypes.slice() : [];
    const desiredValues = ['all', ...types.map((type) => type)];
    const existingValues = Array.from($commvaultPlansType.options || []).map((opt) => opt.value);
    let needsUpdate = desiredValues.length !== existingValues.length;
    if (!needsUpdate) {
      for (let i = 0; i < desiredValues.length; i += 1) {
        if (desiredValues[i] !== existingValues[i]) {
          needsUpdate = true;
          break;
        }
      }
    }
    if (!needsUpdate) {
      if (!desiredValues.includes(commvaultPlansState.planType)) {
        commvaultPlansState.planType = 'all';
        $commvaultPlansType.value = 'all';
      }
      return;
    }
    $commvaultPlansType.innerHTML = '';
    desiredValues.forEach((value) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value === 'all' ? 'All plan types' : value;
      $commvaultPlansType.append(option);
    });
    if (!desiredValues.includes(commvaultPlansState.planType)) {
      commvaultPlansState.planType = 'all';
    }
    $commvaultPlansType.value = commvaultPlansState.planType;
  }

  function renderCommvaultPlans() {
    populateCommvaultPlanTypeOptions();
    const plans = Array.isArray(commvaultPlansState.plans) ? commvaultPlansState.plans : [];
    const filteredPlans = getFilteredCommvaultPlans(plans);
    if ($commvaultPlansSummary) {
      const total = Number.isFinite(Number(commvaultPlansState.totalPlans))
        ? Number(commvaultPlansState.totalPlans)
        : plans.length;
      const updated = commvaultPlansState.generatedAt ? formatTimestamp(commvaultPlansState.generatedAt) : 'never';
      const filterNote = commvaultPlansState.planType && commvaultPlansState.planType !== 'all'
        ? ` (type: ${commvaultPlansState.planType})`
        : '';
      if (commvaultPlansState.loading) {
        $commvaultPlansSummary.textContent = 'Loading Commvault plans…';
      } else if (!plans.length) {
        $commvaultPlansSummary.textContent = `No Commvault plans are cached. Last update: ${updated}.`;
      } else {
        $commvaultPlansSummary.textContent = `Showing ${filteredPlans.length} plan(s)${filterNote} of ${total} cached — updated ${updated}.`;
      }
    }

    if (!$commvaultPlansTableBody) return;

    if (commvaultPlansState.loading) {
      $commvaultPlansTableBody.innerHTML = '<tr class="loading"><td colspan="7">Loading Commvault plans…</td></tr>';
      return;
    }

    if (commvaultPlansState.error) {
      $commvaultPlansTableBody.innerHTML = '<tr class="empty"><td colspan="7">Failed to load Commvault plan data.</td></tr>';
      return;
    }

    if (!plans.length) {
      $commvaultPlansTableBody.innerHTML = '<tr class="empty"><td colspan="7">No Commvault plans available.</td></tr>';
      return;
    }

    if (!filteredPlans.length) {
      $commvaultPlansTableBody.innerHTML = '<tr class="empty"><td colspan="7">No Commvault plans match the selected type.</td></tr>';
      return;
    }

    const rows = filteredPlans.map((plan) => {
      if (!plan || typeof plan !== 'object') return '';
      const name = plan.name ? String(plan.name) : 'Unnamed plan';
      const planId = Number(plan.plan_id);
      const planTypeLabel = plan.plan_type ? String(plan.plan_type) : '—';
      const entitiesValue = Number(plan.associated_entities);
      const entitiesLabel = Number.isFinite(entitiesValue) ? entitiesValue.toLocaleString() : '—';
      const rpoLabel = plan.rpo ? String(plan.rpo) : '—';
      const copyValue = Number(plan.copy_count);
      const copyLabel = Number.isFinite(copyValue) ? copyValue.toLocaleString() : '—';
      const statusLabelRaw = plan.status ? String(plan.status) : '';
      const statusClass = statusLabelRaw ? getCommvaultStatusClass(statusLabelRaw) : '';
      const statusCell = statusLabelRaw
        ? `<span class="status-pill${statusClass ? ` ${statusClass}` : ''}">${escapeHtml(statusLabelRaw)}</span>`
        : '<span class="muted">Unknown</span>';
      const tags = Array.isArray(plan.tags) ? plan.tags.filter((tag) => tag && typeof tag === 'string') : [];
      const tagsCell = tags.length
        ? `<div class="commvault-plan-tags">${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}</div>`
        : '<span class="muted">No tags</span>';
      const metaPieces = [];
      if (Number.isFinite(planId)) {
        metaPieces.push(`ID ${planId}`);
      }
      const metaLine = metaPieces.length ? `<span class="muted">${escapeHtml(metaPieces.join(' · '))}</span>` : '';

      return `
        <tr>
          <td class="plan-name"><strong>${escapeHtml(name)}</strong>${metaLine}</td>
          <td>${planTypeLabel !== '—' ? escapeHtml(planTypeLabel) : '—'}</td>
          <td>${entitiesLabel}</td>
          <td>${rpoLabel !== '—' ? escapeHtml(rpoLabel) : '—'}</td>
          <td>${copyLabel}</td>
          <td>${statusCell}</td>
          <td>${tagsCell}</td>
        </tr>`;
    }).filter(Boolean);

    $commvaultPlansTableBody.innerHTML = rows.join('');
  }

  async function loadCommvaultPlans(force) {
    if (commvaultPlansState.loading) return;
    const now = Date.now();
    const fetchKey = 'plans';
    if (
      !force &&
      commvaultPlansState.lastFetchKey === fetchKey &&
      commvaultPlansState.lastFetchMs &&
      now - commvaultPlansState.lastFetchMs < 30000
    ) {
      renderCommvaultPlans();
      return;
    }

    commvaultPlansState.loading = true;
    commvaultPlansState.error = null;
    setCommvaultPlansStatus('Loading Commvault plans…', false, 0);
    renderCommvaultPlans();

    try {
      const params = new URLSearchParams();
      if (force) params.set('refresh', '1');
      const query = params.toString();
      const url = query ? `${API_BASE}/commvault/plans?${query}` : `${API_BASE}/commvault/plans`;
      const res = await fetch(url);
      if (!res.ok) {
        throw new Error(`${res.status} ${res.statusText}`);
      }
      const data = await res.json().catch(() => ({}));
      const plans = Array.isArray(data?.plans) ? data.plans : [];
      commvaultPlansState.plans = plans.filter((plan) => plan && typeof plan === 'object');
      commvaultPlansState.generatedAt = data?.generated_at || null;
      commvaultPlansState.totalPlans = Number(data?.total_cached) || commvaultPlansState.plans.length;
      const types = Array.isArray(data?.plan_types)
        ? data.plan_types.filter((type) => typeof type === 'string' && type.trim())
        : [];
      commvaultPlansState.planTypes = types.sort((a, b) => a.localeCompare(b));
      commvaultPlansState.lastFetchMs = now;
      commvaultPlansState.lastFetchKey = fetchKey;
      setCommvaultPlansStatus('', false);
    } catch (err) {
      console.error('Failed to load Commvault plans', err);
      commvaultPlansState.error = err;
      commvaultPlansState.lastFetchKey = null;
      setCommvaultPlansStatus(`Failed to load Commvault plans: ${err?.message || err}`, true, 0);
    } finally {
      commvaultPlansState.loading = false;
      renderCommvaultPlans();
    }
  }

  function renderCommvaultStorage() {
    if (commvaultStorageState.loading) {
      setCommvaultStorageStatus('Loading storage pools…');
    } else if (commvaultStorageState.error) {
      setCommvaultStorageStatus(`Failed to load storage pools: ${commvaultStorageState.error?.message || commvaultStorageState.error}`, true);
    } else {
      setCommvaultStorageStatus('');
    }

    const pools = commvaultStorageState.pools || [];
    if (pools.length === 0 && !commvaultStorageState.loading) {
      setCommvaultStorageStatus('No storage pools found.', false);
    }

    if ($commvaultStorageSummary) {
      const fetched = commvaultStorageState.fetchedAt ? ` — updated ${commvaultStorageState.fetchedAt}` : '';
      const totalCapacity = pools.reduce((sum, pool) => sum + (Number(pool.total_capacity_bytes) || 0), 0);
      const usedCapacity = pools.reduce((sum, pool) => sum + (Number(pool.used_bytes) || 0), 0);
      const summaryText = `Showing ${pools.length} storage pool(s)${fetched}`;
      const capacityText = totalCapacity ? ` — total capacity ${formatCommvaultBytes(totalCapacity)}, used ${formatCommvaultBytes(usedCapacity)}` : '';
      $commvaultStorageSummary.textContent = `${summaryText}${capacityText}`;
    }

    if ($commvaultStorageTableBody) {
      if (!pools.length) {
        $commvaultStorageTableBody.innerHTML = '<tr class="empty"><td colspan="10">Storage metrics not available.</td></tr>';
      } else {
        const selectedId = Number(commvaultStorageState.selectedId);
        const rows = pools.map((pool) => {
          const usagePct = typeof pool.usage_percent === 'number' && Number.isFinite(pool.usage_percent) && pool.usage_percent >= 0
            ? pool.usage_percent
            : null;
          const usageLabel = usagePct !== null ? `${usagePct.toFixed(1)}%` : '—';
          const dedupeRatioValue = typeof pool.dedupe_ratio === 'number' && pool.dedupe_ratio > 0 ? pool.dedupe_ratio : null;
          const dedupeLabel = dedupeRatioValue !== null ? `${dedupeRatioValue.toFixed(2)}x` : '—';
          const used = formatCommvaultBytes(pool.used_bytes);
          const free = formatCommvaultBytes(pool.free_bytes);
          const capacity = formatCommvaultBytes(pool.total_capacity_bytes);
          const status = escapeHtml(pool.status || 'Unknown');
          const region = escapeHtml(pool.region_name || '—');
          const policy = escapeHtml(pool.storage_policy_name || '—');
          const poolIdNum = Number(pool.pool_id);
          const rowClasses = [poolIdNum === selectedId ? 'active' : ''].filter(Boolean).join(' ');
          return `
            <tr class="${rowClasses}" data-commvault-pool-id="${escapeHtml(pool.pool_id)}">
              <td>${escapeHtml(pool.name || `Pool ${pool.pool_id}`)}</td>
              <td>${status}</td>
              <td>${policy}</td>
              <td>${region}</td>
              <td>${capacity}</td>
              <td>${used}</td>
              <td>${free}</td>
              <td>${usageLabel}</td>
              <td>${dedupeLabel}</td>
              <td>${escapeHtml(pool.number_of_nodes ?? '—')}</td>
            </tr>`;
        }).join('');
        $commvaultStorageTableBody.innerHTML = rows;
      }
    }

    renderCommvaultStorageDetail();
  }

  function renderCommvaultStorageDetail() {
    if (!$commvaultStorageDetail) return;
    const pools = commvaultStorageState.pools || [];
    if (!pools.length) {
      $commvaultStorageDetail.innerHTML = '<p class="commvault-placeholder">Select a storage pool to see detailed metrics.</p>';
      return;
    }
    const selectedIdNum = Number(commvaultStorageState.selectedId);
    let selected = pools.find((pool) => Number(pool.pool_id) === selectedIdNum);
    if (!selected) {
      selected = pools[0];
      commvaultStorageState.selectedId = selected?.pool_id ?? null;
    }
    if (!selected) {
      $commvaultStorageDetail.innerHTML = '<p class="commvault-placeholder">No storage pools available.</p>';
      return;
    }
    const stats = [
      ['Status', selected.status || 'Unknown'],
      ['Storage policy', selected.storage_policy_name || '—'],
      ['Policy ID', selected.storage_policy_id ?? '—'],
      ['Region', selected.region_name || '—'],
      ['Capacity', formatCommvaultBytes(selected.total_capacity_bytes)],
      ['Used', formatCommvaultBytes(selected.used_bytes)],
      ['Free', formatCommvaultBytes(selected.free_bytes)],
      ['Logical', formatCommvaultBytes(selected.logical_capacity_bytes)],
      ['Usage', typeof selected.usage_percent === 'number' && Number.isFinite(selected.usage_percent) && selected.usage_percent >= 0 ? `${selected.usage_percent.toFixed(1)}%` : '—'],
      ['Dedupe ratio', typeof selected.dedupe_ratio === 'number' && selected.dedupe_ratio > 0 ? `${selected.dedupe_ratio.toFixed(2)}x` : '—'],
      ['Dedupe savings', formatCommvaultBytes(selected.dedupe_savings_bytes)],
      ['Nodes', selected.number_of_nodes ?? '—'],
      ['Archive storage', selected.is_archive_storage ? 'Yes' : 'No'],
      ['Cloud class', selected.cloud_storage_class_name || '—'],
      ['Libraries', (selected.library_ids && selected.library_ids.length) ? selected.library_ids.join(', ') : '—'],
    ];

    const detailRows = stats.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value ?? '—')}</dd>`).join('');
    let rawJson = '';
    try {
      rawJson = JSON.stringify(selected.details || {}, null, 2);
    } catch {
      rawJson = '';
    }

    $commvaultStorageDetail.innerHTML = `
      <div>
        <h3>${escapeHtml(selected.name || `Pool ${selected.pool_id}`)}</h3>
        <dl>${detailRows}</dl>
      </div>
      ${rawJson ? `<pre>${escapeHtml(rawJson)}</pre>` : ''}
    `;
  }

  function setCommvaultServerStatus(message, isError = false) {
    if (!$commvaultServerStatus) return;
    if (!message) {
      $commvaultServerStatus.hidden = true;
      $commvaultServerStatus.textContent = '';
      $commvaultServerStatus.classList.remove('error');
      return;
    }
    $commvaultServerStatus.hidden = false;
    $commvaultServerStatus.textContent = message;
    $commvaultServerStatus.classList.toggle('error', !!isError);
  }

  function renderCommvaultServerSuggestions() {
    if (!$commvaultServerSuggestions) return;
    const suggestions = Array.isArray(commvaultServerState.suggestions) ? commvaultServerState.suggestions : [];
    const query = (commvaultServerState.query || '').trim();
    if (!suggestions.length || !query) {
      $commvaultServerSuggestions.hidden = true;
      $commvaultServerSuggestions.innerHTML = '';
      return;
    }
    const frag = document.createDocumentFragment();
    for (const item of suggestions.slice(0, 8)) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.dataset.clientId = item?.client_id != null ? String(item.client_id) : '';
      btn.dataset.clientName = item?.display_name || item?.name || '';
      const display = item?.display_name || item?.name || (item?.client_id != null ? `#${item.client_id}` : 'Unknown');
      const subtitle = item?.client_id != null ? `ID ${item.client_id}${item?.name && item.name !== display ? ` · ${item.name}` : ''}` : (item?.name || '');
      btn.innerHTML = `<strong>${escapeHtml(display)}</strong>${subtitle ? `<span class="muted">${escapeHtml(subtitle)}</span>` : ''}`;
      frag.append(btn);
    }
    $commvaultServerSuggestions.innerHTML = '';
    $commvaultServerSuggestions.append(frag);
    $commvaultServerSuggestions.hidden = false;
  }

  function renderCommvaultServerBreakdown(items, target) {
    if (!target) return;
    const list = Array.isArray(items) ? items.filter(Boolean) : [];
    if (!list.length) {
      target.innerHTML = '<li class="empty">No data yet.</li>';
      return;
    }
    const frag = document.createDocumentFragment();
    for (const entry of list.slice(0, 8)) {
      const label = entry?.label || entry?.plan || entry?.name || 'Unnamed';
      const count = entry?.restore_points ?? entry?.count ?? entry?.total ?? 0;
      const li = document.createElement('li');
      const labelSpan = document.createElement('span');
      labelSpan.textContent = label;
      const countSpan = document.createElement('span');
      countSpan.className = 'count';
      countSpan.textContent = String(count);
      li.append(labelSpan, countSpan);
      frag.append(li);
    }
    target.innerHTML = '';
    target.append(frag);
  }

  function renderCommvaultServerMetrics() {
    if (!$commvaultServerMetrics) return;
    const stats = commvaultServerState.stats;
    if (!$commvaultServerMetricCount) return;
    if (!stats || !commvaultServerState.summary) {
      $commvaultServerMetricCount.textContent = '—';
      if ($commvaultServerMetricWindow) $commvaultServerMetricWindow.textContent = '';
      if ($commvaultServerMetricApp) $commvaultServerMetricApp.textContent = '—';
      if ($commvaultServerMetricAppExtra) $commvaultServerMetricAppExtra.textContent = '';
      if ($commvaultServerMetricMedia) $commvaultServerMetricMedia.textContent = '—';
      if ($commvaultServerMetricMediaExtra) $commvaultServerMetricMediaExtra.textContent = '';
      if ($commvaultServerMetricReduction) $commvaultServerMetricReduction.textContent = '—';
      if ($commvaultServerMetricReductionRatio) $commvaultServerMetricReductionRatio.textContent = '';
      return;
    }
    const jobCount = stats.job_count ?? commvaultServerState.jobs.length;
    $commvaultServerMetricCount.textContent = String(jobCount);
    const windowHours = commvaultServerState.jobMetrics?.window_hours ?? commvaultServerState.sinceHours ?? 0;
    if ($commvaultServerMetricWindow) {
      $commvaultServerMetricWindow.textContent = windowHours > 0 ? `${windowHours}h window` : 'All time window';
    }
    if ($commvaultServerMetricApp) {
      $commvaultServerMetricApp.textContent = formatCommvaultBytes(stats.total_application_bytes);
    }
    if ($commvaultServerMetricAppExtra) {
      const retained = stats.retained_jobs ?? 0;
      $commvaultServerMetricAppExtra.textContent = retained ? `${retained} retained job(s)` : '';
    }
    if ($commvaultServerMetricMedia) {
      $commvaultServerMetricMedia.textContent = formatCommvaultBytes(stats.total_media_bytes);
    }
    if ($commvaultServerMetricMediaExtra) {
      const savingsBytes = stats.savings_bytes ?? null;
      $commvaultServerMetricMediaExtra.textContent = savingsBytes ? `Saved ${formatCommvaultBytes(savingsBytes)}` : '';
    }
    if ($commvaultServerMetricReduction) {
      const avgSavings = stats.average_savings_percent;
      $commvaultServerMetricReduction.textContent = typeof avgSavings === 'number' ? formatCommvaultPercent(avgSavings) : '—';
    }
    if ($commvaultServerMetricReductionRatio) {
      $commvaultServerMetricReductionRatio.textContent = stats.average_reduction_ratio_text ? `≈ ${stats.average_reduction_ratio_text}` : '';
    }
    renderCommvaultServerBreakdown(stats.plan_breakdown, $commvaultServerPlanList);
    renderCommvaultServerBreakdown(stats.subclient_breakdown, $commvaultServerSubclientList);
    renderCommvaultServerBreakdown(stats.policy_breakdown, $commvaultServerPolicyList);
  }

  function renderCommvaultServerTable() {
    if (!$commvaultServerTableBody) return;
    const jobs = Array.isArray(commvaultServerState.jobs) ? commvaultServerState.jobs : [];
    if (!jobs.length) {
      $commvaultServerTableBody.innerHTML = '<tr class="empty"><td colspan="9">Search for a server to see recent restore points.</td></tr>';
      return;
    }
    const rows = jobs.map((job) => {
      const jobId = job?.job_id != null ? String(job.job_id) : '–';
      const statusLabel = job?.localized_status || job?.status || 'Unknown';
      const statusClass = getCommvaultStatusClass(statusLabel);
      const statusHtml = `<span class="status-pill${statusClass ? ` ${statusClass}` : ''}">${escapeHtml(statusLabel)}</span>`;
      const plan = job?.plan_name || '—';
      const subclient = job?.subclient_name || job?.backup_set_name || '—';
      const start = formatCommvaultDate(job?.start_time);
      const retain = formatCommvaultDate(job?.retain_until);
      const appSize = formatCommvaultBytes(job?.size_of_application_bytes);
      const mediaSize = formatCommvaultBytes(job?.size_on_media_bytes);
      const savings = formatCommvaultPercent(job?.percent_savings);
      return `
        <tr>
          <td><strong>${escapeHtml(jobId)}</strong></td>
          <td>${statusHtml}</td>
          <td>${plan !== '—' ? escapeHtml(plan) : '—'}</td>
          <td>${subclient !== '—' ? escapeHtml(subclient) : '—'}</td>
          <td>${escapeHtml(start)}</td>
          <td>${escapeHtml(retain)}</td>
          <td>${escapeHtml(appSize)}</td>
          <td>${escapeHtml(mediaSize)}</td>
          <td>${escapeHtml(savings)}</td>
        </tr>`;
    });
    $commvaultServerTableBody.innerHTML = rows.join('');
  }

  function ensureCommvaultCanvas(canvas) {
    if (!canvas) return null;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    const dpr = window.devicePixelRatio || 1;
    const displayWidth = canvas.clientWidth || canvas.width;
    const displayHeight = canvas.clientHeight || canvas.height;
    if (canvas.style.width === '') canvas.style.width = `${displayWidth}px`;
    if (canvas.style.height === '') canvas.style.height = `${displayHeight}px`;
    const scaledWidth = Math.max(1, Math.floor(displayWidth * dpr));
    const scaledHeight = Math.max(1, Math.floor(displayHeight * dpr));
    if (canvas.width !== scaledWidth || canvas.height !== scaledHeight) {
      canvas.width = scaledWidth;
      canvas.height = scaledHeight;
    }
    ctx.resetTransform?.();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, width: displayWidth, height: displayHeight };
  }

  function drawCommvaultServerLineChart(canvas, datasets, options = {}) {
    const surface = ensureCommvaultCanvas(canvas);
    if (!surface) return;
    const { ctx, width, height } = surface;
    const scaleX = canvas.width / Math.max(1, width);
    const scaleY = canvas.height / Math.max(1, height);
    const chartInfo = {
      points: [],
      axisLabels: Array.isArray(options.labels) ? options.labels : [],
    };
    ctx.clearRect(0, 0, width, height);
    ctx.font = '12px system-ui, sans-serif';
    ctx.fillStyle = '#64748b';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';

    const maxPoints = Math.max(0, ...datasets.map((ds) => Array.isArray(ds?.values) ? ds.values.length : 0));
    if (maxPoints < 2) {
      ctx.fillText('Not enough data to chart', 12, height / 2);
      registerCommvaultChart(canvas, chartInfo);
      return;
    }

    let minValue = Number.POSITIVE_INFINITY;
    let maxValue = Number.NEGATIVE_INFINITY;
    let hasValue = false;
    for (const ds of datasets) {
      for (const raw of ds.values || []) {
        if (raw == null || Number.isNaN(raw)) continue;
        if (raw < minValue) minValue = raw;
        if (raw > maxValue) maxValue = raw;
        hasValue = true;
      }
    }
    if (!hasValue) {
      ctx.fillText('Not enough data to chart', 12, height / 2);
      registerCommvaultChart(canvas, chartInfo);
      return;
    }
    if (!Number.isFinite(minValue) || !Number.isFinite(maxValue) || minValue === maxValue) {
      minValue = 0;
      maxValue = Number.isFinite(maxValue) && maxValue > 0 ? maxValue : 1;
    }

    const padding = 16;
    const usableWidth = Math.max(1, width - padding * 2);
    const usableHeight = Math.max(1, height - padding * 2);

    ctx.strokeStyle = 'rgba(148, 163, 184, 0.35)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padding, height - padding);
    ctx.lineTo(width - padding, height - padding);
    ctx.stroke();

    for (const dataset of datasets) {
      const values = Array.isArray(dataset?.values) ? dataset.values : [];
      if (!values.length) continue;
      ctx.beginPath();
      ctx.lineWidth = dataset?.lineWidth || 2.2;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.strokeStyle = dataset?.color || '#3b82f6';
      let hasMove = false;
      const denominator = maxValue - minValue || 1;
      const stepX = values.length > 1 ? usableWidth / (values.length - 1) : usableWidth;
      for (let index = 0; index < values.length; index += 1) {
        const raw = values[index];
        if (raw == null || Number.isNaN(raw)) {
          hasMove = false;
          continue;
        }
        const normalised = (raw - minValue) / denominator;
        const x = padding + stepX * index;
        const y = height - padding - Math.max(0, Math.min(1, normalised)) * usableHeight;
        if (!hasMove) {
          ctx.moveTo(x, y);
          hasMove = true;
        } else {
          ctx.lineTo(x, y);
        }
      }
      ctx.stroke();

      if (dataset?.drawPoints) {
        ctx.fillStyle = dataset.color || '#3b82f6';
        const denominatorInner = maxValue - minValue || 1;
        const stepXInner = values.length > 1 ? usableWidth / (values.length - 1) : usableWidth;
        const pointLabels = Array.isArray(dataset?.pointLabels) ? dataset.pointLabels : null;
        const datasetLabel = dataset?.name || '';
        for (let index = 0; index < values.length; index += 1) {
          const raw = values[index];
          if (raw == null || Number.isNaN(raw)) continue;
          const normalised = (raw - minValue) / denominatorInner;
          const x = padding + stepXInner * index;
          const y = height - padding - Math.max(0, Math.min(1, normalised)) * usableHeight;
          ctx.beginPath();
          ctx.arc(x, y, 3, 0, Math.PI * 2);
          ctx.fill();

          const axisLabel = chartInfo.axisLabels[index] || '';
          const dateLabel = (Array.isArray(options.tooltipDates) ? options.tooltipDates[index] : '') || axisLabel;
          const pointLabel = pointLabels ? pointLabels[index] : null;
          chartInfo.points.push({
            x: x * scaleX,
            y: y * scaleY,
            datasetLabel,
            valueLabel: pointLabel,
            dateLabel,
          });
        }
      }
    }

    const axisLabels = Array.isArray(options?.labels) ? options.labels : null;
    if (axisLabels && axisLabels.length) {
      const baseValues = Array.isArray(datasets[0]?.values) ? datasets[0].values : [];
      const labelCount = Math.min(axisLabels.length, baseValues.length);
      if (labelCount > 0) {
        const stepXLabels = labelCount > 1 ? usableWidth / (labelCount - 1) : usableWidth;
        const labelEvery = Math.max(1, options?.labelEvery || Math.ceil(labelCount / 6));
        ctx.save();
        ctx.fillStyle = '#475569';
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.25)';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        for (let index = 0; index < labelCount; index += 1) {
          if (index % labelEvery !== 0 && index !== labelCount - 1 && index !== 0) continue;
          const label = axisLabels[index];
          if (!label) continue;
          const x = padding + stepXLabels * index;
          ctx.beginPath();
          ctx.moveTo(x, height - padding);
          ctx.lineTo(x, height - padding + 4);
          ctx.stroke();
          ctx.fillText(String(label), x, height - padding + 6);
        }
        ctx.restore();
      }
    }

    if (options?.label) {
      ctx.fillStyle = '#475569';
      ctx.fillText(options.label, padding, padding - 4);
    }

    registerCommvaultChart(canvas, chartInfo);
    return chartInfo;
  }

  function renderCommvaultServerCharts() {
    if (!$commvaultServerChartSize || !$commvaultServerChartSavings) return;
    hideCommvaultChartTooltip();
    const timeline = commvaultServerState.stats?.series?.timeline;
    if (!Array.isArray(timeline) || !timeline.length) {
      drawCommvaultServerLineChart($commvaultServerChartSize, []);
      drawCommvaultServerLineChart($commvaultServerChartSavings, []);
      if ($commvaultServerChartSizeUnit) $commvaultServerChartSizeUnit.textContent = '';
      return;
    }

    const appRaw = timeline.map((entry) => {
      const value = entry?.size_of_application_bytes;
      return typeof value === 'number' ? value : Number(value) || 0;
    });
    const mediaRaw = timeline.map((entry) => {
      const value = entry?.size_on_media_bytes;
      return typeof value === 'number' ? value : Number(value) || 0;
    });
    const shortDateLabels = timeline.map((entry) => formatCommvaultChartDate(entry?.start_time));
    const longDateLabels = timeline.map((entry) => formatCommvaultDate(entry?.start_time));
    const appValueLabels = timeline.map((entry) => formatCommvaultBytes(entry?.size_of_application_bytes));
    const mediaValueLabels = timeline.map((entry) => formatCommvaultBytes(entry?.size_on_media_bytes));

    const maxRaw = Math.max(0, ...appRaw, ...mediaRaw);
    const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
    let unitIndex = 0;
    let divisor = 1;
    while (unitIndex < units.length - 1 && maxRaw / divisor >= 1024) {
      divisor *= 1024;
      unitIndex += 1;
    }
    const appValues = appRaw.map((value) => (divisor ? value / divisor : value));
    const mediaValues = mediaRaw.map((value) => (divisor ? value / divisor : value));
    const unitLabel = units[unitIndex];
    if ($commvaultServerChartSizeUnit) {
      $commvaultServerChartSizeUnit.textContent = `Unit: ${unitLabel}`;
    }
    drawCommvaultServerLineChart($commvaultServerChartSize, [
      { values: appValues, color: '#6366f1', drawPoints: true, pointLabels: appValueLabels, name: 'Application' },
      { values: mediaValues, color: '#0ea5e9', drawPoints: true, pointLabels: mediaValueLabels, name: 'Media' },
    ], { labels: shortDateLabels, tooltipDates: longDateLabels });

    const savingsValues = timeline.map((entry) => {
      const value = entry?.percent_savings;
      if (value == null) return null;
      const num = Number(value);
      return Number.isFinite(num) ? num : null;
    });
    const savingsLabels = timeline.map((entry) => (entry?.percent_savings == null ? null : formatCommvaultPercent(entry.percent_savings)));
    drawCommvaultServerLineChart($commvaultServerChartSavings, [
      { values: savingsValues, color: '#f97316', drawPoints: true, pointLabels: savingsLabels, name: 'Data reduction' },
    ], { label: 'Percentage', labels: shortDateLabels, tooltipDates: longDateLabels });
  }

  function updateCommvaultServerSummaryText() {
    if (!$commvaultServerSummary) return;
    if (commvaultServerState.loading) {
      $commvaultServerSummary.textContent = 'Loading server metrics…';
      return;
    }
    if (!commvaultServerState.summary) {
      $commvaultServerSummary.textContent = 'Search for a server to view restore points and retention metrics.';
      return;
    }
    const summary = commvaultServerState.summary;
    const name = summary.display_name || summary.name || `#${summary.client_id}`;
    const stats = commvaultServerState.stats;
    const jobMetrics = commvaultServerState.jobMetrics;
    const jobCount = stats?.job_count ?? jobMetrics?.job_count ?? commvaultServerState.jobs.length;
    const windowHours = jobMetrics?.window_hours ?? commvaultServerState.sinceHours ?? 0;
    const retainedText = commvaultServerState.retainedOnly ? 'retained jobs' : 'all jobs';
    const apps = formatCommvaultBytes(stats?.total_application_bytes);
    const media = formatCommvaultBytes(stats?.total_media_bytes);
    const updated = formatTimestamp(jobMetrics?.fetched_at) || 'recently';
    $commvaultServerSummary.textContent = `Showing ${jobCount} restore point(s) for ${name} (${retainedText}, window ${windowHours > 0 ? `${windowHours}h` : 'all time'}) — app ${apps}, media ${media} — updated ${updated}.`;
  }

  function renderCommvaultServerState() {
    updateCommvaultServerSummaryText();
    renderCommvaultServerMetrics();
    renderCommvaultServerTable();
    renderCommvaultServerCharts();
    renderCommvaultServerSuggestions();
    const loading = commvaultServerState.loading;
    if ($commvaultServerSearchBtn) $commvaultServerSearchBtn.disabled = loading;
    if ($commvaultServerRefresh) $commvaultServerRefresh.disabled = loading;
    if ($commvaultServerQuery) $commvaultServerQuery.disabled = loading && commvaultServerState.refreshing;
    if ($commvaultServerExportButtons) {
      $commvaultServerExportButtons.classList.toggle('disabled', !commvaultServerState.summary || loading);
    }
  }

  async function fetchCommvaultServerSummary(options = { refresh: false }) {
    const inputIdentifier = commvaultServerState.selectedClientId != null
      ? String(commvaultServerState.selectedClientId)
      : (commvaultServerState.clientIdentifier || commvaultServerState.query).trim();
    if (!inputIdentifier) {
      setCommvaultServerStatus('Enter a server name or ID to search.', true);
      return;
    }

    setCommvaultServerStatus('Loading server metrics…');
    commvaultServerState.clientIdentifier = inputIdentifier;
    const params = new URLSearchParams();
    params.set('client', inputIdentifier);
    params.set('job_limit', String(Math.max(0, commvaultServerState.jobLimit || 0)));
    params.set('since_hours', String(Math.max(0, commvaultServerState.sinceHours || 0)));
    params.set('retained_only', commvaultServerState.retainedOnly ? 'true' : 'false');
    if (options?.refresh) params.set('refresh_cache', 'true');

    const fetchKey = `${inputIdentifier}|${params.get('job_limit')}|${params.get('since_hours')}|${params.get('retained_only')}`;
    const now = Date.now();
    if (!options?.refresh && commvaultServerState.lastFetchKey === fetchKey && commvaultServerState.lastFetchMs && now - commvaultServerState.lastFetchMs < 30_000) {
      setCommvaultServerStatus('');
      renderCommvaultServerState();
      return;
    }

    const serial = ++commvaultServerState.requestSerial;
    commvaultServerState.loading = true;
    commvaultServerState.refreshing = !!options?.refresh;
    renderCommvaultServerState();

    try {
      const res = await fetch(`${API_BASE}/commvault/servers/summary?${params.toString()}`);
      if (!res.ok) {
        throw new Error(`${res.status} ${res.statusText}`);
      }
      const data = await res.json().catch(() => ({}));
      if (serial !== commvaultServerState.requestSerial) return;
      applyCommvaultServerSummary(data || {}, inputIdentifier);
      commvaultServerState.lastFetchKey = fetchKey;
      commvaultServerState.lastFetchMs = Date.now();
      setCommvaultServerStatus('');
    } catch (err) {
      if (serial !== commvaultServerState.requestSerial) return;
      commvaultServerState.error = err;
      console.error('Failed to load Commvault server metrics', err);
      setCommvaultServerStatus(`Failed to load server metrics: ${err?.message || err}`, true);
    } finally {
      if (serial === commvaultServerState.requestSerial) {
        commvaultServerState.loading = false;
        commvaultServerState.refreshing = false;
        renderCommvaultServerState();
      }
    }
  }

  function applyCommvaultServerSummary(payload, identifier) {
    const summary = payload?.client || null;
    commvaultServerState.summary = summary;
    commvaultServerState.stats = payload?.stats || null;
    commvaultServerState.jobs = Array.isArray(payload?.jobs) ? payload.jobs : [];
    commvaultServerState.jobMetrics = payload?.job_metrics || null;
    commvaultServerState.lastIdentifier = identifier;
    if (summary?.client_id != null) {
      commvaultServerState.selectedClientId = summary.client_id;
      commvaultServerState.selectedClientName = summary.display_name || summary.name || '';
    }
  }

  function queueCommvaultServerSuggestions(value) {
    const text = (value || '').trim();
    commvaultServerState.query = value;
    if (commvaultServerSuggestionTimer) {
      clearTimeout(commvaultServerSuggestionTimer);
      commvaultServerSuggestionTimer = null;
    }
    if (!text) {
      commvaultServerState.suggestions = [];
      renderCommvaultServerSuggestions();
      return;
    }
    const serial = ++commvaultServerState.suggestionSerial;
    commvaultServerSuggestionTimer = setTimeout(async () => {
      try {
        const params = new URLSearchParams({ q: text, limit: '8' });
        const res = await fetch(`${API_BASE}/commvault/servers/search?${params.toString()}`);
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        const data = await res.json().catch(() => ({}));
        if (serial !== commvaultServerState.suggestionSerial) return;
        commvaultServerState.suggestions = Array.isArray(data?.results) ? data.results : [];
        renderCommvaultServerSuggestions();
      } catch (err) {
        if (serial !== commvaultServerState.suggestionSerial) return;
        console.warn('Commvault server suggestion lookup failed', err);
        commvaultServerState.suggestions = [];
        renderCommvaultServerSuggestions();
      }
    }, 220);
  }

  function handleCommvaultServerSuggestionClick(event) {
    const btn = event.target.closest('button[data-client-id]');
    if (!btn) return;
    event.preventDefault();
    if (commvaultServerSuggestionTimer) {
      clearTimeout(commvaultServerSuggestionTimer);
      commvaultServerSuggestionTimer = null;
    }
    commvaultServerState.suggestionSerial += 1;
    const clientId = btn.dataset.clientId ? Number(btn.dataset.clientId) : null;
    const clientName = btn.dataset.clientName || btn.textContent || '';
    commvaultServerState.selectedClientId = Number.isFinite(clientId) ? clientId : null;
    commvaultServerState.selectedClientName = clientName.trim();
    commvaultServerState.clientIdentifier = commvaultServerState.selectedClientId != null ? String(commvaultServerState.selectedClientId) : commvaultServerState.selectedClientName;
    commvaultServerState.suggestions = [];
    if ($commvaultServerQuery) {
      $commvaultServerQuery.value = commvaultServerState.selectedClientName || btn.textContent || '';
    }
    renderCommvaultServerSuggestions();
    fetchCommvaultServerSummary({ refresh: false });
  }

  function handleCommvaultServerSearch(forceRefresh = false) {
    const inputValue = $commvaultServerQuery ? ($commvaultServerQuery.value || '').trim() : '';
    if (!inputValue && commvaultServerState.selectedClientId == null) {
      setCommvaultServerStatus('Enter a server name or ID to search.', true);
      return;
    }
    if (commvaultServerSuggestionTimer) {
      clearTimeout(commvaultServerSuggestionTimer);
      commvaultServerSuggestionTimer = null;
    }
    commvaultServerState.suggestionSerial += 1;
    if (commvaultServerState.selectedClientName && commvaultServerState.selectedClientName !== inputValue) {
      commvaultServerState.selectedClientId = null;
      commvaultServerState.selectedClientName = '';
    }
    commvaultServerState.clientIdentifier = commvaultServerState.selectedClientId != null ? String(commvaultServerState.selectedClientId) : inputValue;
    commvaultServerState.query = inputValue;
    commvaultServerState.suggestions = [];
    renderCommvaultServerSuggestions();
    fetchCommvaultServerSummary({ refresh: forceRefresh });
  }

  function downloadCommvaultServerExport(format) {
    if (!commvaultServerState.lastIdentifier) {
      setCommvaultServerStatus('Search for a server before exporting.', true);
      return;
    }
    const params = new URLSearchParams();
    params.set('client', commvaultServerState.lastIdentifier);
    params.set('file_format', format);
    params.set('job_limit', String(Math.max(0, commvaultServerState.jobLimit || 0)));
    params.set('since_hours', String(Math.max(0, commvaultServerState.sinceHours || 0)));
    params.set('retained_only', commvaultServerState.retainedOnly ? 'true' : 'false');
    const url = `${API_BASE}/commvault/servers/export?${params.toString()}`;
    const link = document.createElement('a');
    link.href = url;
    link.rel = 'noopener';
    link.target = '_blank';
    document.body.append(link);
    link.click();
    link.remove();
  }

  async function loadCommvaultData(force) {
    if (commvaultState.loading) return;
    const now = Date.now();
    const fetchKey = `since:${commvaultState.sinceHours}`;
    if (!force && commvaultState.lastFetchKey === fetchKey && commvaultState.lastFetchMs && now - commvaultState.lastFetchMs < 30000) {
      updateCommvaultSummary();
      renderCommvaultTable();
      return;
    }
    commvaultState.loading = true;
    commvaultState.error = null;
    updateCommvaultSummary();
    setCommvaultStatus('Loading Commvault backups…', false, 0);
    try {
      const res = await fetch(`${API_BASE}/commvault/backups?since_hours=${encodeURIComponent(commvaultState.sinceHours || 0)}`);
      if (!res.ok) {
        throw new Error(`${res.status} ${res.statusText}`);
      }
      const data = await res.json().catch(() => ({}));
      applyCommvaultPayload(data || {});
      commvaultState.lastFetchMs = Date.now();
      commvaultState.lastFetchKey = fetchKey;
      renderCommvaultTable();
      setCommvaultStatus('', false);
    } catch (err) {
      console.error('Failed to load Commvault data', err);
      commvaultState.error = err;
      setCommvaultStatus(`Failed to load Commvault data: ${err?.message || err}`, true, 0);
      commvaultState.lastFetchKey = null;
    } finally {
      commvaultState.loading = false;
      updateCommvaultSummary();
    }
  }

  async function loadCommvaultStorage(force) {
    if (commvaultStorageState.loading) return;
    const now = Date.now();
    if (!force && commvaultStorageState.lastFetchMs && now - commvaultStorageState.lastFetchMs < COMMVAULT_STORAGE_REFRESH_INTERVAL_MS) {
      renderCommvaultStorage();
      return;
    }
    commvaultStorageState.loading = true;
    commvaultStorageState.error = null;
    renderCommvaultStorage();
    try {
      const res = await fetch(`${API_BASE}/commvault/storage`);
      if (!res.ok) {
        throw new Error(`${res.status} ${res.statusText}`);
      }
      const data = await res.json().catch(() => ({}));
      const pools = Array.isArray(data?.pools) ? data.pools : [];
      commvaultStorageState.pools = pools;
      commvaultStorageState.fetchedAt = data?.generated_at || null;
      const firstId = pools.length ? Number(pools[0]?.pool_id) : NaN;
      if (!pools.length) {
        commvaultStorageState.selectedId = null;
      } else if (!Number.isFinite(Number(commvaultStorageState.selectedId))) {
        commvaultStorageState.selectedId = Number.isFinite(firstId) ? firstId : null;
      } else if (!pools.some((pool) => Number(pool?.pool_id) === Number(commvaultStorageState.selectedId))) {
        commvaultStorageState.selectedId = Number.isFinite(firstId) ? firstId : null;
      }
      commvaultStorageState.lastFetchMs = now;
    } catch (err) {
      console.error('Failed to load Commvault storage data', err);
      commvaultStorageState.error = err;
    } finally {
      commvaultStorageState.loading = false;
      renderCommvaultStorage();
    }
  }

  async function refreshCommvaultData() {
    if (commvaultState.loading) return;
    commvaultState.loading = true;
    commvaultState.error = null;
    updateCommvaultSummary();
    setCommvaultStatus('Updating Commvault backups…', false, 0);
    try {
      const params = new URLSearchParams();
      params.set('limit', String(commvaultState.limit || 0));
      params.set('since_hours', String(commvaultState.sinceHours || 0));
      const res = await fetch(`${API_BASE}/commvault/backups/refresh?${params.toString()}`, { method: 'POST' });
      if (!res.ok) {
        throw new Error(`${res.status} ${res.statusText}`);
      }
      const data = await res.json().catch(() => ({}));
      applyCommvaultPayload(data || {});
      commvaultState.lastFetchMs = Date.now();
      commvaultState.lastFetchKey = `since:${commvaultState.sinceHours}`;
      renderCommvaultTable();
      setCommvaultStatus('Commvault backups updated.', false);
    } catch (err) {
      console.error('Failed to refresh Commvault data', err);
      commvaultState.error = err;
      setCommvaultStatus(`Failed to refresh Commvault data: ${err?.message || err}`, true, 0);
      commvaultState.lastFetchKey = null;
    } finally {
      commvaultState.loading = false;
      updateCommvaultSummary();
    }
  }

  if ($commvaultTabs) {
    $commvaultTabs.addEventListener('click', (event) => {
      const btn = event.target.closest('button[data-commvault-tab]');
      if (!btn) return;
      const tab = btn.getAttribute('data-commvault-tab') || 'backups';
      setCommvaultTab(tab);
    });
  }

  if ($commvaultRefresh) {
    $commvaultRefresh.addEventListener('click', (event) => {
      event.preventDefault();
      refreshCommvaultData();
    });
  }

  if ($commvaultStorageRefresh) {
    $commvaultStorageRefresh.addEventListener('click', (event) => {
      event.preventDefault();
      loadCommvaultStorage(true);
    });
  }

  if ($commvaultSince) {
    $commvaultSince.value = String(commvaultState.sinceHours);
    $commvaultSince.addEventListener('change', (event) => {
      const next = Number(event.target.value);
      if (!Number.isFinite(next) || next < 1 || next > 48) {
        event.target.value = String(commvaultState.sinceHours);
        return;
      }
      if (next === commvaultState.sinceHours) return;
      commvaultState.sinceHours = next;
      updateCommvaultSummary();
      loadCommvaultData(true);
    });
  }

  if ($commvaultPlansType) {
    $commvaultPlansType.addEventListener('change', (event) => {
      const value = (event.target.value || 'all').trim();
      commvaultPlansState.planType = value || 'all';
      renderCommvaultPlans();
    });
  }

  if ($commvaultPlansRefresh) {
    $commvaultPlansRefresh.addEventListener('click', () => loadCommvaultPlans(true));
  }

  renderCommvaultPlans();

  if ($commvaultSearch) {
    $commvaultSearch.value = commvaultState.search;
    const applySearch = debounce(() => {
      setCommvaultSearch($commvaultSearch.value);
      renderCommvaultTable();
    }, 200);
    $commvaultSearch.addEventListener('input', applySearch);
  }

  $commvaultStorageTableBody?.addEventListener('click', (event) => {
    const row = event.target.closest('tr[data-commvault-pool-id]');
    if (!row) return;
    const id = Number(row.dataset.commvaultPoolId);
    if (!Number.isFinite(id)) return;
    commvaultStorageState.selectedId = id;
    renderCommvaultStorage();
  });

  if ($commvaultServerQuery) {
    $commvaultServerQuery.addEventListener('input', (event) => {
      queueCommvaultServerSuggestions(event.target.value || '');
    });
    $commvaultServerQuery.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        handleCommvaultServerSearch(false);
      }
    });
  }

  if ($commvaultServerSearchBtn) {
    $commvaultServerSearchBtn.addEventListener('click', () => handleCommvaultServerSearch(false));
  }

  if ($commvaultServerRefresh) {
    $commvaultServerRefresh.addEventListener('click', () => handleCommvaultServerSearch(true));
  }

  if ($commvaultServerRetained) {
    $commvaultServerRetained.addEventListener('change', () => {
      commvaultServerState.retainedOnly = !!$commvaultServerRetained.checked;
      if (commvaultServerState.summary && !commvaultServerState.loading) {
        fetchCommvaultServerSummary({ refresh: true });
      }
    });
  }

  if ($commvaultServerSince) {
    $commvaultServerSince.addEventListener('change', () => {
      const value = Number($commvaultServerSince.value);
      const next = Number.isFinite(value) ? Math.max(0, value) : 0;
      if (commvaultServerState.sinceHours === next) return;
      commvaultServerState.sinceHours = next;
      if (commvaultServerState.summary && !commvaultServerState.loading) {
        fetchCommvaultServerSummary({ refresh: true });
      }
    });
  }

  if ($commvaultServerLimit) {
    const syncLimit = () => {
      const value = Number($commvaultServerLimit.value);
      const next = Number.isFinite(value) ? Math.max(0, Math.min(2000, value)) : 0;
      $commvaultServerLimit.value = String(next);
      if (commvaultServerState.jobLimit === next) return next;
      commvaultServerState.jobLimit = next;
      return next;
    };
    $commvaultServerLimit.addEventListener('change', () => {
      const next = syncLimit();
      if (commvaultServerState.summary && !commvaultServerState.loading && next != null) {
        fetchCommvaultServerSummary({ refresh: true });
      }
    });
    $commvaultServerLimit.addEventListener('blur', syncLimit);
  }

  if ($commvaultServerSuggestions) {
    $commvaultServerSuggestions.addEventListener('click', handleCommvaultServerSuggestionClick);
  }

  if ($commvaultServerExportButtons) {
    $commvaultServerExportButtons.addEventListener('click', (event) => {
      const btn = event.target.closest('button[data-format]');
      if (!btn || btn.disabled) return;
      const format = btn.dataset.format;
      if (!format) return;
      downloadCommvaultServerExport(format);
    });
  }

  document.addEventListener('click', (event) => {
    if (commvaultState.tab !== 'servers') return;
    if (!$commvaultServerSuggestions || $commvaultServerSuggestions.hidden) return;
    if ($commvaultServerSuggestions.contains(event.target)) return;
    if ($commvaultServerQuery && $commvaultServerQuery.contains(event.target)) return;
    commvaultServerState.suggestions = [];
    renderCommvaultServerSuggestions();
  });

  renderCommvaultServerState();

  // ---------------------------
  // vCenter inventory
  // ---------------------------

  function getActiveVCenter() {
    if (!vcenterState.instances.length) return null;
    const match = vcenterState.instances.find((inst) => inst.id === vcenterState.activeId);
    return match || vcenterState.instances[0] || null;
  }

  function setVCenterStatus(message = null, tone = 'info') {
    if (!$vcenterStatus) return;
    const text = message || describeVCenterSelection() || '';
    $vcenterStatus.textContent = text;
    $vcenterStatus.classList.remove('error', 'success');
    if (tone === 'error') {
      $vcenterStatus.classList.add('error');
    } else if (tone === 'success') {
      $vcenterStatus.classList.add('success');
    }
  }

  function renderVCenterTabs() {
    if (!$vcenterTabs) return;
    $vcenterTabs.innerHTML = '';
    if (!vcenterState.instances.length) {
      $vcenterTabs.classList.add('empty');
      return;
    }
    $vcenterTabs.classList.remove('empty');
    const frag = document.createDocumentFragment();
    const realInstanceCount = vcenterState.instances.filter((entry) => entry && entry.id && entry.id !== ALL_VCENTER_ID).length;
    vcenterState.instances.forEach((inst) => {
      if (!inst || !inst.id) return;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'tab';
      btn.dataset.vcenterId = inst.id;
      btn.textContent = inst.name || 'vCenter';
      if (inst.id === vcenterState.activeId) {
        btn.classList.add('active');
      }
      const tooltipParts = [];
      if (inst.aggregate || inst.id === ALL_VCENTER_ID) {
        const countLabel = realInstanceCount === 1 ? 'vCenter' : 'vCenters';
        tooltipParts.push(`Combined view across ${realInstanceCount} ${countLabel}`);
        if (inst.vm_count != null && !Number.isNaN(inst.vm_count)) {
          tooltipParts.push(`Known VMs: ${String(inst.vm_count)}`);
        }
      } else {
        if (inst.base_url) tooltipParts.push(inst.base_url);
        if (inst.vm_count != null && !Number.isNaN(inst.vm_count)) {
          tooltipParts.push(`Cached VMs: ${String(inst.vm_count)}`);
        }
      }
      if (inst.last_refresh) {
        try {
          tooltipParts.push(`Last update: ${amsDateTimeString(new Date(inst.last_refresh))}`);
        } catch {}
      }
      if (tooltipParts.length) {
        btn.title = tooltipParts.join('\n');
      }
      frag.appendChild(btn);
    });
    $vcenterTabs.appendChild(frag);
  }

  function vcenterVmMatches(vm, token) {
    if (!vm || !token) return false;
    const lower = token.toLowerCase();
    const values = [];
    const push = (value) => {
      if (typeof value === 'string') {
        const trimmed = value.trim();
        if (trimmed) values.push(trimmed.toLowerCase());
      }
    };
    push(getVmIdentifier(vm));
    if (vm && typeof vm.__vcenterName === 'string') push(vm.__vcenterName);
    if (vm && Object.prototype.hasOwnProperty.call(vm, 'vm_id')) {
      push(typeof vm.vm_id === 'string' ? vm.vm_id : String(vm.vm_id || ''));
    }
    push(vm.name);
    push(vm.power_state);
    push(vm.guest_os);
    push(vm.tools_status);
    push(vm.host);
    push(vm.cluster);
    push(vm.datacenter);
    push(vm.resource_pool);
    push(vm.folder);
    push(vm.instance_uuid);
    push(vm.bios_uuid);
    if (Array.isArray(vm.ip_addresses)) vm.ip_addresses.forEach(push);
    if (Array.isArray(vm.mac_addresses)) vm.mac_addresses.forEach(push);
    if (Array.isArray(vm.tags)) vm.tags.forEach(push);
    if (Array.isArray(vm.network_names)) vm.network_names.forEach(push);
    push(vm.guest_family);
    push(vm.guest_name);
    push(vm.guest_full_name);
    push(vm.guest_host_name);
    push(vm.guest_ip_address);
    push(vm.tools_run_state);
    push(vm.tools_version);
    push(vm.tools_version_status);
    push(vm.tools_install_type);
    push(vm.vcenter_url);
    const attrs = vm?.custom_attributes;
    if (attrs && typeof attrs === 'object') {
      Object.entries(attrs).forEach(([key, value]) => {
        if (key) push(key);
        if (value != null) push(String(value));
      });
    }
    return values.some((value) => value.includes(lower));
  }

  function describeVCenterSelection() {
    const active = getActiveVCenter();
    if (!active) {
      return 'No vCenter instances configured yet.';
    }

    const name = active.name || 'vCenter';
    const total = Array.isArray(vcenterState.vms) ? vcenterState.vms.length : 0;
    const filtered = Array.isArray(vcenterState.filtered) ? vcenterState.filtered.length : 0;
    const meta = vcenterState.meta || {};
    const metaCountRaw = Number(meta.vm_count);
    const vmBase = Number.isFinite(metaCountRaw) && metaCountRaw >= 0 ? metaCountRaw : total;
    const generatedIso = typeof meta.generated_at === 'string' && meta.generated_at ? meta.generated_at : null;
    const sourceLabel = (() => {
      if (meta.source === 'live') return 'live data';
      if (meta.source === 'mixed') return 'mixed data';
      if (meta.source === 'aggregate') return 'aggregated data';
      return 'cached data';
    })();
    const timeLabel = (() => {
      if (!generatedIso) return 'never';
      try {
        return amsDateTimeString(new Date(generatedIso));
      } catch {
        return generatedIso;
      }
    })();

    const failureSuffix = Array.isArray(meta.failures) && meta.failures.length
      ? ` • Partial failures: ${meta.failures.join(', ')}`
      : '';

    if (total === 0) {
      return `No virtual machines available for ${name}. Last update: ${timeLabel}${failureSuffix}.`;
    }

    if (filtered === total) {
      const suffix = total === 1 ? '' : 's';
      return `Showing ${total.toLocaleString()} VM${suffix} from ${name} • ${sourceLabel} updated ${timeLabel}${failureSuffix}.`;
    }
    const suffix = filtered === 1 ? '' : 's';
    return `Showing ${filtered.toLocaleString()} of ${total.toLocaleString()} VM${suffix} from ${name} (cached total ${vmBase.toLocaleString()}) • ${sourceLabel} updated ${timeLabel}${failureSuffix}.`;
  }

  function applyVCenterFilter() {
    const search = (vcenterState.search || '').trim().toLowerCase();
    const tokens = search ? search.split(/\s+/).filter(Boolean) : [];
    if (!tokens.length) {
      vcenterState.filtered = Array.isArray(vcenterState.vms) ? vcenterState.vms.slice() : [];
      return;
    }
    vcenterState.filtered = vcenterState.vms.filter((vm) => tokens.every((token) => vcenterVmMatches(vm, token)));
  }

  function renderVCenterTableHeader() {
    if (!$vcenterTableHead) return;
    const columns = getVCenterColumns();
    const row = document.createElement('tr');
    columns.forEach((col) => {
      const th = document.createElement('th');
      th.scope = 'col';
      th.textContent = col.label;
      if (col.className) th.classList.add(col.className);
      row.appendChild(th);
    });
    $vcenterTableHead.innerHTML = '';
    $vcenterTableHead.appendChild(row);
  }

  function renderVCenterTable() {
    if (!$vcenterTableBody) return;
    const columns = getVCenterColumns();
    renderVCenterTableHeader();
    $vcenterTableBody.innerHTML = '';
    if (!vcenterState.filtered.length) {
      const tr = document.createElement('tr');
      tr.className = 'empty';
      const td = document.createElement('td');
      td.colSpan = columns.length;
      td.textContent = vcenterState.vms.length
        ? 'No virtual machines match the current filter.'
        : 'No virtual machines available for this vCenter.';
      tr.appendChild(td);
      $vcenterTableBody.appendChild(tr);
      return;
    }
    const frag = document.createDocumentFragment();
    vcenterState.filtered.forEach((vm, idx) => {
      const tr = document.createElement('tr');
      columns.forEach((col) => {
        const td = document.createElement('td');
        if (col.className) td.classList.add(col.className);
        let value;
        try {
          if (typeof col.render === 'function') {
            value = col.render(vm, idx);
          } else if (typeof col.formatter === 'function') {
            value = col.formatter(vm, idx);
          } else if (col.key && vm && Object.prototype.hasOwnProperty.call(vm, col.key)) {
            value = vm[col.key];
          } else {
            value = '';
          }
        } catch {
          value = '';
        }
        if (value instanceof Node) {
          td.appendChild(value);
        } else if (value && typeof value === 'object' && !Array.isArray(value)) {
          if (value.className) {
            const raw = Array.isArray(value.className) ? value.className : [value.className];
            const classTokens = [];
            raw.forEach((entry) => {
              String(entry)
                .split(/\s+/)
                .map((token) => token.trim())
                .filter(Boolean)
                .forEach((token) => classTokens.push(token));
            });
            if (classTokens.length) td.classList.add(...classTokens);
          }
          if (value.title) td.title = value.title;
          if (value.node instanceof Node) {
            td.appendChild(value.node);
          } else if (value.html != null) {
            td.innerHTML = String(value.html);
          } else if (value.text != null) {
            td.textContent = String(value.text);
          } else if (value.value != null) {
            td.textContent = String(value.value);
          } else {
            td.textContent = '';
          }
        } else {
          let rendered = value;
          if (Array.isArray(rendered)) {
            rendered = rendered.join(', ');
          }
          if (rendered === null || rendered === undefined) {
            rendered = '';
          }
          td.textContent = typeof rendered === 'string' ? rendered : String(rendered);
        }
        tr.appendChild(td);
      });
      frag.appendChild(tr);
    });
    $vcenterTableBody.appendChild(frag);
  }

  function updateVCenterView() {
    renderVCenterTabs();
    const hasInstances = vcenterState.instances.length > 0;
    if ($vcenterEmpty) $vcenterEmpty.hidden = hasInstances;
    if (!hasInstances) {
      if ($vcenterLoading) $vcenterLoading.hidden = true;
      if ($vcenterError) {
        $vcenterError.hidden = true;
        $vcenterError.textContent = '';
      }
      if ($vcenterTableWrapper) $vcenterTableWrapper.hidden = true;
      return;
    }
    if ($vcenterLoading) $vcenterLoading.hidden = !vcenterState.loading;
    if ($vcenterError) {
      if (vcenterState.error) {
        $vcenterError.hidden = false;
        $vcenterError.textContent = vcenterState.error;
      } else {
        $vcenterError.hidden = true;
        $vcenterError.textContent = '';
      }
    }
    const showTable = !vcenterState.loading && !vcenterState.error;
    if ($vcenterTableWrapper) $vcenterTableWrapper.hidden = !showTable;
    if (showTable) {
      renderVCenterTable();
    }
    const override = vcenterState.statusOverride;
    if (override) {
      const { tone = 'info', message = null } = override;
      vcenterState.statusOverride = null;
      setVCenterStatus(message, tone);
    } else {
      setVCenterStatus();
    }
  }

  async function loadVCenterInventory(instanceId, options = {}) {
    if (!instanceId) return;
    const { force = false, refresh = false } = options;
    const wantLive = force || refresh;
    const isAggregate = instanceId === ALL_VCENTER_ID;
    if (vcenterState.activeId === instanceId && vcenterState.loading && !wantLive) return;
    const previousState = {
      vms: Array.isArray(vcenterState.vms) ? vcenterState.vms.slice() : null,
      filtered: Array.isArray(vcenterState.filtered) ? vcenterState.filtered.slice() : null,
      meta: vcenterState.meta ? { ...vcenterState.meta } : null,
      error: vcenterState.error,
    };
    vcenterState.activeId = instanceId;
    vcenterState.loading = true;
    vcenterState.error = null;
    vcenterState.statusOverride = null;
    if ($vcenterSearch && typeof $vcenterSearch.value === 'string') {
      vcenterState.search = $vcenterSearch.value.trim();
    }
    updateVCenterView();
    setVCenterStatus(isAggregate ? 'Loading combined vCenter inventory…' : 'Loading vCenter inventory…');
    try {
      if (isAggregate) {
        const realInstances = vcenterState.instances.filter((inst) => inst && inst.id && inst.id !== ALL_VCENTER_ID);
        if (!realInstances.length) {
          vcenterState.meta = { aggregated: true, vm_count: 0, generated_at: null, source: 'aggregate' };
          vcenterState.vms = [];
          vcenterState.filtered = [];
          applyVCenterFilter();
          vcenterState.error = null;
          vcenterState.statusOverride = { tone: 'error' };
          setVCenterStatus('No vCenter instances available to aggregate.', 'error');
          return;
        }

        const aggregatedVms = [];
        const aggregatedMeta = {
          aggregated: true,
          source: wantLive ? 'live' : 'aggregate',
          vm_count: 0,
          generated_at: null,
          sources: [],
        };
        let latestDate = null;
        let sawLive = false;
        let sawCached = false;
        const errors = [];

        for (const inst of realInstances) {
          try {
            const base = `${API_BASE}/vcenter/${encodeURIComponent(inst.id)}`;
            const endpoint = `${base}/vms${wantLive ? '?refresh=true' : ''}`;
            const res = await fetch(endpoint, { method: 'GET' });
            const payload = await res.json().catch(() => ({}));
            if (!res.ok) {
              throw new Error(payload?.detail || `${res.status} ${res.statusText}`);
            }

            const vms = Array.isArray(payload?.vms) ? payload.vms : [];
            const configInfo = payload && typeof payload.config === 'object' ? payload.config : null;
            const metaPayload = payload && typeof payload.meta === 'object' ? { ...payload.meta } : {};

            if (!metaPayload.generated_at && configInfo?.last_refresh) {
              metaPayload.generated_at = configInfo.last_refresh;
            }
            if (metaPayload.vm_count == null && configInfo?.vm_count != null) {
              metaPayload.vm_count = configInfo.vm_count;
            }
            if (!metaPayload.source) {
              metaPayload.source = wantLive ? 'live' : 'cache';
            }

            const normalized = vms.map((vm) => ({
              ...normalizeVCenterVm(vm),
              __vcenterId: inst.id,
              __vcenterName: inst.name || inst.base_url || inst.id,
            }));
            aggregatedVms.push(...normalized);

            if (typeof metaPayload.vm_count === 'number' && Number.isFinite(metaPayload.vm_count)) {
              aggregatedMeta.vm_count += metaPayload.vm_count;
            } else {
              aggregatedMeta.vm_count += normalized.length;
            }

            if (metaPayload.generated_at) {
              const dt = new Date(metaPayload.generated_at);
              if (!Number.isNaN(dt.valueOf())) {
                if (!latestDate || dt > latestDate) {
                  latestDate = dt;
                }
              }
            }

            if (metaPayload.source === 'live') {
              sawLive = true;
            } else {
              sawCached = true;
            }

            aggregatedMeta.sources.push({
              id: inst.id,
              name: inst.name || inst.base_url || inst.id,
              vm_count: metaPayload.vm_count != null ? metaPayload.vm_count : normalized.length,
              generated_at: metaPayload.generated_at || null,
              source: metaPayload.source,
            });

            if (configInfo) {
              const idx = vcenterState.instances.findIndex((entry) => entry.id === inst.id);
              if (idx !== -1) {
                const merged = {
                  ...vcenterState.instances[idx],
                  ...configInfo,
                  last_refresh:
                    metaPayload.generated_at
                    || configInfo.last_refresh
                    || vcenterState.instances[idx].last_refresh
                    || null,
                  vm_count:
                    metaPayload.vm_count != null
                      ? metaPayload.vm_count
                      : configInfo.vm_count ?? vcenterState.instances[idx].vm_count ?? null,
                };
                vcenterState.instances[idx] = merged;
              }
            }
          } catch (error) {
            errors.push({ instance: inst, error });
            console.error('Failed to load vCenter inventory for', inst?.id || '(unknown)', error);
          }
        }

        aggregatedMeta.generated_at = latestDate ? latestDate.toISOString() : null;
        aggregatedMeta.source = (() => {
          if (sawLive && sawCached) return 'mixed';
          if (sawLive) return 'live';
          return wantLive ? 'live' : 'aggregate';
        })();
        if (!aggregatedMeta.vm_count && aggregatedVms.length) {
          aggregatedMeta.vm_count = aggregatedVms.length;
        }
        aggregatedMeta.failures = errors.map(({ instance }) => instance?.name || instance?.id).filter(Boolean);

        const aggregateIndex = vcenterState.instances.findIndex((entry) => entry.id === ALL_VCENTER_ID);
        if (aggregateIndex !== -1) {
          vcenterState.instances[aggregateIndex] = {
            ...vcenterState.instances[aggregateIndex],
            vm_count: aggregatedMeta.vm_count,
            last_refresh: aggregatedMeta.generated_at,
            aggregate: true,
          };
        }

        renderVCenterTabs();

        vcenterState.meta = aggregatedMeta;
        vcenterState.vms = aggregatedVms;
        if ($vcenterSearch && typeof $vcenterSearch.value === 'string') {
          vcenterState.search = $vcenterSearch.value.trim();
        }
        applyVCenterFilter();
        vcenterState.lastFetchAt = Date.now();
        vcenterState.error = null;
        if ($vcenterSearch && $vcenterSearch.value.trim() !== vcenterState.search) {
          $vcenterSearch.value = vcenterState.search;
        }

        if (!aggregatedVms.length && errors.length === realInstances.length) {
          const errorNames = errors.map(({ instance }) => instance.name || instance.id).filter(Boolean).join(', ');
          throw new Error(errorNames ? `Failed to load inventory for: ${errorNames}` : 'Failed to load combined vCenter inventory');
        }
        const tone = errors.length ? 'error' : aggregatedMeta.source === 'live' ? 'success' : 'info';
        vcenterState.statusOverride = { tone };
        return;
      }

      const base = `${API_BASE}/vcenter/${encodeURIComponent(instanceId)}`;
      const endpoint = `${base}/vms${wantLive ? '?refresh=true' : ''}`;
      const res = await fetch(endpoint, { method: 'GET' });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(payload?.detail || `${res.status} ${res.statusText}`);
      }

      const vms = Array.isArray(payload?.vms) ? payload.vms : [];
      const configInfo = payload && typeof payload.config === 'object' ? payload.config : null;
      const owner = vcenterState.instances.find((inst) => inst.id === instanceId) || null;
      const normalizedVms = vms.map((vm) => {
        const normalized = normalizeVCenterVm(vm);
        if (owner) {
          return {
            ...normalized,
            __vcenterId: owner.id,
            __vcenterName: owner.name || owner.base_url || owner.id,
          };
        }
        return normalized;
      });
      const metaPayload = payload && typeof payload.meta === 'object' ? { ...payload.meta } : {};

      if (configInfo) {
        const idx = vcenterState.instances.findIndex((inst) => inst.id === instanceId);
        if (idx !== -1) {
          const merged = {
            ...vcenterState.instances[idx],
            ...configInfo,
            last_refresh: metaPayload.generated_at || configInfo.last_refresh || vcenterState.instances[idx].last_refresh || null,
            vm_count:
              metaPayload.vm_count != null
                ? metaPayload.vm_count
                : configInfo.vm_count ?? vcenterState.instances[idx].vm_count ?? null,
          };
          vcenterState.instances[idx] = merged;
        }
      }

      recalcAggregateInstanceMeta();
      renderVCenterTabs();

      if (!metaPayload.generated_at && configInfo?.last_refresh) {
        metaPayload.generated_at = configInfo.last_refresh;
      }
      if (metaPayload.vm_count == null && configInfo?.vm_count != null) {
        metaPayload.vm_count = configInfo.vm_count;
      }
      if (!metaPayload.source) {
        metaPayload.source = wantLive ? 'live' : 'cache';
      }

      vcenterState.meta = metaPayload;
      vcenterState.vms = normalizedVms;
      if ($vcenterSearch && typeof $vcenterSearch.value === 'string') {
        vcenterState.search = $vcenterSearch.value.trim();
      }
      applyVCenterFilter();
      vcenterState.lastFetchAt = Date.now();
      vcenterState.error = null;
      if ($vcenterSearch && $vcenterSearch.value.trim() !== vcenterState.search) {
        $vcenterSearch.value = vcenterState.search;
      }
      vcenterState.statusOverride = { tone: metaPayload.source === 'live' ? 'success' : 'info' };
    } catch (err) {
      console.error('Failed to load vCenter inventory', instanceId, err);
      vcenterState.error = err?.message || 'Failed to load vCenter inventory';
      if (previousState.vms) {
        vcenterState.vms = previousState.vms;
        vcenterState.filtered = previousState.filtered || previousState.vms.slice();
        vcenterState.meta = previousState.meta;
        setVCenterStatus(`${vcenterState.error} • showing cached data`, 'error');
      } else {
        vcenterState.vms = [];
        vcenterState.filtered = [];
        vcenterState.meta = null;
        setVCenterStatus(vcenterState.error, 'error');
      }
    } finally {
      vcenterState.loading = false;
      updateVCenterView();
    }
  }

  async function loadVCenterInstances(force = false) {
    if (!canAccessPage('vcenter')) return [];
    try {
      setVCenterStatus('Loading vCenter instances…');
      const res = await fetch(`${API_BASE}/vcenter/instances`);
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(payload?.detail || `${res.status} ${res.statusText}`);
      }
      const items = Array.isArray(payload)
        ? payload
            .filter((item) => item && item.id)
            .map((item) => {
              const name = (item.name || item.base_url || 'vCenter').trim() || 'vCenter';
              const numericVmCount = Number(item.vm_count);
              return {
                id: item.id,
                name,
                base_url: item.base_url || '',
                verify_ssl: item.verify_ssl !== false,
                has_credentials: !!item.has_credentials,
                last_refresh: item.last_refresh || null,
                vm_count: Number.isFinite(numericVmCount) && numericVmCount >= 0 ? numericVmCount : null,
              };
            })
        : [];
      items.sort((a, b) => a.name.localeCompare(b.name));
      const aggregateEntry = items.length
        ? {
            id: ALL_VCENTER_ID,
            name: 'All',
            base_url: '',
            verify_ssl: true,
            has_credentials: items.every((inst) => inst.has_credentials),
            last_refresh: null,
            vm_count: null,
            aggregate: true,
          }
        : null;
      const combined = aggregateEntry ? [aggregateEntry, ...items] : items;
      vcenterState.instances = combined;
      if (!combined.length) {
        vcenterState.activeId = null;
        vcenterState.vms = [];
        vcenterState.filtered = [];
        vcenterState.error = null;
        renderVCenterTabs();
        updateVCenterView();
        setVCenterStatus('No vCenter instances configured.', 'error');
        return items;
      }
      recalcAggregateInstanceMeta();
      const priorId = vcenterState.activeId;
      const preserveSelection = priorId && combined.some((inst) => inst.id === priorId) && !force;
      const targetId = preserveSelection ? priorId : combined[0].id;
      vcenterState.activeId = targetId;
      vcenterState.meta = null;
      renderVCenterTabs();
      await loadVCenterInventory(targetId);
      return items;
    } catch (err) {
      console.error('Failed to load vCenter instances', err);
      vcenterState.instances = [];
      vcenterState.activeId = null;
      vcenterState.vms = [];
      vcenterState.filtered = [];
      vcenterState.meta = null;
      vcenterState.error = err?.message || 'Failed to load vCenter instances';
      renderVCenterTabs();
      updateVCenterView();
      setVCenterStatus(vcenterState.error, 'error');
      return [];
    }
  }

  if ($vcenterTabs) {
    $vcenterTabs.addEventListener('click', (event) => {
      const btn = event.target.closest('button[data-vcenter-id]');
      if (!btn) return;
      const identifier = btn.dataset.vcenterId;
      if (!identifier) return;
      if (vcenterState.loading && identifier === vcenterState.activeId) return;
      loadVCenterInventory(identifier).catch(() => {});
    });
  }

  if ($vcenterRefresh) {
    $vcenterRefresh.addEventListener('click', () => {
      if (vcenterState.activeId) {
        loadVCenterInventory(vcenterState.activeId, { refresh: true }).catch(() => {});
      } else {
        loadVCenterInstances(true).catch(() => {});
      }
    });
  }

  if ($vcenterSearch) {
    const applySearch = debounce(() => {
      vcenterState.search = ($vcenterSearch.value || '').trim();
      applyVCenterFilter();
      if (!vcenterState.loading && !vcenterState.error) {
        setVCenterStatus(describeVCenterSelection());
      }
      updateVCenterView();
    }, 180);
    $vcenterSearch.addEventListener('input', applySearch);
  }

  // ---------------------------
  // Suggestions
  // ---------------------------
  function updateSuggestionMeta(meta) {
    if (!meta) return;
    if (Array.isArray(meta.classifications)) suggestionState.meta.classifications = meta.classifications.slice();
    if (Array.isArray(meta.statuses)) suggestionState.meta.statuses = meta.statuses.slice();
  }

  const suggestionDefaultClassification = () => {
    const cls = suggestionState.meta.classifications || [];
    const preferred = cls.find((c) => (c?.name || '').toLowerCase() === 'could have');
    return preferred?.name || cls[0]?.name || 'Could have';
  };

  const suggestionDefaultStatus = () => {
    const sts = suggestionState.meta.statuses || [];
    const preferred = sts.find((s) => (s?.value || '').toLowerCase() === 'new');
    return preferred?.value || sts[0]?.value || 'new';
  };

  const parseSuggestionDate = (value) => {
    if (!value) return null;
    const withZone = value.endsWith('Z') ? value : `${value}Z`;
    const d = new Date(withZone);
    if (Number.isNaN(d.getTime())) return null;
    return d;
  };

  const formatSuggestionDate = (value) => {
    const d = parseSuggestionDate(value);
    if (!d) return value || '';
    try { return `${amsDateTimeString(d)} ${amsTzShort(d)}`.trim(); }
    catch { return d.toISOString(); }
  };

  function populateSuggestionSelects(selectedClass, selectedStatus) {
    if ($suggestionClassification) {
      $suggestionClassification.innerHTML = '';
      const classes = suggestionState.meta.classifications || [];
      classes.forEach((c) => {
        if (!c || !c.name) return;
        const opt = document.createElement('option');
        opt.value = c.name;
        opt.textContent = c.name;
        if (selectedClass && selectedClass.toLowerCase() === c.name.toLowerCase()) opt.selected = true;
        $suggestionClassification.appendChild(opt);
      });
      if (!$suggestionClassification.value) {
        $suggestionClassification.value = suggestionDefaultClassification();
      }
    }
    if ($suggestionStatus) {
      $suggestionStatus.innerHTML = '';
      const statuses = suggestionState.meta.statuses || [];
      statuses.forEach((s) => {
        if (!s || !s.value) return;
        const opt = document.createElement('option');
        opt.value = s.value;
        opt.textContent = s.label || s.value;
        if (selectedStatus && selectedStatus.toLowerCase() === s.value.toLowerCase()) opt.selected = true;
        $suggestionStatus.appendChild(opt);
      });
      if (!$suggestionStatus.value) {
        $suggestionStatus.value = suggestionDefaultStatus();
      }
    }
  }

  function updateSuggestionStateItem(item) {
    if (!item || !item.id) return;
    const idx = suggestionState.items.findIndex((it) => it && it.id === item.id);
    if (idx === -1) {
      suggestionState.items.push(item);
    } else {
      suggestionState.items[idx] = item;
    }
  }

  function removeSuggestionFromState(id) {
    if (!id) return;
    suggestionState.items = suggestionState.items.filter((it) => it && it.id !== id);
  }

  function setSuggestionCommentsEnabled(enabled) {
    if ($suggestionCommentsWrapper) {
      $suggestionCommentsWrapper.classList.toggle('disabled', !enabled);
    }
    if ($suggestionCommentText) $suggestionCommentText.disabled = !enabled;
    if ($suggestionCommentAdd) $suggestionCommentAdd.disabled = !enabled;
  }

  function renderSuggestionDetailMeta(item, isNew) {
    if (!$suggestionDetailMeta) return;
    if (isNew) {
      $suggestionDetailMeta.textContent = 'Create a new suggestion';
      return;
    }
    if (!item) {
      $suggestionDetailMeta.textContent = '';
      return;
    }
    const parts = [];
    if (item.classification) parts.push(item.classification);
    const created = formatSuggestionDate(item.created_at);
    if (created) parts.push(`Created ${created}`);
    if (item.status_label || item.status) parts.push(`Status: ${item.status_label || item.status}`);
    if (typeof item.likes === 'number') parts.push(`Likes: ${item.likes}`);
    $suggestionDetailMeta.textContent = parts.join(' · ');
  }

  function renderSuggestionComments(item, isNew) {
    if (!$suggestionComments) return;
    $suggestionComments.innerHTML = '';
    const comments = Array.isArray(item?.comments) ? item.comments : [];
    if (isNew) {
      $suggestionComments.classList.add('empty');
      const msg = document.createElement('div');
      msg.className = 'suggestion-comment-empty';
      msg.textContent = 'Save the suggestion to start a discussion.';
      $suggestionComments.appendChild(msg);
      return;
    }
    if (!comments.length) {
      $suggestionComments.classList.add('empty');
      const msg = document.createElement('div');
      msg.className = 'suggestion-comment-empty';
      msg.textContent = 'No comments yet.';
      $suggestionComments.appendChild(msg);
      return;
    }
    $suggestionComments.classList.remove('empty');
    const frag = document.createDocumentFragment();
    comments.forEach((comment) => {
      if (!comment) return;
      const wrap = document.createElement('div');
      wrap.className = 'suggestion-comment-item';
      const body = document.createElement('div');
      body.className = 'suggestion-comment-text';
      body.textContent = comment.text || '';
      const meta = document.createElement('div');
      meta.className = 'suggestion-comment-meta';
      meta.textContent = formatSuggestionDate(comment.created_at);
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'suggestion-comment-remove';
      remove.title = 'Delete comment';
      remove.textContent = '×';
      remove.addEventListener('click', async (e) => {
        e.preventDefault();
        remove.disabled = true;
        try {
          await deleteSuggestionComment(comment.id);
        } finally {
          remove.disabled = false;
        }
      });
      wrap.appendChild(body);
      wrap.appendChild(meta);
      wrap.appendChild(remove);
      frag.appendChild(wrap);
    });
    $suggestionComments.appendChild(frag);
  }

  function renderSuggestionForm(item, isNew) {
    suggestionState.current = item;
    populateSuggestionSelects(item?.classification, item?.status);
    if ($suggestionTitle) $suggestionTitle.value = item?.title || '';
    if ($suggestionSummary) $suggestionSummary.value = item?.summary || '';
    if ($suggestionClassification && item?.classification) $suggestionClassification.value = item.classification;
    if ($suggestionStatus && item?.status) $suggestionStatus.value = item.status;
    setSuggestionCommentsEnabled(!isNew && !!item?.id);
    renderSuggestionDetailMeta(item, isNew);
    renderSuggestionComments(item, isNew || !item?.id);
    if ($suggestionCommentText && !isNew) $suggestionCommentText.value = '';
    if ($suggestionDelete) {
      const canDelete = !isNew && !!(item && item.id);
      $suggestionDelete.hidden = !canDelete;
      $suggestionDelete.disabled = !canDelete;
    }
  }

  function renderSuggestionsList() {
    if (!$suggestionList) return;
    $suggestionList.innerHTML = '';
    const items = Array.isArray(suggestionState.items) ? suggestionState.items : [];
    if (!items.length) {
      $suggestionList.classList.add('empty');
      const placeholder = document.createElement('div');
      placeholder.className = 'suggestion-empty';
      placeholder.textContent = 'No suggestions yet.';
      $suggestionList.appendChild(placeholder);
      return;
    }
    $suggestionList.classList.remove('empty');
    const frag = document.createDocumentFragment();
    items.forEach((item) => {
      if (!item || !item.id) return;
      const card = document.createElement('article');
      card.className = 'suggestion-card';
      card.setAttribute('role', 'button');
      card.tabIndex = 0;
      card.dataset.id = item.id;
      const badge = document.createElement('div');
      badge.className = 'suggestion-badge';
      badge.textContent = item.classification_letter || (item.classification || '?').charAt(0).toUpperCase();
      if (item.classification_color) badge.style.background = item.classification_color;
      const info = document.createElement('div');
      info.className = 'suggestion-info';
      const title = document.createElement('h3');
      title.className = 'suggestion-title';
      title.textContent = item.title || '(Untitled suggestion)';
      const meta = document.createElement('div');
      meta.className = 'suggestion-meta';
      const when = formatSuggestionDate(item.created_at);
      if (when) {
        const span = document.createElement('span');
        span.textContent = `Placed ${when}`;
        meta.appendChild(span);
      }
      if (item.status_label || item.status) {
        const span = document.createElement('span');
        span.textContent = item.status_label || item.status;
        meta.appendChild(span);
      }
      info.appendChild(title);
      info.appendChild(meta);
      if (item.summary) {
        const summary = document.createElement('p');
        summary.className = 'suggestion-summary';
        summary.textContent = item.summary;
        info.appendChild(summary);
      }
      const likeBtn = document.createElement('button');
      likeBtn.type = 'button';
      likeBtn.className = 'suggestion-like';
      likeBtn.innerHTML = `<span aria-hidden="true">👍</span><span class="suggestion-like-count">${item.likes ?? 0}</span>`;
      likeBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        e.preventDefault();
        likeBtn.disabled = true;
        try {
          await likeSuggestion(item.id);
        } finally {
          likeBtn.disabled = false;
        }
      });
      card.addEventListener('click', () => {
        suggestionState.route = { mode: 'detail', id: item.id };
        window.location.hash = `#suggestions/${item.id}`;
      });
      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          suggestionState.route = { mode: 'detail', id: item.id };
          window.location.hash = `#suggestions/${item.id}`;
        }
      });
      card.appendChild(badge);
      card.appendChild(info);
      card.appendChild(likeBtn);
      frag.appendChild(card);
    });
    $suggestionList.appendChild(frag);
  }

  async function loadSuggestions(force = false, options = {}) {
    const { silent = false, skipRender = false } = options || {};
    if (suggestionState.loading && !force) return;
    suggestionState.loading = true;
    try {
      const res = await fetch(`${API_BASE}/suggestions`);
      if (!res.ok) {
        const problem = await res.json().catch(() => null);
        throw new Error(problem?.detail || res.statusText);
      }
      const data = await res.json();
      updateSuggestionMeta(data?.meta);
      if (Array.isArray(data?.items)) {
        suggestionState.items = data.items.slice();
        if (!skipRender) renderSuggestionsList();
      } else if (!skipRender) {
        renderSuggestionsList();
      }
    } catch (err) {
      console.error('Failed to load suggestions', err);
      if (!silent) alert(`Failed to load suggestions: ${err?.message || err}`);
    } finally {
      suggestionState.loading = false;
    }
  }

  async function ensureSuggestionMeta() {
    const hasMeta = (suggestionState.meta.classifications || []).length && (suggestionState.meta.statuses || []).length;
    if (!hasMeta) await loadSuggestions(true, { silent: true, skipRender: true });
  }

  async function prepareNewSuggestion() {
    suggestionState.route = { mode: 'new', id: null };
    await ensureSuggestionMeta();
    const item = {
      id: null,
      title: '',
      summary: '',
      classification: suggestionDefaultClassification(),
      status: suggestionDefaultStatus(),
      status_label: 'New',
      likes: 0,
      created_at: null,
      comments: [],
    };
    suggestionState.current = item;
    renderSuggestionForm(item, true);
  }

  async function loadSuggestionDetail(id) {
    if (!id) {
      alert('Suggestion not found.');
      window.location.hash = '#suggestions';
      return;
    }
    suggestionState.route = { mode: 'detail', id };
    await ensureSuggestionMeta();
    try {
      const res = await fetch(`${API_BASE}/suggestions/${encodeURIComponent(id)}`);
      if (!res.ok) {
        const problem = await res.json().catch(() => null);
        throw new Error(problem?.detail || res.statusText);
      }
      const data = await res.json();
      updateSuggestionMeta(data?.meta);
      if (data?.item) {
        suggestionState.current = data.item;
        updateSuggestionStateItem(data.item);
        renderSuggestionForm(data.item, false);
        renderSuggestionsList();
      } else {
        throw new Error('Missing suggestion data');
      }
    } catch (err) {
      console.error('Failed to load suggestion', err);
      alert(`Could not load suggestion: ${err?.message || err}`);
      window.location.hash = '#suggestions';
    }
  }

  async function saveSuggestion() {
    const isNew = suggestionState.route.mode === 'new' || !suggestionState.current?.id;
    const title = ($suggestionTitle?.value || '').trim();
    if (!title) {
      alert('Title is required.');
      $suggestionTitle?.focus();
      return;
    }
    await ensureSuggestionMeta();
    const payload = {
      title,
      summary: ($suggestionSummary?.value || '').trim(),
      classification: $suggestionClassification?.value || suggestionDefaultClassification(),
      status: $suggestionStatus?.value || suggestionDefaultStatus(),
    };
    try {
      let res;
      if (isNew) {
        res = await fetch(`${API_BASE}/suggestions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        res = await fetch(`${API_BASE}/suggestions/${encodeURIComponent(suggestionState.current.id)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }
      if (!res.ok) {
        const problem = await res.json().catch(() => null);
        throw new Error(problem?.detail || res.statusText);
      }
      const data = await res.json();
      if (data?.item) {
        updateSuggestionStateItem(data.item);
        renderSuggestionsList();
      }
      window.location.hash = '#suggestions';
      await loadSuggestions(true, { silent: true });
    } catch (err) {
      console.error('Failed to save suggestion', err);
      alert(`Save failed: ${err?.message || err}`);
    }
  }

  async function likeSuggestion(id) {
    if (!id) return;
    try {
      const res = await fetch(`${API_BASE}/suggestions/${encodeURIComponent(id)}/like`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ delta: 1 }),
      });
      if (!res.ok) {
        const problem = await res.json().catch(() => null);
        throw new Error(problem?.detail || res.statusText);
      }
      const data = await res.json();
      if (data?.item) {
        updateSuggestionStateItem(data.item);
        renderSuggestionsList();
        if (suggestionState.current?.id === data.item.id) {
          suggestionState.current = data.item;
          renderSuggestionForm(data.item, false);
        }
      }
    } catch (err) {
      console.error('Failed to like suggestion', err);
      alert(`Unable to like suggestion: ${err?.message || err}`);
    }
  }

  async function addSuggestionComment() {
    const current = suggestionState.current;
    if (!current?.id) return;
    const text = ($suggestionCommentText?.value || '').trim();
    if (!text) {
      alert('Enter a comment before posting.');
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/suggestions/${encodeURIComponent(current.id)}/comments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) {
        const problem = await res.json().catch(() => null);
        throw new Error(problem?.detail || res.statusText);
      }
      const data = await res.json();
      if (data?.item) {
        suggestionState.current = data.item;
        updateSuggestionStateItem(data.item);
        renderSuggestionForm(data.item, false);
        renderSuggestionsList();
      }
      if ($suggestionCommentText) $suggestionCommentText.value = '';
    } catch (err) {
      console.error('Failed to add comment', err);
      alert(`Unable to add comment: ${err?.message || err}`);
    }
  }

  async function deleteSuggestionComment(commentId) {
    const current = suggestionState.current;
    if (!current?.id || !commentId) return;
    try {
      const res = await fetch(`${API_BASE}/suggestions/${encodeURIComponent(current.id)}/comments/${encodeURIComponent(commentId)}`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        const problem = await res.json().catch(() => null);
        throw new Error(problem?.detail || res.statusText);
      }
      const data = await res.json();
      if (data?.item) {
        suggestionState.current = data.item;
        updateSuggestionStateItem(data.item);
        renderSuggestionForm(data.item, false);
        renderSuggestionsList();
      }
    } catch (err) {
      console.error('Failed to delete comment', err);
      alert(`Unable to delete comment: ${err?.message || err}`);
    }
  }

  async function deleteSuggestion() {
    const current = suggestionState.current;
    if (!current?.id) return;
    const label = current.title ? `"${current.title}"` : 'this suggestion';
    const confirmed = window.confirm(`Are you sure you want to delete ${label}? This cannot be undone.`);
    if (!confirmed) return;
    if ($suggestionDelete) $suggestionDelete.disabled = true;
    try {
      const res = await fetch(`${API_BASE}/suggestions/${encodeURIComponent(current.id)}`, { method: 'DELETE' });
      if (!res.ok) {
        const problem = await res.json().catch(() => null);
        throw new Error(problem?.detail || res.statusText);
      }
      removeSuggestionFromState(current.id);
      renderSuggestionsList();
      suggestionState.current = null;
      suggestionState.route = { mode: 'list', id: null };
      window.location.hash = '#suggestions';
    } catch (err) {
      console.error('Failed to delete suggestion', err);
      alert(`Unable to delete suggestion: ${err?.message || err}`);
    }
    if ($suggestionDelete) $suggestionDelete.disabled = false;
  }

  if ($suggestionsButton) {
    $suggestionsButton.addEventListener('click', (e) => {
      e.preventDefault();
      suggestionState.route = { mode: 'list', id: null };
      window.location.hash = '#suggestions';
    });
  }
  $suggestionNew?.addEventListener('click', (e) => {
    e.preventDefault();
    suggestionState.route = { mode: 'new', id: null };
    window.location.hash = '#suggestions/new';
  });
  $suggestionBack?.addEventListener('click', (e) => {
    e.preventDefault();
    window.location.hash = '#suggestions';
  });
  $suggestionSave?.addEventListener('click', (e) => {
    e.preventDefault();
    saveSuggestion();
  });
  $suggestionCommentAdd?.addEventListener('click', (e) => {
    e.preventDefault();
    addSuggestionComment();
  });
  $suggestionDelete?.addEventListener('click', (e) => {
    e.preventDefault();
    deleteSuggestion();
  });
  $adminBackupRun?.addEventListener('click', (e) => {
    e.preventDefault();
    runManualBackup($adminBackupRun);
  });

  $adminBackupType?.addEventListener('change', () => {
    updateBackupConfigVisibility();
  });

  adminTabs.forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const tab = btn.dataset.adminTab;
      setAdminTab(tab);
    });
  });

  setAdminTab(adminState.activeTab);

  // ---------------------------
  // Admin settings
  // ---------------------------
  function createAdminSettingCard(item) {
    const card = document.createElement('div');
    card.className = 'admin-setting';

    const header = document.createElement('div');
    header.className = 'admin-setting-header';
    const title = document.createElement('h3');
    title.className = 'admin-setting-title';
    title.textContent = item.label || item.key;
    const keyLabel = document.createElement('span');
    keyLabel.className = 'admin-setting-key';
    keyLabel.textContent = item.key;
    header.appendChild(title);
    header.appendChild(keyLabel);

    const body = document.createElement('div');
    body.className = 'admin-setting-body';
    const input = document.createElement('input');
    input.type = item.secret ? 'password' : 'text';
    input.value = item.value || '';
    if (item.placeholder_effective) input.placeholder = item.placeholder_effective;
    input.dataset.key = item.key;
    input.dataset.secret = item.secret ? '1' : '0';
    input.dataset.hasValue = item.has_value ? '1' : '0';
    if (item.secret && item.has_value) {
      input.addEventListener('focus', () => {
        if (!input.value) input.placeholder = '';
      });
      input.addEventListener('blur', () => {
        if (!input.value && item.placeholder_effective) input.placeholder = item.placeholder_effective;
      });
    }
    body.appendChild(input);

    const actions = document.createElement('div');
    actions.className = 'admin-setting-actions';
    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'btn';
    saveBtn.textContent = 'Save';
    saveBtn.addEventListener('click', async () => {
      await saveAdminSetting(item, input, saveBtn);
    });
    const resetBtn = document.createElement('button');
    resetBtn.type = 'button';
    resetBtn.className = 'btn ghost';
    resetBtn.textContent = 'Reset';
    resetBtn.addEventListener('click', async () => {
      if (!window.confirm(`Reset ${item.label || item.key} to default?`)) return;
      await resetAdminSetting(item, resetBtn);
    });
    actions.appendChild(saveBtn);
    actions.appendChild(resetBtn);
    body.appendChild(actions);

    card.appendChild(header);
    card.appendChild(body);
    return card;
  }

  function renderAdminGroup(container, items, options = {}) {
    if (!container) return;
    const list = Array.isArray(items) ? items : [];
    if (!list.length) {
      container.replaceChildren();
      if (options.emptyMessage) {
        const empty = document.createElement('p');
        empty.className = 'muted';
        empty.textContent = options.emptyMessage;
        container.appendChild(empty);
      }
      return;
    }
    const frag = document.createDocumentFragment();
    list.forEach((item) => {
      frag.appendChild(createAdminSettingCard(item));
    });
    container.replaceChildren(frag);
  }

  function renderAdminSettings() {
    if (!$adminSettings) return;
    const settings = Array.isArray(adminState.settings) ? adminState.settings : [];
    const groups = settings.reduce((acc, item) => {
      let cat = (item.category || 'api').toLowerCase();
      if (cat === 'net_atlassian') cat = 'net-atlassian';
      if (!acc[cat]) acc[cat] = [];
      acc[cat].push(item);
      return acc;
    }, {});

    renderAdminGroup(adminContainers['zabbix'], groups['zabbix'] || [], { emptyMessage: 'Configure Zabbix connection settings.' });
    renderAdminGroup(adminContainers['net-atlassian'], groups['net-atlassian'] || [], { emptyMessage: 'Configure NetBox and Atlassian access.' });
    renderAdminGroup(adminContainers['chat'], groups['chat'] || [], { emptyMessage: 'Add API keys and defaults to enable chat providers.' });
    renderAdminGroup(adminContainers['export'], groups['export'] || [], { emptyMessage: 'No export settings available.' });
    renderAdminGroup(adminContainers['api'], groups['api'] || [], { emptyMessage: 'No API/UI settings available.' });
    renderAdminGroup(adminContainers['backup'], groups['backup'] || [], { emptyMessage: 'Configure backup options.' });
  }

  async function loadAdminSettings(force = false) {
    if (!$adminSettings) return;
    if (adminState.loading && !force) return;
    adminState.loading = true;
    if ($adminStatus) $adminStatus.textContent = 'Loading settings…';
    try {
      const res = await fetch(`${API_BASE}/admin/env`);
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || res.statusText);
      }
      const data = await res.json();
      adminState.settings = Array.isArray(data?.settings) ? data.settings : [];
      adminState.backup = data?.backup || {};
      renderAdminSettings();
      if ($adminStatus) {
        const backup = adminState.backup || {};
        if (!backup.enabled) {
          $adminStatus.textContent = 'Backup disabled';
        } else if (backup.enabled && !backup.configured) {
          $adminStatus.textContent = 'Backup enabled but not configured';
        } else if (backup.type && backup.target) {
          $adminStatus.textContent = `Backup (${backup.type}) → ${backup.target}`;
        } else if (backup.type) {
          $adminStatus.textContent = `Backup enabled (${backup.type})`;
        } else {
          $adminStatus.textContent = 'Backup enabled';
        }
      }
      updateBackupConfigFromState();
    } catch (err) {
      console.error('Failed to load admin settings', err);
      if ($adminStatus) $adminStatus.textContent = 'Failed to load settings';
      alert(`Unable to load admin settings: ${err?.message || err}`);
    } finally {
      setAdminTab(adminState.activeTab || 'zabbix');
      adminState.loading = false;
      // Load users and global keys when admin settings are loaded
      if (adminState.activeTab === 'users') {
        loadAdminUsers($adminUserIncludeInactive?.checked).catch(() => {});
        loadAdminGlobalApiKeys().catch(() => {});
      }
    }
  }

  async function saveAdminSetting(item, input, button) {
    const payload = { key: item.key, value: input.value };
    if (item.secret && !input.value && item.has_value) {
      payload.value = null;
    }
    button.disabled = true;
    if ($adminStatus) $adminStatus.textContent = `Saving ${item.label || item.key}…`;
    try {
      const res = await fetch(`${API_BASE}/admin/env`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || res.statusText);
      }
      const data = await res.json();
      adminState.settings = Array.isArray(data?.settings) ? data.settings : [];
      adminState.backup = data?.backup || {};
      renderAdminSettings();
      setAdminTab(adminState.activeTab || 'zabbix');
      if ((item.category || '').toLowerCase() === 'chat') {
        loadChatConfig();
      }
      if ($adminStatus) $adminStatus.textContent = 'Saved';
    } catch (err) {
      console.error('Failed to save setting', err);
      if ($adminStatus) $adminStatus.textContent = 'Save failed';
      alert(`Unable to save setting: ${err?.message || err}`);
    } finally {
      button.disabled = false;
    }
  }

  async function resetAdminSetting(item, button) {
    button.disabled = true;
    if ($adminStatus) $adminStatus.textContent = `Resetting ${item.label || item.key}…`;
    try {
      const res = await fetch(`${API_BASE}/admin/env/reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: item.key }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || res.statusText);
      }
      const data = await res.json();
      adminState.settings = Array.isArray(data?.settings) ? data.settings : [];
      adminState.backup = data?.backup || {};
      renderAdminSettings();
      setAdminTab(adminState.activeTab || 'zabbix');
      if ((item.category || '').toLowerCase() === 'chat') {
        loadChatConfig();
      }
      if ($adminStatus) $adminStatus.textContent = 'Reset complete';
    } catch (err) {
      console.error('Failed to reset setting', err);
      if ($adminStatus) $adminStatus.textContent = 'Reset failed';
      alert(`Unable to reset setting: ${err?.message || err}`);
    } finally {
      button.disabled = false;
    }
  }

  async function runManualBackup(button) {
    if (!window.confirm('Run backup now?')) return;
    button.disabled = true;
    if ($adminStatus) $adminStatus.textContent = 'Running backup…';
    try {
      const res = await fetch(`${API_BASE}/admin/backup-sync`, { method: 'POST' });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || res.statusText);
      }
      const data = await res.json();
      if (data?.status === 'ok') {
        const method = data?.method || 'backup';
        const count = data?.count || data?.uploaded?.length || data?.copied?.length || 0;
        alert(`${method.toUpperCase()} backup finished with ${count} file(s).`);
      } else {
        alert(`Backup response: ${data?.reason || data?.status || 'unknown'}`);
      }
      if ($adminStatus) $adminStatus.textContent = 'Backup completed';
    } catch (err) {
      console.error('Backup failed', err);
      if ($adminStatus) $adminStatus.textContent = 'Backup failed';
      alert(`Backup failed: ${err?.message || err}`);
    } finally {
      button.disabled = false;
    }
  }

  function updateBackupConfigVisibility() {
    const type = $adminBackupType?.value || 'local';
    if ($adminBackupLocalConfig) {
      $adminBackupLocalConfig.hidden = type !== 'local';
    }
    if ($adminBackupRemoteConfig) {
      $adminBackupRemoteConfig.hidden = !['sftp', 'scp'].includes(type);
    }
  }

  function updateBackupConfigFromState() {
    const backup = adminState.backup || {};
    if ($adminBackupStatus) {
      if (backup.enabled && backup.configured) {
        $adminBackupStatus.textContent = `Backup configured: ${backup.type || 'unknown'} → ${backup.target || 'unknown'}`;
        $adminBackupStatus.className = 'admin-backup-status success';
      } else if (backup.enabled) {
        $adminBackupStatus.textContent = 'Backup enabled but not properly configured';
        $adminBackupStatus.className = 'admin-backup-status warning';
      } else {
        $adminBackupStatus.textContent = 'Backup disabled';
        $adminBackupStatus.className = 'admin-backup-status disabled';
      }
    }
  }

  function setAdminTab(tab) {
    const availableTabs = Array.from(adminTabs).map((btn) => btn.dataset.adminTab);
    if (!availableTabs.includes(tab)) {
      tab = availableTabs[0] || 'zabbix';
    }
    adminState.activeTab = tab;
    adminTabs.forEach((btn) => {
      const isActive = btn.dataset.adminTab === tab;
      btn.classList.toggle('active', isActive);
    });
    Object.entries(adminPanels).forEach(([key, panel]) => {
      if (!panel) return;
      panel.classList.toggle('active', key === tab);
    });
    
    // Load data when switching to users tab
    if (tab === 'users') {
      loadAdminUsers($adminUserIncludeInactive?.checked).catch(() => {});
      loadAdminGlobalApiKeys().catch(() => {});
      loadAdminRoles(adminState.roles.length === 0).catch(() => {});
      showAdminUserEmpty();
    }

    // Initialize backup config when switching to backup tab
    if (tab === 'backup') {
      updateBackupConfigVisibility();
      updateBackupConfigFromState();
    }

    if (tab === 'vcenter') {
      loadAdminVCenters(adminState.vcenters.length === 0).catch(() => {});
    }
  }

  function resetAdminVCenterForm() {
    if ($adminVCenterId) $adminVCenterId.value = '';
    if ($adminVCenterName) $adminVCenterName.value = '';
    if ($adminVCenterBaseUrl) $adminVCenterBaseUrl.value = '';
    if ($adminVCenterUsername) $adminVCenterUsername.value = '';
    if ($adminVCenterPassword) $adminVCenterPassword.value = '';
    if ($adminVCenterVerifySSL) $adminVCenterVerifySSL.checked = true;
    if ($adminVCenterFormStatus) $adminVCenterFormStatus.textContent = '';
    if ($adminVCenterPasswordHelp) $adminVCenterPasswordHelp.hidden = true;
  }

  function openAdminVCenterForm(config = null) {
    if (!$adminVCenterForm) return;
    adminState.editingVCenter = config;
    if ($adminVCenterFormTitle) $adminVCenterFormTitle.textContent = config ? 'Edit vCenter' : 'Add vCenter';
    if ($adminVCenterId) $adminVCenterId.value = config?.id || '';
    if ($adminVCenterName) $adminVCenterName.value = config?.name || '';
    if ($adminVCenterBaseUrl) $adminVCenterBaseUrl.value = config?.base_url || '';
    if ($adminVCenterUsername) $adminVCenterUsername.value = config?.username || '';
    if ($adminVCenterPassword) $adminVCenterPassword.value = '';
    if ($adminVCenterVerifySSL) $adminVCenterVerifySSL.checked = config ? config.verify_ssl !== false : true;
    if ($adminVCenterPasswordHelp) $adminVCenterPasswordHelp.hidden = !config;
    if ($adminVCenterFormStatus) $adminVCenterFormStatus.textContent = '';
    $adminVCenterForm.classList.remove('hidden');
    $adminVCenterName?.focus();
  }

  function closeAdminVCenterForm() {
    if (!$adminVCenterForm) return;
    adminState.editingVCenter = null;
    resetAdminVCenterForm();
    if ($adminVCenterFormStatus) $adminVCenterFormStatus.classList.remove('error', 'success');
    $adminVCenterForm.classList.add('hidden');
  }

  function renderAdminVCenterList() {
    if (!$adminVCenterList) return;
    $adminVCenterList.innerHTML = '';
    if (adminState.vcenterLoading) {
      const loading = document.createElement('div');
      loading.className = 'account-empty';
      loading.textContent = 'Loading vCenters…';
      $adminVCenterList.appendChild(loading);
      return;
    }
    if (!adminState.vcenters.length) {
      const empty = document.createElement('div');
      empty.className = 'account-empty';
      empty.textContent = 'No vCenters configured yet.';
      $adminVCenterList.appendChild(empty);
      return;
    }

    const frag = document.createDocumentFragment();
    adminState.vcenters.forEach((vc) => {
      if (!vc) return;
      const card = document.createElement('div');
      card.className = 'admin-vcenter-card';

      const main = document.createElement('div');
      main.className = 'admin-vcenter-card-main';

      const title = document.createElement('h3');
      title.className = 'admin-vcenter-card-name';
      title.textContent = vc.name || 'vCenter';
      main.appendChild(title);

      const url = document.createElement('div');
      url.className = 'admin-vcenter-card-url';
      url.textContent = vc.base_url || 'URL not configured';
      main.appendChild(url);

      const meta = document.createElement('div');
      meta.className = 'admin-vcenter-card-meta';
      const usernameSpan = document.createElement('span');
      usernameSpan.textContent = vc.username ? `User: ${vc.username}` : 'User not set';

      const tlsSpan = document.createElement('span');
      const tlsOk = vc.verify_ssl !== false;
      tlsSpan.textContent = tlsOk ? 'TLS verified' : 'TLS not verified';
      tlsSpan.classList.add(tlsOk ? 'status-ok' : 'status-warn');

      const credsSpan = document.createElement('span');
      const credsOk = !!vc.has_credentials;
      credsSpan.textContent = credsOk ? 'Credentials stored' : 'Credentials missing';
      credsSpan.classList.add(credsOk ? 'status-ok' : 'status-warn');

      const refreshSpan = document.createElement('span');
      if (vc.last_refresh) {
        try {
          refreshSpan.textContent = `Last update: ${amsDateTimeString(new Date(vc.last_refresh))}`;
        } catch {
          refreshSpan.textContent = `Last update: ${vc.last_refresh}`;
        }
        refreshSpan.classList.add('status-ok');
      } else {
        refreshSpan.textContent = 'Last update: never';
        refreshSpan.classList.add('status-warn');
      }

      const countSpan = document.createElement('span');
      const vmCount = Number(vc.vm_count);
      if (Number.isFinite(vmCount) && vmCount >= 0) {
        const label = vmCount === 1 ? 'VM' : 'VMs';
        countSpan.textContent = `${vmCount.toLocaleString()} ${label}`;
        countSpan.classList.add('status-ok');
      } else {
        countSpan.textContent = 'VMs: unknown';
        countSpan.classList.add('status-warn');
      }

      meta.append(usernameSpan, tlsSpan, credsSpan, countSpan, refreshSpan);
      main.appendChild(meta);

      const actions = document.createElement('div');
      actions.className = 'admin-vcenter-card-actions';

      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'btn ghost';
      editBtn.textContent = 'Edit';
      editBtn.addEventListener('click', () => openAdminVCenterForm(vc));

      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'btn danger ghost';
      deleteBtn.textContent = 'Delete';
      deleteBtn.addEventListener('click', () => deleteAdminVCenter(vc));

      actions.appendChild(editBtn);
      actions.appendChild(deleteBtn);

      card.appendChild(main);
      card.appendChild(actions);
      frag.appendChild(card);
    });

    $adminVCenterList.appendChild(frag);
  }

  async function loadAdminVCenters(force = false) {
    if (!$adminVCenterList) return [];
    if (adminState.vcenterLoading && !force) return adminState.vcenters;
    adminState.vcenterLoading = true;
    renderAdminVCenterList();
    try {
      const res = await fetch(`${API_BASE}/vcenter/configs`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data?.detail || `${res.status} ${res.statusText}`);
      }
      adminState.vcenters = Array.isArray(data)
        ? data.map((item) => {
            if (!item || typeof item !== 'object') return item;
            const numericVmCount = Number(item.vm_count);
            return {
              ...item,
              vm_count: Number.isFinite(numericVmCount) && numericVmCount >= 0 ? numericVmCount : null,
            };
          })
        : [];
      if ($adminVCenterStatus) {
        $adminVCenterStatus.classList.remove('error');
        $adminVCenterStatus.classList.add('success');
      }
      flashStatus(
        $adminVCenterStatus,
        `Loaded ${adminState.vcenters.length} vCenter${adminState.vcenters.length === 1 ? '' : 's'}.`,
      );
      return adminState.vcenters;
    } catch (err) {
      console.error('Failed to load vCenter configurations', err);
      adminState.vcenters = [];
      if ($adminVCenterStatus) {
        $adminVCenterStatus.classList.remove('success');
        $adminVCenterStatus.classList.add('error');
      }
      flashStatus($adminVCenterStatus, `Failed to load vCenters: ${err?.message || err}`, 4000);
      return [];
    } finally {
      adminState.vcenterLoading = false;
      renderAdminVCenterList();
    }
  }

  async function saveAdminVCenter() {
    if (!$adminVCenterForm || !$adminVCenterSave) return;
    const id = ($adminVCenterId?.value || '').trim();
    const name = ($adminVCenterName?.value || '').trim();
    const baseUrl = ($adminVCenterBaseUrl?.value || '').trim();
    const username = ($adminVCenterUsername?.value || '').trim();
    const password = ($adminVCenterPassword?.value || '').trim();
    const verify = !!$adminVCenterVerifySSL?.checked;

    if ($adminVCenterFormStatus) $adminVCenterFormStatus.classList.remove('error', 'success');
    if (!name || !baseUrl || !username) {
      if ($adminVCenterFormStatus) $adminVCenterFormStatus.classList.add('error');
      flashStatus($adminVCenterFormStatus, 'Name, base URL, and username are required.', 3200);
      return;
    }

    const payload = {
      name,
      base_url: baseUrl,
      username,
      verify_ssl: verify,
    };
    if (!id || password) {
      if (!password) {
        if ($adminVCenterFormStatus) $adminVCenterFormStatus.classList.add('error');
        flashStatus($adminVCenterFormStatus, 'Password is required for new vCenters.', 3200);
        return;
      }
      payload.password = password;
    }

    const method = id ? 'PUT' : 'POST';
    const url = id ? `${API_BASE}/vcenter/configs/${encodeURIComponent(id)}` : `${API_BASE}/vcenter/configs`;

    $adminVCenterSave.disabled = true;
    flashStatus($adminVCenterFormStatus, 'Saving…');
    try {
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data?.detail || `${res.status} ${res.statusText}`);
      }
      if ($adminVCenterStatus) {
        $adminVCenterStatus.classList.remove('error');
        $adminVCenterStatus.classList.add('success');
      }
      flashStatus($adminVCenterStatus, id ? 'Updated vCenter configuration.' : 'Created vCenter configuration.', 3600);
      closeAdminVCenterForm();
      await loadAdminVCenters(true);
      loadVCenterInstances(true).catch(() => {});
    } catch (err) {
      console.error('Failed to save vCenter configuration', err);
      if ($adminVCenterFormStatus) $adminVCenterFormStatus.classList.add('error');
      flashStatus($adminVCenterFormStatus, `Failed to save: ${err?.message || err}`, 4000);
    } finally {
      $adminVCenterSave.disabled = false;
    }
  }

  async function deleteAdminVCenter(vc) {
    if (!vc || !vc.id) return;
    const confirmed = window.confirm(`Delete vCenter '${vc.name || vc.id}'?`);
    if (!confirmed) return;
    try {
      const res = await fetch(`${API_BASE}/vcenter/configs/${encodeURIComponent(vc.id)}`, { method: 'DELETE' });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || `${res.status} ${res.statusText}`);
      }
      if ($adminVCenterStatus) {
        $adminVCenterStatus.classList.remove('error');
        $adminVCenterStatus.classList.add('success');
      }
      flashStatus($adminVCenterStatus, 'Deleted vCenter configuration.', 3600);
      if (adminState.editingVCenter?.id === vc.id) {
        closeAdminVCenterForm();
      }
      await loadAdminVCenters(true);
      loadVCenterInstances(true).catch(() => {});
    } catch (err) {
      console.error('Failed to delete vCenter configuration', err);
      if ($adminVCenterStatus) {
        $adminVCenterStatus.classList.remove('success');
        $adminVCenterStatus.classList.add('error');
      }
      flashStatus($adminVCenterStatus, `Failed to delete: ${err?.message || err}`, 4000);
    }
  }

  // ---------------------------
  // User Management Functions
  // ---------------------------
  
  async function loadAdminUsers(includeInactive = false) {
    if (!$adminUserList) return;
    try {
      const params = new URLSearchParams();
      if (includeInactive) params.set('include_inactive', 'true');
      const res = await fetch(`${API_BASE}/admin/users?${params.toString()}`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || res.statusText);
      }
      const users = await res.json();
      adminState.users = Array.isArray(users) ? users : [];
      renderAdminUserList();
      flashStatus($adminUserStatus, `Loaded ${adminState.users.length} users`);
    } catch (err) {
      console.error('Failed to load users', err);
      flashStatus($adminUserStatus, `Failed to load users: ${err?.message || err}`);
    }
  }

  function renderAdminUserList() {
    if (!$adminUserList) return;
    $adminUserList.innerHTML = '';
    
    if (!adminState.users.length) {
      const empty = document.createElement('div');
      empty.className = 'account-empty';
      empty.textContent = 'No users found.';
      $adminUserList.appendChild(empty);
      return;
    }

    const frag = document.createDocumentFragment();
    adminState.users.forEach((user) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'admin-user-item';
      if (adminState.selectedUser?.id === user.id) {
        item.classList.add('active');
      }
      
      const name = document.createElement('div');
      name.className = 'admin-user-name';
      name.textContent = user.display_name || user.username;
      
      const meta = document.createElement('div');
      meta.className = 'admin-user-meta';
      const parts = [];
      if (user.username !== (user.display_name || user.username)) {
        parts.push(`@${user.username}`);
      }
      parts.push(humanizeRole(user.role));
      if (!user.is_active) parts.push('Inactive');
      meta.textContent = parts.join(' • ');
      
      item.appendChild(name);
      item.appendChild(meta);
      
      item.addEventListener('click', () => {
        selectAdminUser(user);
      });
      
      frag.appendChild(item);
    });
    
    $adminUserList.appendChild(frag);
  }

  function collectRoleSelections(card) {
    return Array.from(card.querySelectorAll('input[data-permission]'))
      .filter((input) => input instanceof HTMLInputElement && input.checked && input.dataset.permission)
      .map((input) => input.dataset.permission);
  }

  function rolePermissionSet(role) {
    return new Set(Array.isArray(role?.permissions) ? role.permissions : []);
  }

  function updateRoleCardState(card, role) {
    if (!card || !role) return;
    const saveBtn = card.querySelector('[data-role-save]');
    if (!saveBtn) return;
    const selected = new Set(collectRoleSelections(card));
    const baseline = rolePermissionSet(role);
    let dirty = selected.size !== baseline.size;
    if (!dirty) {
      baseline.forEach((perm) => {
        if (!selected.has(perm)) dirty = true;
      });
    }
    saveBtn.disabled = !dirty;
    card.dataset.dirty = dirty ? '1' : '0';
  }

  function renderAdminRoles() {
    if (!$adminRoleList) return;
    $adminRoleList.innerHTML = '';

    if (!adminState.roles.length) {
      const empty = document.createElement('div');
      empty.className = 'account-empty';
      empty.textContent = 'No roles defined yet.';
      $adminRoleList.appendChild(empty);
      return;
    }

    const capabilities = Array.isArray(adminState.roleCapabilities) ? adminState.roleCapabilities : [];
    const frag = document.createDocumentFragment();

    adminState.roles.forEach((role) => {
      const card = document.createElement('section');
      card.className = 'admin-role-card';
      card.dataset.role = role.role;

      const header = document.createElement('div');
      header.className = 'admin-role-card-header';
      const title = document.createElement('h4');
      title.textContent = role.label || humanizeRole(role.role);
      header.appendChild(title);
      const keyBadge = document.createElement('span');
      keyBadge.className = 'badge role-key';
      keyBadge.textContent = role.role;
      header.appendChild(keyBadge);
      card.appendChild(header);

      const description = (role.description || '').trim();
      if (description) {
        const para = document.createElement('p');
        para.className = 'admin-role-desc';
        para.textContent = description;
        card.appendChild(para);
      }

      const perms = rolePermissionSet(role);
      const capabilitiesContainer = document.createElement('div');
      capabilitiesContainer.className = 'admin-role-capabilities';
      if (!capabilities.length) {
        const warning = document.createElement('div');
        warning.className = 'admin-role-empty';
        warning.textContent = 'No capabilities available.';
        capabilitiesContainer.appendChild(warning);
      } else {
        capabilities.forEach((cap) => {
          if (!cap?.id) return;
          const label = document.createElement('label');
          label.className = 'admin-role-capability';
          const checkbox = document.createElement('input');
          checkbox.type = 'checkbox';
          checkbox.dataset.permission = cap.id;
          checkbox.checked = perms.has(cap.id);
          label.appendChild(checkbox);
          const span = document.createElement('span');
          const titleText = cap.label || cap.id;
          const descText = cap.description ? ` – ${cap.description}` : '';
          span.innerHTML = `<strong>${titleText}</strong>${descText}`;
          label.appendChild(span);
          checkbox.addEventListener('change', () => updateRoleCardState(card, role));
          capabilitiesContainer.appendChild(label);
        });
      }
      card.appendChild(capabilitiesContainer);

      const actions = document.createElement('div');
      actions.className = 'admin-role-actions';
      const saveBtn = document.createElement('button');
      saveBtn.type = 'button';
      saveBtn.className = 'btn ghost';
      saveBtn.textContent = 'Save';
      saveBtn.dataset.roleSave = '1';
      saveBtn.addEventListener('click', () => saveRolePermissions(role.role, card));
      actions.appendChild(saveBtn);
      card.appendChild(actions);

      updateRoleCardState(card, role);
      frag.appendChild(card);
    });

    $adminRoleList.appendChild(frag);
  }

  async function loadAdminRoles(force = false) {
    if (!force && adminState.roles.length) {
      renderAdminRoles();
      refreshAdminRoleOptions();
      return;
    }
    try {
      if ($adminRoleStatus) $adminRoleStatus.textContent = 'Loading roles…';
      const res = await fetch(`${API_BASE}/admin/roles`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || res.statusText);
      }
      const payload = await res.json();
      const roles = Array.isArray(payload?.roles) ? payload.roles : [];
      adminState.roles = roles.map((role) => ({
        ...role,
        permissions: Array.isArray(role?.permissions) ? role.permissions : [],
      }));
      adminState.roleCapabilities = Array.isArray(payload?.capabilities) ? payload.capabilities : [];
      renderAdminRoles();
      refreshAdminRoleOptions();
      if ($adminRoleStatus) $adminRoleStatus.textContent = '';
    } catch (err) {
      console.error('Failed to load roles', err);
      flashStatus($adminRoleStatus, err?.message || 'Unable to load roles.');
    }
  }

  async function saveRolePermissions(roleKey, card) {
    if (!roleKey || !card) return;
    const role = adminState.roles.find((entry) => entry.role === roleKey);
    if (!role) {
      flashStatus($adminRoleStatus, `Role '${roleKey}' is not defined.`);
      return;
    }
    const selected = collectRoleSelections(card);
    const currentSet = new Set(selected);
    const baseline = rolePermissionSet(role);
    let changed = currentSet.size !== baseline.size;
    if (!changed) {
      baseline.forEach((perm) => {
        if (!currentSet.has(perm)) changed = true;
      });
    }
    if (!changed) {
      flashStatus($adminRoleStatus, 'No changes to save.');
      updateRoleCardState(card, role);
      return;
    }

    const saveBtn = card.querySelector('[data-role-save]');
    if (saveBtn) saveBtn.disabled = true;
    flashStatus($adminRoleStatus, 'Saving…');

    try {
      const payload = {
        permissions: selected,
        label: role.label || role.role,
        description: role.description || null,
      };
      const res = await fetch(`${API_BASE}/admin/roles/${encodeURIComponent(roleKey)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || res.statusText);
      }
      const data = await res.json();
      if (data && typeof data === 'object') {
        adminState.roles = adminState.roles.map((entry) => (entry.role === data.role ? {
          ...entry,
          ...data,
          permissions: Array.isArray(data.permissions) ? data.permissions : [],
        } : entry));
        adminState.users = adminState.users.map((user) => (user.role === data.role ? {
          ...user,
          permissions: Array.isArray(data.permissions) ? data.permissions : [],
        } : user));
        if (adminState.selectedUser && adminState.selectedUser.role === data.role) {
          adminState.selectedUser = {
            ...adminState.selectedUser,
            permissions: Array.isArray(data.permissions) ? data.permissions : [],
          };
          showAdminUserDetail(adminState.selectedUser);
        }
        if (currentUser && currentUser.role === data.role) {
          currentUser.permissions = Array.isArray(data.permissions) ? data.permissions : [];
          setUserPermissions(currentUser.permissions);
          applyRoleRestrictions();
          updateTopbarUser();
        }
        renderAdminRoles();
        flashStatus($adminRoleStatus, 'Permissions updated.');
      }
    } catch (err) {
      console.error('Failed to update role permissions', err);
      flashStatus($adminRoleStatus, err?.message || 'Failed to update role permissions.');
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  function refreshAdminRoleOptions(preselect = null) {
    if (!$adminUserRole) return;
    const currentValue = preselect ?? $adminUserRole.value;
    $adminUserRole.innerHTML = '';
    const roles = adminState.roles.length ? adminState.roles : [{ role: 'member', label: 'Member' }, { role: 'admin', label: 'Admin' }];
    roles.forEach((role) => {
      if (!role?.role) return;
      const opt = document.createElement('option');
      opt.value = role.role;
      opt.textContent = role.label || humanizeRole(role.role);
      $adminUserRole.appendChild(opt);
    });
    const desired = currentValue || (roles[0] && roles[0].role) || 'member';
    $adminUserRole.value = desired;
  }

  function selectAdminUser(user) {
    adminState.selectedUser = user;
    renderAdminUserList(); // Re-render to update active state
    showAdminUserDetail(user);
  }

  function showAdminUserDetail(user) {
    if (!user) {
      showAdminUserEmpty();
      return;
    }

    // Hide empty state and show forms
    if ($adminUserEmpty) $adminUserEmpty.classList.add('hidden');
    if ($adminUserForm) $adminUserForm.classList.remove('hidden');
    if ($adminUserPasswordForm) $adminUserPasswordForm.classList.remove('hidden');
    if ($adminUserDelete) $adminUserDelete.classList.remove('hidden');

    // Populate form
    if ($adminUserFormTitle) $adminUserFormTitle.textContent = `Edit User: ${user.display_name || user.username}`;
    refreshAdminRoleOptions(user.role);
    if ($adminUserUsername) $adminUserUsername.value = user.username || '';
    if ($adminUserDisplay) $adminUserDisplay.value = user.display_name || '';
    if ($adminUserEmail) $adminUserEmail.value = user.email || '';
    if ($adminUserRole) $adminUserRole.value = user.role || 'member';
    if ($adminUserActive) $adminUserActive.checked = user.is_active !== false;

    // Hide new password field for existing users
    if ($adminUserNewPasswordRow) $adminUserNewPasswordRow.style.display = 'none';
    if ($adminUserForm) $adminUserForm.classList.remove('create-mode');

    // Clear password form
    if ($adminUserPassword) $adminUserPassword.value = '';
    
    // Clear status messages
    flashStatus($adminUserFormStatus, '');
    flashStatus($adminUserPasswordStatus, '');
  }

  function showAdminUserEmpty() {
    adminState.selectedUser = null;
    if ($adminUserEmpty) $adminUserEmpty.classList.remove('hidden');
    if ($adminUserForm) $adminUserForm.classList.add('hidden');
    if ($adminUserPasswordForm) $adminUserPasswordForm.classList.add('hidden');
    if ($adminUserDelete) $adminUserDelete.classList.add('hidden');
  }

  function showAdminUserCreate() {
    adminState.selectedUser = null;
    
    // Show forms in create mode
    if ($adminUserEmpty) $adminUserEmpty.classList.add('hidden');
    if ($adminUserForm) {
      $adminUserForm.classList.remove('hidden');
      $adminUserForm.classList.add('create-mode');
    }
    if ($adminUserPasswordForm) $adminUserPasswordForm.classList.add('hidden');
    if ($adminUserDelete) $adminUserDelete.classList.add('hidden');

    // Clear and setup form for new user
    if ($adminUserFormTitle) $adminUserFormTitle.textContent = 'Create New User';
    if ($adminUserUsername) {
      $adminUserUsername.value = '';
      $adminUserUsername.removeAttribute('readonly');
    }
    if ($adminUserDisplay) $adminUserDisplay.value = '';
    if ($adminUserEmail) $adminUserEmail.value = '';
    if ($adminUserNewPassword) $adminUserNewPassword.value = '';
    refreshAdminRoleOptions('member');
    if ($adminUserRole) $adminUserRole.value = 'member';
    if ($adminUserActive) $adminUserActive.checked = true;

    // Show new password field for new users
    if ($adminUserNewPasswordRow) $adminUserNewPasswordRow.style.display = 'flex';
    
    // Clear status messages
    flashStatus($adminUserFormStatus, '');
    flashStatus($adminUserPasswordStatus, '');
    
    // Focus username field
    setTimeout(() => $adminUserUsername?.focus(), 100);
  }

  async function saveAdminUser() {
    const isCreate = !adminState.selectedUser;
    const username = ($adminUserUsername?.value || '').trim();
    const displayName = ($adminUserDisplay?.value || '').trim();
    const email = ($adminUserEmail?.value || '').trim();
    const role = $adminUserRole?.value || 'member';
    const isActive = $adminUserActive?.checked !== false;

    if (!username) {
      flashStatus($adminUserFormStatus, 'Username is required');
      $adminUserUsername?.focus();
      return;
    }

    if (isCreate) {
      const password = ($adminUserNewPassword?.value || '').trim();
      if (!password) {
        flashStatus($adminUserFormStatus, 'Password is required for new users');
        $adminUserNewPassword?.focus();
        return;
      }
      if (password.length < 8) {
        flashStatus($adminUserFormStatus, 'Password must be at least 8 characters');
        $adminUserNewPassword?.focus();
        return;
      }
    }

    if (email && !email.includes('@')) {
      flashStatus($adminUserFormStatus, 'Invalid email address');
      $adminUserEmail?.focus();
      return;
    }

    flashStatus($adminUserFormStatus, isCreate ? 'Creating user...' : 'Updating user...');
    
    try {
      let res;
      if (isCreate) {
        const payload = {
          username: username.toLowerCase(),
          password: $adminUserNewPassword.value,
          display_name: displayName || null,
          email: email || null,
          role: role,
        };
        res = await fetch(`${API_BASE}/admin/users`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        const payload = {
          display_name: displayName || null,
          email: email || null,
          role: role,
          is_active: isActive,
        };
        res = await fetch(`${API_BASE}/admin/users/${encodeURIComponent(adminState.selectedUser.id)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || res.statusText);
      }

      const savedUser = await res.json();
      flashStatus($adminUserFormStatus, isCreate ? 'User created successfully' : 'User updated successfully');
      
      // Refresh user list and select the saved user
      await loadAdminUsers($adminUserIncludeInactive?.checked);
      if (savedUser && typeof savedUser === 'object') {
        if (currentUser && savedUser.id === currentUser.id) {
          currentUser = savedUser;
          accountState.user = savedUser;
          setUserPermissions(Array.isArray(savedUser.permissions) ? savedUser.permissions : []);
          updateTopbarUser();
          populateAccountForms();
          applyRoleRestrictions();
        }
      }
      if (isCreate) {
        showAdminUserEmpty();
      } else {
        const matched = adminState.users.find((user) => user.id === savedUser.id) || savedUser;
        selectAdminUser(matched);
      }
    } catch (err) {
      console.error('Failed to save user', err);
      flashStatus($adminUserFormStatus, `Failed to save user: ${err?.message || err}`);
    }
  }

  async function setAdminUserPassword() {
    if (!adminState.selectedUser) return;
    
    const newPassword = ($adminUserPassword?.value || '').trim();
    if (!newPassword) {
      flashStatus($adminUserPasswordStatus, 'Password is required');
      $adminUserPassword?.focus();
      return;
    }
    if (newPassword.length < 8) {
      flashStatus($adminUserPasswordStatus, 'Password must be at least 8 characters');
      $adminUserPassword?.focus();
      return;
    }

    flashStatus($adminUserPasswordStatus, 'Setting password...');
    
    try {
      const res = await fetch(`${API_BASE}/admin/users/${encodeURIComponent(adminState.selectedUser.id)}/password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_password: newPassword }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || res.statusText);
      }

      flashStatus($adminUserPasswordStatus, 'Password updated successfully');
      if ($adminUserPassword) $adminUserPassword.value = '';
    } catch (err) {
      console.error('Failed to set password', err);
      flashStatus($adminUserPasswordStatus, `Failed to set password: ${err?.message || err}`);
    }
  }

  async function deleteAdminUser() {
    if (!adminState.selectedUser) return;
    
    const user = adminState.selectedUser;
    const displayName = user.display_name || user.username;
    
    if (!confirm(`Are you sure you want to delete user "${displayName}"? This action cannot be undone.`)) {
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/admin/users/${encodeURIComponent(user.id)}`, {
        method: 'DELETE',
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || res.statusText);
      }

      flashStatus($adminUserStatus, `User "${displayName}" deleted successfully`);
      
      // Refresh user list and clear selection
      await loadAdminUsers($adminUserIncludeInactive?.checked);
      showAdminUserEmpty();
    } catch (err) {
      console.error('Failed to delete user', err);
      flashStatus($adminUserStatus, `Failed to delete user: ${err?.message || err}`);
    }
  }

  async function loadAdminGlobalApiKeys() {
    if (!$adminGlobalList) return;
    try {
      const res = await fetch(`${API_BASE}/admin/global-api-keys`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || res.statusText);
      }
      const keys = await res.json();
      adminState.globalApiKeys = Array.isArray(keys) ? keys : [];
      renderAdminGlobalApiKeys();
    } catch (err) {
      console.error('Failed to load global API keys', err);
      flashStatus($adminGlobalStatus, `Failed to load global API keys: ${err?.message || err}`);
    }
  }

  function renderAdminGlobalApiKeys() {
    if (!$adminGlobalList) return;
    $adminGlobalList.innerHTML = '';
    
    if (!adminState.globalApiKeys.length) {
      const empty = document.createElement('div');
      empty.className = 'account-token-empty';
      empty.textContent = 'No global API keys configured.';
      $adminGlobalList.appendChild(empty);
      return;
    }

    const frag = document.createDocumentFragment();
    adminState.globalApiKeys.forEach((key) => {
      const card = document.createElement('div');
      card.className = 'admin-global-card';
      
      const header = document.createElement('div');
      header.className = 'admin-global-card-header';
      
      const meta = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = providerLabel(key.provider);
      meta.appendChild(title);
      if (key.label) {
        const label = document.createElement('div');
        label.textContent = key.label;
        label.style.fontSize = '12px';
        label.style.color = 'var(--muted)';
        meta.appendChild(label);
      }
      
      const actions = document.createElement('div');
      actions.className = 'admin-global-card-actions';
      
      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'btn ghost';
      editBtn.textContent = 'Edit';
      editBtn.addEventListener('click', () => editGlobalApiKey(key));
      
      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'btn ghost';
      deleteBtn.textContent = 'Delete';
      deleteBtn.addEventListener('click', () => deleteGlobalApiKey(key.provider));
      
      actions.appendChild(editBtn);
      actions.appendChild(deleteBtn);
      
      header.appendChild(meta);
      header.appendChild(actions);
      card.appendChild(header);
      
      frag.appendChild(card);
    });
    
    $adminGlobalList.appendChild(frag);
  }

  function showGlobalApiKeyForm(key = null) {
    adminState.editingGlobalKey = true;
    if ($adminGlobalForm) $adminGlobalForm.classList.remove('hidden');
    
    // Populate providers dropdown
    if ($adminGlobalProvider) {
      $adminGlobalProvider.innerHTML = '';
      const providers = accountState.providers.length
        ? accountState.providers
        : defaultChatProviders.map((id) => ({ id }));
      
      providers.forEach((provider) => {
        const option = document.createElement('option');
        option.value = provider.id;
        option.textContent = providerLabel(provider.id);
        $adminGlobalProvider.appendChild(option);
      });
    }
    
    if (key) {
      // Edit mode
      if ($adminGlobalProvider) $adminGlobalProvider.value = key.provider;
      if ($adminGlobalLabel) $adminGlobalLabel.value = key.label || '';
      if ($adminGlobalSecret) $adminGlobalSecret.value = '';
    } else {
      // Create mode
      if ($adminGlobalProvider) $adminGlobalProvider.value = '';
      if ($adminGlobalLabel) $adminGlobalLabel.value = '';
      if ($adminGlobalSecret) $adminGlobalSecret.value = '';
    }
    
    flashStatus($adminGlobalStatus, '');
    setTimeout(() => $adminGlobalSecret?.focus(), 100);
  }

  function hideGlobalApiKeyForm() {
    adminState.editingGlobalKey = false;
    if ($adminGlobalForm) $adminGlobalForm.classList.add('hidden');
    flashStatus($adminGlobalStatus, '');
  }

  function editGlobalApiKey(key) {
    showGlobalApiKeyForm(key);
  }

  async function saveGlobalApiKey() {
    const provider = ($adminGlobalProvider?.value || '').trim();
    const label = ($adminGlobalLabel?.value || '').trim();
    const secret = ($adminGlobalSecret?.value || '').trim();

    if (!provider) {
      flashStatus($adminGlobalStatus, 'Provider is required');
      $adminGlobalProvider?.focus();
      return;
    }
    if (!secret) {
      flashStatus($adminGlobalStatus, 'Secret is required');
      $adminGlobalSecret?.focus();
      return;
    }

    flashStatus($adminGlobalStatus, 'Saving...');
    
    try {
      const res = await fetch(`${API_BASE}/admin/global-api-keys/${encodeURIComponent(provider)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ secret, label: label || null }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || res.statusText);
      }

      flashStatus($adminGlobalStatus, 'Global API key saved successfully');
      hideGlobalApiKeyForm();
      await loadAdminGlobalApiKeys();
      await refreshChatProviders(); // Refresh chat providers to update UI
    } catch (err) {
      console.error('Failed to save global API key', err);
      flashStatus($adminGlobalStatus, `Failed to save: ${err?.message || err}`);
    }
  }

  async function deleteGlobalApiKey(provider) {
    if (!provider) return;
    
    if (!confirm(`Are you sure you want to delete the global API key for ${providerLabel(provider)}?`)) {
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/admin/global-api-keys/${encodeURIComponent(provider)}`, {
        method: 'DELETE',
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || res.statusText);
      }

      flashStatus($adminGlobalStatus, 'Global API key deleted successfully');
      await loadAdminGlobalApiKeys();
      await refreshChatProviders(); // Refresh chat providers to update UI
    } catch (err) {
      console.error('Failed to delete global API key', err);
      flashStatus($adminGlobalStatus, `Failed to delete: ${err?.message || err}`);
    }
  }

  // Chat placeholder
  const $chatProvider = document.getElementById('chat-provider');
  const $chatModel = document.getElementById('chat-model');
  const $chatDataset = document.getElementById('chat-dataset');
  const $chatInput = document.getElementById('chat-input');
  const $chatSend = document.getElementById('chat-send');
  const $chatLog = document.getElementById('chat-log');
  const $chatSessions = document.getElementById('chat-sessions');
  const $chatNew = document.getElementById('chat-new');
  const $chatMessages = document.getElementById('chat-messages');
  renderChatEmptyState();
  let chatSessionId = null;
  function saveChatPrefs() {
    try {
      if ($chatProvider) localStorage.setItem('chat_provider', $chatProvider.value || '');
      if ($chatModel) localStorage.setItem('chat_model', $chatModel.value || '');
      if ($chatDataset) localStorage.setItem('chat_dataset', $chatDataset.value || 'merged');
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
      const savedDataset = localStorage.getItem('chat_dataset');
      if ($chatDataset) {
        const normalized = savedDataset === 'all' ? 'merged' : savedDataset;
        if (normalized && Array.from($chatDataset.options || []).some(opt => opt.value === normalized)) {
          $chatDataset.value = normalized;
        } else if (!$chatDataset.value) {
          $chatDataset.value = 'merged';
        }
      }
    } catch {}
  }
  function setupChatPrefListeners() {
    $chatProvider?.addEventListener('change', () => saveChatPrefs());
    $chatModel?.addEventListener('change', () => saveChatPrefs());
    $chatModel?.addEventListener('blur', () => saveChatPrefs());
    $chatDataset?.addEventListener('change', () => saveChatPrefs());
    document.getElementById('chat-stream')?.addEventListener('change', () => saveChatPrefs());
    document.getElementById('chat-include-data')?.addEventListener('change', () => saveChatPrefs());
  }
  async function loadChatDefaults() {
    try {
      const data = await refreshChatProviders();
      if (!data) return;
      // Set default provider if none selected
      const dprov = data?.default_provider || 'openai';
      if ($chatProvider && !$chatProvider.value) $chatProvider.value = dprov;
      // If model empty, set default for selected provider
      const sel = $chatProvider?.value || dprov;
      const cfg = (data?.providers || []).find(p => p.id === sel);
      if ($chatModel && !$chatModel.value && cfg && cfg.default_model) $chatModel.value = cfg.default_model;
    } catch {}
  }
  function formatTokenSummary(usage) {
    if (!usage || typeof usage !== 'object') return '';
    const parts = [];
    const prompt = usage.prompt_tokens ?? usage.promptTokens;
    const completion = usage.completion_tokens ?? usage.completionTokens;
    const total = usage.total_tokens ?? usage.totalTokens;
    const cost = usage.cost_usd ?? usage.costUsd ?? 0;
    
    const toNumber = (value) => {
      const num = Number(value);
      return Number.isFinite(num) ? num : null;
    };
    
    const promptNum = toNumber(prompt);
    const completionNum = toNumber(completion);
    const totalNum = toNumber(total);
    const costNum = toNumber(cost);
    
    if (promptNum !== null) parts.push(`prompt: ${promptNum}`);
    if (completionNum !== null) parts.push(`completion: ${completionNum}`);
    if (totalNum !== null) parts.push(`total: ${totalNum}`);
    if (costNum !== null && costNum > 0) parts.push(`cost: $${costNum.toFixed(4)}`);
    
    if (!parts.length) return '';
    return `Tokens — ${parts.join(', ')}`;
  }

  function formatTokenMetrics(usage) {
    if (!usage || typeof usage !== 'object') return '';
    const efficiency = usage.token_efficiency ?? 0;
    const retries = usage.retry_count ?? 0;
    const rateLimited = usage.was_rate_limited ?? false;
    const queueTime = usage.queue_wait_time_ms ?? 0;
    
    const parts = [];
    if (efficiency > 0) parts.push(`efficiency: ${efficiency.toFixed(2)} chars/token`);
    if (retries > 0) parts.push(`retries: ${retries}`);
    if (rateLimited) parts.push('rate limited');
    if (queueTime > 0) parts.push(`queue: ${queueTime}ms`);
    
    return parts.length > 0 ? `Performance — ${parts.join(', ')}` : '';
  }

  function appendChat(role, text, meta = null) {
    if (!$chatMessages) return;
    
    // Hide empty state if present
    const emptyState = $chatMessages.querySelector('.chat-empty-state');
    if (emptyState) {
      emptyState.style.display = 'none';
    }
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${role}`;
    
    const bubble = document.createElement('div');
    bubble.className = 'chat-message-bubble';
    
    // Use markdown parsing for assistant messages, plain text for user messages
    if (role === 'assistant') {
      bubble.innerHTML = parseMarkdown(text);
    } else {
      bubble.textContent = text;
    }
    
    const time = document.createElement('div');
    time.className = 'chat-message-time';
    time.textContent = new Date().toLocaleTimeString();
    
    messageDiv.appendChild(bubble);
    messageDiv.appendChild(time);

    if (role === 'assistant') {
      const usageText = meta && meta.prompt_tokens !== undefined ? formatTokenSummary(meta) : formatTokenSummary(meta?.usage ?? meta);
      const metricsText = formatTokenMetrics(meta?.usage ?? meta);
      
      if (usageText) {
        const metaDiv = document.createElement('div');
        metaDiv.className = 'chat-message-meta';
        metaDiv.textContent = usageText;
        messageDiv.appendChild(metaDiv);
      }
      
      if (metricsText) {
        const metricsDiv = document.createElement('div');
        metricsDiv.className = 'chat-message-metrics';
        metricsDiv.textContent = metricsText;
        messageDiv.appendChild(metricsDiv);
      }
    }
    
    $chatMessages.appendChild(messageDiv);
    $chatMessages.scrollTop = $chatMessages.scrollHeight;
  }

  async function refreshChatHistory() {
    const sid = await ensureChatSession();
    if (!sid) return;
    try {
      const res = await fetch(`${API_BASE}/chat/history?session_id=${encodeURIComponent(sid)}`);
      if (!res.ok) return;
      const data = await res.json();
      const msgs = Array.isArray(data?.messages) ? data.messages : [];
      clearChatLog();
      for (const m of msgs) {
        if (m && typeof m.content === 'string' && typeof m.role === 'string') appendChat(m.role, m.content, m.usage || null);
      }
    } catch (err) {
      console.error('Failed to load chat history', err);
    }
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"]/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m] || m));
  }

  function formatTimestamp(ts) {
    if (!ts) return '';
    try {
      const d = new Date(ts);
      if (Number.isNaN(d.getTime())) return ts;
      return `${amsDateTimeString(d)} ${amsTzShort(d)}`.trim();
    } catch {
      return ts;
    }
  }

  function renderChatEmptyState() {
    if (!$chatMessages) return;
    $chatMessages.innerHTML = '';
    const empty = document.createElement('div');
    empty.className = 'chat-empty-state';

    const icon = document.createElement('div');
    icon.className = 'chat-empty-icon';
    icon.textContent = '💬';
    const title = document.createElement('h3');
    title.textContent = 'Welcome to AI Chat';
    const description = document.createElement('p');
    description.textContent = 'Ask anything about your data exports, monitoring events or Atlassian updates and I will pull the relevant context.';

    const suggestions = document.createElement('div');
    suggestions.id = 'chat-examples';
    suggestions.className = 'chat-suggestions';

    empty.append(icon, title, description, suggestions);
    $chatMessages.append(empty);
    $chatExamples = suggestions;
    
    // Ensure persistent examples are shown
    ensurePersistentSearchOptions();
  }

  function clearChatLog() {
    renderChatEmptyState();
  }

  function setupSuggestionButtons() {
    const suggestionButtons = document.querySelectorAll('.chat-suggestion-btn');
    suggestionButtons.forEach(btn => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const suggestion = btn.getAttribute('data-suggestion') || btn.textContent || '';
        insertChatPrompt(suggestion, true);
      });
    });
  }

  // Auto-resize textarea
  function setupAutoResize() {
    if ($chatInput) {
      $chatInput.addEventListener('input', () => {
        $chatInput.style.height = 'auto';
        $chatInput.style.height = Math.min($chatInput.scrollHeight, 120) + 'px';
      });
    }
  }

  function renderChatSessions() {
    if (!$chatSessions) return;
    const sessions = Array.isArray(chatSessionsState.items) ? chatSessionsState.items : [];
    if (!sessions.length) {
      const empty = document.createElement('div');
      empty.className = 'chat-sessions-empty';
      empty.textContent = 'No chats yet';
      $chatSessions.replaceChildren(empty);
      return;
    }
    const frag = document.createDocumentFragment();
    sessions.forEach((session) => {
      if (!session || !session.session_id) return;
      const wrapper = document.createElement('div');
      wrapper.className = 'chat-session-wrapper';
      
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chat-session';
      if (session.session_id === chatSessionsState.active) btn.classList.add('active');
      const title = escapeHtml(session.title || 'New chat');
      const time = formatTimestamp(session.updated_at);
      btn.innerHTML = `<div class="chat-session-title">${title}</div><div class="chat-session-meta">${escapeHtml(time)}</div>`;
      btn.addEventListener('click', () => {
        setActiveChatSession(session.session_id);
      });
      
      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'chat-session-delete';
      deleteBtn.innerHTML = '×';
      deleteBtn.title = 'Delete chat session';
      deleteBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        e.preventDefault();
        await deleteChatSession(session.session_id);
      });
      
      wrapper.appendChild(btn);
      wrapper.appendChild(deleteBtn);
      frag.appendChild(wrapper);
    });
    $chatSessions.replaceChildren(frag);
  }

  async function deleteChatSession(sessionId) {
    if (!sessionId) return;
    
    const session = chatSessionsState.items.find(s => s.session_id === sessionId);
    const title = session?.title || 'this chat';
    
    if (!confirm(`Are you sure you want to delete "${title}"? This cannot be undone.`)) {
      return;
    }
    
    try {
      const res = await fetch(`${API_BASE}/chat/session/${encodeURIComponent(sessionId)}`, {
        method: 'DELETE',
      });
      
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || res.statusText);
      }
      
      // Remove from local state
      chatSessionsState.items = chatSessionsState.items.filter(s => s.session_id !== sessionId);
      
      // If this was the active session, switch to another or create new
      if (chatSessionsState.active === sessionId) {
        if (chatSessionsState.items.length > 0) {
          await setActiveChatSession(chatSessionsState.items[0].session_id);
        } else {
          chatSessionId = null;
          chatSessionsState.active = null;
          await createChatSession();
        }
      }
      
      renderChatSessions();
    } catch (err) {
      console.error('Failed to delete chat session', err);
      alert(`Failed to delete chat session: ${err?.message || err}`);
    }
  }

  async function setActiveChatSession(sessionId, options = {}) {
    if (!sessionId) return;
    chatSessionId = sessionId;
    chatSessionsState.active = sessionId;
    try { localStorage.setItem('chat_session_id', sessionId); } catch {}
    renderChatSessions();
    if (options.loadHistory !== false) {
      await refreshChatHistory();
    }
  }

  async function ensureChatSession() {
    if (chatSessionId) return chatSessionId;
    try {
      const stored = localStorage.getItem('chat_session_id');
      if (stored) chatSessionId = stored;
    } catch {}
    if (chatSessionId) return chatSessionId;
    await createChatSession();
    return chatSessionId;
  }

  async function createChatSession(name) {
    try {
      const res = await fetch(`${API_BASE}/chat/session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(name ? { name } : {}),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || res.statusText);
      }
      const session = await res.json();
      chatSessionId = session.session_id;
      chatSessionsState.active = chatSessionId;
      chatSessionsState.items = [session, ...chatSessionsState.items.filter((s) => s.session_id !== chatSessionId)];
      try { localStorage.setItem('chat_session_id', chatSessionId); } catch {}
      renderChatSessions();
      clearChatLog();
      return chatSessionId;
    } catch (err) {
      console.error('Failed to create chat session', err);
      alert(`Unable to start a new chat: ${err?.message || err}`);
      return null;
    }
  }

  async function fetchChatSessions() {
    if (chatSessionsState.loading) return;
    chatSessionsState.loading = true;
    try {
      const res = await fetch(`${API_BASE}/chat/sessions`);
      if (!res.ok) return;
      const data = await res.json();
      const sessions = Array.isArray(data?.sessions) ? data.sessions : [];
      chatSessionsState.items = sessions;
      let desired = chatSessionId;
      if (!desired) {
        try { desired = localStorage.getItem('chat_session_id'); } catch {}
      }
      if (desired && !sessions.some((s) => s?.session_id === desired)) desired = null;
      if (!desired) {
        if (sessions.length) {
          desired = sessions[0].session_id;
        } else {
          await createChatSession();
          return;
        }
      }
      chatSessionId = desired;
      chatSessionsState.active = desired;
      try { localStorage.setItem('chat_session_id', desired); } catch {}
      renderChatSessions();
      await refreshChatHistory();
    } catch (err) {
      console.error('Failed to load chat sessions', err);
    } finally {
      chatSessionsState.loading = false;
    }
  }

  async function sendChat() {
    const q = ($chatInput?.value || '').trim();
    if (!q) return;
    appendChat('user', q);
    if ($chatInput) $chatInput.value = '';
    const prov = ($chatProvider?.value || 'openai');
    const mdl = ($chatModel?.value || '');
    const datasetRaw = ($chatDataset?.value || 'merged');
    const dataset = datasetRaw === 'all' ? 'merged' : datasetRaw;
    saveChatPrefs();
    const sid = await ensureChatSession();
    if (!sid) return;
    const sys = chatConfig.systemPrompt || '';
    const toolContext = pendingToolContext;
    pendingToolContext = null;
    const messagePayload = toolContext
      ? `${toolContext.label}\n${toolContext.text}\n\nQuestion:\n${q}`
      : q;
    const tempPref = (typeof chatConfig.temperature === 'number' && Number.isFinite(chatConfig.temperature))
      ? chatConfig.temperature
      : undefined;
    
    // Enhanced status placeholder with queue information
    let placeholder = document.createElement('div');
    placeholder.className = 'chat-status-message processing';
    placeholder.innerHTML = `
      <div class="chat-status-icon spinning"></div>
      <span>AI is processing your request...</span>
    `;
    $chatMessages?.appendChild(placeholder);
    $chatMessages?.scrollTo(0, $chatMessages.scrollHeight);
    
    // Check queue status
    try {
      const queueRes = await fetch(`${API_BASE}/monitoring/queue-status`);
      if (queueRes.ok) {
        const queueData = await queueRes.json();
        const queueSize = queueData?.queue?.queue_size || 0;
        if (queueSize > 0) {
          placeholder.innerHTML = `
            <div class="chat-status-icon"></div>
            <span>Request queued (${queueSize} ahead of you)</span>
          `;
        }
      }
    } catch (e) {
      // Ignore queue status errors
    }
    try {
      const includeData = !!document.getElementById('chat-include-data')?.checked;
      const wantStream = !!document.getElementById('chat-stream')?.checked;
      // Streaming verzoek naar /chat/stream, met fallback naar /chat/complete
      const res = wantStream ? await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: prov, model: mdl, message: messagePayload, session_id: sid, system: sys, temperature: tempPref, include_context: includeData, dataset }),
      }) : null;
      if (!wantStream || !res || !res.ok || !res.body) {
        // Fallback to non-streaming
        const res2 = await fetch(`${API_BASE}/chat/complete`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: prov, model: mdl, message: messagePayload, session_id: sid, system: sys, temperature: tempPref, include_context: includeData, dataset }),
        });
        const data2 = await res2.json().catch(() => ({}));
        placeholder.remove();
        if (!res2.ok) {
          appendChat('assistant', data2?.detail || `Error: ${res2.status} ${res2.statusText}`);
        } else {
          appendChat('assistant', data2?.reply || '(empty response)', data2?.usage || null);
        }
        await fetchChatSessions();
        return;
      }
      // Stream tonen
      const messageDiv = document.createElement('div');
      messageDiv.className = 'chat-message assistant';
      
      const bubble = document.createElement('div');
      bubble.className = 'chat-message-bubble';
      
      const time = document.createElement('div');
      time.className = 'chat-message-time';
      time.textContent = new Date().toLocaleTimeString();
      
      messageDiv.appendChild(bubble);
      messageDiv.appendChild(time);
      placeholder.replaceWith(messageDiv);
      
      const reader = res.body.getReader();
      const td = new TextDecoder();
      let gotAny = false;
      let fullText = '';
      let usageMeta = null;
      let metaDiv = null;
      
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const text = td.decode(value, { stream: true });
        if (!text) continue;
        gotAny = true;
        fullText += text;

        const match = fullText.match(/\[\[TOKENS (\{.*?\})\]\]/);
        if (match) {
          try {
            usageMeta = JSON.parse(match[1]);
          } catch (_) {
            usageMeta = null;
          }
          fullText = fullText.replace(match[0], '').trimEnd();
        }

        bubble.innerHTML = parseMarkdown(fullText);
        $chatMessages?.scrollTo(0, $chatMessages.scrollHeight);
      }
      // No chunks? Fallback to complete
      if (!gotAny) {
        const res3 = await fetch(`${API_BASE}/chat/complete`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: prov, model: mdl, message: messagePayload, session_id: sid, system: sys, temperature: tempPref, include_context: includeData, dataset }),
        });
        const data3 = await res3.json().catch(() => ({}));
        if (!res3.ok) {
          bubble.innerHTML = parseMarkdown(data3?.detail || `Error: ${res3.status} ${res3.statusText}`);
        } else {
          bubble.innerHTML = parseMarkdown(data3?.reply || '');
          const usageText = formatTokenSummary(data3?.usage);
          if (usageText && messageDiv) {
            const metaDiv = document.createElement('div');
            metaDiv.className = 'chat-message-meta';
            metaDiv.textContent = usageText;
            messageDiv.appendChild(metaDiv);
          }
        }
      }
      if (usageMeta) {
        if (!metaDiv) {
          metaDiv = document.createElement('div');
          metaDiv.className = 'chat-message-meta';
          messageDiv.appendChild(metaDiv);
        }
        metaDiv.textContent = formatTokenSummary(usageMeta);
      }
      await fetchChatSessions();
    } catch (e) {
      placeholder.remove();
      
      // Enhanced error handling with user-friendly messages
      let errorMessage = `Error: ${e?.message || e}`;
      if (e?.message && e.message.includes('rate limit')) {
        errorMessage = '⚠️ Rate limit reached. Please wait a moment before sending another message.';
      } else if (e?.message && e.message.includes('503')) {
        errorMessage = '⚠️ Service temporarily unavailable. Please try again in a few moments.';
      } else if (e?.message && e.message.includes('queue')) {
        errorMessage = '⏳ Request queue is full. Please wait and try again.';
      }
      
      appendChat('assistant', errorMessage);
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
  
  // New chat button event listener
  $chatNew?.addEventListener('click', async () => {
    await createChatSession();
    clearChatLog();
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
        try {
          const d = new Date(iso.replace(' ', 'T') + 'Z');
          const now = new Date();
          return sameAmsDay(d, now) ? amsTimeString(d) : amsDateTimeString(d);
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
    if (!hasPermission('zabbix.ack')) {
      alert('You do not have permission to acknowledge Zabbix problems.');
      return;
    }
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
  function cleanupDeepSearchQuery(raw) {
    if (!raw) return raw;
    let value = raw.trim();
    value = value.replace(/^SYSTEMS\s*-\s*/i, '');
    value = value.replace(/\s*-\s*RAC$/i, '');
    return value.trim();
  }
  // Search page for selected Zabbix problem/host
  document.getElementById('zbx-search')?.addEventListener('click', (e) => {
    e.preventDefault();
    try {
      const feed = document.getElementById('zbx-feed');
      if (!feed) { alert('No list loaded.'); return; }
      const boxes = Array.from(feed.querySelectorAll('input.zbx-ev[type="checkbox"]'));
      const selected = boxes.filter(b => b.checked);
      if (selected.length === 0) { alert('Select one problem to search.'); return; }
      if (selected.length > 1) { alert('Select only one problem to search.'); return; }
      const cb = selected[0];
      // Get host name text from the same row (Host is the 5th column)
      let query = '';
      try {
        const tr = cb.closest('tr');
        if (tr && tr.children && tr.children.length >= 6) {
          const hostCell = tr.children[4];
          query = (hostCell?.innerText || '').trim();
          if (!query) {
            const probCell = tr.children[5];
            query = (probCell?.innerText || '').trim();
        }
      }
    } catch {}
    if (!query) { alert('Could not determine host/problem text to search.'); return; }
    const finalQuery = cleanupDeepSearchQuery(query) || query.trim();
    if (!finalQuery) { alert('Query resolved to an empty value.'); return; }
    // Navigate to Search and perform deep search
    const searchInput = document.getElementById('search-q');
    if (searchInput) searchInput.value = finalQuery;
    showPage('search');
    // Delay a tick to allow DOM to show Search before running
    setTimeout(() => { try { if (typeof runDeepSearch === 'function') runDeepSearch(); } catch {} }, 0);
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
      return `${amsTimeString(d)} ${amsTzShort(d)}`;
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
        try {
          const d = new Date(iso.replace(' ', 'T') + 'Z');
          return amsDateTimeString(d);
        } catch { return iso; }
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
    if (!hasPermission('zabbix.ack')) {
      alert('You do not have permission to acknowledge Zabbix problems.');
      return;
    }
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
    searchJira();
  });
  // Confluence helpers
  function ensureConfDefaults() {
    try {
      const saved = JSON.parse(localStorage.getItem('conf_filters') || '{}');
      if ($confQ && typeof saved.q === 'string') $confQ.value = saved.q;
      if ($confSpace && typeof saved.space === 'string') $confSpace.value = saved.space;
      if ($confType && typeof saved.ctype === 'string') $confType.value = saved.ctype;
      if ($confLabels && typeof saved.labels === 'string') $confLabels.value = saved.labels;
      if ($confUpdated && typeof saved.updated === 'string') $confUpdated.value = saved.updated;
      if ($confMax && typeof saved.max_results === 'number') $confMax.value = String(saved.max_results);
    } catch {}
  }
  function saveConfFilters(filters) {
    try { localStorage.setItem('conf_filters', JSON.stringify(filters)); } catch {}
  }
  function buildConfParams() {
    const params = new URLSearchParams();
    const q = ($confQ?.value || '').trim(); if (q) params.set('q', q);
    const space = ($confSpace?.value || '').trim(); if (space) params.set('space', space);
    const ctype = ($confType?.value || '').trim(); if (ctype) params.set('ctype', ctype);
    const labels = ($confLabels?.value || '').trim(); if (labels) params.set('labels', labels);
    const updated = ($confUpdated?.value || '').trim(); if (updated) params.set('updated', updated);
    const max = Number($confMax?.value || 50) || 50; params.set('max_results', String(max));
    saveConfFilters({ q, space, ctype, labels, updated, max_results: max });
    try { localStorage.setItem('conf_last_query', params.toString()); } catch {}
    return params.toString();
  }
  async function searchConfluence(showSpinner = true) {
    if ($confResults && showSpinner) $confResults.textContent = 'Searching…';
    // Check configuration
    try {
      const chk = await fetch(`${API_BASE}/confluence/config`);
      const cfg = await chk.json().catch(() => ({}));
      if (!cfg?.configured) { if ($confResults) $confResults.textContent = 'Confluence not configured (ATLASSIAN_* missing).'; return; }
    } catch {}
    const qs = buildConfParams();
    const url = `${API_BASE}/confluence/search?${qs}`;
    try {
      const res = await fetch(url);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { if ($confResults) $confResults.textContent = data?.detail || `${res.status} ${res.statusText}`; return; }
      let items = Array.isArray(data?.results) ? data.results.slice() : [];
      try { items.sort((a,b) => (new Date(b.updated||0)) - (new Date(a.updated||0))); } catch {}
      if (!items.length) { if ($confResults) $confResults.textContent = 'No results.'; return; }
      const table = document.createElement('table'); table.className = 'zbx-table';
      const thead = document.createElement('thead'); thead.innerHTML = '<tr><th>Titel</th><th>Space</th><th>Type</th><th>Updated</th></tr>';
      const tbody = document.createElement('tbody');
      const fmtTime = (iso) => { if (!iso) return ''; try { return amsDateTimeString(new Date(iso)); } catch { return iso; } };
      for (const it of items) {
        const tr = document.createElement('tr');
        const tdTitle = document.createElement('td');
        if (it.url) { const a = document.createElement('a'); a.href = it.url; a.textContent = it.title || '(untitled)'; a.target = '_blank'; a.rel = 'noopener'; tdTitle.appendChild(a); } else { tdTitle.textContent = it.title || '(untitled)'; }
        const tdSpace = document.createElement('td'); tdSpace.textContent = it.space || '';
        const tdType = document.createElement('td'); tdType.textContent = it.type || '';
        const tdUpd = document.createElement('td'); tdUpd.textContent = fmtTime(it.updated);
        tr.appendChild(tdTitle); tr.appendChild(tdSpace); tr.appendChild(tdType); tr.appendChild(tdUpd);
        tbody.appendChild(tr);
      }
      table.appendChild(thead); table.appendChild(tbody);
      if ($confResults) { $confResults.innerHTML = ''; $confResults.appendChild(table); }
    } catch (e) {
      if ($confResults) $confResults.textContent = `Error: ${e?.message || e}`;
    }
  }
  document.getElementById('conf-search')?.addEventListener('click', () => searchConfluence());
  document.getElementById('conf-reset')?.addEventListener('click', () => {
    if ($confQ) $confQ.value = '';
    if ($confSpace) $confSpace.value = '';
    if ($confType) $confType.value = 'page';
    if ($confLabels) $confLabels.value = '';
    if ($confUpdated) $confUpdated.value = '';
    if ($confMax) $confMax.value = '50';
    saveConfFilters({ q: '', space: '', ctype: 'page', labels: '', updated: '', max_results: 50 });
    searchConfluence();
  });
  $confQ?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); searchConfluence(); } });
  $confSpace?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); searchConfluence(); } });
  $confLabels?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); searchConfluence(); } });

  // NetBox search helpers
  const $nbQ = document.getElementById('nb-q');
  const $nbDs = document.getElementById('nb-ds');
  const $nbMax = document.getElementById('nb-max');
  const $nbResults = document.getElementById('nb-results');
  let NB_BASE = '';
  function ensureNbDefaults() {
    try {
      const saved = JSON.parse(localStorage.getItem('nb_filters') || '{}');
      if ($nbQ && typeof saved.q === 'string') $nbQ.value = saved.q;
      if ($nbDs && typeof saved.dataset === 'string') $nbDs.value = saved.dataset;
      if ($nbMax && typeof saved.max_results === 'number') $nbMax.value = String(saved.max_results);
    } catch {}
    // Load NetBox base URL once
    (async () => {
      try { const r = await fetch(`${API_BASE}/netbox/config`); const d = await r.json(); NB_BASE = (d && d.base_url) || ''; } catch {}
    })();
  }
  function saveNbFilters(filters) {
    try { localStorage.setItem('nb_filters', JSON.stringify(filters)); } catch {}
  }
  function buildNbParams() {
    const q = ($nbQ?.value || '').trim();
    const ds = ($nbDs?.value || 'all');
    const max = Number($nbMax?.value || 50) || 50;
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    params.set('dataset', ds);
    params.set('limit', String(max));
    saveNbFilters({ q, dataset: ds, max_results: max });
    try { localStorage.setItem('nb_last_query', params.toString()); } catch {}
    return params.toString();
  }
  async function searchNetbox(showSpinner = true) {
    if ($nbResults && showSpinner) $nbResults.textContent = 'Searching…';
    try {
      const qs = buildNbParams();
      const res = await fetch(`${API_BASE}/netbox/search?${qs}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { if ($nbResults) $nbResults.textContent = data?.detail || `${res.status} ${res.statusText}`; return; }
      let rows = Array.isArray(data?.rows) ? data.rows.slice() : [];
      try { rows.sort((a,b) => (new Date(b['Updated']||0)) - (new Date(a['Updated']||0))); } catch {}
      if (!rows.length) { if ($nbResults) $nbResults.textContent = 'No results.'; return; }
      // Determine columns: prefer /column-order intersection if available
      let columns = [];
      try {
        const pref = await fetch(`${API_BASE}/column-order`);
        const order = await pref.json();
        const keys = Object.keys(rows[0] || {});
        if (Array.isArray(order) && order.length) {
          columns = order.filter(c => keys.includes(c));
          for (const k of keys) if (!columns.includes(k)) columns.push(k);
        } else {
          columns = keys;
        }
      } catch {
        columns = Object.keys(rows[0] || {});
      }
      // Hide internal helper fields
      columns = columns.filter(c => String(c).toLowerCase() !== 'ui_path');
      // Ensure Updated column is visible and placed near the end
      const updIdx = columns.findIndex(c => String(c).toLowerCase() === 'updated');
      if (updIdx === -1) {
        // If rows contain Updated key but it didn't make it into columns, add it
        if (rows.length && Object.prototype.hasOwnProperty.call(rows[0], 'Updated')) columns.push('Updated');
      } else {
        // Move Updated near the end (before the very last column to keep layout stable)
        const [u] = columns.splice(updIdx, 1);
        columns.push(u);
      }
      const table = document.createElement('table'); table.className = 'zbx-table';
      const thead = document.createElement('thead');
      thead.innerHTML = '<tr>' + columns.map(c => `<th>${c}</th>`).join('') + '</tr>';
      const tbody = document.createElement('tbody');
      const nameKey = (() => {
        const keys = columns.map(c => String(c).toLowerCase());
        const cand = ['name', 'device', 'vm name', 'hostname'];
        for (const c of cand) { const i = keys.indexOf(c); if (i !== -1) return columns[i]; }
        return columns[0] || '';
      })();
      for (const r of rows) {
        const tr = document.createElement('tr');
        for (const c of columns) {
          const td = document.createElement('td');
          const v = r[c];
          if (String(c).toLowerCase() === 'updated') {
            // Pretty print timestamp
            try { td.textContent = v ? amsDateTimeString(new Date(v)) : ''; }
            catch { td.textContent = v == null ? '' : String(v); }
          } else if (NB_BASE && c === nameKey && v != null && String(v).trim()) {
            const a = document.createElement('a');
            // Prefer direct object path when available from API
            const uiPath = r && typeof r === 'object' ? (r.ui_path || r.UI_PATH || r.UiPath) : '';
            let href = '';
            if (uiPath && typeof uiPath === 'string') {
              href = NB_BASE.replace(/\/$/, '') + uiPath;
            } else {
              // Fallback to NetBox search
              const ds = ($nbDs?.value || 'all');
              const q = encodeURIComponent(String(v));
              href = NB_BASE.replace(/\/$/, '') + '/search/?q=' + q;
              if (ds === 'devices') href = NB_BASE.replace(/\/$/, '') + '/dcim/devices/?q=' + q;
              if (ds === 'vms') href = NB_BASE.replace(/\/$/, '') + '/virtualization/virtual-machines/?q=' + q;
            }
            a.href = href; a.target = '_blank'; a.rel = 'noopener';
            a.textContent = String(v);
            td.appendChild(a);
          } else {
            td.textContent = (v == null ? '' : String(v));
          }
          tr.appendChild(td);
        }
        tbody.appendChild(tr);
      }
      table.appendChild(thead); table.appendChild(tbody);
      if ($nbResults) { $nbResults.innerHTML = ''; $nbResults.appendChild(table); }
    } catch (e) {
      if ($nbResults) $nbResults.textContent = `Error: ${e?.message || e}`;
    }
  }
  document.getElementById('nb-search')?.addEventListener('click', () => searchNetbox());
  document.getElementById('nb-reset')?.addEventListener('click', () => {
    if ($nbQ) $nbQ.value = '';
    if ($nbDs) $nbDs.value = 'all';
    if ($nbMax) $nbMax.value = '50';
    saveNbFilters({ q: '', dataset: 'all', max_results: 50 });
    searchNetbox();
  });
  $nbQ?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); searchNetbox(); } });

  // Search aggregator
  const $searchQ = document.getElementById('search-q');
  const $searchResults = document.getElementById('search-results');
  const $searchZ = document.getElementById('search-zlimit');
  const $searchJ = document.getElementById('search-jlimit');
  const $searchC = document.getElementById('search-climit');
  const $searchV = document.getElementById('search-vlimit');
  let searchCommvaultMetricsSeq = 0;

  function createCommvaultMetricCard(label, value, meta) {
    const card = document.createElement('div');
    card.className = 'commvault-server-card';
    const lbl = document.createElement('span'); lbl.className = 'label'; lbl.textContent = label;
    const val = document.createElement('span'); val.className = 'value'; val.textContent = value;
    card.append(lbl, val);
    if (meta) {
      const metaNode = document.createElement('span'); metaNode.className = 'meta'; metaNode.textContent = meta;
      card.append(metaNode);
    }
    return card;
  }

  async function loadSearchCommvaultMetrics(query, container) {
    if (!container) return;
    const existing = container.querySelector('.search-commvault-metrics-panel');
    if (existing) existing.remove();

    const trimmed = (query || '').trim();
    if (!trimmed) return;

    const seq = ++searchCommvaultMetricsSeq;
    const params = new URLSearchParams({
      client: trimmed,
      job_limit: '0',
      since_hours: '0',
      retained_only: 'true',
    });

    try {
      const res = await fetch(`${API_BASE}/commvault/servers/summary?${params.toString()}`);
      if (seq !== searchCommvaultMetricsSeq) return;
      if (!res.ok) return;
      const data = await res.json().catch(() => null);
      if (!data || !data.stats || !Array.isArray(data.jobs)) return;

      const stats = data.stats || {};
      const metrics = data.job_metrics || {};
      const summary = data.client || {};

      const jobCount = Number(stats.job_count) || 0;
      const windowHours = Number(metrics.window_hours);
      const windowText = Number.isFinite(windowHours) && windowHours > 0 ? `${windowHours}h window` : 'All time window';
      const retainedCount = Number(stats.retained_jobs) || 0;
      const retainedText = `${retainedCount.toLocaleString()} retained job(s)`;
      const savingsText = `Saved ${formatCommvaultBytes(stats.savings_bytes)}`;
      const ratioMeta = stats.average_reduction_ratio_text ? `≈ ${stats.average_reduction_ratio_text}` : '';
      const fetchedAt = metrics.fetched_at ? formatTimestamp(metrics.fetched_at) : '';

      const metricsWrap = document.createElement('div');
      metricsWrap.className = 'commvault-server-metrics';
      metricsWrap.append(
        createCommvaultMetricCard('Restore points', jobCount.toLocaleString(), windowText),
        createCommvaultMetricCard('Application size', formatCommvaultBytes(stats.total_application_bytes), retainedText),
        createCommvaultMetricCard('Media size', formatCommvaultBytes(stats.total_media_bytes), savingsText),
        createCommvaultMetricCard('Average reduction', formatCommvaultPercent(stats.average_savings_percent), ratioMeta),
      );

      const panel = document.createElement('div');
      panel.className = 'panel search-commvault-metrics-panel';
      const header = document.createElement('div');
      header.className = 'search-commvault-metrics-header';
      const title = document.createElement('h3');
      const name = summary.display_name || summary.name || (summary.client_id != null ? `Client ${summary.client_id}` : 'Commvault');
      title.textContent = `Commvault — ${name}`;
      header.append(title);
      if (fetchedAt) {
        const meta = document.createElement('span'); meta.className = 'search-commvault-metrics-meta'; meta.textContent = `Cached ${fetchedAt}`;
        header.append(meta);
      }
      panel.append(header, metricsWrap);

      container.prepend(panel);
    } catch (err) {
      if (seq !== searchCommvaultMetricsSeq) return;
      console.warn('Commvault metrics lookup failed', err);
    }
  }

  async function runDeepSearch() {
    if ($searchResults) $searchResults.textContent = 'Searching…';
    const q = ($searchQ?.value || '').trim();
    if (!q) { if ($searchResults) $searchResults.textContent = 'Enter a search term.'; return; }
    try {
      if (!NB_BASE) {
        try { const r0 = await fetch(`${API_BASE}/netbox/config`); const d0 = await r0.json(); NB_BASE = (d0 && d0.base_url) || ''; } catch {}
      }
      // Build limits (defaults 10; 0 means no limit; NetBox unlimited server-side)
      const zl = Number($searchZ?.value || 10) || 10;
      const jl = Number($searchJ?.value || 10) || 10;
      const cl = Number($searchC?.value || 10) || 10;
      const vl = Number($searchV?.value || 10) || 10;
      const qs = new URLSearchParams({ q, zlimit: String(zl), jlimit: String(jl), climit: String(cl) });
      qs.set('vlimit', String(vl));
      const res = await fetch(`${API_BASE}/search/aggregate?${qs.toString()}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { if ($searchResults) $searchResults.textContent = data?.detail || `${res.status} ${res.statusText}`; return; }
      const wrap = document.createElement('div');
      function section(title, contentNode) { const d = document.createElement('div'); d.className = 'panel'; const h = document.createElement('h3'); h.textContent = title; d.appendChild(h); d.appendChild(contentNode); return d; }
      // Zabbix
      const z = data?.zabbix || {}; const znode = document.createElement('div'); const zlist = document.createElement('ul'); zlist.style.paddingLeft = '18px';
      (z?.active || []).forEach(it => {
        const li = document.createElement('li');
        const st = it.status || (it.resolved ? 'RESOLVED' : 'ACTIVE');
        const prefix = `[${it.clock || ''}] [${st}]` + (it.severity != null ? ` sev=${it.severity}` : '');
        const a = document.createElement('a');
        const href = it.problem_url || it.host_url || '';
        if (href) { a.href = href; a.target = '_blank'; a.rel = 'noopener'; a.textContent = ` ${it.name || ''}`; li.textContent = prefix + ' '; li.appendChild(a); }
        else { li.textContent = `${prefix} ${it.name || ''}`; }
        zlist.appendChild(li);
      });
      (z?.historical || []).slice(0, 20).forEach(it => {
        const li = document.createElement('li');
        const st = it.status || (String(it.value||'')==='1' ? 'PROBLEM' : 'OK');
        const prefix = `[${it.clock || ''}] [${st}]`;
        const a = document.createElement('a');
        const href = it.event_url || it.host_url || '';
        if (href) { a.href = href; a.target = '_blank'; a.rel = 'noopener'; a.textContent = ` ${it.name || ''}`; li.textContent = prefix + ' '; li.appendChild(a); }
        else { li.textContent = `${prefix} ${it.name || ''}`; }
        zlist.appendChild(li);
      });
      if (!zlist.childNodes.length) znode.textContent = 'No Zabbix data.'; else znode.appendChild(zlist);
      wrap.appendChild(section('Zabbix', znode));
      // Jira
      const j = data?.jira || {}; const jnode = document.createElement('div');
      if (Array.isArray(j.issues) && j.issues.length) {
        const ul = document.createElement('ul'); ul.style.paddingLeft = '18px';
        const issues = j.issues.slice();
        try { issues.sort((a,b) => (new Date(b.updated||0)) - (new Date(a.updated||0))); } catch {}
        issues.forEach(it => {
          const li = document.createElement('li');
          const a = document.createElement('a'); a.href = it.url || '#'; a.target = '_blank'; a.rel = 'noopener'; a.textContent = `${it.key || ''} — ${it.summary || ''}`;
          const ts = (() => { try { return it.updated ? amsDateTimeString(new Date(it.updated)) : ''; } catch { return it.updated || ''; } })();
          li.textContent = ts ? `[${ts}] ` : '';
          li.appendChild(a);
          ul.appendChild(li);
        });
        jnode.appendChild(ul);
      } else { jnode.textContent = 'No Jira data.'; }
      wrap.appendChild(section('Jira', jnode));
      // Confluence
      const c = data?.confluence || {}; const cnode = document.createElement('div');
      if (Array.isArray(c.results) && c.results.length) {
        const ul = document.createElement('ul'); ul.style.paddingLeft = '18px';
        const pages = c.results.slice();
        try { pages.sort((a,b) => (new Date(b.updated||0)) - (new Date(a.updated||0))); } catch {}
        pages.forEach(it => {
          const li = document.createElement('li');
          const a = document.createElement('a'); a.href = it.url || '#'; a.target = '_blank'; a.rel = 'noopener'; a.textContent = it.title || '';
          const ts = (() => { try { return it.updated ? amsDateTimeString(new Date(it.updated)) : ''; } catch { return it.updated || ''; } })();
          li.textContent = ts ? `[${ts}] ` : '';
          li.appendChild(a);
          ul.appendChild(li);
        });
        cnode.appendChild(ul);
      } else { cnode.textContent = 'No Confluence data.'; }
      wrap.appendChild(section('Confluence', cnode));
      // vCenter
      const vcenter = data?.vcenter || {};
      const vnode = document.createElement('div');
      if (vcenter.permitted === false) {
        vnode.textContent = 'vCenter results require additional permissions.';
      } else {
        const vItems = Array.isArray(vcenter.items) ? vcenter.items : [];
        if (vItems.length) {
          const ul = document.createElement('ul');
          ul.style.paddingLeft = '18px';
          vItems.forEach((vm) => {
            const li = document.createElement('li');
            const title = document.createElement('div');
            const nameLink = document.createElement('a');
            nameLink.textContent = vm.name || vm.id || 'Virtual Machine';
            if (vm.detail_url) {
              nameLink.href = vm.detail_url;
              nameLink.target = '_blank';
              nameLink.rel = 'noopener';
            }
            title.appendChild(nameLink);
            if (vm.power_state) {
              const badge = document.createElement('span');
              badge.className = 'badge';
              badge.style.marginLeft = '8px';
              badge.style.fontSize = '11px';
              badge.style.padding = '2px 6px';
              badge.textContent = vm.power_state;
              title.appendChild(badge);
            }
            li.appendChild(title);
            const metaParts = [];
            if (vm.config_name) metaParts.push(vm.config_name);
            if (vm.guest_host_name) metaParts.push(vm.guest_host_name);
            if (vm.guest_ip_address) metaParts.push(vm.guest_ip_address);
            if (!vm.guest_ip_address && Array.isArray(vm.ip_addresses) && vm.ip_addresses.length) {
              metaParts.push(vm.ip_addresses.join(', '));
            }
            if (vm.guest_os) metaParts.push(vm.guest_os);
            const metaLine = document.createElement('div');
            metaLine.className = 'muted';
            metaLine.textContent = metaParts.filter(Boolean).join(' • ') || 'No additional metadata.';
            if (vm.vcenter_url) {
              const ext = document.createElement('a');
              ext.href = vm.vcenter_url;
              ext.target = '_blank';
              ext.rel = 'noopener';
              ext.textContent = 'Open in vCenter';
              ext.style.marginLeft = '8px';
              metaLine.append(' ');
              metaLine.appendChild(ext);
            }
            li.appendChild(metaLine);
            ul.appendChild(li);
          });
          vnode.appendChild(ul);
          const rawTotal = Number(vcenter.total);
          const totalCount = Number.isFinite(rawTotal) && rawTotal > 0 ? rawTotal : vItems.length;
          if (vcenter.has_more || totalCount > vItems.length) {
            const note = document.createElement('div');
            note.className = 'muted';
            note.style.marginTop = '6px';
            note.textContent = `Showing ${vItems.length.toLocaleString()} of ${totalCount.toLocaleString()} match(es). Refine your search to narrow further.`;
            vnode.appendChild(note);
          }
        } else if (Array.isArray(vcenter.errors) && vcenter.errors.length) {
          vnode.textContent = 'Unable to load vCenter data.';
        } else {
          vnode.textContent = 'No vCenter data.';
        }
        if (Array.isArray(vcenter.errors) && vcenter.errors.length) {
          const err = document.createElement('div');
          err.className = 'muted';
          err.style.marginTop = '6px';
          err.textContent = `Issues while fetching vCenter data: ${vcenter.errors.join('; ')}`;
          vnode.appendChild(err);
        }
      }
      wrap.appendChild(section('vCenter', vnode));
      // NetBox
      const n = data?.netbox || {}; const nnode = document.createElement('div');
      if (Array.isArray(n.items) && n.items.length) {
        const ul = document.createElement('ul'); ul.style.paddingLeft = '18px';
        const items = n.items.slice();
        try { items.sort((a,b) => (new Date(b.Updated||0)) - (new Date(a.Updated||0))); } catch {}
        items.forEach(it => {
          const li = document.createElement('li');
          const a = document.createElement('a'); const href = (NB_BASE ? NB_BASE.replace(/\/$/, '') + (it.ui_path || '') : '#'); a.href = href; a.target = '_blank'; a.rel = 'noopener'; a.textContent = `${it.Name || ''} ${it.Type ? '('+it.Type+')' : ''}`;
          const ts = (() => { try { return it.Updated ? amsDateTimeString(new Date(it.Updated)) : ''; } catch { return it.Updated || ''; } })();
          li.textContent = ts ? `[${ts}] ` : '';
          li.appendChild(a);
          ul.appendChild(li);
        });
        nnode.appendChild(ul);
      } else { nnode.textContent = 'No NetBox data.'; }
      wrap.appendChild(section('NetBox', nnode));
      if ($searchResults) {
        $searchResults.innerHTML = '';
        $searchResults.appendChild(wrap);
        loadSearchCommvaultMetrics(q, wrap);
      }
    } catch (e) { if ($searchResults) $searchResults.textContent = `Error: ${e?.message || e}`; }
  }
  document.getElementById('search-run')?.addEventListener('click', () => runDeepSearch());
  $searchQ?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); runDeepSearch(); } });

  // Jira helpers
  function ensureJiraDefaults() {
    try {
      const saved = JSON.parse(localStorage.getItem('jira_filters') || '{}');
      if ($jiraQ && typeof saved.q === 'string') $jiraQ.value = saved.q;
      if ($jiraProject && typeof saved.project === 'string') $jiraProject.value = saved.project;
      if ($jiraStatus && typeof saved.status === 'string') $jiraStatus.value = saved.status;
      if ($jiraAssignee && typeof saved.assignee === 'string') $jiraAssignee.value = saved.assignee;
      if ($jiraPriority && typeof saved.priority === 'string') $jiraPriority.value = saved.priority;
      if ($jiraType && typeof saved.issuetype === 'string') $jiraType.value = saved.issuetype;
      if ($jiraTeam && typeof saved.team === 'string') $jiraTeam.value = saved.team;
      if ($jiraUpdated && typeof saved.updated === 'string') $jiraUpdated.value = saved.updated;
      if ($jiraOpen && typeof saved.only_open !== 'undefined') $jiraOpen.checked = !!saved.only_open;
      if ($jiraMax && typeof saved.max_results === 'number') $jiraMax.value = String(saved.max_results);
      // Default Team when nothing saved
      if ($jiraTeam && (!$jiraTeam.value || !$jiraTeam.value.trim())) $jiraTeam.value = 'Systems Infrastructure';
    } catch {}
  }
  function saveJiraFilters(filters) {
    try { localStorage.setItem('jira_filters', JSON.stringify(filters)); } catch {}
  }
  function buildJiraParams() {
    const params = new URLSearchParams();
    const q = ($jiraQ?.value || '').trim(); if (q) params.set('q', q);
    const project = ($jiraProject?.value || '').trim(); if (project) params.set('project', project);
    const status = ($jiraStatus?.value || '').trim(); if (status) params.set('status', status);
    const assignee = ($jiraAssignee?.value || '').trim(); if (assignee) params.set('assignee', assignee);
    const priority = ($jiraPriority?.value || '').trim(); if (priority) params.set('priority', priority);
    const issuetype = ($jiraType?.value || '').trim(); if (issuetype) params.set('issuetype', issuetype);
    const team = ($jiraTeam?.value || '').trim(); if (team) params.set('team', team);
    const updated = ($jiraUpdated?.value || '').trim(); if (updated) params.set('updated', updated);
    const onlyOpen = $jiraOpen ? ($jiraOpen.checked ? '1' : '0') : '1'; params.set('only_open', onlyOpen);
    const max = Number($jiraMax?.value || 50) || 50; params.set('max_results', String(max));
    saveJiraFilters({ q, project, status, assignee, priority, issuetype, team, updated, only_open: onlyOpen === '1', max_results: max });
    try { localStorage.setItem('jira_last_query', params.toString()); } catch {}
    return params.toString();
  }
  function jiraConfiguredBadge(ok) {
    if (!$jiraResults) return;
    const div = document.createElement('div');
    div.className = 'muted';
    div.style.margin = '4px 0 8px';
    div.textContent = ok ? '' : 'Jira not configured: set ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN in .env.';
    return div;
  }
  async function searchJira(showSpinner = true) {
    if (!$jiraResults) return;
    // Check configuration
    try {
      const chk = await fetch(`${API_BASE}/jira/config`);
      const cfg = await chk.json().catch(() => ({}));
      if (!cfg?.configured) {
        $jiraResults.textContent = 'Jira not configured. Add ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN to .env.';
        return;
      }
    } catch {}
    const qs = buildJiraParams();
    const url = `${API_BASE}/jira/search?${qs}`;
    if (showSpinner) $jiraResults.textContent = 'Searching…';
    try {
      const res = await fetch(url);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { $jiraResults.textContent = data?.detail || `${res.status} ${res.statusText}`; return; }
      let issues = Array.isArray(data?.issues) ? data.issues.slice() : [];
      try { issues.sort((a,b) => (new Date(b.updated||0)) - (new Date(a.updated||0))); } catch {}
      if (!issues.length) { $jiraResults.textContent = 'No results.'; return; }
      // Build table
      const table = document.createElement('table');
      table.className = 'zbx-table';
      const thead = document.createElement('thead');
      thead.innerHTML = '<tr><th>Key</th><th>Summary</th><th>Status</th><th>Assignee</th><th>Priority</th><th>Type</th><th>Project</th><th>Updated</th></tr>';
      table.appendChild(thead);
      const tbody = document.createElement('tbody');
      const fmtTime = (iso) => { if (!iso) return ''; try { const d = new Date(iso); return amsDateTimeString(d); } catch { return iso; } };
      for (const it of issues) {
        const tr = document.createElement('tr');
        const tdKey = document.createElement('td');
        if (it.url) { const a = document.createElement('a'); a.href = it.url; a.textContent = it.key; a.target = '_blank'; a.rel = 'noopener'; tdKey.appendChild(a); } else { tdKey.textContent = it.key || ''; }
        const tdSummary = document.createElement('td'); tdSummary.textContent = it.summary || '';
        const tdStatus = document.createElement('td'); tdStatus.textContent = it.status || '';
        const tdAssignee = document.createElement('td'); tdAssignee.textContent = it.assignee || '';
        const tdPriority = document.createElement('td'); tdPriority.textContent = it.priority || '';
        const tdType = document.createElement('td'); tdType.textContent = it.issuetype || '';
        const tdProj = document.createElement('td'); tdProj.textContent = it.project || '';
        const tdUpd = document.createElement('td'); tdUpd.textContent = fmtTime(it.updated);
        tr.appendChild(tdKey); tr.appendChild(tdSummary); tr.appendChild(tdStatus); tr.appendChild(tdAssignee); tr.appendChild(tdPriority); tr.appendChild(tdType); tr.appendChild(tdProj); tr.appendChild(tdUpd);
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      $jiraResults.innerHTML = '';
      $jiraResults.appendChild(table);
    } catch (e) {
      $jiraResults.textContent = `Error: ${e?.message || e}`;
    }
  }
  document.getElementById('jira-search')?.addEventListener('click', () => searchJira());
  document.getElementById('jira-reset')?.addEventListener('click', () => {
    if ($jiraQ) $jiraQ.value = '';
    if ($jiraProject) $jiraProject.value = '';
    if ($jiraStatus) $jiraStatus.value = '';
    if ($jiraAssignee) $jiraAssignee.value = '';
    if ($jiraPriority) $jiraPriority.value = '';
    if ($jiraType) $jiraType.value = '';
    if ($jiraUpdated) $jiraUpdated.value = '';
    if ($jiraOpen) $jiraOpen.checked = true;
    if ($jiraMax) $jiraMax.value = '50';
    saveJiraFilters({ q: '', project: '', status: '', assignee: '', priority: '', issuetype: '', updated: '', only_open: true, max_results: 50 });
    searchJira();
  });
  $jiraQ?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); searchJira(); } });
  $jiraProject?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); searchJira(); } });
  $jiraStatus?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); searchJira(); } });
  $jiraAssignee?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); searchJira(); } });
  $jiraPriority?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); searchJira(); } });
  $jiraType?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); searchJira(); } });
  $jiraTeam?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); searchJira(); } });

  // Init
  // Ensure fields panel is closed on load
  if ($fieldsPanel) $fieldsPanel.hidden = true;
  populateAccountForms();
  loadCurrentUser();
  // Use default dataset (persisted state handles columns/filters/density)
  // Set initial dataset tab active
  $dsTabs?.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-ds') === dataset));
  // Initial page from hash
  // Prepare chat defaults before showing the page (so UI sensible)
  setupChatPrefListeners();
  loadChatPrefs();
  loadChatDefaults();
  loadChatConfig();
  const initialPage = parseHashPage();
  persistActivePage(initialPage);
  if (typeof setupChatSidebarTabs === 'function') {
    setupChatSidebarTabs();
  }
  // Clean up any legacy ?view=... from the URL at startup
  try { updateURLDebounced(); } catch {}
  if (initialPage === 'chat') {
    fetchChatSessions();
    setupAutoResize();
    setupSuggestionButtons();
  }
  loadTools();
  showPage(initialPage);
  // Ensure Export dataset loads immediately on first load
  if (initialPage === 'export') {
    try { fetchData(); } catch {}
  }
  // When switching to chat, ensure session and history are loaded
  

  // ---------------------------
  // User Management Event Listeners
  // ---------------------------
  
  // User list refresh and include inactive toggle
  $adminUserRefresh?.addEventListener('click', () => {
    loadAdminUsers($adminUserIncludeInactive?.checked).catch(() => {});
  });
  
  $adminUserIncludeInactive?.addEventListener('change', () => {
    loadAdminUsers($adminUserIncludeInactive.checked).catch(() => {});
  });
  
  // Create new user button
  $adminUserCreate?.addEventListener('click', () => {
    showAdminUserCreate();
  });
  
  // User form submission
  $adminUserForm?.addEventListener('submit', (e) => {
    e.preventDefault();
    saveAdminUser();
  });
  
  // Password form submission
  $adminUserPasswordForm?.addEventListener('submit', (e) => {
    e.preventDefault();
    setAdminUserPassword();
  });
  
  // Delete user button
  $adminUserDelete?.addEventListener('click', () => {
    deleteAdminUser();
  });
  
  // Global API key management
  $adminGlobalAdd?.addEventListener('click', () => {
    showGlobalApiKeyForm();
  });
  
  $adminGlobalForm?.addEventListener('submit', (e) => {
    e.preventDefault();
    saveGlobalApiKey();
  });
  
  $adminGlobalCancel?.addEventListener('click', () => {
    hideGlobalApiKeyForm();
  });

  $adminVCenterAdd?.addEventListener('click', () => {
    openAdminVCenterForm();
  });

  $adminVCenterForm?.addEventListener('submit', (event) => {
    event.preventDefault();
    saveAdminVCenter();
  });

  $adminVCenterCancel?.addEventListener('click', () => {
    closeAdminVCenterForm();
  });

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
  // ---------------------------
  // Token Usage Monitoring
  // ---------------------------
  
  const monitoringState = {
    tokenUsage: null,
    queueStatus: null,
    rateLimits: null,
    autoRefresh: false,
    refreshInterval: null,
  };

  async function loadTokenUsageStats(hours = 24) {
    try {
      const res = await fetch(`${API_BASE}/monitoring/token-usage?hours=${hours}`);
      if (!res.ok) return null;
      const data = await res.json();
      monitoringState.tokenUsage = data;
      return data;
    } catch (err) {
      console.error('Failed to load token usage stats', err);
      return null;
    }
  }

  async function loadQueueStatus() {
    try {
      const res = await fetch(`${API_BASE}/monitoring/queue-status`);
      if (!res.ok) return null;
      const data = await res.json();
      monitoringState.queueStatus = data;
      return data;
    } catch (err) {
      console.error('Failed to load queue status', err);
      return null;
    }
  }

  async function loadRateLimitStatus() {
    try {
      const res = await fetch(`${API_BASE}/monitoring/rate-limits`);
      if (!res.ok) return null;
      const data = await res.json();
      monitoringState.rateLimits = data;
      return data;
    } catch (err) {
      console.error('Failed to load rate limit status', err);
      return null;
    }
  }

  async function loadPerformanceMetrics(hours = 24) {
    try {
      const res = await fetch(`${API_BASE}/monitoring/performance?hours=${hours}`);
      if (!res.ok) return null;
      return await res.json();
    } catch (err) {
      console.error('Failed to load performance metrics', err);
      return null;
    }
  }

  function renderTokenUsageDashboard() {
    const container = document.getElementById('token-usage-dashboard');
    if (!container || !monitoringState.tokenUsage) return;

    const usage = monitoringState.tokenUsage.token_usage_24h || {};
    const rateLimits = monitoringState.rateLimits?.rate_limits || {};
    
    container.innerHTML = `
      <div class="token-usage-header">
        <h3 class="token-usage-title">Token Usage & Performance</h3>
        <button class="token-usage-refresh" onclick="refreshMonitoringData()">Refresh</button>
      </div>
      
      <div class="token-metrics-grid">
        <div class="token-metric-card">
          <div class="token-metric-value">${(usage.total_tokens || 0).toLocaleString()}</div>
          <div class="token-metric-label">Total Tokens</div>
        </div>
        <div class="token-metric-card">
          <div class="token-metric-value">$${(usage.total_cost_usd || 0).toFixed(4)}</div>
          <div class="token-metric-label">Total Cost</div>
        </div>
        <div class="token-metric-card">
          <div class="token-metric-value">${usage.request_count || 0}</div>
          <div class="token-metric-label">Requests</div>
        </div>
        <div class="token-metric-card">
          <div class="token-metric-value">${Math.round(usage.average_tokens_per_request || 0)}</div>
          <div class="token-metric-label">Avg Tokens/Req</div>
        </div>
      </div>
      
      <div class="rate-limit-status ${getRateLimitStatusClass(rateLimits)}">
        <div class="rate-limit-indicator"></div>
        <span>${getRateLimitStatusText(rateLimits)}</span>
      </div>
      
      <div class="performance-chart">
        <span>Performance chart placeholder</span>
      </div>
      
      <div class="cost-summary">
        <span class="cost-period">Last 24 hours</span>
        <span class="cost-amount">$${(usage.total_cost_usd || 0).toFixed(4)}</span>
      </div>
    `;
  }

  function getRateLimitStatusClass(rateLimits) {
    if (rateLimits.stabilization_active) return 'error';
    if (rateLimits.request_utilization_minute > 80 || rateLimits.token_utilization_minute > 80) return 'warning';
    return 'healthy';
  }

  function getRateLimitStatusText(rateLimits) {
    if (rateLimits.stabilization_active) {
      return 'Rate limiting active - requests temporarily reduced';
    }
    
    const reqUtil = Math.round(rateLimits.request_utilization_minute || 0);
    const tokenUtil = Math.round(rateLimits.token_utilization_minute || 0);
    
    if (reqUtil > 80 || tokenUtil > 80) {
      return `High utilization - Requests: ${reqUtil}%, Tokens: ${tokenUtil}%`;
    }
    
    return `Healthy - Requests: ${reqUtil}%, Tokens: ${tokenUtil}%`;
  }

  function renderQueueStatus() {
    const container = document.getElementById('queue-status');
    if (!container || !monitoringState.queueStatus) return;

    const queue = monitoringState.queueStatus.queue || {};
    const queueSize = queue.queue_size || 0;
    const processing = queue.processing_count || 0;
    
    let statusClass = 'idle';
    let statusText = 'Idle';
    
    if (processing > 0) {
      statusClass = 'processing';
      statusText = `Processing ${processing} request${processing > 1 ? 's' : ''}`;
    } else if (queueSize > 0) {
      statusClass = 'waiting';
      statusText = `${queueSize} request${queueSize > 1 ? 's' : ''} queued`;
    }

    container.innerHTML = `
      <div class="queue-status">
        <div class="queue-indicator ${statusClass}"></div>
        <span>${statusText}</span>
      </div>
    `;
  }

  async function refreshMonitoringData() {
    try {
      await Promise.all([
        loadTokenUsageStats(),
        loadQueueStatus(),
        loadRateLimitStatus(),
      ]);
      
      renderTokenUsageDashboard();
      renderQueueStatus();
      
    } catch (err) {
      console.error('Failed to refresh monitoring data', err);
    }
  }

  function startMonitoringAutoRefresh() {
    if (monitoringState.refreshInterval) {
      clearInterval(monitoringState.refreshInterval);
    }
    
    monitoringState.autoRefresh = true;
  // Handle monitoring dashboard toggle
  const $chatShowMonitoring = document.getElementById('chat-show-monitoring');
  $chatShowMonitoring?.addEventListener('change', () => {
    const show = $chatShowMonitoring.checked;
    const dashboard = document.getElementById('token-usage-dashboard');
    const queueStatus = document.getElementById('queue-status');
    
    if (dashboard) dashboard.style.display = show ? 'block' : 'none';
    if (queueStatus) queueStatus.style.display = show ? 'block' : 'none';
    
    if (show) {
      refreshMonitoringData();
    }
    
    try {
      localStorage.setItem('chat_show_monitoring', show ? '1' : '0');
    } catch {}
  });

  // Load monitoring preference
  try {
    const savedMonitoring = localStorage.getItem('chat_show_monitoring');
    if ($chatShowMonitoring && savedMonitoring !== null) {
      $chatShowMonitoring.checked = savedMonitoring === '1';
    }
  } catch {}

  // Override showPage to handle monitoring
  const originalShowPageFunc = showPage;
  showPage = function(p) {
    originalShowPageFunc(p);
    
    if (p === 'chat') {
      // Show/hide monitoring based on checkbox
      const showMonitoring = $chatShowMonitoring?.checked || false;
      const dashboard = document.getElementById('token-usage-dashboard');
      const queueStatus = document.getElementById('queue-status');
      
      if (dashboard) dashboard.style.display = showMonitoring ? 'block' : 'none';
      if (queueStatus) queueStatus.style.display = showMonitoring ? 'block' : 'none';
      
      if (showMonitoring) {
        // Load initial monitoring data
        refreshMonitoringData();
        startMonitoringAutoRefresh();
      }
    } else {
      stopMonitoringAutoRefresh();
    }
  };
    monitoringState.refreshInterval = setInterval(() => {
      if (page === 'chat' || page === 'admin') {
        refreshMonitoringData();
      }
    }, 30000); // Refresh every 30 seconds
  }

  function stopMonitoringAutoRefresh() {
    if (monitoringState.refreshInterval) {
      clearInterval(monitoringState.refreshInterval);
      monitoringState.refreshInterval = null;
    }
    monitoringState.autoRefresh = false;
  }

  // Initialize monitoring when chat page is shown
  const originalShowPage = showPage;
  showPage = function(p) {
    originalShowPage(p);
    
    if (p === 'chat') {
      // Load initial monitoring data
      refreshMonitoringData();
      startMonitoringAutoRefresh();
    } else {
      stopMonitoringAutoRefresh();
    }
  };

  // ---------------------------
  // Enhanced Chat Sidebar Management
  // ---------------------------
  
  const CHAT_SIDEBAR_TABS = ['sessions', 'tools'];

  const chatSidebarState = {
    activeTab: CHAT_SIDEBAR_TABS[0],
    tabsReady: false,
  };

  function normaliseChatSidebarTab(tabName) {
    if (!tabName) return CHAT_SIDEBAR_TABS[0];
    const value = String(tabName).toLowerCase();
    return CHAT_SIDEBAR_TABS.includes(value) ? value : CHAT_SIDEBAR_TABS[0];
  }

  function switchChatSidebarTab(tabName, options = {}) {
    const { focusTab = false, skipPersist = false } = options;
    const targetTab = normaliseChatSidebarTab(tabName);
    chatSidebarState.activeTab = targetTab;

    const tabButtons = document.querySelectorAll('.chat-sidebar-tab');
    let activeButton = null;
    tabButtons.forEach((btn) => {
      const btnTab = normaliseChatSidebarTab(btn.getAttribute('data-tab'));
      const isActive = btnTab === targetTab;
      btn.classList.toggle('active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
      btn.setAttribute('tabindex', isActive ? '0' : '-1');
      if (isActive) activeButton = btn;
    });

    const panels = document.querySelectorAll('.chat-sidebar-panel');
    panels.forEach((panel) => {
      const panelTab = normaliseChatSidebarTab(panel.getAttribute('data-tab'));
      const isActive = panelTab === targetTab;
      panel.classList.toggle('active', isActive);
      panel.toggleAttribute('hidden', !isActive);
      panel.setAttribute('aria-hidden', isActive ? 'false' : 'true');
      panel.setAttribute('tabindex', isActive ? '0' : '-1');
    });

    if (focusTab && activeButton) activeButton.focus();
    if (!skipPersist) {
      try { localStorage.setItem('chat_sidebar_tab', targetTab); } catch {}
    }
    return targetTab;
  }

  // Setup sidebar tab event listeners
  function setupChatSidebarTabs() {
    const tabButtons = document.querySelectorAll('.chat-sidebar-tab');
    if (!tabButtons.length) return;

    const tabContainer = document.querySelector('.chat-sidebar-tabs');

    if (!chatSidebarState.tabsReady) {
      tabContainer?.addEventListener('click', (event) => {
        const btn = event.target.closest('.chat-sidebar-tab');
        if (!btn) return;
        const tabName = btn.getAttribute('data-tab');
        if (!tabName) return;
        event.preventDefault();
        switchChatSidebarTab(tabName);
      });

      tabContainer?.addEventListener('keydown', (event) => {
        const target = event.target.closest('.chat-sidebar-tab');
        if (!target) return;

        const key = event.key;
        const currentIdx = CHAT_SIDEBAR_TABS.indexOf(normaliseChatSidebarTab(chatSidebarState.activeTab));
        let nextTab = null;

        if (key === 'ArrowRight' || key === 'ArrowDown') {
          nextTab = CHAT_SIDEBAR_TABS[(currentIdx + 1) % CHAT_SIDEBAR_TABS.length];
        } else if (key === 'ArrowLeft' || key === 'ArrowUp') {
          nextTab = CHAT_SIDEBAR_TABS[(currentIdx - 1 + CHAT_SIDEBAR_TABS.length) % CHAT_SIDEBAR_TABS.length];
        } else if (key === 'Home') {
          nextTab = CHAT_SIDEBAR_TABS[0];
        } else if (key === 'End') {
          nextTab = CHAT_SIDEBAR_TABS[CHAT_SIDEBAR_TABS.length - 1];
        } else if (key === ' ' || key === 'Spacebar' || key === 'Enter') {
          event.preventDefault();
          switchChatSidebarTab(target.getAttribute('data-tab'), { focusTab: true });
          return;
        } else {
          return;
        }

        if (nextTab) {
          event.preventDefault();
          switchChatSidebarTab(nextTab, { focusTab: true });
        }
      });

      chatSidebarState.tabsReady = true;
    }

    let savedTab = null;
    try {
      savedTab = localStorage.getItem('chat_sidebar_tab');
    } catch {}
    const initialTab = savedTab && CHAT_SIDEBAR_TABS.includes(savedTab)
      ? savedTab
      : chatSidebarState.activeTab || CHAT_SIDEBAR_TABS[0];
    switchChatSidebarTab(initialTab, { skipPersist: true });
  }


  // Enhanced showPage function with proper chat initialization
  const enhancedShowPage = showPage;
  showPage = function(p) {
    enhancedShowPage(p);
    
    if (p === 'chat') {
      // Initialize sidebar tabs
      setupChatSidebarTabs();
      
      // Ensure persistent search options
      ensurePersistentSearchOptions();
      
      // Load monitoring if enabled
      const showMonitoring = document.getElementById('chat-show-monitoring')?.checked || false;
      const dashboard = document.getElementById('token-usage-dashboard');
      const queueStatus = document.getElementById('queue-status');
      
      if (dashboard) dashboard.style.display = showMonitoring ? 'block' : 'none';
      if (queueStatus) queueStatus.style.display = showMonitoring ? 'block' : 'none';
      
      if (showMonitoring) {
        refreshMonitoringData();
        startMonitoringAutoRefresh();
      }
    } else {
      stopMonitoringAutoRefresh();
    }
  };

  // Expose monitoring functions globally for debugging
  window.refreshMonitoringData = refreshMonitoringData;
  window.loadTokenUsageStats = loadTokenUsageStats;
  window.loadQueueStatus = loadQueueStatus;
  window.switchChatSidebarTab = switchChatSidebarTab;
  window.ensurePersistentSearchOptions = ensurePersistentSearchOptions;
    }
  });
})();
