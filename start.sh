#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
umask 077
task_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
open_page() {
  if [[ -s "$task_dir/.launch-pin" ]]; then
    termux-open-url "http://127.0.0.1:8765/login#pin=$(cat "$task_dir/.launch-pin")"
  else
    termux-open-url "$(cat "$task_dir/.launch-url")"
  fi
}
if [[ -z "${PREFIX:-}" || "$PREFIX" != *com.termux* ]]; then
  echo 'Spusti v Termuxe.' >&2
  exit 1
fi
if [[ "${1:-}" == 'restart' ]]; then
  proot-distro login zssk-mobile --no-sysvipc --bind "$task_dir:/opt/zssk-app" -- \
    /opt/zssk-venv/bin/python /opt/zssk-app/stop.py
  for ((attempt=0; attempt<30; attempt++)); do
    curl --max-time 1 -fsS http://127.0.0.1:8765/health >/dev/null 2>&1 || break
    sleep 1
  done
  if curl --max-time 1 -fsS http://127.0.0.1:8765/health >/dev/null 2>&1; then
    echo 'Stará služba stále beží. Zastav ju cez Ctrl+C v jej okne Termuxu.' >&2
    exit 1
  fi
fi
if [[ -s "$task_dir/.launch-url" ]] && curl --max-time 2 -fsS http://127.0.0.1:8765/health | rg -q 'zssk-web'; then
  open_page
  exit 0
fi
if ! proot-distro login zssk-mobile --no-sysvipc -- /usr/bin/test -x /opt/zssk-venv/bin/python; then
  echo 'Najprv spusti bash install.sh.' >&2
  exit 1
fi
rm -f "$task_dir/.launch-url" "$task_dir/.launch-pin"
termux-wake-lock || true
service_pid=''
cleanup() {
  if [[ -n "$service_pid" ]]; then
    kill -TERM "$service_pid" 2>/dev/null || true
    wait "$service_pid" 2>/dev/null || true
  fi
  termux-wake-unlock || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
echo 'ZSSK sa spúšťa. Stránka sa otvorí automaticky.'
echo 'Termux nechaj bežať. Ukončenie: Ctrl+C.'
proot-distro login zssk-mobile --no-sysvipc --bind "$task_dir:/opt/zssk-app" -- \
  /bin/bash -c 'cd /opt/zssk-app && exec /opt/zssk-venv/bin/python mobile.py' &
service_pid=$!
opened=0
for ((attempt=0; attempt<120; attempt++)); do
  if ! kill -0 "$service_pid" 2>/dev/null; then
    wait "$service_pid" || true
    service_pid=''
    echo 'Služba sa nespustila. Pozri chybu vyššie.' >&2
    exit 1
  fi
  if [[ -s "$task_dir/.launch-url" ]] && curl --max-time 1 -fsS http://127.0.0.1:8765/health 2>/dev/null | rg -q 'zssk-web'; then
    if open_page; then opened=1; fi
    break
  fi
  sleep 0.25
done
if [[ "$opened" != 1 ]]; then
  echo 'Automatické otvorenie sa nepodarilo. Počkajte na spustenie a otvorte http://127.0.0.1:8765.'
fi
service_status=0
wait "$service_pid" || service_status=$?
service_pid=''
if [[ "$service_status" != 0 ]]; then
  echo "Služba ZSSK sa ukončila s kódom $service_status. Uložené lístky zostávajú v histórii." >&2
fi
exit "$service_status"
