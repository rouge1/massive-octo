#!/bin/bash

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$SCRIPT_DIR"
CONFIG_DIR="$PROJECT_DIR/config"
mkdir -p "$CONFIG_DIR"

WATCHER_PID_FILE="$CONFIG_DIR/watcher.pid"
WEBSITE_PID_FILE="$CONFIG_DIR/website.pid"
WATCHER_LOG="$CONFIG_DIR/watcher.log"
WEBSITE_LOG="$CONFIG_DIR/website.log"

PREFERRED_ENVS=("mass" "price-env")

# Capture X11 display vars now, before any subshell changes them
CAPTURED_DISPLAY="${DISPLAY:-:0}"
CAPTURED_XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

# Check and activate conda environment
ensure_conda_env() {
    if ! command -v conda &> /dev/null; then
        echo "WARNING: conda command not found. Make sure conda is installed and in PATH."
        return 1
    fi

    CURRENT_ENV="${CONDA_DEFAULT_ENV:-}"

    # Already in one of the acceptable environments
    for env in "${PREFERRED_ENVS[@]}"; do
        if [ "$CURRENT_ENV" = "$env" ]; then
            echo "✓ Conda environment '$env' is active"
            return 0
        fi
    done

    if [ -n "$CURRENT_ENV" ]; then
        echo "WARNING: Wrong conda environment active: '$CURRENT_ENV' (expected one of: ${PREFERRED_ENVS[*]})"
    else
        echo "WARNING: No conda environment is active (expected one of: ${PREFERRED_ENVS[*]})"
    fi

    CONDA_BASE=$(conda info --base 2>/dev/null)
    if [ -z "$CONDA_BASE" ]; then
        echo "ERROR: Could not determine conda base directory"
        return 1
    fi

    source "$CONDA_BASE/etc/profile.d/conda.sh"

    for env in "${PREFERRED_ENVS[@]}"; do
        echo "Trying conda environment '$env'..."
        if conda activate "$env" 2>/dev/null; then
            echo "✓ Activated conda environment '$env'"
            return 0
        fi
    done

    echo "ERROR: Could not activate any of: ${PREFERRED_ENVS[*]}"
    echo "       Try running: conda activate mass   OR   conda activate price-env"
    return 1
}

start_watcher() {
    if [ -f "$WATCHER_PID_FILE" ] && kill -0 $(cat "$WATCHER_PID_FILE") 2>/dev/null; then
        echo "Watcher already running (PID: $(cat $WATCHER_PID_FILE))"
        return 1
    fi
    cd "$PROJECT_DIR"
    if [ -z "$CAPTURED_DISPLAY" ]; then
        echo "WARNING: No DISPLAY set — GUI window may not appear"
    fi
    DISPLAY="$CAPTURED_DISPLAY" XAUTHORITY="$CAPTURED_XAUTHORITY" \
        python options_watcher.py >> "$WATCHER_LOG" 2>&1 &
    disown $!
    echo $! > "$WATCHER_PID_FILE"
    echo "Watcher started (PID: $!)  → $WATCHER_LOG"
}

start_website() {
    if [ -f "$WEBSITE_PID_FILE" ] && kill -0 $(cat "$WEBSITE_PID_FILE") 2>/dev/null; then
        echo "Website already running (PID: $(cat $WEBSITE_PID_FILE))"
        return 1
    fi
    cd "$PROJECT_DIR"
    if [ -z "$CAPTURED_DISPLAY" ]; then
        echo "WARNING: No DISPLAY set — GUI window may not appear"
    fi
    DISPLAY="$CAPTURED_DISPLAY" XAUTHORITY="$CAPTURED_XAUTHORITY" \
        python website.py >> "$WEBSITE_LOG" 2>&1 &
    disown $!
    echo $! > "$WEBSITE_PID_FILE"
    echo "Website started (PID: $!)  → $WEBSITE_LOG"
}

stop_watcher() {
    if [ -f "$WATCHER_PID_FILE" ]; then
        PID=$(cat "$WATCHER_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID" 2>/dev/null
            pkill -P "$PID" 2>/dev/null
            echo "Watcher stopped (PID: $PID)"
        else
            echo "Watcher not running (stale PID file)"
        fi
        rm -f "$WATCHER_PID_FILE"
    else
        echo "Watcher not running"
    fi
}

stop_website() {
    if [ -f "$WEBSITE_PID_FILE" ]; then
        PID=$(cat "$WEBSITE_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID" 2>/dev/null
            pkill -P "$PID" 2>/dev/null
            echo "Website stopped (PID: $PID)"
        else
            echo "Website not running (stale PID file)"
        fi
        rm -f "$WEBSITE_PID_FILE"
    else
        echo "Website not running"
    fi
}

status() {
    echo "=== Options Watcher (options_watcher.py) ==="
    if [ -f "$WATCHER_PID_FILE" ] && kill -0 $(cat "$WATCHER_PID_FILE") 2>/dev/null; then
        echo "  Status: RUNNING (PID: $(cat $WATCHER_PID_FILE))"
    else
        echo "  Status: STOPPED"
        [ -f "$WATCHER_PID_FILE" ] && rm -f "$WATCHER_PID_FILE"
    fi

    echo ""
    echo "=== Website Server (website.py) ==="
    if [ -f "$WEBSITE_PID_FILE" ] && kill -0 $(cat "$WEBSITE_PID_FILE") 2>/dev/null; then
        echo "  Status: RUNNING (PID: $(cat $WEBSITE_PID_FILE))"
    else
        echo "  Status: STOPPED"
        [ -f "$WEBSITE_PID_FILE" ] && rm -f "$WEBSITE_PID_FILE"
    fi
}

case "$1" in
    start)
        if ! ensure_conda_env; then
            echo ""
            echo "Failed to ensure conda environment. Aborting."
            exit 1
        fi
        echo ""
        start_watcher
        start_website
        echo ""
        echo "Logs:"
        echo "  config/watcher.log"
        echo "  config/website.log"
        ;;
    stop)
        stop_watcher
        stop_website
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $0 {start|stop|status}"
        exit 1
        ;;
esac
