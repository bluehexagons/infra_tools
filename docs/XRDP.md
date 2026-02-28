# XRDP Configuration and Troubleshooting

This document describes the XRDP setup, known issues, and troubleshooting procedures for remote desktop sessions.

## Overview

The infra_tools XRDP setup is optimized for:
- **Dynamic resolution support** - Window resizing without reconnection
- **Security** - TLS encryption, group-based access control
- **Stability** - XFCE desktop environment with RDP-compatible configuration
- **Simplicity** - No audio support (removed to reduce complexity)

## Architecture

### Backend: Xorg + xorgxrdp

We use **Xorg with xorgxrdp driver** exclusively, not Xvnc:
- ✅ **xorgxrdp**: Emits proper RANDR events for dynamic resolution
- ❌ **Xvnc**: Does not emit RRScreenChangeNotify events, causes freezes on resize

### Key Configuration Files

| File | Purpose | Location |
|------|---------|----------|
| `sesman.ini` | Session manager config | `/etc/xrdp/sesman.ini` |
| `xrdp.ini` | RDP protocol settings | `/etc/xrdp/xrdp.ini` |
| `xorg.conf` | X server configuration | `/etc/X11/xrdp/xorg.conf` |
| `Xwrapper.config` | X server permissions | `/etc/X11/Xwrapper.config` |
| `startwm.sh` | Session startup script | `~/startwm.sh` |

### Session Startup Script

Located at `~/startwm.sh`, this script:

1. Sets XRDP-specific environment variables:
   - `XRDP_SESSION=1` - Indicates RDP session to applications
   - `XFCE_DISABLE_DISPLAY_MANAGEMENT=1` - Prevents XFCE from managing displays

2. Disables X screen saver and DPMS via `xset` commands

3. Launches the desktop environment through dbus-launch

**Note:** The script explicitly disables display management because xorgxrdp handles RANDR events natively. Any additional display management scripts or manual refresh mechanisms will cause session freezing.

## Configuration Details

### Xwrapper.config

**Critical for preventing session freezes:**

```ini
allowed_users=anybody
needs_root_rights=no
```

Without this, XRDP sessions cannot start X server, causing:
- Permission errors in logs
- Black screen on connect
- Immediate disconnects
- Session freezes

### XFCE RDP Compatibility

The `configure_xfce_for_rdp()` function disables components that interfere with RDP sessions:

1. **light-locker** - Screen locker (crashes without display manager)
2. **xfsettingsd** - Settings daemon (interferes with RANDR events - CRITICAL for dynamic resolution)
3. **DPMS** - Display power management (no hardware in RDP)
4. **xfce4-power-manager** - Power management features
5. **Invalid autostart entries** - Removed to prevent startup errors

**Critical:** xfsettingsd's display management is disabled because it conflicts with xorgxrdp's RANDR event handling. This is the most common cause of session freezes on resize.

### X.Org Configuration

```ini
Section "Device"
    Driver "xrdpdev"
    Option "UseGlamor" "false"  # Disabled to prevent resize crashes
    Option "SWCursor" "true"      # Software cursor for stability
EndSection

Section "Screen"
    Virtual 3840 2160  # Max resolution for dynamic resizing (4K support)
EndSection

Section "ServerFlags"
    # Disable screen saver and DPMS to prevent conflicts with XRDP
    Option "StandbyTime" "0"
    Option "SuspendTime" "0"
    Option "OffTime" "0"
    Option "BlankTime" "0"
EndSection
```

**Key Changes:**
- **Glamor disabled** - Prevents GPU-related crashes during resolution changes
- **Software cursor (SWCursor)** - Avoids cursor rendering issues during resize
- **4K virtual screen** - Supports up to 3840x2160 resolution
- **DPMS/Screensaver disabled** - Prevents X server from managing display state

### Network Optimization

```ini
tcp_send_buffer_bytes=65536  # Increased from 32KB
tcp_recv_buffer_bytes=65536  # Increased from 32KB
tcp_nodelay=true
tcp_keepalive=true
```

## Known Issues

### Issue: Session Freezes on Window Resize

**Symptoms:**
- RDP window resizes successfully initially
- Desktop becomes unresponsive after resize
- Disconnect/reconnect sometimes fixes it
- May freeze again on subsequent resize

**Possible Causes:**

1. **XFCE Desktop Environment Issues**
   - xfsettingsd may interfere with RANDR events
   - Display configuration conflicts
   - Power manager trying to manage non-existent hardware

2. **xorgxrdp Driver Race Conditions**
   - Rapid resizing can cause race conditions
   - Driver may not complete one resize before another starts
   - Known upstream issue in xorgxrdp

3. **Client-Side Problems**
   - Some RDP clients handle dynamic resolution poorly
   - Remmina versions may have bugs
   - Client settings (color depth, compression) can impact stability

4. **X Server State**
   - X server may not properly handle RANDR requests
   - Display mode switching can cause hangs
   - Virtual screen size limits being exceeded

### Issue: Black Screen on Connect

**Symptoms:**
- Connection established but screen is black
- No desktop elements visible
- Session appears active but unresponsive

**Common Causes:**
- Missing Xwrapper.config (check `/etc/X11/Xwrapper.config`)
- Desktop environment not starting (check `~/.xsession-errors`)
- X server permission errors (check `/var/log/xrdp-sesman.log`)

### Issue: Immediate Disconnect

**Symptoms:**
- Connection drops immediately after authentication
- "Connection closed" or similar error

**Common Causes:**
- XFCE configuration errors
- Missing dbus-launch
- Incompatible session startup script

## Troubleshooting Steps

### 1. Check Configuration Files

```bash
# Verify Xwrapper.config exists and has correct content
cat /etc/X11/Xwrapper.config

# Should show:
# allowed_users=anybody
# needs_root_rights=no

# Check sesman.ini for Xorg backend
grep -A 5 "\[Xorg\]" /etc/xrdp/sesman.ini

# Check XFCE configuration was applied
ls -la ~/.config/autostart/light-locker.desktop
cat ~/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml
```

### 2. Review Log Files

```bash
# XRDP main log
sudo tail -100 /var/log/xrdp.log

# Session manager log (most useful for debugging)
sudo tail -100 /var/log/xrdp-sesman.log

# X server log for this session
tail -100 ~/.xorgxrdp.*.log

# Session errors
tail -100 ~/.xsession-errors

# System journal for xrdp service
sudo journalctl -u xrdp -n 100 --no-pager
```

### 3. Check Running Processes

```bash
# During an active session, check processes
ps aux | grep -E 'xrdp|Xorg|xfce'

# Look for:
# - Xorg process with xrdpdev
# - xrdp-sesman
# - xfce4-session
# - dbus-daemon

# Check for problematic processes that should be disabled
ps aux | grep -E 'light-locker|pm-suspend'
```

### 4. Test Different Clients

Try different RDP clients to isolate client-side issues:

- **Remmina** (Linux) - Most common, but can have bugs
- **Microsoft Remote Desktop** (Windows/Mac) - Reference implementation
- **xfreerdp** (Command line) - Good for debugging

Example with xfreerdp:
```bash
xfreerdp /v:server.example.com /u:username /dynamic-resolution
```

### 5. Reduce Resolution Changes

If freezing only happens on resize:

1. Use a fixed resolution instead of dynamic
2. Avoid rapid/repeated resizing
3. Resize slowly and wait for desktop to stabilize
4. Consider using full-screen mode

### 6. Check Desktop Environment

```bash
# Test if XFCE is causing issues by trying a minimal session
# Edit ~/startwm.sh temporarily:
#!/bin/bash
exec xterm

# If xterm works but XFCE freezes, issue is in XFCE configuration
```

### 7. Monitor RANDR Events

```bash
# Install xev to monitor X events
sudo apt-get install x11-utils

# In an active session, run:
xev -root | grep -i randr

# Resize window and watch for RRScreenChangeNotify events
# If no events appear, RANDR is not working
```

## Debugging Checklist

When reporting freeze issues, provide:

- [ ] XRDP version: `xrdp --version`
- [ ] xorgxrdp version: `dpkg -l | grep xorgxrdp`
- [ ] Desktop environment: Usually XFCE
- [ ] Client application and version
- [ ] Contents of `/etc/X11/Xwrapper.config`
- [ ] Last 50 lines of `/var/log/xrdp-sesman.log`
- [ ] Last 50 lines of `~/.xsession-errors`
- [ ] Output of `ps aux | grep -E 'xrdp|Xorg'` during freeze
- [ ] Whether disconnect/reconnect fixes it
- [ ] Whether it happens on first resize or subsequent resizes

## Workarounds

### Temporary: Disable Dynamic Resolution

If stability is more important than convenience:

1. In Remmina: Uncheck "Use client resolution"
2. Set a fixed resolution (e.g., 1920x1080)
3. Reconnect

### Temporary: Restart Session After Resize

If freeze happens predictably:

1. Resize window
2. Immediately disconnect
3. Reconnect
4. Continue working

### Experimental: Enable Glamor

**Warning:** May cause crashes, but worth testing:

Edit `/etc/X11/xrdp/xorg.conf`:
```ini
Section "Device"
    Driver "xrdpdev"
    Option "UseGlamor" "true"  # Changed from false
EndSection
```

Restart xrdp:
```bash
sudo systemctl restart xrdp
```

## Advanced Diagnostics

### Enable Debug Logging

Edit `/etc/xrdp/sesman.ini`:
```ini
[Logging]
LogLevel=DEBUG  # Changed from INFO
```

Edit `/etc/xrdp/xrdp.ini`:
```ini
[Logging]
LogLevel=DEBUG  # Changed from INFO
```

Restart and reproduce issue, then check logs.

### Monitor X Server

```bash
# Watch X server resource usage during resize
watch -n 1 'ps aux | grep Xorg'

# Check if X server is consuming CPU during freeze
top -p $(pgrep Xorg)
```

### Test RANDR Directly

```bash
# List current outputs
xrandr

# Try manual resize (in active session)
xrandr --output default --mode 1920x1080

# If this works but RDP resize freezes, issue is in xrdp/xorgxrdp
```

## References

- [xrdp GitHub Issues](https://github.com/neutrinolabs/xrdp/issues)
- [xorgxrdp GitHub](https://github.com/neutrinolabs/xorgxrdp)
- [RANDR Extension Spec](https://www.x.org/releases/X11R7.7/doc/randrproto/randrproto.txt)

## See Also

- `desktop/xrdp_steps.py` - XRDP setup implementation
- `desktop/desktop_environment_steps.py` - XFCE RDP configuration
- `desktop/service_tools/xrdp_session_cleanup.py` - Session cleanup
- `tests/test_xrdp.py` - XRDP configuration tests
