#!/bin/bash
# usage: octagon.sh [first_turn] [corner] [final_spinl]  -- defaults = v2 (1.11 0.40 0.61, tuned on a run-down battery)
# 2026-10-25 charged battery spins ~135 deg/s vs ~101 -> use 0.80 0.35 0.46
T=${1:-1.11}; C=${2:-0.40}; F=${3:-0.61}
echo "--- FLOOR: OCTAGON (turn $T, corners $C, final spinl $F) $(date +%F) ---" >> /tmp/mitt/tank_live.log
steps=("go 1.6 30 0.3 17" "spinr $T 30 0.3 0")
for i in 1 2 3 4 5 6 7; do steps+=("go 1.25 30 0.3 17" "spinr $C 30 0.3 0"); done
steps+=("go 1.25 30 0.3 17" "spinl $F 30 0.3 0" "rev 1.6 30 0.3 17")
python3 "$(dirname "$0")/route.py" "${steps[@]}"
