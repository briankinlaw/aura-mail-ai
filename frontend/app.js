// Aura Mail AI - Frontend Application Controller (v1.1 Cloud Multi-Account)

// --- Authenticated Session Initialization from Same-Origin Runtime ---
let AURA_SESSION_TOKEN = window.__AURA_SESSION_TOKEN__ || null;

const _nativeFetch = window.fetch;
window._nativeFetch = _nativeFetch;
window.fetch = async function(url, options = {}) {
  options = options || {};
  options.headers = options.headers || {};
  const token = AURA_SESSION_TOKEN || window.__AURA_SESSION_TOKEN__;
  if (token) {
    if (options.headers instanceof Headers) {
      if (!options.headers.has('Authorization')) {
        options.headers.set('Authorization', `Bearer ${token}`);
      }
      if (!options.headers.has('X-Aura-Session-Token')) {
        options.headers.set('X-Aura-Session-Token', token);
      }
    } else if (typeof options.headers === 'object') {
      if (!options.headers['Authorization']) {
        options.headers['Authorization'] = `Bearer ${token}`;
      }
      if (!options.headers['X-Aura-Session-Token']) {
        options.headers['X-Aura-Session-Token'] = token;
      }
    }
  }
  return _nativeFetch(url, options);
};

let APP_STATE = {
  emails: [],
  accounts: [],
  selectedEmailId: null,
  profile: null,
  canonicalData: null,
  resumes: [],
  status: null,
  activeFilter: 'ALL',
  activeNoiseAccountFilter: 'ALL',
  queueFilter: 'pending',
  followups: [],
  followupFilter: 'PENDING',
  activeVaultFilter: 'ALL',
  vaultSearchQuery: '',
  devicePollInterval: null,
  activeRiskToken: null,
  riskRequestGeneration: 0
};

// DOM Elements
const elements = {
  statResumeInquiries: document.getElementById('stat-resume-inquiries'),
  statNoiseDetected: document.getElementById('stat-noise-detected'),
  statTimeSaved: document.getElementById('stat-time-saved'),
  statCleanliness: document.getElementById('stat-cleanliness'),
  
  tabBadgeRecruiters: document.getElementById('tab-badge-recruiters'),
  tabBadgeFollowups: document.getElementById('tab-badge-followups'),
  tabBadgeNoise: document.getElementById('tab-badge-noise'),
  tabBadgeVault: document.getElementById('tab-badge-vault'),
  tabBadgeAccounts: document.getElementById('tab-badge-accounts'),
  headerConnCount: document.getElementById('header-conn-count'),
  recruiterCountPill: document.getElementById('recruiter-count-pill'),
  
  // Queue sub-filters
  filterBtnPending: document.getElementById('filter-btn-pending'),
  filterBtnStaged: document.getElementById('filter-btn-staged'),
  filterBtnReplied: document.getElementById('filter-btn-replied'),
  filterBtnAll: document.getElementById('filter-btn-all'),
  filterCountPending: document.getElementById('filter-count-pending'),
  filterCountStaged: document.getElementById('filter-count-staged'),
  filterCountReplied: document.getElementById('filter-count-replied'),
  filterCountAll: document.getElementById('filter-count-all'),
  
  recruiterEmailsList: document.getElementById('recruiter-emails-list'),
  triageTableBody: document.getElementById('triage-table-body'),
  noiseAccountsGrid: document.getElementById('noise-accounts-grid'),
  triageAccountFilterGroup: document.getElementById('triage-account-filter-group'),
  accountsCardsGrid: document.getElementById('accounts-cards-grid'),
  demoModeBanner: document.getElementById('demo-mode-banner'),
  btnDisableDemo: document.getElementById('btn-disable-demo'),
  
  inboundSubject: document.getElementById('inbound-subject'),
  inboundSender: document.getElementById('inbound-sender'),
  inboundAccountPill: document.getElementById('inbound-account-pill'),
  inboundDate: document.getElementById('inbound-date'),
  inboundMessageBody: document.getElementById('inbound-message-body'),
  
  specRole: document.getElementById('spec-role'),
  specCompany: document.getElementById('spec-company'),
  specSalary: document.getElementById('spec-salary'),
  specSkills: document.getElementById('spec-skills'),
  
  // Canonical Match Elements
  canonicalMatchCard: document.getElementById('canonical-match-card'),
  matchLensBadge: document.getElementById('match-lens-badge'),
  matchScoreValue: document.getElementById('match-score-value'),
  matchRationale: document.getElementById('match-rationale'),
  resumeVariantSelect: document.getElementById('resume-variant-select'),
  attachmentFormatHint: document.getElementById('attachment-format-hint'),
  
  replyBodyText: document.getElementById('reply-body-text'),
  attachedResumeName: document.getElementById('attached-resume-name'),
  toneSelector: document.getElementById('tone-selector'),
  
  btnSyncInbox: document.getElementById('btn-sync-inbox'),
  btnRegenerateDraft: document.getElementById('btn-regenerate-draft'),
  btnSaveDraft: document.getElementById('btn-save-draft'),
  btnSaveDraftLabel: document.getElementById('btn-save-draft-label'),
  btnMarkReplied: document.getElementById('btn-mark-replied'),
  btnCopyDraft: document.getElementById('btn-copy-draft'),
  btnRiskCheck: document.getElementById('btn-risk-check'),
  webCockpitRiskBadge: document.getElementById('web-cockpit-risk-badge'),
  btnOrchestrateAllNoise: document.getElementById('btn-orchestrate-all-noise'),
  btnBatchCleanNoise: document.getElementById('btn-batch-clean-noise'),
  btnOpenAccounts: document.getElementById('btn-open-accounts'),
  btnAddAccountModal: document.getElementById('btn-add-account-modal'),
  btnOpenSettings: document.getElementById('btn-open-settings'),
  btnSaveProfile: document.getElementById('btn-save-profile'),
  btnSaveSettings: document.getElementById('btn-save-settings'),
  settingAutoQuarantine: document.getElementById('setting-auto-quarantine-noise'),

  // Follow-up Elements
  followupTasksList: document.getElementById('followup-tasks-list'),
  fuCountPending: document.getElementById('fu-count-pending'),
  fuCountCompleted: document.getElementById('fu-count-completed'),
  fuCountAll: document.getElementById('fu-count-all'),
  fuFilterPending: document.getElementById('fu-filter-pending'),
  fuFilterCompleted: document.getElementById('fu-filter-completed'),
  fuFilterAll: document.getElementById('fu-filter-all'),
  btnAddOrchestratePipeline: document.getElementById('btn-orchestrate-pipeline'),
  btnAddCustomFollowup: document.getElementById('btn-add-custom-followup'),
  followupModal: document.getElementById('followup-modal'),
  followupModalCloseBtn: document.getElementById('followup-modal-close-btn'),
  btnCancelFollowup: document.getElementById('btn-cancel-followup'),
  btnSaveCustomFollowup: document.getElementById('btn-save-custom-followup'),
  fuRecruiterInput: document.getElementById('fu-recruiter-input'),
  fuCompanyInput: document.getElementById('fu-company-input'),
  fuRoleInput: document.getElementById('fu-role-input'),
  fuDateInput: document.getElementById('fu-date-input'),
  fuNotesInput: document.getElementById('fu-notes-input'),
  
  // Vault Elements
  vaultGridContainer: document.getElementById('vault-grid-container'),
  vaultSearchInput: document.getElementById('vault-search-input'),
  btnRefreshResumes: document.getElementById('btn-refresh-resumes'),
  btnOpenLedgerModal: document.getElementById('btn-open-ledger-modal'),
  vaultCountAll: document.getElementById('vault-count-all'),
  vaultCountStandard: document.getElementById('vault-count-standard'),
  vaultCountTargeted: document.getElementById('vault-count-targeted'),
  vaultCountTruth: document.getElementById('vault-count-truth'),
  
  // Ledger Modal
  ledgerModal: document.getElementById('ledger-modal'),
  ledgerModalCloseBtn: document.getElementById('ledger-modal-close-btn'),
  btnCloseLedger: document.getElementById('btn-close-ledger'),
  ledgerTextViewer: document.getElementById('ledger-text-viewer'),
  
  // Auth Modal
  accountAuthModal: document.getElementById('account-auth-modal'),
  modalCloseBtn: document.getElementById('modal-close-btn'),
  authTabMsal: document.getElementById('auth-tab-msal'),
  authTabGoogle: document.getElementById('auth-tab-google'),
  authTabImap: document.getElementById('auth-tab-imap'),
  authPanelMsal: document.getElementById('auth-panel-msal'),
  authPanelGoogle: document.getElementById('auth-panel-google'),
  authPanelImap: document.getElementById('auth-panel-imap'),
  btnStartDeviceFlow: document.getElementById('btn-start-device-flow'),
  btnStartDirectMsal: document.getElementById('btn-start-direct-msal'),
  deviceFlowDisplay: document.getElementById('device-flow-display'),
  deviceCodeDisplay: document.getElementById('device-code-display'),
  devicePollStatus: document.getElementById('device-poll-status'),
  btnStartGoogleAuth: document.getElementById('btn-start-google-auth'),
  googleAuthCodeInput: document.getElementById('google-auth-code-input'),
  btnSubmitGoogleCode: document.getElementById('btn-submit-google-code'),
  btnSaveImapAuth: document.getElementById('btn-save-imap-auth'),
  
  resumeDropzone: document.getElementById('resume-dropzone'),
  resumeFileInput: document.getElementById('resume-file-input'),
  profileActiveName: document.getElementById('profile-active-name'),
  profileActiveLens: document.getElementById('profile-active-lens'),
  
  cloudStatusText: document.getElementById('cloud-status-text'),
  cloudDot: document.getElementById('cloud-dot'),
  desktopStatusText: document.getElementById('desktop-status-text'),
  desktopDot: document.getElementById('desktop-dot'),
  aiStatusText: document.getElementById('ai-status-text'),
  aiDot: document.getElementById('ai-dot')
};

// --- Initialization ---
document.addEventListener('DOMContentLoaded', async () => {
  setupTabNavigation();
  setupEventListeners();
  handleUrlAuthParams();
  await refreshAll();
});

function handleUrlAuthParams() {
  const params = new URLSearchParams(window.location.search);
  const authSuccess = params.get('auth');
  const authError = params.get('auth_error');
  const provider = params.get('provider');

  if (authSuccess === 'success') {
    const provName = provider === 'google' ? 'Google / Gmail' : provider === 'microsoft' ? 'Microsoft Outlook' : 'Cloud Account';
    showToast(`✓ Successfully connected ${provName}!`, 'success');
  } else if (authError) {
    if (authError === 'invalid_state') {
      showToast('Authentication session expired or state was already used. Click "Sign In" on your account card to connect.', 'warning');
    } else if (authError === 'exchange_failed') {
      showToast('OAuth token exchange failed. Please verify your client credentials and permissions.', 'error');
    } else if (authError === 'missing_code') {
      showToast('No authorization code was returned by the provider.', 'error');
    } else if (authError === 'provider_error') {
      showToast('The email provider encountered an error during sign-in.', 'error');
    } else {
      showToast(`Authentication error: ${authError}`, 'error');
    }
  }

  if (authSuccess || authError) {
    window.history.replaceState({}, document.title, window.location.pathname);
  }
}

async function refreshAll() {
  await Promise.all([
    fetchStatus(),
    fetchAccounts(),
    fetchProfile(),
    fetchSettings(),
    fetchCanonicalResumes(),
    fetchEmails(),
    fetchStats(),
    fetchFollowups()
  ]);
  renderNoiseAccountCards();
  await fetchAnalyticsData();
}

// --- Tabs Navigation ---
function setupTabNavigation() {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      
      const targetPane = tab.getAttribute('data-tab');
      document.querySelectorAll('.tab-pane').forEach(p => p.style.display = 'none');
      
      const activePane = document.getElementById(`pane-${targetPane}`);
      if (activePane) activePane.style.display = 'block';
    });
  });
}

// --- API Calls ---

async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) return;
    const data = await res.json();
    APP_STATE.status = data;
    
    // Cloud Status
    if (data.demo_mode) {
      elements.cloudStatusText.textContent = 'Demo Mode (Offline Sandbox)';
      elements.cloudDot.className = 'status-dot';
      elements.cloudDot.style.background = '#eab308';
      if (elements.demoModeBanner) elements.demoModeBanner.style.display = 'flex';
    } else {
      if (elements.demoModeBanner) elements.demoModeBanner.style.display = 'none';
      if (data.connected_accounts > 0) {
        elements.cloudStatusText.textContent = `Cloud Sync: ${data.connected_accounts}/${data.total_accounts} Active`;
        elements.cloudDot.className = 'status-dot';
        elements.cloudDot.style.background = '#10b981';
      } else {
        elements.cloudStatusText.textContent = 'Cloud: Disconnected (Configure Accounts)';
        elements.cloudDot.className = 'status-dot';
        elements.cloudDot.style.background = '#ef4444';
      }
    }
    
    // Authoritative Microsoft Graph Provider Status (Phase 2.1)
    if (data.graph_connection) {
      const gConn = data.graph_connection;
      elements.desktopStatusText.textContent = gConn.display_text || `Microsoft Graph: ${gConn.status}`;
      elements.desktopDot.className = 'status-dot';
      if (gConn.status === 'CONNECTED') {
        elements.desktopDot.style.background = '#10b981';
      } else if (gConn.status === 'AUTH_REQUIRED') {
        elements.desktopDot.style.background = '#f59e0b';
      } else if (gConn.status === 'DEMO') {
        elements.desktopDot.style.background = '#eab308';
      } else {
        elements.desktopDot.style.background = '#94a3b8';
      }
    } else if (data.desktop_outlook_app && data.desktop_outlook_app.is_running) {
      elements.desktopStatusText.textContent = 'Mac Outlook: Running';
      elements.desktopDot.className = 'status-dot';
      elements.desktopDot.style.background = '#10b981';
    } else {
      elements.desktopStatusText.textContent = 'Microsoft Graph: Disconnected';
      elements.desktopDot.className = 'status-dot';
      elements.desktopDot.style.background = '#94a3b8';
    }
    
    // AI Status
    if (data.gemini_configured) {
      elements.aiStatusText.textContent = 'Gemini AI: Active (Keychain)';
      elements.aiDot.className = 'status-dot';
      elements.aiDot.style.background = '#10b981';
    } else {
      elements.aiStatusText.textContent = 'AI Engine: Local Heuristics';
      elements.aiDot.className = 'status-dot';
      elements.aiDot.style.background = '#3b82f6';
    }
    
    if (data.active_resume) {
      elements.attachedResumeName.textContent = data.active_resume;
      if (elements.profileActiveName) elements.profileActiveName.textContent = data.active_resume;
    }
  } catch (err) {
    console.error('Failed to fetch status', err);
  }
}

async function fetchAccounts() {
  try {
    const res = await fetch('/api/accounts');
    if (!res.ok) return;
    const accounts = await res.json();
    APP_STATE.accounts = accounts;
    
    const connectedCount = accounts.filter(a => a.is_connected).length;
    if (elements.headerConnCount) elements.headerConnCount.textContent = connectedCount;
    if (elements.tabBadgeAccounts) elements.tabBadgeAccounts.textContent = accounts.length;
    
    renderAccountsGrid();
    renderNoiseAccountCards();
  } catch (err) {
    console.error('Failed to fetch accounts', err);
  }
}

async function fetchStats() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) return;
    const stats = await res.json();
    
    elements.statResumeInquiries.textContent = stats.resume_requests || 0;
    elements.statNoiseDetected.textContent = stats.noise_detected || 0;
    elements.statTimeSaved.textContent = `${stats.time_saved_minutes || 0}m`;
    elements.statCleanliness.textContent = `${stats.inbox_cleanliness_score || 100}%`;
    
    elements.tabBadgeRecruiters.textContent = stats.resume_requests || 0;
    elements.tabBadgeNoise.textContent = stats.noise_detected || 0;
    elements.recruiterCountPill.textContent = `${stats.resume_requests || 0} requests`;
  } catch (err) {
    console.error('Failed to fetch stats', err);
  }
}

async function fetchEmails() {
  try {
    const res = await fetch('/api/emails');
    if (!res.ok) return;
    const emails = await res.json();
    APP_STATE.emails = emails;
    
    renderRecruiterList();
    renderTriageTable();
    renderNoiseAccountCards();
  } catch (err) {
    console.error('Failed to fetch emails', err);
  }
}

async function fetchProfile() {
  try {
    const res = await fetch('/api/profile');
    const profile = await res.json();
    APP_STATE.profile = profile;
    
    document.getElementById('prof-name').value = profile.full_name || 'Brian K. Kinlaw';
    document.getElementById('prof-title').value = profile.current_title || 'Enterprise Cloud, Data & AI Solutions Architecture Advisor';
    document.getElementById('prof-bio').value = profile.summary_bio || '';
    document.getElementById('prof-skills').value = (profile.core_skills || []).join(', ');
    document.getElementById('prof-target-roles').value = (profile.target_roles || []).join(', ');
    document.getElementById('prof-prefs').value = profile.work_preferences || '';
    document.getElementById('prof-instructions').value = profile.custom_reply_instructions || '';
    
    const histEmailsInput = document.getElementById('prof-historical-emails');
    if (histEmailsInput) {
      histEmailsInput.value = (profile.historical_email_accounts || []).join(', ');
    }
    
    if (elements.profileActiveName) {
      elements.profileActiveName.textContent = profile.active_resume_file || 'Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx';
    }
  } catch (err) {
    console.error('Failed to fetch profile', err);
  }
}

async function fetchSettings() {
  try {
    const res = await fetch('/api/settings');
    const settings = await res.json();
    
    const azureInput = document.getElementById('setting-azure-client');
    if (azureInput && settings.azure_client_id) azureInput.value = settings.azure_client_id;
    
    const tenantInput = document.getElementById('setting-azure-tenant');
    if (tenantInput && settings.azure_tenant_id) tenantInput.value = settings.azure_tenant_id;
    
    const googleInput = document.getElementById('setting-google-client');
    if (googleInput && settings.google_client_id) googleInput.value = settings.google_client_id;
    
    const googleStatus = document.getElementById('google-secret-status');
    if (googleStatus) {
      if (settings.has_google_client_secret) {
        googleStatus.textContent = `Configured in macOS Keychain (${settings.google_client_secret_masked || '••••'})`;
        googleStatus.style.color = '#6ee7b7';
      } else {
        googleStatus.textContent = 'Not configured';
        googleStatus.style.color = '#94a3b8';
      }
    }
    
    const geminiStatus = document.getElementById('gemini-key-status');
    if (geminiStatus) {
      if (settings.has_gemini_api_key) {
        geminiStatus.textContent = `Configured in macOS Keychain (${settings.gemini_api_key_masked || '••••'})`;
        geminiStatus.style.color = '#6ee7b7';
      } else {
        geminiStatus.textContent = 'Not configured';
        geminiStatus.style.color = '#f87171';
      }
    }

    const folderInput = document.getElementById('setting-safe-folder');
    if (folderInput && settings.safe_folder_name) folderInput.value = settings.safe_folder_name;

    const autoQuarantineCheck = document.getElementById('setting-auto-quarantine-noise');
    if (autoQuarantineCheck) autoQuarantineCheck.checked = settings.auto_quarantine_noise !== false;

    const demoCheck = document.getElementById('setting-demo-mode');
    if (demoCheck) demoCheck.checked = !!settings.demo_mode;
  } catch (err) {
    console.error('Failed to fetch settings', err);
  }
}

async function fetchCanonicalResumes(forceRefresh = false) {
  try {
    const res = await fetch(`/api/canonical/resumes?refresh=${forceRefresh ? 'true' : 'false'}`);
    const data = await res.json();
    APP_STATE.canonicalData = data;
    APP_STATE.resumes = data.all_resumes || [];
    
    if (elements.tabBadgeVault) {
      elements.tabBadgeVault.textContent = data.total_resumes || 0;
    }
    
    populateResumeDropdown();
    renderVaultGrid();
  } catch (err) {
    console.error('Failed to fetch canonical resumes', err);
  }
}

// --- Render Methods ---

function renderAccountsGrid() {
  const container = elements.accountsCardsGrid;
  if (!container) return;
  container.innerHTML = '';
  
  if (APP_STATE.accounts.length === 0) {
    container.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <div class="empty-state-icon">📭</div>
        <p>No mailbox accounts configured yet. Click "Connect New Account" to add one.</p>
      </div>`;
    return;
  }
  
  APP_STATE.accounts.forEach(acc => {
    const card = document.createElement('div');
    card.className = 'vault-card';
    card.style.background = 'rgba(30, 41, 59, 0.7)';
    
    let provBadge = '☁️ Microsoft Graph';
    let provColor = '#3b82f6';
    if (acc.provider === 'GMAIL') {
      provBadge = '📮 Gmail API';
      provColor = '#ea4335';
    } else if (acc.provider === 'IMAP') {
      provBadge = '🌐 Standard IMAP';
      provColor = '#10b981';
    } else if (acc.provider === 'DEMO') {
      provBadge = '🧪 Demo Sandbox';
      provColor = '#eab308';
    }
    
    const hasError = Boolean(acc.last_error);
    const isConn = acc.is_connected && !hasError;
    let statusPill = `<span style="font-size: 0.75rem; color: #10b981; font-weight: 600;">● Connected</span>`;
    if (hasError) {
      statusPill = `<span style="font-size: 0.75rem; color: #f59e0b; font-weight: 600;">⚠️ Needs Attention</span>`;
    } else if (!isConn) {
      statusPill = `<span style="font-size: 0.75rem; color: #ef4444; font-weight: 600;">○ Disconnected</span>`;
    }
    
    const caps = (acc.capabilities || []).filter(c => c !== 'SEND').map(c => `<span class="skill-chip" style="font-size: 0.65rem; padding: 2px 6px;">${c}</span>`).join(' ');
    
    card.innerHTML = `
      <div>
        <div class="vault-card-header" style="margin-bottom: 8px;">
          <span class="lens-pill" style="background: ${provColor}22; color: ${provColor}; border: 1px solid ${provColor}55;">
            ${provBadge}
          </span>
          ${statusPill}
        </div>
        <div class="vault-card-title" style="font-size: 1.05rem; word-break: break-all;">${acc.email_address}</div>
        <div class="vault-card-headline" style="color: var(--text-secondary); margin-top: 4px;">${acc.display_name}</div>
        
        ${acc.is_alias ? `<p style="font-size: 0.75rem; color: #93c5fd; margin-top: 6px;">↳ Alias of parent mailbox: <code>${acc.alias_of}</code></p>` : ''}
        ${hasError ? `<div style="background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: var(--radius-sm); padding: 8px 10px; margin-top: 8px; font-size: 0.775rem; color: #fca5a5; line-height: 1.4;"><strong>Action Needed:</strong> ${acc.last_error}</div>` : ''}
        
        <div style="margin-top: 10px;">
          <div style="font-size: 0.7rem; color: var(--text-muted); margin-bottom: 4px;">Capabilities:</div>
          <div style="display: flex; flex-wrap: wrap; gap: 4px;">${caps}</div>
        </div>
      </div>
      
      <div style="margin-top: 14px; border-top: 1px solid rgba(255, 255, 255, 0.08); padding-top: 10px;">
        <div class="vault-card-footer">
          <span style="font-size: 0.7rem; color: var(--text-muted);">
            Sync: ${acc.last_sync_time ? acc.last_sync_time.split('T')[1].slice(0,5) : 'Never'}
          </span>
          <div style="display: flex; gap: 6px;">
            <button class="btn btn-secondary btn-sm" onclick="testAccount('${acc.account_id}')">Test</button>
            <button class="btn ${hasError ? 'btn-primary' : 'btn-secondary'} btn-sm" onclick="openAuthModalFor('${acc.provider}', '${acc.account_id}')">
              ${hasError ? 'Fix / Sign In' : (isConn ? 'Re-Auth' : 'Sign In')}
            </button>
          </div>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

window.testAccount = async function(accountId) {
  showToast(`Testing connection for ${accountId}...`, 'info');
  try {
    const res = await fetch(`/api/accounts/${encodeURIComponent(accountId)}/test`, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast(`Connection verified for ${accountId}!`, 'success');
    } else {
      showToast(`Connection test failed: ${data.safe_message}`, 'error');
    }
    await fetchAccounts();
    await fetchStatus();
  } catch (err) {
    showToast(`Test error: ${err.message}`, 'error');
  }
};

window.openAuthModalFor = function(providerType, accountId) {
  elements.accountAuthModal.classList.add('active');
  elements.accountAuthModal.dataset.accountId = accountId || '';
  
  const targetBadge = document.getElementById('modal-target-account-badge');
  if (targetBadge) {
    if (accountId) {
      targetBadge.textContent = `Target: ${accountId}`;
      targetBadge.style.display = 'inline-block';
    } else {
      targetBadge.style.display = 'none';
    }
  }

  const pType = (providerType || '').toUpperCase();
  const accLower = (accountId || '').toLowerCase();

  if (pType === 'GMAIL' || accLower.includes('@gmail.com') || accLower.includes('@mavencode.com')) {
    if (elements.authTabGoogle) elements.authTabGoogle.click();
    const gInput = document.getElementById('google-auth-code-input');
    if (gInput) gInput.value = '';
  } else if (pType === 'IMAP' || accLower.includes('@satx.rr.com')) {
    if (elements.authTabImap) elements.authTabImap.click();
    const emInput = document.getElementById('imap-email-input');
    if (emInput) emInput.value = accountId || '';
    
    // Auto-fill known server host defaults if empty or matching domain
    const imapInput = document.getElementById('imap-server-input');
    if (accLower.includes('satx.rr.com')) {
      if (imapInput) imapInput.value = 'mail.twc.com';
    }
  } else {
    if (elements.authTabMsal) elements.authTabMsal.click();
  }
};

function populateResumeDropdown() {
  const select = elements.resumeVariantSelect;
  if (!select) return;
  select.innerHTML = '';
  
  if (!APP_STATE.canonicalData) return;
  
  const standardGroup = document.createElement('optgroup');
  standardGroup.label = '── Level 3 Standard Canonicals ──';
  
  (APP_STATE.canonicalData.standard_canonicals || []).forEach(r => {
    const opt = document.createElement('option');
    opt.value = r.filename;
    opt.textContent = `★ ${r.filename} [${r.lens_badge}]`;
    standardGroup.appendChild(opt);
  });
  select.appendChild(standardGroup);
  
  const customGroup = document.createElement('optgroup');
  customGroup.label = '── Custom Targeted Applications ──';
  
  (APP_STATE.canonicalData.targeted_customs || []).forEach(r => {
    const opt = document.createElement('option');
    opt.value = r.filename;
    opt.textContent = `${r.filename} (${r.format.toUpperCase()})`;
    customGroup.appendChild(opt);
  });
  select.appendChild(customGroup);
  
  const masterGroup = document.createElement('optgroup');
  masterGroup.label = '── Master & Specialized Variants ──';
  (APP_STATE.canonicalData.master_variants || []).forEach(r => {
    const opt = document.createElement('option');
    opt.value = r.filename;
    opt.textContent = `${r.filename} (${r.format.toUpperCase()})`;
    masterGroup.appendChild(opt);
  });
  select.appendChild(masterGroup);
}

function getAccountInfoForEmail(emailMsg) {
  if (!emailMsg) return { accountId: 'kinlawb@outlook.com', provider: 'MICROSOFT_GRAPH', label: 'kinlawb@outlook.com (Outlook)', type: 'outlook' };
  
  let accountId = emailMsg.account_id || '';
  let provider = emailMsg.provider || '';
  
  if (emailMsg.id && emailMsg.id.includes('::')) {
    const parts = emailMsg.id.split('::');
    if (parts.length === 3) {
      provider = parts[0].trim().toUpperCase();
      accountId = decodeURIComponent(parts[1]).toLowerCase();
    }
  }
  
  if (!accountId || accountId === 'primary' || accountId === 'default') {
    accountId = 'kinlawb@outlook.com';
  }
  
  let label = accountId;
  let type = 'outlook';
  
  if (accountId.includes('gmail.com') || accountId.includes('mavencode.com') || provider === 'GMAIL') {
    label = `${accountId} (Google Workspace)`;
    type = 'google';
  } else if (accountId.includes('satx.rr.com') || provider === 'IMAP') {
    label = `${accountId} (Spectrum)`;
    type = 'imap';
  } else if (accountId.includes('outlook.com') || provider === 'MICROSOFT_GRAPH') {
    label = `${accountId} (Outlook)`;
    type = 'outlook';
  } else if (provider === 'DEMO') {
    label = `${accountId} (Sandbox)`;
    type = 'demo';
  }
  
  return { accountId, provider, label, type };
}

function renderRecruiterList() {
  const container = elements.recruiterEmailsList;
  if (!container) return;
  container.innerHTML = '';
  
  const allRecruiters = APP_STATE.emails.filter(e => e.classification && e.classification.is_resume_request);
  const pendingEmails = allRecruiters.filter(e => e.status !== 'DRAFTED' && e.status !== 'REPLIED' && e.status !== 'TRASHED' && e.status !== 'ARCHIVED');
  const stagedEmails = allRecruiters.filter(e => e.status === 'DRAFTED');
  const repliedEmails = allRecruiters.filter(e => e.status === 'REPLIED');
  
  if (elements.filterCountPending) elements.filterCountPending.textContent = pendingEmails.length;
  if (elements.filterCountStaged) elements.filterCountStaged.textContent = stagedEmails.length;
  if (elements.filterCountReplied) elements.filterCountReplied.textContent = repliedEmails.length;
  if (elements.filterCountAll) elements.filterCountAll.textContent = allRecruiters.length;
  if (elements.recruiterCountPill) elements.recruiterCountPill.textContent = `${pendingEmails.length} pending / ${allRecruiters.length} total`;
  
  const currentFilter = APP_STATE.queueFilter || 'pending';
  let filteredEmails = pendingEmails;
  if (currentFilter === 'staged') filteredEmails = stagedEmails;
  else if (currentFilter === 'replied') filteredEmails = repliedEmails;
  else if (currentFilter === 'all') filteredEmails = allRecruiters;
  
  if (filteredEmails.length === 0) {
    let emptyMsg = 'No pending recruiter reachouts in queue.';
    let emptyIcon = '🎉';
    if (currentFilter === 'staged') {
      emptyMsg = 'No reachouts currently staged in Drafts.';
      emptyIcon = '📝';
    } else if (currentFilter === 'replied') {
      emptyMsg = 'No reachouts marked as Replied yet.';
      emptyIcon = '📬';
    } else if (currentFilter === 'all') {
      emptyMsg = 'No recruiter reachouts found in connected mailboxes.';
      emptyIcon = '📭';
    } else {
      emptyMsg = 'All caught up! All recruiter reachouts have been drafted or processed.';
    }
    container.innerHTML = `
      <div class="empty-state" style="padding: 2.5rem 1rem;">
        <div class="empty-state-icon" style="font-size: 2.25rem; margin-bottom: 8px;">${emptyIcon}</div>
        <p style="font-size: 0.85rem; color: #94a3b8; text-align: center;">${emptyMsg}</p>
      </div>`;
    return;
  }
  
  filteredEmails.forEach(emailMsg => {
    const card = document.createElement('div');
    card.className = `email-card ${emailMsg.id === APP_STATE.selectedEmailId ? 'selected' : ''}`;
    card.id = `card-${emailMsg.id.replace(/[^a-zA-Z0-9_-]/g, '_')}`;
    
    const roleName = emailMsg.classification?.recruiter_details?.role_title || emailMsg.subject;
    const compName = emailMsg.classification?.recruiter_details?.company_name || 'Hiring Team';
    const match = emailMsg.classification?.resume_match;
    const lensBadge = match?.lens_badge || 'Advisor (Level 3A)';
    const accInfo = getAccountInfoForEmail(emailMsg);
    
    let statusBadgeHtml = '<span class="status-chip pending">Pending</span>';
    if (emailMsg.status === 'DRAFTED') {
      statusBadgeHtml = '<span class="status-chip drafted">📝 Draft Staged</span>';
    } else if (emailMsg.status === 'REPLIED') {
      statusBadgeHtml = '<span class="status-chip replied">✅ Replied</span>';
    }
    
    card.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
        <span class="account-chip ${accInfo.type}" title="Received on ${accInfo.label}">
          ${accInfo.type === 'google' ? '🌐' : (accInfo.type === 'outlook' ? '📬' : '⚡')} ${accInfo.accountId}
        </span>
        ${statusBadgeHtml}
      </div>
      <div class="email-card-header">
        <span class="sender-name">${emailMsg.sender_name}</span>
        <span class="email-time">${emailMsg.received_at.split(' ')[1] || ''}</span>
      </div>
      <div class="email-subject">${roleName}</div>
      <div class="email-snippet">${emailMsg.preview}</div>
      <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px;">
        <span class="category-tag recruiter">🎯 ${compName}</span>
        <span class="lens-pill" style="font-size: 0.65rem; padding: 1px 6px; background: rgba(59,130,246,0.15); color: #93c5fd;">${lensBadge}</span>
      </div>
    `;
    
    card.addEventListener('click', () => selectRecruiterEmail(emailMsg.id));
    container.appendChild(card);
  });
  
  if (!filteredEmails.some(e => e.id === APP_STATE.selectedEmailId) && filteredEmails.length > 0) {
    selectRecruiterEmail(filteredEmails[0].id);
  }
}

function selectRecruiterEmail(emailId) {
  APP_STATE.selectedEmailId = emailId;
  APP_STATE.activeRiskToken = null;
  APP_STATE.riskRequestGeneration++;
  
  document.querySelectorAll('.email-card').forEach(c => c.classList.remove('selected'));
  const card = document.getElementById(`card-${emailId.replace(/[^a-zA-Z0-9_-]/g, '_')}`);
  if (card) card.classList.add('selected');
  
  const emailMsg = APP_STATE.emails.find(e => e.id === emailId);
  if (!emailMsg) return;
  
  const accInfo = getAccountInfoForEmail(emailMsg);
  
  elements.inboundSubject.textContent = emailMsg.subject;
  elements.inboundSender.textContent = `From: ${emailMsg.sender_name} <${emailMsg.sender_email}>`;
  if (elements.inboundAccountPill) {
    elements.inboundAccountPill.className = `account-pill-badge ${accInfo.type}`;
    elements.inboundAccountPill.innerHTML = `📬 Received on: <strong>${accInfo.label}</strong>`;
  }
  elements.inboundDate.textContent = `Received: ${emailMsg.received_at}`;
  elements.inboundMessageBody.textContent = emailMsg.body_text;
  
  // Recruiter Specs
  const specs = emailMsg.classification?.recruiter_details;
  if (specs) {
    elements.specRole.textContent = specs.role_title || 'Enterprise Solutions Architecture Role';
    elements.specCompany.textContent = specs.company_name || 'Prospective Employer';
    elements.specSalary.textContent = specs.salary_range || 'Competitive / Open to Discussion';
    
    elements.specSkills.innerHTML = (specs.required_skills || ['Cloud Architecture', 'Google Cloud', 'Enterprise Data'])
      .map(s => `<span class="skill-chip">${s}</span>`).join('');
  }
  
  // Canonical Match & Lens Card
  const match = emailMsg.classification?.resume_match;
  if (match) {
    elements.matchLensBadge.textContent = match.lens_name;
    elements.matchLensBadge.style.background = `${match.lens_color}22`;
    elements.matchLensBadge.style.color = match.lens_color;
    elements.matchLensBadge.style.borderColor = `${match.lens_color}66`;
    
    elements.matchScoreValue.textContent = `${match.match_score}%`;
    elements.matchRationale.textContent = match.rationale;
    
    const chosenResume = emailMsg.selected_resume_file || match.selected_resume;
    if (chosenResume) {
      elements.resumeVariantSelect.value = chosenResume;
      elements.attachedResumeName.textContent = chosenResume;
      const isPdf = chosenResume.endsWith('.pdf');
      elements.attachmentFormatHint.textContent = isPdf ? 'Canonical Document (Adobe PDF)' : 'Canonical Document (Word DOCX)';
    }
  } else {
    const defaultResume = APP_STATE.profile?.active_resume_file || 'Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx';
    elements.attachedResumeName.textContent = defaultResume;
    elements.resumeVariantSelect.value = defaultResume;
  }
  
  // Update Stage Button Label to indicate destination mailbox
  if (elements.btnSaveDraftLabel) {
    const clientName = accInfo.type === 'google' ? 'Gmail' : (accInfo.type === 'imap' ? 'Spectrum' : 'Outlook');
    elements.btnSaveDraftLabel.textContent = `Stage Draft in ${clientName} (${accInfo.accountId})`;
  }
  
  // Draft Reply & Structured Grounding State
  elements.replyBodyText.value = emailMsg.draft_reply || '';
  updateGroundingBadge(emailMsg);
  updateRiskBadge(emailMsg);
}

function updateGroundingBadge(emailMsg) {
  const badge = document.querySelector('.ledger-grounded-badge');
  if (!badge) return;
  if (!emailMsg || !emailMsg.draft_reply) {
    badge.textContent = 'ℹ️ No Draft';
    badge.title = 'No draft reply has been generated for this email.';
    badge.style.background = 'rgba(148, 163, 184, 0.15)';
    badge.style.color = '#94a3b8';
    badge.style.borderColor = 'rgba(148, 163, 184, 0.3)';
    return;
  }
  if (emailMsg.is_grounded && emailMsg.grounding_status === 'GROUNDED') {
    badge.textContent = '🔒 Provenance Grounded';
    badge.title = 'Authoritatively verified against Canonical Career System provenance records';
    badge.style.background = 'rgba(16, 185, 129, 0.15)';
    badge.style.color = '#10b981';
    badge.style.borderColor = 'rgba(16, 185, 129, 0.4)';
  } else if (emailMsg.grounding_status === 'NO_CAREER_CLAIMS_DETECTED') {
    badge.textContent = 'ℹ️ No Career Claims Detected';
    badge.title = 'No career claims detected — no authoritative grounding performed';
    badge.style.background = 'rgba(148, 163, 184, 0.15)';
    badge.style.color = '#94a3b8';
    badge.style.borderColor = 'rgba(148, 163, 184, 0.3)';
  } else {
    badge.textContent = '⚠️ Grounding Validation Required';
    badge.title = 'Draft text is unverified, unprovenanced, or edited; prior grounding authority is invalid.';
    badge.style.background = 'rgba(245, 158, 11, 0.15)';
    badge.style.color = '#f59e0b';
    badge.style.borderColor = 'rgba(245, 158, 11, 0.4)';
  }
}

function updateRiskBadge(emailMsg) {
  const badge = elements.webCockpitRiskBadge || document.getElementById('web-cockpit-risk-badge');
  if (!badge) return;
  if (!emailMsg || !emailMsg.draft_reply || !emailMsg.risk_is_current || !emailMsg.risk_result) {
    badge.style.display = 'none';
    badge.textContent = '';
    return;
  }
  const risk = emailMsg.risk_result;
  const sev = risk.severity || 'SAFE';
  badge.style.display = 'inline-block';
  if (sev === 'SAFE') {
    badge.textContent = '🛡️ Risk: Safe';
    badge.title = risk.second_opinion_summary || 'No risk signals detected.';
    badge.style.background = 'rgba(16, 185, 129, 0.15)';
    badge.style.color = '#10b981';
    badge.style.borderColor = 'rgba(16, 185, 129, 0.4)';
  } else if (sev === 'CAUTION') {
    badge.textContent = '⚠️ Risk: Caution';
    badge.title = risk.second_opinion_summary || 'Review caution advisory.';
    badge.style.background = 'rgba(245, 158, 11, 0.15)';
    badge.style.color = '#f59e0b';
    badge.style.borderColor = 'rgba(245, 158, 11, 0.4)';
  } else {
    badge.textContent = '🛑 Risk: High Risk';
    badge.title = risk.second_opinion_summary || 'High risk signals detected.';
    badge.style.background = 'rgba(239, 68, 68, 0.15)';
    badge.style.color = '#ef4444';
    badge.style.borderColor = 'rgba(239, 68, 68, 0.4)';
  }
}

function renderTriageTable() {
  const tbody = elements.triageTableBody;
  if (!tbody) return;
  tbody.innerHTML = '';
  
  let filtered = APP_STATE.emails;
  if (APP_STATE.activeFilter === 'NOISE') {
    filtered = APP_STATE.emails.filter(e => e.classification?.is_noise);
  } else if (APP_STATE.activeFilter === 'RESUME_REQUEST') {
    filtered = APP_STATE.emails.filter(e => e.classification?.is_resume_request);
  } else if (APP_STATE.activeFilter === 'OTHER') {
    filtered = APP_STATE.emails.filter(e => !e.classification?.is_noise && !e.classification?.is_resume_request);
  }

  // Filter by selected mailbox
  if (APP_STATE.activeNoiseAccountFilter && APP_STATE.activeNoiseAccountFilter !== 'ALL') {
    filtered = filtered.filter(e => {
      const accInfo = getAccountInfoForEmail(e);
      return accInfo.accountId.toLowerCase() === APP_STATE.activeNoiseAccountFilter.toLowerCase();
    });
  }
  
  const totalLabel = document.getElementById('triage-total-label');
  if (totalLabel) totalLabel.textContent = `Showing ${filtered.length} emails`;
  
  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; padding: 2rem; color: var(--text-muted);">
          No emails match the selected category & mailbox filter.
        </td>
      </tr>
    `;
    return;
  }

  filtered.forEach(emailMsg => {
    const tr = document.createElement('tr');
    const accInfo = getAccountInfoForEmail(emailMsg);
    
    let tagClass = 'other';
    let tagLabel = 'Direct / Human';
    if (emailMsg.classification?.category === 'RESUME_REQUEST') {
      tagClass = 'recruiter';
      tagLabel = '🎯 Recruiter / Resume';
    } else if (emailMsg.classification?.category === 'NOISE_PROMOTIONAL') {
      tagClass = 'noise-promo';
      tagLabel = '📢 Promotional Spam';
    } else if (emailMsg.classification?.category === 'NOISE_NEWSLETTER') {
      tagClass = 'noise-news';
      tagLabel = '📰 Newsletter';
    } else if (emailMsg.classification?.category === 'NOISE_NOTIFICATION') {
      tagClass = 'noise-notif';
      tagLabel = '🔔 System Alert';
    }
    
    const isCleaned = emailMsg.status === 'TRASHED';
    
    tr.innerHTML = `
      <td>
        <span class="account-chip ${accInfo.type}" title="Received on ${accInfo.label}">
          ${accInfo.type === 'google' ? '🌐' : (accInfo.type === 'outlook' ? '📬' : '⚡')} ${accInfo.accountId}
        </span>
      </td>
      <td>
        <strong style="font-size: 0.85rem;">${escapeHtml(emailMsg.sender_name)}</strong>
        <div style="font-size: 0.75rem; color: var(--text-muted);">${escapeHtml(emailMsg.sender_email)}</div>
      </td>
      <td>
        <div style="font-weight: 500; color: #e2e8f0; max-width: 260px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(emailMsg.subject)}</div>
        <div style="font-size: 0.75rem; color: var(--text-secondary); max-width: 260px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(emailMsg.preview)}</div>
      </td>
      <td><span class="category-tag ${tagClass}">${tagLabel}</span></td>
      <td style="font-size: 0.775rem; color: var(--text-secondary); max-width: 220px;">
        ${escapeHtml(emailMsg.classification?.reasoning || 'Classified by Aura AI')}
      </td>
      <td>
        ${isCleaned ? 
          '<span style="color: #34d399; font-size: 0.775rem; font-weight: 600;">✓ In Safe Folder</span>' :
          `<button class="btn btn-secondary btn-sm" onclick="quarantineSingleEmail('${emailMsg.id}')" title="Move to cloud safe folder">🛡️ Quarantine</button>`
        }
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function renderNoiseAccountCards() {
  const container = elements.noiseAccountsGrid;
  if (!container) return;
  container.innerHTML = '';

  const accounts = APP_STATE.accounts.length > 0 ? APP_STATE.accounts : [
    { account_id: 'kinlawb@outlook.com', provider: 'MICROSOFT_GRAPH', display_name: 'kinlawb@outlook.com' },
    { account_id: 'brian.kinlaw@outlook.com', provider: 'MICROSOFT_GRAPH', display_name: 'brian.kinlaw@outlook.com' },
    { account_id: 'brian@mavencode.com', provider: 'GMAIL', display_name: 'brian@mavencode.com' },
    { account_id: 'briankkinlaw@gmail.com', provider: 'GMAIL', display_name: 'briankkinlaw@gmail.com' },
    { account_id: 'briankinlaw@satx.rr.com', provider: 'IMAP', display_name: 'briankinlaw@satx.rr.com' }
  ];

  accounts.forEach(acc => {
    const accId = acc.account_id || acc.email_address || '';
    const accEmails = APP_STATE.emails.filter(e => {
      const info = getAccountInfoForEmail(e);
      return info.accountId.toLowerCase() === accId.toLowerCase();
    });

    const noiseRemaining = accEmails.filter(e => e.classification?.is_noise && e.status !== 'TRASHED').length;
    const noiseCleaned = accEmails.filter(e => e.classification?.is_noise && e.status === 'TRASHED').length;
    const recruiters = accEmails.filter(e => e.classification?.is_resume_request && e.status !== 'TRASHED').length;
    const isClean = noiseRemaining === 0;

    let provIcon = '📬';
    let provLabel = 'Microsoft Graph (Outlook)';
    if (acc.provider === 'GMAIL' || accId.includes('gmail.com') || accId.includes('mavencode.com')) {
      provIcon = '🌐';
      provLabel = 'Google Workspace / Gmail';
    } else if (acc.provider === 'IMAP' || accId.includes('satx.rr.com')) {
      provIcon = '⚡';
      provLabel = 'Spectrum IMAP';
    }

    const card = document.createElement('div');
    card.className = `noise-acc-card ${isClean ? 'is-clean' : ''}`;
    card.innerHTML = `
      <div>
        <div class="noise-acc-card-header">
          <span style="font-size: 1.1rem;">${provIcon}</span>
          <span class="noise-clean-badge ${isClean ? 'zero-noise' : 'has-noise'}">
            ${isClean ? '✓ 100% Noise-Free' : `⚠️ ${noiseRemaining} Noise in Inbox`}
          </span>
        </div>
        <div class="noise-acc-email" style="margin-top: 6px;">${escapeHtml(accId)}</div>
        <div class="noise-acc-provider">${provLabel}</div>
      </div>
      
      <div>
        <div class="noise-acc-stats-row">
          <span>In-Inbox Recruiters:</span>
          <strong style="color: #93c5fd;">${recruiters}</strong>
        </div>
        <div class="noise-acc-stats-row">
          <span>Quarantined Safe:</span>
          <strong style="color: #34d399;">${noiseCleaned}</strong>
        </div>
        ${!isClean ? `
          <button class="btn btn-secondary btn-sm noise-acc-clean-action" onclick="cleanNoiseForAccount('${escapeHtml(accId)}')">
            🧹 Clean ${noiseRemaining} Noise Emails
          </button>
        ` : `
          <div style="font-size: 0.75rem; color: #34d399; text-align: center; margin-top: 8px; font-weight: 600;">
            ● Inbox fully protected
          </div>
        `}
      </div>
    `;
    container.appendChild(card);
  });

  renderTriageAccountFilterButtons(accounts);
}

function updateNoiseBatchCleanButtonLabel() {
  const btn = elements.btnBatchCleanNoise;
  if (!btn) return;
  if (!APP_STATE.activeNoiseAccountFilter || APP_STATE.activeNoiseAccountFilter === 'ALL') {
    btn.innerHTML = '<span>🧹</span> Clean Loaded Noise (All Mailboxes)';
  } else {
    btn.innerHTML = `<span>🧹</span> Clean Loaded Noise (<code>${escapeHtml(APP_STATE.activeNoiseAccountFilter)}</code>)`;
  }
}

function renderTriageAccountFilterButtons(accounts) {
  const container = elements.triageAccountFilterGroup;
  if (!container) return;
  
  const allBtn = container.querySelector('[data-account-filter="ALL"]');
  container.innerHTML = '';
  if (allBtn) {
    container.appendChild(allBtn);
  } else {
    const btn = document.createElement('button');
    btn.className = `btn btn-secondary btn-sm ${APP_STATE.activeNoiseAccountFilter === 'ALL' ? 'active-filter' : ''}`;
    btn.setAttribute('data-account-filter', 'ALL');
    btn.textContent = 'All Mailboxes';
    btn.addEventListener('click', () => {
      container.querySelectorAll('button').forEach(b => b.classList.remove('active-filter'));
      btn.classList.add('active-filter');
      APP_STATE.activeNoiseAccountFilter = 'ALL';
      updateNoiseBatchCleanButtonLabel();
      renderTriageTable();
    });
    container.appendChild(btn);
  }

  accounts.forEach(acc => {
    const accId = acc.account_id || acc.email_address;
    if (!accId) return;
    const btn = document.createElement('button');
    btn.className = `btn btn-secondary btn-sm ${APP_STATE.activeNoiseAccountFilter.toLowerCase() === accId.toLowerCase() ? 'active-filter' : ''}`;
    btn.setAttribute('data-account-filter', accId);
    btn.textContent = accId.split('@')[0];
    btn.title = accId;
    btn.addEventListener('click', () => {
      container.querySelectorAll('button').forEach(b => b.classList.remove('active-filter'));
      btn.classList.add('active-filter');
      APP_STATE.activeNoiseAccountFilter = accId;
      updateNoiseBatchCleanButtonLabel();
      renderTriageTable();
    });
    container.appendChild(btn);
  });
  
  updateNoiseBatchCleanButtonLabel();
}

function renderVaultGrid() {
  const container = elements.vaultGridContainer;
  if (!container || !APP_STATE.canonicalData) return;
  container.innerHTML = '';
  
  const standards = APP_STATE.canonicalData.standard_canonicals || [];
  const targeted = APP_STATE.canonicalData.targeted_customs || [];
  const truth = APP_STATE.canonicalData.source_of_truth_docs || [];
  const masters = APP_STATE.canonicalData.master_variants || [];
  
  if (elements.vaultCountAll) elements.vaultCountAll.textContent = APP_STATE.resumes.length + truth.length;
  if (elements.vaultCountStandard) elements.vaultCountStandard.textContent = standards.length;
  if (elements.vaultCountTargeted) elements.vaultCountTargeted.textContent = targeted.length;
  if (elements.vaultCountTruth) elements.vaultCountTruth.textContent = truth.length;
  
  let list = [];
  if (APP_STATE.activeVaultFilter === 'ALL') {
    list = [...standards, ...targeted, ...masters, ...truth];
  } else if (APP_STATE.activeVaultFilter === 'standard_canonical') {
    list = standards;
  } else if (APP_STATE.activeVaultFilter === 'targeted_custom') {
    list = targeted;
  } else if (APP_STATE.activeVaultFilter === 'source_of_truth') {
    list = truth;
  }
  
  if (APP_STATE.vaultSearchQuery) {
    const q = APP_STATE.vaultSearchQuery.toLowerCase();
    list = list.filter(r => 
      r.filename.toLowerCase().includes(q) || 
      r.display_title.toLowerCase().includes(q) ||
      (r.snippet && r.snippet.toLowerCase().includes(q))
    );
  }
  
  if (list.length === 0) {
    container.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <div class="empty-state-icon">🔍</div>
        <p>No canonical documents match your filter.</p>
      </div>`;
    return;
  }
  
  const activeDefault = APP_STATE.profile?.active_resume_file || '';
  
  list.forEach(r => {
    const card = document.createElement('div');
    card.className = 'vault-card';
    const isCurrentActive = (r.filename === activeDefault);
    
    card.innerHTML = `
      <div>
        <div class="vault-card-header">
          <span class="lens-pill" style="background: ${r.lens_color}22; color: ${r.lens_color}; border: 1px solid ${r.lens_color}55;">
            ${r.lens_badge || 'Standard'}
          </span>
          <span class="format-badge ${r.format}">${r.format}</span>
        </div>
        <div class="vault-card-title" style="margin-top: 8px;">${r.display_title}</div>
        <div class="vault-card-headline">${r.headline || r.filename}</div>
        <div class="vault-card-snippet" style="margin-top: 8px;">${r.snippet}</div>
      </div>
      
      <div>
        <div class="vault-card-footer">
          <span>${r.size_kb} KB • ${r.last_modified}</span>
          <button class="btn btn-secondary btn-sm" onclick="setActiveResume('${r.filename}')">
            ${isCurrentActive ? '★ Active Default' : 'Set as Default'}
          </button>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

window.setActiveResume = async function(filename) {
  if (!APP_STATE.profile) return;
  APP_STATE.profile.active_resume_file = filename;
  showToast(`Setting ${filename} as active default resume...`, 'info');
  
  try {
    await fetch('/api/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(APP_STATE.profile)
    });
    showToast(`Default resume updated to ${filename}`, 'success');
    await refreshAll();
  } catch (err) {
    showToast('Failed to update default: ' + err.message, 'error');
  }
};

// --- Event Handlers & User Actions ---

function setupEventListeners() {
  // Sync Inbox
  elements.btnSyncInbox.addEventListener('click', async () => {
    showToast('Syncing cloud inboxes and triaging with AI...', 'info');
    elements.btnSyncInbox.disabled = true;
    try {
      const res = await fetch('/api/emails/sync', { method: 'POST' });
      const data = await res.json();
      if (data.sync_stats && data.sync_stats.accounts_failed > 0) {
        showToast(`Sync finished with warnings: ${data.sync_stats.accounts_synced} mailboxes synced, ${data.sync_stats.accounts_failed} failed.`, 'error');
      } else {
        showToast(`Sync complete! Found ${data.resume_requests_found} recruiter reachouts and ${data.noise_detected} noise items.`, 'success');
      }
      await refreshAll();
    } catch (err) {
      showToast('Sync failed: ' + err.message, 'error');
    } finally {
      elements.btnSyncInbox.disabled = false;
    }
  });

  // Open Accounts Tab
  elements.btnOpenAccounts.addEventListener('click', () => {
    const accTab = document.querySelector('[data-tab="connected-accounts"]');
    if (accTab) accTab.click();
  });

  if (elements.btnAddAccountModal) {
    elements.btnAddAccountModal.addEventListener('click', () => {
      elements.accountAuthModal.classList.add('active');
    });
  }

  // Auth Tabs
  if (elements.authTabMsal) {
    elements.authTabMsal.addEventListener('click', () => {
      elements.authTabMsal.classList.add('active-filter');
      if (elements.authTabGoogle) elements.authTabGoogle.classList.remove('active-filter');
      if (elements.authTabImap) elements.authTabImap.classList.remove('active-filter');
      if (elements.authPanelMsal) elements.authPanelMsal.style.display = 'block';
      if (elements.authPanelGoogle) elements.authPanelGoogle.style.display = 'none';
      if (elements.authPanelImap) elements.authPanelImap.style.display = 'none';
    });
  }

  if (elements.authTabGoogle) {
    elements.authTabGoogle.addEventListener('click', () => {
      elements.authTabGoogle.classList.add('active-filter');
      if (elements.authTabMsal) elements.authTabMsal.classList.remove('active-filter');
      if (elements.authTabImap) elements.authTabImap.classList.remove('active-filter');
      if (elements.authPanelGoogle) elements.authPanelGoogle.style.display = 'block';
      if (elements.authPanelMsal) elements.authPanelMsal.style.display = 'none';
      if (elements.authPanelImap) elements.authPanelImap.style.display = 'none';
    });
  }

  if (elements.authTabImap) {
    elements.authTabImap.addEventListener('click', () => {
      elements.authTabImap.classList.add('active-filter');
      if (elements.authTabMsal) elements.authTabMsal.classList.remove('active-filter');
      if (elements.authTabGoogle) elements.authTabGoogle.classList.remove('active-filter');
      if (elements.authPanelImap) elements.authPanelImap.style.display = 'block';
      if (elements.authPanelMsal) elements.authPanelMsal.style.display = 'none';
      if (elements.authPanelGoogle) elements.authPanelGoogle.style.display = 'none';
    });
  }

  // Google OAuth Flow
  if (elements.btnStartGoogleAuth) {
    elements.btnStartGoogleAuth.addEventListener('click', async () => {
      try {
        const res = await fetch('/api/auth/google/url');
        const data = await res.json();
        if (res.ok && data.auth_url) {
          window.location.href = data.auth_url;
        } else {
          showToast(data.detail || 'Please configure Google OAuth Client ID in Settings first, or connect via IMAP with a Gmail App Password.', 'warning');
        }
      } catch (err) {
        showToast('Error initiating Google sign-in: ' + err.message, 'error');
      }
    });
  }

  if (elements.btnSubmitGoogleCode) {
    elements.btnSubmitGoogleCode.addEventListener('click', async () => {
      const codeVal = (elements.googleAuthCodeInput.value || '').trim();
      if (!codeVal) {
        showToast('Please paste the Google authorization code or callback URL.', 'error');
        return;
      }
      elements.btnSubmitGoogleCode.disabled = true;
      elements.btnSubmitGoogleCode.textContent = 'Verifying Google Code...';
      try {
        const targetAcc = elements.accountAuthModal.dataset.accountId || '';
        const res = await fetch('/api/auth/google/submit-code', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code: codeVal, account_id: targetAcc })
        });
        const data = await res.json();
        if (res.ok && data.success) {
          showToast(`Connected to Google Cloud API as ${data.account_id}!`, 'success');
          elements.accountAuthModal.classList.remove('active');
          await refreshAll();
        } else {
          showToast(data.detail || data.safe_message || 'Google token exchange failed.', 'error');
        }
      } catch (err) {
        showToast('Google exchange error: ' + err.message, 'error');
      } finally {
        elements.btnSubmitGoogleCode.disabled = false;
        elements.btnSubmitGoogleCode.textContent = 'Verify & Connect Google Account';
      }
    });
  }

  // MSAL Device Flow
  elements.btnStartDeviceFlow.addEventListener('click', async () => {
    elements.btnStartDeviceFlow.disabled = true;
    elements.btnStartDeviceFlow.textContent = 'Initiating Microsoft Login...';
    try {
      const res = await fetch('/api/auth/msal/device-code', { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.user_code) {
        elements.deviceCodeDisplay.textContent = data.user_code;
        const linkAnchor = document.getElementById('device-link-anchor');
        const verifyUri = data.verification_uri || 'https://www.microsoft.com/link';
        if (linkAnchor) {
          linkAnchor.href = verifyUri;
          linkAnchor.textContent = verifyUri.replace(/^https?:\/\/(www\.)?/, '');
        }
        elements.deviceFlowDisplay.style.display = 'block';
        elements.devicePollStatus.textContent = `Waiting for you to enter code at ${verifyUri.replace(/^https?:\/\/(www\.)?/, '')}...`;
        
        // Start polling
        const targetAcc = elements.accountAuthModal.dataset.accountId || '';
        if (APP_STATE.devicePollInterval) clearInterval(APP_STATE.devicePollInterval);
        APP_STATE.devicePollInterval = setInterval(async () => {
          try {
            const pollRes = await fetch('/api/auth/msal/device-code/poll', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ account_id: targetAcc })
            });
            const pollData = await pollRes.json();
            if (pollData.success) {
              clearInterval(APP_STATE.devicePollInterval);
              showToast(`Connected to Microsoft Graph as ${pollData.account_id}!`, 'success');
              elements.accountAuthModal.classList.remove('active');
              await refreshAll();
            } else if (!pollData.retryable) {
              elements.devicePollStatus.textContent = pollData.safe_message;
            }
          } catch (e) {}
        }, 5000);
      } else {
        showToast(data.detail || 'Failed to start device flow.', 'error');
      }
    } catch (err) {
      showToast('Error: ' + err.message, 'error');
    } finally {
      elements.btnStartDeviceFlow.disabled = false;
      elements.btnStartDeviceFlow.textContent = 'Start Microsoft Device Sign-In Flow';
    }
  });

  // Direct MSAL Browser OAuth Flow
  if (elements.btnStartDirectMsal) {
    elements.btnStartDirectMsal.addEventListener('click', async () => {
      try {
        const targetAcc = elements.accountAuthModal.dataset.accountId || '';
        const urlParam = targetAcc ? `?account_id=${encodeURIComponent(targetAcc)}` : '';
        const res = await fetch(`/api/auth/msal/url${urlParam}`);
        const data = await res.json();
        if (res.ok && data.auth_url) {
          window.location.href = data.auth_url;
        } else {
          showToast(data.detail || 'Microsoft Client ID not configured.', 'warning');
        }
      } catch (err) {
        showToast('Error initiating Microsoft direct login: ' + err.message, 'error');
      }
    });
  }

  // Save IMAP Auth
  elements.btnSaveImapAuth.addEventListener('click', async () => {
    const emailAddr = document.getElementById('imap-email-input').value.trim();
    const pwd = document.getElementById('imap-password-input').value.trim();
    const imapServer = document.getElementById('imap-server-input').value.trim();
    
    if (!emailAddr || !pwd) {
      showToast('Email address and password required.', 'error');
      return;
    }
    
    elements.btnSaveImapAuth.disabled = true;
    elements.btnSaveImapAuth.textContent = 'Verifying & Storing in Keychain...';
    try {
      const res = await fetch('/api/auth/imap', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: emailAddr,
          password: pwd,
          imap_server: imapServer
        })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        showToast(`Connected to IMAP mailbox for ${emailAddr}!`, 'success');
        elements.accountAuthModal.classList.remove('active');
        await refreshAll();
      } else {
        showToast(data.detail || data.safe_message || 'IMAP verification failed.', 'error');
      }
    } catch (err) {
      showToast('Connection failed: ' + err.message, 'error');
    } finally {
      elements.btnSaveImapAuth.disabled = false;
      elements.btnSaveImapAuth.textContent = 'Connect & Save to Keychain';
    }
  });

  // Resume Dropdown Change
  if (elements.resumeVariantSelect) {
    elements.resumeVariantSelect.addEventListener('change', (e) => {
      const selected = e.target.value;
      elements.attachedResumeName.textContent = selected;
      const isPdf = selected.endsWith('.pdf');
      elements.attachmentFormatHint.textContent = isPdf ? 'Canonical Document (Adobe PDF)' : 'Canonical Document (Word DOCX)';
      
      const emailMsg = APP_STATE.emails.find(em => em.id === APP_STATE.selectedEmailId);
      if (emailMsg) {
        emailMsg.selected_resume_file = selected;
      }
      showToast(`Attached resume updated to ${selected}. Click Regenerate to adapt pitch.`, 'info');
    });
  }

  // Manual Edit Listener on Reply Textarea (Step 7 & 8)
  if (elements.replyBodyText) {
    elements.replyBodyText.addEventListener('input', () => {
      // Invalidate in-flight risk request tokens immediately on edit
      APP_STATE.activeRiskToken = null;
      APP_STATE.riskRequestGeneration++;

      const emailMsg = APP_STATE.emails.find(em => em.id === APP_STATE.selectedEmailId);
      if (emailMsg) {
        emailMsg.draft_reply = elements.replyBodyText.value;
        const hadDraftAuthority = !!emailMsg.draft_id || emailMsg.is_grounded;
        const priorDraftId = emailMsg.draft_id;

        // Immediately clear browser displayed authority (fail closed)
        emailMsg.is_grounded = false;
        emailMsg.grounding_status = 'UNVERIFIED';
        emailMsg.draft_id = null;
        emailMsg.claim_bindings = [];
        emailMsg.draft_text_hash = null;
        emailMsg.risk_result = null;
        emailMsg.risk_draft_id = null;
        emailMsg.risk_draft_text_hash = null;
        emailMsg.risk_is_current = false;
        updateGroundingBadge(emailMsg);
        updateRiskBadge(emailMsg);

        // Trigger persistent server invalidation once per draft lifecycle on first edit
        if (hadDraftAuthority && priorDraftId && !emailMsg.invalidation_issued) {
          emailMsg.invalidation_issued = true;
          fetch(`/api/emails/${encodeURIComponent(emailMsg.id)}/invalidate-draft`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ draft_id: priorDraftId })
          }).catch(err => console.error('Failed to issue draft invalidation', err));
        }
      }
    });
  }

  // Regenerate Draft
  elements.btnRegenerateDraft.addEventListener('click', async () => {
    if (!APP_STATE.selectedEmailId) return;
    // Invalidate active risk token on regeneration
    APP_STATE.activeRiskToken = null;
    APP_STATE.riskRequestGeneration++;

    const tone = elements.toneSelector.value;
    const chosenResume = elements.resumeVariantSelect.value;
    showToast(`Generating ${tone} response grounded in ${chosenResume}...`, 'info');
    
    try {
      const res = await fetch(`/api/emails/${encodeURIComponent(APP_STATE.selectedEmailId)}/generate-reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tone: tone, selected_resume: chosenResume })
      });
      const data = await res.json();
      elements.replyBodyText.value = data.draft_reply || '';

      const emailMsg = APP_STATE.emails.find(em => em.id === APP_STATE.selectedEmailId);
      if (emailMsg) {
        emailMsg.draft_reply = data.draft_reply;
        emailMsg.draft_id = data.draft_id;
        emailMsg.claim_bindings = data.claim_bindings || [];
        emailMsg.grounding_status = data.grounding_status;
        emailMsg.is_grounded = data.is_grounded || false;
        emailMsg.draft_text_hash = data.draft_text_hash || null;
        emailMsg.risk_result = null;
        emailMsg.risk_draft_id = null;
        emailMsg.risk_draft_text_hash = null;
        emailMsg.risk_is_current = false;
        emailMsg.invalidation_issued = false;
        updateGroundingBadge(emailMsg);
        updateRiskBadge(emailMsg);
      }

      if (data.is_grounded) {
        showToast('Provenance-backed claims verified', 'success');
      } else if (data.grounding_status === 'NO_CAREER_CLAIMS_DETECTED') {
        showToast('Draft generated — no career claims detected', 'info');
      } else {
        showToast('Draft generated — grounding validation required', 'info');
      }
      await fetchEmails();
    } catch (err) {
      showToast('Generation failed: ' + err.message, 'error');
    }
  });

  // Risk Check Button
  if (elements.btnRiskCheck) {
    elements.btnRiskCheck.addEventListener('click', async () => {
      if (!APP_STATE.selectedEmailId) return;
      const emailMsg = APP_STATE.emails.find(em => em.id === APP_STATE.selectedEmailId);
      const replyBody = elements.replyBodyText.value;

      // Unique token and generation snapshot for asynchronous race prevention
      const currentToken = 'risk_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
      const currentGen = ++APP_STATE.riskRequestGeneration;
      APP_STATE.activeRiskToken = currentToken;

      const capturedEmailId = APP_STATE.selectedEmailId;
      const capturedDraftId = emailMsg ? emailMsg.draft_id : null;
      const capturedDraftText = replyBody;
      const capturedDraftTextHash = emailMsg ? emailMsg.draft_text_hash : null;
      const capturedSelectedEmailId = APP_STATE.selectedEmailId;

      showToast('Running Gemini Risk Sentinel audit on current draft...', 'info');
      elements.btnRiskCheck.disabled = true;

      const snapshot = {
        token: currentToken,
        generation: currentGen,
        selectedEmailId: capturedSelectedEmailId,
        emailId: capturedEmailId,
        draftId: capturedDraftId,
        draftText: capturedDraftText,
        draftTextHash: capturedDraftTextHash
      };

      try {
        const payload = {
          draft_id: emailMsg ? emailMsg.draft_id : null,
          draft_text: replyBody,
          claim_bindings: emailMsg ? emailMsg.claim_bindings : []
        };
        const res = await fetch(`/api/emails/${encodeURIComponent(APP_STATE.selectedEmailId)}/risk-check`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();

        // Check if asynchronous state changed during network transit using RiskValidator
        const validator = (typeof RiskValidator !== 'undefined') ? RiskValidator : (typeof require !== 'undefined' ? require('./risk_validator.js') : null);

        const currentState = {
          activeToken: APP_STATE.activeRiskToken,
          generation: APP_STATE.riskRequestGeneration,
          selectedEmailId: APP_STATE.selectedEmailId,
          emailMsg: emailMsg,
          currentText: elements.replyBodyText.value
        };

        const staleCheck = validator ? validator.isRiskResponseStale(snapshot, currentState) : {
          isStale: (
            APP_STATE.activeRiskToken !== currentToken ||
            APP_STATE.riskRequestGeneration !== currentGen ||
            APP_STATE.selectedEmailId !== capturedSelectedEmailId ||
            !emailMsg ||
            emailMsg.id !== capturedEmailId ||
            emailMsg.draft_id !== capturedDraftId ||
            elements.replyBodyText.value !== capturedDraftText
          ),
          reason: 'Stale client state'
        };

        if (staleCheck.isStale) {
          console.warn(`Stale asynchronous risk response discarded: ${staleCheck.reason}`);
          return;
        }

        // Validate response structure and cryptographic draft_text_hash equality
        const valCheck = validator ? validator.validateRiskResponse(data, snapshot) : {
          isValid: (
            data &&
            typeof data === 'object' &&
            ['SUCCESS', 'VALIDATION_FAILED', 'DIVERGENCE_DETECTED', 'INVALIDATION_PERSISTENCE_FAILURE'].includes(data.status) &&
            data.email_id === capturedEmailId &&
            (data.status !== 'SUCCESS' || (
              data.draft_id === capturedDraftId &&
              data.draft_text_hash === capturedDraftTextHash &&
              data.risk_is_current === true &&
              data.risk &&
              typeof data.risk.severity === 'string' &&
              typeof data.risk.recommended_action === 'string'
            ))
          ),
          isMalformed: true,
          reason: 'Invalid response structure or hash mismatch'
        };

        if (!valCheck.isValid) {
          console.error(`Malformed or invalid risk response received: ${valCheck.reason}. Failing closed.`);
          emailMsg.risk_is_current = false;
          emailMsg.risk_result = null;
          emailMsg.is_grounded = false;
          emailMsg.grounding_status = 'UNVERIFIED';
          updateGroundingBadge(emailMsg);
          updateRiskBadge(emailMsg);
          showToast(`Risk check verification failed: ${valCheck.reason}`, 'error');
          return;
        }

        if (data.status === 'SUCCESS' && data.risk_is_current) {
          emailMsg.risk_result = data.risk;
          emailMsg.risk_draft_id = data.draft_id;
          emailMsg.risk_draft_text_hash = data.draft_text_hash;
          emailMsg.risk_is_current = true;
          emailMsg.is_grounded = data.is_grounded;
          emailMsg.grounding_status = data.grounding_status;
          showToast(`Risk check: ${data.risk?.severity || 'Complete'} (${data.risk?.recommended_action || 'PROCEED'})`, 'success');
        } else {
          emailMsg.is_grounded = false;
          emailMsg.grounding_status = data.grounding_status || 'UNVERIFIED';
          emailMsg.risk_is_current = false;
          emailMsg.risk_result = data.risk || null;
          showToast(`Risk check: ${data.validation_summary || 'Validation Required'}`, 'warning');
        }
        updateGroundingBadge(emailMsg);
        updateRiskBadge(emailMsg);
      } catch (err) {
        showToast('Risk check failed: ' + err.message, 'error');
      } finally {
        elements.btnRiskCheck.disabled = false;
      }
    });
  }

  // Stage in Cloud Drafts
  if (elements.btnSaveDraft) {
    elements.btnSaveDraft.addEventListener('click', async () => {
      if (!APP_STATE.selectedEmailId) return;
      const emailMsg = APP_STATE.emails.find(em => em.id === APP_STATE.selectedEmailId);
      const replyBody = elements.replyBodyText.value;
      const chosenResume = elements.resumeVariantSelect.value;
      const accInfo = getAccountInfoForEmail(emailMsg);
      const clientName = accInfo.type === 'google' ? 'Gmail' : (accInfo.type === 'imap' ? 'Spectrum' : 'Outlook');
      showToast(`Staging draft in ${clientName} (${accInfo.accountId}) with '${chosenResume}' attached...`, 'info');

      try {
        const payload = {
          reply_body: replyBody,
          resume_filename: chosenResume,
          draft_id: emailMsg ? emailMsg.draft_id : null,
          claim_bindings: emailMsg ? emailMsg.claim_bindings : []
        };
        const res = await fetch(`/api/emails/${encodeURIComponent(APP_STATE.selectedEmailId)}/save-draft`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (emailMsg && data) {
          emailMsg.is_grounded = data.is_grounded || false;
          emailMsg.grounding_status = data.grounding_status || 'UNVERIFIED';
          updateGroundingBadge(emailMsg);
        }
        if (data.success) {
          showToast(data.safe_message || `✓ Draft successfully staged in ${clientName} Drafts folder (${accInfo.accountId})! Review and send in ${clientName}.`, 'success');
        } else {
          showToast(`Draft staging error: ${data.safe_message}`, 'error');
        }
        await refreshAll();
      } catch (err) {
        showToast('Failed to stage draft: ' + err.message, 'error');
      }
    });
  }

  // Mark as Replied & Schedule Follow-up
  if (elements.btnMarkReplied) {
    elements.btnMarkReplied.addEventListener('click', async () => {
      if (!APP_STATE.selectedEmailId) return;
      const emailMsg = APP_STATE.emails.find(em => em.id === APP_STATE.selectedEmailId);
      const accInfo = getAccountInfoForEmail(emailMsg);
      showToast(`Marking response sent and scheduling follow-up for ${emailMsg?.sender_name || 'recruiter'}...`, 'info');

      try {
        const res = await fetch(`/api/emails/${encodeURIComponent(APP_STATE.selectedEmailId)}/mark-replied`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            followup_days: 3,
            notes: `Sent response from ${accInfo.accountId} via ${accInfo.provider}`
          })
        });
        const data = await res.json();
        if (res.ok) {
          showToast(`✓ Marked as Replied! Follow-up reminder scheduled for 3 business days.`, 'success');
        } else {
          showToast(`Error: ${data.detail || 'Failed to mark replied'}`, 'error');
        }
        await refreshAll();
      } catch (err) {
        showToast('Failed to mark replied: ' + err.message, 'error');
      }
    });
  }

  // Recruiter Queue Sub-Filter Buttons
  const queueFilterBtns = [
    { btn: elements.filterBtnPending, filter: 'pending' },
    { btn: elements.filterBtnStaged, filter: 'staged' },
    { btn: elements.filterBtnReplied, filter: 'replied' },
    { btn: elements.filterBtnAll, filter: 'all' }
  ];

  queueFilterBtns.forEach(({ btn, filter }) => {
    if (btn) {
      btn.addEventListener('click', () => {
        queueFilterBtns.forEach(item => item.btn?.classList.remove('active-filter'));
        btn.classList.add('active-filter');
        APP_STATE.queueFilter = filter;
        renderRecruiterList();
      });
    }
  });

  // Follow-up Sub-Filters
  const followupFilterBtns = [
    { btn: elements.fuFilterPending, filter: 'pending' },
    { btn: elements.fuFilterCompleted, filter: 'completed' },
    { btn: elements.fuFilterAll, filter: 'all' }
  ];

  followupFilterBtns.forEach(({ btn, filter }) => {
    if (btn) {
      btn.addEventListener('click', () => {
        followupFilterBtns.forEach(item => item.btn?.classList.remove('active-filter'));
        btn.classList.add('active-filter');
        APP_STATE.followupFilter = filter;
        renderFollowups();
      });
    }
  });

  // Orchestrate Pipeline Hero Button
  if (elements.btnAddOrchestratePipeline) {
    elements.btnAddOrchestratePipeline.addEventListener('click', () => {
      if (typeof window.orchestratePipeline === 'function') {
        window.orchestratePipeline();
      }
    });
  }

  // Add Custom Follow-up Modal
  if (elements.btnAddCustomFollowup) {
    elements.btnAddCustomFollowup.addEventListener('click', () => {
      if (elements.fuDateInput) {
        const d = new Date();
        d.setDate(d.getDate() + 3);
        elements.fuDateInput.value = d.toISOString().split('T')[0];
      }
      if (elements.followupModal) elements.followupModal.classList.add('active');
    });
  }

  if (elements.followupModalCloseBtn) {
    elements.followupModalCloseBtn.addEventListener('click', () => {
      if (elements.followupModal) elements.followupModal.classList.remove('active');
    });
  }

  if (elements.btnCancelFollowup) {
    elements.btnCancelFollowup.addEventListener('click', () => {
      if (elements.followupModal) elements.followupModal.classList.remove('active');
    });
  }

  if (elements.btnSaveCustomFollowup) {
    elements.btnSaveCustomFollowup.addEventListener('click', async () => {
      const roleTitle = elements.fuRoleInput?.value.trim() || 'Executive Outreach';
      const recruiterName = elements.fuRecruiterInput?.value.trim() || 'Recruiter';
      const companyName = elements.fuCompanyInput?.value.trim() || 'Hiring Organization';
      const dueDate = elements.fuDateInput?.value;
      const notes = elements.fuNotesInput?.value.trim();

      if (!dueDate) {
        showToast('Please provide a follow-up due date.', 'warning');
        return;
      }

      try {
        const payload = {
          role_title: roleTitle,
          title: roleTitle,
          recruiter_name: recruiterName,
          company_name: companyName,
          company: companyName,
          due_date: dueDate,
          notes: notes || `Follow-up scheduled with ${recruiterName} (${companyName}) regarding ${roleTitle}.`
        };
        const res = await fetch('/api/followups', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          showToast('Follow-up reminder scheduled!', 'success');
          if (elements.followupModal) elements.followupModal.classList.remove('active');
          if (elements.fuRoleInput) elements.fuRoleInput.value = '';
          if (elements.fuRecruiterInput) elements.fuRecruiterInput.value = '';
          if (elements.fuCompanyInput) elements.fuCompanyInput.value = '';
          if (elements.fuNotesInput) elements.fuNotesInput.value = '';
          await fetchFollowups();
        } else {
          const data = await res.json();
          showToast(`Error: ${data.detail || 'Could not create follow-up'}`, 'error');
        }
      } catch (err) {
        showToast('Failed to save follow-up: ' + err.message, 'error');
      }
    });
  }

  // Copy Draft Response
  if (elements.btnCopyDraft) {
    elements.btnCopyDraft.addEventListener('click', () => {
      const textToCopy = elements.replyBodyText.value.trim();
      if (!textToCopy) {
        showToast('No draft text to copy.', 'warning');
        return;
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(textToCopy);
      } else {
        const temp = document.createElement('textarea');
        temp.value = textToCopy;
        document.body.appendChild(temp);
        temp.select();
        document.execCommand('copy');
        document.body.removeChild(temp);
      }
      showToast('Response text copied to clipboard! Ready to paste into mail client.', 'success');
    });
  }

  // Vault Refresh
  if (elements.btnRefreshResumes) {
    elements.btnRefreshResumes.addEventListener('click', async () => {
      showToast('Re-scanning local canonical directories on disk...', 'info');
      await fetchCanonicalResumes(true);
      showToast(`Scan complete: indexed ${APP_STATE.resumes.length} canonical resumes.`, 'success');
    });
  }

  // Vault Category Filter Buttons
  const vaultFilterBtns = document.querySelectorAll('#vault-category-filter button');
  vaultFilterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      vaultFilterBtns.forEach(b => b.classList.remove('active-filter'));
      btn.classList.add('active-filter');
      APP_STATE.activeVaultFilter = btn.getAttribute('data-vault-filter');
      renderVaultGrid();
    });
  });

  // Vault Search Input
  if (elements.vaultSearchInput) {
    elements.vaultSearchInput.addEventListener('input', (e) => {
      APP_STATE.vaultSearchQuery = e.target.value;
      renderVaultGrid();
    });
  }

  // Ledger Modal
  if (elements.btnOpenLedgerModal) {
    elements.btnOpenLedgerModal.addEventListener('click', async () => {
      elements.ledgerModal.classList.add('active');
      elements.ledgerTextViewer.textContent = 'Loading Accomplishment Ledger from disk...';
      try {
        const res = await fetch('/api/canonical/ledger');
        const data = await res.json();
        elements.ledgerTextViewer.textContent = data.ledger || 'No ledger text found on disk.';
      } catch (err) {
        elements.ledgerTextViewer.textContent = 'Error loading ledger: ' + err.message;
      }
    });
  }

  if (elements.ledgerModalCloseBtn) {
    elements.ledgerModalCloseBtn.addEventListener('click', () => elements.ledgerModal.classList.remove('active'));
  }
  if (elements.btnCloseLedger) {
    elements.btnCloseLedger.addEventListener('click', () => elements.ledgerModal.classList.remove('active'));
  }
  if (elements.modalCloseBtn) {
    elements.modalCloseBtn.addEventListener('click', () => {
      elements.accountAuthModal.classList.remove('active');
      if (APP_STATE.devicePollInterval) clearInterval(APP_STATE.devicePollInterval);
    });
  }

  // Orchestrate All Inboxes Noise
  if (elements.btnOrchestrateAllNoise) {
    elements.btnOrchestrateAllNoise.addEventListener('click', async () => {
      await orchestrateAllInboxesNoise();
    });
  }

  // Batch Clean Noise (Current View)
  if (elements.btnBatchCleanNoise) {
    elements.btnBatchCleanNoise.addEventListener('click', async () => {
      showToast('Relocating noise emails to cloud safe folder...', 'info');
      try {
        const payload = APP_STATE.activeNoiseAccountFilter !== 'ALL' ? { account_id: APP_STATE.activeNoiseAccountFilter } : {};
        const res = await fetch('/api/emails/clean-noise', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        showToast(data.message || `Cleaned ${data.cleaned_count} emails.`, 'success');
        await refreshAll();
      } catch (err) {
        showToast('Cleanup failed: ' + err.message, 'error');
      }
    });
  }

  // Triage Filter Buttons
  const filterBtns = document.querySelectorAll('#triage-filter-group button');
  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => b.classList.remove('active-filter'));
      btn.classList.add('active-filter');
      APP_STATE.activeFilter = btn.getAttribute('data-filter');
      renderTriageTable();
    });
  });

  // Candidate Profile Save
  elements.btnSaveProfile.addEventListener('click', async () => {
    const histEmailsRaw = document.getElementById('prof-historical-emails')?.value || '';
    const historicalAccounts = histEmailsRaw.split(',').map(s => s.trim()).filter(Boolean);

    const payload = {
      full_name: document.getElementById('prof-name').value,
      current_title: document.getElementById('prof-title').value,
      summary_bio: document.getElementById('prof-bio').value,
      core_skills: document.getElementById('prof-skills').value.split(',').map(s => s.trim()).filter(Boolean),
      target_roles: document.getElementById('prof-target-roles').value.split(',').map(s => s.trim()).filter(Boolean),
      work_preferences: document.getElementById('prof-prefs').value,
      custom_reply_instructions: document.getElementById('prof-instructions').value,
      historical_email_accounts: historicalAccounts,
      active_resume_file: APP_STATE.profile?.active_resume_file || "Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx"
    };
    
    showToast('Saving profile preferences...', 'info');
    try {
      await fetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      showToast('Candidate Profile saved successfully!', 'success');
      await refreshAll();
    } catch (err) {
      showToast('Failed to save profile: ' + err.message, 'error');
    }
  });

  // Resume Upload Dropzone
  elements.resumeDropzone.addEventListener('click', () => elements.resumeFileInput.click());
  elements.resumeFileInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    const formData = new FormData();
    formData.append('file', file);
    
    showToast(`Uploading ${file.name}...`, 'info');
    try {
      const res = await fetch('/api/profile/upload-resume', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      showToast(data.message, 'success');
      await refreshAll();
    } catch (err) {
      showToast('Upload failed: ' + err.message, 'error');
    }
  });

  // Settings Button
  elements.btnOpenSettings.addEventListener('click', () => {
    const settingsTab = document.querySelector('[data-tab="system-settings"]');
    if (settingsTab) settingsTab.click();
  });

  // Save Settings
  elements.btnSaveSettings.addEventListener('click', async () => {
    const geminiKey = document.getElementById('setting-gemini-key').value.trim();
    const azureClient = document.getElementById('setting-azure-client').value.trim();
    const azureTenant = document.getElementById('setting-azure-tenant').value.trim();
    const googleClient = document.getElementById('setting-google-client')?.value.trim() || '';
    const googleSecret = document.getElementById('setting-google-secret')?.value.trim() || '';
    const safeFolder = document.getElementById('setting-safe-folder').value.trim();
    const autoQuarantine = document.getElementById('setting-auto-quarantine-noise')?.checked;
    const demoMode = document.getElementById('setting-demo-mode').checked;
    
    showToast('Saving engine settings...', 'info');
    try {
      const payload = {
        azure_client_id: azureClient,
        azure_tenant_id: azureTenant,
        google_client_id: googleClient,
        safe_folder_name: safeFolder,
        auto_quarantine_noise: autoQuarantine !== false,
        demo_mode: demoMode
      };
      if (geminiKey) payload.gemini_api_key = geminiKey;
      if (googleSecret) payload.google_client_secret = googleSecret;

      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      showToast('Settings saved successfully in macOS Keychain & configuration!', 'success');
      await refreshAll();
    } catch (err) {
      showToast('Failed to save settings: ' + err.message, 'error');
    }
  });

  // Disable Demo Button
  if (elements.btnDisableDemo) {
    elements.btnDisableDemo.addEventListener('click', async () => {
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ demo_mode: false })
      });
      showToast('Demo Mode disabled. Switched to live multi-account cloud mode.', 'info');
      await refreshAll();
    });
  }
}

// --- Analytics Fetch & Render ---

async function fetchAnalyticsData() {
  try {
    const [kpisRes, funnelRes, compRes, roiRes, eventsRes] = await Promise.all([
      fetch('/api/analytics/kpis'),
      fetch('/api/analytics/funnel'),
      fetch('/api/analytics/compensation'),
      fetch('/api/analytics/resumes-roi'),
      fetch('/api/analytics/events')
    ]);

    if (!kpisRes.ok || !funnelRes.ok || !compRes.ok || !roiRes.ok || !eventsRes.ok) {
      return;
    }

    const [kpis, funnel, comp, roi, events] = await Promise.all([
      kpisRes.json(),
      funnelRes.json(),
      compRes.json(),
      roiRes.json(),
      eventsRes.json()
    ]);

    renderAnalyticsKPIs(kpis);
    renderFunnelChart(funnel);
    renderCompensationBenchmarks(comp);
    renderRoiLeaderboard(roi);
    renderAuditStream(events);
  } catch (err) {
    console.error('Failed to fetch analytics', err);
  }
}

function renderAnalyticsKPIs(kpis) {
  const elTotal = document.getElementById('kpi-total-reachouts');
  const elActive = document.getElementById('kpi-active-pipeline');
  const elConv = document.getElementById('kpi-conversion-rate');
  const elSaved = document.getElementById('kpi-time-saved');

  if (elTotal) elTotal.textContent = kpis.total_reachouts || 0;
  if (elActive) elActive.textContent = kpis.active_pipeline || 0;
  if (elConv) elConv.textContent = `${kpis.response_conversion_rate || 0}%`;
  if (elSaved) elSaved.textContent = `${kpis.time_saved_hours || 0}h`;
}

function renderFunnelChart(stages) {
  const container = document.getElementById('funnel-chart-container');
  if (!container) return;
  container.innerHTML = '';

  stages.forEach(s => {
    const row = document.createElement('div');
    row.className = 'funnel-stage-row';
    row.innerHTML = `
      <div class="funnel-stage-header">
        <span>${s.stage}</span>
        <span style="font-family: var(--font-mono); color: ${s.color};">${s.count} (${s.pct}%)</span>
      </div>
      <div class="funnel-bar-track">
        <div class="funnel-bar-fill" style="width: ${Math.max(s.pct, 4)}%; background: ${s.color};"></div>
      </div>
    `;
    container.appendChild(row);
  });
}

function renderCompensationBenchmarks(data) {
  const container = document.getElementById('comp-benchmarks-container');
  if (!container) return;
  container.innerHTML = '';

  const benchmarks = data.benchmarks || [];
  if (benchmarks.length === 0) {
    container.innerHTML = '<p style="color: var(--text-muted); font-size: 0.85rem;">No compensation data logged yet.</p>';
    return;
  }

  benchmarks.forEach(b => {
    const item = document.createElement('div');
    item.className = 'comp-item';
    const minK = Math.round(b.min / 1000);
    const maxK = Math.round(b.max / 1000);
    const medK = Math.round(b.median / 1000);

    item.innerHTML = `
      <div class="comp-item-header">
        <span class="comp-lens-title">${b.lens_name}</span>
        <span class="comp-metric-label">$${minK}k - $${maxK}k</span>
      </div>
      <div class="comp-bar-wrapper">
        <span>$${minK}k min</span>
        <div class="comp-bar-track">
          <div class="comp-bar-fill" style="width: ${Math.min(100, Math.max(30, (medK / 350) * 100))}%;"></div>
        </div>
        <span>Median: $${medK}k</span>
      </div>
    `;
    container.appendChild(item);
  });
}

function renderRoiLeaderboard(rows) {
  const tbody = document.getElementById('resume-roi-tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No resume engagements recorded yet.</td></tr>';
    return;
  }

  rows.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>
        <strong style="color: #f1f5f9; font-size: 0.825rem;">${r.display_name}</strong>
        <div style="font-size: 0.7rem; color: var(--text-muted);">${r.filename}</div>
      </td>
      <td><span class="lens-pill" style="font-size: 0.65rem; background: rgba(59,130,246,0.15); color: #93c5fd;">${r.lens}</span></td>
      <td style="font-weight: 600; font-family: var(--font-mono);">${r.total_attached}</td>
      <td style="font-family: var(--font-mono); color: #10b981;">${r.replies_sent}</td>
      <td><span class="roi-conversion-badge">${r.conversion_rate}%</span></td>
    `;
    tbody.appendChild(tr);
  });
}

function renderAuditStream(events) {
  const container = document.getElementById('audit-stream-container');
  if (!container) return;
  container.innerHTML = '';

  if (events.length === 0) {
    container.innerHTML = '<p style="color: var(--text-muted); font-size: 0.85rem; padding: 12px;">No audit events recorded yet.</p>';
    return;
  }

  events.forEach(e => {
    const item = document.createElement('div');
    item.className = 'audit-item';
    const timeFormatted = e.timestamp ? e.timestamp.replace('T', ' ').slice(0, 19) : '--';

    item.innerHTML = `
      <div class="audit-item-top">
        <span class="audit-badge ${e.event_type}">${e.event_type.replace('_', ' ')}</span>
        <span style="font-size: 0.7rem; color: var(--text-muted); font-family: var(--font-mono);">${timeFormatted}</span>
      </div>
      <div class="audit-desc">${e.details || (e.company ? `${e.role} at ${e.company}` : 'System event')}</div>
      <div class="audit-meta">
        <span>${e.resume_file ? `📎 ${e.resume_file}` : (e.lens || 'Canonical Core')}</span>
        <span>AI Latency: ${e.latency_ms || 12}ms</span>
      </div>
    `;
    container.appendChild(item);
  });
}

window.orchestrateAllInboxesNoise = async function() {
  showToast('⚡ Orchestrating & scanning all mailboxes for zero-noise inboxes...', 'info');
  try {
    const res = await fetch('/api/inbox/orchestrate-noise', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sync_first: true })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`✓ Zero-Noise Orchestration Complete: ${data.total_noise_quarantined || 0} noise emails safely quarantined across ${data.accounts_scanned || 0} mailboxes to '${data.safe_folder_name || 'AI Cleaned - Noise'}'.`, 'success');
    } else {
      showToast(`Orchestration error: ${data.detail || data.message || 'Unknown error'}`, 'error');
    }
    await refreshAll();
  } catch (err) {
    showToast('Failed to orchestrate noise: ' + err.message, 'error');
  }
};

window.cleanNoiseForAccount = async function(accountId) {
  showToast(`Quarantining noise emails for ${accountId}...`, 'info');
  try {
    const res = await fetch('/api/emails/clean-noise', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId })
    });
    const data = await res.json();
    showToast(data.message || `Cleaned ${data.cleaned_count} emails for ${accountId}.`, 'success');
    await refreshAll();
  } catch (err) {
    showToast('Failed to clean noise: ' + err.message, 'error');
  }
};

window.quarantineSingleEmail = async function(emailId) {
  showToast('Moving email to cloud safe folder...', 'info');
  try {
    const res = await fetch(`/api/emails/${encodeURIComponent(emailId)}/quarantine`, { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message || 'Email safely moved to quarantine folder.', 'success');
    } else {
      showToast(`Error: ${data.detail || 'Failed to quarantine email'}`, 'error');
    }
    await refreshAll();
  } catch (err) {
    showToast('Failed: ' + err.message, 'error');
  }
};

window.trashSingleEmail = async function(emailId) {
  try {
    const res = await fetch(`/api/emails/${encodeURIComponent(emailId)}/trash`, { method: 'POST' });
    if (res.ok) {
      showToast('Moved to trash.', 'info');
    } else {
      showToast('Failed to trash email.', 'error');
    }
    await refreshAll();
  } catch (err) {
    showToast('Failed: ' + err.message, 'error');
  }
};

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = 'toast';
  
  let icon = 'ℹ️';
  if (type === 'success') icon = '✅';
  if (type === 'error') icon = '❌';
  
  toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
  container.appendChild(toast);
  
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4500);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

async function fetchFollowups() {
  try {
    const res = await fetch('/api/followups');
    if (res.ok) {
      const data = await res.json();
      APP_STATE.followups = data.tasks || [];
      renderFollowups();
    }
  } catch (err) {
    console.error('Failed to fetch followups:', err);
  }
}

function renderFollowups() {
  const container = elements.followupTasksList || document.getElementById('followup-tasks-list');
  if (!container) return;

  const filter = APP_STATE.followupFilter || 'pending';
  const tasks = APP_STATE.followups || [];

  const filteredTasks = tasks.filter(t => {
    if (filter === 'pending') return t.status === 'PENDING';
    if (filter === 'completed') return t.status === 'COMPLETED';
    return true; // 'all'
  });

  // Update tab badge and filter counters
  const pendingCount = tasks.filter(t => t.status === 'PENDING').length;
  const completedCount = tasks.filter(t => t.status === 'COMPLETED').length;
  const totalCount = tasks.length;

  if (elements.fuCountPending) elements.fuCountPending.textContent = pendingCount;
  if (elements.fuCountCompleted) elements.fuCountCompleted.textContent = completedCount;
  if (elements.fuCountAll) elements.fuCountAll.textContent = totalCount;

  if (elements.tabBadgeFollowups) {
    elements.tabBadgeFollowups.textContent = pendingCount;
    elements.tabBadgeFollowups.style.display = pendingCount > 0 ? 'inline-block' : 'none';
  }

  container.innerHTML = '';

  if (filteredTasks.length === 0) {
    container.innerHTML = `
      <div style="text-align: center; padding: 48px; color: var(--text-muted);">
        <div style="font-size: 2.5rem; margin-bottom: 12px;">📅</div>
        <h4 style="color: var(--text-primary); margin-bottom: 8px;">No ${filter !== 'all' ? filter : ''} follow-up tasks</h4>
        <p style="font-size: 0.85rem;">Follow-up reminders appear here automatically from all active recruiter reachouts, or you can add custom reminders.</p>
        <button class="btn btn-primary" onclick="orchestratePipeline()" style="margin-top: 16px; background: linear-gradient(135deg, #0284c7, #0369a1); font-weight: 600;">
          <span>⚡</span> Orchestrate Pipeline
        </button>
      </div>
    `;
    return;
  }

  filteredTasks.forEach(task => {
    const card = document.createElement('div');
    card.className = `followup-card ${task.status.toLowerCase()}`;
    
    // Check if overdue
    const isOverdue = task.status === 'PENDING' && task.due_date && new Date(task.due_date) < new Date(new Date().setHours(0,0,0,0));
    const title = task.role_title || task.title || 'Executive Outreach';
    const company = task.company_name || task.company || 'Hiring Organization';
    const recruiter = task.recruiter_name || 'Recruiter';
    
    card.innerHTML = `
      <div class="followup-card-left">
        <div class="followup-card-header" style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
          <span class="followup-card-title ${task.status === 'COMPLETED' ? 'strikethrough' : ''}" style="font-weight: 700; color: #f8fafc;">${escapeHtml(title)}</span>
          ${isOverdue ? '<span class="status-chip chip-overdue" style="background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); font-size: 0.72rem; padding: 2px 8px; border-radius: 999px;">⚠️ Overdue</span>' : ''}
          <span class="status-chip ${task.status.toLowerCase()}" style="font-size: 0.72rem; padding: 2px 8px; border-radius: 999px; ${task.status === 'COMPLETED' ? 'background: rgba(16, 185, 129, 0.2); color: #34d399;' : 'background: rgba(14, 165, 233, 0.2); color: #38bdf8;'}">${task.status === 'COMPLETED' ? '✓ Completed' : '⏳ Action Needed'}</span>
        </div>
        <div class="followup-card-meta" style="display: flex; gap: 14px; margin-top: 6px; font-size: 0.82rem; color: var(--text-secondary); flex-wrap: wrap;">
          <span>👤 <strong>${escapeHtml(recruiter)}</strong></span>
          <span>🏢 ${escapeHtml(company)}</span>
          ${task.account_id ? `<span>📬 <code style="font-size: 0.75rem;">${escapeHtml(task.account_id)}</code></span>` : ''}
          ${task.due_date ? `<span>📅 Target Due: <strong style="color: #38bdf8;">${escapeHtml(task.due_date)}</strong></span>` : ''}
        </div>
        ${task.notes ? `<div class="followup-card-notes" style="margin-top: 8px; font-size: 0.82rem; color: #cbd5e1; background: rgba(15, 23, 42, 0.6); padding: 8px 12px; border-radius: 6px; border-left: 3px solid #0284c7;">📝 ${escapeHtml(task.notes)}</div>` : ''}
      </div>
      <div class="followup-card-actions" style="display: flex; align-items: center; gap: 8px; margin-top: 10px;">
        ${task.email_id ? `
          <button class="btn btn-primary btn-sm" onclick="openFollowupInStudio('${escapeHtml(task.email_id)}')" title="Open reachout and tailored draft in Recruiter Studio" style="background: linear-gradient(135deg, #0284c7, #0369a1); font-weight: 600;">
            <span>🎯</span> Open in Studio
          </button>
        ` : ''}
        ${task.status === 'PENDING' ? `
          <button class="btn btn-secondary btn-sm" onclick="completeFollowupTask('${escapeHtml(task.id)}')" title="Mark Completed">✓ Done</button>
        ` : `
          <button class="btn btn-secondary btn-sm" onclick="reopenFollowupTask('${escapeHtml(task.id)}')" title="Reopen Task">↩ Reopen</button>
        `}
        <button class="btn btn-icon btn-sm" onclick="deleteFollowupTask('${escapeHtml(task.id)}')" title="Delete Reminder" style="color: var(--text-muted);">🗑️</button>
      </div>
    `;
    container.appendChild(card);
  });
}

window.openFollowupInStudio = function(emailId) {
  if (!emailId) return;
  // 1. Switch to Recruiter & Resume Studio tab
  const studioTabBtn = document.querySelector('.tab-btn[data-tab="recruiter-studio"]');
  if (studioTabBtn) studioTabBtn.click();

  // 2. Ensure queue filter shows all reachouts so the targeted card is rendered
  APP_STATE.queueFilter = 'all';
  const filterBtns = document.querySelectorAll('#queue-filter-group button');
  filterBtns.forEach(b => {
    if (b.getAttribute('data-queue-filter') === 'all') {
      b.classList.add('active');
    } else {
      b.classList.remove('active');
    }
  });
  renderRecruiterList();

  // 3. Select the email in the Studio
  if (typeof selectRecruiterEmail === 'function') {
    selectRecruiterEmail(emailId);
  }

  // 4. Smooth scroll the card into view
  setTimeout(() => {
    const card = document.getElementById(`card-${emailId.replace(/[^a-zA-Z0-9_-]/g, '_')}`);
    if (card) {
      card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, 100);

  showToast('Loaded recruiter opportunity in Studio.', 'info');
};

window.orchestratePipeline = async function() {
  try {
    showToast('Orchestrating Recruiter Follow-ups & Pipeline...', 'info');
    const res = await fetch('/api/pipeline/orchestrate', { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      showToast(`Pipeline Orchestrated! ${data.pending_tasks || 0} reachouts scheduled.`, 'success');
      await fetchFollowups();
    } else {
      showToast('Failed to orchestrate pipeline.', 'error');
    }
  } catch (err) {
    showToast('Error: ' + err.message, 'error');
  }
};

window.completeFollowupTask = async function(taskId) {
  try {
    const res = await fetch(`/api/followups/${taskId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'COMPLETED' })
    });
    if (res.ok) {
      showToast('Follow-up marked as completed!', 'success');
      await fetchFollowups();
    } else {
      showToast('Failed to update follow-up.', 'error');
    }
  } catch (err) {
    showToast('Error: ' + err.message, 'error');
  }
};

window.reopenFollowupTask = async function(taskId) {
  try {
    const res = await fetch(`/api/followups/${taskId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'PENDING' })
    });
    if (res.ok) {
      showToast('Follow-up reopened.', 'info');
      await fetchFollowups();
    } else {
      showToast('Failed to reopen follow-up.', 'error');
    }
  } catch (err) {
    showToast('Error: ' + err.message, 'error');
  }
};

window.deleteFollowupTask = async function(taskId) {
  if (!confirm('Are you sure you want to delete this follow-up reminder?')) return;
  try {
    const res = await fetch(`/api/followups/${taskId}`, { method: 'DELETE' });
    if (res.ok) {
      showToast('Follow-up deleted.', 'info');
      await fetchFollowups();
    } else {
      showToast('Failed to delete follow-up.', 'error');
    }
  } catch (err) {
    showToast('Error: ' + err.message, 'error');
  }
};

