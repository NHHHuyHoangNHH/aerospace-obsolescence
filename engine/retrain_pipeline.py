"""
engine/retrain_pipeline.py
===========================
Wrapper chạy tuần tự: train.py → embeddings.py
Dùng làm entrypoint cho Cloud Run Job retrain-job.

Chạy:
    python engine/retrain_pipeline.py --version 3
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent


def log(msg: str):
    print(f"{datetime.now().strftime('%H:%M:%S')}  {msg}", flush=True)


def run(script: str, extra_args: list[str] = []) -> int:
    cmd = [sys.executable, str(ROOT / script)] + extra_args
    log(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    return result.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="1", help="Model version")
    args = parser.parse_args()

    log("=" * 55)
    log(f"Retrain Pipeline — version: {args.version}")
    log("=" * 55)

    # Step 1: Train XGBoost
    log("\n[1/2] Running train.py...")
    code = run("train.py", ["--version", args.version])
    if code != 0:
        log(f"❌ train.py failed (exit {code}) — aborting")
        sys.exit(code)
    log("✅ train.py done")

    # Step 2: Rebuild embeddings + evidence
    log("\n[2/2] Running embeddings.py...")
    code = run("embeddings.py", ["--top-n", "50", "--rebuild-index"])
    if code != 0:
        log(f"❌ embeddings.py failed (exit {code})")
        sys.exit(code)
    log("✅ embeddings.py done")

    log("\n" + "=" * 55)
    log(f"✅ Retrain pipeline complete — model v{args.version}")
    log("=" * 55)


if __name__ == "__main__":
    main()