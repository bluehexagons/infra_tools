# Shell Completion

The unified `infra_tools` CLI supports tab completion for Bash, Zsh, and Fish.

## Quick Setup

```bash
uv tool install --upgrade argcomplete
infra_tools completions
```

This installs completion for the consolidated launcher, including `setup`,
`patch`, `shares`, `recall`, `reconstruct`, `deploy`, `proxmox`, `network`,
`completions`, `python-tools`, and `credentials`.

## Manual Setup

### Bash

```bash
eval "$(register-python-argcomplete infra_tools)"
```

### Zsh

```bash
eval "$(register-python-argcomplete infra_tools)"
```

### Fish

```bash
register-python-argcomplete --shell fish infra_tools > ~/.config/fish/completions/infra_tools.fish
```

## System-wide Installation

```bash
sudo infra_tools completions --global --shell bash
```
