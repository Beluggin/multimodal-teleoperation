#!/bin/bash
# usage: tankrun.sh <move> [secs] [duty]  -- logs staged latency to tank_live.log
LOG=/tmp/mitt/tank_live.log; SOCK=/tmp/mitt/cm-tank
K="-i $HOME/.ssh/tank -o BatchMode=yes"
[ -S $SOCK ] || ssh $K -o ControlMaster=yes -o ControlPath=$SOCK -o ControlPersist=600 -fN pi@tank.local
send=$(date +%s%3N)
echo "$(date +%T.%3N) SEND $*" >> $LOG
out=$(ssh $K -o ControlPath=$SOCK pi@tank.local "python3 -u ~/motor_bench.py $*" 2>&1)
done_ms=$(date +%s%3N)
echo "$out" | awk -v s=$send '/^@/{t=substr($1,2); printf "             %-15s +%5d ms after send\n",$2,t-s; next} {print "             tank: " $0}' >> $LOG
echo "$(date +%T.%3N) DONE $* round trip $((done_ms-send)) ms" >> $LOG
