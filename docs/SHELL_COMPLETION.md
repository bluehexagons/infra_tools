# Shell Completion

The unified `infra-tools` CLI supports full tab completion for Bash, Zsh, and
Fish. `tcsh` is accepted as a compatibility choice but has no generated
completion file; use Bash or Zsh for the complete command surface.

## Quick Setup

```bash
uv tool install --upgrade argcomplete
infra-tools completions
```

This installs completion for the consolidated launcher, including `setup`,
`patch`, `shares`, `recall`, `reconstruct`, `deploy`, `proxmox`, `network`,
`completions`, `python-tools`, and `credentials`.

## Manual Setup

### Bash

```bash
eval "$(register-python-argcomplete infra-tools)"
```

### Zsh

```bash
eval "$(register-python-argcomplete infra-tools)"
```

### Fish

```bash
register-python-argcomplete --shell fish infra-tools > ~/.config/fish/completions/infra-tools.fish
```

## System-wide Installation

```bash
sudo infra-tools completions --global --shell bash
```
