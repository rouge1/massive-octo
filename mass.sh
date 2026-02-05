#!/bin/bash

PROJECT_DIR="/data/python/massive"
CONFIG_DIR="$PROJECT_DIR/config"
mkdir -p "$CONFIG_DIR"

BACKEND_PID_FILE="$CONFIG_DIR/backend.pid"
FRONTEND_PID_FILE="$CONFIG_DIR/frontend.pid"
BACKEND_LOG="$CONFIG_DIR/backend.log"
FRONTEND_LOG="$CONFIG_DIR/frontend.log"

REQUIRED_ENV="mass"

# Check and activate conda environment
ensure_conda_env() {
    # Check if conda is available
    if ! command -v conda &> /dev/null; then
        echo "WARNING: conda command not found. Make sure conda is installed and in PATH."
        return 1
    fi

    # Get current conda environment
    CURRENT_ENV="${CONDA_DEFAULT_ENV:-}"

    if [ "$CURRENT_ENV" = "$REQUIRED_ENV" ]; then
        echo "✓ Conda environment '$REQUIRED_ENV' is active"
        return 0
    fi

    if [ -n "$CURRENT_ENV" ]; then
        echo "WARNING: Wrong conda environment active: '$CURRENT_ENV' (expected '$REQUIRED_ENV')"
    else
        echo "WARNING: No conda environment is active (expected '$REQUIRED_ENV')"
    fi

    echo "Activating conda environment '$REQUIRED_ENV'..."

    # Source conda.sh to enable conda activate in scripts
    CONDA_BASE=$(conda info --base 2>/dev/null)
    if [ -z "$CONDA_BASE" ]; then
        echo "ERROR: Could not determine conda base directory"
        return 1
    fi

    source "$CONDA_BASE/etc/profile.d/conda.sh"

    if conda activate "$REQUIRED_ENV" 2>/dev/null; then
        echo "✓ Activated conda environment '$REQUIRED_ENV'"
        return 0
    else
        echo "ERROR: Failed to activate conda environment '$REQUIRED_ENV'"
        echo "       Try running: conda activate $REQUIRED_ENV"
        return 1
    fi
}

start_backend() {
    if [ -f "$BACKEND_PID_FILE" ] && kill -0 $(cat "$BACKEND_PID_FILE") 2>/dev/null; then
        echo "Backend already running (PID: $(cat $BACKEND_PID_FILE))"
        return 1
    fi
    cd "$PROJECT_DIR/backend"
    nohup uvicorn main:app --reload --port 8000 > "$BACKEND_LOG" 2>&1 &
    echo $! > "$BACKEND_PID_FILE"
    echo "Backend started (PID: $!)"
}

start_frontend() {
    if [ -f "$FRONTEND_PID_FILE" ] && kill -0 $(cat "$FRONTEND_PID_FILE") 2>/dev/null; then
        echo "Frontend already running (PID: $(cat $FRONTEND_PID_FILE))"
        return 1
    fi
    cd "$PROJECT_DIR/frontend"
    nohup python -m http.server 3000 > "$FRONTEND_LOG" 2>&1 &
    echo $! > "$FRONTEND_PID_FILE"
    echo "Frontend started (PID: $!)"
}

stop_backend() {
    if [ -f "$BACKEND_PID_FILE" ]; then
        PID=$(cat "$BACKEND_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID" 2>/dev/null
            # Also kill any child processes (uvicorn spawns workers)
            pkill -P "$PID" 2>/dev/null
            echo "Backend stopped (PID: $PID)"
        else
            echo "Backend not running (stale PID file)"
        fi
        rm -f "$BACKEND_PID_FILE"
    else
        echo "Backend not running"
    fi
}

stop_frontend() {
    if [ -f "$FRONTEND_PID_FILE" ]; then
        PID=$(cat "$FRONTEND_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID" 2>/dev/null
            echo "Frontend stopped (PID: $PID)"
        else
            echo "Frontend not running (stale PID file)"
        fi
        rm -f "$FRONTEND_PID_FILE"
    else
        echo "Frontend not running"
    fi
}

status() {
    echo "=== Backend (FastAPI on :8000) ==="
    if [ -f "$BACKEND_PID_FILE" ] && kill -0 $(cat "$BACKEND_PID_FILE") 2>/dev/null; then
        echo "  Status: RUNNING (PID: $(cat $BACKEND_PID_FILE))"
    else
        echo "  Status: STOPPED"
        [ -f "$BACKEND_PID_FILE" ] && rm -f "$BACKEND_PID_FILE"
    fi

    echo ""
    echo "=== Frontend (HTTP on :3000) ==="
    if [ -f "$FRONTEND_PID_FILE" ] && kill -0 $(cat "$FRONTEND_PID_FILE") 2>/dev/null; then
        echo "  Status: RUNNING (PID: $(cat $FRONTEND_PID_FILE))"
    else
        echo "  Status: STOPPED"
        [ -f "$FRONTEND_PID_FILE" ] && rm -f "$FRONTEND_PID_FILE"
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
        start_backend
        start_frontend
        echo ""
        echo "Backend:  http://localhost:8000"
        echo "Frontend: http://localhost:3000"
        ;;
    stop)
        stop_backend
        stop_frontend
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $0 {start|stop|status}"
        exit 1
        ;;
esac
