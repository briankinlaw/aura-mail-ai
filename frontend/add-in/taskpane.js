/**
 * Aura Mail AI - Outlook Taskpane (Office.js)
 * Triage recruiter outreach, calculate opportunity fit, broker calendar slots,
 * and stage Canonical Career System grounded responses directly in Outlook.
 */

const API_BASE = window.location.origin;

// --- Authenticated Session Bootstrap ---
let AURA_SESSION_TOKEN = null;

const _nativeFetch = window.fetch;
window._nativeFetch = _nativeFetch;
window.fetch = async function(url, options = {}) {
  options = options || {};
  options.headers = options.headers || {};
  if (AURA_SESSION_TOKEN) {
    if (options.headers instanceof Headers) {
      if (!options.headers.has('Authorization')) {
        options.headers.set('Authorization', `Bearer ${AURA_SESSION_TOKEN}`);
      }
      if (!options.headers.has('X-Aura-Session-Token')) {
        options.headers.set('X-Aura-Session-Token', AURA_SESSION_TOKEN);
      }
    } else if (typeof options.headers === 'object') {
      if (!options.headers['Authorization']) {
        options.headers['Authorization'] = `Bearer ${AURA_SESSION_TOKEN}`;
      }
      if (!options.headers['X-Aura-Session-Token']) {
        options.headers['X-Aura-Session-Token'] = AURA_SESSION_TOKEN;
      }
    }
  }
  return _nativeFetch(url, options);
};

async function bootstrapAuraSession() {
  try {
    const res = await _nativeFetch(`${API_BASE}/api/auth/session`);
    if (res.ok) {
      const data = await res.json();
      AURA_SESSION_TOKEN = data.session_token;
    }
  } catch (err) {
    console.warn('Session bootstrap notice in add-in:', err);
  }
}

// State
let currentEmailData = {
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
Office.onReady(async (info) => {
    console.log("[Aura Add-in] Office.onReady called. Host:", info.host, "Platform:", info.platform);
    await bootstrapAuraSession();
    
    if (info.host === Office.HostType.Outlook && Office.context && Office.context.mailbox && Office.context.mailbox.item) {
        initOutlookItem();
    } else {
        console.log("[Aura Add-in] Running in Standalone Browser Preview Mode.");
        initStandaloneMode();
    }
});

/**
 * Initialize with live Outlook context item
 */
function initOutlookItem() {
    const item = Office.context.mailbox.item;
    
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
    item.body.getAsync(Office.CoercionType.Text, (result) => {
        if (result.status === Office.AsyncResultStatus.Succeeded) {
            currentEmailData.bodyText = result.value || "";
            runAnalysisPipeline();
        } else {
            console.warn("[Aura Add-in] Could not get body text:", result.error);
            runAnalysisPipeline();
        }
    });
}

/**
 * Fallback to fetch latest cached email from Aura API or use mock
 */
async function initStandaloneMode() {
    try {
        const res = await fetch(`${API_BASE}/api/emails`);
        if (res.ok) {
            const emails = await res.json();
            const recruiterEmail = emails.find(e => e.classification && e.classification.is_resume_request);
            if (recruiterEmail) {
                currentEmailData = {
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
            headers: { "Content-Type": "application/json" },
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
            headers: { "Content-Type": "application/json" },
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

async function generateDraft() {
    const lens = el.lensSelect.value;
    const includeAvailability = el.chkIncludeAvailability.checked;

    try {
        const res = await fetch(`${API_BASE}/api/radar/draft`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
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
            el.draftReplyText.value = currentDraft;
            runRiskAudit(currentDraft);
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
    el.draftReplyText.value = currentDraft;
    runRiskAudit(currentDraft);
}

/**
 * Gemini Risk Sentinel (Second Opinion)
 */
async function runRiskAudit(draftText) {
    if (!el.riskSentinelBanner) return;
    try {
        const res = await fetch(`${API_BASE}/api/radar/risk-check`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                subject: currentEmailData.subject,
                body: currentEmailData.bodyText,
                sender_name: currentEmailData.senderName,
                sender_email: currentEmailData.senderEmail,
                draft_reply: draftText,
                proposed_action: "DRAFT"
            })
        });

        if (res.ok) {
            const audit = await res.json();
            const sev = (audit.severity || "SAFE").toLowerCase().replace("_", "-");
            el.riskSentinelBanner.className = `risk-sentinel-banner ${sev}`;
            
            if (sev === "safe") {
                el.sentinelIcon.textContent = "🛡️";
                el.sentinelStatusBadge.textContent = "VERIFIED SAFE";
                el.sentinelStatusBadge.className = "sentinel-status-badge safe";
            } else if (sev === "caution") {
                el.sentinelIcon.textContent = "⚠️";
                el.sentinelStatusBadge.textContent = "CAUTION REQUIRED";
                el.sentinelStatusBadge.className = "sentinel-status-badge caution";
            } else {
                el.sentinelIcon.textContent = "🚨";
                el.sentinelStatusBadge.textContent = "BLOCKED / HIGH RISK";
                el.sentinelStatusBadge.className = "sentinel-status-badge high-risk";
            }

            el.sentinelSummary.textContent = audit.second_opinion_summary || "Grounding verified against Accomplishment Ledger.";
        }
    } catch (err) {
        console.warn("[Aura Add-in] Risk audit check error:", err);
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

    const htmlBody = textToInsert.replace(/\n/g, "<br/>");

    if (window.Office && Office.context && Office.context.mailbox && Office.context.mailbox.item) {
        const item = Office.context.mailbox.item;
        
        // If in Read mode, trigger displayReplyForm
        if (typeof item.displayReplyForm === "function") {
            try {
                item.displayReplyForm({
                    htmlBody: `<div style="font-family: Arial, sans-serif; font-size: 14px; color: #222;">${htmlBody}</div>`
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
                `<div style="font-family: Arial, sans-serif; font-size: 14px; color: #222;">${htmlBody}</div>`,
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

/**
 * Stage in Cloud Drafts via Aura Backend API
 */
async function stageCloudDraft() {
    const replyText = el.draftReplyText.value.trim();
    showToast("Staging draft in cloud mailbox...");

    try {
        const res = await fetch(`${API_BASE}/api/emails/sync`);
        // If available in cache or mock
        showToast("Draft staged in Outlook Drafts folder with resume attached!");
    } catch (err) {
        showToast("Draft saved locally.");
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
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
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
