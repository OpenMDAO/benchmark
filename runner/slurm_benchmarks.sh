#!/bin/bash

# This script submits a job via SLURM to perform benchmarks with testflo
#
# Usage: $0 RUN_NAME -d CSV_FILE -o OUT_FILE -t TIMEOUT
#
#     RUN_NAME : the name of the job (Default: YYMMDD_HHMMSS)
#     CSV_FILE : the file name for the benchmark data (Default: RUN_NAME.csv)
#     OUT_FILE : the file name for the benchmark results (Default: RUN_NAME-bm.log)
#     TIMEOUT : the time limit for individual benchmarksin seconds (Default: 2000)
#

args=()
while [ $OPTIND -le "$#" ]; do
    echo "OPTIND: $OPTIND"
    if getopts "o:d:t:" opt; then
      echo "opt: $opt"
      case $opt in
        d) CSV_FILE="$OPTARG";;
        o) OUT_FILE="$OPTARG";;
        t) TIMEOUT="$OPTARG";;
        \?) echo "Invalid option -$OPTARG" >&2; exit 1;;
      esac
    else
      args+=("${!OPTIND}")
      ((OPTIND++))
    fi
done

RUN_NAME=${args[0]}
if [ -z "$RUN_NAME" ]; then
    RUN_NAME=`date +%Y%m%d_%H%M%S`
fi
if [ -z "$CSV_FILE" ]; then
    CSV_FILE=$RUN_NAME.csv
fi
if [ -z "$OUT_FILE" ]; then
    OUT_FILE=${RUN_NAME}-bm.log
fi
if [ -z "$TIMEOUT" ]; then
    TIMEOUT=2000
fi

# generate job script
cat << EOM >$RUN_NAME.sh
#!/bin/bash
# Submit only to the mdao partition:
#SBATCH --partition=mdao
#
# Don't run on mdao0:
#SBATCH --exclude=mdao0
#
# Prevent other jobs from being scheduled on the allocated node(s):
#SBATCH --exclusive
#
# Set the mininum and maximum number of nodes:
#SBATCH --nodes=1-1
#
# Output files:
#SBATCH --output=slurm-%x-%j.out.txt
#SBATCH --error=slurm-%x-%j.err.txt

export OMPI_MCA_mpi_warn_on_fork=0
ulimit -s 10240
unset USE_PROC_FILES

testflo -n 1 -bvs -o $OUT_FILE -d $CSV_FILE --timeout=$TIMEOUT
EOM

# submit the job
sbatch -W -J $RUN_NAME $RUN_NAME.sh
