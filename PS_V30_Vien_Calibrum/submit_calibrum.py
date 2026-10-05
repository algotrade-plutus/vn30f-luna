#!/usr/bin/env python3
"""Check or submit the frozen three-file Calibrum package."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time


ALPHA_DIR = Path(__file__).resolve().parent
ROOT = ALPHA_DIR.parent.parent
LIBS_DIR = Path("/home/jovyan/shared-storage/libs")
profile = os.environ.get("EVANGELION_PROFILE")
if profile and profile != "research":
    raise RuntimeError("submit_calibrum.py cần Evangelion Research profile")
for path in ((ALPHA_DIR,) if profile else (LIBS_DIR, ALPHA_DIR)):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

env_file = LIBS_DIR / ".env"
if env_file.is_file():
    from dotenv import load_dotenv

    load_dotenv(env_file)

import dm_manager  # noqa: E402
from PS_V30_Vien_Calibrum import CalibrumAlpha  # noqa: E402


EXPECTED_FILES = [
    "PS_V30_Vien_Calibrum.py",
    "config.json",
    "PS_V30_Vien_Calibrum_model.pt",
]


def load_json(name: str) -> dict:
    return json.loads((ALPHA_DIR / name).read_text(encoding="utf-8"))


def verify_package(files: list[str]) -> None:
    if files != EXPECTED_FILES:
        raise ValueError(f"Manifest phải đúng {EXPECTED_FILES}")
    for name in files:
        path = ALPHA_DIR / name
        if not path.is_file() or path.parent != ALPHA_DIR:
            raise FileNotFoundError(f"Manifest thiếu file hợp lệ: {name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"  {name:<38} {path.stat().st_size:>8} bytes  {digest}")


def run(action: str) -> None:
    os.chdir(ALPHA_DIR)
    config = load_json("config.json")
    manifest = load_json("submit_manifest.json")
    files = list(manifest["submission_files"])
    if manifest["alpha_name"] != config["name"]:
        raise ValueError("Tên alpha trong manifest và config không khớp")
    if config.get("name") != "PS_V30_Vien_Calibrum":
        raise ValueError("Sai tên Calibrum")
    if config.get("class_name") != "CalibrumAlpha":
        raise ValueError("Sai class_name Calibrum")
    if config.get("alpha_type") != "ml":
        raise ValueError("Calibrum phải khai báo alpha_type='ml'")
    if config.get("time_to_start") != ["Auto"]:
        raise ValueError("Calibrum phải dùng time_to_start=['Auto']")
    verify_package(files)

    alpha = CalibrumAlpha(config)
    dm_list = dm_manager.DMManager("PM_alpha_calibrum_submit").get_data(config["data"])
    started = time.perf_counter()
    alpha.generate(dm_list)
    elapsed = time.perf_counter() - started
    metrics = alpha.backtest(fee=0.4).Get_metrics()
    alpha.test_alpha()
    checks = {
        "generate_under_20s": elapsed < 20.0,
        "margin_ge_15": float(metrics["margin_after_fee"]) >= 15.0,
        "sharpe_ge_1_5": float(metrics["sharpe_after_fee"]) >= 1.5,
        "trades_ge_180": int(metrics["total_trade"]) >= 180,
        "futures_leak": bool(alpha.is_pass_futures_leak),
        "overfit": bool(alpha.is_pass_overfit),
    }
    print(
        f"Generate {elapsed:.3f}s | Net {metrics['profit_after_fee']:+.1f} | "
        f"Sharpe {metrics['sharpe_after_fee']:.2f} | "
        f"Margin {metrics['margin_after_fee']:.2f} bps | "
        f"Trades {metrics['total_trade']}"
    )
    print("Checks:", checks)
    if not all(checks.values()):
        raise RuntimeError("Calibrum chưa vượt toàn bộ pre-submit checks")

    if action == "check":
        print("Dry-run hoàn tất; không thay đổi trạng thái remote.")
        return
    if not config.get("password") or config["password"] == "YOUR_PASSWORD_HERE":
        raise ValueError("Điền password thật trước khi submit/update")
    response = alpha.submit_alpha(files) if action == "submit" else alpha.update_alpha(files)
    print(json.dumps(response, indent=2, ensure_ascii=False, default=str))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", nargs="?", choices=("check", "submit", "update"), default="check"
    )
    run(parser.parse_args().action)


if __name__ == "__main__":
    main()
