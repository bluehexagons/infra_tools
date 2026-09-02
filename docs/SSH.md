# SSH authentication

`infra-tools` uses the system OpenSSH client for remote commands, uploads,
Proxmox operations, rsync transfers, and sshfs mounts. A configured `--key`
is passed to OpenSSH as an identity file; infra-tools never needs to store or
receive the key's passphrase.

## Password-protected private keys

When a command is started from a terminal, SSH is allowed to ask for the
private-key passphrase. This applies to setup and patch handoffs, Proxmox
commands, agent authentication and pairing, maintenance, transfers, and the
sysadmin shortcuts. A passphrase prompt can still appear while command output
is captured because OpenSSH uses the controlling terminal for authentication.
Interactive SSH subprocesses do not use the automation wall-clock timeout,
because it cannot distinguish time spent at that prompt from remote execution.
A newly provisioned guest can therefore wait for its setup key without the
operator watching the entire provisioning phase. If the SSH server closes an
interactive connection while setup is waiting at the remote-sudo verification
prompt, setup opens one fresh connection so the operator can enter the key
passphrase again. SSH connection establishment still has its own timeout, and
the command remains interruptible with Ctrl-C.

Commands started without a terminal—such as piped setup, automation, and
parallel host checks—cannot safely ask several processes for a passphrase. In
that case infra-tools enables OpenSSH batch mode and retains bounded operation
timeouts. Load the key into an SSH agent before starting the command:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
ssh-add -l

infra-tools setup workstation_dev 192.0.2.40 admin --key ~/.ssh/id_ed25519
```

The agent keeps the decrypted key in memory and does not save the passphrase
to disk. `ssh-add` prompts once in the terminal, after which all infra-tools
SSH subprocesses inherit `SSH_AUTH_SOCK` and can authenticate without another
prompt. The agent must remain running for later commands; a new shell, reboot,
or agent restart may require `ssh-add` again.

For a desktop login, use the desktop's SSH-agent or keyring integration when
available. For unattended services, prefer a dedicated deployment key with
the narrowest authorized-key restrictions practical, or arrange an explicitly
managed agent environment. Do not put a passphrase in a command line,
repository, setup cache, systemd unit, or shell script.

## Repeated and parallel operations

Proxmox inspection and maintenance commands use a short-lived OpenSSH control
connection, so the first authenticated connection can be reused by subsequent
checks and by the streamed cloud-init or public-key uploads used during guest
provisioning. This reduces repeated prompts, but it does not replace an agent
for parallel operations such as `fan`, `df`, or `reachable`. Preload the key
when a command can open more than one SSH connection at a time.

The same terminal-aware behavior is used by SCP, rsync-over-SSH, SSHFS, and
other SSH uploads. A hosted setup may still prompt once for the Proxmox
identity and once for a different guest identity; loading both keys into the
agent avoids both prompts. SSHFS mounts may detach or reconnect after the
original terminal is gone, so an agent is the reliable choice for a long-lived
mount.

The managed UFW policy rate-limits SSH only when no inbound access sources are
declared. When `--lan-access` or `--access-source` identifies trusted management
networks, those source-restricted SSH rules allow connection bursts used by
setup, transfers, and host-key enrollment. SSH remains key-only and protected
by fail2ban. Rerunning setup migrates older source-specific `LIMIT` rules to
the trusted-source `ALLOW` policy without opening global SSH access.

Proxmox guests are a special host-key enrollment case. After provisioning,
infra-tools scans the guest's ED25519 key from the authenticated Proxmox node,
replaces any stale plain or hashed entry for that address in both the workspace
`known_hosts` and the invoking user's default `~/.ssh/known_hosts`, and then
uses strict checking for the direct guest connection. It also refreshes both
files before every setup rerun for a cached managed guest whose saved
infra-tools metadata matches the address, machine type, and Proxmox node. This
cleans up stale trust left by older or recreated managed guests before either
infra-tools or plain `ssh HOST` performs a strict check. Existing guests
without that matching saved identity are not enrolled automatically; enroll
those explicitly with `infra-tools ssh-key enroll` after verifying the
displayed fingerprint. Proxmox node and guest connections both use strict
checking against the workspace `known_hosts` file.
Explicit enrollment scans only the ED25519 key, avoiding a burst of parallel
probe connections against hosts that enforce SSH connection-rate limits.
The explicit enrollment command does not modify OpenSSH's default
`~/.ssh/known_hosts`; plain `ssh HOST` continues to use that separate file
unless setup has reconciled a matching managed Proxmox guest or the user's SSH
configuration selects the infra-tools workspace file.

Hosted VM setup also needs the guest setup account to run privileged staging
commands. The upload itself uses SSH standard input for a tar stream, so
infra-tools never lets a remote `sudo` prompt consume that stream. It checks
`sudo -n` and requires passwordless sudo for the setup account. Authenticating
with `sudo -v` in a separate SSH terminal is not sufficient because normal
sudo credential caches are scoped to a terminal or parent process.
Proxmox VM cloud-init installs that rule as
`/etc/sudoers.d/infra-tools-USERNAME`, owned by `root:root` with mode `0440`.
The normal VM setup flow removes that bootstrap rule before completion. Pass
`--nopasswd` to validate and retain it for compatibility with non-root reruns.
Without that flag, rerun setup through the retained key-only root SSH account;
the configured user remains in `sudo`, but sudo requires its password.
`--harden-agent` also removes the configured user from the `sudo` group.
It also reconciles other administrator and root-equivalent supplementary
groups. `--harden-user` implies that policy, locks Unix password
authentication even when the account previously had no password, makes the
home directory private, and removes sensitive system-data and device groups
while leaving authorized-key shell SSH usable. It also disables SSH agent,
TCP, Unix-socket, X11, and tunnel forwarding for that identity and prevents
`~/.ssh/rc` execution. A later root-driven setup with
`--no-harden-user --no-harden-agent` restores the account settings that
infra-tools recorded before the lockdown and removes those per-user SSH
restrictions.
For an existing VM that was not provisioned by infra-tools, grant the setup
account the intended `NOPASSWD` sudo rule before the first setup or connect as
root. The temporary managed rule is removed unless `--nopasswd` is selected.
No sudo password is accepted, stored, passed in the archive, or written to the
setup cache.

## Troubleshooting

Check which agent is active and whether it has the expected identity:

```bash
printf '%s\n' "${SSH_AUTH_SOCK:-no SSH agent socket}"
ssh-add -l
```

If a terminal command still fails, test the same identity directly without
forcing batch mode:

```bash
ssh -o BatchMode=no -i ~/.ssh/id_ed25519 admin@host true
```

If the command is being piped or run from a service, do not try to provide the
passphrase through standard input—the remote command or uploaded payload may
already be using it. Load the identity into the agent visible to that process
instead. A failure that says `Permission denied (publickey)` in a
non-interactive run commonly means that the key was not loaded into that
agent, or that the process received a different `SSH_AUTH_SOCK`.
