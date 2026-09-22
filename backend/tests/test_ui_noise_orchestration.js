/**
 * UI & DOM Validation Test Suite for Noise Orchestration & Zero-Noise Inbox Architecture.
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

function runNoiseOrchestrationUiTests() {
    console.log("=== Running Aura Mail AI Noise Orchestration UI DOM Validation Suite ===");

    const htmlPath = path.resolve(__dirname, '../../frontend/index.html');
    const cssPath = path.resolve(__dirname, '../../frontend/style.css');
    const jsPath = path.resolve(__dirname, '../../frontend/app.js');

    const html = fs.readFileSync(htmlPath, 'utf8');
    const css = fs.readFileSync(cssPath, 'utf8');
    const js = fs.readFileSync(jsPath, 'utf8');

    // 1. HTML Element Verifications
    assert(html.includes('id="btn-orchestrate-all-noise"'), 'Missing #btn-orchestrate-all-noise button in index.html');
    assert(html.includes('id="noise-accounts-grid"'), 'Missing #noise-accounts-grid in index.html');
    assert(html.includes('id="triage-account-filter-group"'), 'Missing #triage-account-filter-group in index.html');
    assert(html.includes('id="setting-auto-quarantine-noise"'), 'Missing #setting-auto-quarantine-noise in index.html');
    assert(html.includes('Orchestrate & Clean All Inboxes'), 'Missing hero button text in index.html');
    console.log("PASS: All required Noise Orchestration HTML elements verified");

    // 2. CSS Style Verifications
    assert(css.includes('.noise-accounts-grid'), 'Missing .noise-accounts-grid in style.css');
    assert(css.includes('.noise-acc-card'), 'Missing .noise-acc-card in style.css');
    assert(css.includes('.noise-clean-badge'), 'Missing .noise-clean-badge in style.css');
    assert(css.includes('.noise-acc-stats-row'), 'Missing .noise-acc-stats-row in style.css');
    assert(css.includes('.noise-acc-clean-action'), 'Missing .noise-acc-clean-action in style.css');
    console.log("PASS: All required Noise Orchestration CSS styles verified");

    // 3. JS Handler Verifications
    assert(js.includes('orchestrateAllInboxesNoise'), 'Missing orchestrateAllInboxesNoise in app.js');
    assert(js.includes('cleanNoiseForAccount'), 'Missing cleanNoiseForAccount in app.js');
    assert(js.includes('quarantineSingleEmail'), 'Missing quarantineSingleEmail in app.js');
    assert(js.includes('renderNoiseAccountCards'), 'Missing renderNoiseAccountCards in app.js');
    assert(js.includes('renderTriageAccountFilterButtons'), 'Missing renderTriageAccountFilterButtons in app.js');
    assert(js.includes('auto_quarantine_noise'), 'Missing auto_quarantine_noise binding in app.js');
    console.log("PASS: All required Noise Orchestration JS functions verified");

    console.log("All Noise Orchestration UI DOM validations passed successfully!\n");
}

try {
    runNoiseOrchestrationUiTests();
} catch (e) {
    console.error("FAIL: Noise Orchestration UI DOM Validation Failed!", e.message);
    process.exit(1);
}
