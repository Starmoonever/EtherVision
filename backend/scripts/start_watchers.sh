#!/bin/bash

PID_FILE="$(cd "$(dirname "$0")/.." && pwd)/watchers.pid"

nohup uv run aave-crawler watch -p v2 -l 60         > nohup_v2.log          2>&1 & echo "$!" > "$PID_FILE"
nohup uv run aave-crawler watch -p v3 -l 60         > nohup_v3.log          2>&1 & echo "$!" >> "$PID_FILE"
nohup uv run aave-crawler watch -p v2_borrow -l 60  > nohup_v2_borrow.log   2>&1 & echo "$!" >> "$PID_FILE"
nohup uv run aave-crawler watch -p v3_borrow -l 60   > nohup_v3_borrow.log   2>&1 & echo "$!" >> "$PID_FILE"

echo "Watchers started. PIDs saved to $PID_FILE"
cat "$PID_FILE"
