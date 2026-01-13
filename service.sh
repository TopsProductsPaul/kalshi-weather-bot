#!/bin/bash
# BTC Bot Service Management Script
# Usage: ./service.sh [install|uninstall|start|stop|restart|status|logs]

PLIST_NAME="com.kalshi.btcbot"
PLIST_SRC="$(pwd)/com.kalshi.btcbot.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_FILE="$(pwd)/btc_bot.log"

case "$1" in
    install)
        echo "Installing BTC bot service..."
        cp "$PLIST_SRC" "$PLIST_DEST"
        launchctl load "$PLIST_DEST"
        echo "✅ Service installed and started"
        echo "   Logs: $LOG_FILE"
        ;;

    uninstall)
        echo "Uninstalling BTC bot service..."
        launchctl unload "$PLIST_DEST" 2>/dev/null
        rm -f "$PLIST_DEST"
        echo "✅ Service uninstalled"
        ;;

    start)
        echo "Starting BTC bot..."
        launchctl start "$PLIST_NAME"
        echo "✅ Started"
        ;;

    stop)
        echo "Stopping BTC bot..."
        launchctl stop "$PLIST_NAME"
        echo "✅ Stopped"
        ;;

    restart)
        echo "Restarting BTC bot..."
        launchctl stop "$PLIST_NAME"
        sleep 2
        launchctl start "$PLIST_NAME"
        echo "✅ Restarted"
        ;;

    status)
        echo "BTC Bot Status:"
        launchctl list | grep -q "$PLIST_NAME" && echo "✅ Running" || echo "❌ Not running"
        if [ -f "$LOG_FILE" ]; then
            echo ""
            echo "Last 10 log lines:"
            tail -10 "$LOG_FILE"
        fi
        ;;

    logs)
        if [ -f "$LOG_FILE" ]; then
            tail -f "$LOG_FILE"
        else
            echo "No log file found at $LOG_FILE"
        fi
        ;;

    *)
        echo "Usage: $0 {install|uninstall|start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  install   - Install and start the service"
        echo "  uninstall - Stop and remove the service"
        echo "  start     - Start the service"
        echo "  stop      - Stop the service"
        echo "  restart   - Restart the service"
        echo "  status    - Show service status and recent logs"
        echo "  logs      - Follow log file in real-time"
        exit 1
        ;;
esac
