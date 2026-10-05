#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_dir="$project_dir/.venv"
python_cmd="${ALGOTRADE_PYTHON:-}"
if [[ -z "$python_cmd" ]]; then
  for candidate in python3.11 python3.12 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && \
       "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
      python_cmd="$candidate"
      break
    fi
  done
fi
if [[ -z "$python_cmd" ]]; then
  echo "Python 3.10+ is required; set ALGOTRADE_PYTHON=/path/to/python" >&2
  exit 1
fi
with_fix=false
if [[ "${1:-}" == "--with-fix" ]]; then
  with_fix=true
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--with-fix]" >&2
  exit 2
fi

if [[ -x "$venv_dir/bin/python" ]]; then
  expected_version="$($python_cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  current_version="$($venv_dir/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [[ "$expected_version" != "$current_version" ]]; then
    echo "Existing .venv uses Python $current_version; move it aside before rebuilding with $expected_version" >&2
    exit 1
  fi
fi

"$python_cmd" -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip install --upgrade pip setuptools wheel
"$venv_dir/bin/python" -m pip install -r "$project_dir/requirements.txt"
"$venv_dir/bin/python" -m pip install "$project_dir/vendor/paperbroker_client-0.2.8-py3-none-any.whl"

if [[ "$with_fix" == true ]]; then
  machine_arch="$(uname -m)"
  kernel_name="$(uname -s)"
  if [[ "$kernel_name" == "Darwin" && "$machine_arch" == "arm64" ]]; then
    build_dir="$(mktemp -d /tmp/algotrade-quickfix.XXXXXX)"
    "$venv_dir/bin/python" -m pip download \
      --no-deps --no-binary=:all: --dest "$build_dir" quickfix==1.15.1
    tar -xzf "$build_dir/quickfix-1.15.1.tar.gz" -C "$build_dir"
    "$venv_dir/bin/python" "$project_dir/scripts/patch_quickfix_arm.py" \
      "$build_dir/quickfix-1.15.1"
    "$venv_dir/bin/python" -m pip install "$build_dir/quickfix-1.15.1"
  else
    "$venv_dir/bin/python" -m pip install 'quickfix>=1.15.1'
  fi
fi

"$venv_dir/bin/python" "$project_dir/scripts/diagnose.py"
