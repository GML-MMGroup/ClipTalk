/* Output-scoped export snapshots. No DOM or global subtitle controls. */
(() => {
  function capture(job, version, output) {
    if (!job?.id || !version?.id || !output?.filename) throw new Error("请选择要导出的具体文件");
    return Object.freeze({
      jobId: String(job.id), versionId: String(version.id), outputFilename: String(output.filename),
      outputRevision: output.outputRevision || null,
      subtitleMode: output.subtitleMode === "burn" ? "burn" : "none",
      subtitleStyle: output.subtitleStyle || "clean",
      segments: JSON.parse(JSON.stringify(output.segments || [])),
    });
  }

  function isCurrent(snapshot, job) {
    if (!snapshot || String(job?.id) !== snapshot.jobId) return false;
    const version = job.outputVersions?.find((item) => String(item.id) === snapshot.versionId);
    const output = version?.outputs?.find((item) => item.filename === snapshot.outputFilename);
    return Boolean(output && (output.outputRevision || null) === snapshot.outputRevision);
  }

  function withOptions(snapshot, options) {
    return Object.freeze({ ...snapshot, subtitleMode: options.subtitleMode === "burn" ? "burn" : "none",
      subtitleStyle: ["clean", "bold", "social"].includes(options.subtitleStyle) ? options.subtitleStyle : "clean" });
  }

  function mountOptions(host, snapshot) {
    const fieldset = document.createElement("fieldset");
    fieldset.className = "output-specs";
    const legend = document.createElement("legend");
    legend.textContent = "仅用于本次导出的字幕设置";
    fieldset.append(legend);
    const selects = {};
    for (const [name, title, choices] of [
      ["subtitleMode", "字幕", [["none", "不添加字幕"], ["burn", "添加并校对字幕"]]],
      ["subtitleStyle", "样式", [["clean", "简洁 · 白字描边"], ["bold", "醒目 · 加粗亮色"], ["social", "短视频 · 大字底框"]]],
    ]) {
      const label = document.createElement("label");
      label.textContent = title;
      const select = document.createElement("select");
      select.setAttribute("aria-label", `本次导出${title}`);
      for (const [value, text] of choices) select.add(new Option(text, value));
      select.value = snapshot[name];
      label.append(select); fieldset.append(label); selects[name] = select;
    }
    const sync = () => { selects.subtitleStyle.disabled = selects.subtitleMode.value !== "burn"; };
    selects.subtitleMode.addEventListener("change", sync); sync();
    host.after(fieldset);
    return { read: () => withOptions(snapshot, { subtitleMode: selects.subtitleMode.value, subtitleStyle: selects.subtitleStyle.value }),
      remove: () => fieldset.remove() };
  }

  function requestBody(snapshot, subtitleDraftId, acknowledgeQualityRisk, draft = null) {
    return {
      specVersion: 1,
      ...(draft ? { subtitleDraftRevision: draft.revision, subtitleDraftHash: draft.contentHash } : {}),
      outputFilename: snapshot.outputFilename, outputRevision: snapshot.outputRevision,
      subtitleMode: snapshot.subtitleMode, subtitleStyle: snapshot.subtitleStyle,
      subtitleDraftId, acknowledgeQualityRisk,
    };
  }
  window.ClipTalkDelivery = Object.freeze({ capture, isCurrent, requestBody, withOptions, mountOptions });
})();
