#!/bin/bash --login

#
# env vars
#
BENCHMARK_DIR=$HOME/benchmark/runner
TMP_DIR=$HOME/tmp

#
# activate benchmark env, with slack_sdk and matplotlib
#
source ~/.bashrc
conda activate benchmark

#
# start clean
#
# conda clean --packages -y

#
# cd to benchmark runner dir and run benchmarks
#
cd $BENCHMARK_DIR

if [[ "$#" -eq 0 ]]; then
  ./benchmark.py -u *.json
else
  for FILE_NAME in "$@"; do
    ./benchmark.py -fuk $FILE_NAME
  done
fi

#
# delete logs older than 10 days
#
find $BENCHMARK_DIR/logs -name "*.log" -type f -mtime +10 -exec rm -f {} \;

#
# delete envs older than 10 days
#
#find $HOME/.conda/envs -type d -mtime +10 -exec rm -rf {} \;

#
# delete temporary files older than 3 days
#
find $TMPDIR -type d -mtime +3 -exec rm -rf {} \;

