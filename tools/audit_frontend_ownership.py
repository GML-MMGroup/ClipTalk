from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = STATIC / "index.html"

RETIRED_ASSETS = {
    "cliptalk-redesign-v1.css",
    "cliptalk-redesign-v1.js",
    "cliptalk-reference-v2.css",
    "cliptalk-reference-v3.css",
    "cliptalk-reference-v3.js",
    "sidebar-redesign.css",
    "workspace-glass.css",
}


def production_assets(html: str, suffix: str) -> list[str]:
    pattern = rf"/static/([^\"'?]+\.{re.escape(suffix)})(?:\?[^\"]*)?"
    return re.findall(pattern, html)


def check(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    html = INDEX.read_text(encoding="utf-8")
    styles = production_assets(html, "css")
    scripts = production_assets(html, "js")
    failures: list[str] = []

    check(len(styles) == len(set(styles)), "生产页面存在重复 CSS 引用", failures)
    check(len(scripts) == len(set(scripts)), "生产页面存在重复 JavaScript 引用", failures)
    check(len(styles) <= 12, f"生产 CSS 数量回升到 {len(styles)}，上限为 12", failures)
    check(not (RETIRED_ASSETS & set(styles + scripts)), "生产页面重新加载了已退役资源", failures)

    for asset in styles + scripts:
        check((STATIC / asset).is_file(), f"生产资源不存在：static/{asset}", failures)
    for asset in RETIRED_ASSETS:
        check(not (STATIC / asset).exists(), f"已退役资源重新出现：static/{asset}", failures)

    workbench_owner = STATIC / "workbench.css"
    for path in STATIC.glob("*.css"):
        if path == workbench_owner:
            continue
        source = path.read_text(encoding="utf-8")
        check(
            not re.search(r"ct-workbench-v4|ct-v4-|ctV4", source),
            f"工作台专属选择器泄漏到 {path.name}",
            failures,
        )
        check(not re.search(r"color-scheme\s*:\s*light\b", source), f"旧浅色原生控件主题重新出现在 {path.name}", failures)
        check("ct-faithful-v3" not in source, f"退役的 v3 状态选择器重新出现在 {path.name}", failures)
        check("data-ct-ui" not in source, f"退役的 reference-v2 状态选择器重新出现在 {path.name}", failures)

    # Palette aliases may have one owner and one declaration. In the past,
    # later root blocks silently changed the current green palette to amber.
    palette_owners = {
        "cliptalk-tokens.css": ["--ct-canvas", "--ct-panel", "--ct-primary", "--ct-text", "--ct-sidebar"],
        "theme.css": ["--pw-canvas", "--pw-canvas-deep", "--pw-surface-1", "--pw-text", "--pw-accent", "--pw-accent-hover", "--pw-accent-ink"],
        "secondary-editor-focus.css": ["--secondary-accent", "--secondary-canvas", "--secondary-panel", "--secondary-text"],
    }
    for owner, tokens in palette_owners.items():
        for token in tokens:
            declarations = [
                path.name for path in STATIC.glob("*.css")
                for _ in re.finditer(rf"{re.escape(token)}\s*:", path.read_text(encoding="utf-8"))
            ]
            check(declarations == [owner], f"色板 {token} 必须仅由 {owner} 定义一次：{declarations}", failures)

    controller = (STATIC / "workspace-controller.js").read_text(encoding="utf-8")
    timeline = (STATIC / "timeline-presentation.js").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    check(controller.count("new MutationObserver") == 1, "工作台控制器必须只有一个根观察器", failures)
    check("new MutationObserver" not in timeline, "时间线展示模块不得自行观察和重排工作区", failures)
    check("ClipTalkWorkspaceState?.execution?.(job)" in app, "app.js 绕过了统一 execution 契约", failures)
    check("legacy-activate" not in app, "前端仍在调用已弃用的激活接口", failures)
    check("ct-faithful-v3" not in controller, "工作台控制器仍保留退役的 v3 状态", failures)
    check("data-panel-resizer" not in html, "生产页面重新引入了已退役的自由侧栏拖拽", failures)
    check("reviewWorkbenchResizer" not in html, "生产页面重新引入了失效的审核区拖拽", failures)
    check("timelineResizer" not in html, "生产页面重新引入了失效的时间线拖拽", failures)
    check("cliptalk-review-workbench-height" not in app, "运行时仍在保存已退役的审核区高度", failures)
    check("vlm-highlight-panel-layout" not in app, "运行时仍在保存已退役的侧栏宽度", failures)

    if failures:
        print("Frontend ownership audit failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(
        "Frontend ownership audit passed: "
        f"{len(styles)} stylesheets, {len(scripts)} scripts, one workbench owner."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
