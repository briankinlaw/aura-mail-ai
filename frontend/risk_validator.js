/**
 * Aura Mail AI - Frontend Risk Response Validator (Phase 5.5.5)
 *
 * Deterministic client-side validation logic for asynchronous Gemini Risk Sentinel responses.
 * Implements strict fail-closed verification of:
 * - Request token and generation matching
 * - Selected email and draft identity matching
 * - Live editor textarea content matching
 * - Cryptographic draft-text-hash exact equality (data.draft_text_hash === snapshot.draftTextHash)
 * - Schema integrity and recognized status / severity / action values
 */

(function (root, factory) {
  if (typeof module === 'object' && typeof module.exports === 'object') {
    // CommonJS / Node / JSC environment
    module.exports = factory();
  } else {
    // Browser / global environment
    root.RiskValidator = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const RECOGNIZED_STATUSES = [
    'SUCCESS',
    'VALIDATION_FAILED',
    'DIVERGENCE_DETECTED',
    'INVALIDATION_PERSISTENCE_FAILURE',
    'STALE_EVALUATION',
    'QUARANTINED'
  ];
  const RECOGNIZED_SEVERITIES = ['SAFE', 'CAUTION', 'HIGH_RISK'];
  const RECOGNIZED_ACTIONS = ['PROCEED', 'REVIEW_CAUTION', 'BLOCKED'];

  /**
   * Evaluates whether an incoming risk response is stale based on user interactions
   * (editing textarea, switching emails, regenerating drafts, or launching newer requests).
   *
   * @param {Object} snapshot - Captured snapshot at request launch time.
   * @param {string} snapshot.token - Unique request token.
   * @param {number} snapshot.generation - Request generation counter.
   * @param {string} snapshot.selectedEmailId - Selected email ID at launch.
   * @param {string} snapshot.emailId - Target email ID.
   * @param {string|null} snapshot.draftId - Target draft ID.
   * @param {string} snapshot.draftText - Editor text at launch.
   * @param {string|null} snapshot.draftTextHash - Authoritative text hash at launch.
   *
   * @param {Object} currentState - Live client state at response arrival time.
   * @param {string|null} currentState.activeToken - Current active risk token.
   * @param {number} currentState.generation - Current risk generation counter.
   * @param {string} currentState.selectedEmailId - Currently selected email ID in UI.
   * @param {Object|null} currentState.emailMsg - Current active email object.
   * @param {string} currentState.currentText - Current editor textarea text.
   *
   * @returns {{ isStale: boolean, reason: string|null }}
   */
  function isRiskResponseStale(snapshot, currentState) {
    if (!snapshot || !currentState) {
      return { isStale: true, reason: 'Missing snapshot or current state' };
    }

    if (currentState.activeToken !== snapshot.token) {
      return { isStale: true, reason: 'Request token mismatch or invalidated by edit/regeneration/email switch' };
    }

    if (currentState.generation !== snapshot.generation) {
      return { isStale: true, reason: 'Request generation counter is stale' };
    }

    if (currentState.selectedEmailId !== snapshot.selectedEmailId) {
      return { isStale: true, reason: 'Selected email in UI changed during request' };
    }

    if (!currentState.emailMsg || currentState.emailMsg.id !== snapshot.emailId) {
      return { isStale: true, reason: 'Email object missing or changed' };
    }

    if (currentState.emailMsg.draft_id !== snapshot.draftId) {
      return { isStale: true, reason: 'Email draft_id was modified or replaced during request' };
    }

    if (currentState.currentText !== snapshot.draftText) {
      return { isStale: true, reason: 'Editor textarea content changed during request' };
    }

    return { isStale: false, reason: null };
  }

  /**
   * Validates structure, payload integrity, and cryptographic draft-text-hash matching
   * of a risk check response.
   *
   * @param {Object} data - Server response payload.
   * @param {Object} snapshot - Captured snapshot at request launch time.
   *
   * @returns {{ isValid: boolean, isMalformed: boolean, reason: string|null }}
   */
  function validateRiskResponse(data, snapshot) {
    if (!data || typeof data !== 'object') {
      return { isValid: false, isMalformed: true, reason: 'Response data is not a valid object' };
    }

    if (!snapshot || typeof snapshot !== 'object') {
      return { isValid: false, isMalformed: true, reason: 'Request snapshot is missing or invalid' };
    }

    if (!RECOGNIZED_STATUSES.includes(data.status)) {
      return { isValid: false, isMalformed: true, reason: `Unrecognized response status: ${data.status}` };
    }

    if (!data.email_id || data.email_id !== snapshot.emailId) {
      return { isValid: false, isMalformed: true, reason: `Response email_id mismatch: expected '${snapshot.emailId}', got '${data.email_id}'` };
    }

    // Exact response draft-text-hash equality requirement (Phase 5.5.5)
    if (data.status === 'SUCCESS') {
      if (!snapshot.draftTextHash || typeof snapshot.draftTextHash !== 'string' || !snapshot.draftTextHash.trim()) {
        return { isValid: false, isMalformed: true, reason: 'Snapshot lacks authoritative draftTextHash for SUCCESS response' };
      }

      if (!data.draft_text_hash || typeof data.draft_text_hash !== 'string' || !data.draft_text_hash.trim()) {
        return { isValid: false, isMalformed: true, reason: 'Response lacks required draft_text_hash string' };
      }

      if (data.draft_text_hash !== snapshot.draftTextHash) {
        return { isValid: false, isMalformed: true, reason: `Response draft_text_hash mismatch: expected '${snapshot.draftTextHash}', got '${data.draft_text_hash}'` };
      }

      if (!data.draft_id || typeof data.draft_id !== 'string' || data.draft_id !== snapshot.draftId) {
        return { isValid: false, isMalformed: true, reason: `Response draft_id mismatch: expected '${snapshot.draftId}', got '${data.draft_id}'` };
      }

      if (data.risk_is_current !== true) {
        return { isValid: false, isMalformed: true, reason: 'SUCCESS response must have risk_is_current === true' };
      }

      if (!data.risk || typeof data.risk !== 'object') {
        return { isValid: false, isMalformed: true, reason: 'Missing risk assessment object in SUCCESS response' };
      }

      if (typeof data.risk.severity !== 'string' || !RECOGNIZED_SEVERITIES.includes(data.risk.severity.toUpperCase())) {
        return { isValid: false, isMalformed: true, reason: `Invalid risk severity: ${data.risk.severity}` };
      }

      if (typeof data.risk.recommended_action !== 'string' || !RECOGNIZED_ACTIONS.includes(data.risk.recommended_action.toUpperCase())) {
        return { isValid: false, isMalformed: true, reason: `Invalid recommended action: ${data.risk.recommended_action}` };
      }
    }

    return { isValid: true, isMalformed: false, reason: null };
  }

  return {
    isRiskResponseStale: isRiskResponseStale,
    validateRiskResponse: validateRiskResponse,
    RECOGNIZED_STATUSES: RECOGNIZED_STATUSES,
    RECOGNIZED_SEVERITIES: RECOGNIZED_SEVERITIES,
    RECOGNIZED_ACTIONS: RECOGNIZED_ACTIONS
  };
});
