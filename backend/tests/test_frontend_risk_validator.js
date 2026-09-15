/**
 * Aura Mail AI - Frontend Risk Validator Direct JavaScript Regression Suite (Phase 5.5.5)
 *
 * Directly executes the production JavaScript logic in frontend/risk_validator.js
 * to verify fail-closed enforcement of:
 * - Exact draft-text-hash matching (data.draft_text_hash === snapshot.draftTextHash)
 * - Staleness detection (edits, generation increment, email switch, replacement)
 * - Malformed response schema rejection
 */

// Environment-agnostic loader (Node, JSC, JXA/osascript)
if (typeof console === 'undefined') {
  console = {
    log: function(msg) { print(msg); },
    error: function(msg) { print('ERROR: ' + msg); },
    warn: function(msg) { print('WARN: ' + msg); }
  };
}

let RiskValidator;
if (typeof require !== 'undefined') {
  RiskValidator = require('../../frontend/risk_validator.js');
} else if (typeof load !== 'undefined') {
  load('frontend/risk_validator.js');
  RiskValidator = this.RiskValidator;
} else if (typeof RiskValidator !== 'undefined') {
  RiskValidator = RiskValidator;
} else {
  throw new Error('Unable to resolve RiskValidator in current JS runtime.');
}

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

console.log('=== Running Frontend Risk Validator JavaScript Test Suite ===');

const baseSnapshot = {
  token: 'risk_token_123',
  generation: 1,
  selectedEmailId: 'email_test_1',
  emailId: 'email_test_1',
  draftId: 'draft_test_1',
  draftText: 'Hello recruiter, I am writing to discuss the opportunity.',
  draftTextHash: 'hash_abc_123_authoritative'
};

const baseCurrentState = {
  activeToken: 'risk_token_123',
  generation: 1,
  selectedEmailId: 'email_test_1',
  emailMsg: {
    id: 'email_test_1',
    draft_id: 'draft_test_1',
    draft_text_hash: 'hash_abc_123_authoritative'
  },
  currentText: 'Hello recruiter, I am writing to discuss the opportunity.'
};

const baseValidResponse = {
  status: 'SUCCESS',
  email_id: 'email_test_1',
  draft_id: 'draft_test_1',
  draft_text_hash: 'hash_abc_123_authoritative',
  risk_is_current: true,
  risk: {
    severity: 'SAFE',
    recommended_action: 'PROCEED',
    risk_score: 10
  },
  is_grounded: true,
  grounding_status: 'GROUNDED'
};

// 1. Valid Response Acceptance
const validCheck = RiskValidator.validateRiskResponse(baseValidResponse, baseSnapshot);
const validStale = RiskValidator.isRiskResponseStale(baseSnapshot, baseCurrentState);
assert(validCheck.isValid === true && validCheck.isMalformed === false, 'Accepts valid response matching snapshot');
assert(validStale.isStale === false, 'Accepts response when client state is fresh and unchanged');

// 2. Missing Response Hash Rejected
const missingHashResp = Object.assign({}, baseValidResponse, { draft_text_hash: undefined });
const missingHashCheck = RiskValidator.validateRiskResponse(missingHashResp, baseSnapshot);
assert(missingHashCheck.isValid === false && missingHashCheck.isMalformed === true, 'Rejects response with missing draft_text_hash');

// 3. Empty Response Hash Rejected
const emptyHashResp = Object.assign({}, baseValidResponse, { draft_text_hash: '   ' });
const emptyHashCheck = RiskValidator.validateRiskResponse(emptyHashResp, baseSnapshot);
assert(emptyHashCheck.isValid === false && emptyHashCheck.isMalformed === true, 'Rejects response with empty/whitespace draft_text_hash');

// 4. Non-String Response Hash Rejected
const nonStringHashResp = Object.assign({}, baseValidResponse, { draft_text_hash: 123456 });
const nonStringHashCheck = RiskValidator.validateRiskResponse(nonStringHashResp, baseSnapshot);
assert(nonStringHashCheck.isValid === false && nonStringHashCheck.isMalformed === true, 'Rejects response with non-string draft_text_hash');

// 5. Incorrect Response Hash Rejected
const wrongHashResp = Object.assign({}, baseValidResponse, { draft_text_hash: 'hash_different_forged' });
const wrongHashCheck = RiskValidator.validateRiskResponse(wrongHashResp, baseSnapshot);
assert(wrongHashCheck.isValid === false && wrongHashCheck.isMalformed === true, 'Rejects response with incorrect draft_text_hash');

// 6. Correct Draft ID but Incorrect Hash Rejected
const correctDraftWrongHashResp = Object.assign({}, baseValidResponse, { draft_id: 'draft_test_1', draft_text_hash: 'wrong_hash' });
const correctDraftWrongHashCheck = RiskValidator.validateRiskResponse(correctDraftWrongHashResp, baseSnapshot);
assert(correctDraftWrongHashCheck.isValid === false && correctDraftWrongHashCheck.isMalformed === true, 'Rejects correct draft ID with incorrect draft_text_hash');

// 7. Correct Hash but Incorrect Draft ID Rejected
const correctHashWrongDraftResp = Object.assign({}, baseValidResponse, { draft_id: 'draft_test_2', draft_text_hash: 'hash_abc_123_authoritative' });
const correctHashWrongDraftCheck = RiskValidator.validateRiskResponse(correctHashWrongDraftResp, baseSnapshot);
assert(correctHashWrongDraftCheck.isValid === false && correctHashWrongDraftCheck.isMalformed === true, 'Rejects correct hash with incorrect draft ID');

// 8. Correct Hash and Draft ID for Wrong Email Rejected
const wrongEmailResp = Object.assign({}, baseValidResponse, { email_id: 'email_test_2' });
const wrongEmailCheck = RiskValidator.validateRiskResponse(wrongEmailResp, baseSnapshot);
assert(wrongEmailCheck.isValid === false && wrongEmailCheck.isMalformed === true, 'Rejects response targeting foreign email ID');

// 9. Older Request Generation Rejected
const staleGenState = Object.assign({}, baseCurrentState, { generation: 2 });
const staleGenCheck = RiskValidator.isRiskResponseStale(baseSnapshot, staleGenState);
assert(staleGenCheck.isStale === true, 'Rejects response from older request generation');

// 10. In-flight Response Discarded After Textarea Edit
const editedState = Object.assign({}, baseCurrentState, {
  activeToken: null,
  generation: 2,
  currentText: 'Hello recruiter, I am typing an unauthorized edit.'
});
const editedCheck = RiskValidator.isRiskResponseStale(baseSnapshot, editedState);
assert(editedCheck.isStale === true, 'Discards in-flight response after textarea edit');

// 11. In-flight Response Discarded After Switching Selected Email
const switchedEmailState = Object.assign({}, baseCurrentState, {
  activeToken: null,
  generation: 2,
  selectedEmailId: 'email_test_2'
});
const switchedEmailCheck = RiskValidator.isRiskResponseStale(baseSnapshot, switchedEmailState);
assert(switchedEmailCheck.isStale === true, 'Discards in-flight response after switching selected email');

// 12. In-flight Response Discarded After Draft Regeneration
const regeneratedState = Object.assign({}, baseCurrentState, {
  activeToken: 'risk_token_new_gen',
  generation: 2,
  emailMsg: {
    id: 'email_test_1',
    draft_id: 'draft_regenerated_2',
    draft_text_hash: 'new_hash_456'
  }
});
const regeneratedCheck = RiskValidator.isRiskResponseStale(baseSnapshot, regeneratedState);
assert(regeneratedCheck.isStale === true, 'Discards in-flight response after draft regeneration');

// 13. Malformed Status Rejected
const malformedStatusResp = Object.assign({}, baseValidResponse, { status: 'UNEXPECTED_STATUS_OK' });
const malformedStatusCheck = RiskValidator.validateRiskResponse(malformedStatusResp, baseSnapshot);
assert(malformedStatusCheck.isValid === false && malformedStatusCheck.isMalformed === true, 'Rejects response with unrecognized status');

// 14. Missing Risk Assessment Object in SUCCESS Rejected
const missingRiskObjResp = Object.assign({}, baseValidResponse, { risk: null });
const missingRiskObjCheck = RiskValidator.validateRiskResponse(missingRiskObjResp, baseSnapshot);
assert(missingRiskObjCheck.isValid === false && missingRiskObjCheck.isMalformed === true, 'Rejects SUCCESS response missing risk assessment object');

// 15. Invalid Severity in Risk Object Rejected
const invalidSeverityResp = Object.assign({}, baseValidResponse, { risk: { severity: 'UNCHECKED', recommended_action: 'PROCEED' } });
const invalidSeverityCheck = RiskValidator.validateRiskResponse(invalidSeverityResp, baseSnapshot);
assert(invalidSeverityCheck.isValid === false && invalidSeverityCheck.isMalformed === true, 'Rejects response with unrecognized risk severity');

// 16. Invalid Recommended Action in Risk Object Rejected
const invalidActionResp = Object.assign({}, baseValidResponse, { risk: { severity: 'SAFE', recommended_action: 'ALLOW_SEND' } });
const invalidActionCheck = RiskValidator.validateRiskResponse(invalidActionResp, baseSnapshot);
assert(invalidActionCheck.isValid === false && invalidActionCheck.isMalformed === true, 'Rejects response with unrecognized recommended action');

console.log(`\nAll ${passedTests}/${totalTests} JavaScript Risk Validator tests passed successfully!`);
