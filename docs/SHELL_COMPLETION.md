# Shell Completion

All setup scripts support tab completion for bash, zsh, and fish.

## Quick Setup

```bash
pip install argcomplete
python3 setup_completions.py
```

## Supported Scripts

- `setup_workstation_desktop`
- `setup_workstation_dev`
- `setup_server_web`
- `setup_server_dev`
- `setup_server_proxmox`
- `setup_server_lite`
- `setup_pc_dev`
- `patch_setup`
- `recall_setup`
- `reconstruct_setup`
- `webhook_manager`

## Manual Setup

### Bash

```bash
eval "$(register-python-argcomplete setup_workstation_desktop)"
eval "$(register-python-argcomplete setup_server_web)"
```

### Zsh

```bash
eval "$(register-python-argcomplete setup_workstation_desktop)"
eval "$(register-python-argcomplete setup_server_web)"
```

### Fish

```bash
register-python-argcomplete --shell fish setup_workstation_desktop > ~/.config/fish/completions/setup_workstation_desktop.fish
register-python-argcomplete --shell fish setup_server_web > ~/.config/fish/completions/setup_server_web.fish
```

## System-wide Installation

```bash
sudo python3 setup_completions.py --global --shell bash
```
