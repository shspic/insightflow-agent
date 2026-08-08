import { apiRequest, downloadResource } from "./client.js";

const workspaceReviewBase = (workspaceId) => `/workspaces/${workspaceId}`;

export const createReviewBrief = (workspaceId, payload) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-briefs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const fetchCurrentReviewBrief = (workspaceId) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-briefs/current`);

export const fetchReviewBrief = (workspaceId, briefId) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-briefs/${briefId}`);

export const confirmReviewBrief = (workspaceId, briefId) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-briefs/${briefId}/confirm`, {
    method: "POST",
  });

export const createReviewRun = (workspaceId, payload) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-runs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const fetchReviewRuns = (workspaceId) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-runs`);

export const fetchReviewRun = (workspaceId, runId) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-runs/${runId}`);

export const executeReviewRun = (workspaceId, runId) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-runs/${runId}/execute`, {
    method: "POST",
  });

export const fetchReviewEvidences = (workspaceId, runId) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-runs/${runId}/evidences`);

export const fetchReviewFindings = (workspaceId, runId) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-runs/${runId}/findings`);

export const createReviewFindingAction = (workspaceId, findingId, payload) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-findings/${findingId}/actions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const fetchReviewFindingActions = (workspaceId, findingId) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-findings/${findingId}/actions`);

// ── ReviewReport ─────────────────────────────────────────────────────

export const generateReviewReport = (workspaceId, runId) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-runs/${runId}/reports`, {
    method: "POST",
  });

export const fetchReviewReports = (workspaceId, runId) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-runs/${runId}/reports`);

export const fetchReviewReport = (workspaceId, runId, reportId) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-runs/${runId}/reports/${reportId}`);

export const fetchReviewReportAssets = (workspaceId, runId, reportId) =>
  apiRequest(`${workspaceReviewBase(workspaceId)}/review-runs/${runId}/reports/${reportId}/assets`);

export const downloadReviewReportAsset = (workspaceId, runId, reportId, assetId, fallbackName = "review-report") =>
  downloadResource(`/api/v2/workspaces/${workspaceId}/review-runs/${runId}/reports/${reportId}/assets/${assetId}/download`, fallbackName);

// ── Verification Agent 智能核验（阶段 4C-3）────────────────────────────

const verificationBase = (workspaceId, runId, verificationRunId) =>
  `${workspaceReviewBase(workspaceId)}/review-runs/${runId}/verification-runs${verificationRunId ? `/${verificationRunId}` : ""}`;

export const createVerificationRun = (workspaceId, runId, payload) =>
  apiRequest(`${verificationBase(workspaceId, runId)}`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const fetchVerificationRuns = (workspaceId, runId) =>
  apiRequest(`${verificationBase(workspaceId, runId)}`);

export const fetchVerificationRun = (workspaceId, runId, verificationRunId) =>
  apiRequest(`${verificationBase(workspaceId, runId, verificationRunId)}`);

export const fetchVerificationToolCalls = (workspaceId, runId, verificationRunId) =>
  apiRequest(`${verificationBase(workspaceId, runId, verificationRunId)}/tool-calls`);

export const fetchVerificationCandidates = (workspaceId, runId, verificationRunId) =>
  apiRequest(`${verificationBase(workspaceId, runId, verificationRunId)}/candidates`);

export const createVerificationCandidateDecision = (workspaceId, runId, verificationRunId, payload) =>
  apiRequest(`${verificationBase(workspaceId, runId, verificationRunId)}/candidate-decisions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const fetchVerificationCandidateDecisions = (workspaceId, runId, verificationRunId) =>
  apiRequest(`${verificationBase(workspaceId, runId, verificationRunId)}/candidate-decisions`);
