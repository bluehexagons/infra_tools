#!/bin/bash
# Monitor infra_tools logs for errors and warnings
#
# Usage:
#   ./monitor_logs.sh              # Monitor all logs
#   ./monitor_logs.sh errors       # Only show errors
#   ./monitor_logs.sh warnings     # Only show warnings
#   ./monitor_logs.sh SERVICE_NAME # Monitor specific service

set -euo pipefail

LOG_DIR="/var/log/infra_tools"
MODE="${1:-all}"

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

if [ ! -d "$LOG_DIR" ]; then
    echo "Error: Log directory $LOG_DIR does not exist"
    echo "Logs will be created when services run for the first time"
    exit 1
fi

echo "Monitoring infra_tools logs in $LOG_DIR"
echo "Press Ctrl+C to stop"
echo ""

case "$MODE" in
    errors)
        echo "Showing ERRORS only"
        tail -F "$LOG_DIR"/*/*.log 2>/dev/null | grep --line-buffered "ERROR" | while read -r line; do
            echo -e "${RED}$line${NC}"
        done
        ;;
    warnings)
        echo "Showing WARNINGS only"
        tail -F "$LOG_DIR"/*/*.log 2>/dev/null | grep --line-buffered "WARNING" | while read -r line; do
            echo -e "${YELLOW}$line${NC}"
        done
        ;;
    all)
        echo "Showing all logs"
        tail -F "$LOG_DIR"/*/*.log 2>/dev/null | while read -r line; do
            if echo "$line" | grep -q "ERROR"; then
                echo -e "${RED}$line${NC}"
            elif echo "$line" | grep -q "WARNING"; then
                echo -e "${YELLOW}$line${NC}"
            else
                echo "$line"
            fi
        done
        ;;
    *)
        # Assume it's a service name or subdirectory
        if [ -f "$LOG_DIR/$MODE.log" ]; then
            echo "Monitoring $MODE.log"
            tail -F "$LOG_DIR/$MODE.log"
        elif [ -d "$LOG_DIR/$MODE" ]; then
            echo "Monitoring logs in $MODE/"
            tail -F "$LOG_DIR/$MODE"/*.log 2>/dev/null
        elif [ -f "$LOG_DIR"/*/"$MODE.log" ]; then
            echo "Monitoring $MODE.log"
            tail -F "$LOG_DIR"/*/"$MODE.log"
        else
            echo "Error: Unknown mode or service: $MODE"
            echo ""
            echo "Usage:"
            echo "  $0              # Monitor all logs"
            echo "  $0 errors       # Only show errors"
            echo "  $0 warnings     # Only show warnings"
            echo "  $0 SERVICE_NAME # Monitor specific service"
            echo ""
            echo "Available services:"
            find "$LOG_DIR" -name "*.log" -type f 2>/dev/null | sed "s|$LOG_DIR/||" | sed 's|/| - |' || echo "  (No log files found yet)"
            exit 1
        fi
        ;;
esac
