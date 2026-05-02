# Shell Completion

The unified `infra_tools.py` CLI supports tab completion for bash, zsh, and fish.

## Quick Setup

```bash
uv tool install --upgrade argcomplete
python3 infra_tools.py completions
```

This installs completion for the single consolidated `infra_tools.py` entry point, including subcommands such as
`setup`, `patch`, `recall`, `reconstruct`, `completions`, `python-tools`, and `credentials`.

## Manual Setup

### Bash

```bash
eval "$(register-python-argcomplete infra_tools.py)"
```

### Zsh

```bash
eval "$(register-python-argcomplete infra_tools.py)"
```

### Fish

```bash
register-python-argcomplete --shell fish infra_tools.py > ~/.config/fish/completions/infra_tools.py.fish
```

## System-wide Installation

```bash
sudo python3 infra_tools.py completions --global --shell bash
```
