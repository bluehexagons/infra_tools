#!/bin/sh

set -eu

REPOSITORY="bluehexagons/infra_tools"
REF="${INFRA_TOOLS_REF:-main}"
INSTALL_DIR=""
TARGET_USER=""
SHELL_NAME=""
RUN_SETUP=0
ARCHIVE_URL="${INFRA_TOOLS_ARCHIVE_URL:-}"

usage() {
    cat <<'EOF'
Install or update infra_tools from GitHub.

Usage:
  install.sh [options]
  install.sh [options] --setup SYSTEM_TYPE HOST [USERNAME] [SETUP_OPTIONS...]

Options:
  --ref REF            Git branch, tag, or commit to install (default: main)
  --install-dir PATH   Source destination (default: /opt/infra_tools as root,
                       otherwise ~/.local/share/infra_tools)
  --user USER          User receiving local tools and completions
  --shell SHELL        bash, zsh, fish, or tcsh (default: target user's shell)
  --setup ...          Run `infra_tools setup ...` after installation
  -h, --help           Show this help

Examples:
  curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | sh
  wget -qO- https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | sh
  curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh |
    sudo sh -s -- --user "$USER"
  curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh |
    sh -s -- --setup server_dev localhost "$USER" --machine hardware --agent-suite terminal
  curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh |
    sudo sh -s -- --user "$USER" --setup server_proxmox 10.0.0.10 root --key /home/me/.ssh/id_ed25519
EOF
}

fail() {
    printf 'infra_tools installer: %s\n' "$*" >&2
    exit 1
}

run_privileged() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
        return
    fi

    command -v sudo >/dev/null 2>&1 || fail "this step requires root privileges; install sudo or rerun the installer with sudo"
    sudo "$@"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --ref)
            [ "$#" -ge 2 ] || fail "--ref requires a value"
            REF=$2
            shift 2
            ;;
        --install-dir)
            [ "$#" -ge 2 ] || fail "--install-dir requires a value"
            INSTALL_DIR=$2
            shift 2
            ;;
        --user)
            [ "$#" -ge 2 ] || fail "--user requires a value"
            TARGET_USER=$2
            shift 2
            ;;
        --shell)
            [ "$#" -ge 2 ] || fail "--shell requires a value"
            SHELL_NAME=$2
            shift 2
            ;;
        --setup)
            RUN_SETUP=1
            shift
            break
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown option: $1"
            ;;
    esac
done

case "$REF" in
    ""|/*|*".."*|*[!A-Za-z0-9._/-]*)
        fail "invalid --ref value: $REF"
        ;;
esac

if [ "$RUN_SETUP" -eq 1 ] && [ "$#" -lt 2 ]; then
    fail "--setup requires at least SYSTEM_TYPE and HOST"
fi

CURRENT_USER=$(id -un)
if [ -z "$TARGET_USER" ]; then
    if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
        TARGET_USER=$SUDO_USER
    else
        TARGET_USER=$CURRENT_USER
    fi
fi

if ! id "$TARGET_USER" >/dev/null 2>&1; then
    fail "user not found: $TARGET_USER"
fi
if [ "$(id -u)" -ne 0 ] && [ "$TARGET_USER" != "$CURRENT_USER" ]; then
    fail "installing for another user requires root"
fi

TARGET_HOME=$(getent passwd "$TARGET_USER" | awk -F: 'NR == 1 { print $6 }')
[ -n "$TARGET_HOME" ] || fail "could not determine home directory for $TARGET_USER"

if [ -z "$INSTALL_DIR" ]; then
    if [ "$(id -u)" -eq 0 ]; then
        INSTALL_DIR=/opt/infra_tools
    else
        INSTALL_DIR="${XDG_DATA_HOME:-$TARGET_HOME/.local/share}/infra_tools"
    fi
fi
case "$INSTALL_DIR" in
    /*) ;;
    *) fail "--install-dir must be an absolute path" ;;
esac
[ "$INSTALL_DIR" != "/" ] || fail "refusing to use / as the install directory"

if [ -z "$SHELL_NAME" ]; then
    USER_SHELL=$(getent passwd "$TARGET_USER" | awk -F: 'NR == 1 { print $7 }')
    SHELL_NAME=$(basename "${USER_SHELL:-bash}")
fi
case "$SHELL_NAME" in
    bash|zsh|fish|tcsh) ;;
    *) SHELL_NAME=bash ;;
esac

LOCAL_SETUP=0
if [ "$RUN_SETUP" -eq 1 ]; then
    case "$2" in
        localhost|127.0.0.1|::1) LOCAL_SETUP=1 ;;
    esac

    if [ "$LOCAL_SETUP" -eq 1 ]; then
        SETUP_SYSTEM_TYPE=$1
        SETUP_HOST=$2
        shift 2
        if [ "$#" -eq 0 ] || [ "${1#-}" != "$1" ]; then
            set -- "$SETUP_SYSTEM_TYPE" "$SETUP_HOST" "$TARGET_USER" "$@"
        else
            set -- "$SETUP_SYSTEM_TYPE" "$SETUP_HOST" "$@"
        fi

        if [ "$(id -u)" -ne 0 ]; then
            command -v sudo >/dev/null 2>&1 || fail "local setup requires sudo; install sudo or rerun the installer with sudo"
        fi
    fi
fi

missing_prerequisite=0
for command_name in python3 git ssh rsync tar; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        missing_prerequisite=1
    fi
done
if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    missing_prerequisite=1
fi

if [ "$missing_prerequisite" -eq 1 ]; then
    command -v apt-get >/dev/null 2>&1 || fail "automatic prerequisite installation requires apt-get"
    printf '%s\n' "Installing bootstrap prerequisites..."
    run_privileged env DEBIAN_FRONTEND=noninteractive apt-get update -qq
    run_privileged env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        ca-certificates curl git openssh-client python3 rsync tar
fi

TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/infra_tools_install.XXXXXX")
cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

ARCHIVE_PATH="$TEMP_DIR/infra_tools.tar.gz"
if [ -n "${INFRA_TOOLS_ARCHIVE_FILE:-}" ]; then
    cp "$INFRA_TOOLS_ARCHIVE_FILE" "$ARCHIVE_PATH"
else
    if [ -z "$ARCHIVE_URL" ]; then
        ARCHIVE_URL="https://codeload.github.com/$REPOSITORY/tar.gz/$REF"
    fi
    printf 'Downloading infra_tools (%s)...\n' "$REF"
    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 3 --connect-timeout 20 "$ARCHIVE_URL" -o "$ARCHIVE_PATH"
    else
        wget -q --tries=3 --timeout=20 -O "$ARCHIVE_PATH" "$ARCHIVE_URL"
    fi
fi

if ! tar -tzf "$ARCHIVE_PATH" | while IFS= read -r archive_entry; do
    case "$archive_entry" in
        /*|../*|*/../*) exit 1 ;;
    esac
done; then
    fail "downloaded archive contains an unsafe path"
fi

TOP_LEVEL=$(tar -tzf "$ARCHIVE_PATH" | sed -n '1{s,/.*,,;p;}')
[ -n "$TOP_LEVEL" ] || fail "downloaded archive is empty"
tar -xzf "$ARCHIVE_PATH" -C "$TEMP_DIR"
EXTRACTED_DIR="$TEMP_DIR/$TOP_LEVEL"
[ -f "$EXTRACTED_DIR/infra_tools.py" ] || fail "downloaded archive does not contain infra_tools.py"

INSTALL_PARENT=$(dirname "$INSTALL_DIR")
mkdir -p "$INSTALL_PARENT"
STAGED_DIR="${INSTALL_DIR}.new.$$"
[ ! -e "$STAGED_DIR" ] || fail "staging path already exists: $STAGED_DIR"
mv "$EXTRACTED_DIR" "$STAGED_DIR"

BACKUP_DIR=""
rollback_install() {
    FAILED_DIR="${INSTALL_DIR}.failed.$$"
    if [ -e "$INSTALL_DIR" ]; then
        mv "$INSTALL_DIR" "$FAILED_DIR"
    fi
    if [ -n "$BACKUP_DIR" ] && [ -e "$BACKUP_DIR" ]; then
        mv "$BACKUP_DIR" "$INSTALL_DIR"
        printf 'Installation failed; previous install restored. Failed source kept at %s\n' "$FAILED_DIR" >&2
    else
        printf 'Installation failed; failed source kept at %s\n' "$FAILED_DIR" >&2
    fi
}

if [ -e "$INSTALL_DIR" ]; then
    BACKUP_DIR="${INSTALL_DIR}.backup.$(date +%s).$$"
    [ ! -e "$BACKUP_DIR" ] || fail "backup path already exists: $BACKUP_DIR"
    mv "$INSTALL_DIR" "$BACKUP_DIR"
fi
if ! mv "$STAGED_DIR" "$INSTALL_DIR"; then
    if [ -n "$BACKUP_DIR" ] && [ -e "$BACKUP_DIR" ]; then
        mv "$BACKUP_DIR" "$INSTALL_DIR"
    fi
    fail "could not activate downloaded source"
fi
if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR/state" ]; then
    if ! cp -a "$BACKUP_DIR/state" "$INSTALL_DIR/state"; then
        rollback_install
        fail "could not preserve existing infra_tools state"
    fi
fi

printf 'Installing infra_tools for %s...\n' "$TARGET_USER"
if [ "$(id -u)" -eq 0 ]; then
    if ! python3 "$INSTALL_DIR/infra_tools.py" bootstrap --shell "$SHELL_NAME" --user "$TARGET_USER"; then
        rollback_install
        exit 1
    fi
else
    if ! HOME=$TARGET_HOME USER=$TARGET_USER python3 "$INSTALL_DIR/infra_tools.py" bootstrap \
        --shell "$SHELL_NAME" \
        --user "$TARGET_USER" \
        --skip-system-packages; then
        rollback_install
        exit 1
    fi
fi

USER_LAUNCHER="$TARGET_HOME/.local/bin/infra_tools"
if [ ! -x "$USER_LAUNCHER" ]; then
    rollback_install
    fail "bootstrap completed without creating $USER_LAUNCHER"
fi
if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
    chmod 700 "$BACKUP_DIR"
fi

printf '\ninfra_tools installed successfully.\n'
printf '  Source: %s\n' "$INSTALL_DIR"
printf '  Command: %s\n' "$USER_LAUNCHER"
if [ -n "$BACKUP_DIR" ]; then
    printf '  Previous source backup: %s\n' "$BACKUP_DIR"
fi
case ":${PATH:-}:" in
    *":$TARGET_HOME/.local/bin:"*) ;;
    *) printf '  Note: add %s/.local/bin to PATH or start a new login shell.\n' "$TARGET_HOME" ;;
esac

run_for_target() {
    if [ "$TARGET_USER" = "$CURRENT_USER" ]; then
        HOME=$TARGET_HOME USER=$TARGET_USER "$@"
    else
        runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" "$@"
    fi
}

run_local_setup() {
    if [ -t 2 ] && [ -r /dev/tty ]; then
        run_privileged env \
            HOME="$TARGET_HOME" \
            USER="$TARGET_USER" \
            SUDO_USER="$TARGET_USER" \
            python3 "$INSTALL_DIR/infra_tools.py" setup "$@" < /dev/tty
    else
        run_privileged env \
            HOME="$TARGET_HOME" \
            USER="$TARGET_USER" \
            SUDO_USER="$TARGET_USER" \
            python3 "$INSTALL_DIR/infra_tools.py" setup "$@"
    fi
}

if [ "$RUN_SETUP" -eq 1 ]; then
    printf '\nRunning requested system setup as %s...\n' "$TARGET_USER"
    if [ "$LOCAL_SETUP" -eq 1 ]; then
        run_local_setup "$@"
    elif [ -t 2 ] && [ -r /dev/tty ]; then
        run_for_target python3 "$INSTALL_DIR/infra_tools.py" setup "$@" < /dev/tty
    else
        run_for_target python3 "$INSTALL_DIR/infra_tools.py" setup "$@"
    fi
fi
