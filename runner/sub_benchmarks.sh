#!/bin/bash
#
# This script submits a job via qsub (if available) to perform benchmarks with testflo
#
# Usage: sub_benchmarks RUN_NAME CSV_FILE NSLOTS
#
#     RUN_NAME : the name of the job (REQUIRED)
#     CSV_FILE : the file name for the benchmark data (REQUIRED)
#     NSLOTS   : the number of processors (optional, default 20)
#

RUN_NAME=$1
CSV_FILE=$2

case $3 in
    ''|*[!0-9]*) NSLOTS=20 ;;
    *)           NSLOTS=$1 ;;
esac

# generate job script
cat << EOM >job
#!/bin/bash
#
# Use the ompi parallel environment, with X processors:
#$ -pe ompi $NSLOTS
#
# The name of the job:
#$ -N $RUN_NAME
#
# Start from the current working directory:
#$ -cwd
#
# Set the shell:
#$ -S /bin/bash
#
# Retain the existing environment (except PATH, see below):
#$ -V
#
# Output and error filenames (optional):
#$ -o \$JOB_NAME-\$JOB_ID.output
#$ -e \$JOB_NAME-\$JOB_ID.error
#
# Send mail at the end of the job (optional):
#$ -m e
#
# Address to send mail to (optional):
#$ -M stephen.w.ryan@nasa.gov
#
# Exclude the interactive node
#$ -hard -q mdao.q@mdao[1-9]*

# USE_PROC_FILES causes I/O erros when using MPI.Spawn
unset USE_PROC_FILES

# what is using cpu before
ps -eo pcpu,cpuid,pid,user,args | sort -k 1 -r | head -10 >>top.txt

testflo -n 1 -bv -d $CSV_FILE

# what is using cpu after
ps -eo pcpu,cpuid,pid,user,args | sort -k 1 -r | head -10 >>top.txt

EOM

# submit job via qsub if available, otherwise just run via bash
QSUB=`command -v qsub`
if [ -n "$QSUB" ]; then
    echo "submitting job via qsub"
    qsub -sync y job
else
    echo "running job via bash"
    bash job
fi
