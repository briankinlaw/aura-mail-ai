// Aura Mail AI - Frontend Application Controller (with Canonical Career System Integration)

let APP_STATE = {
  emails: [],
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
  recruiterCountPill: document.getElementById('recruiter-count-pill'),
  
  recruiterEmailsList: document.getElementById('recruiter-emails-list'),
  triageTableBody: document.getElementById('triage-table-body'),
  
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
  btnOpenConnect: document.getElementById('btn-open-connect'),
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
  
  // Device Code Modal
  deviceLoginModal: document.getElementById('device-login-modal'),
  modalCloseBtn: document.getElementById('modal-close-btn'),
  deviceCodeText: document.getElementById('device-code-text'),
  devicePollStatus: document.getElementById('device-poll-status'),
  btnOpenMicrosoftLogin: document.getElementById('btn-open-microsoft-login'),
  
  resumeDropzone: document.getElementById('resume-dropzone'),
  resumeFileInput: document.getElementById('resume-file-input'),
  profileActiveName: document.getElementById('profile-active-name'),
  profileActiveLens: document.getElementById('profile-active-lens'),
  
  outlookStatusText: document.getElementById('outlook-status-text'),
  outlookDot: document.getElementById('outlook-dot'),
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
    fetchProfile(),
    fetchCanonicalResumes(),
    fetchEmails(),
    fetchStats()
  ]);
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
    
    if (data.auth_mode === 'GRAPH_CLOUD_OAUTH') {
      elements.outlookStatusText.textContent = data.outlook_user || 'Outlook: Cloud Synced';
      elements.outlookDot.className = 'status-dot';
      elements.btnOpenConnect.innerHTML = '<span>☁️</span> Cloud Synced';
      elements.btnOpenConnect.className = 'btn btn-emerald btn-sm';
      elements.deviceLoginModal.classList.remove('active');
    } else if (data.auth_mode === 'MAC_DESKTOP_CLIENT') {
      elements.outlookStatusText.textContent = 'Outlook Client: Connected (Direct Bridge)';
      elements.outlookDot.className = 'status-dot';
      elements.btnOpenConnect.innerHTML = '<span>🟢</span> Outlook Client Active';
      elements.btnOpenConnect.className = 'btn btn-emerald btn-sm';
    } else {
      elements.outlookStatusText.textContent = 'Demo Mode (Offline)';
      elements.outlookDot.className = 'status-dot';
      elements.btnOpenConnect.innerHTML = '<span>🔄</span> Connect Outlook';
      elements.btnOpenConnect.className = 'btn btn-secondary btn-sm';
    }
    
    if (data.gemini_configured) {
      elements.aiStatusText.textContent = 'Gemini 2.5 Flash: Active';
      elements.aiDot.className = 'status-dot';
    } else {
      elements.aiStatusText.textContent = 'AI Engine: Local Heuristics';
      elements.aiDot.className = 'status-dot';
    }
    
    if (data.active_resume) {
      elements.attachedResumeName.textContent = data.active_resume;
      if (elements.profileActiveName) elements.profileActiveName.textContent = data.active_resume;
    }
  } catch (err) {
    console.error('Failed to fetch status', err);
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
    
    const activeEmailsInput = document.getElementById('prof-active-emails');
    if (activeEmailsInput) {
      activeEmailsInput.value = (profile.active_email_accounts || []).join(', ');
    }
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
  
  recruiterEmails.forEach(email => {
    const card = document.createElement('div');
    card.className = `email-card ${email.id === APP_STATE.selectedEmailId ? 'selected' : ''}`;
    card.id = `card-${email.id}`;
    
    const roleName = email.classification?.recruiter_details?.role_title || email.subject;
    const compName = email.classification?.recruiter_details?.company_name || 'Hiring Team';
    const match = email.classification?.resume_match;
    const lensBadge = match?.lens_badge || 'Advisor (Level 3A)';
    
    card.innerHTML = `
      <div class="email-card-header">
        <span class="sender-name">${email.sender_name}</span>
        <span class="email-time">${email.received_at.split(' ')[1] || ''}</span>
      </div>
      <div class="email-subject">${roleName}</div>
      <div class="email-snippet">${email.preview}</div>
      <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px;">
        <span class="category-tag recruiter">🎯 ${compName}</span>
        <span class="lens-pill" style="font-size: 0.65rem; padding: 1px 6px; background: rgba(59,130,246,0.15); color: #93c5fd;">${lensBadge}</span>
      </div>
    `;
    
    card.addEventListener('click', () => selectRecruiterEmail(email.id));
    container.appendChild(card);
  });
  
  if (!APP_STATE.selectedEmailId && recruiterEmails.length > 0) {
    selectRecruiterEmail(recruiterEmails[0].id);
  }
}

function selectRecruiterEmail(emailId) {
  APP_STATE.selectedEmailId = emailId;
  
  document.querySelectorAll('.email-card').forEach(c => c.classList.remove('selected'));
  const card = document.getElementById(`card-${emailId}`);
  if (card) card.classList.add('selected');
  
  const email = APP_STATE.emails.find(e => e.id === emailId);
  if (!email) return;
  
  elements.inboundSubject.textContent = email.subject;
  elements.inboundSender.textContent = `From: ${email.sender_name} <${email.sender_email}>`;
  elements.inboundDate.textContent = `Received: ${email.received_at}`;
  elements.inboundMessageBody.textContent = email.body_text;
  
  // Recruiter Specs
  const specs = email.classification?.recruiter_details;
  if (specs) {
    elements.specRole.textContent = specs.role_title || 'Enterprise Solutions Architecture Role';
    elements.specCompany.textContent = specs.company_name || 'Prospective Employer';
    elements.specSalary.textContent = specs.salary_range || 'Competitive / Open to Discussion';
    
    elements.specSkills.innerHTML = (specs.required_skills || ['Cloud Architecture', 'Google Cloud', 'Enterprise Data'])
      .map(s => `<span class="skill-chip">${s}</span>`).join('');
  }
  
  // Canonical Match & Lens Card
  const match = email.classification?.resume_match;
  if (match) {
    elements.matchLensBadge.textContent = match.lens_name;
    elements.matchLensBadge.style.background = `${match.lens_color}22`;
    elements.matchLensBadge.style.color = match.lens_color;
    elements.matchLensBadge.style.borderColor = `${match.lens_color}66`;
    
    elements.matchScoreValue.textContent = `${match.match_score}%`;
    elements.matchRationale.textContent = match.rationale;
    
    const chosenResume = email.selected_resume_file || match.selected_resume;
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
  elements.replyBodyText.value = email.draft_reply || '';
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
  
  filtered.forEach(email => {
    const tr = document.createElement('tr');
    
    let tagClass = 'other';
    let tagLabel = 'Direct / Human';
    if (email.classification?.category === 'RESUME_REQUEST') {
      tagClass = 'recruiter';
      tagLabel = '🎯 Recruiter / Resume';
    } else if (email.classification?.category === 'NOISE_PROMOTIONAL') {
      tagClass = 'noise-promo';
      tagLabel = '📢 Promotional Spam';
    } else if (email.classification?.category === 'NOISE_NEWSLETTER') {
      tagClass = 'noise-news';
      tagLabel = '📰 Newsletter';
    } else if (email.classification?.category === 'NOISE_NOTIFICATION') {
      tagClass = 'noise-notif';
      tagLabel = '🔔 System Alert';
    }
    
    const isTrashed = email.status === 'TRASHED';
    
    tr.innerHTML = `
      <td>
        <strong style="font-size: 0.85rem;">${email.sender_name}</strong>
        <div style="font-size: 0.75rem; color: var(--text-muted);">${email.sender_email}</div>
      </td>
      <td>
        <div style="font-weight: 500; color: #e2e8f0; max-width: 280px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${email.subject}</div>
        <div style="font-size: 0.75rem; color: var(--text-secondary); max-width: 280px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${email.preview}</div>
      </td>
      <td><span class="category-tag ${tagClass}">${tagLabel}</span></td>
      <td style="font-size: 0.775rem; color: var(--text-secondary); max-width: 250px;">
        ${email.classification?.reasoning || 'Classified by Aura AI'}
      </td>
      <td>
        ${isTrashed ? 
          '<span style="color: var(--text-muted); font-size: 0.8rem;">✓ Cleaned</span>' :
          `<button class="btn btn-secondary btn-sm" onclick="trashSingleEmail('${email.id}')">Trash</button>`
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

// Global action to set default resume
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
    showToast('Syncing inbox and triaging with AI...', 'info');
    elements.btnSyncInbox.disabled = true;
    try {
      const res = await fetch('/api/emails/sync', { method: 'POST' });
      const data = await res.json();
      showToast(`Sync complete! Found ${data.resume_requests_found} recruiter reachouts and ${data.noise_detected} noise items.`, 'success');
      await refreshAll();
    } catch (err) {
      showToast('Sync failed: ' + err.message, 'error');
    } finally {
      elements.btnSyncInbox.disabled = false;
    }
  });

  // Resume Dropdown Change in Recruiter Studio
  if (elements.resumeVariantSelect) {
    elements.resumeVariantSelect.addEventListener('change', (e) => {
      const selected = e.target.value;
      elements.attachedResumeName.textContent = selected;
      const isPdf = selected.endsWith('.pdf');
      elements.attachmentFormatHint.textContent = isPdf ? 'Canonical Document (Adobe PDF)' : 'Canonical Document (Word DOCX)';
      
      const email = APP_STATE.emails.find(em => em.id === APP_STATE.selectedEmailId);
      if (email) {
        email.selected_resume_file = selected;
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
      const res = await fetch(`/api/emails/${APP_STATE.selectedEmailId}/generate-reply`, {
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

  // Save to Outlook Drafts
  elements.btnSaveDraft.addEventListener('click', async () => {
    if (!APP_STATE.selectedEmailId) return;
    const replyBody = elements.replyBodyText.value;
    const chosenResume = elements.resumeVariantSelect.value;
    showToast(`Saving draft to Outlook with ${chosenResume} attached...`, 'info');
    
    try {
      const res = await fetch(`/api/emails/${APP_STATE.selectedEmailId}/save-draft`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reply_body: replyBody, resume_filename: chosenResume })
      });
      const data = await res.json();
      showToast('Draft successfully created in Outlook with canonical resume attached!', 'success');
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
    
    showToast('Sending response via Outlook...', 'info');
    try {
      const res = await fetch(`/api/emails/${APP_STATE.selectedEmailId}/send-reply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reply_body: replyBody, attach_resume: true, resume_filename: chosenResume })
      });
      const data = await res.json();
      showToast('Reply and canonical resume sent successfully!', 'success');
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

  // Batch Clean Noise
  elements.btnBatchCleanNoise.addEventListener('click', async () => {
    showToast('Moving all noise emails to safe cleanup folder...', 'info');
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
    const activeEmailsRaw = document.getElementById('prof-active-emails')?.value || '';
    const histEmailsRaw = document.getElementById('prof-historical-emails')?.value || '';
    
    const activeAccounts = activeEmailsRaw.split(',').map(s => s.trim()).filter(Boolean);
    const historicalAccounts = histEmailsRaw.split(',').map(s => s.trim()).filter(Boolean);

    const payload = {
      full_name: document.getElementById('prof-name').value,
      current_title: document.getElementById('prof-title').value,
      summary_bio: document.getElementById('prof-bio').value,
      core_skills: document.getElementById('prof-skills').value.split(',').map(s => s.trim()).filter(Boolean),
      target_roles: document.getElementById('prof-target-roles').value.split(',').map(s => s.trim()).filter(Boolean),
      work_preferences: document.getElementById('prof-prefs').value,
      custom_reply_instructions: document.getElementById('prof-instructions').value,
      active_email_accounts: activeAccounts,
      historical_email_accounts: historicalAccounts,
      active_resume_file: APP_STATE.profile?.active_resume_file || "Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx"
    };
    
    showToast('Saving profile & account preferences...', 'info');
    try {
      await fetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      showToast('Candidate Profile & Active Inboxes saved successfully!', 'success');
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

  // Open Direct Outlook Client Status Modal
  elements.btnOpenConnect.addEventListener('click', async () => {
    elements.deviceLoginModal.classList.add('active');
    try {
      const setRes = await fetch('/api/settings');
      const setJson = await setRes.json();
      const azureInput = document.getElementById('azure-client-input');
      if (azureInput && setJson.azure_client_id) {
        azureInput.value = setJson.azure_client_id;
      }
    } catch (e) {}
  });

  if (elements.modalCloseBtn) {
    elements.modalCloseBtn.addEventListener('click', () => {
      elements.deviceLoginModal.classList.remove('active');
    });
  }

  const btnModalSync = document.getElementById('btn-modal-sync-inbox');
  if (btnModalSync) {
    btnModalSync.addEventListener('click', async () => {
      elements.deviceLoginModal.classList.remove('active');
      elements.btnSyncInbox.click();
    });
  }

  const btnModalProfile = document.getElementById('btn-modal-open-profile');
  if (btnModalProfile) {
    btnModalProfile.addEventListener('click', () => {
      elements.deviceLoginModal.classList.remove('active');
      const profTab = document.querySelector('[data-tab="candidate-profile"]');
      if (profTab) profTab.click();
    });
  }

  // Save Azure Client ID
  const btnSaveAzure = document.getElementById('btn-save-azure-client');
  if (btnSaveAzure) {
    btnSaveAzure.addEventListener('click', async () => {
      const cid = document.getElementById('azure-client-input').value.trim();
      if (!cid) {
        showToast('Please enter your Azure Application (Client) ID.', 'error');
        return;
      }
      btnSaveAzure.disabled = true;
      btnSaveAzure.textContent = 'Saving...';
      try {
        await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ azure_client_id: cid })
        });
        showToast('Azure Client ID saved! Click Step 1 to sign in.', 'success');
      } catch (err) {
        showToast('Failed to save Client ID', 'error');
      } finally {
        btnSaveAzure.disabled = false;
        btnSaveAzure.textContent = 'Save ID';
      }
    });
  }

  // Submit OAuth2 Code
  const btnSubmitOAuth = document.getElementById('btn-submit-oauth-code');
  if (btnSubmitOAuth) {
    btnSubmitOAuth.addEventListener('click', async () => {
      const codeInput = document.getElementById('oauth-code-input').value.trim();
      if (!codeInput) {
        showToast('Please paste the URL or authorization code.', 'error');
        return;
      }
      
      btnSubmitOAuth.disabled = true;
      btnSubmitOAuth.textContent = 'Exchanging token...';
      showToast('Connecting to Microsoft Graph Cloud...', 'info');
      
      try {
        const res = await fetch('/api/auth/submit-code', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code: codeInput })
        });
        
        const data = await res.json();
        if (res.ok && data.status === 'SUCCESS') {
          showToast(`Successfully connected to Microsoft Graph as ${data.username}!`, 'success');
          elements.deviceLoginModal.classList.remove('active');
          await refreshAll();
        } else {
          showToast(data.detail || 'Failed to exchange authorization code.', 'error');
        }
      } catch (err) {
        showToast(`Authentication error: ${err.message}`, 'error');
      } finally {
        btnSubmitOAuth.disabled = false;
        btnSubmitOAuth.textContent = 'Complete Sync ✓';
      }
    });
  }

  elements.modalCloseBtn.addEventListener('click', () => {
    elements.deviceLoginModal.classList.remove('active');
    if (APP_STATE.devicePollInterval) clearInterval(APP_STATE.devicePollInterval);
  });

  // Settings Button
  elements.btnOpenSettings.addEventListener('click', () => {
    const settingsTab = document.querySelector('[data-tab="system-settings"]');
    if (settingsTab) settingsTab.click();
  });

  // Save Settings
  elements.btnSaveSettings.addEventListener('click', async () => {
    const geminiKey = document.getElementById('setting-gemini-key').value;
    const azureClient = document.getElementById('setting-azure-client').value;
    const safeFolder = document.getElementById('setting-safe-folder').value;
    const autopilot = document.getElementById('setting-autopilot').checked;
    
    showToast('Saving engine settings...', 'info');
    try {
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gemini_api_key: geminiKey,
          azure_client_id: azureClient,
          safe_folder_name: safeFolder,
          auto_pilot_enabled: autopilot
        })
      });
      showToast('Settings saved!', 'success');
      await fetchStatus();
    } catch (err) {
      showToast('Failed to save settings', 'error');
    }
  });

  // Refresh Analytics Button
  const btnRefreshAnalytics = document.getElementById('btn-refresh-analytics');
  if (btnRefreshAnalytics) {
    btnRefreshAnalytics.addEventListener('click', async () => {
      showToast('Refreshing career pipeline telemetry...', 'info');
      await fetchAnalyticsData();
      showToast('Telemetry and KPIs updated!', 'success');
    });
  }

  // Export Analytics Button
  const btnExportAnalytics = document.getElementById('btn-export-analytics');
  if (btnExportAnalytics) {
    btnExportAnalytics.addEventListener('click', async () => {
      try {
        const res = await fetch('/api/analytics/export');
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `Aura_Career_Analytics_${new Date().toISOString().split('T')[0]}.json`;
        a.click();
        showToast('Exported complete telemetry snapshot to JSON!', 'success');
      } catch (err) {
        showToast('Export failed: ' + err.message, 'error');
      }
    });
  }
}

// --- Analytics & Observability Fetch & Render ---

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

// Hook refreshAll to also update analytics
const originalRefreshAll = refreshAll;
refreshAll = async function() {
  await originalRefreshAll();
  await fetchAnalyticsData();
};

// Global function for table action
window.trashSingleEmail = async function(emailId) {
  try {
    await fetch(`/api/emails/${emailId}/trash`, { method: 'POST' });
    showToast('Moved to trash.', 'info');
    await refreshAll();
  } catch (err) {
    showToast('Failed: ' + err.message, 'error');
  }
};

// --- Toast Notification Helper ---
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
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
  }, 4000);
}
