/**
 * Aura Mail AI - Outlook Taskpane (Office.js)
 * Triage recruiter outreach, calculate opportunity fit, broker calendar slots,
 * and stage Canonical Career System grounded responses directly in Outlook.
 */

const API_BASE = window.location.origin;

// --- Authenticated Session Initialization from Same-Origin Runtime ---
let AURA_SESSION_TOKEN = window.__AURA_SESSION_TOKEN__ || null;

/**
 * Returns authorization headers including the active Aura session token.
 */
function getAuthHeaders(extraHeaders = {}) {
    const token = window.__AURA_SESSION_TOKEN__ || AURA_SESSION_TOKEN || "";
    const headers = {
        "Content-Type": "application/json",
        ...extraHeaders
    };
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
        headers["X-Aura-Session-Token"] = token;
    }
    return headers;
}

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

// State
let currentEmailData = {
    id: null,
    account_id: null,
    subject: "Senior Solutions Architect & Strategic Advisor Reachout",
    senderName: "Sarah Jenkins",
    senderEmail: "sjenkins@techrecruitingpartners.com",
    bodyText: "Hi Brian, I came across your impressive background leading Google Cloud and enterprise AI architectures. We have an executive Solutions Architecture opening at our client that seems like an exact match. Could you share your updated resume and let us know your availability for an intro chat?",
    date: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
};

let currentTriageResult = null;
let currentDraft = "";
let currentSlots = [];
let selectedTone = "Professional & Warm";

// DOM Elements
const el = {
    loadingView: document.getElementById("loadingView"),
    mainView: document.getElementById("mainView"),
    loadingMessage: document.getElementById("loadingMessage"),
    connectionStatus: document.getElementById("connectionStatus"),
    btnRescan: document.getElementById("btnRescan"),
    
    // Context
    categoryBadge: document.getElementById("categoryBadge"),
    emailTime: document.getElementById("emailTime"),
    emailSubject: document.getElementById("emailSubject"),
    senderName: document.getElementById("senderName"),
    senderEmail: document.getElementById("senderEmail"),
    
    // Radar
    fitScoreVal: document.getElementById("fitScoreVal"),
    fitTierBadge: document.getElementById("fitTierBadge"),
    scoreCircle: document.getElementById("scoreCircle"),
    detectedRole: document.getElementById("detectedRole"),
    detectedCompany: document.getElementById("detectedCompany"),
    detectedSalary: document.getElementById("detectedSalary"),
    signalTagsContainer: document.getElementById("signalTagsContainer"),
    
    // Lens
    lensSelect: document.getElementById("lensSelect"),
    activeResumeFilename: document.getElementById("activeResumeFilename"),
    
    // Scribe
    draftReplyText: document.getElementById("draftReplyText"),
    btnRegenerate: document.getElementById("btnRegenerate"),
    chkIncludeAvailability: document.getElementById("chkIncludeAvailability"),
    btnInsertReply: document.getElementById("btnInsertReply"),
    btnStageDraft: document.getElementById("btnStageDraft"),
    btnCopyClipboard: document.getElementById("btnCopyClipboard"),
    
    // Calendar
    slotsList: document.getElementById("slotsList"),
    btnCopySlots: document.getElementById("btnCopySlots"),
    
    // Risk Sentinel (Second Opinion)
    riskSentinelBanner: document.getElementById("riskSentinelBanner"),
    sentinelIcon: document.getElementById("sentinelIcon"),
    sentinelStatusBadge: document.getElementById("sentinelStatusBadge"),
    sentinelSummary: document.getElementById("sentinelSummary"),

    // Toast
    toast: document.getElementById("toast"),
    toastMessage: document.getElementById("toastMessage")
};

// Initialize Office.js or Standalone Mode
Office.onReady((info) => {
    console.log("[Aura Add-in] Office.onReady called. Host:", info.host, "Platform:", info.platform);
    
    if (info.host === Office.HostType.Outlook && Office.context && Office.context.mailbox && Office.context.mailbox.item) {
        initOutlookItem();
    } else {
        console.log("[Aura Add-in] Running in Standalone Browser Preview Mode.");
        initStandaloneMode();
    }
});

/**
 * Initialize with live Outlook context item (Phase 2.1 Unified Item Resolution)
 */
async function initOutlookItem() {
    const item = Office.context.mailbox.item;
    
    // Acquire Office.js item ID and normalize to Graph REST ID
    let rawItemId = item.itemId;
    let normalizedRestId = rawItemId;
    if (rawItemId && Office.context.mailbox.convertToRestId && Office.MailboxEnums && Office.MailboxEnums.RestVersion) {
        try {
            normalizedRestId = Office.context.mailbox.convertToRestId(rawItemId, Office.MailboxEnums.RestVersion.v2_0);
        } catch (e) {
            console.warn("[Aura Add-in] convertToRestId conversion error:", e);
        }
    }

    const userEmail = (Office.context.mailbox.userProfile && Office.context.mailbox.userProfile.emailAddress)
        ? Office.context.mailbox.userProfile.emailAddress.toLowerCase()
        : null;

    // Check if the item can be positively resolved in Aura's cache
    if (normalizedRestId) {
        try {
            const resolveRes = await fetch(`${API_BASE}/api/emails/resolve-item`, {
                method: "POST",
                headers: getAuthHeaders(),
                body: JSON.stringify({
                    provider: "MICROSOFT_GRAPH",
                    account_id: userEmail,
                    item_id: normalizedRestId
                })
            });

            if (resolveRes.ok) {
                const resolvedData = await resolveRes.json();
                if (resolvedData.found && resolvedData.email) {
                    const cachedEmail = resolvedData.email;
                    currentEmailData = {
                        id: resolvedData.composite_id,
                        account_id: cachedEmail.account_id || userEmail,
                        subject: cachedEmail.subject || item.subject || "No Subject",
                        senderName: cachedEmail.sender_name || (item.from ? item.from.displayName : "Recruiter"),
                        senderEmail: cachedEmail.sender_email || (item.from ? item.from.emailAddress : ""),
                        bodyText: cachedEmail.body_text || "",
                        date: new Date(cachedEmail.received_at || item.dateTimeCreated || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                    };
                    runAnalysisPipeline();
                    return;
                }
            } else if (resolveRes.status === 401 || resolveRes.status === 403) {
                console.error(`[Aura Add-in] Resolver authorization failure (${resolveRes.status}). Session token missing or invalid.`);
            } else if (resolveRes.status === 404) {
                console.log("[Aura Add-in] Item not in local cache; reading directly from active Office.js item.");
            } else {
                console.warn("[Aura Add-in] Item resolution returned unexpected status:", resolveRes.status);
            }
        } catch (err) {
            console.warn("[Aura Add-in] Item resolution error:", err);
        }
    }

    // Direct read from open Outlook item
    currentEmailData.account_id = userEmail;
    currentEmailData.subject = item.subject || "No Subject";
    
    if (item.from) {
        currentEmailData.senderName = item.from.displayName || item.from.emailAddress || "Recruiter";
        currentEmailData.senderEmail = item.from.emailAddress || "";
    } else if (item.sender) {
        currentEmailData.senderName = item.sender.displayName || item.sender.emailAddress || "Recruiter";
        currentEmailData.senderEmail = item.sender.emailAddress || "";
    }

    if (item.dateTimeCreated) {
        currentEmailData.date = new Date(item.dateTimeCreated).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    // Read email body text
    if (item.body && typeof item.body.getAsync === "function") {
        item.body.getAsync(Office.CoercionType.Text, (result) => {
            if (result.status === Office.AsyncResultStatus.Succeeded) {
                currentEmailData.bodyText = result.value || "";
                runAnalysisPipeline();
            } else {
                console.warn("[Aura Add-in] Could not get body text:", result.error);
                runAnalysisPipeline();
            }
        });
    } else {
        runAnalysisPipeline();
    }
}

/**
 * Fallback to fetch latest cached email from Aura API or use mock
 */
async function initStandaloneMode() {
    try {
        const res = await fetch(`${API_BASE}/api/emails`, {
            headers: getAuthHeaders()
        });
        if (res.ok) {
            const emails = await res.json();
            const recruiterEmail = (Array.isArray(emails) && emails.find(e => e.classification && e.classification.is_resume_request)) || (Array.isArray(emails) && emails[0]) || null;
            if (recruiterEmail) {
                currentEmailData = {
                    id: recruiterEmail.id,
                    account_id: recruiterEmail.account_id,
                    subject: recruiterEmail.subject,
                    senderName: recruiterEmail.sender_name,
                    senderEmail: recruiterEmail.sender_email,
                    bodyText: recruiterEmail.body_text,
                    date: new Date(recruiterEmail.received_at || Date.now()).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                };
            }
        }
    } catch (err) {
        console.warn("[Aura Add-in] API check failed, using simulated data", err);
    }
    runAnalysisPipeline();
}

/**
 * Run end-to-end Opportunity Radar Triage, Availability Broker, and Scribe
 */
async function runAnalysisPipeline() {
    showLoading(true, "Scanning opportunity signals & calculating fit...");
    updateContextUI();

    try {
        // 1. Opportunity Radar Triage
        const triageRes = await fetch(`${API_BASE}/api/radar/triage`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({
                subject: currentEmailData.subject,
                body: currentEmailData.bodyText,
                sender_name: currentEmailData.senderName,
                sender_email: currentEmailData.senderEmail
            })
        });

        if (triageRes.ok) {
            currentTriageResult = await triageRes.json();
            updateRadarUI(currentTriageResult);
        }

        // 2. Fetch Availability Slots
        fetchAvailabilitySlots();

        // 3. Generate Grounded Scribe Response
        await generateDraft();

    } catch (err) {
        console.error("[Aura Add-in] Pipeline error:", err);
        showToast("Opportunity analysis ready (offline mode)");
    } finally {
        showLoading(false);
    }
}

function updateContextUI() {
    el.emailSubject.textContent = currentEmailData.subject;
    el.senderName.textContent = currentEmailData.senderName;
    el.senderEmail.textContent = `<${currentEmailData.senderEmail}>`;
    el.emailTime.textContent = currentEmailData.date;
}

function updateRadarUI(data) {
    const score = data.fit_score || 85;
    el.fitScoreVal.textContent = score;
    
    // Conic gradient for score ring
    const color = score >= 75 ? "#10b981" : score >= 50 ? "#f59e0b" : "#ef4444";
    el.scoreCircle.style.background = `conic-gradient(${color} 0% ${score}%, #334155 ${score}% 100%)`;
    
    // Tier badge
    const tier = data.verdict || (score >= 75 ? "HIGH FIT" : score >= 50 ? "MEDIUM FIT" : "LOW FIT");
    el.fitTierBadge.textContent = tier;
    el.fitTierBadge.className = `fit-tier-badge ${score >= 75 ? 'high' : score >= 50 ? 'medium' : 'low'}`;
    
    // Role & Company
    el.detectedRole.textContent = data.role || "Solutions Architecture & AI Lead";
    el.detectedCompany.textContent = data.company || "Enterprise Client";
    el.detectedSalary.textContent = data.salary || "Competitive / Senior Bracket";
    
    // Signals
    if (data.key_points && data.key_points.length > 0) {
        el.signalTagsContainer.innerHTML = data.key_points
            .map(pt => `<span class="tag">${escapeHtml(pt)}</span>`)
            .join("");
    }

    // Update suggested lens & resume
    if (data.suggested_resume) {
        el.activeResumeFilename.textContent = data.suggested_resume;
    }
}

async function fetchAvailabilitySlots() {
    try {
        const res = await fetch(`${API_BASE}/api/calendar/availability`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ days_ahead: 7, timezone: "America/Chicago" })
        });
        if (res.ok) {
            const data = await res.json();
            currentSlots = data.slots || [];
            if (currentSlots.length > 0) {
                el.slotsList.innerHTML = currentSlots
                    .slice(0, 3)
                    .map(s => `<li class="slot-item">${escapeHtml(s.formatted_display)}</li>`)
                    .join("");
            } else {
                el.slotsList.innerHTML = `<li class="slot-item">Flexible availability during US business hours.</li>`;
            }
        }
    } catch (err) {
        console.warn("[Aura Add-in] Could not fetch calendar slots:", err);
        el.slotsList.innerHTML = `<li class="slot-item">Tuesday &amp; Thursday 10:00 AM – 2:00 PM CT</li>`;
    }
}

let currentDraftId = null;
let currentClaimBindings = [];

async function generateDraft() {
    const lens = el.lensSelect.value;
    const includeAvailability = el.chkIncludeAvailability.checked;

    try {
        const res = await fetch(`${API_BASE}/api/radar/draft`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({
                subject: currentEmailData.subject,
                body: currentEmailData.bodyText,
                sender_name: currentEmailData.senderName,
                lens: lens,
                tone: selectedTone,
                include_availability: includeAvailability,
                selected_resume: el.activeResumeFilename.textContent
            })
        });

        if (res.ok) {
            const data = await res.json();
            currentDraft = data.draft_reply || "";
            currentDraftId = data.draft_id || null;
            currentClaimBindings = data.claim_bindings || [];
            el.draftReplyText.value = currentDraft;
            runRiskAudit(currentDraft, currentDraftId, currentClaimBindings);
        } else {
            fallbackDraft(lens, includeAvailability);
        }
    } catch (err) {
        fallbackDraft(lens, includeAvailability);
    }
}

function fallbackDraft(lens, includeAvailability) {
    const recName = currentEmailData.senderName.split(" ")[0] || "there";
    const resume = el.activeResumeFilename.textContent;
    let availBlock = "";
    if (includeAvailability) {
        availBlock = "\n\nHere are a few times I am available for a brief introductory conversation next week:\n" +
                     "• Tuesday: 10:00 AM – 10:30 AM CT\n" +
                     "• Wednesday: 2:00 PM – 2:30 PM CT\n" +
                     "• Thursday: 11:00 AM – 11:30 AM CT";
    }
    currentDraft = `Hi ${recName},\n\n` +
        `Thank you for reaching out regarding the opportunity. The scope directly aligns with my background in enterprise cloud architectures, data platforms, and AI systems.\n\n` +
        `Over my career across Google Cloud, CDW, and enterprise advisory, I have influenced and delivered $100M+ in enterprise revenue, including influencing $8M in new Google Cloud revenue.\n\n` +
        `I have attached my updated resume (${resume}) for your review.${availBlock}\n\n` +
        `Please feel free to suggest a time that suits your schedule or share a calendar link.\n\n` +
        `Best regards,\nBrian Kinlaw\nStrategic Advisor, Data & AI | Solutions Architecture\n(210) 717-5305 | linkedin.com/in/briankinlaw`;
    currentDraftId = null;
    currentClaimBindings = [];
    el.draftReplyText.value = currentDraft;
    runRiskAudit(currentDraft, null, []);
}

/**
 * Gemini Risk Sentinel (Second Opinion)
 */
let currentAuditRequestId = 0;

function invalidateRiskAudit(reason = "Draft modified after audit.") {
    currentAuditRequestId += 1;
    currentDraftId = null;
    currentClaimBindings = [];
    if (!el.riskSentinelBanner) return;
    el.riskSentinelBanner.className = "risk-sentinel-banner pending";
    el.sentinelIcon.textContent = "ℹ️";
    el.sentinelStatusBadge.textContent = "RE-AUDIT REQUIRED";
    el.sentinelStatusBadge.className = "sentinel-status-badge pending";
    el.sentinelSummary.textContent = "Draft changed after its last risk check. The previous audit no longer applies.";
}

async function runRiskAudit(draftText, draftId = currentDraftId, claimBindings = currentClaimBindings) {
    if (!el.riskSentinelBanner) return;

    const auditRequestId = ++currentAuditRequestId;

    // Immediately clear prior status when a new audit starts
    el.riskSentinelBanner.className = "risk-sentinel-banner pending";
    el.sentinelIcon.textContent = "⏳";
    el.sentinelStatusBadge.textContent = "AUDITING...";
    el.sentinelStatusBadge.className = "sentinel-status-badge pending";
    el.sentinelSummary.textContent = "Evaluating draft safety and grounding against Accomplishment Ledger...";

    try {
        const res = await fetch(`${API_BASE}/api/radar/risk-check`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({
                subject: currentEmailData.subject,
                body: currentEmailData.bodyText,
                sender_name: currentEmailData.senderName,
                sender_email: currentEmailData.senderEmail,
                draft_reply: draftText,
                proposed_action: "DRAFT",
                draft_id: draftId,
                claim_bindings: claimBindings
            })
        });

        // Stale check 1: after fetch() network boundary
        if (auditRequestId !== currentAuditRequestId) {
            return;
        }

        if (res.ok) {
            let audit;
            try {
                audit = await res.json();
            } catch (jsonErr) {
                if (auditRequestId !== currentAuditRequestId) return;
                console.warn("[Aura Add-in] Risk audit JSON parse error:", jsonErr);
                el.riskSentinelBanner.className = "risk-sentinel-banner unavailable";
                el.sentinelIcon.textContent = "ℹ️";
                el.sentinelStatusBadge.textContent = "RISK CHECK UNAVAILABLE";
                el.sentinelStatusBadge.className = "sentinel-status-badge unavailable";
                el.sentinelSummary.textContent = "Automated risk check response was malformed. Human review required before native client dispatch.";
                return;
            }

            // Stale check 2: after await res.json() parse boundary before interpretation and rendering
            if (auditRequestId !== currentAuditRequestId) {
                return;
            }

            // Defense-in-depth: content correlation verification
            if (el.draftReplyText && el.draftReplyText.value !== draftText) {
                invalidateRiskAudit("Draft content diverged from audited text.");
                return;
            }

            const sev = String(audit.severity || "").toUpperCase();
            const action = String(audit.recommended_action || "").toUpperCase();
            const isExplicitSafe = (sev === "SAFE" && action === "PROCEED");
            const isHighRisk = (sev === "HIGH_RISK" || action === "BLOCKED");
            const isCaution = (!isHighRisk && (sev === "CAUTION" || action === "REVIEW_CAUTION"));
            const groundingStatus = String(audit.grounding_status || "").toUpperCase();

            if (isExplicitSafe) {
                el.riskSentinelBanner.className = "risk-sentinel-banner safe";
                el.sentinelIcon.textContent = "🛡️";
                if (groundingStatus === "GROUNDED") {
                    el.sentinelStatusBadge.textContent = "SAFE • GROUNDED";
                } else if (groundingStatus === "NO_CAREER_CLAIMS_DETECTED") {
                    el.sentinelStatusBadge.textContent = "SAFE • NO CAREER CLAIMS";
                } else {
                    el.sentinelStatusBadge.textContent = "SAFE";
                }
                el.sentinelStatusBadge.className = "sentinel-status-badge safe";
                el.sentinelSummary.textContent = audit.second_opinion_summary || "Grounding verified against Accomplishment Ledger.";
            } else if (isHighRisk) {
                el.riskSentinelBanner.className = "risk-sentinel-banner high-risk";
                el.sentinelIcon.textContent = "🚨";
                el.sentinelStatusBadge.textContent = "BLOCKED / HIGH RISK";
                el.sentinelStatusBadge.className = "sentinel-status-badge high-risk";
                el.sentinelSummary.textContent = audit.second_opinion_summary || "High-risk signals detected. Direct action blocked.";
            } else if (isCaution) {
                el.riskSentinelBanner.className = "risk-sentinel-banner caution";
                el.sentinelIcon.textContent = "⚠️";
                el.sentinelStatusBadge.textContent = "CAUTION REQUIRED";
                el.sentinelStatusBadge.className = "sentinel-status-badge caution";
                el.sentinelSummary.textContent = audit.second_opinion_summary || "Cautionary items detected requiring review.";
            } else {
                // Malformed / unrecognized response structure: FAIL SAFE
                el.riskSentinelBanner.className = "risk-sentinel-banner unavailable";
                el.sentinelIcon.textContent = "ℹ️";
                el.sentinelStatusBadge.textContent = "REVIEW REQUIRED";
                el.sentinelStatusBadge.className = "sentinel-status-badge unavailable";
                el.sentinelSummary.textContent = "Risk audit returned an unrecognized result. Manual review required.";
            }
        } else {
            // Non-2xx response: FAIL SAFE
            el.riskSentinelBanner.className = "risk-sentinel-banner unavailable";
            el.sentinelIcon.textContent = "ℹ️";
            el.sentinelStatusBadge.textContent = "RISK CHECK UNAVAILABLE";
            el.sentinelStatusBadge.className = "sentinel-status-badge unavailable";
            el.sentinelSummary.textContent = "Automated risk check could not be completed. Human review required before native client dispatch.";
        }
    } catch (err) {
        if (auditRequestId !== currentAuditRequestId) {
            return;
        }
        console.warn("[Aura Add-in] Risk audit check error:", err);
        el.riskSentinelBanner.className = "risk-sentinel-banner unavailable";
        el.sentinelIcon.textContent = "ℹ️";
        el.sentinelStatusBadge.textContent = "RISK CHECK UNAVAILABLE";
        el.sentinelStatusBadge.className = "sentinel-status-badge unavailable";
        el.sentinelSummary.textContent = "Automated risk check could not be completed. Human review required before native client dispatch.";
    }
}

/**
 * Pre-fill or Insert Reply into Outlook Compose Window
 */
function insertReplyIntoOutlook() {
    const textToInsert = el.draftReplyText.value.trim();
    if (!textToInsert) {
        showToast("No draft text to insert");
        return;
    }

    const safeHtml = formatReplyAsSafeHtml(textToInsert);

    if (typeof Office !== "undefined" && Office && Office.context && Office.context.mailbox && Office.context.mailbox.item) {
        const item = Office.context.mailbox.item;
        
        // If in Read mode, trigger displayReplyForm
        if (typeof item.displayReplyForm === "function") {
            try {
                item.displayReplyForm({
                    htmlBody: `<div style="font-family: Arial, sans-serif; font-size: 14px; color: #222;">${safeHtml}</div>`
                });
                showToast("Reply form opened with staged draft!");
                return;
            } catch (err) {
                console.warn("displayReplyForm failed:", err);
            }
        }
        
        // If already composing, set body
        if (item.body && typeof item.body.setAsync === "function") {
            item.body.setAsync(
                `<div style="font-family: Arial, sans-serif; font-size: 14px; color: #222;">${safeHtml}</div>`,
                { coercionType: Office.CoercionType.Html },
                (asyncResult) => {
                    if (asyncResult.status === Office.AsyncResultStatus.Succeeded) {
                        showToast("Draft inserted into Outlook reply!");
                    } else {
                        copyToClipboard(textToInsert);
                        showToast("Copied to clipboard (Ready to paste)");
                    }
                }
            );
            return;
        }
    }

    // Fallback: Copy to clipboard
    copyToClipboard(textToInsert);
    showToast("Copied to clipboard! Ready to paste into Outlook.");
}

let isStagingDraft = false;

/**
 * Validates backend response contract for cloud draft staging.
 * Requires successful HTTP status, parsed JSON object, success flag, and valid non-empty string draft ID.
 */
function validateStageDraftResponse(res, data) {
    if (!res || !res.ok) {
        return {
            isValid: false,
            errorType: "HTTP_ERROR",
            statusCode: res ? res.status : 0,
            message: `HTTP ${res ? res.status : "unknown"}`
        };
    }
    if (!data || typeof data !== "object" || Array.isArray(data)) {
        return {
            isValid: false,
            errorType: "MALFORMED_RESPONSE",
            message: "Malformed response shape from server."
        };
    }
    if (!data.success) {
        return {
            isValid: false,
            errorType: "PROVIDER_FAILURE",
            message: data.safe_message || data.error_code || "Provider rejected draft staging."
        };
    }
    const remoteId = data.remote_object_id || data.draft_id;
    if (!remoteId || typeof remoteId !== "string" || !remoteId.trim()) {
        return {
            isValid: false,
            errorType: "MISSING_DRAFT_ID",
            message: "Authoritative provider draft identifier missing from confirmation."
        };
    }
    return {
        isValid: true,
        draftId: remoteId.trim(),
        message: data.safe_message || "Draft staged successfully in cloud mailbox!"
    };
}

/**
 * Stage in Cloud Drafts via Aura Backend API
 *
 * Persistence operation only: creates/stages a provider draft in Outlook/Graph drafts folder.
 * NEVER invokes, authorizes, or implies provider send.
 */
async function stageCloudDraft() {
    if (isStagingDraft) {
        return;
    }

    const emailId = currentEmailData && currentEmailData.id ? currentEmailData.id : null;
    if (!emailId) {
        showToast("Cannot stage draft: Email message context is missing or unlinked.");
        return;
    }

    const replyText = el.draftReplyText ? el.draftReplyText.value.trim() : "";
    if (!replyText) {
        showToast("Cannot stage draft: Draft text is empty.");
        return;
    }

    const resumeFilename = (el.activeResumeFilename && el.activeResumeFilename.textContent)
        ? el.activeResumeFilename.textContent.trim()
        : null;

    const accountId = (currentEmailData && currentEmailData.account_id)
        ? currentEmailData.account_id
        : (typeof Office !== "undefined" && Office.context && Office.context.mailbox && Office.context.mailbox.userProfile && Office.context.mailbox.userProfile.emailAddress
            ? Office.context.mailbox.userProfile.emailAddress.toLowerCase()
            : null);

    const payload = {
        reply_body: replyText,
        resume_filename: resumeFilename,
        draft_id: currentDraftId,
        claim_bindings: currentClaimBindings,
        account_id: accountId
    };

    isStagingDraft = true;
    if (el.btnStageDraft) {
        el.btnStageDraft.disabled = true;
    }
    showToast("Staging draft in cloud mailbox...");

    try {
        const res = await fetch(`${API_BASE}/api/emails/${encodeURIComponent(emailId)}/save-draft`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            let errDetail = "";
            try {
                const errData = await res.json();
                if (errData && errData.detail) {
                    errDetail = typeof errData.detail === "string" ? errData.detail : JSON.stringify(errData.detail);
                } else if (errData && errData.safe_message) {
                    errDetail = errData.safe_message;
                }
            } catch (_) {
                // Ignore json parse failure on error responses
            }

            if (res.status === 400) {
                showToast(`Draft staging failed: Invalid request (HTTP 400)${errDetail ? ' - ' + errDetail : ''}`);
            } else if (res.status === 401) {
                showToast("Draft staging failed: Authentication required (HTTP 401). Please re-authenticate.");
            } else if (res.status === 403) {
                showToast(`Draft staging failed: Authorization denied or account mismatch (HTTP 403)${errDetail ? ' - ' + errDetail : ''}`);
            } else if (res.status === 404) {
                showToast("Draft staging failed: Message context not found in Aura (HTTP 404).");
            } else if (res.status >= 500) {
                showToast(`Draft staging failed: Server or provider error (HTTP ${res.status})${errDetail ? ' - ' + errDetail : ''}`);
            } else {
                showToast(`Draft staging failed with HTTP status ${res.status}.`);
            }
            return;
        }

        let data;
        try {
            data = await res.json();
        } catch (jsonErr) {
            showToast("Draft staging failed: Malformed JSON response from server.");
            return;
        }

        const validation = validateStageDraftResponse(res, data);
        if (!validation.isValid) {
            showToast(`Draft staging failed: ${validation.message}`);
            return;
        }

        // Confirmed draft creation success
        showToast("Draft staged successfully in cloud mailbox!");
    } catch (err) {
        console.error("[Aura Add-in] Stage cloud draft network error:", err);
        showToast(`Draft staging failed: Network error (${err.message || "Unable to reach server"}).`);
    } finally {
        isStagingDraft = false;
        if (el.btnStageDraft) {
            el.btnStageDraft.disabled = false;
        }
    }
}

/**
 * Clipboard Helpers
 */
function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text);
    } else {
        const temp = document.createElement("textarea");
        temp.value = text;
        document.body.appendChild(temp);
        temp.select();
        document.execCommand("copy");
        document.body.removeChild(temp);
    }
}

function showToast(message) {
    el.toastMessage.textContent = message;
    el.toast.classList.remove("hidden");
    setTimeout(() => {
        el.toast.classList.add("hidden");
    }, 2800);
}

function showLoading(isLoading, msg = "Loading...") {
    if (isLoading) {
        el.loadingMessage.textContent = msg;
        el.loadingView.classList.remove("hidden");
        el.mainView.style.display = "none";
    } else {
        el.loadingView.classList.add("hidden");
        el.mainView.style.display = "flex";
    }
}

function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function formatReplyAsSafeHtml(untrustedText) {
    if (!untrustedText) return "";
    return escapeHtml(untrustedText).replace(/\r?\n/g, "<br/>");
}

// Event Listeners
el.btnRescan.addEventListener("click", () => runAnalysisPipeline());
el.btnRegenerate.addEventListener("click", () => generateDraft());

el.lensSelect.addEventListener("change", (e) => {
    const val = e.target.value;
    if (val === "Advisor") {
        el.activeResumeFilename.textContent = "Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx";
    } else if (val === "SME") {
        el.activeResumeFilename.textContent = "Brian_Kinlaw_2026-09-08_Technical_SME_Canonical_current.docx";
    } else if (val === "Leadership") {
        el.activeResumeFilename.textContent = "Brian_Kinlaw_2026-09-08_Leadership_VP_Director_Canonical_current.docx";
    } else {
        el.activeResumeFilename.textContent = "Brian_Kinlaw_2026-09-08_Consulting_Practice_Lead_Canonical_current.docx";
    }
    generateDraft();
});

document.querySelectorAll(".btn-tone").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".btn-tone").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        selectedTone = btn.getAttribute("data-tone");
        generateDraft();
    });
});

el.chkIncludeAvailability.addEventListener("change", () => generateDraft());
el.btnInsertReply.addEventListener("click", insertReplyIntoOutlook);
el.btnStageDraft.addEventListener("click", stageCloudDraft);
el.btnCopyClipboard.addEventListener("click", () => {
    copyToClipboard(el.draftReplyText.value);
    showToast("Draft copied to clipboard!");
});

if (el.draftReplyText) {
    el.draftReplyText.addEventListener("input", () => {
        invalidateRiskAudit("User edited draft text.");
    });
}

el.btnCopySlots.addEventListener("click", () => {
    if (currentSlots.length > 0) {
        const text = currentSlots.slice(0, 3).map(s => `• ${s.formatted_display}`).join("\n");
        copyToClipboard(text);
        showToast("Booking slots copied!");
    } else {
        copyToClipboard("Tuesday & Thursday 10:00 AM – 2:00 PM CT");
        showToast("Default slots copied!");
    }
});

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        validateStageDraftResponse,
        stageCloudDraft,
        getAuthHeaders,
        escapeHtml,
        formatReplyAsSafeHtml,
        insertReplyIntoOutlook
    };
}
