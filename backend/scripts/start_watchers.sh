#!/bin/bash

nohup uv run aave-crawler watch -p v2 > nohup_v2.log 2>&1 &
nohup uv run aave-crawler watch -p v3 > nohup_v3.log 2>&1 &
nohup uv run aave-crawler watch -p v2_borrow > nohup_v2_borrow.log 2>&1 &
nohup uv run aave-crawler watch -p v3_borrow > nohup_v3_borrow.log 2>&1 &
