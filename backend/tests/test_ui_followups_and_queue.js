const fs = require('fs');
const path = require('path');
const assert = require('assert');

console.log("=== Running Aura Mail AI Follow-up & Queue UI DOM Validation Suite ===");

const htmlPath = path.join(__dirname, '../../frontend/index.html');
const cssPath = path.join(__dirname, '../../frontend/style.css');
const jsPath = path.join(__dirname, '../../frontend/app.js');

const html = fs.readFileSync(htmlPath, 'utf8');
const css = fs.readFileSync(cssPath, 'utf8');
const js = fs.readFileSync(jsPath, 'utf8');

// 1. Verify HTML Elements
assert(html.includes('id="tab-badge-followups"'), "Missing tab-badge-followups in index.html");
assert(html.includes('data-tab="followups-hub"'), "Missing data-tab=followups-hub in index.html");
assert(html.includes('id="pane-followups-hub"'), "Missing pane-followups-hub in index.html");
assert(html.includes('id="filter-btn-pending"'), "Missing filter-btn-pending in index.html");
assert(html.includes('id="filter-btn-staged"'), "Missing filter-btn-staged in index.html");
assert(html.includes('id="filter-btn-replied"'), "Missing filter-btn-replied in index.html");
assert(html.includes('id="filter-btn-all"'), "Missing filter-btn-all in index.html");
assert(html.includes('id="inbound-account-pill"'), "Missing inbound-account-pill in index.html");
assert(html.includes('id="btn-mark-replied"'), "Missing btn-mark-replied in index.html");
assert(html.includes('id="followup-modal"'), "Missing followup-modal in index.html");
console.log("PASS: All required HTML UI elements verified in index.html");

// 2. Verify CSS Classes
assert(css.includes('.account-chip.google'), "Missing .account-chip.google in style.css");
assert(css.includes('.account-chip.outlook'), "Missing .account-chip.outlook in style.css");
assert(css.includes('.account-chip.imap'), "Missing .account-chip.imap in style.css");
assert(css.includes('.queue-filter-btn'), "Missing .queue-filter-btn in style.css");
assert(css.includes('.followup-card'), "Missing .followup-card in style.css");
assert(css.includes('.status-chip.drafted'), "Missing .status-chip.drafted in style.css");
assert(css.includes('.status-chip.replied'), "Missing .status-chip.replied in style.css");
console.log("PASS: All required CSS classes and account styles verified in style.css");

// 3. Verify JS Logic
assert(js.includes('getAccountInfoForEmail'), "Missing getAccountInfoForEmail in app.js");
assert(js.includes('fetchFollowups'), "Missing fetchFollowups in app.js");
assert(js.includes('renderFollowups'), "Missing renderFollowups in app.js");
assert(js.includes('completeFollowupTask'), "Missing completeFollowupTask in app.js");
assert(js.includes('reopenFollowupTask'), "Missing reopenFollowupTask in app.js");
assert(js.includes('deleteFollowupTask'), "Missing deleteFollowupTask in app.js");
assert(js.includes('btnMarkReplied'), "Missing btnMarkReplied handler in app.js");
assert(js.includes('queueFilter'), "Missing queueFilter logic in app.js");
console.log("PASS: All required JS functions and state handlers verified in app.js");

console.log("All Follow-up & Queue UI DOM validations passed successfully!");
