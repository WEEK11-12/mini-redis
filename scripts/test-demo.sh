#!/usr/bin/env bash
# Run the interactive cache demo test suite (tests/test_interactive_cache.py).
# Scope: this demo only. It needs no MongoDB, no Docker and no network; it uses in-memory
# doubles plus real Mini Redis child processes on OS-assigned loopback ports.
# Other suites (store, HTTP API, expiration, concurrency) are not part of this command.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${DEMO_PYTHON:-python3}"

usage() {
  cat <<EOF
사용법: ./scripts/test-demo.sh [--help]

인터랙티브 캐시 시연의 자동 시험(tests/test_interactive_cache.py)만 실행합니다.
MongoDB·Docker·네트워크가 필요 없고, 사용자의 DB·속도 기록·실행 중인 시연을 건드리지 않습니다.
다른 단계의 시험(저장소·HTTP API·만료·동시성)은 여기에 포함되지 않습니다.
동시성 시험은 임시 계측이 필요해 별도로 다룹니다 — docs/iterations/05-concurrency/verification.md

환경 변수: DEMO_PYTHON(기본 python3)
EOF
}

for argument in "$@"; do
  case "$argument" in
    -h|--help) usage; exit 0 ;;
    *) usage >&2; printf '오류: 알 수 없는 인자: %s\n' "$argument" >&2; exit 2 ;;
  esac
done

command -v "$PYTHON" >/dev/null 2>&1 || { printf '오류: %s 를 찾을 수 없습니다.\n' "$PYTHON" >&2; exit 2; }

cd "$ROOT"
printf '시연 시험을 실행합니다 (tests/test_interactive_cache.py).\n'
"$PYTHON" -B -m unittest discover -s tests -p 'test_interactive_cache.py'
