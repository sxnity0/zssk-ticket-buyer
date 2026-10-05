#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
umask 077
if [[ -z "${PREFIX:-}" || "$PREFIX" != *com.termux* ]]; then
  echo 'Tento inštalátor spusti v aplikácii Termux na Androide.' >&2
  exit 1
fi
task_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
pkg update -y
pkg install -y proot-distro curl ripgrep
# Zámerne samostatný kontajner; existujúci Debian používateľa sa nemení.
container_name='zssk-mobile'
if ! proot-distro login "$container_name" --no-sysvipc -- /bin/true >/dev/null 2>&1; then
  proot-distro install debian:12 --name "$container_name"
fi
proot-distro login "$container_name" --no-sysvipc --bind "$task_dir:/opt/zssk-app" -- /bin/bash -s <<'DEBIAN'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
  xvfb x11vnc novnc websockify fonts-dejavu-core
python3 -m venv /opt/zssk-venv
/opt/zssk-venv/bin/pip install -r /opt/zssk-app/requirements.txt
/opt/zssk-venv/bin/python -m playwright install --with-deps chromium
DEBIAN
echo
echo 'Inštalácia dokončená. Spustenie:'
echo "bash \"$task_dir/start.sh\""
