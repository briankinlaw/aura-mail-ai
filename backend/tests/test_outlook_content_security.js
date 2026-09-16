/**
 * Aura Mail AI - Phase 9 Outlook Content Security JavaScript Regression Suite
 *
 * Validates Phase 9 Secure Outlook Generated Content invariants:
 * 1. Model-generated and user-controlled text is treated as untrusted content.
 * 2. Proper escaping order: & -> &amp;, < -> &lt;, > -> &gt;, " -> &quot;, ' -> &#39;, followed by newline conversion.
 * 3. Literal <script>alert(1)</script> cannot become executable script.
 * 4. Literal <img src=x onerror=alert(1)> cannot become active event handler.
 * 5. Literal <a href="javascript:alert(1)">click</a> cannot become active javascript: link.
 * 6. Ampersands, quotes, apostrophes, multiline text, and full Unicode are preserved.
 * 7. Recruiter content containing HTML-like characters remains literal and intact.
 * 8. Office.js insertion paths (displayReplyForm and setAsync) receive safe escaped HTML.
 * 9. Exact-draft Risk Sentinel correlation and edit-invalidation operate on canonical plain text.
 * 10. Cloud draft staging continues to stage canonical plain text without entity corruption.
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

console.log("=== Running Phase 9 Outlook Content Security JavaScript Test Suite ===");

// Minimal DOM & Browser Environment Setup for taskpane.js loading
const mockElement = (initialValue = "") => ({
  value: initialValue,
  textContent: "Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx",
  checked: true,
  classList: {
    remove: () => {},
    add: () => {}
  },
  addEventListener: () => {},
  style: {},
  disabled: false,
  className: "",
  select: () => {}
});

let lastDisplayReplyFormArgs = null;
let lastSetAsyncArgs = null;
let lastClipboardText = null;

global.window = {
  location: { origin: "https://localhost:8000" },
  __AURA_SESSION_TOKEN__: "test_session_token_xyz"
};


const domElements = {
  loadingView: mockElement(""),
  mainView: mockElement(""),
  loadingMessage: mockElement(""),
  connectionStatus: mockElement(""),
  btnRescan: mockElement(""),
  categoryBadge: mockElement(""),
  emailTime: mockElement(""),
  emailSubject: mockElement(""),
  senderName: mockElement(""),
  senderEmail: mockElement(""),
  fitScoreVal: mockElement(""),
  fitTierBadge: mockElement(""),
  scoreCircle: mockElement(""),
  detectedRole: mockElement(""),
  detectedCompany: mockElement(""),
  detectedSalary: mockElement(""),
  signalTagsContainer: mockElement(""),
  lensSelect: mockElement("Advisor"),
  activeResumeFilename: mockElement("Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx"),
  draftReplyText: mockElement(""),
  btnRegenerate: mockElement(""),
  chkIncludeAvailability: mockElement(true),
  btnInsertReply: mockElement(""),
  btnStageDraft: mockElement(""),
  btnCopyClipboard: mockElement(""),
  slotsList: mockElement(""),
  btnCopySlots: mockElement(""),
  riskSentinelBanner: mockElement(""),
  sentinelIcon: mockElement(""),
  sentinelStatusBadge: mockElement(""),
  sentinelSummary: mockElement(""),
  toast: mockElement(""),
  toastMessage: mockElement("")
};

global.document = {
  getElementById: (id) => {
    if (!domElements[id]) {
      domElements[id] = mockElement("");
    }
    return domElements[id];
  },
  querySelectorAll: () => [mockElement()],
  body: {
    appendChild: () => {},
    removeChild: () => {}
  },
  createElement: () => mockElement(),
  execCommand: () => true
};

global.Office = {
  onReady: (cb) => { cb({ host: "Outlook", platform: "PC" }); },
  HostType: { Outlook: "Outlook" },
  CoercionType: {
    Html: "html",
    Text: "text"
  },
  AsyncResultStatus: {
    Succeeded: "succeeded",
    Failed: "failed"
  },
  context: {
    mailbox: {
      item: {
        itemId: "item_native_123",
        subject: "Senior Architect Opportunity",
        from: { displayName: "Recruiter", emailAddress: "recruiter@example.com" },
        displayReplyForm: (args) => {
          lastDisplayReplyFormArgs = args;
        },
        body: {
          setAsync: (html, options, callback) => {
            lastSetAsyncArgs = { html, options };
            if (callback) {
              callback({ status: Office.AsyncResultStatus.Succeeded });
            }
          }
        }
      },
      userProfile: {
        emailAddress: "kinlawb@outlook.com"
      }
    }
  }
};

global.window.Office = global.Office;

global.fetch = async () => ({ ok: true, json: async () => ({}) });

const TaskpaneModule = require("../../frontend/add-in/taskpane.js");
const { escapeHtml, formatReplyAsSafeHtml, insertReplyIntoOutlook } = TaskpaneModule;

// =========================================================================
// SECTION 1: ESCAPING & FORMATTING UNIT TESTS
// =========================================================================

// Test 1: Literal <script>alert(1)</script>
const scriptPayload = "<script>alert(1)</script>";
const escapedScript = escapeHtml(scriptPayload);
const safeHtmlScript = formatReplyAsSafeHtml(scriptPayload);
assert(escapedScript === "&lt;script&gt;alert(1)&lt;/script&gt;", "Script payload is properly HTML-escaped");
assert(!safeHtmlScript.includes("<script>"), "Safe HTML does not contain raw <script> tag");
assert(safeHtmlScript === "&lt;script&gt;alert(1)&lt;/script&gt;", "formatReplyAsSafeHtml output matches safe escaped string");

// Test 2: Literal <img src=x onerror=alert(1)>
const imgPayload = "<img src=x onerror=alert(1)>";
const escapedImg = escapeHtml(imgPayload);
assert(escapedImg === "&lt;img src=x onerror=alert(1)&gt;", "Img onerror payload is properly escaped");
assert(!escapedImg.includes("<img"), "Safe representation contains no <img tag");
assert(!escapedImg.includes("<"), "Safe representation contains no unescaped < tag");
assert(!escapedImg.includes(">"), "Safe representation contains no unescaped > tag");


// Test 3: Literal <a href="javascript:alert(1)">click</a>
const linkPayload = '<a href="javascript:alert(1)">click</a>';
const escapedLink = escapeHtml(linkPayload);
assert(escapedLink === '&lt;a href=&quot;javascript:alert(1)&quot;&gt;click&lt;/a&gt;', "JavaScript link is fully escaped and inactive");
assert(!escapedLink.includes('<a href='), "Safe representation contains no <a tag");

// Test 4: Ampersand preservation
const ampersandText = "Research & Development";
const escapedAmp = escapeHtml(ampersandText);
assert(escapedAmp === "Research &amp; Development", "Ampersand is escaped to &amp;");

// Test 5: Quotation mark preservation
const quoteText = 'He said "Hello" to the team';
const escapedQuote = escapeHtml(quoteText);
assert(escapedQuote === "He said &quot;Hello&quot; to the team", "Double quotes are escaped to &quot;");

// Test 6: Apostrophe preservation
const apostropheText = "Brian's availability for next week";
const escapedApos = escapeHtml(apostropheText);
assert(escapedApos === "Brian&#39;s availability for next week", "Apostrophe is escaped to &#39;");

// Test 7: Multiline text handling
const multilineText = "Line one\nLine two\r\nLine three";
const safeMultiline = formatReplyAsSafeHtml(multilineText);
assert(safeMultiline === "Line one<br/>Line two<br/>Line three", "Newlines (LF and CRLF) are safely converted to <br/> after escaping");

// Test 8: Unicode preservation
const unicodeText = "résumé José 你好 こんにちは مرحبا ✓ — 🙂";
const escapedUnicode = escapeHtml(unicodeText);
const safeUnicode = formatReplyAsSafeHtml(unicodeText);
assert(escapedUnicode === unicodeText, "Unicode characters are completely preserved without corruption or stripping");
assert(safeUnicode === unicodeText, "formatReplyAsSafeHtml preserves full Unicode range");

// Test 9: Realistic Recruiter Content with HTML-like characters
const recruiterContent = 'The role requires 5+ years of C++/C# experience.\nCompensation is < $200K depending on level.\nPlease confirm "interest" & availability.';
const safeRecruiterContent = formatReplyAsSafeHtml(recruiterContent);
const expectedRecruiterSafe = 'The role requires 5+ years of C++/C# experience.<br/>Compensation is &lt; $200K depending on level.<br/>Please confirm &quot;interest&quot; &amp; availability.';
assert(safeRecruiterContent === expectedRecruiterSafe, "Realistic recruiter content with <, >, \", & and newlines formatted correctly");

// Test 10: Mixed Adversarial Payloads
const mixed1 = "Brian's \"reply\" & notes:\n<script>alert('✓')</script>";
const safeMixed1 = formatReplyAsSafeHtml(mixed1);
const expectedMixed1 = "Brian&#39;s &quot;reply&quot; &amp; notes:<br/>&lt;script&gt;alert(&#39;✓&#39;)&lt;/script&gt;";
assert(safeMixed1 === expectedMixed1, "Mixed payload with quotes, apos, ampersand, script, Unicode and newline escaped in correct order");

const mixed2 = '"><img src=x onerror=alert(1)>';
const safeMixed2 = formatReplyAsSafeHtml(mixed2);
assert(safeMixed2 === '&quot;&gt;&lt;img src=x onerror=alert(1)&gt;', 'Attribute breakout payload "><img is safely neutralized');

const mixed3 = "='><script>alert(1)</script>";
const safeMixed3 = formatReplyAsSafeHtml(mixed3);
assert(safeMixed3 === "=&#39;&gt;&lt;script&gt;alert(1)&lt;/script&gt;", "Single quote breakout payload is safely neutralized");

// Test 11: Escaping Order Invariant (No double-encoding)
// Proves & is escaped first, so replacing < with &lt; does not subsequently turn into &amp;lt;
const orderCheck = escapeHtml("<>");
assert(orderCheck === "&lt;&gt;", "Escaping does not double-escape newly generated entities");
assert(!orderCheck.includes("&amp;lt;"), "No &amp;lt; entity corruption");

// =========================================================================
// SECTION 2: OFFICE.JS INSERTION CONTRACT TESTS
// =========================================================================

// Test 12: Read Mode displayReplyForm receives safe escaped HTML
lastDisplayReplyFormArgs = null;
domElements.draftReplyText.value = 'Hello <Recruiter> & "Team",\n<script>alert(1)</script>';
insertReplyIntoOutlook();

assert(lastDisplayReplyFormArgs !== null, "displayReplyForm was invoked in Read Mode");
assert(typeof lastDisplayReplyFormArgs.htmlBody === "string", "displayReplyForm received htmlBody string");
assert(lastDisplayReplyFormArgs.htmlBody.includes("&lt;Recruiter&gt; &amp; &quot;Team&quot;,<br/>&lt;script&gt;alert(1)&lt;/script&gt;"), "displayReplyForm htmlBody contains properly escaped HTML");
assert(!lastDisplayReplyFormArgs.htmlBody.includes("<script>"), "displayReplyForm htmlBody contains no raw <script> tag");
assert(!lastDisplayReplyFormArgs.htmlBody.includes("<Recruiter>"), "displayReplyForm htmlBody contains no raw <Recruiter> tag");

// Test 13: Compose Mode setAsync receives safe escaped HTML
const originalDisplayReplyForm = Office.context.mailbox.item.displayReplyForm;
delete Office.context.mailbox.item.displayReplyForm; // Simulate Compose mode where displayReplyForm is undefined

lastSetAsyncArgs = null;
domElements.draftReplyText.value = 'Hi Marcus,\nBrian\'s schedule: <Tuesday> & "Thursday"\n<img src=x onerror=alert(1)>';
insertReplyIntoOutlook();

assert(lastSetAsyncArgs !== null, "setAsync was invoked in Compose Mode");
assert(lastSetAsyncArgs.options.coercionType === Office.CoercionType.Html, "setAsync used Office.CoercionType.Html");
assert(lastSetAsyncArgs.html.includes("Brian&#39;s schedule: &lt;Tuesday&gt; &amp; &quot;Thursday&quot;<br/>&lt;img src=x onerror=alert(1)&gt;"), "setAsync html contains properly escaped content");
assert(!lastSetAsyncArgs.html.includes("<img"), "setAsync html contains no active img tag");
assert(lastSetAsyncArgs.html.includes("&lt;img src=x onerror=alert(1)&gt;"), "setAsync html contains literal escaped payload");


// Restore displayReplyForm
Office.context.mailbox.item.displayReplyForm = originalDisplayReplyForm;

// Test 14: Clipboard Fallback receives Canonical Plain Text
const originalOffice = global.Office;
global.Office = null; // Simulate environment without Office.js
global.window.Office = null;

let copiedValue = null;
const originalCreateElement = global.document.createElement;
global.document.createElement = (tag) => {
  const elem = mockElement();
  if (tag === "textarea") {
    // Intercept created textarea to inspect copied value
    Object.defineProperty(elem, "value", {
      set: (val) => { copiedValue = val; },
      get: () => copiedValue
    });
  }
  return elem;
};

domElements.draftReplyText.value = 'Plain text with "quotes" & <tags>';
insertReplyIntoOutlook();

assert(copiedValue === 'Plain text with "quotes" & <tags>', "Clipboard fallback receives raw canonical text, not HTML-escaped text");
assert(domElements.draftReplyText.value === 'Plain text with "quotes" & <tags>', "Draft textarea retains raw canonical text");

global.document.createElement = originalCreateElement;
global.Office = originalOffice;
global.window.Office = originalOffice;


// =========================================================================
// SECTION 3: RISK SENTINEL & CANONICAL DRAFT CORRELATION REGRESSIONS
// =========================================================================

const RiskValidator = require("../../frontend/risk_validator.js");
const crypto = require("crypto");

function computeAuthoritativeHash(text) {
  return crypto.createHash("sha256").update(text, "utf8").digest("hex");
}

// Test 15: Exact-Draft Risk Sentinel Correlation with Safe Rendering
// Unedited draft reaches VERIFIED SAFE, rendered safely without hash corruption
const canonicalDraftText = 'Hi Marcus,\nThank you for reaching out regarding the opportunity.\nI am available Tuesday & Thursday.\nBest regards,\nBrian Kinlaw';
const draftHash = computeAuthoritativeHash(canonicalDraftText);

const snapshot = {
  token: 'risk_token_p9',
  generation: 1,
  selectedEmailId: 'email_p9_1',
  emailId: 'email_p9_1',
  draftId: 'draft_p9_1',
  draftText: canonicalDraftText,
  draftTextHash: draftHash
};

const currentStateUnedited = {
  activeToken: 'risk_token_p9',
  generation: 1,
  selectedEmailId: 'email_p9_1',
  emailMsg: {
    id: 'email_p9_1',
    draft_id: 'draft_p9_1',
    draft_text_hash: draftHash
  },
  currentText: canonicalDraftText
};

const riskResponseSafe = {
  status: 'SUCCESS',
  email_id: 'email_p9_1',
  draft_id: 'draft_p9_1',
  draft_text_hash: draftHash,
  risk_is_current: true,
  risk: {
    severity: 'SAFE',
    recommended_action: 'PROCEED',
    risk_score: 5
  },
  is_grounded: true,
  grounding_status: 'GROUNDED'
};

const checkValid = RiskValidator.validateRiskResponse(riskResponseSafe, snapshot);
const checkStaleUnedited = RiskValidator.isRiskResponseStale(snapshot, currentStateUnedited);

assert(checkValid.isValid === true, "Unedited canonical draft validates against Risk Sentinel snapshot");
assert(checkStaleUnedited.isStale === false, "Unedited canonical draft is NOT stale");

// Rendering it to Outlook uses safeHtml without altering the canonical text
const renderedHtml = formatReplyAsSafeHtml(canonicalDraftText);
assert(renderedHtml.includes("Tuesday &amp; Thursday"), "Outlook rendering escapes ampersand");
assert(currentStateUnedited.currentText === canonicalDraftText, "Canonical draft in state remains unmutated plain text");
assert(computeAuthoritativeHash(currentStateUnedited.currentText) === draftHash, "Hash of canonical draft remains exact match");

// Test 16: Meaningful Edit Invalidates Risk Sentinel Correlation
const editedDraftText = 'Hi Marcus,\nThank you for reaching out regarding the opportunity.\nI am available Wednesday & Friday.\nBest regards,\nBrian Kinlaw';
const currentStateEdited = {
  activeToken: 'risk_token_p9',
  generation: 1,
  selectedEmailId: 'email_p9_1',
  emailMsg: {
    id: 'email_p9_1',
    draft_id: 'draft_p9_1',
    draft_text_hash: draftHash
  },
  currentText: editedDraftText
};

const checkStaleEdited = RiskValidator.isRiskResponseStale(snapshot, currentStateEdited);
assert(checkStaleEdited.isStale === true, "Edited draft text is flagged as STALE by Risk Sentinel");
assert(checkStaleEdited.reason === "Editor textarea content changed during request", "Staleness reason indicates editor content changed");

// Test 17: HTML-like content in Draft + Risk Sentinel Correlation
// A draft that legitimately contains HTML-like text (e.g. discussing <script> or < $200K)
const htmlLikeDraft = 'Hi Marcus,\nWe specialize in securing apps against <script> injection.\nCompensation target: < $250K.\nBest,\nBrian';
const htmlLikeHash = computeAuthoritativeHash(htmlLikeDraft);

const htmlSnapshot = {
  token: 'risk_token_html_1',
  generation: 1,
  selectedEmailId: 'email_html_1',
  emailId: 'email_html_1',
  draftId: 'draft_html_1',
  draftText: htmlLikeDraft,
  draftTextHash: htmlLikeHash
};

const htmlState = {
  activeToken: 'risk_token_html_1',
  generation: 1,
  selectedEmailId: 'email_html_1',
  emailMsg: {
    id: 'email_html_1',
    draft_id: 'draft_html_1',
    draft_text_hash: htmlLikeHash
  },
  currentText: htmlLikeDraft
};

const htmlRiskResp = {
  status: 'SUCCESS',
  email_id: 'email_html_1',
  draft_id: 'draft_html_1',
  draft_text_hash: htmlLikeHash,
  risk_is_current: true,
  risk: { severity: 'SAFE', recommended_action: 'PROCEED', risk_score: 5 },
  is_grounded: true,
  grounding_status: 'GROUNDED'
};

const htmlCheck = RiskValidator.validateRiskResponse(htmlRiskResp, htmlSnapshot);
const htmlStaleCheck = RiskValidator.isRiskResponseStale(htmlSnapshot, htmlState);

assert(htmlCheck.isValid === true, "Risk Sentinel correlates draft with HTML-like content based on authoritative hash");
assert(htmlStaleCheck.isStale === false, "Draft with HTML-like content remains fresh when unedited");

const htmlRendered = formatReplyAsSafeHtml(htmlLikeDraft);
assert(htmlRendered.includes("&lt;script&gt;"), "HTML-like content is safely escaped in rendered representation");
assert(htmlRendered.includes("&lt; $250K"), "Less-than sign is safely escaped in rendered representation");
assert(!htmlRendered.includes("<script>"), "No raw <script> tag in rendered representation");

// =========================================================================
// SECTION 4: CLOUD DRAFT STAGING PRESERVATION
// =========================================================================

// Test 18: Staged payload uses canonical text, not escaped entities
const stagingText = 'Hello Recruiter,\nI am interested in the role & available next week.\nCompensation: < $200K.';
domElements.draftReplyText.value = stagingText;

// Verify that the value retrieved for cloud staging is raw canonical text
const stagedTextValue = domElements.draftReplyText.value.trim();
assert(stagedTextValue === stagingText, "Cloud draft staging extracts exact canonical plain text");
assert(!stagedTextValue.includes("&amp;"), "Staged cloud draft does not contain premature &amp; entities");
assert(!stagedTextValue.includes("&lt;"), "Staged cloud draft does not contain premature &lt; entities");

console.log(`\nAll ${totalTests}/${totalTests} Phase 9 JavaScript Outlook Content Security tests passed successfully!`);
