"""Run one training command and record observed whole-GPU and WSL resources."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--resources", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Missing child command")
    if args.log.exists() or args.resources.exists():
        raise FileExistsError("Use new log/resource paths")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    started_utc = datetime.now(UTC).isoformat()
    observations = []
    with args.log.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        while process.poll() is None:
            row = {"elapsed_seconds": time.perf_counter() - started,
                   "wsl_available_mib": psutil.virtual_memory().available / 2**20,
                   "swap_used_mib": psutil.swap_memory().used / 2**20}
            try:
                usage = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu,temperature.gpu",
                                                  "--format=csv,noheader,nounits"], text=True, timeout=3).strip().splitlines()[0]
                memory, utilization, temperature = map(float, usage.split(","))
                row.update(gpu_used_mib=memory, gpu_util_percent=utilization, gpu_temp_c=temperature)
            except (subprocess.SubprocessError, ValueError, IndexError):
                pass
            try:
                child = psutil.Process(process.pid)
                row["process_tree_rss_mib"] = sum(p.memory_info().rss for p in [child] + child.children(recursive=True)) / 2**20
            except psutil.Error:
                pass
            observations.append(row)
            time.sleep(.8)
        code = process.wait()
    result = {"started_utc": started_utc, "exit_code": code,
              "elapsed_seconds": time.perf_counter() - started, "command": command,
              "gpu_memory_scope": "Whole GPU including Windows and other processes; observed samples, not an exact allocator peak.",
              "observed_gpu_peak_mib": max((r["gpu_used_mib"] for r in observations if "gpu_used_mib" in r), default=None),
              "minimum_wsl_available_mib": min((r["wsl_available_mib"] for r in observations), default=None),
              "max_swap_used_mib": max((r["swap_used_mib"] for r in observations), default=None),
              "observations": observations}
    args.resources.parent.mkdir(parents=True, exist_ok=True)
    args.resources.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "observations"}), flush=True)
    sys.exit(code)


if __name__ == "__main__":
    main()
