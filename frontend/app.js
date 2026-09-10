// Aura Mail AI - Frontend Application Controller (v1.1 Cloud Multi-Account)

let APP_STATE = {
  emails: [],
  accounts: [],
  selectedEmailId: null,
  profile: null,
  canonicalData: null,
  resumes: [],
  status: null,
  activeFilter: 'ALL',
  activeVaultFilter: 'ALL',
  vaultSearchQuery: '',
  devicePollInterval: null
};

// DOM Elements
const elements = {
  statResumeInquiries: document.getElementById('stat-resume-inquiries'),
  statNoiseDetected: document.getElementById('stat-noise-detected'),
  statTimeSaved: document.getElementById('stat-time-saved'),
  statCleanliness: document.getElementById('stat-cleanliness'),
  
  tabBadgeRecruiters: document.getElementById('tab-badge-recruiters'),
  tabBadgeNoise: document.getElementById('tab-badge-noise'),
  tabBadgeVault: document.getElementById('tab-badge-vault'),
  tabBadgeAccounts: document.getElementById('tab-badge-accounts'),
  headerConnCount: document.getElementById('header-conn-count'),
  recruiterCountPill: document.getElementById('recruiter-count-pill'),
  
  recruiterEmailsList: document.getElementById('recruiter-emails-list'),
  triageTableBody: document.getElementById('triage-table-body'),
  accountsCardsGrid: document.getElementById('accounts-cards-grid'),
  demoModeBanner: document.getElementById('demo-mode-banner'),
  btnDisableDemo: document.getElementById('btn-disable-demo'),
  
  inboundSubject: document.getElementById('inbound-subject'),
  inboundSender: document.getElementById('inbound-sender'),
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
  btnSendReply: document.getElementById('btn-send-reply'),
  btnBatchCleanNoise: document.getElementById('btn-batch-clean-noise'),
  btnOpenAccounts: document.getElementById('btn-open-accounts'),
  btnAddAccountModal: document.getElementById('btn-add-account-modal'),
  btnOpenSettings: document.getElementById('btn-open-settings'),
  btnSaveProfile: document.getElementById('btn-save-profile'),
  btnSaveSettings: document.getElementById('btn-save-settings'),
  
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
  authTabImap: document.getElementById('auth-tab-imap'),
  authPanelMsal: document.getElementById('auth-panel-msal'),
  authPanelImap: document.getElementById('auth-panel-imap'),
  btnStartDeviceFlow: document.getElementById('btn-start-device-flow'),
  deviceFlowDisplay: document.getElementById('device-flow-display'),
  deviceCodeDisplay: document.getElementById('device-code-display'),
  devicePollStatus: document.getElementById('device-poll-status'),
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
  await refreshAll();
});

async function refreshAll() {
  await Promise.all([
    fetchStatus(),
    fetchAccounts(),
    fetchProfile(),
    fetchCanonicalResumes(),
    fetchEmails(),
    fetchStats()
  ]);
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
    
    // Advisory Mac Desktop App Status
    if (data.desktop_outlook_app && data.desktop_outlook_app.is_running) {
      elements.desktopStatusText.textContent = 'Mac Outlook: Running';
      elements.desktopDot.className = 'status-dot';
      elements.desktopDot.style.background = '#10b981';
    } else {
      elements.desktopStatusText.textContent = 'Mac Outlook: Offline (Cloud Active)';
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
    const accounts = await res.json();
    APP_STATE.accounts = accounts;
    
    const connectedCount = accounts.filter(a => a.is_connected).length;
    if (elements.headerConnCount) elements.headerConnCount.textContent = connectedCount;
    if (elements.tabBadgeAccounts) elements.tabBadgeAccounts.textContent = accounts.length;
    
    renderAccountsGrid();
  } catch (err) {
    console.error('Failed to fetch accounts', err);
  }
}

async function fetchStats() {
  try {
    const res = await fetch('/api/stats');
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
    const emails = await res.json();
    APP_STATE.emails = emails;
    
    renderRecruiterList();
    renderTriageTable();
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
      provBadge = '🌐 Standard IMAP/SMTP';
      provColor = '#10b981';
    } else if (acc.provider === 'DEMO') {
      provBadge = '🧪 Demo Sandbox';
      provColor = '#eab308';
    }
    
    const isConn = acc.is_connected;
    const statusPill = isConn ? 
      `<span style="font-size: 0.75rem; color: #10b981; font-weight: 600;">● Connected</span>` :
      `<span style="font-size: 0.75rem; color: #ef4444; font-weight: 600;">○ Disconnected</span>`;
    
    const caps = (acc.capabilities || []).map(c => `<span class="skill-chip" style="font-size: 0.65rem; padding: 2px 6px;">${c}</span>`).join(' ');
    
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
        ${acc.last_error ? `<div style="background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: var(--radius-sm); padding: 6px 10px; margin-top: 8px; font-size: 0.75rem; color: #fca5a5;">⚠️ ${acc.last_error}</div>` : ''}
        
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
            <button class="btn btn-secondary btn-sm" onclick="openAuthModalFor('${acc.provider}', '${acc.account_id}')">
              ${isConn ? 'Re-Auth' : 'Sign In'}
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
  if (providerType === 'IMAP') {
    elements.authTabImap.click();
    document.getElementById('imap-email-input').value = accountId;
  } else {
    elements.authTabMsal.click();
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

function renderRecruiterList() {
  const container = elements.recruiterEmailsList;
  container.innerHTML = '';
  
  const recruiterEmails = APP_STATE.emails.filter(e => e.classification && e.classification.is_resume_request);
  
  if (recruiterEmails.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📭</div>
        <p>No recruiter reachouts currently in queue.</p>
      </div>`;
    return;
  }
  
  recruiterEmails.forEach(emailMsg => {
    const card = document.createElement('div');
    card.className = `email-card ${emailMsg.id === APP_STATE.selectedEmailId ? 'selected' : ''}`;
    card.id = `card-${emailMsg.id.replace(/[^a-zA-Z0-9_-]/g, '_')}`;
    
    const roleName = emailMsg.classification?.recruiter_details?.role_title || emailMsg.subject;
    const compName = emailMsg.classification?.recruiter_details?.company_name || 'Hiring Team';
    const match = emailMsg.classification?.resume_match;
    const lensBadge = match?.lens_badge || 'Advisor (Level 3A)';
    
    card.innerHTML = `
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
  
  if (!APP_STATE.selectedEmailId && recruiterEmails.length > 0) {
    selectRecruiterEmail(recruiterEmails[0].id);
  }
}

function selectRecruiterEmail(emailId) {
  APP_STATE.selectedEmailId = emailId;
  
  document.querySelectorAll('.email-card').forEach(c => c.classList.remove('selected'));
  const card = document.getElementById(`card-${emailId.replace(/[^a-zA-Z0-9_-]/g, '_')}`);
  if (card) card.classList.add('selected');
  
  const emailMsg = APP_STATE.emails.find(e => e.id === emailId);
  if (!emailMsg) return;
  
  elements.inboundSubject.textContent = emailMsg.subject;
  elements.inboundSender.textContent = `From: ${emailMsg.sender_name} <${emailMsg.sender_email}>`;
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
  
  // Draft Reply
  elements.replyBodyText.value = emailMsg.draft_reply || '';
}

function renderTriageTable() {
  const tbody = elements.triageTableBody;
  tbody.innerHTML = '';
  
  let filtered = APP_STATE.emails;
  if (APP_STATE.activeFilter === 'NOISE') {
    filtered = APP_STATE.emails.filter(e => e.classification?.is_noise);
  } else if (APP_STATE.activeFilter === 'RESUME_REQUEST') {
    filtered = APP_STATE.emails.filter(e => e.classification?.is_resume_request);
  } else if (APP_STATE.activeFilter === 'OTHER') {
    filtered = APP_STATE.emails.filter(e => !e.classification?.is_noise && !e.classification?.is_resume_request);
  }
  
  document.getElementById('triage-total-label').textContent = `Showing ${filtered.length} emails`;
  
  filtered.forEach(emailMsg => {
    const tr = document.createElement('tr');
    
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
    
    const isTrashed = emailMsg.status === 'TRASHED';
    
    tr.innerHTML = `
      <td>
        <strong style="font-size: 0.85rem;">${emailMsg.sender_name}</strong>
        <div style="font-size: 0.75rem; color: var(--text-muted);">${emailMsg.sender_email}</div>
      </td>
      <td>
        <div style="font-weight: 500; color: #e2e8f0; max-width: 280px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${emailMsg.subject}</div>
        <div style="font-size: 0.75rem; color: var(--text-secondary); max-width: 280px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${emailMsg.preview}</div>
      </td>
      <td><span class="category-tag ${tagClass}">${tagLabel}</span></td>
      <td style="font-size: 0.775rem; color: var(--text-secondary); max-width: 250px;">
        ${emailMsg.classification?.reasoning || 'Classified by Aura AI'}
      </td>
      <td>
        ${isTrashed ? 
          '<span style="color: var(--text-muted); font-size: 0.8rem;">✓ Cleaned</span>' :
          `<button class="btn btn-secondary btn-sm" onclick="trashSingleEmail('${emailMsg.id}')">Trash</button>`
        }
      </td>
    `;
    tbody.appendChild(tr);
  });
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
  elements.authTabMsal.addEventListener('click', () => {
    elements.authTabMsal.classList.add('active-filter');
    elements.authTabImap.classList.remove('active-filter');
    elements.authPanelMsal.style.display = 'block';
    elements.authPanelImap.style.display = 'none';
  });

  elements.authTabImap.addEventListener('click', () => {
    elements.authTabImap.classList.add('active-filter');
    elements.authTabMsal.classList.remove('active-filter');
    elements.authPanelMsal.style.display = 'none';
    elements.authPanelImap.style.display = 'block';
  });

  // MSAL Device Flow
  elements.btnStartDeviceFlow.addEventListener('click', async () => {
    elements.btnStartDeviceFlow.disabled = true;
    elements.btnStartDeviceFlow.textContent = 'Initiating Microsoft Login...';
    try {
      const res = await fetch('/api/auth/msal/device-code', { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.user_code) {
        elements.deviceCodeDisplay.textContent = data.user_code;
        elements.deviceFlowDisplay.style.display = 'block';
        elements.devicePollStatus.textContent = 'Waiting for you to enter code at microsoft.com/devicelogin...';
        
        // Start polling
        if (APP_STATE.devicePollInterval) clearInterval(APP_STATE.devicePollInterval);
        APP_STATE.devicePollInterval = setInterval(async () => {
          try {
            const pollRes = await fetch('/api/auth/msal/device-code/poll', { method: 'POST' });
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

  // Save IMAP Auth
  elements.btnSaveImapAuth.addEventListener('click', async () => {
    const emailAddr = document.getElementById('imap-email-input').value.trim();
    const pwd = document.getElementById('imap-password-input').value.trim();
    const imapServer = document.getElementById('imap-server-input').value.trim();
    const smtpServer = document.getElementById('smtp-server-input').value.trim();
    
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
          imap_server: imapServer,
          smtp_server: smtpServer
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

  // Regenerate Draft
  elements.btnRegenerateDraft.addEventListener('click', async () => {
    if (!APP_STATE.selectedEmailId) return;
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
      elements.replyBodyText.value = data.draft_reply;
      showToast('Personalized grounded response updated!', 'success');
      await fetchEmails();
    } catch (err) {
      showToast('Generation failed: ' + err.message, 'error');
    }
  });

  // Save to Cloud Drafts
  elements.btnSaveDraft.addEventListener('click', async () => {
    if (!APP_STATE.selectedEmailId) return;
    const replyBody = elements.replyBodyText.value;
    const chosenResume = elements.resumeVariantSelect.value;
    showToast(`Creating draft in cloud mailbox with '${chosenResume}' attached...`, 'info');
    
    try {
      const res = await fetch(`/api/emails/${encodeURIComponent(APP_STATE.selectedEmailId)}/save-draft`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reply_body: replyBody, resume_filename: chosenResume })
      });
      const data = await res.json();
      if (data.success) {
        showToast(data.safe_message || 'Draft successfully created in cloud Drafts folder!', 'success');
      } else {
        showToast(`Draft error: ${data.safe_message}`, 'error');
      }
      await refreshAll();
    } catch (err) {
      showToast('Failed to save draft: ' + err.message, 'error');
    }
  });

  // Send Reply
  elements.btnSendReply.addEventListener('click', async () => {
    if (!APP_STATE.selectedEmailId) return;
    const replyBody = elements.replyBodyText.value;
    const chosenResume = elements.resumeVariantSelect.value;
    
    if (!confirm(`Are you ready to send this response with ${chosenResume} attached?`)) return;
    
    showToast('Sending response via cloud provider...', 'info');
    try {
      const res = await fetch(`/api/emails/${encodeURIComponent(APP_STATE.selectedEmailId)}/send-reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reply_body: replyBody, attach_resume: true, resume_filename: chosenResume })
      });
      const data = await res.json();
      if (data.success) {
        showToast(data.safe_message || 'Reply sent successfully!', 'success');
      } else {
        showToast(`Send error: ${data.safe_message}`, 'error');
      }
      await refreshAll();
    } catch (err) {
      showToast('Failed to send reply: ' + err.message, 'error');
    }
  });

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

  // Batch Clean Noise
  elements.btnBatchCleanNoise.addEventListener('click', async () => {
    showToast('Moving noise emails to cloud quarantine folder...', 'info');
    try {
      const res = await fetch('/api/emails/clean-noise', { method: 'POST' });
      const data = await res.json();
      showToast(data.message || `Cleaned ${data.cleaned_count} emails.`, 'success');
      await refreshAll();
    } catch (err) {
      showToast('Cleanup failed: ' + err.message, 'error');
    }
  });

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
    const safeFolder = document.getElementById('setting-safe-folder').value.trim();
    const demoMode = document.getElementById('setting-demo-mode').checked;
    
    showToast('Saving engine settings...', 'info');
    try {
      const payload = {
        azure_client_id: azureClient,
        azure_tenant_id: azureTenant,
        safe_folder_name: safeFolder,
        demo_mode: demoMode
      };
      if (geminiKey) payload.gemini_api_key = geminiKey;

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
