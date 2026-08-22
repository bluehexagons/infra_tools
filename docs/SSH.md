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
operator watching the entire provisioning phase. SSH connection establishment
still has its own timeout, and the command remains interruptible with Ctrl-C.

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

Proxmox guests are a special host-key enrollment case. After provisioning,
infra-tools scans the guest's ED25519 key from the authenticated Proxmox node,
replaces any stale entry for that address in the workspace `known_hosts`, and
then uses strict checking for the direct guest connection. It also refreshes
the key when a provisioning recheck confirms an existing guest whose saved
infra-tools metadata matches the address, machine type, and Proxmox node.
Existing guests without that matching saved identity are not enrolled
automatically; enroll those explicitly with `infra-tools ssh-key enroll` after
verifying the displayed fingerprint. Proxmox node and guest connections both
use strict checking against the workspace `known_hosts` file.

Hosted VM setup also needs the guest setup account to run privileged staging
commands. The upload itself uses SSH standard input for a tar stream, so
infra-tools never lets a remote `sudo` prompt consume that stream. It checks
`sudo -n` and requires passwordless sudo for the setup account. Authenticating
with `sudo -v` in a separate SSH terminal is not sufficient because normal
sudo credential caches are scoped to a terminal or parent process.
Proxmox VM cloud-init installs that rule as
`/etc/sudoers.d/infra-tools-USERNAME`, owned by `root:root` with mode `0440`.
The normal VM setup flow validates and repairs that drop-in on reruns, so an
older file with overly broad permissions is corrected automatically.
For an existing VM that was not provisioned by infra-tools, grant the setup
account the intended `NOPASSWD` sudo rule before setup. No sudo password is
accepted, stored, passed in the archive, or written to the setup cache.

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
