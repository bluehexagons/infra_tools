#!/usr/bin/env bash
# fix_pve_storage_mounts.sh
#
# Interactive script that finds Proxmox dir-type storages requiring a mount
# point on this node, identifies which are currently broken, and guides you
# through assigning a disk UUID to each one so it can be persisted in fstab.
#
# Fixes: "unable to activate storage 'X' - directory is expected to be a
#         mount point but is not mounted: '/mnt/pve/X' (500)"

set -euo pipefail

# ── Helpers ──────────────────────────────────────────────────────────────────

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "  ${BOLD}${1}${RESET}"; }
ok()      { echo -e "  ${GREEN}[ok]${RESET}     ${1}"; }
warn()    { echo -e "  ${YELLOW}[warn]${RESET}   ${1}"; }
err()     { echo -e "  ${RED}[error]${RESET}  ${1}" >&2; }
section() { echo -e "\n${BOLD}── ${1} ──${RESET}"; }

confirm() {
    # confirm "prompt" → returns 0 for yes, 1 for no
    local prompt="${1} [y/N] "
    local reply
    read -r -p "$(echo -e "  ${prompt}")" reply
    [[ "${reply,,}" == "y" || "${reply,,}" == "yes" ]]
}

# ── Root check ────────────────────────────────────────────────────────────────

if [[ $EUID -ne 0 ]]; then
    err "must run as root"
    exit 1
fi

FSTAB=/etc/fstab
HOSTNAME_SHORT="$(hostname -s)"

# ── Step 1: Find broken storages ──────────────────────────────────────────────

section "Scanning PVE storage config"

STORAGE_CFG=/etc/pve/storage.cfg
if [[ ! -f "$STORAGE_CFG" ]]; then
    err "$STORAGE_CFG not found — is this a Proxmox node?"
    exit 1
fi

# Collect dir: storages that have is_mountpoint=1 and apply to this node.
# storage.cfg blocks look like:
#   dir: <name>
#       path /mnt/pve/<name>
#       ...
#       is_mountpoint 1
#       nodes <comma-or-space separated list>   (optional; absent = all nodes)

declare -a BROKEN_NAMES=()
declare -a BROKEN_PATHS=()

current_name=""
current_path=""
current_is_mountpoint=0
current_nodes=""

process_block() {
    [[ -z "$current_name" ]] && return
    if [[ "$current_is_mountpoint" -eq 1 ]]; then
        # nodes line is optional; if absent the storage applies to all nodes
        local applies=1
        if [[ -n "$current_nodes" ]]; then
            applies=0
            # nodes can be space or comma separated
            for n in ${current_nodes//,/ }; do
                if [[ "$n" == "$HOSTNAME_SHORT" ]]; then
                    applies=1
                    break
                fi
            done
        fi
        if [[ "$applies" -eq 1 ]]; then
            if ! findmnt -rn "$current_path" > /dev/null 2>&1; then
                BROKEN_NAMES+=("$current_name")
                BROKEN_PATHS+=("$current_path")
            else
                ok "${current_name} (${current_path}) — already mounted"
            fi
        fi
    fi
}

while IFS= read -r line || [[ -n "$line" ]]; do
    # New block starts with a non-whitespace type: name line
    if [[ "$line" =~ ^[a-zA-Z] ]]; then
        process_block
        current_name=""
        current_path=""
        current_is_mountpoint=0
        current_nodes=""
        if [[ "$line" =~ ^dir:[[:space:]]+(.+) ]]; then
            current_name="${BASH_REMATCH[1]}"
        fi
    elif [[ "$line" =~ ^[[:space:]]+path[[:space:]]+(.+) ]]; then
        current_path="${BASH_REMATCH[1]}"
    elif [[ "$line" =~ ^[[:space:]]+is_mountpoint[[:space:]]+([0-9]+) ]]; then
        current_is_mountpoint="${BASH_REMATCH[1]}"
    elif [[ "$line" =~ ^[[:space:]]+nodes[[:space:]]+(.+) ]]; then
        current_nodes="${BASH_REMATCH[1]}"
    fi
done < "$STORAGE_CFG"
process_block  # handle last block in file

if [[ ${#BROKEN_NAMES[@]} -eq 0 ]]; then
    echo ""
    ok "No broken mountpoint storages found on ${HOSTNAME_SHORT}."
    echo ""
    echo "  Running pvesm status for confirmation:"
    pvesm status
    exit 0
fi

echo ""
warn "${#BROKEN_NAMES[@]} storage(s) need a mount on ${HOSTNAME_SHORT}:"
for i in "${!BROKEN_NAMES[@]}"; do
    echo "    $((i+1)). ${BROKEN_NAMES[$i]}  →  ${BROKEN_PATHS[$i]}"
done

# ── Step 2: Show available disks ──────────────────────────────────────────────

section "Available block devices"

echo ""
echo "  lsblk (sizes and mount points):"
lsblk -o NAME,SIZE,FSTYPE,UUID,MOUNTPOINT | sed 's/^/    /'

echo ""
echo "  blkid (UUIDs for unmounted partitions):"
# Show only partitions that are NOT currently mounted and have a UUID
while IFS= read -r bline; do
    dev="${bline%%:*}"
    if ! findmnt -rn "$dev" > /dev/null 2>&1; then
        echo "    $bline"
    fi
done < <(blkid | sort)

# ── Step 3: Assign a UUID to each broken storage ──────────────────────────────

section "Assign disks to storages"

declare -a CONFIRMED_UUIDS=()
declare -a CONFIRMED_PATHS=()
declare -a CONFIRMED_FSTYPES=()

for i in "${!BROKEN_NAMES[@]}"; do
    name="${BROKEN_NAMES[$i]}"
    path="${BROKEN_PATHS[$i]}"
    echo ""
    info "Storage: ${name}  (${path})"

    # Try to auto-detect: look for a blkid entry whose label or partlabel
    # fuzzy-matches the storage name (common when drives were labelled on setup)
    auto_uuid=""
    auto_fstype=""
    while IFS= read -r bline; do
        dev="${bline%%:*}"
        if findmnt -rn "$dev" > /dev/null 2>&1; then
            continue  # already mounted somewhere, skip
        fi
        if echo "$bline" | grep -qi "LABEL=\"${name}\""; then
            auto_uuid="$(echo "$bline" | grep -oP 'UUID="\K[^"]+')"
            auto_fstype="$(echo "$bline" | grep -oP 'TYPE="\K[^"]+')"
            break
        fi
    done < <(blkid)

    if [[ -n "$auto_uuid" ]]; then
        warn "Possible match by label: UUID=${auto_uuid} (${auto_fstype})"
        if confirm "Use this UUID for ${name}?"; then
            CONFIRMED_UUIDS+=("$auto_uuid")
            CONFIRMED_PATHS+=("$path")
            CONFIRMED_FSTYPES+=("$auto_fstype")
            continue
        fi
    fi

    # Manual entry
    echo "  Enter the UUID for this storage (from blkid output above),"
    echo "  or press Enter to skip this storage."
    read -r -p "  UUID: " input_uuid
    input_uuid="${input_uuid// /}"  # strip accidental spaces

    if [[ -z "$input_uuid" ]]; then
        warn "Skipping ${name}"
        continue
    fi

    # Validate UUID format before touching anything
    if [[ ! "$input_uuid" =~ ^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$ ]]; then
        err "Invalid UUID format: ${input_uuid} — skipping ${name}"
        continue
    fi

    # Look up fstype from blkid for the entered UUID
    detected_fstype="$(blkid | grep -i "UUID=\"${input_uuid}\"" | grep -oP 'TYPE="\K[^"]+' || true)"
    if [[ -n "$detected_fstype" ]]; then
        info "Detected filesystem type: ${detected_fstype}"
        fstype="$detected_fstype"
    else
        warn "Could not detect filesystem type for UUID=${input_uuid}"
        read -r -p "  Filesystem type [ext4]: " input_fstype
        fstype="${input_fstype:-ext4}"
    fi

    CONFIRMED_UUIDS+=("$input_uuid")
    CONFIRMED_PATHS+=("$path")
    CONFIRMED_FSTYPES+=("$fstype")
done

if [[ ${#CONFIRMED_UUIDS[@]} -eq 0 ]]; then
    warn "Nothing to do — all storages were skipped."
    exit 0
fi

# ── Step 4: Review and confirm ────────────────────────────────────────────────

section "Review planned changes"

echo ""
echo "  The following fstab entries will be added and mounted:"
echo ""
for i in "${!CONFIRMED_UUIDS[@]}"; do
    echo "    UUID=${CONFIRMED_UUIDS[$i]} ${CONFIRMED_PATHS[$i]} ${CONFIRMED_FSTYPES[$i]} defaults,nofail 0 2"
done
echo ""

if ! confirm "Proceed?"; then
    warn "Aborted — no changes made."
    exit 0
fi

# ── Step 5: Apply ─────────────────────────────────────────────────────────────

section "Applying changes"

for i in "${!CONFIRMED_UUIDS[@]}"; do
    uuid="${CONFIRMED_UUIDS[$i]}"
    mnt="${CONFIRMED_PATHS[$i]}"
    fst="${CONFIRMED_FSTYPES[$i]}"
    line="UUID=${uuid} ${mnt} ${fst} defaults,nofail 0 2"

    if [[ ! -d "$mnt" ]]; then
        info "Creating directory ${mnt}"
        mkdir -p "$mnt"
    fi

    if grep -qF "UUID=${uuid}" "$FSTAB"; then
        warn "fstab entry already exists for UUID=${uuid}, skipping"
    else
        info "Adding: ${line}"
        echo "$line" >> "$FSTAB"
    fi
done

info "Running systemctl daemon-reload"
systemctl daemon-reload
info "Running mount -a"
mount -a

# ── Step 6: Verify ────────────────────────────────────────────────────────────

section "Results"

echo ""
for i in "${!CONFIRMED_PATHS[@]}"; do
    mnt="${CONFIRMED_PATHS[$i]}"
    if findmnt -rn "$mnt" > /dev/null 2>&1; then
        ok "${mnt}"
    else
        err "${mnt} — still not mounted; check UUID and filesystem type"
    fi
done

echo ""
info "PVE storage status:"
pvesm status
