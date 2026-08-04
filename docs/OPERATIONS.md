# Saved configuration operations

infra_tools stores setup arguments, host metadata, credentials, run status, and
history under the active workspace. These commands operate on saved
configurations without requiring a new setup command line each time.

## Inspect saved hosts

```bash
infra_tools list
infra_tools list production
infra_tools info production
infra_tools list --json
infra_tools info --compact
infra_tools cmd production
```

`list` filters by host, friendly name, or tag. `info` shows configuration and
last-run status. `cmd` reconstructs a safe, redacted setup command.

## Patch and redeploy

`patch` merges targeted options into the saved configuration and executes the
remote setup flow:

```bash
infra_tools patch production --ssl --ssl-email admin@example.com
infra_tools patch production --deploy api.example.com https://github.com/user/api.git
```

Use `deploy` to rerun saved configurations:

```bash
infra_tools deploy production
infra_tools deploy production --yes
```

Some capabilities have narrower fast paths. Use
[Samba share updates](SAMBA_SHARES.md#fast-share-only-updates) to update Samba
without running unrelated setup work.

## Recall and reconstruction

```bash
infra_tools recall example.com admin
infra_tools recall example.com admin --key ~/.ssh/id_ed25519
infra_tools reconstruct
```

`reconstruct` analyzes the current host; `recall` targets a remote host.

## Remove saved configurations

Removal affects workspace metadata only; it does not uninstall software from a
target:

```bash
infra_tools rm old-server
infra_tools rm old-server --yes
```

## Interactive shell

```bash
infra_tools shell
```

Useful commands include `list`, `info`, `cmd`, `new`, `setup`, `deploy`, `rm`,
`recall`, `workspace`, and `proxmox`. Startup commands can be placed in
`~/.infra_toolsrc`; history is stored at `~/.local/share/infra_tools/shell_history`.

## Testing

```bash
python3 -m unittest discover -s tests
./run_tests.py
./run_tests.py --suite smoke
./run_tests.py --list-suites
./run_tests.py --list-categories
./run_tests.py --durations 20
```

Live Proxmox and other expensive tests are opt-in. See
[`tests/expensive_support.py`](../tests/expensive_support.py) and
[Proxmox workflows](PROXMOX.md) for environment-specific requirements.
