#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: tools/setup-codex-bubblewrap.sh [options]

Install and configure bubblewrap for the Codex Linux sandbox.

Options:
  --dry-run                      Print commands without running them.
  --allow-global-userns-relax    If AppArmor still blocks bwrap, temporarily set
                                 kernel.apparmor_restrict_unprivileged_userns=0.
  --persist-global-userns-relax  With --allow-global-userns-relax, persist that
                                 sysctl in /etc/sysctl.d/99-codex-userns.conf.
  -h, --help                     Show this help.

Security model:
  The safe path is package-managed bubblewrap plus the bwrap AppArmor profile.
  Relaxing kernel.apparmor_restrict_unprivileged_userns is a broader host-level
  change, so this script only does it when explicitly requested.
EOF
}

dry_run=0
allow_global_userns_relax=0
persist_global_userns_relax=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      dry_run=1
      ;;
    --allow-global-userns-relax)
      allow_global_userns_relax=1
      ;;
    --persist-global-userns-relax)
      allow_global_userns_relax=1
      persist_global_userns_relax=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

run() {
  if [ "$dry_run" -eq 1 ]; then
    printf 'DRY RUN:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

have() {
  command -v "$1" >/dev/null 2>&1
}

sudo_cmd() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

run_sudo() {
  if [ "$dry_run" -eq 1 ]; then
    if [ "$(id -u)" -eq 0 ]; then
      run "$@"
    else
      run sudo "$@"
    fi
  else
    sudo_cmd "$@"
  fi
}

detect_os() {
  os_id=""
  os_version_id=""
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    os_id="${ID:-}"
    os_version_id="${VERSION_ID:-}"
  fi
}

install_bubblewrap() {
  if have bwrap; then
    echo "bubblewrap already installed: $(command -v bwrap)"
    bwrap --version || true
    return
  fi

  if have apt-get; then
    run_sudo apt-get update
    run_sudo apt-get install -y bubblewrap
  elif have dnf; then
    run_sudo dnf install -y bubblewrap
  elif have yum; then
    run_sudo yum install -y bubblewrap
  elif have pacman; then
    run_sudo pacman -Sy --needed bubblewrap
  elif have zypper; then
    run_sudo zypper install -y bubblewrap
  else
    echo "No supported package manager found. Install the distro package named bubblewrap." >&2
    exit 1
  fi
}

load_ubuntu_bwrap_apparmor_profile() {
  if [ "${os_id:-}" != "ubuntu" ]; then
    return
  fi

  profile_src="/usr/share/apparmor/extra-profiles/bwrap-userns-restrict"
  profile_dst="/etc/apparmor.d/bwrap-userns-restrict"

  if [ ! -r "$profile_src" ] && have apt-get; then
    run_sudo apt-get update
    run_sudo apt-get install -y apparmor-profiles apparmor-utils
  fi

  if [ -r "$profile_src" ]; then
    run_sudo install -m 0644 "$profile_src" "$profile_dst"
    run_sudo apparmor_parser -r "$profile_dst"
    echo "Loaded AppArmor profile: $profile_dst"
  elif [ -r "$profile_dst" ]; then
    run_sudo apparmor_parser -r "$profile_dst"
    echo "Reloaded AppArmor profile: $profile_dst"
  else
    echo "AppArmor bwrap profile not found; skipping profile load." >&2
  fi

  if have systemctl; then
    run_sudo systemctl reload apparmor.service || true
  fi
}

apparmor_userns_restricted() {
  sysctl_file="/proc/sys/kernel/apparmor_restrict_unprivileged_userns"
  [ -r "$sysctl_file" ] && [ "$(cat "$sysctl_file")" = "1" ]
}

maybe_relax_global_userns_restriction() {
  if ! apparmor_userns_restricted; then
    return
  fi

  if [ "$allow_global_userns_relax" -ne 1 ]; then
    cat >&2 <<'EOF'
AppArmor still restricts unprivileged user namespaces.

For the lowest-risk setup, prefer fixing/loading the bwrap AppArmor profile.
If Codex still cannot start its Linux sandbox and you accept the broader
host-level risk, rerun with:

  tools/setup-codex-bubblewrap.sh --allow-global-userns-relax

Add --persist-global-userns-relax only if you intentionally want this sysctl
to survive reboot.
EOF
    return
  fi

  run_sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0

  if [ "$persist_global_userns_relax" -eq 1 ]; then
    tmp_file="$(mktemp)"
    printf '%s\n' 'kernel.apparmor_restrict_unprivileged_userns=0' > "$tmp_file"
    run_sudo install -m 0644 "$tmp_file" /etc/sysctl.d/99-codex-userns.conf
    rm -f "$tmp_file"
    run_sudo sysctl --system
  fi
}

print_next_steps() {
  cat <<'EOF'

Next steps:
  1. Restart Codex or start a new Codex session.
  2. Keep Codex permissions on workspace-write with on-request approvals.
  3. Avoid using danger-full-access as a workaround for sandbox setup errors.

To undo a persisted global userns relaxation:
  sudo rm -f /etc/sysctl.d/99-codex-userns.conf
  sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=1
  sudo sysctl --system
EOF
}

main() {
  detect_os
  echo "Detected OS: ${os_id:-unknown} ${os_version_id:-}"
  install_bubblewrap
  load_ubuntu_bwrap_apparmor_profile
  # maybe_relax_global_userns_restriction
  # print_next_steps
}

main "$@"
