"""Accept a container port binding only when 27017/tcp maps exactly to 127.0.0.1:<port>.

Reads `docker container inspect -f '{{json .HostConfig.PortBindings}}'` on stdin.
Exit 0 when the mapping matches, 1 otherwise (wrong host IP, wrong host port,
another container port, external exposure, or no binding at all).
"""
import json
import sys

WANTED_CONTAINER_PORT = "27017/tcp"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_port_binding.py <host port>", file=sys.stderr)
        return 2
    host_port = sys.argv[1]
    try:
        bindings = json.loads(sys.stdin.read() or "null")
    except ValueError as error:
        print("포트 매핑을 읽지 못했습니다: %s" % error, file=sys.stderr)
        return 1
    if not isinstance(bindings, dict):
        print("포트 매핑이 없습니다.", file=sys.stderr)
        return 1

    for container_port, entries in bindings.items():
        if container_port == WANTED_CONTAINER_PORT or not entries:
            continue
        print("예상하지 않은 포트 매핑: %s" % container_port, file=sys.stderr)
        return 1

    entries = bindings.get(WANTED_CONTAINER_PORT) or []
    if len(entries) != 1:
        print("%s 매핑이 정확히 하나가 아닙니다." % WANTED_CONTAINER_PORT, file=sys.stderr)
        return 1
    entry = entries[0]
    if not isinstance(entry, dict):
        print("포트 매핑 형식을 알 수 없습니다.", file=sys.stderr)
        return 1
    if entry.get("HostIp") != "127.0.0.1" or entry.get("HostPort") != host_port:
        print("매핑이 127.0.0.1:%s가 아닙니다: %s" % (host_port, entry), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
