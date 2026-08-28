(function createClipTalkReviewActions(global) {
  async function persistExclusions({ jobId, indices }) {
    if (!jobId) throw new Error("缺少待保存的任务 ID");
    return global.ClipTalkApi.requestJson(`/api/jobs/${encodeURIComponent(jobId)}/review-exclusions`, {
      method: "POST",
      body: { indices: [...new Set((indices || []).map(Number).filter(Number.isFinite))] },
    });
  }

  global.ClipTalkReviewActions = Object.freeze({ persistExclusions });
})(window);
