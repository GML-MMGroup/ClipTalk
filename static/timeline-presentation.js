(function timelinePresentationModule() {
  "use strict";

  const body = document.body;
  const $ = (selector, root = document) => root.querySelector(selector);

  function currentJobId() {
    const source = $("#mainVideo")?.currentSrc || $("#mainVideo")?.src || "";
    return decodeURIComponent(source.match(/\/api\/jobs\/([^/]+)/)?.[1] || "");
  }

  function resolvedCurrentJobId() {
    if (typeof window.ClipTalkCurrentJobId === "function") {
      return String(window.ClipTalkCurrentJobId() || "");
    }
    return currentJobId();
  }

  const sourceTimelineState = {
    jobId: "",
    status: "idle",
    data: null,
    retryAt: 0,
  };

  const sourceWaveformState = {
    jobId: "",
    status: "idle",
    data: null,
    retryAt: 0,
  };

  function formatShortDuration(value) {
    const total = Math.max(0, Math.floor(Number(value) || 0));
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  function setSourceTimelineStatus(status) {
    const placeholder = $("#ctTimelinePlaceholder");
    if (!placeholder) return;
    placeholder.dataset.ctTimelineAssetState = status;
    body.dataset.ctSourceTimelineAssetState = status;
    const hint = placeholder.querySelector("header span");
    if (hint && status === "loading") hint.textContent = "正在生成时间轴缩略图与镜头索引，完成后会自动显示";
    if (hint && status === "error") hint.textContent = "时间轴缩略图暂不可用，系统正在自动重试";
  }

  function selectSpriteItems(items, targetCount) {
    if (!Array.isArray(items) || !items.length) return [];
    const count = Math.min(targetCount, items.length);
    if (count <= 1) return [items[0]];
    const selected = [];
    for (let index = 0; index < count; index += 1) {
      selected.push(items[Math.round((index * (items.length - 1)) / (count - 1))]);
    }
    return selected;
  }

  function renderSourceTimelineStrip(data) {
    const placeholder = $("#ctTimelinePlaceholder");
    const strip = placeholder?.querySelector("[data-ct-source-strip]");
    if (!placeholder || !strip) return;
    const sprite = data?.sprite || {};
    const items = selectSpriteItems(sprite.items, 14);
    const spriteUrl = data?.spriteUrl || data?.sprite_url || "";
    const columns = Math.max(1, Number(sprite.columns || 1));
    const rows = Math.max(1, Number(sprite.rows || 1));
    if (!spriteUrl || !items.length) {
      setSourceTimelineStatus("empty");
      return;
    }
    strip.replaceChildren();
    items.forEach((item) => {
      const frame = document.createElement("i");
      frame.className = "ct-source-frame";
      frame.style.backgroundImage = `url("${String(spriteUrl).replaceAll("\"", "%22")}")`;
      frame.style.backgroundSize = `${columns * 100}% ${rows * 100}%`;
      frame.style.backgroundPosition = `${columns > 1 ? (Number(item.column || 0) / (columns - 1)) * 100 : 0}% ${rows > 1 ? (Number(item.row || 0) / (rows - 1)) * 100 : 0}%`;
      frame.title = `源片 ${formatShortDuration(item.time)}`;
      strip.appendChild(frame);
    });
    const labels = placeholder.querySelectorAll(".ct-placeholder-ruler span");
    if (labels[0]) labels[0].textContent = "00:00";
    if (labels[1]) labels[1].textContent = formatShortDuration(data?.duration);
    const hint = placeholder.querySelector("header span");
    if (hint) hint.textContent = "源视频已就绪；提交剪辑要求后生成镜头、字幕与封面轨道";
    setSourceTimelineStatus("ready");
  }

  function setSourceWaveformStatus(status) {
    const placeholder = $("#ctTimelinePlaceholder");
    if (placeholder) placeholder.dataset.ctWaveformState = status;
  }

  function renderSourceTimelineWaveform(data) {
    const canvas = $("#ctTimelinePlaceholder [data-ct-source-waveform]");
    if (!canvas) return false;
    const bounds = canvas.getBoundingClientRect();
    const width = Math.max(0, Math.round(bounds.width));
    const height = Math.max(0, Math.round(bounds.height));
    if (width < 2 || height < 2) return false;

    const minimums = Array.isArray(data?.minimums) ? data.minimums : [];
    const maximums = Array.isArray(data?.maximums) ? data.maximums : [];
    const peaks = Array.isArray(data?.peaks) ? data.peaks : [];
    const sampleCount = Math.max(minimums.length, maximums.length, peaks.length);
    if (!data?.hasAudio || !sampleCount) {
      setSourceWaveformStatus("empty");
      return false;
    }

    const ratio = Math.min(2, Math.max(1, window.devicePixelRatio || 1));
    const pixelWidth = Math.round(width * ratio);
    const pixelHeight = Math.round(height * ratio);
    if (canvas.width !== pixelWidth) canvas.width = pixelWidth;
    if (canvas.height !== pixelHeight) canvas.height = pixelHeight;
    const context = canvas.getContext("2d");
    if (!context) return false;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);

    const normalization = Math.max(.04, Number(data?.normalizationPeak) || 1);
    const center = height / 2;
    const amplitude = Math.max(2, center - 3);
    context.strokeStyle = "rgba(171, 214, 151, .88)";
    context.lineWidth = 1;
    context.beginPath();
    for (let x = 0; x < width; x += 1) {
      const start = Math.floor((x / width) * sampleCount);
      const end = Math.max(start + 1, Math.ceil(((x + 1) / width) * sampleCount));
      let low = 0;
      let high = 0;
      for (let index = start; index < Math.min(sampleCount, end); index += 1) {
        const peak = Math.abs(Number(peaks[index] || 0));
        low = Math.min(low, Number(minimums[index] ?? -peak));
        high = Math.max(high, Number(maximums[index] ?? peak));
      }
      const top = center - Math.min(1, Math.abs(high) / normalization) * amplitude;
      const bottom = center + Math.min(1, Math.abs(low) / normalization) * amplitude;
      context.moveTo(x + .5, top);
      context.lineTo(x + .5, bottom);
    }
    context.stroke();
    setSourceWaveformStatus("ready");
    return true;
  }

  function syncSourceTimelineWaveform() {
    const placeholder = $("#ctTimelinePlaceholder");
    if (!placeholder) return;
    const jobId = resolvedCurrentJobId();
    if (!jobId) {
      sourceWaveformState.jobId = "";
      sourceWaveformState.status = "idle";
      sourceWaveformState.data = null;
      setSourceWaveformStatus("idle");
      return;
    }
    if (sourceWaveformState.jobId !== jobId) {
      sourceWaveformState.jobId = jobId;
      sourceWaveformState.status = "idle";
      sourceWaveformState.data = null;
      sourceWaveformState.retryAt = 0;
    }
    if (sourceWaveformState.status === "ready" && sourceWaveformState.data) {
      renderSourceTimelineWaveform(sourceWaveformState.data);
      return;
    }
    if (sourceWaveformState.status === "loading") return;
    if (sourceWaveformState.status === "error" && Date.now() < sourceWaveformState.retryAt) return;
    sourceWaveformState.status = "loading";
    setSourceWaveformStatus("loading");
    fetch(`/api/jobs/${encodeURIComponent(jobId)}/waveform`, { credentials: "same-origin" })
      .then((response) => {
        if (!response.ok) throw new Error(`waveform ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (sourceWaveformState.jobId !== jobId) return;
        sourceWaveformState.data = data;
        sourceWaveformState.status = "ready";
        renderSourceTimelineWaveform(data);
      })
      .catch(() => {
        if (sourceWaveformState.jobId !== jobId) return;
        sourceWaveformState.status = "error";
        sourceWaveformState.retryAt = Date.now() + 5000;
        setSourceWaveformStatus("error");
      });
  }

  let sourceTimelinePlaybackFrame = 0;

  function syncSourceTimelinePlayhead() {
    const video = $("#mainVideo");
    const placeholder = $("#ctTimelinePlaceholder");
    const strip = placeholder?.querySelector(".picture > span");
    const playhead = placeholder?.querySelector(".ct-placeholder-playhead");
    if (!video || !placeholder || !strip || !playhead) return;
    const duration = Number.isFinite(Number(video.duration)) && Number(video.duration) > 0
      ? Number(video.duration)
      : Number(sourceTimelineState.data?.duration || sourceWaveformState.data?.duration || 0);
    const currentTime = Math.max(0, Number(video.currentTime || 0));
    const progress = duration > 0 ? Math.min(1, currentTime / duration) : 0;
    const placeholderBounds = placeholder.getBoundingClientRect();
    const stripBounds = strip.getBoundingClientRect();
    if (stripBounds.width <= 0) return;
    const left = stripBounds.left - placeholderBounds.left + stripBounds.width * progress;
    placeholder.style.setProperty("--ct-source-playhead-left", `${Math.round(left * 1000) / 1000}px`);
    placeholder.dataset.ctPlaybackProgress = String(progress);
  }

  function stopSourceTimelinePlaybackSync() {
    if (!sourceTimelinePlaybackFrame) return;
    cancelAnimationFrame(sourceTimelinePlaybackFrame);
    sourceTimelinePlaybackFrame = 0;
  }

  function sourceTimelinePlaybackTick() {
    sourceTimelinePlaybackFrame = 0;
    syncSourceTimelinePlayhead();
    const video = $("#mainVideo");
    if (video && !video.paused && !video.ended) {
      sourceTimelinePlaybackFrame = requestAnimationFrame(sourceTimelinePlaybackTick);
    }
  }

  function startSourceTimelinePlaybackSync() {
    stopSourceTimelinePlaybackSync();
    sourceTimelinePlaybackTick();
  }

  function bindSourceTimelinePlayer() {
    const video = $("#mainVideo");
    if (!video || video.dataset.ctSourceTimelineBound === "true") return;
    video.dataset.ctSourceTimelineBound = "true";
    ["loadedmetadata", "durationchange", "timeupdate", "seeking", "seeked"].forEach((eventName) => {
      video.addEventListener(eventName, syncSourceTimelinePlayhead);
    });
    video.addEventListener("play", startSourceTimelinePlaybackSync);
    video.addEventListener("pause", () => {
      stopSourceTimelinePlaybackSync();
      syncSourceTimelinePlayhead();
    });
    video.addEventListener("ended", () => {
      stopSourceTimelinePlaybackSync();
      syncSourceTimelinePlayhead();
    });
  }

  function syncSourceTimelineAssets() {
    const placeholder = $("#ctTimelinePlaceholder");
    if (!placeholder) return;
    const jobId = resolvedCurrentJobId();
    if (!jobId) {
      sourceTimelineState.jobId = "";
      sourceTimelineState.status = "idle";
      sourceTimelineState.data = null;
      setSourceTimelineStatus("idle");
      return;
    }
    if (sourceTimelineState.jobId !== jobId) {
      sourceTimelineState.jobId = jobId;
      sourceTimelineState.status = "idle";
      sourceTimelineState.data = null;
      sourceTimelineState.retryAt = 0;
    }
    if (sourceTimelineState.status === "ready" && sourceTimelineState.data) {
      renderSourceTimelineStrip(sourceTimelineState.data);
      return;
    }
    if (sourceTimelineState.status === "loading") return;
    if (sourceTimelineState.status === "error" && Date.now() < sourceTimelineState.retryAt) return;
    sourceTimelineState.status = "loading";
    setSourceTimelineStatus("loading");
    fetch(`/api/jobs/${encodeURIComponent(jobId)}/timeline-assets`, { credentials: "same-origin" })
      .then((response) => {
        if (!response.ok) {
          const error = new Error(`timeline assets ${response.status}`);
          error.retryable = [202, 404, 409, 425, 429, 503].includes(response.status);
          throw error;
        }
        return response.json();
      })
      .then((data) => {
        if (sourceTimelineState.jobId !== jobId) return;
        if (data?.ready === false) {
          const failed = Boolean(data?.generationError);
          const delay = failed ? 5000 : 1200;
          sourceTimelineState.status = failed ? "error" : "loading";
          sourceTimelineState.data = null;
          sourceTimelineState.retryAt = Date.now() + delay;
          setSourceTimelineStatus(failed ? "error" : "loading");
          window.setTimeout(() => {
            if (sourceTimelineState.jobId !== jobId) return;
            sourceTimelineState.status = "idle";
            syncSourceTimelineAssets();
          }, delay + 50);
          return;
        }
        sourceTimelineState.data = data;
        sourceTimelineState.status = "ready";
        renderSourceTimelineStrip(data);
      })
      .catch((error) => {
        if (sourceTimelineState.jobId !== jobId) return;
        const retryable = Boolean(error?.retryable);
        const delay = retryable ? 1200 : 5000;
        sourceTimelineState.status = retryable ? "loading" : "error";
        sourceTimelineState.retryAt = Date.now() + delay;
        setSourceTimelineStatus(retryable ? "loading" : "error");
        window.setTimeout(() => {
          if (sourceTimelineState.jobId !== jobId) return;
          sourceTimelineState.status = "idle";
          syncSourceTimelineAssets();
        }, delay + 50);
      });
  }

  function sync() {
    if (!$("#ctTimelinePlaceholder")) return;
    syncSourceTimelineAssets();
    syncSourceTimelineWaveform();
    bindSourceTimelinePlayer();
    syncSourceTimelinePlayhead();
  }

  window.addEventListener("resize", sync, { passive: true });
  window.ClipTalkTimelinePresentation = Object.freeze({ sync });
  sync();
})();
