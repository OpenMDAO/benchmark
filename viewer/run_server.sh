#!/bin/bash

#
# set PYTHONPATH
#

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd $DIR
export PYTHONPATH="$DIR/../runner"

#
# check if server is already running, if not then run it
#

CMD="python tornado_server.py"

if pgrep -f "$CMD" >&/dev/null; then
    echo "$CMD already running..."
else
    echo "running $CMD..."
    DATE_STR=`date +"%F-%H%M%S"`
    nohup $CMD >& server-$DATE_STR.out &
fi
