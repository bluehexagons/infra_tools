# Centralized Logging System

The infra_tools repository uses a centralized logging system to ensure consistent log management across all services and systems. This enables better monitoring and easier integration with external monitoring services.

## Overview

All services in infra_tools write logs to a centralized location (`/var/log/infra_tools/`) with:
- **Rotating file handlers** to prevent disk space issues
- **Standardized log format** with timestamps and severity levels
- **Optional syslog integration** for system-level monitoring
- **Automatic directory creation** with fallback to stderr

## Log Directory Structure

```
/var/log/infra_tools/
├── operations/          # Operation logs (from operation_log.py)
│   ├── sync_*.log
│   ├── scrub_*.log
│   └── par2_*.log
├── common/              # Common services
│   └── auto_restart_if_needed.log
├── desktop/             # Desktop services
│   └── xrdp_session_cleanup.log
├── web/                 # Web services
│   ├── auto_update_node.log
│   └── auto_update_ruby.log
└── scrub/              # Scrub services
    └── scrub-*.log
```

## Log Format

All logs use a consistent format:

```
2026-01-24 12:34:56 - INFO     - service_name - Log message here
2026-01-24 12:35:01 - WARNING  - service_name - Warning message
2026-01-24 12:35:15 - ERROR    - service_name - Error message with details
```

Format: `%(asctime)s - %(levelname)-8s - %(name)s - %(message)s`

## Log Levels

The system supports standard Python logging levels:

- **DEBUG**: Detailed information for diagnosing problems
- **INFO**: General informational messages (default)
- **WARNING**: Warning messages for potentially problematic situations
- **ERROR**: Error messages for serious problems
- **CRITICAL**: Critical messages for very serious errors

## Using Centralized Logging in Services

### For New Services

Use the `get_service_logger()` function for the simplest integration:

```python
#!/usr/bin/env python3
"""My Service Script"""

import os
import sys

# Add lib directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../..'))

from lib.logging_utils import get_service_logger

# Initialize logger for this service
logger = get_service_logger('my_service', 'common', use_syslog=True)

def main():
    logger.info('Service starting')
    
    try:
        # Do work
        logger.info('Work completed successfully')
    except Exception as e:
        logger.error(f'Service failed: {e}')
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### Logger Parameters

- `service_name`: Name of your service (e.g., 'auto_update_node')
- `log_subdir`: Subdirectory under `/var/log/infra_tools/` (e.g., 'web', 'common', 'desktop')
- `level`: Log level (default: INFO)
- `use_syslog`: Whether to also send logs to syslog (default: False)

### Log Rotation

Logs automatically rotate when they reach **5 MB** in size, keeping **5 backup files**. This means each service can use up to 30 MB of disk space for logs (current + 5 backups).

To customize rotation:

```python
from lib.logging_utils import get_rotating_logger

logger = get_rotating_logger(
    name='my_service',
    log_file='/var/log/infra_tools/my_service.log',
    max_bytes=10 * 1024 * 1024,  # 10 MB
    backup_count=10,              # Keep 10 backups
    level=INFO
)
```

## Advanced: Operation Logging

For complex operations that require state tracking, checkpoints, and rollback support, use the `operation_log.py` framework:

```python
from lib.operation_log import create_operation_logger

# Create operation logger
logger = create_operation_logger('sync', source='/data', destination='/backup')

# Log steps
logger.log_step('validation', 'started', 'Validating paths')
logger.log_step('validation', 'completed', 'Paths validated')

# Log metrics
logger.log_metric('files_synced', 1234, 'count')

# Log errors
logger.log_error('network_error', 'Connection timeout', {'host': 'backup.local'})

# Log warnings
logger.log_warning('Slow network detected')

# Complete operation
logger.complete('completed', 'Sync completed successfully')
```

Operation logs are stored in `/var/log/infra_tools/operations/` and include:
- Structured JSON format
- Timestamps for all events
- Operation state checkpoints
- Rollback information
- Performance metrics

## Monitoring Integration

### Log Format for Monitoring Tools

The centralized logging system outputs logs in a format easily parsed by monitoring tools:

1. **Timestamps**: ISO 8601 format for easy parsing
2. **Severity levels**: Clear ERROR/WARNING/INFO markers
3. **Service identification**: Service name in every log line
4. **Structured data**: Operation logs use JSON format

### Syslog Integration

Services can send logs to syslog by using `use_syslog=True`:

```python
logger = get_service_logger('my_service', 'common', use_syslog=True)
```

This allows integration with:
- System logging daemons
- Remote syslog servers
- Log aggregation tools (e.g., rsyslog, syslog-ng)

### Monitoring Error and Warning Patterns

A monitoring script is provided for easy log monitoring:

```bash
# Monitor all logs with color coding (errors in red, warnings in yellow)
./scripts/monitor_logs.sh

# Monitor only errors
./scripts/monitor_logs.sh errors

# Monitor only warnings
./scripts/monitor_logs.sh warnings

# Monitor a specific service
./scripts/monitor_logs.sh auto_update_node
```

You can also use standard Unix tools:

```bash
# Monitor for ERROR level logs
tail -F /var/log/infra_tools/*/*.log | grep "ERROR"

# Monitor for WARNING level logs
tail -F /var/log/infra_tools/*/*.log | grep "WARNING"

# Watch a specific service
tail -F /var/log/infra_tools/web/auto_update_node.log
```

### Example Monitoring Script

```bash
#!/bin/bash
# Monitor infra_tools logs and send alerts

LOG_DIR="/var/log/infra_tools"

# Check for recent errors
RECENT_ERRORS=$(find "$LOG_DIR" -name "*.log" -mmin -5 -exec grep -l "ERROR" {} \;)

if [ -n "$RECENT_ERRORS" ]; then
    # Send alert (customize for your notification system)
    echo "Errors detected in: $RECENT_ERRORS" | mail -s "infra_tools Alert" admin@example.com
fi
```

## Migrating Existing Services

### From print() statements

Replace:
```python
print("Starting service")
print(f"Error: {error_message}")
```

With:
```python
logger.info("Starting service")
logger.error(f"Error: {error_message}")
```

### From syslog

Replace:
```python
import syslog
syslog.syslog(syslog.LOG_INFO, "Service started")
syslog.syslog(syslog.LOG_ERR, f"Error: {error}")
```

With:
```python
from lib.logging_utils import get_service_logger
logger = get_service_logger('my_service', 'common', use_syslog=True)
logger.info("Service started")
logger.error(f"Error: {error}")
```

The `use_syslog=True` parameter ensures logs still go to syslog while also being written to the centralized log files.

## Best Practices

1. **Use appropriate log levels**:
   - INFO for normal operations
   - WARNING for recoverable issues
   - ERROR for failures that require attention

2. **Include context in error messages**:
   ```python
   logger.error(f"Failed to update Node.js from {current_version} to {target_version}")
   ```

3. **Log at key points**:
   - Service start/end
   - Before/after critical operations
   - All errors and warnings
   - Important state changes

4. **Don't log sensitive data**:
   - Passwords
   - API keys
   - Personal information

5. **Use structured logging for complex data**:
   ```python
   from lib.operation_log import create_operation_logger
   logger = create_operation_logger('deployment', app='myapp', version='1.2.3')
   ```

## Troubleshooting

### Logs not appearing

1. Check directory permissions:
   ```bash
   ls -la /var/log/infra_tools/
   ```

2. Check for stderr fallback messages:
   ```bash
   systemctl status <service-name> | grep "Error creating log"
   ```

3. Verify the log file path:
   ```python
   logger.handlers[0].baseFilename  # Shows actual log file path
   ```

### Disk space issues

Check log directory size:
```bash
du -sh /var/log/infra_tools/
```

Logs automatically rotate, but old logs can be cleaned up:
```bash
# Remove logs older than 30 days
find /var/log/infra_tools -name "*.log*" -mtime +30 -delete
```

For operation logs, use the built-in cleanup:
```python
from lib.operation_log import get_operation_logger_manager
manager = get_operation_logger_manager()
cleaned = manager.cleanup_old_logs(days_to_keep=30)
print(f"Cleaned up {cleaned} old log files")
```

## Related Files

- `lib/logging_utils.py` - Core logging utilities
- `lib/operation_log.py` - Advanced operation logging with state tracking
- Service tools in:
  - `common/service_tools/`
  - `web/service_tools/`
  - `desktop/service_tools/`
  - `sync/service_tools/`
  - `deploy/service_tools/`
