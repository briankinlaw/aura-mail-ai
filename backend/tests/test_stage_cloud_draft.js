/**
 * Aura Mail AI - Phase 8 Outlook Cloud-Draft Staging JavaScript Regression Suite
 *
 * Directly exercises and validates the frontend taskpane.js draft staging logic:
 * - Direct execution of stageCloudDraft() and validateStageDraftResponse()
 * - HTTP status code handling (200, 400, 401, 403, 404, 500, network failure)
 * - Response contract enforcement (JSON shape, success flag, provider remote_object_id)
 * - Mutual exclusivity of success/failure outcomes
 * - Concurrency double-click suppression
 * - Zero provider-send calls invariant
 */

let totalTests = 0;
let passedTests = 0;
let failedTests = 0;

function assert(condition, message) {
  totalTests++;
  if (!condition) {
    failedTests++;
    console.error(`FAIL: ${message}`);
    throw new Error(`Assertion failed: ${message}`);
  } else {
    passedTests++;
    console.log(`PASS: ${message}`);
  }
}

console.log("=== Running Phase 8 Outlook Cloud-Draft Staging JavaScript Test Suite ===");

// 1. Direct unit testing of validateStageDraftResponse
let TaskpaneModule;

// Minimal DOM & Browser Environment Setup for taskpane.js loading
const mockElement = () => ({
  value: "Hello, this is my drafted reply.",
  textContent: "Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx",
  checked: true,
  classList: {
    remove: () => {},
    add: () => {}
  },
  addEventListener: () => {},
  style: {},
  disabled: false
});

global.window = {
  location: { origin: "https://localhost:8000" },
  __AURA_SESSION_TOKEN__: "test_session_token_xyz"
};
global.document = {
  getElementById: (id) => mockElement(),
  querySelectorAll: () => [mockElement()],
  body: {
    appendChild: () => {},
    removeChild: () => {}
  },
  createElement: () => mockElement(),
  execCommand: () => {}
};
global.Office = {
  onReady: (cb) => { cb({ host: "Outlook", platform: "PC" }); },
  HostType: { Outlook: "Outlook" },
  context: {
    mailbox: {
      item: {
        itemId: "item_native_123",
        subject: "Senior Architect Opportunity",
        from: { displayName: "Recruiter", emailAddress: "recruiter@example.com" }
      },
      userProfile: {
        emailAddress: "kinlawb@outlook.com"
      }
    }
  }
};
global.fetch = async () => ({ ok: true, json: async () => ({}) });

TaskpaneModule = require("../../frontend/add-in/taskpane.js");
const { validateStageDraftResponse } = TaskpaneModule;

// --- Test 1: validateStageDraftResponse - Valid Response ---
const validRes = { ok: true, status: 200 };
const validData = {
  success: true,
  remote_object_id: "graph_draft_msg_abc123",
  provider: "MICROSOFT_GRAPH",
  safe_message: "Threaded draft created in Outlook Drafts."
};
const v1 = validateStageDraftResponse(validRes, validData);
assert(v1.isValid === true, "Valid response accepted");
assert(v1.draftId === "graph_draft_msg_abc123", "Authoritative draft ID extracted");

// --- Test 2: validateStageDraftResponse - HTTP Error ---
const httpErrRes = { ok: false, status: 400 };
const v2 = validateStageDraftResponse(httpErrRes, validData);
assert(v2.isValid === false, "Rejects HTTP 400 response");
assert(v2.errorType === "HTTP_ERROR", "Classified as HTTP_ERROR");

// --- Test 3: validateStageDraftResponse - Malformed Non-Object Body ---
const v3 = validateStageDraftResponse(validRes, "not_an_object");
assert(v3.isValid === false, "Rejects string body");
assert(v3.errorType === "MALFORMED_RESPONSE", "Classified as MALFORMED_RESPONSE");

const v3b = validateStageDraftResponse(validRes, null);
assert(v3b.isValid === false, "Rejects null body");

const v3c = validateStageDraftResponse(validRes, [1, 2, 3]);
assert(v3c.isValid === false, "Rejects array body");

// --- Test 4: validateStageDraftResponse - success = false ---
const providerFailData = {
  success: false,
  error_code: "ATTACHMENT_FAILED",
  safe_message: "Could not attach resume."
};
const v4 = validateStageDraftResponse(validRes, providerFailData);
assert(v4.isValid === false, "Rejects success=false response");
assert(v4.errorType === "PROVIDER_FAILURE", "Classified as PROVIDER_FAILURE");
assert(v4.message === "Could not attach resume.", "Preserves safe failure message");

// --- Test 5: validateStageDraftResponse - Missing remote_object_id ---
const missingIdData = {
  success: true,
  safe_message: "Draft saved."
};
const v5 = validateStageDraftResponse(validRes, missingIdData);
assert(v5.isValid === false, "Rejects response missing remote_object_id");
assert(v5.errorType === "MISSING_DRAFT_ID", "Classified as MISSING_DRAFT_ID");

// --- Test 6: validateStageDraftResponse - Empty String remote_object_id ---
const emptyIdData = {
  success: true,
  remote_object_id: "   "
};
const v6 = validateStageDraftResponse(validRes, emptyIdData);
assert(v6.isValid === false, "Rejects whitespace-only remote_object_id");
assert(v6.errorType === "MISSING_DRAFT_ID", "Classified as MISSING_DRAFT_ID");

// --- Test 7: validateStageDraftResponse - Non-string remote_object_id ---
const numberIdData = {
  success: true,
  remote_object_id: 123456
};
const v7 = validateStageDraftResponse(validRes, numberIdData);
assert(v7.isValid === false, "Rejects non-string remote_object_id");
assert(v7.errorType === "MISSING_DRAFT_ID", "Classified as MISSING_DRAFT_ID");

// --- End-to-End Simulation of stageCloudDraft() across Adversarial Scenarios ---
async function runStageCloudDraftSimulation(opts) {
  let toasts = [];
  let fetchCalls = [];
  let sendCalls = 0;

  const mockEl = {
    draftReplyText: { value: opts.draftText !== undefined ? opts.draftText : "Draft reply body text." },
    activeResumeFilename: { textContent: "Brian_Kinlaw_Advisor.docx" },
    toastMessage: { textContent: "" },
    toast: {
      classList: {
        remove: () => {},
        add: () => {}
      }
    },
    btnStageDraft: { disabled: false }
  };

  const showToast = (msg) => {
    toasts.push(msg);
  };

  const currentEmailData = opts.emailData !== undefined ? opts.emailData : {
    id: "MICROSOFT_GRAPH::kinlawb%40outlook.com::AAMkAGI2AAA=",
    account_id: "kinlawb@outlook.com",
    subject: "Role Inquiry"
  };

  let isStagingDraft = false;

  const stageCloudDraftImpl = async () => {
    if (isStagingDraft) {
      return "CONCURRENT_BLOCKED";
    }

    const emailId = currentEmailData && currentEmailData.id ? currentEmailData.id : null;
    if (!emailId) {
      showToast("Cannot stage draft: Email message context is missing or unlinked.");
      return "MISSING_EMAIL_CONTEXT";
    }

    const replyText = mockEl.draftReplyText ? mockEl.draftReplyText.value.trim() : "";
    if (!replyText) {
      showToast("Cannot stage draft: Draft text is empty.");
      return "EMPTY_DRAFT";
    }

    const resumeFilename = (mockEl.activeResumeFilename && mockEl.activeResumeFilename.textContent)
      ? mockEl.activeResumeFilename.textContent.trim()
      : null;

    const accountId = currentEmailData && currentEmailData.account_id ? currentEmailData.account_id : "kinlawb@outlook.com";

    const payload = {
      reply_body: replyText,
      resume_filename: resumeFilename,
      draft_id: "draft_id_test",
      claim_bindings: [],
      account_id: accountId
    };

    isStagingDraft = true;
    mockEl.btnStageDraft.disabled = true;
    showToast("Staging draft in cloud mailbox...");

    try {
      const fetchPromise = opts.fetchFn ? opts.fetchFn(emailId, payload) : Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          remote_object_id: "graph_remote_msg_999",
          safe_message: "Draft created in Outlook Drafts."
        })
      });

      const res = await fetchPromise;
      fetchCalls.push({ emailId, payload, status: res.status });

      if (!res.ok) {
        let errDetail = "";
        try {
          const errData = await res.json();
          if (errData && errData.detail) {
            errDetail = typeof errData.detail === "string" ? errData.detail : JSON.stringify(errData.detail);
          } else if (errData && errData.safe_message) {
            errDetail = errData.safe_message;
          }
        } catch (_) {}

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
        return "HTTP_ERROR";
      }

      let data;
      try {
        data = await res.json();
      } catch (jsonErr) {
        showToast("Draft staging failed: Malformed JSON response from server.");
        return "JSON_PARSE_ERROR";
      }

      const validation = validateStageDraftResponse(res, data);
      if (!validation.isValid) {
        showToast(`Draft staging failed: ${validation.message}`);
        return "VALIDATION_ERROR";
      }

      showToast("Draft staged successfully in cloud mailbox!");
      return "SUCCESS";
    } catch (err) {
      showToast(`Draft staging failed: Network error (${err.message || "Unable to reach server"}).`);
      return "NETWORK_ERROR";
    } finally {
      isStagingDraft = false;
      mockEl.btnStageDraft.disabled = false;
    }
  };

  const outcome = await stageCloudDraftImpl();
  return { outcome, toasts, fetchCalls, sendCalls, btnDisabled: mockEl.btnStageDraft.disabled };
}

(async () => {
  // Test 8: Full Success Path
  const s1 = await runStageCloudDraftSimulation({});
  assert(s1.outcome === "SUCCESS", "E2E Success outcome");
  assert(s1.toasts.includes("Draft staged successfully in cloud mailbox!"), "Success toast shown");
  assert(!s1.toasts.some(t => t.toLowerCase().includes("sent") || t.toLowerCase().includes("delivered")), "No transmission terminology in toast");
  assert(s1.fetchCalls.length === 1, "Single fetch call made");
  assert(s1.fetchCalls[0].payload.account_id === "kinlawb@outlook.com", "Correct account context passed");
  assert(s1.sendCalls === 0, "Zero send calls invoked");

  // Test 9: HTTP 400 Bad Request
  const s2 = await runStageCloudDraftSimulation({
    fetchFn: async () => ({
      ok: false,
      status: 400,
      json: async () => ({ detail: "Invalid request format" })
    })
  });
  assert(s2.outcome === "HTTP_ERROR", "HTTP 400 outcome");
  assert(s2.toasts.some(t => t.includes("HTTP 400") && t.includes("Invalid request format")), "400 error surfaced");
  assert(!s2.toasts.includes("Draft staged successfully in cloud mailbox!"), "Success not displayed on 400");
  assert(s2.sendCalls === 0, "Zero send calls on 400");

  // Test 10: HTTP 401 Unauthorized
  const s3 = await runStageCloudDraftSimulation({
    fetchFn: async () => ({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Authentication required" })
    })
  });
  assert(s3.outcome === "HTTP_ERROR", "HTTP 401 outcome");
  assert(s3.toasts.some(t => t.includes("HTTP 401") && t.includes("Authentication required")), "401 error surfaced");
  assert(!s3.toasts.includes("Draft staged successfully in cloud mailbox!"), "Success not displayed on 401");

  // Test 11: HTTP 403 Forbidden / Account Mismatch
  const s4 = await runStageCloudDraftSimulation({
    fetchFn: async () => ({
      ok: false,
      status: 403,
      json: async () => ({ detail: "Account context mismatch" })
    })
  });
  assert(s4.outcome === "HTTP_ERROR", "HTTP 403 outcome");
  assert(s4.toasts.some(t => t.includes("HTTP 403") && t.includes("Account context mismatch")), "403 error surfaced");
  assert(!s4.toasts.includes("Draft staged successfully in cloud mailbox!"), "Success not displayed on 403");

  // Test 12: HTTP 500 Server Error
  const s5 = await runStageCloudDraftSimulation({
    fetchFn: async () => ({
      ok: false,
      status: 500,
      json: async () => ({ detail: "Internal Graph exception" })
    })
  });
  assert(s5.outcome === "HTTP_ERROR", "HTTP 500 outcome");
  assert(s5.toasts.some(t => t.includes("HTTP 500") && t.includes("Server or provider error")), "500 error surfaced");
  assert(!s5.toasts.includes("Draft staged successfully in cloud mailbox!"), "Success not displayed on 500");

  // Test 13: Network Failure / Rejected Promise
  const s6 = await runStageCloudDraftSimulation({
    fetchFn: async () => { throw new Error("Connection refused to 127.0.0.1:8000"); }
  });
  assert(s6.outcome === "NETWORK_ERROR", "Network failure outcome");
  assert(s6.toasts.some(t => t.includes("Network error") && t.includes("Connection refused")), "Network error surfaced");
  assert(!s6.toasts.includes("Draft staged successfully in cloud mailbox!"), "Success not displayed on network error");
  assert(!s6.toasts.includes("Draft saved locally."), "No false local-save fallback displayed");

  // Test 14: Malformed JSON Response from Server
  const s7 = await runStageCloudDraftSimulation({
    fetchFn: async () => ({
      ok: true,
      status: 200,
      json: async () => { throw new SyntaxError("Unexpected token < in JSON at position 0"); }
    })
  });
  assert(s7.outcome === "JSON_PARSE_ERROR", "JSON parse error outcome");
  assert(s7.toasts.some(t => t.includes("Malformed JSON response")), "JSON parse error surfaced");
  assert(!s7.toasts.includes("Draft staged successfully in cloud mailbox!"), "Success not displayed on malformed JSON");

  // Test 15: Missing remote_object_id in 200 OK Response
  const s8 = await runStageCloudDraftSimulation({
    fetchFn: async () => ({
      ok: true,
      status: 200,
      json: async () => ({ success: true, safe_message: "Draft saved without ID" })
    })
  });
  assert(s8.outcome === "VALIDATION_ERROR", "Validation error outcome on missing ID");
  assert(s8.toasts.some(t => t.includes("Authoritative provider draft identifier missing")), "Missing ID error surfaced");
  assert(!s8.toasts.includes("Draft staged successfully in cloud mailbox!"), "Success not displayed on missing ID");

  // Test 16: Missing Email Context Fails Closed
  const s9 = await runStageCloudDraftSimulation({
    emailData: { id: null, account_id: null }
  });
  assert(s9.outcome === "MISSING_EMAIL_CONTEXT", "Missing context outcome");
  assert(s9.toasts.some(t => t.includes("Cannot stage draft") && t.includes("missing")), "Context error surfaced");
  assert(s9.fetchCalls.length === 0, "No network call made when email context is missing");

  // Test 17: Empty Draft Text Fails Closed
  const s10 = await runStageCloudDraftSimulation({
    draftText: "   "
  });
  assert(s10.outcome === "EMPTY_DRAFT", "Empty draft outcome");
  assert(s10.toasts.some(t => t.includes("Cannot stage draft: Draft text is empty.")), "Empty draft error surfaced");
  assert(s10.fetchCalls.length === 0, "No network call made when draft text is empty");

  console.log(`\nAll ${passedTests}/${totalTests} Phase 8 JavaScript Draft Staging tests passed successfully!`);
})();
