#!/bin/sh

set -eu

REPOSITORY="bluehexagons/infra_tools"
REPOSITORY_URL="${INFRA_TOOLS_REPOSITORY_URL:-https://github.com/$REPOSITORY.git}"
CHANNEL="${INFRA_TOOLS_CHANNEL:-dev}"
CHANNEL_SET=0
if [ "${INFRA_TOOLS_CHANNEL+x}" = "x" ]; then
    CHANNEL_SET=1
fi
INSTALL_DIR=""
TARGET_USER=""
SHELL_NAME=""
RUN_SETUP=0
LOCAL_SETUP_REQUESTED=0

usage() {
    cat <<'EOF'
Install or update infra_tools from a managed Git worktree.

Usage:
  install.sh [options]
  install.sh [options] --setup SYSTEM_TYPE HOST [USERNAME] [SETUP_OPTIONS...]
  install.sh [options] --local-setup SYSTEM_TYPE [SETUP_OPTIONS...]

Options:
  --channel CHANNEL     stable, dev, v[version], branch-[branch], or commit-[hash]
                        (default: dev for the current development release)
  --ref REF             Compatibility alias for --channel; bare refs are branches
  --install-dir PATH   Source destination (default: /opt/infra_tools as root,
                       otherwise ~/.local/share/infra_tools)
  --user USER          User receiving local tools and completions
  --shell SHELL        bash, zsh, fish, or tcsh (default: target user's shell)
  --setup ...          Run `infra_tools setup ...` after installation
  --local-setup TYPE   Run `infra_tools setup TYPE localhost USER` after installation
                       (the target user comes from --user or the invoking user)
  -h, --help           Show this help

Examples:
  curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | sh
  curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh |
    sh -s -- --channel stable
  wget -qO- https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | sh
  curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh |
    sudo sh -s -- --user "$USER"
  curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh |
    sh -s -- --setup server_dev localhost "$USER" --machine hardware --agent-suite terminal
  curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh |
    sudo sh -s -- --user "$USER" --local-setup control_plane --agent-suite terminal
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

normalize_ref() {
    case "$1" in
        main) CHANNEL=dev ;;
        stable|dev|v*|branch-*|commit-*) CHANNEL=$1 ;;
        *) CHANNEL="branch-$1" ;;
    esac
}

validate_channel() {
    case "$CHANNEL" in
        stable|dev) ;;
        v[0-9]*)
            case "$CHANNEL" in
                *[!A-Za-z0-9.+-]*|v) fail "invalid --channel value: $CHANNEL" ;;
            esac
            ;;
        branch-*)
            branch=${CHANNEL#branch-}
            [ -n "$branch" ] || fail "invalid --channel value: $CHANNEL"
            case "$branch" in
                *[!A-Za-z0-9._/-]*|.*|*/|*..*|*//*|*@\{*)
                    fail "invalid branch channel: $CHANNEL"
                    ;;
            esac
            ;;
        commit-*)
            commit=${CHANNEL#commit-}
            [ -n "$commit" ] || fail "invalid --channel value: $CHANNEL"
            case "$commit" in
                *[!A-Fa-f0-9]*) fail "invalid commit channel: $CHANNEL" ;;
            esac
            ;;
        *) fail "invalid --channel value: $CHANNEL" ;;
    esac
}

validate_host_os() {
    [ -r /etc/os-release ] || fail "cannot detect host distribution: /etc/os-release is missing"
    distro_id=$(sed -n 's/^ID=//p' /etc/os-release | sed 's/^"//; s/"$//' | head -n 1)
    case "$distro_id" in
        debian|ubuntu|linuxmint) ;;
        *) fail "unsupported host distribution: ${distro_id:-unknown}; Debian is officially supported (Ubuntu and Linux Mint are best-effort)" ;;
    esac
}

resolve_channel_ref() {
    case "$CHANNEL" in
        stable)
            TARGET_REF=$(git -C "$STAGED_DIR" tag --list 'v[0-9]*' | awk '/^v[0-9]+\.[0-9]+\.[0-9]+$/ { print }' | sort -V | tail -n 1)
            [ -n "$TARGET_REF" ] || fail "no versioned release tags are available for stable"
            TARGET_REF="refs/tags/$TARGET_REF"
            ;;
        dev) TARGET_REF=refs/remotes/origin/main ;;
        v*) TARGET_REF="refs/tags/$CHANNEL" ;;
        branch-*) TARGET_REF="refs/remotes/origin/${CHANNEL#branch-}" ;;
        commit-*) TARGET_REF=${CHANNEL#commit-} ;;
    esac

    if ! git -C "$STAGED_DIR" rev-parse --verify --quiet "$TARGET_REF^{commit}" >/dev/null; then
        fail "channel does not exist in the repository: $CHANNEL"
    fi
}

write_channel_state() {
    state_dir="$INSTALL_DIR/.infra_tools"
    mkdir -p "$state_dir"
    commit=$(git -C "$INSTALL_DIR" rev-parse --verify HEAD)
    state_path="$state_dir/channel.json"
    temporary_state="$state_path.new.$$"
    printf '{\n  "channel": "%s",\n  "commit": "%s"\n}\n' \
        "$CHANNEL" "$commit" > "$temporary_state"
    chmod 600 "$temporary_state"
    mv "$temporary_state" "$state_path"
}

if [ -n "${INFRA_TOOLS_REF:-}" ] && [ "${INFRA_TOOLS_CHANNEL+x}" != "x" ]; then
    normalize_ref "$INFRA_TOOLS_REF"
    CHANNEL_SET=1
fi

while [ "$#" -gt 0 ]; do
    case "$1" in
        --channel)
            [ "$#" -ge 2 ] || fail "--channel requires a value"
            CHANNEL=$2
            CHANNEL_SET=1
            shift 2
            ;;
        --ref)
            [ "$#" -ge 2 ] || fail "--ref requires a value"
            normalize_ref "$2"
            CHANNEL_SET=1
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
        --local-setup)
            RUN_SETUP=1
            LOCAL_SETUP_REQUESTED=1
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

validate_channel
validate_host_os

if [ "$RUN_SETUP" -eq 1 ] && [ "$LOCAL_SETUP_REQUESTED" -eq 0 ] && [ "$#" -lt 2 ]; then
    fail "--setup requires at least SYSTEM_TYPE and HOST"
fi
if [ "$LOCAL_SETUP_REQUESTED" -eq 1 ] && [ "$#" -lt 1 ]; then
    fail "--local-setup requires SYSTEM_TYPE"
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
if [ "$LOCAL_SETUP_REQUESTED" -eq 1 ]; then
    SETUP_SYSTEM_TYPE=$1
    shift
    set -- "$SETUP_SYSTEM_TYPE" localhost "$TARGET_USER" "$@"
    LOCAL_SETUP=1
    if [ "$(id -u)" -ne 0 ]; then
        command -v sudo >/dev/null 2>&1 || fail "local setup requires sudo; install sudo or rerun the installer with sudo"
    fi
elif [ "$RUN_SETUP" -eq 1 ]; then
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
for command_name in python3 git ssh rsync; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        missing_prerequisite=1
    fi
done
if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    missing_prerequisite=1
fi

ensure_debian_bootstrap_sources() {
    if [ "$distro_id" != "debian" ]; then
        return
    fi

    distro_codename=$(sed -n 's/^VERSION_CODENAME=//p' /etc/os-release | sed 's/^"//; s/"$//' | head -n 1)
    case "$distro_codename" in
        [a-z]*)
            case "$distro_codename" in
                *[!a-z0-9-]*) fail "invalid Debian release codename: $distro_codename" ;;
            esac
            ;;
        *) fail "could not determine Debian release codename" ;;
    esac

    # A minimal install may have only a CD/DVD source and may not yet have
    # Python available, so repair the bootstrap source configuration in POSIX
    # shell before attempting to install the installer's prerequisites.
    run_privileged sh -s -- "$distro_codename" <<'EOF'
set -eu

codename=$1
apt_dir=/etc/apt
source_dir="$apt_dir/sources.list.d"
keyring=/usr/share/keyrings/debian-archive-keyring.pgp
if [ ! -r "$keyring" ]; then
    keyring=/usr/share/keyrings/debian-archive-keyring.gpg
fi
managed_path="$source_dir/infra_tools-debian.sources"

[ -r "$keyring" ] || {
    printf '%s\n' "infra_tools installer: Debian archive keyring is missing at $keyring" >&2
    exit 1
}

mkdir -p "$source_dir"

for source_path in "$apt_dir/sources.list" "$source_dir"/*.list; do
    [ -f "$source_path" ] || continue
    if grep -Eq '^[[:space:]]*deb[[:space:]]+(\[[^]]*\][[:space:]]+)?cdrom:' "$source_path"; then
        backup_path="$source_path.infra_tools.bak"
        [ -e "$backup_path" ] || cp -p "$source_path" "$backup_path"
        sed -i -E 's/^([[:space:]]*deb[[:space:]]+(\[[^]]*\][[:space:]]+)?cdrom:)/# Disabled by infra_tools: \1/' "$source_path"
    fi
done

for source_path in "$source_dir"/*.sources; do
    [ -f "$source_path" ] || continue
    if awk '
        /^[[:space:]]*#/ { next }
        /(^|[[:space:]])cdrom:/ { found=1; exit }
        END { exit found ? 0 : 1 }
    ' "$source_path"; then
        backup_path="$source_path.infra_tools.bak"
        [ -e "$backup_path" ] || cp -p "$source_path" "$backup_path"
        sed -i 's/^/# Disabled by infra_tools: /' "$source_path"
    fi
done

temporary_path="$managed_path.new.$$"
cat > "$temporary_path" <<SOURCE
# Managed by infra_tools. Do not edit; rerun infra_tools after a Debian release change.
Types: deb
URIs: https://deb.debian.org/debian
Suites: $codename $codename-updates
Components: main non-free-firmware
Signed-By: $keyring

Types: deb
URIs: https://security.debian.org/debian-security
Suites: $codename-security
Components: main non-free-firmware
Signed-By: $keyring
SOURCE
chmod 0644 "$temporary_path"

if [ -e "$managed_path" ]; then
    grep -q '^# Managed by infra_tools' "$managed_path" || {
        rm -f "$temporary_path"
        printf '%s\n' "infra_tools installer: refusing to overwrite unmanaged APT source $managed_path" >&2
        exit 1
    }
    if cmp -s "$temporary_path" "$managed_path"; then
        rm -f "$temporary_path"
    else
        backup_path="$managed_path.infra_tools.bak"
        [ -e "$backup_path" ] || cp -p "$managed_path" "$backup_path"
        mv "$temporary_path" "$managed_path"
    fi
else
    mv "$temporary_path" "$managed_path"
fi
EOF
}

if [ "$missing_prerequisite" -eq 1 ]; then
    command -v apt-get >/dev/null 2>&1 || fail "automatic prerequisite installation requires apt-get"
    ensure_debian_bootstrap_sources
    printf '%s\n' "Installing bootstrap prerequisites..."
    run_privileged env DEBIAN_FRONTEND=noninteractive apt-get update -qq
    run_privileged env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        ca-certificates git openssh-client python3 rsync
fi

if [ "$CHANNEL_SET" -eq 0 ] && [ -f "$INSTALL_DIR/.infra_tools/channel.json" ]; then
    existing_channel=$(python3 -c \
        'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("channel", ""))' \
        "$INSTALL_DIR/.infra_tools/channel.json" 2>/dev/null || true)
    if [ -n "$existing_channel" ]; then
        CHANNEL=$existing_channel
        validate_channel
    fi
fi

if [ -e "$INSTALL_DIR" ] && [ -d "$INSTALL_DIR/.git" ]; then
    if [ -n "$(git -C "$INSTALL_DIR" status --porcelain)" ]; then
        fail "existing install has local changes; commit or stash them before reinstalling"
    fi
fi

TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/infra_tools_install.XXXXXX")
cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

INSTALL_PARENT=$(dirname "$INSTALL_DIR")
mkdir -p "$INSTALL_PARENT"
STAGED_DIR="${INSTALL_DIR}.new.$$"
[ ! -e "$STAGED_DIR" ] || fail "staging path already exists: $STAGED_DIR"

printf 'Cloning infra_tools repository (%s)...\n' "$CHANNEL"
if ! git clone "$REPOSITORY_URL" "$STAGED_DIR"; then
    fail "could not clone repository: $REPOSITORY_URL"
fi
if ! git -C "$STAGED_DIR" fetch --prune --tags origin; then
    fail "could not fetch repository refs"
fi
resolve_channel_ref
if ! git -C "$STAGED_DIR" checkout --detach "$TARGET_REF" >/dev/null; then
    fail "could not check out channel: $CHANNEL"
fi

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
if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR/.infra_tools" ]; then
    if ! cp -a "$BACKUP_DIR/.infra_tools" "$INSTALL_DIR/.infra_tools"; then
        rollback_install
        fail "could not preserve existing channel state"
    fi
fi
write_channel_state

if [ "$(id -u)" -eq 0 ] && [ "$TARGET_USER" != "root" ]; then
    TARGET_UID=$(getent passwd "$TARGET_USER" | awk -F: 'NR == 1 { print $3 }')
    TARGET_GID=$(getent passwd "$TARGET_USER" | awk -F: 'NR == 1 { print $4 }')
    if [ -z "$TARGET_UID" ] || [ -z "$TARGET_GID" ]; then
        rollback_install
        fail "could not determine target user ownership"
    fi
    if ! chown -R "$TARGET_UID:$TARGET_GID" "$INSTALL_DIR"; then
        rollback_install
        fail "could not assign the managed repository to $TARGET_USER"
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
printf '  Channel: %s\n' "$CHANNEL"
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
