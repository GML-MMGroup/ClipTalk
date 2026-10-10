"""Continue ONLY an isolated, completed automatic-delivery acceptance run.

Invokes configured models. Keeps the original report and all previous versions.
No main-instance jobs or credential files are copied or modified.
"""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from real_video_acceptance import Runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", choices=["shorter", "audio", "motion", "cover", "cover_default"], default=["shorter", "audio", "motion"])
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--retry-failed", action="store_true", help="Retry the latest failed isolated plan with current code")
    args = parser.parse_args()
    directory = args.report.resolve().parent
    local_root = Path("local-artifacts").resolve()
    if local_root not in directory.parents or not (directory / "runtime/jobs").is_dir():
        parser.error("Use a completed isolated local-artifacts acceptance report")
    previous_report = json.loads(args.report.read_text())
    if previous_report.get("mode") != "current_code_asgi_models_and_render":
        parser.error("Only isolated acceptance runs may be resumed")
    if args.retry_failed:
        previous = next((r for r in reversed(previous_report["results"]) if r.get("status") in {"failed", "no_result"} and r.get("planId")), None)
    else:
        previous = next((r for r in reversed(previous_report["results"]) if r.get("status") == "render_passed" and r.get("filename")), None)
    if not previous or any(r.get("status") == "running" for r in previous_report["results"]):
        parser.error("The preceding acceptance run must finish successfully first")
    config = SimpleNamespace(base_url="http://127.0.0.1", in_process=True, config_root=Path("data"),
                             ffmpeg="/usr/bin/ffmpeg", ffprobe="/usr/bin/ffprobe", video=Path(previous_report["source"]),
                             speaker_video=None, timeout=900, review_input=None, execution_mode="automatic_delivery")
    runner = Runner(config, directory)
    from app import main as application
    application.load_jobs()
    runner.results = previous_report["results"]
    goals = {"shorter": "把当前成片再剪短一点，不加字幕，不加封面",
             "audio": "为当前成片降低底噪并优化音量，不改画面，不加字幕，不加封面",
             "motion": "为当前成片增加1秒的动态图文片头，标题写：新品发布",
             "cover": "为当前成片更换封面，使用本次视频画面，封面文字：认真对话。把封面放在开头1秒。",
             # 不提"开头/片头"：验证封面默认合入片头（与成片一致）的新行为。
             "cover_default": "为当前成片更换封面，使用本次视频画面，封面文字：认真对话。"}
    passed = True
    try:
        if args.retry_failed:
            result = runner.case(previous["case"], previous["goal"], existing=(previous["jobId"], previous["workspaceId"]), retry_plan_id=previous["planId"])
            print("retry", result.get("status"), flush=True)
            return 0 if result.get("status") == "render_passed" else 1
        for name in args.cases:
            result = runner.case(name, goals[name], previous)
            print(name, result.get("status"), flush=True)
            if result.get("status") != "render_passed":
                passed = False
                break
            previous = result
    finally:
        runner.client.close()
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
