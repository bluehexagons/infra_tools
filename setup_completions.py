#!/usr/bin/env python3
"""Setup shell tab completion for infra_tools scripts.

This script helps users enable tab completion for all infra_tools commands.
Supports bash, zsh, fish, and tcsh shells.

Usage:
    python3 setup_completions.py [--shell bash|zsh|fish|tcsh] [--global|--user]
    
Examples:
    # Enable for current shell (auto-detected)
    python3 setup_completions.py
    
    # Enable for specific shell
    python3 setup_completions.py --shell zsh
    
    # Enable system-wide (requires sudo)
    sudo python3 setup_completions.py --global
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

try:
    import argcomplete
except ImportError:
    argcomplete = None

# List of all infra_tools entry points
INFRA_TOOLS_SCRIPTS = [
    "setup_workstation_desktop",
    "setup_workstation_dev",
    "setup_server_web",
    "setup_server_dev",
    "setup_server_proxmox",
    "setup_server_lite",
    "setup_pc_dev",
    "patch_setup",
    "recall_setup",
    "reconstruct_setup",
    "webhook_manager",
]


def detect_shell() -> str:
    """Detect the current shell from environment."""
    shell = os.environ.get("SHELL", "")
    if "bash" in shell:
        return "bash"
    elif "zsh" in shell:
        return "zsh"
    elif "fish" in shell:
        return "fish"
    elif "tcsh" in shell:
        return "tcsh"
    return "bash"  # default


def get_bash_config_file() -> Path:
    """Get the appropriate bash config file."""
    # Check for .bashrc first, then .bash_profile, then .profile
    home = Path.home()
    for filename in [".bashrc", ".bash_profile", ".profile"]:
        path = home / filename
        if path.exists():
            return path
    return home / ".bashrc"


def get_zsh_config_file() -> Path:
    """Get the appropriate zsh config file."""
    home = Path.home()
    zshrc = home / ".zshrc"
    if zshrc.exists():
        return zshrc
    return home / ".zshrc"


def get_fish_config_dir() -> Path:
    """Get fish configuration directory."""
    config_dir = Path.home() / ".config" / "fish"
    return config_dir


def setup_bash_completions(global_install: bool = False) -> bool:
    """Setup bash completions for infra_tools."""
    if not argcomplete:
        print("Error: argcomplete is not installed. Install it with:")
        print("  pip install argcomplete")
        return False
    
    try:
        # Get the register-python-argcomplete command
        result = subprocess.run(
            ["which", "register-python-argcomplete"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            print("Error: register-python-argcomplete not found in PATH")
            print("Make sure argcomplete is installed: pip install argcomplete")
            return False
        
        register_cmd = result.stdout.strip()
        
        if global_install:
            # System-wide bash completion
            completions_dir = Path("/etc/bash_completion.d")
            if not completions_dir.exists():
                print(f"Error: {completions_dir} does not exist")
                print("System-wide installation requires bash-completion package")
                return False
            
            for script in INFRA_TOOLS_SCRIPTS:
                completion_file = completions_dir / f"{script}"
                try:
                    result = subprocess.run(
                        [register_cmd, script],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        completion_file.write_text(result.stdout)
                        print(f"  Created: {completion_file}")
                    else:
                        print(f"  Error creating completion for {script}: {result.stderr}")
                        return False
                except Exception as e:
                    print(f"  Error: {e}")
                    return False
            
            print(f"\nSystem-wide bash completions installed in {completions_dir}")
            print("New shells will have tab completion enabled automatically.")
        else:
            # User-specific installation
            config_file = get_bash_config_file()
            
            # Check if already configured
            if config_file.exists():
                content = config_file.read_text()
                if "argcomplete" in content and any(s in content for s in INFRA_TOOLS_SCRIPTS):
                    print(f"Completions already configured in {config_file}")
                    return True
            
            # Add completion evals to bashrc
            lines = ["# infra_tools shell completions"]
            for script in INFRA_TOOLS_SCRIPTS:
                lines.append(f'eval "$(register-python-argcomplete {script})"')
            
            with open(config_file, "a") as f:
                f.write("\n" + "\n".join(lines) + "\n")
            
            print(f"Added completions to {config_file}")
            print("Run 'source {0}' or restart your shell to enable completions.".format(config_file))
        
        return True
    except Exception as e:
        print(f"Error setting up bash completions: {e}")
        return False


def setup_zsh_completions(global_install: bool = False) -> bool:
    """Setup zsh completions for infra_tools."""
    if not argcomplete:
        print("Error: argcomplete is not installed. Install it with:")
        print("  pip install argcomplete")
        return False
    
    try:
        result = subprocess.run(
            ["which", "register-python-argcomplete"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            print("Error: register-python-argcomplete not found in PATH")
            return False
        
        register_cmd = result.stdout.strip()
        
        if global_install:
            # Try to find zsh site-functions
            try:
                result = subprocess.run(
                    ["zsh", "-c", "echo $fpath"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    fpaths = result.stdout.strip().split()
                    for fp in fpaths:
                        if "site-functions" in fp and Path(fp).exists():
                            completions_dir = Path(fp)
                            break
                    else:
                        print("Error: Could not find zsh site-functions directory")
                        return False
                else:
                    print("Error: Could not determine zsh fpath")
                    return False
            except Exception as e:
                print(f"Error: {e}")
                return False
            
            for script in INFRA_TOOLS_SCRIPTS:
                completion_file = completions_dir / f"_{script}"
                try:
                    result = subprocess.run(
                        [register_cmd, "--shell", "zsh", script],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        completion_file.write_text(result.stdout)
                        print(f"  Created: {completion_file}")
                    else:
                        print(f"  Error creating completion for {script}: {result.stderr}")
                except Exception as e:
                    print(f"  Error: {e}")
            
            print(f"\nZsh completions installed in {completions_dir}")
            print("You may need to run 'compinit' or restart your shell.")
        else:
            config_file = get_zsh_config_file()
            
            # Check if already configured
            if config_file.exists():
                content = config_file.read_text()
                if "argcomplete" in content and any(s in content for s in INFRA_TOOLS_SCRIPTS):
                    print(f"Completions already configured in {config_file}")
                    return True
            
            # Add completion evals to zshrc
            lines = ["# infra_tools shell completions"]
            for script in INFRA_TOOLS_SCRIPTS:
                lines.append(f'eval "$(register-python-argcomplete {script})"')
            
            with open(config_file, "a") as f:
                f.write("\n" + "\n".join(lines) + "\n")
            
            print(f"Added completions to {config_file}")
            print("Run 'source {0}' or restart your shell to enable completions.".format(config_file))
        
        return True
    except Exception as e:
        print(f"Error setting up zsh completions: {e}")
        return False


def setup_fish_completions(global_install: bool = False) -> bool:
    """Setup fish completions for infra_tools."""
    if not argcomplete:
        print("Error: argcomplete is not installed. Install it with:")
        print("  pip install argcomplete")
        return False
    
    try:
        result = subprocess.run(
            ["which", "register-python-argcomplete"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            print("Error: register-python-argcomplete not found in PATH")
            return False
        
        register_cmd = result.stdout.strip()
        
        config_dir = get_fish_config_dir()
        completions_dir = config_dir / "completions"
        completions_dir.mkdir(parents=True, exist_ok=True)
        
        for script in INFRA_TOOLS_SCRIPTS:
            completion_file = completions_dir / f"{script}.fish"
            try:
                result = subprocess.run(
                    [register_cmd, "--shell", "fish", script],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    completion_file.write_text(result.stdout)
                    print(f"  Created: {completion_file}")
                else:
                    print(f"  Error creating completion for {script}: {result.stderr}")
            except Exception as e:
                print(f"  Error: {e}")
        
        print(f"\nFish completions installed in {completions_dir}")
        print("Completions are active immediately in new fish shells.")
        return True
    except Exception as e:
        print(f"Error setting up fish completions: {e}")
        return False


def setup_tcsh_completions(global_install: bool = False) -> bool:
    """Setup tcsh completions for infra_tools."""
    print("Note: tcsh completion support is limited.")
    print("Consider using bash or zsh for full tab completion support.")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Setup shell tab completion for infra_tools scripts"
    )
    parser.add_argument(
        "--shell",
        choices=["bash", "zsh", "fish", "tcsh", "auto"],
        default="auto",
        help="Shell type (default: auto-detect)"
    )
    parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Install completions system-wide (requires sudo/root)"
    )
    parser.add_argument(
        "--user",
        action="store_true",
        help="Install completions for current user only (default)"
    )
    
    if argcomplete:
        argcomplete.autocomplete(parser)
    
    args = parser.parse_args()
    
    # Determine shell
    shell = args.shell
    if shell == "auto":
        shell = detect_shell()
        print(f"Detected shell: {shell}")
    
    # Check for root if global install
    if args.global_install and os.geteuid() != 0:
        print("Error: Global installation requires root privileges")
        print("Run with: sudo python3 setup_completions.py --global")
        return 1
    
    print(f"\nSetting up {shell} completions...")
    if args.global_install:
        print("(system-wide installation)\n")
    else:
        print("(user installation)\n")
    
    # Setup completions based on shell
    setup_funcs = {
        "bash": setup_bash_completions,
        "zsh": setup_zsh_completions,
        "fish": setup_fish_completions,
        "tcsh": setup_tcsh_completions,
    }
    
    if shell in setup_funcs:
        success = setup_funcs[shell](args.global_install)
        if success:
            print("\nTo use completions immediately, run:")
            print('  eval "$(register-python-argcomplete setup_workstation_desktop)"')
            print("\nOr restart your shell.")
            return 0
        else:
            return 1
    else:
        print(f"Error: Unsupported shell '{shell}'")
        print("Supported shells: bash, zsh, fish, tcsh")
        return 1


if __name__ == "__main__":
    sys.exit(main())
