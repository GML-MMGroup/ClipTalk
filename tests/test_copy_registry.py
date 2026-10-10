"""文案注册表唯一性与防回潮测试（设计 F）。

- 注册表必须包含关键标准文案；
- 已收敛事件的旧说法不得再出现在业务代码（lint 门禁）。

可直接运行（python tests/test_copy_registry.py）作为独立 lint，
也可被 pytest 收集。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import copy_messages as cm  # noqa: E402

# 已收敛事件的旧说法：命中即视为回归（防回潮）。
# 排除定义源 app/copy_messages.py 自身（其注释/函数体允许出现旧说法作说明）。
FORBIDDEN = [
    "已绑定当前任务的封面版本",
    "当前封面已保存",
    "封面已保存；生成成片后可继续绑定",
    "本次方案已执行完成，可查看对应结果",
    "本次要求已完成，可以查看结果",
    "查看处理详情",
    "查看检查详情",
    "修改后将重新生成方案，原方案不会立即覆盖",
    "预览成片效果。确认无误后即可导出",
]

SCAN_DIRS = [os.path.join(ROOT, "app"), os.path.join(ROOT, "static")]
EXCLUDE_FILES = {os.path.join(ROOT, "app", "copy_messages.py")}


def test_registry_has_standard_entries():
    for ns in (cm.STATUS, cm.MSG, cm.ACTION):
        assert isinstance(ns, dict) and ns, f"{ns!r} must be non-empty dict"
    assert cm.ACTION["view_detail"] == "查看详情"
    assert cm.ACTION["view_cover"] == "查看生成的封面"
    assert cm.ACTION["view_clip"] == "查看片段"
    assert cm.ACTION["view_history"] == "查看上次处理结果"
    assert cm.ACTION["view_quality"] == "查看质量提醒并定位问题片段"
    assert cm.STATUS["cover_saved"] == "封面已保存"


def _scan_hits():
    hits = []
    for base in SCAN_DIRS:
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.endswith((".py", ".js")):
                    continue
                fp = os.path.join(dirpath, fn)
                if fp in EXCLUDE_FILES:
                    continue
                try:
                    text = open(fp, encoding="utf-8").read()
                except OSError:
                    continue
                for phrase in FORBIDDEN:
                    if phrase in text:
                        hits.append((fp, phrase))
    return hits


def test_no_forbidden_legacy_phrases():
    hits = _scan_hits()
    assert not hits, "发现已收敛的旧说法仍在业务代码中:\n" + "\n".join(
        f"  {fp}: {phrase}" for fp, phrase in hits
    )


if __name__ == "__main__":
    hits = _scan_hits()
    if hits:
        print("FAIL: 发现已收敛旧说法:")
        for fp, phrase in hits:
            print(f"  {fp}: {phrase}")
        sys.exit(1)
    print("OK: 未发现已收敛旧说法")
