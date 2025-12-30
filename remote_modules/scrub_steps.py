"""Data integrity checking with par2 and systemd timers."""

import os
import shlex
import hashlib
from typing import List

from lib.config import SetupConfig
from lib.setup_common import REMOTE_INSTALL_DIR
from .utils import run, is_package_installed
from shared.mount_utils import is_path_under_mnt, get_mount_ancestor


def install_par2(config: SetupConfig) -> None:
    """Install par2cmdline if not already installed."""
    if is_package_installed("par2"):
        print("  ✓ par2 already installed")
        return
    
    run("apt-get install -y -qq par2")
    print("  ✓ par2 installed")


def parse_scrub_spec(scrub_spec: List[str]) -> dict:
    """Parse scrub specification.
    
    Args:
        scrub_spec: [directory, database_path, redundancy, frequency]
        
    Returns:
        dict with 'directory', 'database_path', 'redundancy', 'frequency'
    """
    if len(scrub_spec) != 4:
        raise ValueError(f"Invalid scrub spec: expected 4 arguments, got {len(scrub_spec)}")
    
    directory, database_path, redundancy, frequency = scrub_spec
    
    # Validate that directory is absolute
    if not directory.startswith('/'):
        raise ValueError(f"Directory path must be absolute: {directory}")
    
    # Resolve database_path - can be relative or absolute
    if not database_path.startswith('/'):
        # Relative path - resolve relative to directory
        database_path = os.path.join(directory, database_path)
    
    # Normalize the database path
    database_path = os.path.normpath(database_path)
    
    # Validate redundancy format (e.g., "5%")
    if not redundancy.endswith('%'):
        raise ValueError(f"Redundancy must end with '%': {redundancy}")
    try:
        redundancy_value = int(redundancy[:-1])
        if redundancy_value < 1 or redundancy_value > 100:
            raise ValueError(f"Redundancy percentage must be between 1 and 100: {redundancy}")
    except ValueError as e:
        if "invalid literal" in str(e):
            raise ValueError(f"Invalid redundancy format: {redundancy}")
        raise
    
    # Validate frequency
    valid_frequencies = ['hourly', 'daily', 'weekly', 'monthly']
    if frequency not in valid_frequencies:
        raise ValueError(f"Invalid frequency '{frequency}'. Must be one of: {', '.join(valid_frequencies)}")
    
    return {
        'directory': directory,
        'database_path': database_path,
        'redundancy': redundancy,
        'frequency': frequency
    }


def _check_path_on_smb_mount(path: str, config: SetupConfig) -> bool:
    """Check if path is on an SMB mount."""
    if not config.smb_mounts:
        return False
    for mount_spec in config.smb_mounts:
        mountpoint = mount_spec[0]
        if path.startswith(mountpoint + '/') or path == mountpoint:
            return True
    return False


def _escape_systemd_description(value: str) -> str:
    """Escape value for safe use in a systemd Description field."""
    return value.replace("\\", "\\\\").replace("\n", " ").replace('"', "'")


def get_timer_calendar(frequency: str) -> str:
    """Get systemd timer OnCalendar value for the given frequency.
    
    Args:
        frequency: 'hourly', 'daily', 'weekly', or 'monthly'
        
    Returns:
        OnCalendar string for systemd timer
    """
    calendars = {
        'hourly': '*-*-* *:00:00',  # Every hour on the hour
        'daily': '*-*-* 03:00:00',   # Daily at 3 AM (different from sync to avoid conflicts)
        'weekly': 'Sun *-*-* 03:00:00',  # Sunday at 3 AM
        'monthly': '*-*-01 03:00:00'  # First day of month at 3 AM
    }
    return calendars.get(frequency, '*-*-* 03:00:00')


def create_scrub_service(config: SetupConfig, scrub_spec: List[str] = None, **_) -> None:
    """Create par2 systemd service and timer for data integrity checking.
    
    Args:
        config: SetupConfig object
        scrub_spec: [directory, database_path, redundancy, frequency]
    """
    scrub_config = parse_scrub_spec(scrub_spec)
    
    directory = scrub_config['directory']
    database_path = scrub_config['database_path']
    redundancy = scrub_config['redundancy']
    frequency = scrub_config['frequency']
    
    # Create a unique name for the service using hash to avoid collisions
    path_hash = hashlib.md5(f"{directory}:{database_path}".encode()).hexdigest()[:8]
    safe_dir = directory.replace('/', '_').strip('_')
    service_name = f"scrub-{safe_dir}-{path_hash}"
    
    # Ensure directory exists (but don't create under /mnt if not mounted)
    if not os.path.exists(directory):
        if is_path_under_mnt(directory):
            # Check if any parent is mounted
            mount_ancestor = get_mount_ancestor(directory)
            if not mount_ancestor:
                print(f"  ⚠ Warning: Directory {directory} is under /mnt but no mount point found")
                print(f"    Skipping directory creation - ensure mount is configured first")
            else:
                # Parent is mounted, safe to create subdirectory
                print(f"    Creating subdirectory under mount: {directory}")
                os.makedirs(directory, exist_ok=True)
                run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(directory)}")
        else:
            print(f"  ⚠ Warning: Directory does not exist: {directory}")
            print(f"    Creating directory: {directory}")
            os.makedirs(directory, exist_ok=True)
            run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(directory)}")
    
    # Ensure database parent directory exists (but don't create under /mnt if not mounted)
    db_parent = os.path.dirname(database_path)
    if db_parent and not os.path.exists(db_parent):
        if is_path_under_mnt(db_parent):
            # Check if any parent is mounted
            mount_ancestor = get_mount_ancestor(db_parent)
            if not mount_ancestor:
                print(f"  ⚠ Warning: Database parent {db_parent} is under /mnt but no mount point found")
                print(f"    Skipping directory creation - ensure mount is configured first")
            else:
                # Parent is mounted, safe to create subdirectory
                print(f"    Creating database directory under mount: {db_parent}")
                os.makedirs(db_parent, exist_ok=True)
                run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(db_parent)}")
        else:
            print(f"    Creating database directory: {db_parent}")
            os.makedirs(db_parent, exist_ok=True)
            run(f"chown {shlex.quote(config.username)}:{shlex.quote(config.username)} {shlex.quote(db_parent)}")
    
    # Escape paths for systemd description
    escaped_directory = _escape_systemd_description(directory)
    escaped_database = _escape_systemd_description(database_path)
    
    # Check if directory or database path needs mount validation
    dir_on_smb = _check_path_on_smb_mount(directory, config)
    db_on_smb = _check_path_on_smb_mount(database_path, config)
    dir_under_mnt = is_path_under_mnt(directory)
    db_under_mnt = is_path_under_mnt(database_path)
    
    # Need mount checks if on SMB mount or under /mnt
    needs_mount_check = dir_on_smb or db_on_smb or dir_under_mnt or db_under_mnt
    
    # Create scrub script
    script_path = f"/usr/local/bin/{service_name}.sh"
    
    # Script to create/update par2 files and verify/repair
    # The script should:
    # 1. Create par2 files for new files (if they don't have .par2)
    # 2. Verify existing files
    # 3. Repair if needed
    # 4. Log results
    
    log_dir = f"/var/log/scrub"
    log_file = f"{log_dir}/{service_name}.log"
    
    # Create log directory
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    script_content = f"""#!/bin/bash
set -e

DIRECTORY={shlex.quote(directory)}
DATABASE={shlex.quote(database_path)}
REDUNDANCY={shlex.quote(redundancy[:-1])}  # Remove % sign
LOG_FILE={shlex.quote(log_file)}

# Ensure database directory exists
mkdir -p "$DATABASE"

echo "========================================" >> "$LOG_FILE"
echo "Scrub started: $(date)" >> "$LOG_FILE"
echo "Directory: $DIRECTORY" >> "$LOG_FILE"
echo "Database: $DATABASE" >> "$LOG_FILE"
echo "Redundancy: $REDUNDANCY%" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# Function to create par2 for a file
create_par2() {{
    local file="$1"
    local relative_path="${{file#$DIRECTORY/}}"
    local par2_base="$DATABASE/${{relative_path}}.par2"
    
    # Check if par2 already exists
    if [ ! -f "${{par2_base}}" ]; then
        echo "Creating par2 for: $relative_path" >> "$LOG_FILE"
        mkdir -p "$(dirname "$par2_base")"
        par2 create -r"$REDUNDANCY" -n1 "$par2_base" "$file" >> "$LOG_FILE" 2>&1 || echo "Error creating par2 for $relative_path" >> "$LOG_FILE"
    fi
}}

# Function to verify/repair a file
verify_repair() {{
    local file="$1"
    local relative_path="${{file#$DIRECTORY/}}"
    local par2_base="$DATABASE/${{relative_path}}.par2"
    
    if [ -f "${{par2_base}}" ]; then
        echo "Verifying: $relative_path" >> "$LOG_FILE"
        if ! par2 verify "$par2_base" >> "$LOG_FILE" 2>&1; then
            echo "Verification failed for: $relative_path" >> "$LOG_FILE"
            echo "Attempting repair..." >> "$LOG_FILE"
            if par2 repair "$par2_base" >> "$LOG_FILE" 2>&1; then
                echo "✓ Repaired: $relative_path" >> "$LOG_FILE"
            else
                echo "✗ Repair failed: $relative_path" >> "$LOG_FILE"
            fi
        fi
    fi
}}

# Process all files in directory
find "$DIRECTORY" -type f ! -path "$DATABASE/*" -print0 | while IFS= read -r -d '' file; do
    create_par2 "$file"
    verify_repair "$file"
done

echo "Scrub completed: $(date)" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
"""
    
    with open(script_path, 'w') as f:
        f.write(script_content)
    
    # Make script executable
    run(f"chmod +x {shlex.quote(script_path)}")
    
    print(f"  ✓ Created scrub script: {script_path}")
    
    # Create systemd service file
    service_file = f"/etc/systemd/system/{service_name}.service"
    
    if needs_mount_check:
        # Use Python script for mount checking
        check_script = f"{REMOTE_INSTALL_DIR}/check_scrub_mounts.py"
        
        service_content = f"""[Unit]
Description=Data integrity check for {escaped_directory}
After=local-fs.target

[Service]
Type=oneshot
User=root
Group=root
ExecCondition=/usr/bin/python3 {check_script} {shlex.quote(directory)} {shlex.quote(database_path)}
ExecStart={shlex.quote(script_path)}
StandardOutput=journal
StandardError=journal
"""
    else:
        service_content = f"""[Unit]
Description=Data integrity check for {escaped_directory}
After=local-fs.target

[Service]
Type=oneshot
User=root
Group=root
ExecStart={shlex.quote(script_path)}
StandardOutput=journal
StandardError=journal
"""
    
    with open(service_file, 'w') as f:
        f.write(service_content)
    
    print(f"  ✓ Created service: {service_name}.service")
    
    # Create systemd timer file
    timer_file = f"/etc/systemd/system/{service_name}.timer"
    calendar = get_timer_calendar(frequency)
    
    timer_content = f"""[Unit]
Description=Timer for data integrity check of {escaped_directory} ({frequency})
Requires={service_name}.service

[Timer]
OnCalendar={calendar}
Persistent=true
AccuracySec=1m

[Install]
WantedBy=timers.target
"""
    
    with open(timer_file, 'w') as f:
        f.write(timer_content)
    
    print(f"  ✓ Created timer: {service_name}.timer ({frequency})")
    
    # Reload systemd, enable and start the timer
    run("systemctl daemon-reload")
    run(f"systemctl enable {shlex.quote(service_name)}.timer")
    run(f"systemctl start {shlex.quote(service_name)}.timer")
    
    print(f"  ✓ Enabled and started timer")
    
    # Show timer status
    result = run(f"systemctl list-timers {shlex.quote(service_name)}.timer --no-pager", check=False)
    if result.returncode == 0:
        print(f"  ℹ Timer status:")
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                print(f"    {line}")
    
    # Perform initial scrub (only create new par2 files, don't verify to keep it fast)
    print(f"  ℹ Performing initial par2 creation (fast mode)...")
    
    # Create a faster initial script that only creates par2 files without verification
    init_script = f"""#!/bin/bash
DIRECTORY={shlex.quote(directory)}
DATABASE={shlex.quote(database_path)}
REDUNDANCY={shlex.quote(redundancy[:-1])}

mkdir -p "$DATABASE"

find "$DIRECTORY" -type f ! -path "$DATABASE/*" -print0 | while IFS= read -r -d '' file; do
    relative_path="${{file#$DIRECTORY/}}"
    par2_base="$DATABASE/${{relative_path}}.par2"
    
    if [ ! -f "${{par2_base}}" ]; then
        mkdir -p "$(dirname "$par2_base")"
        par2 create -r"$REDUNDANCY" -n1 "$par2_base" "$file" >/dev/null 2>&1 || true
    fi
done
"""
    
    init_script_path = f"/tmp/{service_name}-init.sh"
    with open(init_script_path, 'w') as f:
        f.write(init_script)
    run(f"chmod +x {shlex.quote(init_script_path)}")
    
    result = run(init_script_path, check=False)
    run(f"rm {shlex.quote(init_script_path)}")
    
    if result.returncode == 0:
        print(f"  ✓ Initial par2 creation completed")
    else:
        print(f"  ⚠ Warning: Initial par2 creation may have encountered issues")
    
    print(f"  ✓ Scrub configured: {directory} (redundancy: {redundancy}, frequency: {frequency})")
    print(f"  ℹ Logs: {log_file}")
