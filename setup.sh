#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
if [[ -z "${PREFIX:-}" || "$PREFIX" != *com.termux* ]]; then
  echo 'Spusti v Termuxe.' >&2
  exit 1
fi
task_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
pkg install -y proot-distro curl ripgrep
if ! proot-distro login zssk-mobile --no-sysvipc -- /usr/bin/test -x /opt/zssk-venv/bin/python; then
  bash "$task_dir/install.sh"
fi
mkdir -p "$PREFIX/bin" "$HOME/.shortcuts"
# %q zachová medzery aj špeciálne znaky v lokálnej ceste.
{
  printf '#!/data/data/com.termux/files/usr/bin/bash\n'
  printf 'exec bash %q "$@"\n' "$task_dir/start.sh"
} > "$PREFIX/bin/zssk"
chmod 700 "$PREFIX/bin/zssk"
cp "$PREFIX/bin/zssk" "$HOME/.shortcuts/ZSSK"
chmod 700 "$HOME/.shortcuts/ZSSK"
echo 'Hotovo. Napíš zssk — stránka sa otvorí sama.'
