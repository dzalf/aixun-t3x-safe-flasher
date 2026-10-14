#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
#
# aixun.sh - self-contained workspace manager for the T3x safe updater.
#
# Everything lives in ONE folder (the "workspace"), wherever you put it:
#
#   aixun/                  <- workspace root (move/copy/rename freely; see "Moving" below)
#   ├── aixun               <- symlink to project/tools/aixun.sh (created by 'setup')
#   ├── project/            <- the code: a git repository (deliveries replace its contents)
#   ├── venv/               <- private Python environment (outside the repo, never touched by deliveries)
#   ├── firmware/           <- vendor .bin images (never committed)
#   ├── results/            <- test output, probe reports, flash logs
#   └── deliveries/         <- incoming .zip deliveries, kept as history
#
# Nothing is configured system-wide: no ~/.bashrc/~/.zshrc edits, no global git
# config, no system pip. All paths are derived from this script's own location.
# Runs under bash whatever your login shell is (Kali defaults to zsh).
#
# Usage:  ./aixun <command> [args]        (from the workspace root)
#         ./aixun help

set -euo pipefail

# ------------------------------------------------------------------ paths
SELF="$(readlink -f "${BASH_SOURCE[0]}")"         # real path, even when called via the symlink
PROJECT="$(cd "$(dirname "$SELF")/.." && pwd)"     # .../aixun/project
ROOT="$(cd "$PROJECT/.." && pwd)"                  # .../aixun
VENV="$ROOT/venv"
FIRMWARE="$ROOT/firmware"
RESULTS="$ROOT/results"
DELIVERIES="$ROOT/deliveries"
PY="$VENV/bin/python"
PYTHON="${PYTHON:-python3}"                         # override: PYTHON=python3.13 ./aixun setup

# ------------------------------------------------------------------ helpers
say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m  %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
git_() { git -C "$PROJECT" "$@"; }
stamp() { date +%Y%m%d_%H%M%S; }
need_venv() { [[ -x "$PY" ]] || die "no venv yet: run './aixun setup' first"; }
clean_tree() {
    [[ -z "$(git_ status --porcelain)" ]] || die "project has uncommitted changes (see './aixun status'); commit or discard them first"
}
current_branch() { git_ rev-parse --abbrev-ref HEAD; }
# Base branch: 'main' (workspaces made by setup, the GitHub default) or 'master' (older clones/forks).
base_branch() {
    if git_ rev-parse --verify -q main >/dev/null; then echo main
    elif git_ rev-parse --verify -q master >/dev/null; then echo master
    else echo main; fi
}
# Package manager, for exact install hints on any distribution.
pkg_manager() {
    local m
    for m in apt-get dnf zypper pacman; do command -v "$m" >/dev/null && { echo "$m"; return; }; done
    echo unknown
}
pkg_hint() {                          # $1 = base | gui
    case "$(pkg_manager):$1" in
        apt-get:base) echo "sudo apt install -y git rsync unzip python3 python3-venv" ;;
        apt-get:gui)  echo "sudo apt install -y libxcb-cursor0 libxkbcommon-x11-0 libegl1" ;;
        dnf:base)     echo "sudo dnf install -y git rsync unzip python3" ;;
        dnf:gui)      echo "sudo dnf install -y xcb-util-cursor libxkbcommon-x11 mesa-libEGL" ;;
        zypper:base)  echo "sudo zypper install -y git rsync unzip python3" ;;
        zypper:gui)   echo "sudo zypper install -y libxcb-cursor0 libxkbcommon-x11-0 libEGL1" ;;
        pacman:base)  echo "sudo pacman -S --needed git rsync unzip python" ;;
        pacman:gui)   echo "sudo pacman -S --needed xcb-util-cursor libxkbcommon-x11 libglvnd" ;;
        *)            echo "install with your package manager (see INSTALLATION.md)" ;;
    esac
}
# Group that owns USB serial ports: dialout (Debian/Ubuntu/Fedora/openSUSE) or uucp (Arch).
serial_group() {
    if getent group dialout >/dev/null; then echo dialout
    elif getent group uucp >/dev/null; then echo uucp
    else echo dialout; fi
}
pip_() {                             # visible progress: pip prints Collecting/Downloading/Installing lines
    "$PY" -m pip --disable-pip-version-check "$@"
}
_gui_prereq_checks() {               # warnings only: what the GUI needs from the system
    # distribution-independent: ask the dynamic linker which shared libraries exist
    local ldc libs missing_qt=()
    ldc="$(command -v ldconfig || echo /sbin/ldconfig)"
    if libs="$("$ldc" -p 2>/dev/null)"; then
        for so in libxcb-cursor.so.0 libxkbcommon-x11.so.0 libEGL.so.1; do
            grep -q "$so" <<<"$libs" || missing_qt+=("$so")
        done
        ((${#missing_qt[@]})) && warn "the GUI needs ${missing_qt[*]}: $(pkg_hint gui)  (Qt's X11 platform plugin will not start without them)"
    fi
    # PySide6 6.12 wheels: manylinux_2_39 on aarch64, manylinux_2_34 on x86_64 (older glibc: pip
    # falls back to an older PySide6 if one has a matching wheel; the CLI never needs Qt)
    local glibc need
    glibc="$("$PY" -c 'import platform; print(platform.libc_ver()[1] or "0")')"
    case "$(uname -m)" in aarch64|arm64) need=2.39 ;; *) need=2.34 ;; esac
    if [[ "$(printf '%s\n%s\n' "$glibc" "$need" | sort -V | head -n1)" != "$need" ]]; then
        warn "glibc $glibc found; PySide6 6.12 wheels for $(uname -m) need $need or newer: pip may pick an older PySide6 or none (the CLI still works)"
    fi
    return 0
}

# The venv only needs pip when project/pyproject.toml changes (dependencies, commands).
# Code changes need nothing: the project is installed "editable", so venv/ runs project/ directly.
# A stamp in venv/ records which pyproject.toml the venv was last built from.
STAMP="$VENV/.aixun-pyproject.sha256"
_pyproject_hash() { sha256sum "$PROJECT/pyproject.toml" | cut -d' ' -f1; }
_extras() { if [[ -f "$PROJECT/src/t3x/gui/app.py" ]]; then echo "dev,gui"; else echo "dev"; fi; }
venv_in_sync() { [[ -f "$STAMP" && "$(cat "$STAMP")" == "$(_pyproject_hash)" ]] && "$PY" -c 'import t3x' 2>/dev/null; }

SYNC_PARTIAL=0
sync_venv() {                        # $1 = force: reinstall even if nothing changed
    local extras; extras="$(_extras)"
    SYNC_PARTIAL=0
    if [[ "${1:-}" != force ]] && venv_in_sync; then
        say "venv already matches pyproject.toml: nothing to install (no internet needed)"
        return 0
    fi
    [[ "$extras" == *gui* ]] && _gui_prereq_checks
    say "Updating the venv from pyproject.toml (extras: $extras; downloads only what is missing)"
    local cons=()
    if [[ -n "${AIXUN_CONSTRAINTS:-}" ]]; then         # e.g. project/constraints/tested.txt: exact tested versions
        [[ -f "$AIXUN_CONSTRAINTS" ]] || die "AIXUN_CONSTRAINTS file not found: $AIXUN_CONSTRAINTS"
        cons=(-c "$AIXUN_CONSTRAINTS"); say "      using pinned versions from $AIXUN_CONSTRAINTS"
    fi
    if pip_ install "${cons[@]}" -e "${PROJECT}[$extras]"; then
        _pyproject_hash > "$STAMP"
        return 0
    fi
    # Offline? pip needs its build tool from the internet unless setuptools is already in the venv.
    if "$PY" -c 'import setuptools' 2>/dev/null; then
        warn "online install failed; retrying offline with the venv's own setuptools (new dependencies, if any, are NOT installed)"
        if pip_ install --no-build-isolation --no-deps -e "$PROJECT"; then
            warn "project re-installed offline. Run './aixun reinstall' once you are online to complete it"
            SYNC_PARTIAL=1
            return 0
        fi
    fi
    return 1
}

# ------------------------------------------------------------------ commands
cmd_help() {
    cat <<EOF
Workspace: $ROOT

  setup                 check prerequisites, create folders, git repo, venv; install the project
  apply ZIP             put a delivery on a new test branch (ZIP may be a name inside deliveries/)
  test [pytest args]    run the test suite; output saved to results/
  probe [FW] [args]     read-only station probe (FW: file name in firmware/); saved to results/
  flash FW [args]       flash firmware/FW with t3x-update; log saved to results/
  accept                merge the tested delivery branch into main (or master)
  rollback              return to main (or master) and discard the delivery branch
  status                branch, history, venv and folder summary
  gui [--sim]           start the graphical updater (--sim: built-in simulated station, no iron)
  online list [--product P]   versions listed on aixun-updates.github.io (internet; never flashes)
                        add -v (timings) or --refresh (ignore the saved list) after list/get/compare
  online get P V              download product P version V (or 'latest') into firmware/
  online compare [--product P]  are the files in firmware/ byte-identical to the site's copies?
  history               list recorded flashes (results/history.jsonl)
  history import [DIR]  add earlier flash logs (from results/, or DIR) to the history
  sim [args]            run the simulated station (for development without the iron)
  run CMD [args]        run any command inside the venv, e.g. './aixun run t3x-image info firmware/x.bin'
  reinstall             re-install the project into venv/ (after an interrupted apply; needs internet
                        unless only code changed)
  rebuild-venv          delete and recreate venv/ (after moving the workspace or a Python upgrade)
  check-publish         before pushing to GitHub: scan project/ and its history for firmware, logs,
                        serial numbers, keys; list commit authors (read-only)
EOF
}

check_layout() {
    # Expected: <workspace>/project/tools/aixun.sh. If the code folder has another name
    # (e.g. the zip was extracted INTO project/), the workspace root would silently move.
    # Two ways to get it wrong: code folder not called 'project' (old zips extracted into project/),
    # or the workspace root itself called 'project' (new zips extracted into project/ -> project/project).
    if [[ "$(basename "$PROJECT")" == "project" && "$(basename "$ROOT")" != "project" ]]; then
        return 0
    fi
    warn "the code folder is '$PROJECT'"
    warn "so the workspace root would be '$ROOT' (venv/, firmware/, results/, deliveries/ go there)."
    warn "Expected layout: <your workspace>/project/tools/aixun.sh. See docs/WORKFLOW.md section 3."
    if [[ -t 0 && "${AIXUN_ALLOW_LAYOUT:-}" != 1 ]]; then
        read -r -p "Use '$ROOT' as the workspace anyway? [y/N] " a
        [[ "$a" =~ ^[Yy]$ ]] || die "stopped; nothing was changed"
    elif [[ "${AIXUN_ALLOW_LAYOUT:-}" != 1 ]]; then
        die "unexpected layout (set AIXUN_ALLOW_LAYOUT=1 to accept it)"
    fi
}

cmd_setup() {
    check_layout
    say "[1/5] Checking prerequisites"
    local missing=()
    for c in git rsync unzip "$PYTHON"; do command -v "$c" >/dev/null || missing+=("$c"); done
    "$PYTHON" -c "import venv, ensurepip" 2>/dev/null || missing+=("python3-venv/python3-full")
    if ((${#missing[@]})); then
        die "missing: ${missing[*]}  ->  $(pkg_hint base)"
    fi
    local grp; grp="$(serial_group)"
    id -nG | grep -qw "$grp" || warn "user '$(id -un)' is not in the '$grp' group: serial access may fail (sudo usermod -aG $grp \$USER, then log out/in)"

    say "[2/5] Creating workspace folders under $ROOT"
    mkdir -p "$FIRMWARE" "$RESULTS" "$DELIVERIES"

    if [[ ! -d "$PROJECT/.git" ]]; then
        say "[3/5] Initialising git repository in project/ (settings stay local to this repository)"
        git_ init -q -b main
        if ! git_ config user.name >/dev/null; then
            git_ config user.name  "${GIT_NAME:-aixun workspace}"
            git_ config user.email "${GIT_EMAIL:-aixun@localhost}"
        fi
        git_ add -A
        git_ commit -q -m "Baseline: $(basename "$PROJECT") as delivered"
    else
        say "[3/5] Git repository already present (kept)"
    fi

    if [[ ! -x "$PY" ]]; then
        say "[4/5] Creating venv at $VENV"
        "$PYTHON" -m venv "$VENV"
    else
        say "[4/5] venv already present (kept)"
    fi
    say "[5/5] Installing the project and its dependencies into the venv"
    say "      (downloads pyserial, pytest, setuptools and, for the GUI, PySide6 ~85 MB; several minutes on a Raspberry Pi)"
    pip_ install --upgrade pip
    sync_venv force || die "installing into the venv failed (internet?). Fix the cause, then: ./aixun reinstall"

    ln -sfn "project/tools/aixun.sh" "$ROOT/aixun"
    say "Done. From $ROOT run:  ./aixun help"
    cmd_status
}

cmd_apply() {
    local zip="${1:-}"; [[ -n "$zip" ]] || die "usage: ./aixun apply ZIP"
    [[ -f "$zip" ]] || zip="$DELIVERIES/$zip"
    [[ -f "$zip" ]] || die "delivery not found: $1"
    case "$(readlink -f "$zip")" in "$DELIVERIES"/*) ;; *) cp "$zip" "$DELIVERIES/"; zip="$DELIVERIES/$(basename "$zip")";; esac
    need_venv; clean_tree

    local name branch tmp src
    name="$(basename "$zip" .zip)"
    branch="delivery/$name"
    git_ rev-parse --verify -q "$branch" >/dev/null && die "branch $branch already exists (accept or rollback it first)"

    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN
    unzip -q "$zip" -d "$tmp"
    src="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -n1)"
    [[ -n "$src" && -f "$src/pyproject.toml" ]] || die "unexpected zip layout (no project folder with pyproject.toml)"

    local base; base="$(base_branch)"
    say "Applying $name on new branch $branch (from $base)"
    git_ switch -q "$base"
    git_ switch -q -c "$branch"
    rsync -a --delete --exclude .git --exclude venv "$src"/ "$PROJECT"/
    git_ add -A
    if git_ diff --cached --quiet; then
        warn "delivery is identical to $base; nothing to commit"
    else
        git_ commit -q -m "Delivery: $name"
        git_ --no-pager diff --stat "$base"..HEAD | tail -n 25
    fi
    if ! sync_venv; then
        warn "The delivery IS applied (branch $branch, committed), but the venv could not be updated."
        warn "Nothing else changed. When the internet works:  ./aixun reinstall   then   ./aixun test"
        exit 1
    fi
    say "Now run './aixun test', then './aixun accept' or './aixun rollback'"
}

cmd_test() {
    need_venv
    local out
    out="$RESULTS/pytest_$(current_branch | tr '/' '-')_$(git_ rev-parse --short HEAD)_$(stamp).txt"
    say "Running tests (output also saved to ${out#"$ROOT"/})"
    set +e
    (cd "$PROJECT" && T3X_FW_DIR="$FIRMWARE" "$PY" -m pytest -v -rs "$@") 2>&1 | tee "$out"
    local rc=${PIPESTATUS[0]}
    set -e
    if ((rc == 0)); then say "All tests passed"; else warn "pytest exit code $rc: send ${out#"$ROOT"/}"; fi
    return "$rc"
}

_fw_path() {
    local f="$1"
    [[ -f "$f" ]] && { readlink -f "$f"; return; }
    [[ -f "$FIRMWARE/$f" ]] && { echo "$FIRMWARE/$f"; return; }
    die "firmware file not found: $f (put .bin files in ${FIRMWARE#"$ROOT"/}/)"
}

cmd_probe() {
    need_venv
    local args=() tag
    tag="probe_$(stamp)"
    if [[ $# -gt 0 && "$1" != -* ]]; then args+=(--fw "$(_fw_path "$1")"); shift; fi
    # one probe run -> both reports (text on screen + file, JSON to file)
    "$VENV/bin/t3x-probe" "${args[@]}" --reader-test 50 --json-out "$RESULTS/$tag.json" "$@" | tee "$RESULTS/$tag.txt"
    say "Saved results/$tag.txt and results/$tag.json"
}

cmd_flash() {
    need_venv
    [[ $# -ge 1 ]] || die "usage: ./aixun flash FW [t3x-update args]"
    local fw; fw="$(_fw_path "$1")"; shift
    "$VENV/bin/t3x-update" -d --log-dir "$RESULTS" "$fw" "$@"
}

cmd_accept() {
    clean_tree
    local b; b="$(current_branch)"
    [[ "$b" == delivery/* ]] || die "not on a delivery branch (current: $b)"
    local base; base="$(base_branch)"
    git_ switch -q "$base"
    git_ merge -q --no-ff -m "Accept ${b#delivery/}" "$b"
    git_ branch -q -d "$b"
    say "Accepted ${b#delivery/} into $base"
}

cmd_rollback() {
    local b; b="$(current_branch)"
    [[ "$b" == delivery/* ]] || die "not on a delivery branch (current: $b)"
    local base; base="$(base_branch)"
    read -r -p "Discard $b and return to $base? [y/N] " a
    [[ "$a" =~ ^[Yy]$ ]] || die "cancelled"
    git_ reset -q --hard
    git_ switch -q "$base"
    git_ branch -q -D "$b"
    need_venv
    sync_venv || warn "back on $base, but the venv could not be updated: run './aixun reinstall' when online"
    say "Back on $base ($(git_ log --oneline -1))"
}

cmd_status() {
    say "Workspace  $ROOT"
    echo "    branch   $(current_branch)   $(git_ log --oneline -1)"
    echo "    history:"; git_ --no-pager log --oneline -6 | sed 's/^/      /'
    [[ -n "$(git_ status --porcelain)" ]] && warn "uncommitted changes in project/"
    if [[ -x "$PY" ]]; then
        echo "    venv     $("$PY" --version 2>&1)  ($("$PY" -c 'import serial,os;print(os.path.dirname(serial.__file__))' 2>/dev/null || echo 'pyserial missing'))"
        if venv_in_sync; then echo "             matches pyproject.toml"; else echo "             NOT in sync with pyproject.toml: ./aixun reinstall"; fi
    else
        echo "    venv     (none: run ./aixun setup)"
    fi
    echo "    firmware $(find "$FIRMWARE" -maxdepth 1 -name '*.bin' 2>/dev/null | wc -l) image(s)    results $(find "$RESULTS" -maxdepth 1 -type f 2>/dev/null | wc -l) file(s)    deliveries $(find "$DELIVERIES" -maxdepth 1 -name '*.zip' 2>/dev/null | wc -l) zip(s)"
}

cmd_gui() {
    need_venv
    [[ -x "$VENV/bin/t3x-gui" ]] || die "the GUI is not installed: run './aixun setup' (needs a delivery that includes it)"
    if [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}${QT_QPA_PLATFORM:-}" ]]; then
        die "no desktop session found (DISPLAY and WAYLAND_DISPLAY are empty): run this from a terminal inside the desktop, not over SSH"
    fi
    (cd "$ROOT" && T3X_FIRMWARE_DIR="$FIRMWARE" T3X_RESULTS_DIR="$RESULTS" T3X_CONFIG="$ROOT/config/gui.json" \
        "$VENV/bin/t3x-gui" "$@")
}

cmd_online() {
    need_venv
    local sub="${1:-}"; shift || true
    local cache=(--cache-dir "$RESULTS/online")     # last version list kept in the workspace
    case "$sub" in
        list)    "$VENV/bin/t3x-online" "${cache[@]}" list "$@" ;;
        get)     "$VENV/bin/t3x-online" "${cache[@]}" get "$@" --dest "$FIRMWARE" ;;
        compare) "$VENV/bin/t3x-online" "${cache[@]}" compare "$FIRMWARE" "$@" ;;
        *) die "usage: ./aixun online list [--product P] | get P V | compare [--product P]" ;;
    esac
}

cmd_history() {
    need_venv
    if [[ "${1:-}" == import ]]; then
        shift
        "$VENV/bin/t3x-history" --results "$RESULTS" import "$@"
    else
        "$VENV/bin/t3x-history" --results "$RESULTS" list
    fi
}

cmd_sim() {
    need_venv
    local ports="$RESULTS/.sim-ports.json"
    say "In another terminal, prefix commands with:  T3X_SIM_PORTS=$ports ./aixun ..."
    "$VENV/bin/t3x-sim" --ports-file "$ports" "$@"
}

cmd_run() {
    need_venv
    [[ $# -ge 1 ]] || die "usage: ./aixun run CMD [args]"
    local c="$1"; shift
    [[ -x "$VENV/bin/$c" ]] && c="$VENV/bin/$c"
    (cd "$ROOT" && PATH="$VENV/bin:$PATH" VIRTUAL_ENV="$VENV" "$c" "$@")
}

cmd_check_publish() {
    say "Pre-publication check of project/ (read-only)"
    "$PYTHON" "$PROJECT/tools/check_publish.py" "$PROJECT"
}

cmd_reinstall() {
    need_venv
    sync_venv force || die "re-install failed (internet?). Nothing was removed; try again when online"
    if ((SYNC_PARTIAL)); then warn "venv re-installed offline only (see above)"; else say "venv re-installed and matches pyproject.toml"; fi
}

cmd_rebuild_venv() {
    say "Recreating $VENV"
    rm -rf "$VENV"
    cmd_setup
}

# ------------------------------------------------------------------ dispatch
c="${1:-help}"; shift || true
case "$c" in
    help|-h|--help) cmd_help ;;
    setup) cmd_setup "$@" ;;
    apply) cmd_apply "$@" ;;
    test) cmd_test "$@" ;;
    probe) cmd_probe "$@" ;;
    flash) cmd_flash "$@" ;;
    accept) cmd_accept "$@" ;;
    rollback) cmd_rollback "$@" ;;
    status) cmd_status "$@" ;;
    gui) cmd_gui "$@" ;;
    online) cmd_online "$@" ;;
    history) cmd_history "$@" ;;
    sim) cmd_sim "$@" ;;
    run) cmd_run "$@" ;;
    reinstall) cmd_reinstall "$@" ;;
    check-publish) cmd_check_publish "$@" ;;
    rebuild-venv) cmd_rebuild_venv "$@" ;;
    *) cmd_help; die "unknown command: $c" ;;
esac
