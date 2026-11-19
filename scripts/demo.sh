#!/usr/bin/env bash
# Start the interactive cache demo: checks, isolated venv, dedicated MongoDB, page server.
# Re-running is idempotent. It never stops or deletes another service, container or volume.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${DEMO_VENV:-$ROOT/.venv-demo}"
CONTAINER="${DEMO_CONTAINER:-mini-redis-demo}"
VOLUME="${DEMO_VOLUME:-${CONTAINER}-data}"
# 페이지 앱이 mongodb://127.0.0.1:27019 를 고정으로 쓰므로 이 포트는 바꾸지 않는다.
MONGO_PORT="27019"
PAGE_PORT="${DEMO_PAGE_PORT:-8766}"
IMAGE="mongo:7"
# 이 스크립트가 만든 자원임을 나중에 알아보기 위한 표지.
LABEL="mini-redis-demo"

usage() {
  cat <<EOF
사용법: ./scripts/demo.sh [--help]

키·값 인터랙티브 캐시 시연을 한 번에 실행합니다.
  1) Python 3·fcntl·Docker 실행 상태를 확인합니다.
  2) 격리 가상환경(${VENV})에 pymongo를 준비합니다.
  3) 전용 MongoDB 컨테이너 '${CONTAINER}'를 127.0.0.1:${MONGO_PORT}에 준비하고 응답을 기다립니다.
  4) 시연 페이지를 http://127.0.0.1:${PAGE_PORT}/ 에 띄웁니다.

Ctrl+C를 누르면 이 스크립트가 띄운 페이지 서버와 전용 캐시 자식만 종료합니다.
MongoDB 컨테이너·볼륨과 속도 기록은 그대로 둡니다(직접 'docker stop ${CONTAINER}').

MongoDB 포트 ${MONGO_PORT}는 페이지 앱이 고정으로 쓰므로 바꿀 수 없습니다.

이 스크립트가 만든 컨테이너·볼륨에는 표지 '${LABEL}=1'을 붙이고, 재실행할 때는 그 표지가
있는 자원만 자동으로 재사용합니다. 표지가 없는 기존 자원은 이름이 같아도 쓰지 않고 멈춥니다
(이름 지정만으로는 승인으로 보지 않습니다). 그 자원이 이 시연 전용임을 직접 확인했다면
  DEMO_CONTAINER=<이름> DEMO_ALLOW_LEGACY=<같은 이름> ./scripts/demo.sh
처럼 명시적으로 승인해 재사용하세요. 어떤 경우에도 다른 자원을 멈추거나 지우지 않습니다.

환경 변수: DEMO_VENV, DEMO_CONTAINER, DEMO_VOLUME, DEMO_PAGE_PORT, DEMO_ALLOW_LEGACY
EOF
}

fail() { printf '오류: %s\n' "$*" >&2; exit 1; }

for argument in "$@"; do
  case "$argument" in
    -h|--help) usage; exit 0 ;;
    *) usage >&2; printf '오류: 알 수 없는 인자: %s\n' "$argument" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null 2>&1 || fail "python3가 필요합니다."
python3 -c 'import fcntl' 2>/dev/null \
  || fail "이 시연은 fcntl 파일 잠금을 쓰는 OS(macOS·Linux)에서만 동작합니다."
command -v docker >/dev/null 2>&1 || fail "docker 명령이 없습니다. Docker를 설치한 뒤 다시 실행하세요."
docker info >/dev/null 2>&1 \
  || fail "Docker가 실행 중이 아닙니다. Docker를 먼저 실행하세요(이 스크립트는 설치·설정을 바꾸지 않습니다)."

# 이미 시연 페이지가 떠 있으면 중복 서버를 만들지 않는다.
if python3 - "$PAGE_PORT" <<'PY'
import socket, sys
probe = socket.socket()
probe.settimeout(1)
sys.exit(0 if probe.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
then
  printf '포트 %s를 이미 쓰고 있습니다. 시연 페이지가 떠 있다면 http://127.0.0.1:%s/ 를 그대로 쓰세요.\n' \
    "$PAGE_PORT" "$PAGE_PORT"
  printf '다른 프로그램이라면 그 프로그램을 종료하지 말고 DEMO_PAGE_PORT=<포트>로 다시 실행하세요.\n'
  exit 3
fi

if [ ! -x "$VENV/bin/python3" ]; then
  printf '가상환경을 만듭니다: %s\n' "$VENV"
  python3 -m venv "$VENV" || fail "가상환경을 만들지 못했습니다."
fi
if ! "$VENV/bin/python3" -c 'import pymongo' >/dev/null 2>&1; then
  printf 'pymongo를 설치합니다(선택 의존성).\n'
  "$VENV/bin/pip" install -q -r "$ROOT/examples/requirements-mongo.txt" \
    || fail "pymongo 설치에 실패했습니다. 네트워크와 pip 설정을 확인하세요."
  "$VENV/bin/python3" -c 'import pymongo' >/dev/null 2>&1 \
    || fail "pymongo 설치 뒤에도 import에 실패했습니다."
fi

# 같은 포트를 쓰는 다른 컨테이너가 있으면 건드리지 않고 멈춘다.
owner="$(docker ps -a --filter "publish=$MONGO_PORT" --format '{{.Names}}' | head -n 1 || true)"
if [ -n "$owner" ] && [ "$owner" != "$CONTAINER" ]; then
  fail "127.0.0.1:${MONGO_PORT}를 컨테이너 '${owner}'가 쓰고 있습니다. 그 컨테이너는 그대로 둡니다. 이 시연 전용임을 확인했다면 DEMO_CONTAINER=${owner}로 재사용하세요."
fi

if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  # 이름만으로는 이 시연 자원으로 인정하지 않는다. 표지(label)나 사용자의 명시적 선택이 필요하다.
  marked="$(docker container inspect -f "{{index .Config.Labels \"$LABEL\"}}" "$CONTAINER" 2>/dev/null || true)"
  if [ "$marked" != "1" ]; then
    if [ "${DEMO_ALLOW_LEGACY:-}" != "$CONTAINER" ]; then
      fail "컨테이너 '${CONTAINER}'에는 이 스크립트가 붙이는 표지(${LABEL})가 없습니다. 스크립트가 만든 자원이 아니므로 그대로 둡니다. 이 컨테이너가 이 시연 전용임을 직접 확인했다면 DEMO_ALLOW_LEGACY=${CONTAINER} 를 함께 지정해 다시 실행하세요."
    fi
    printf '표지 없는 기존 컨테이너를 사용자가 명시적으로 승인해 재사용합니다: %s\n' "$CONTAINER"
  fi

  image="$(docker container inspect -f '{{.Config.Image}}' "$CONTAINER")"
  case "$image" in mongo:*) ;; *) fail "컨테이너 '${CONTAINER}'의 이미지가 ${image} 입니다. 시연용인지 확인할 수 없어 중단합니다." ;; esac

  # /data/db가 이름 있는 볼륨인지 구조적으로 확인한다(임의 bind mount는 거부).
  data_volume="$(docker container inspect -f \
    '{{range .Mounts}}{{if eq .Destination "/data/db"}}{{.Type}} {{.Name}}{{end}}{{end}}' "$CONTAINER")"
  case "$data_volume" in
    'volume '?*) ;;
    *) fail "컨테이너 '${CONTAINER}'의 /data/db가 이름 있는 볼륨이 아닙니다(확인값: '${data_volume}'). 외부 디렉터리를 MongoDB에 연결하지 않도록 중단합니다." ;;
  esac
  data_volume="${data_volume#volume }"
  if [ "$marked" = "1" ] && [ "$data_volume" != "$VOLUME" ]; then
    fail "표지가 있는 컨테이너 '${CONTAINER}'의 데이터 볼륨이 '${data_volume}'입니다. 기대한 '${VOLUME}'과 달라 중단합니다."
  fi

  # 27017/tcp가 정확히 127.0.0.1:${MONGO_PORT}에 매핑됐는지 확인한다(부분 문자열 대조 금지).
  docker container inspect -f '{{json .HostConfig.PortBindings}}' "$CONTAINER" \
    | python3 "$ROOT/scripts/check_port_binding.py" "$MONGO_PORT" \
    || fail "컨테이너 '${CONTAINER}'의 포트 매핑이 127.0.0.1:${MONGO_PORT} → 27017/tcp가 아니어서 중단합니다."

  if [ "$(docker container inspect -f '{{.State.Running}}' "$CONTAINER")" != "true" ]; then
    printf '기존 컨테이너를 다시 시작합니다: %s\n' "$CONTAINER"
    docker start "$CONTAINER" >/dev/null || fail "컨테이너 '${CONTAINER}'를 시작하지 못했습니다."
  else
    printf '기존 시연 컨테이너를 재사용합니다: %s (127.0.0.1:%s, 볼륨 %s)\n' "$CONTAINER" "$MONGO_PORT" "$data_volume"
  fi
else
  # 같은 이름의 볼륨이 이미 있으면 용도를 알 수 없으므로 덮어쓰지 않는다.
  if docker volume inspect "$VOLUME" >/dev/null 2>&1; then
    volume_marked="$(docker volume inspect -f "{{index .Labels \"$LABEL\"}}" "$VOLUME" 2>/dev/null || true)"
    [ "$volume_marked" = "1" ] \
      || fail "볼륨 '${VOLUME}'이 이미 있지만 이 스크립트의 표지(${LABEL})가 없습니다. 그 볼륨은 그대로 둡니다. DEMO_VOLUME=<새 이름>으로 다시 실행하거나, 이 시연 전용임을 확인했다면 그 볼륨을 쓰는 컨테이너를 만든 뒤 DEMO_ALLOW_LEGACY로 재사용하세요."
    printf '표지가 있는 기존 볼륨을 재사용합니다: %s\n' "$VOLUME"
  else
    docker volume create --label "$LABEL=1" "$VOLUME" >/dev/null || fail "볼륨 '${VOLUME}'을 만들지 못했습니다."
  fi
  printf '전용 MongoDB를 새로 만듭니다: %s (127.0.0.1:%s)\n' "$CONTAINER" "$MONGO_PORT"
  docker run -d --name "$CONTAINER" --label "$LABEL=1" -p "127.0.0.1:$MONGO_PORT:27017" \
    -v "$VOLUME:/data/db" "$IMAGE" >/dev/null || fail "MongoDB 컨테이너를 시작하지 못했습니다."
fi

printf 'MongoDB 응답을 기다립니다'
ready=""
for _ in $(seq 1 40); do
  if "$VENV/bin/python3" - "$MONGO_PORT" <<'PY' >/dev/null 2>&1
import sys
from pymongo import MongoClient
client = MongoClient("mongodb://127.0.0.1:%s" % sys.argv[1], serverSelectionTimeoutMS=1000)
client.admin.command("ping")
client.close()
PY
  then ready="yes"; break; fi
  printf '.'
  sleep 1
done
printf '\n'
[ -n "$ready" ] || fail "MongoDB가 제한 시간 안에 응답하지 않았습니다. 'docker logs $CONTAINER'를 확인하세요."

printf '시연 페이지를 시작합니다. 종료하려면 Ctrl+C를 누르세요.\n'
cd "$ROOT"
exec "$VENV/bin/python3" -B -m examples.interactive_cache_page --port "$PAGE_PORT"
