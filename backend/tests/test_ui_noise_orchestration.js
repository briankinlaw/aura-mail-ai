/**
 * UI & DOM Validation Test Suite for Noise Orchestration & Zero-Noise Inbox Architecture.
 * Includes both DOM element validations and runtime JavaScript execution tests for response-status handling.
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

async function runNoiseOrchestrationUiTests() {
    console.log("=== Running Aura Mail AI Noise Orchestration UI Validation Suite ===");

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

    // 3. Extract and Execute JavaScript response-status handling
    console.log("=== Executing Runtime JS Response-Status Handling Tests ===");

    // Find the orchestrateAllInboxesNoise function definition in app.js
    const funcMatch = js.match(/window\.orchestrateAllInboxesNoise\s*=\s*async\s*function\s*\(\)\s*\{([\s\S]*?)\n\};/);
    assert(funcMatch, "Could not extract window.orchestrateAllInboxesNoise from app.js");
    const funcBody = funcMatch[1];

    async function executeWithMockResponse(mockFetch) {
        const toasts = [];
        let refreshCalled = false;

        const sandbox = {
            window: {},
            showToast: (msg, type) => {
                toasts.push({ msg, type });
            },
            refreshAll: async () => {
                refreshCalled = true;
            },
            fetch: mockFetch,
            JSON: JSON,
            encodeURIComponent: encodeURIComponent,
            console: console
        };

        const script = new vm.Script(`
            window.orchestrateAllInboxesNoise = async function() {
                ${funcBody}
            };
        `);
        const context = vm.createContext(sandbox);
        script.runInContext(context);

        await sandbox.window.orchestrateAllInboxesNoise();
        return { toasts, refreshCalled };
    }

    // Test 1: SUCCESS response -> must show success toast (and ONLY success toast for completion)
    {
        const mockFetch = async () => ({
            ok: true,
            json: async () => ({
                status: 'SUCCESS',
                accounts_synced: 2,
                total_noise_quarantined: 5,
                safe_folder_name: 'AI Cleaned - Noise'
            })
        });
        const { toasts, refreshCalled } = await executeWithMockResponse(mockFetch);
        assert(refreshCalled, "refreshAll must be called after orchestration");
        const finalToast = toasts[toasts.length - 1];
        assert.strictEqual(finalToast.type, 'success', "SUCCESS status must trigger 'success' toast");
        assert(finalToast.msg.includes('Zero-Noise Orchestration Complete'), "SUCCESS toast must announce completion");
        console.log("PASS: Runtime SUCCESS response status handled correctly");
    }

    // Test 2: SYNC_SKIPPED response -> must show info toast and unverified message
    {
        const mockFetch = async () => ({
            ok: true,
            json: async () => ({
                status: 'SYNC_SKIPPED',
                total_noise_quarantined: 3
            })
        });
        const { toasts } = await executeWithMockResponse(mockFetch);
        const finalToast = toasts[toasts.length - 1];
        assert.strictEqual(finalToast.type, 'info', "SYNC_SKIPPED must trigger 'info' toast");
        assert(finalToast.msg.includes('unverified'), "SYNC_SKIPPED toast must indicate unverified live status");
        console.log("PASS: Runtime SYNC_SKIPPED response status handled correctly");
    }

    // Test 3: UNVERIFIED response -> must show info toast and unverified message
    {
        const mockFetch = async () => ({
            ok: true,
            json: async () => ({
                status: 'UNVERIFIED',
                total_noise_quarantined: 0
            })
        });
        const { toasts } = await executeWithMockResponse(mockFetch);
        const finalToast = toasts[toasts.length - 1];
        assert.strictEqual(finalToast.type, 'info', "UNVERIFIED must trigger 'info' toast");
        assert(finalToast.msg.includes('unverified'), "UNVERIFIED toast must indicate unverified status");
        console.log("PASS: Runtime UNVERIFIED response status handled correctly");
    }

    // Test 4: SYNC_FAILED response -> must show error toast
    {
        const mockFetch = async () => ({
            ok: true,
            json: async () => ({
                status: 'SYNC_FAILED',
                sync_errors: [{ account_id: 'kinlawb@outlook.com', error: 'Token expired' }],
                cached_messages_triaged: 10
            })
        });
        const { toasts } = await executeWithMockResponse(mockFetch);
        const finalToast = toasts[toasts.length - 1];
        assert.strictEqual(finalToast.type, 'error', "SYNC_FAILED must trigger 'error' toast");
        assert(finalToast.msg.includes('Live sync failed for all mailboxes'), "SYNC_FAILED toast message must be accurate");
        console.log("PASS: Runtime SYNC_FAILED response status handled correctly");
    }

    // Test 5: QUARANTINE_FAILED response -> must show error toast
    {
        const mockFetch = async () => ({
            ok: true,
            json: async () => ({
                status: 'QUARANTINE_FAILED',
                failed_quarantine_count: 4,
                safe_folder_name: 'AI Cleaned - Noise'
            })
        });
        const { toasts } = await executeWithMockResponse(mockFetch);
        const finalToast = toasts[toasts.length - 1];
        assert.strictEqual(finalToast.type, 'error', "QUARANTINE_FAILED must trigger 'error' toast");
        assert(finalToast.msg.includes('Quarantine failed'), "QUARANTINE_FAILED toast message must be accurate");
        console.log("PASS: Runtime QUARANTINE_FAILED response status handled correctly");
    }

    // Test 6: PARTIAL_SUCCESS response (sync failure) -> must show warning toast
    {
        const mockFetch = async () => ({
            ok: true,
            json: async () => ({
                status: 'PARTIAL_SUCCESS',
                accounts_failed: 1,
                sync_errors: [{ account_id: 'brian@mavencode.com' }],
                total_noise_quarantined: 2,
                failed_quarantine_count: 0
            })
        });
        const { toasts } = await executeWithMockResponse(mockFetch);
        const finalToast = toasts[toasts.length - 1];
        assert.strictEqual(finalToast.type, 'warning', "PARTIAL_SUCCESS must trigger 'warning' toast");
        assert(finalToast.msg.includes('sync failed for brian@mavencode.com'), "PARTIAL_SUCCESS toast must detail sync failures");
        console.log("PASS: Runtime PARTIAL_SUCCESS (sync failure) handled correctly");
    }

    // Test 7: PARTIAL_SUCCESS response (quarantine failure) -> must show warning toast
    {
        const mockFetch = async () => ({
            ok: true,
            json: async () => ({
                status: 'PARTIAL_SUCCESS',
                accounts_failed: 0,
                total_noise_quarantined: 3,
                failed_quarantine_count: 1
            })
        });
        const { toasts } = await executeWithMockResponse(mockFetch);
        const finalToast = toasts[toasts.length - 1];
        assert.strictEqual(finalToast.type, 'warning', "PARTIAL_SUCCESS must trigger 'warning' toast");
        assert(finalToast.msg.includes('1 quarantine moves failed'), "PARTIAL_SUCCESS toast must detail quarantine failures");
        console.log("PASS: Runtime PARTIAL_SUCCESS (quarantine failure) handled correctly");
    }

    // Test 8: HTTP Error response -> must show error toast
    {
        const mockFetch = async () => ({
            ok: false,
            json: async () => ({
                detail: 'Server internal error'
            })
        });
        const { toasts } = await executeWithMockResponse(mockFetch);
        const finalToast = toasts[toasts.length - 1];
        assert.strictEqual(finalToast.type, 'error', "HTTP non-ok response must trigger 'error' toast");
        assert(finalToast.msg.includes('Server internal error'), "HTTP error toast must display error detail");
        console.log("PASS: Runtime HTTP error response handled correctly");
    }

    // Test 9: Network / fetch exception -> must catch and show error toast
    {
        const mockFetch = async () => {
            throw new Error('Connection refused');
        };
        const { toasts } = await executeWithMockResponse(mockFetch);
        const finalToast = toasts[toasts.length - 1];
        assert.strictEqual(finalToast.type, 'error', "Fetch exception must trigger 'error' toast");
        assert(finalToast.msg.includes('Connection refused'), "Exception toast must display exception message");
        console.log("PASS: Runtime network exception handled correctly");
    }

    console.log("\nAll Noise Orchestration UI DOM and Runtime Response Execution tests passed successfully!\n");
}

runNoiseOrchestrationUiTests().catch((e) => {
    console.error("FAIL: Noise Orchestration UI Validation Failed!", e.message);
    process.exit(1);
});
