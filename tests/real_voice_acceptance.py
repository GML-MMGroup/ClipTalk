"""Opt-in, isolated reference-voice acceptance on disjoint real-video ranges.

Run with --video, --reference START END, --positive START END,
--negative START END and --run. Ranges must be manually identified before
testing, not selected from model predictions. No cross-environment claim.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
import uuid

from real_video_acceptance import Runner, media_info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    for name in ("reference", "positive", "negative"):
        parser.add_argument("--" + name, nargs=2, type=float, required=True)
    parser.add_argument("--run", action="store_true", required=True)
    parser.add_argument("--skip-render", action="store_true", help="Match-only diagnostic; cannot pass full acceptance")
    args = parser.parse_args()
    duration = float(media_info(args.video, "/usr/bin/ffprobe")["format"]["duration"])
    spans = [args.reference, args.positive, args.negative]
    for start, end in spans:
        if not 0 <= start < end <= duration or end - start < 6:
            parser.error("Each labeled range must contain at least six seconds within the source")
    for index, (start, end) in enumerate(spans):
        if any(max(start, a) < min(end, b) for a, b in spans[index + 1:]):
            parser.error("Enrollment and evaluation ranges must be disjoint")
    root = Path(tempfile.mkdtemp(prefix="voice-acceptance-", dir="local-artifacts")).resolve()
    os.environ["HIGHLIGHT_VOICEPRINT_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(os.urandom(32)).decode()
    config = SimpleNamespace(base_url="http://127.0.0.1", in_process=True, config_root=Path("data"),
                             ffmpeg="/usr/bin/ffmpeg", ffprobe="/usr/bin/ffprobe", video=args.video,
                             speaker_video=None, timeout=1800, review_input=None)
    runner = Runner(config, root)
    report = {"mode": "real_reference_voice_disjoint_ranges", "source": str(args.video),
              "crossEnvironmentValidated": False, "semanticVerdict": "manual_review_required",
              "referenceRange": args.reference, "cases": [], "renderResults": []}
    print("REPORT", root, flush=True)
    def save():
        (root / "voice-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    try:
        reference = root / "reference.wav"
        subprocess.run([config.ffmpeg, "-v", "error", "-ss", str(args.reference[0]), "-i", str(args.video),
                        "-t", str(args.reference[1] - args.reference[0]), "-vn", "-ar", "16000", "-ac", "1",
                        str(reference)], check=True, timeout=120)
        with reference.open("rb") as stream:
            profile = runner.request("POST", "/api/voice-profiles/enroll",
                                     data={"label": "验收目标声音"}, files={"audio": ("reference.wav", stream, "audio/wav")})["profile"]
        report["enrollment"] = "passed"
        save()
        for name, span in (("positive", args.positive), ("negative", args.negative)):
            target = root / f"{name}.mp4"
            subprocess.run([config.ffmpeg, "-v", "error", "-ss", str(span[0]), "-i", str(args.video),
                            "-t", str(span[1] - span[0]), "-c:v", "libx264", "-preset", "ultrafast",
                            "-c:a", "aac", str(target)], check=True, timeout=180)
            with target.open("rb") as stream:
                job = runner.request("POST", "/api/jobs", files={"video": (target.name, stream, "video/mp4")},
                                     data={"workflow_kind": "speaker_edit", "force_reanalyze": "true"})["job"]
            row = {"case": name, "jobId": job["id"], "sourceRange": span, "status": "running"}
            report["cases"].append(row)
            runner.request("POST", f"/api/jobs/{job['id']}/content-search/target-voice", json={"profileId": profile["id"]})
            deadline = time.monotonic() + config.timeout
            while time.monotonic() < deadline:
                job = runner.request("GET", f"/api/jobs/{job['id']}")["job"]
                if job.get("status") in {"failed", "cancelled", "awaiting_content_confirmation"}:
                    break
                time.sleep(2)
            else:
                runner.request("POST", f"/api/jobs/{job['id']}/cancel")
                row["status"] = "timeout"
                save()
                continue
            matches = (job.get("contentSearch") or {}).get("candidates") or []
            row.update(status=job["status"], matchCount=len(matches),
                       automaticallySelectedCount=sum(bool(m.get("selected")) for m in matches),
                       clusterScores=[{k: cluster.get(k) for k in
                                      ("speaker", "score", "decision", "margin", "sampleCount", "consistencyEstablished")}
                                      for cluster in ((job.get("contentSearch") or {}).get("retrievalStats") or {}).get("voiceClusters") or []],
                       ranges=[{"start": m["start"], "end": m["end"], "requiresReview": m.get("requiresReview")} for m in matches])
            row["identityVerdict"] = ("candidate_found" if matches else "missed") if name == "positive" else ("false_positive" if matches else "rejected")
            save()
            if name == "positive" and matches and not args.skip_render:
                workspace = runner.request("POST", "/api/agent/workspaces", json={"jobId": job["id"], "title": "声纹渲染验收"})["workspace"]
                runner.args.video = target
                result = runner.case("voice", "把当前已核验的目标声音片段合成为审核样片", existing=(job["id"], workspace["id"]))
                report["renderResults"].append(result)
                save()
    except Exception as error:
        report["failure"] = {"type": type(error).__name__}
        save()
        raise
    finally:
        runner.client.close()
    print("Results", root / "voice-report.json", flush=True)
    return 0 if (len(report["cases"]) == 2 and report["cases"][0].get("identityVerdict") == "candidate_found"
                 and report["cases"][1].get("identityVerdict") == "rejected"
                 and any(r.get("status") == "render_passed" for r in report["renderResults"])) else 1


if __name__ == "__main__":
    raise SystemExit(main())
