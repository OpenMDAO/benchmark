#!/usr/bin/env python
from __future__ import print_function, division

import traceback

import subprocess
from subprocess import Popen, PIPE

import sys
import os
import os.path
import shlex
import sqlite3
import time
import json
import csv
import math

from datetime import datetime

import logging
logging.basicConfig(level=logging.INFO)

from argparse import ArgumentParser

from contextlib import contextmanager


# copy current env, we will modify and use for external commands
env = os.environ.copy()


benchmark_dir = os.path.abspath(os.path.dirname(__file__))


#
# default configuration options
#

conf = {
    # directories used during benchmarking
    "working_dir": benchmark_dir,
    "data_dir":    "data",
    "repo_dir":    "repos",
    "logs_dir":    "logs",

    # script needs at least bash and conda
    "script_prefix": [
        "#!/bin/bash",
        "set -e"
    ],

    # remove benchmark data file after adding to database
    "remove_csv":  False,

    # generate a plot showing history of each benchmark
    "plot_history": True,

    # CA cert information needed by curl (defaults)
    "no-ca": {
        "cacert":  "/etc/ssl/certs/ca-certificates.crt",
        "capath":  "/etc/ssl/certs"
    },
}


#
# utility functions
#

def read_json(filename):
    """
    read data from a JSON file
    """
    with open(filename) as json_file:
        return json.loads(json_file.read())


def write_json(filename, data):
    """
    write JSON data to a file
    """
    with open(filename, 'w') as json_file:
        json_file.write(json.dumps(data))


def prepend_path(newdir, path):
    """
    prepend `newdir` to `path`, return modified `path`
    """
    dirs = path.split(os.pathsep)
    dirs.insert(0, newdir)
    path = (os.pathsep).join(dirs)
    return path


def init_env(project_info):
    """
    initialize env for commands with benchmark and project customizations
    """
    # reset env to be copy of current OS env
    global env
    env = os.environ.copy()

    # prepend benchmark dir to PATH
    env["PATH"] = prepend_path(benchmark_dir, env["PATH"])

    # add any env vars from benchmark config
    if "env" in conf:
        for key, val in conf["env"].items():
            if val.find('~') >= 0:
                val = os.path.expanduser(val)
            if val.find('$') >= 0:
                val = os.path.expandvars(val)
            val = val.replace("$PYTHONPATH", "")  # in case it was empty
            print("setting benchmark ENV:", key, "=", val)
            env[key] = val

    # add any project specific env vars
    if "env" in project_info:
        for key, val in project_info["env"].items():
            if val.find('~') >= 0:
                val = os.path.expanduser(val)
            if val.find('$') >= 0:
                val = os.path.expandvars(val)
            val = val.replace("$PYTHONPATH", "")  # in case it was empty
            logging.info("setting %s ENV: %s=%s", project_info["name"], key,  val)
            env[key] = val


def execute_cmd(cmd, shell=False, combine=False):
    """
    Execute the external command and get its exitcode, stdout and stderr.
    """
    logging.info("> %s", cmd)
    args = shlex.split(cmd)
    if combine:
        proc = Popen(args, stdout=PIPE, stderr=subprocess.STDOUT, shell=shell, env=env, universal_newlines=True)
    else:
        proc = Popen(args, stdout=PIPE, stderr=PIPE, shell=shell, env=env, universal_newlines=True)
    out, err = proc.communicate()

    rc = proc.returncode
    if rc:
        logging.info("RC: %d", rc)
    if out.strip():
        logging.info(out)
    if rc and err and err.strip():  # disregard inconsequential stderr output
        logging.info("STDERR:\n%s", err)

    return rc, out, err


def remove_dir(dirname):
    """
    Remove repo directory before a benchmarking run.
    Will force fresh cloning and avoid branch issues.
    """
    remove_cmd = "rm -rf " + dirname

    if os.path.exists(dirname):
        code, out, err = execute_cmd(remove_cmd)


def upload(files, args_dest):
    """
    upload files to destination via scp
    """
    args = args_dest.split()[:-1]
    dest = args_dest.split()[-1]
    cmd = "scp %s %s %s" % (" ".join(args), " ".join(files), dest)
    code, out, err = execute_cmd(cmd)
    return code, out, err


def init_logging():
    """
    initialize logging to stdout with clean format
    """
    log = logging.getLogger()

    # remove old handler(s)
    for hdlr in log.handlers:
        log.removeHandler(hdlr)

    # set stdout handler with clean format
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(message)s')
    ch.setFormatter(formatter)
    log.addHandler(ch)


def init_log_file(name):
    """
    initialize log file with given name
    """
    logs_dir = os.path.expanduser(os.path.join(conf["logs_dir"]))
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    filename = os.path.join(logs_dir, name+".log")
    fh = logging.FileHandler(filename)

    format_str = '%(asctime)s %(name)s %(levelname)s: %(message)s'
    fh.formatter = logging.Formatter(format_str)

    log = logging.getLogger()
    log.addHandler(fh)


def close_log_file():
    """
    close current log file(s)
    """
    log = logging.getLogger()
    handlers = log.handlers[:]
    for handler in handlers:
        if isinstance(handler, logging.FileHandler):
            handler.close()
            log.removeHandler(handler)


#
# context managers
#

@contextmanager
def cd(newdir):
    """
    A cd that will better handle error and return to its orig dir.
    """
    logging.info('> cd %s', newdir)
    prevdir = os.getcwd()
    fulldir = os.path.expanduser(newdir)
    if not os.path.exists(fulldir):
        os.makedirs(fulldir)
    os.chdir(fulldir)
    try:
        yield
    finally:
        logging.info('> cd %s (from %s)', prevdir, fulldir)
        os.chdir(prevdir)


@contextmanager
def repo(repository, branch=None):
    """
    cd into local copy of repository.  if the repository has not been
    cloned yet, then clone it to working directory first.
    """
    prev_dir = os.getcwd()

    repo_dir = conf["repo_dir"]
    if not os.path.exists(repo_dir):
        os.makedirs(repo_dir)
    logging.info('> cd %s (from %s)', repo_dir, prev_dir)
    os.chdir(repo_dir)

    repo_name = repository.split('/')[-1]
    if not os.path.isdir(repo_name):
        clone_repo(repository, branch)

    logging.info('> cd %s (REPO)', repo_name)
    os.chdir(repo_name)
    try:
        yield
    finally:
        logging.info('> cd %s (from REPO %s)', prev_dir, repo_name)
        os.chdir(prev_dir)


@contextmanager
def conda(name):
    """
    Change PATH to run in conda environment.
    """
    global env
    save_env = env
    env = env.copy()

    # modify PATH for environment
    path = env["PATH"].split(os.pathsep)
    for dirname in path:
        if ("anaconda" in dirname or "miniconda" in dirname or "miniforge" in dirname) and dirname.endswith("/bin"):
            conda_dir = dirname
            path.remove(conda_dir)
            break

    env_path = conda_dir.replace("/bin", "/envs/"+name)
    env["PATH"] = prepend_path(env_path+"/bin", (os.pathsep).join(path))

    logging.info('> switching environment (into %s)', name)
    try:
        yield
    finally:
        logging.info('> restoring environment (from %s)', name)
        env = save_env


#
# repository helpers
#

repo_types = {}


def clone_repo(repository, branch):
    """
    clone repository into current directory
    """
    if branch:
        git_clone_cmd = "git clone -b %s --single-branch %s" % (branch, repository)
        hg_clone_cmd = "hg clone %s -r %s" % (repository, branch)
    else:
        git_clone_cmd = "git clone " + repository
        hg_clone_cmd = "hg clone " + repository

    repo_type = repo_types.get(repository)
    if repo_type == "git":
        code, out, err = execute_cmd(git_clone_cmd)
    elif repo_type == "hg":
        code, out, err = execute_cmd(hg_clone_cmd)
    else:
        code, out, err = execute_cmd(git_clone_cmd)
        if not code:
            repo_types[repository] = "git"
        else:
            code, out, err = execute_cmd(hg_clone_cmd)
            if not code:
                repo_types[repository] = "hg"
    if code:
        raise RuntimeError("Could not clone %s" % repository)


def get_current_commit(repository):
    """
    Update and check the current repo for the most recent commit.
    """
    git_pull = "git pull"
    git_commit = "git rev-parse HEAD"

    hg_pull = "hg pull"
    hg_merge = "hg merge"
    hg_commit = "hg id -i"

    # pull latest commit from desired branch and get the commit ID
    repo_type = repo_types.get(repository)
    if repo_type == "git":
        code, out, err = execute_cmd(git_pull)
        code, out, err = execute_cmd(git_commit)
    elif repo_type == "hg":
        code, out, err = execute_cmd(hg_pull)
        code, out, err = execute_cmd(hg_merge)
        code, out, err = execute_cmd(hg_commit)
    else:
        code, out, err = execute_cmd(hg_pull)
        if (code == 0):
            code, out, err = execute_cmd(hg_merge)
            code, out, err = execute_cmd(hg_commit)
        else:
            code, out, err = execute_cmd(git_pull)
            code, out, err = execute_cmd(git_commit)

    return out.strip()   # TODO: strip the old commit IDs in the database as well


def get_tag_info():
    """
    Return the latest git tag, meaning, highest numerically, as a string, and the associated commit ID.
    """
    # using a pattern to only grab tags that are in version format "X.Y.Z"
    git_versions = subprocess.Popen(['git', 'tag', '-l', '*.*.*'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    cmd_out, cmd_err = git_versions.communicate()

    cmd_out = cmd_out.decode('utf8')
    # take the output of git tag -l *.*.*, and split it from one string into a list.
    version_tags = cmd_out.split()

    if not version_tags:
        raise Exception('No tags found in repository')

    # use sort to put the versions list in order from lowest to highest
    version_tags.sort(key=lambda s: [u for u in s.split('.')])

    logging.info('sorted version tags: %s', version_tags)

    # grab the highest tag that this repo knows about
    latest_tag = version_tags[-1]

    cmd = subprocess.Popen(['git', 'rev-list', '-1', latest_tag, '-s'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    cmd_out, cmd_err = cmd.communicate()

    cmd_out = cmd_out.decode('utf8')
    commit_id = cmd_out.strip()

    logging.info('latest_tag: %s, commit_id: %s', latest_tag, commit_id)
    return latest_tag, commit_id


#
# worker classes
#

class RunScript(object):
    """
    this class encapsulates a script for running benchmarks
    """
    def __init__(self, run_name, project, unit_tests, keep_env):
        """
        Create conda env, install dependencies and then local repositories.
        """
        self.run_name = run_name

        self.script = script = []

        script_prefix = project.get("script_prefix", conf.get("script_prefix"))
        for line in script_prefix:
            script.append(line)

        script.append("\nRUN_NAME=%s" % run_name)

        # create conda env with required packages
        script.append("\n## Create Conda environment")

        # script.append("\ncat ~/.condarc")

        script.append("\nconda deactivate\nconda deactivate\n")

        conda_spec = project["conda"]

        cmd = "conda create -y -q -n $RUN_NAME "
        conda_pkgs = conda_spec + [
            "git",              # for cloning git repos
            "pip",              # for installing dependencies
            "swig",             # for building dependencies
            "cython",           # for building dependencies
            "psutil",           # for testflo benchmarking
            # "memory_profiler",  # for testflo benchmarking
            #"nomkl",            # TODO: experiment with this
            # "matplotlib",       # for plotting results
            # "curl",             # for uploading files & slack messages
            # "sqlite"            # for backing up the database
        ]
        cmd = cmd + " ".join(conda_pkgs)
        script.append(cmd)

        # activate
        script.append("conda activate $RUN_NAME")

        # run any pre-install commands
        if "preinstall" in project:
            script.append("\n## Run pre-install commands")
            for cmd in project["preinstall"]:
                script.append(os.path.expanduser(cmd))

        # install anaconda dependencies
        if "anaconda" in project:
            script.append("\n## Install from anaconda")
            pkgs = []
            for spec in project["anaconda"]:
                pkgs.append(spec)
            if pkgs:
                script.append("conda install -c anaconda %s --yes" % " ".join(pkgs))

        # install conda-forge dependencies
        if "conda-forge" in project:
            script.append("\n## Install from conda-forge")
            pkgs = []
            for spec in project["conda-forge"]:
                pkgs.append(spec)
            if pkgs:
                script.append("conda install -c conda-forge %s --yes" % " ".join(pkgs))

        # install dependencies
        if "dependencies" in project:
            script.append("\n## Install dependencies")
            for dependency in project["dependencies"]:
                if dependency.startswith("~") or dependency.startswith("/"):
                    script.append("cd %s" % os.path.expanduser(dependency))
                    script.append([
                        "if test -f requirements.txt; then",
                        "    pip install -r requirements.txt",
                        "fi"
                    ])
                    script.append("pip install .")
                    script.append("cd -")
                else:
                    script.append("pip install %s" % dependency)

        # install the proper version of testflo to do the benchmarking
        for spec in conda_spec:
            if "python=2" in spec:
                # self.install("testflo<1.4", options="")
                script.append("pip install testflo<1.4")
                break
            elif spec == "python"  or "python=" in spec or "python\>=" in spec:
                # self.install("testflo", options="")
                # script.append("pip install testflo")
                script.append("pip install git+https://github.com/swryan/testflo@benchmark")
                break

        # install triggers
        for trigger in project["triggers"]:
            if trigger.endswith("/releases"):
                trigger = trigger[:-9]
            script.append("\n## Install trigger: %s" % trigger)
            script.append("cd %s" % trigger.split('/')[-1])
            script.append("if test -f requirements.txt; then")
            script.append("    pip install -r requirements.txt")
            script.append("fi")
            script.append("pip install .")
            script.append("cd -")

        # install repository
        repo_name = project["repository"].split('/')[-1]
        if '#' in repo_name:
            repo_name = repo_name.split('#')[0]
        script.append("\n## Install repo: %s" % repo_name)
        script.append("cd %s" % repo_name)
        if "install" in project:
            for line in project["install"]:
                script.append(line)
        else:
            script.append("if test -f requirements.txt; then")
            script.append("    pip install -r requirements.txt")
            script.append("fi")
            script.append("pip install -e .%s" % project.get("extras", ""))

        # run any post-install commands (in the conda environment & repo dir)
        if "postinstall" in project:
            script.append("\n## Run post-install commands")
            for cmd in project["postinstall"]:
                script.append(cmd)

        # print summary of env
        script.append("\n## List installed packages")
        script.append("conda list")

        # run unit tests
        if unit_tests:
            script.append("\n## Run unit tests")
            if "test_cmd" in project:
                script.append(project.get("test_cmd"))
            else:
                script.append("testflo -n 1 --timeout=%d --show_skipped -o $RUN_NAME.log" %
                              project.get("test_timeout", conf.get("test_timeout", 120)))

        # run benchmarks
        script.append("\n## Run benchmarks")
        benchmark_cmd = conf.get("benchmark_cmd")
        if benchmark_cmd:
            benchmark_cmd = "%s $RUN_NAME -o $RUN_NAME-bm.log -d $RUN_NAME.csv -t %s" % (benchmark_cmd,
                            project.get("benchmark_timeout", conf.get("benchmark_timeout", 3600)))
        else:
            benchmark_cmd = "testflo -n 1 -bvs -o $RUN_NAME-bm.log -d $RUN_NAME.csv --timeout=%d" % \
                            project.get("benchmark_timeout", conf.get("benchmark_timeout", 3600))
        script.append("if [ $? -eq 0 ]; then")
        script.append(benchmark_cmd)
        script.append("fi")

        # done
        script.append("\n## Clean up")
        script.append("conda deactivate")
        if not keep_env:
            script.append("conda env remove -q -y --name $RUN_NAME")

        logging.info("Run Script %s.sh:" % self.run_name)
        logging.info("---------------------------------------------------------")
        logging.info("\n".join(script))
        logging.info("---------------------------------------------------------")

    def execute(self):
        filename = "%s.sh" % self.run_name

        with open(filename, "a") as f:
            f.write("\n".join(self.script))

        execute_cmd("chmod +x %s" % filename)
        execute_cmd("./%s" % filename, shell=True)


class Slack(object):
    """
    this class encapsulates the logic required to post messages and files to Slack
    """
    def __init__(self, cfg, ca):
        self.cfg = cfg
        self.ca = ca

    def post_message(self, message, notify=[]):
        """
        post a simple message
        """
        for n in notify:
            if n.startswith("!"):
                message += " <%s>" % n
            else:
                message += " <@%s>" % n


        payload = {
            "attachments": [
                {
                    "fallback": message,
                    "pretext":  message,
                    "mrkdwn_in": ["pretext", "fields"]
                }
            ],
            "unfurl_links": "false",
            "unfurl_media": "false"
        }

        return self.post_payload(payload)

    def post_image(self, title, image_url):
        """
        post an image
        """
        payload = {
            "attachments": [
                {
                    "fallback":  title,
                    "pretext":   title,
                    "image_url": image_url
                }
            ],
            "unfurl_links": "true",
            "unfurl_media": "true"
        }

        return self.post_payload(payload)

    def post_payload(self, payload):
        """
        post a payload
        """
        p = json.dumps(payload)
        u = self.cfg["message"]
        if self.ca:
            c = "--cacert %s --capath %s " % (self.ca["cacert"], self.ca["capath"])
        else:
            c = ""

        cmd = "curl -s -X POST -H 'Content-type: application/json' --data '%s' %s %s" % (p, u, c)

        code, out, err = execute_cmd(cmd)
        if code:
            logging.warning("Could not post msg to slack: %d\n%s\n%s", code, out, err)

        return code

    def post_file(self, filename, title):
        """
        post a file to slack
        """
        if not "channel" in self.cfg or not "token" in self.cfg:
            msg = "'channel' and/or 'token' not found.. Cannot post file '%s' (%s) to slack" % (filename, title)
            logging.warning(msg)
            return -1

        cmd = "curl -s "

        cmd += "-F file=@%s -F title=%s -F filename=%s -F channels=%s -F token=%s " % \
               (filename, title, filename, self.cfg["channel"], self.cfg["token"])

        if self.ca:
            cmd += "--cacert %s --capath %s " % (self.ca["cacert"], self.ca["capath"])

        cmd += "https://slack.com/api/files.upload"

        code, out, err = execute_cmd(cmd)

        if code:
            logging.warning("Could not post file to slack:\n%s\n%s", out, err)

        return code


class BenchmarkDatabase(object):
    """
    this class encapsulates logic that operates on a benchmark database
    """
    def __init__(self, name):
        self.name = name
        self.dbname = os.path.join(conf["data_dir"], name+".db")
        self.connection = sqlite3.connect(self.dbname)

        logging.info('Connected to database: ' + os.path.abspath(self.dbname))

    def _ensure_commits(self):
        """
        if the commit tables have not been created yet, create them
        """
        with self.connection as c:
            # a table containing the last benchmarked commit for each trigger
            # repository
            c.execute("CREATE TABLE if not exists LastCommits"
                      " (Trigger TEXT UNIQUE, LastCommitID TEXT)")

            # a table containing the commit ID for each trigger repository
            # for a given benchmark run (specified by DateTime)
            c.execute("CREATE TABLE if not exists Commits"
                      " (DateTime INT, Trigger TEXT, CommitID TEXT,"
                      "  PRIMARY KEY (DateTime, Trigger))")

    def _ensure_benchmark_data(self):
        """
        if the benchmark data tables have not been created yet, create them
        """
        with self.connection as c:
            # a table containing the status, elapsed time and memory usage for each
            # benchmark in a run
            c.execute("CREATE TABLE if not exists BenchmarkData"
                      " (DateTime INT, Spec TEXT, Status TEXT, Elapsed REAL, Memory REAL,"
                      "  LoadAvg1m REAL, LoadAvg5m REAL, LoadAvg15m REAL, PRIMARY KEY (DateTime, Spec))")

            # a table containing the versions of all installed dependencies for a run
            c.execute("CREATE TABLE if not exists InstalledDeps"
                      " (DateTime INT,  InstalledDep TEXT, Version TEXT,"
                      "  PRIMARY KEY (DateTime, InstalledDep))")

    def get_last_commit(self, trigger):
        """
        Check the database for the most recent commit that was benchmarked
        for the trigger repository
        """
        self._ensure_commits()

        c = self.connection.cursor()
        c.execute("SELECT LastCommitID FROM LastCommits WHERE Trigger == ?", (trigger,))

        rows = c.fetchall()

        if rows:
            return rows[0][0]
        else:
            return ''

    def update_commits(self, commits, timestamp):
        """
        update commits
        """
        self._ensure_commits()

        with self.connection as c:
            for trigger, commit in commits.items():
                logging.info('INSERTING COMMIT %s %s', trigger, commit)
                c.execute('INSERT OR REPLACE INTO LastCommits VALUES (?, ?)', (trigger, str(commit)))
                c.execute('INSERT INTO Commits VALUES (?, ?, ?)', (timestamp, trigger, str(commit)))

    def add_benchmark_data(self, commits, filename, installed):
        """
        Insert benchmarks results into BenchmarkData table.
        Create the table if it doesn't already exist.
        """
        self._ensure_benchmark_data()

        data_added = False

        with self.connection as c:
            with open(filename, 'r') as csvfile:
                reader = csv.reader(csvfile)

                for row in reader:
                    row[1] = row[1].rsplit('/', 1)[1]  # remove path from benchmark file name
                    logging.info('INSERTING BenchmarkData %s' % str(row))
                    try:
                        c.execute("INSERT INTO BenchmarkData VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                                  (row[0], row[1], row[2], float(row[3]), float(row[4]),
                                   float(row[5]), float(row[6]), float(row[7])))
                        data_added = True
                    except IndexError as err:
                        logging.error("*********************************************************")
                        logging.error("Invalid benchmark data:\n %s", str(row))
                        logging.error("*********************************************************")
                    except sqlite3.IntegrityError as err:
                        logging.error("*********************************************************")
                        logging.error("sqlite3.IntegrityError, Error type:\n %s", type(err))
                        logging.error("Error message:\n %s", str(err))
                        logging.error("BenchmarkData key: %s", str(row[:2]))
                        logging.error("*********************************************************")
                    except Exception as err:
                        logging.error("*********************************************************")
                        logging.error("Error type:\n %s", type(err))
                        logging.error("Error message:\n %s", str(err))
                        logging.error("BenchmarkData key: %s", str(row[:2]))
                        logging.error("*********************************************************")

            if data_added:
                timestamp = row[0]  # row[0] is the timestamp for this set of benchmark data
                self.update_commits(commits, timestamp)
                for dep, ver in installed.items():
                    c.execute("INSERT INTO InstalledDeps VALUES(?, ?, ?)", (timestamp, dep, ver))

    def check_benchmarks(self, timestamp=None, threshold=20.):
        """
        Check the benchmark data from the given timestamp for any benchmark with a
        significant change (greater than threshold) in elapsed time or memory usage.
        If no timestamp is given then check the most recent benchmark data.
        """
        self._ensure_benchmark_data()

        logging.info("Checking benchmarks for timestamp: %s", timestamp)

        if timestamp is None:
            with self.connection as c:
                for row in c.execute("SELECT * FROM BenchmarkData "
                                     "ORDER BY DateTime DESC LIMIT 1"):
                    timestamp = row[0]  # row[0] is the timestamp for this set of benchmark data

        if timestamp is None:
            msg = "No benchmark data found"
            logging.warning(msg)
            return [], []

        date_str = datetime.fromtimestamp(timestamp)

        curr_data = self.get_data_for_timestamp(timestamp)
        if not curr_data:
            msg = "No benchmark data found for timestamp %d (%s)" % (timestamp, date_str)
            logging.warning(msg)
            return [], []

        prev_time = None
        with self.connection as c:
            for row in c.execute("SELECT * FROM BenchmarkData "
                                 "WHERE DateTime<? and Status=='OK' "
                                 "ORDER BY DateTime DESC LIMIT 1", (timestamp,)):
                prev_time = row[0]  # row[0] is the timestamp for this set of benchmark data

        if not prev_time:
            msg = "No benchmark data found previous to timestamp %d (%s)" % (timestamp, date_str)
            logging.warning(msg)
            return [], []

        prev_data = self.get_data_for_timestamp(prev_time)

        cpu_messages = []
        mem_messages = []

        for i in range(len(curr_data["spec"])):
            curr_spec    = curr_data["spec"][i]

            curr_elapsed = curr_data["elapsed"][i]
            curr_memory  = curr_data["memory"][i]
            curr_load1   = curr_data["load_1m"][i]
            curr_load5   = curr_data["load_5m"][i]
            curr_load15  = curr_data["load_15m"][i]

            if len(prev_data["elapsed"]) > i:
                prev_elapsed = prev_data["elapsed"][i]
                prev_memory  = prev_data["memory"][i]
                prev_load1   = prev_data["load_1m"][i]
                prev_load5   = prev_data["load_5m"][i]
                prev_load15  = prev_data["load_15m"][i]

                time_delta   = curr_elapsed - prev_elapsed
                mem_delta    = curr_memory  - prev_memory

                if "url" in conf:
                    link = "<%s|%s>" % (conf["url"]+self.name+'/'+curr_spec, curr_spec.split(".")[-1])
                else:
                    link = curr_spec.split(".")[-1]

                pct_change = 100.*time_delta/prev_elapsed
                if abs(pct_change) >= threshold:
                    inc_or_dec = "decreased" if (pct_change < 0) else "increased"
                    msg = "%s %s by %4.1f%%: %5.2f (load avg = %3.1f, %3.1f, %3.1f) vs. %5.2f (load avg = %3.1f, %3.1f, %3.1f)" \
                        % (link, inc_or_dec, abs(pct_change),
                           curr_elapsed, curr_load1, curr_load5, curr_load15,
                           prev_elapsed, prev_load1, prev_load5, prev_load15)
                    cpu_messages.append(msg)

                pct_change = 100.*mem_delta/prev_memory
                if abs(pct_change) >= threshold:
                    inc_or_dec = "decreased" if (pct_change < 0) else "increased"
                    msg = "%s %s by %4.1f%% (%5.2f  vs. %5.2f)" \
                        % (link, inc_or_dec, abs(pct_change), curr_memory, prev_memory)
                    mem_messages.append(msg)

        return cpu_messages, mem_messages

    def get_data_for_timestamp(self, timestamp):
        """
        get benchmark data for the given timestamp
        """
        data = {}

        with self.connection as c:
            for row in c.execute("SELECT * FROM BenchmarkData "
                                 "WHERE DateTime=? and Status=='OK' "
                                 "ORDER BY DateTime", (timestamp,)):
                data.setdefault('timestamp', []).append(row[0])
                data.setdefault('spec', []).append(row[1])
                data.setdefault('status', []).append(row[2])
                data.setdefault('elapsed', []).append(row[3])
                data.setdefault('memory', []).append(row[4])
                data.setdefault('load_1m', []).append(row[5])
                data.setdefault('load_5m', []).append(row[6])
                data.setdefault('load_15m', []).append(row[7])

        return data

    def get_data_for_spec(self, spec, since=None):
        """
        get benchmark data for the given spec
        """
        data = {}

        c = self.connection.cursor()

        if since:
            c.execute("SELECT * FROM BenchmarkData "
                      "WHERE Spec=? and Status=='OK' and DateTime>? "
                      "ORDER BY DateTime", (spec, since))
        else:
            c.execute("SELECT * FROM BenchmarkData "
                      "WHERE Spec=? and Status=='OK' "
                      "ORDER BY DateTime", (spec,))

        rows = c.fetchall()

        for row in rows:
            data.setdefault('timestamp', []).append(row[0])
            data.setdefault('status', []).append(row[2])
            data.setdefault('elapsed', []).append(row[3])
            data.setdefault('memory', []).append(row[4])
            data.setdefault('LoadAvg1m', []).append(row[5])
            data.setdefault('LoadAvg5m', []).append(row[6])
            data.setdefault('LoadAvg15m', []).append(row[7])

        return data

    def dump(self):
        """
        dump database to SQL file
        """
        with open(self.dbname+'.sql', 'w') as f:
            for line in self.connection.iterdump():
                f.write('%s\n' % line)

    def get_specs(self):
        specs = []
        with self.connection as c:
            for row in c.execute("SELECT DISTINCT Spec FROM BenchmarkData"):
                specs.append(row[0])
        return specs

    def plot_benchmark_data(self, spec=None, show=False, save=False):
        """
        generate a history plot for a single benchmark
        """
        logging.info('plot: %s', spec)

        self._ensure_benchmark_data()

        filename = None

        try:
            import numpy as np

            if not show:
                import matplotlib
                matplotlib.use('Agg')
            from matplotlib import pyplot, ticker

            data = self.get_data_for_spec(spec)

            if not data:
                logging.warning("No data to plot for %s", spec)
                return

            timestamp = np.array(data['timestamp'])
            elapsed   = np.array(data['elapsed'])
            maxrss    = np.array(data['memory'])

            fig, a1 = pyplot.subplots()
            a1.get_xaxis().set_major_locator(ticker.MaxNLocator(integer=True))
            x = np.array(range(len(timestamp)))

            a1.plot(x, elapsed, 'b-')
            a1.set_xlabel('run#')
            a1.set_ylabel('elapsed', color='b')
            a1.set_ylim(0, max(elapsed)*1.15)
            for tl in a1.get_yticklabels():
                tl.set_color('b')

            a2 = a1.twinx()
            a2.plot(x, maxrss, 'r-')
            a2.set_ylabel('maxrss', color='r')
            a2.set_ylim(0, max(maxrss)*1.15)
            for tl in a2.get_yticklabels():
                tl.set_color('r')

            label = spec.rsplit(':', 1)[1]
            pyplot.title(label.replace(".benchmark_", ": "))

            if show:
                pyplot.show()

            if save:
                filename = spec.replace(":", "_") + ".png"
                pyplot.savefig(filename)
                code, out, err = execute_cmd("chmod 644 " + filename)

        except ImportError as err:
            logging.info("numpy and matplotlib are required to plot benchmark data: %s" % err)
        except err:
            raise err

        return filename

    def plot_benchmarks(self, show=False, save=False):
        """
        generate a history plot for this projects benchmarks
        """
        import numpy as np

        logging.info('plot: %s', self.name)
        filenames = []

        try:
            if not show:
                import matplotlib
                matplotlib.use('Agg')
            from matplotlib import pyplot, dates

            color_map = pyplot.get_cmap('rainbow')

            mondays = dates.WeekdayLocator(dates.MONDAY)    # major ticks on the mondays
            weekFmt = dates.DateFormatter('%b %d')          # e.g., Jan 12

            self._ensure_benchmark_data()

            # select only the specs that have more than one data point in the last 6 weeks
            since = time.time() - 6*7*24*60*60
            specs = self.get_specs()

            data = {}
            for spec in specs:
                data_for_spec = self.get_data_for_spec(spec, since=since)
                if data_for_spec and len(data_for_spec['elapsed']) > 1:
                    data[spec] = data_for_spec

            specs = sorted(list(data.keys()))

            specs_per_plot = 7
            plot_count = int(math.ceil(len(specs)/specs_per_plot))

            logging.info("specs: %d, specs per plot: %d, plot_count: %d" %
                         (len(specs), specs_per_plot, plot_count))

            for plot_no in range(plot_count):
                # select up to 'specs_per_plot' specs to plot
                plot_specs = specs[:specs_per_plot]
                specs = specs[specs_per_plot:]
                logging.info('plotting:\n%s' % '\n'.join(plot_specs))

                # initialize max values to normalize data
                max_elapsed = 0
                max_memory = 0

                num_specs = len(plot_specs)
                color_cycle = iter([color_map(1.*i/num_specs) for i in range(num_specs)])

                fig = pyplot.figure()
                a1 = pyplot.subplot(3, 1, 1)
                a2 = pyplot.subplot(3, 1, 2)

                for spec in plot_specs:
                    data = self.get_data_for_spec(spec, since=since)

                    datetimes = [datetime.fromtimestamp(t) for t in data['timestamp']]

                    timestamp = dates.date2num(datetimes)
                    elapsed   = np.array(data['elapsed'])
                    memory    = np.array(data['memory'])

                    max_elapsed = max(max_elapsed, np.max(elapsed))
                    max_memory  = max(max_memory, np.max(memory))

                    color = next(color_cycle)

                    a1.plot_date(timestamp, elapsed/max_elapsed, '.-', color=color, label=spec)
                    a2.plot_date(timestamp, memory/max_memory, '.-', color=color, label=spec)

                a1.set_ylim(-0.1, 1.1)
                a2.set_ylim(-0.1, 1.1)

                a1.set_ylabel('elapsed time')
                a2.set_ylabel('memory usage')

                # format the ticks
                a1.set_xticks([])
                a2.xaxis.set_minor_locator(mondays)
                a2.xaxis.set_major_formatter(weekFmt)
                for tick in a2.xaxis.get_major_ticks():
                    tick.label.set_fontsize('x-small')
                # pyplot.xticks(rotation=45)

                pyplot.legend(plot_specs, loc=9, prop={'size': 8}, bbox_to_anchor=(0.5, -0.2))

                if show:
                    pyplot.show()

                if save:
                    # unique filename for every hour, recycled every day (24hr cache on Slack?)
                    from time import localtime, strftime
                    filename = self.name + strftime("_%H_", localtime()) + str(plot_no) + ".png"
                    pyplot.savefig(filename)
                    code, out, err = execute_cmd("chmod 644 " + filename)
                    filenames.append(filename)

                pyplot.close(fig)

        except ImportError as err:
            logging.info("numpy and matplotlib are required to plot benchmark data: %s" % err)

        return filenames

    def export_benchmark_data(self, spec=None, since=None, filename=None):
        """
        export benchmark data in CSV format
        """
        import numpy as np

        logging.info('export: %s', spec)

        self._ensure_benchmark_data()

        c = self.connection.cursor()

        # get column names
        c.execute("PRAGMA table_info(BenchmarkData)")
        rows = c.fetchall()
        col_names = ','.join([meta[1] for meta in rows])

        # get data
        if spec != 'all':
            if since:
                c.execute("SELECT * FROM BenchmarkData "
                          "WHERE Spec=? and Status=='OK' and DateTime>? "
                          "ORDER BY DateTime", (spec, since))
            else:
                c.execute("SELECT * FROM BenchmarkData "
                          "WHERE Spec=? and Status=='OK' "
                          "ORDER BY DateTime", (spec,))
        else:
            if since:
                c.execute("SELECT * FROM BenchmarkData "
                          "WHERE Status=='OK' and DateTime>? "
                          "ORDER BY DateTime", (since))
            else:
                c.execute("SELECT * FROM BenchmarkData "
                          "WHERE Status=='OK' "
                          "ORDER BY DateTime")

        rows = c.fetchall()

        if not rows:
            logging.warning("No data to export for %s", spec)
            return

        if filename:
            with open(filename,'w') as f:
                f.write(col_names)
                for row in rows:
                    f.write(','.join([str(col) for col in row]))
        else:
            print(col_names)
            for row in rows:
                print(','.join([str(col) for col in row]))

        return filename

    def backup(self):
        """
        create a local backup database, rsync it to destination
        """
        name = self.dbname

        # first save the previous backup, if any
        save_cmd = "mv -f " + name + ".bak " + name + ".prev"
        code, out, err = execute_cmd(save_cmd)

        # create a new backup of the current database and upload it
        backup_cmd = "sqlite3 " + name + " \".backup " + name + ".bak\""
        code, out, err = execute_cmd(backup_cmd)
        if not code:
            try:
                dest = conf["data"]["upload"]
                rsync_cmd = "rsync -zvh " + name + ".bak " + dest + "/" + name
                code, out, err = execute_cmd(rsync_cmd)
            except KeyError:
                pass  # remote backup not configured
            except:
                logging.error("ERROR attempting remote backup")
                logging.error(traceback.format_exc())

    def clean_data(self):
        """
        Clean the database
        """
        self._ensure_commits()
        self._ensure_benchmark_data()

        min_time = datetime(2018,7,1,0,0).timestamp()
        max_time = datetime.now().timestamp()
        print(f"{min_time=} {max_time=}")

        for db in ['Commits', 'BenchmarkData', 'InstalledDeps']:
            to_delete = []

            with self.connection as c:
                for row in c.execute(f"SELECT * FROM {db} ORDER BY DateTime"):

                    ts = row[0]

                    if ts < min_time or ts > max_time:
                        print(f"Removing data from {db} with invalid timestamp: {ts}, {datetime.fromtimestamp(ts)}")
                        c.execute(f"DELETE FROM {db} WHERE DateTime=?", (ts,))


class BenchmarkRunner(object):
    """
    this class encapsulates the logic required to conditionally run
    a set of benchmarks if a trigger repository is updated
    """
    def __init__(self, project):
        self.project = project

        # load the database
        self.db = BenchmarkDatabase(project["name"])

        if "slack" in conf:
            self.slack = Slack(conf["slack"], conf.get("ca"))
        else:
            self.slack = None

    def run(self, force=False, keep_env=False, unit_tests=False):
        """
        run benchmarks if project or any of its dependencies have changed
        """
        logging.info("\n************************************************"
                     "\nRunning benchmarks for %s"
                     "\n************************************************"
                     % self.project["name"])

        project = self.project
        db = self.db

        current_commits = {}
        triggered_by = []

        # initialize log file
        timestr = time.strftime("%Y%m%d-%H%M%S")
        run_name = project["name"] + "_" + timestr
        init_log_file(run_name)

        # remove any previous repo_dir for this project so we start fresh
        remove_dir(conf["repo_dir"])

        # determine if a new benchmark run is needed, this may be due to the
        # project repo or a trigger repo being updated or the `force` option
        if force:
            triggered_by.append('force')

        triggers = project.get("triggers", [])

        for trigger in triggers + [project["repository"]]:
            if trigger.endswith("/releases"):
                check_release = True
                trigger = trigger[:-9]
            else:
                check_release = False

            if '#' in trigger:
                trigger, branch = trigger.split('#')
            else:
                branch = None

            trigger = os.path.expanduser(trigger)

            # check each trigger for any update since last run
            with repo(trigger, branch):
                logging.info('checking trigger ' + trigger + ' ' + branch if branch else '')
                current_commits[trigger] = get_current_commit(trigger)
                logging.info("Curr CommitID: %s", current_commits[trigger])
                last_commit = str(db.get_last_commit(trigger))
                logging.info("Last CommitID: %s", last_commit)
                if (last_commit != current_commits[trigger]):
                    if check_release:
                        # new commit, but is it a release?
                        release_tag, release_commit = get_tag_info()
                        if current_commits[trigger] == release_commit:
                            logging.info("There has been a new release for %s\n", trigger)
                            triggered_by.append(trigger)
                    else:
                        logging.info("There has been an update to %s\n", trigger)
                        triggered_by.append(trigger)

        # if benchmark run is triggered:
        # - check to see if this set of commits has failed
        # - if commits have not failed or forced, run unit tests
        # - run the benchmark
        # - save benchmark results to database
        # - clean up env and repos
        # - back up database
        if triggered_by:
            logging.info("Benchmark triggered by updates to: %s", str(triggered_by))
            trigger_msg = self.get_trigger_message(triggered_by, current_commits)

            conda_spec =  project.get("conda", [])
            dependencies = project.get("dependencies", [])

            # if unit testing fails, the current set of commits will be recorded in fail_file
            fail_file = os.path.join(conf['working_dir'], project["name"]+".fail")

            # start out assuming we have a good set of commits
            good_commits = True

            # if unit testing is enabled, then check that we have not already failed unit testing
            if unit_tests:
                if os.path.exists(fail_file):
                    good_commits = False
                    failed_commits = read_json(fail_file)
                    for key in current_commits:
                        if current_commits[key] != failed_commits[key]:
                            # there has been a new commit, set flag to run and delete fail_file
                            logging.info("found new commit for %s", key)
                            logging.info("old commit: %s", failed_commits[key])
                            logging.info("new commit: %s", current_commits[key])
                            good_commits = True
                            os.remove(fail_file)
                            break

                if not good_commits:
                    logging.info("This set of commits has already failed unit testing.")

            forced = 'force' in triggered_by

            if good_commits or forced:

                # make sure our working repo dir exists
                repo_dir = conf["repo_dir"]
                if not os.path.exists(repo_dir):
                    os.makedirs(repo_dir)

                # create script & run (in the repo directory)
                with cd(repo_dir):
                    repo_name = project["repository"].split('/')[-1]
                    if '#' in repo_name:
                        repo_name = repo_name.split('#')[0]

                    notify = project.get("notify", ["!channel"])

                    # reset flag
                    good_commits = True

                    # run tests and benchmarks
                    script = project.get("script")
                    if script:
                        # script has been provided, just run it and check return code
                        logging.info("Running predefined script: %s" % script)
                        rc, out, err = execute_cmd(script, shell=True, combine=True)
                        if rc:
                            good_commits = False
                            self.slack.post_message("%s However, testing failed..." % trigger_msg, notify=notify)
                        else:
                            self.slack.post_message("%s Testing was successful." % trigger_msg)
                        if out:
                            test_log = os.path.join(repo_name, "%s.txt" % run_name)
                            with open(test_log, "w") as f:
                                f.write(out)
                            self.slack.post_file(test_log,
                                                 "\"%s : See attached output file.\"" % self.project["name"])
                    else:
                        # generate script and then run it
                        script = RunScript(run_name, project, unit_tests, keep_env)
                        script.execute()

                        # check for failed unit tests
                        if unit_tests:
                            test_log = os.path.join(repo_name, "%s.log" % run_name)
                            logging.info("unit test results file: %s", test_log)
                            for line in open(test_log):
                                if line.startswith("Failed:"):
                                    logging.info("test failures (%s): %s", line.split()[1], line)
                                    test_failures = line.split()[1]
                                    if  test_failures != "0":
                                        good_commits = False
                                        if self.slack:
                                            logging.error("%s However, %s unit test(s) failed...", trigger_msg, test_failures)
                                            self.slack.post_message("%s However, %s unit test(s) failed..." % (trigger_msg, test_failures), notify=notify)
                                            self.slack.post_file(test_log,
                                                                 "\"%s : regression testing has failed. See attached results file.\"" % self.project["name"])

                        # check for failed benchmarks
                        if good_commits or forced or not unit_tests:
                            benchmark_log = os.path.join(repo_name, "%s-bm.log" % run_name)
                            logging.info("benchmark results file: %s", benchmark_log)
                            for line in open(benchmark_log):
                                if line.startswith("Failed:"):
                                    logging.info("benchmark failures (%s): %s", line.split()[1], line)
                                    benchmark_fails = line.split()[1]
                                    if benchmark_fails != "0":
                                        good_commits = False
                                        if self.slack:
                                            logging.error("%s However, %s benchmark(s) failed...", trigger_msg, benchmark_fails)
                                            self.slack.post_message("%s However, %s benchmark(s) failed..." % (trigger_msg, benchmark_fails), notify=notify)
                                            self.slack.post_file(benchmark_log,
                                                                 "\"%s : benchmarking has failed. See attached results file.\"" % self.project["name"])

                    if good_commits:
                        # get list of installed dependencies
                        installed_deps = {}
                        with conda(run_name):
                            rc, out, err = execute_cmd("conda list")
                        for line in out.split('\n'):
                            name_ver = line.split(" ", 1)
                            if len(name_ver) == 2:
                                installed_deps[name_ver[0]] = name_ver[1]

                        # update database with benchmark resuls
                        csv_file = os.path.join(repo_name, "%s.csv" % run_name)
                        if os.path.exists(csv_file):
                            db.add_benchmark_data(current_commits, csv_file, installed_deps)
                            self.post_results(trigger_msg)
                            if conf["remove_csv"]:
                                os.remove(csv_file)
                        else:
                            # no benchmarks, just record the commits that passed testing
                            timestamp = time.time()
                            db.update_commits(current_commits, timestamp)
                    else:
                        write_json(fail_file, current_commits)


                if good_commits:
                    # if benchmarks didn't fail but there are no commits in database, then
                    # no benchmarks are defined so don't run again for this set of commits
                    if not db.get_last_commit(project["repository"]):
                        write_json(fail_file, current_commits)
                    else:
                        # back up and transfer database
                        db.backup()

        # close the log file for this run
        close_log_file()

    def post_results(self, trigger_msg):
        """
        generate plots and post a message to slack detailing benchmark results
        """
        db = self.db
        name = self.project["name"]

        # generate summary plots if requested and upload if image location is provided
        image_url = None
        summary_plots = []

        if conf["plot_history"]:
            summary_plots = db.plot_benchmarks(save=True, show=False)
            if conf.get("images") and summary_plots:
                rc, _, _ = upload(summary_plots, conf["images"]["upload"])
                if rc == 0:
                    image_url = conf["images"]["url"]

        # if slack info is provided, post message and plots to slack
        if self.slack:
            # post message that benchmarks were run
            self.slack.post_message(trigger_msg + "\nBenchmarking was successful.")

            # post summary plots
            if summary_plots and image_url:
                for plot_file in summary_plots:
                    self.slack.post_image("", "/".join([image_url, plot_file]))
            else:
                self.slack.post_message("No benchmark history plots generated.")

            # check benchmarks for significant changes & post any resulting messages
            cpu_messages, mem_messages = db.check_benchmarks()
            # notify = "<!channel> The following %s benchmarks had a significant change in %s:\n"
            notify = "The following %s benchmarks had a significant change in %s:\n"

            # post max_messages at a time
            max_messages = 9

            if cpu_messages:
                self.slack.post_message(notify % (name, "elapsed time"))
                while cpu_messages:
                    msg = '\n'.join(cpu_messages[:max_messages])
                    self.slack.post_message(msg)
                    cpu_messages = cpu_messages[max_messages:]
                if os.path.exists("top.txt"):
                    self.slack.post_file("top.txt", "Top 10 CPU before and after")

            if mem_messages:
                self.slack.post_message(notify % (name, "memory usage"))
                while mem_messages:
                    msg = '\n'.join(mem_messages[:max_messages])
                    self.slack.post_message(msg)
                    mem_messages = mem_messages[max_messages:]

    def get_trigger_message(self, triggered_by, current_commits):
        """
        list specific commits (in link form) that triggered benchmarks to run
        """
        name = self.project["name"]

        if "url" in conf:
            pretext = "<%s|%s> benchmarks triggered by " % (conf["url"]+name, name)
        else:
            pretext = "*%s* benchmarks triggered by " % name

        if "force" in triggered_by:
            pretext = pretext + "force:\n"
        else:
            links = []
            # add the specific commit information to each trigger
            for url in triggered_by:
                if "bitbucket" in url:
                    commit = "/commits/"
                else:
                    commit = "/commit/"
                links.append(url + commit + str(current_commits[url]).strip('\n'))

            # insert proper formatting so long URL text is replaced by short trigger-name hyperlink
            links = ["<%s|%s>" % (url.replace("git@github.com:", "https://github.com/"), url.split('/')[-3])
                     for url in links]

            pretext = pretext + "updates to: " + ", ".join(links) + "\n"

        return pretext


#
# command line
#

def _get_parser():
    """
    Returns a parser to handle command line args.
    """

    parser = ArgumentParser()
    parser.usage = "benchmark [options]"

    parser.add_argument('projects', metavar='project', nargs='*',
                        help='project to benchmark (references a JSON file in the working directory)')

    parser.add_argument('-f', '--force', action='store_true', dest='force',
                        help='do the benchmark even if nothing has changed')

    parser.add_argument('-u', '--unit-tests', action='store_true', dest='unit_tests',
                        help='run the unit tests before running the benchmarks.')

    parser.add_argument('-k', '--keep-env', action='store_true', dest='keep_env',
                        help='keep the created conda env after execution (usually for troubleshooting purposes)')

    parser.add_argument('-p', '--plot', metavar='SPEC', action='store', dest='plot',
                        help='plot benchmark history for SPEC')

    parser.add_argument('-c', '--check', action='store_true', dest='check',
                        help='check the most recent benchmark data for significant change')

    parser.add_argument('-d', '--dump', action='store_true', dest='dump',
                        help='dump the contents of the database to an SQL file')

    parser.add_argument('-e', '--export', metavar='SPEC', action='store', dest='export',
                        help='export benchmark history for SPEC in CSV format')

    parser.add_argument('-l', '--clean', action='store_true', dest='clean',
                        help='clean invalid data (i.e. with bad timestamps) from data')


    return parser


def main(args=None):
    """
    process command line arguments and perform requested task
    """
    if args is None:
        args = sys.argv[1:]

    options = _get_parser().parse_args(args)

    # read local configuration if available
    try:
        conf.update(read_json("benchmark.cfg"))
    except IOError:
        logging.info('NOTE: No local configuration found.')

    # initalize logging to stdout
    init_logging()

    # perform the requested operation for each project
    with cd(conf["working_dir"]):
        for project in options.projects:

            # get project info
            if project.endswith(".json"):
                project_file = project
            else:
                project_file = project+".json"
            project_info = read_json(project_file)

            if project_info.get("skip"):  # and not options.force:
                continue

            project_name = os.path.basename(project_file).rsplit('.', 1)[0]
            project_info["name"] = project_name

            init_env(project_info)

            # perform requested action, or just run benchmarks
            if options.plot:
                db = BenchmarkDatabase(project_name)
                if options.plot == 'all':
                    db.plot_benchmarks(save=True, show=True)
                else:
                    db.plot_benchmark_data(options.plot, show=True)
            elif options.dump:
                db = BenchmarkDatabase(project_name)
                db.dump()
            elif options.check:
                db = BenchmarkDatabase(project_name)
                messages = db.check_benchmarks()
                for msg in messages:
                    logging.info(msg)
            elif options.export:
                db = BenchmarkDatabase(project_name)
                db.export_benchmark_data(options.export)
            elif options.clean:
                db = BenchmarkDatabase(project_name)
                db.clean_data()
            else:
                # use a different repo directory for each project
                conf["repo_dir"] = os.path.expanduser(
                    os.path.join(conf["working_dir"], "repos", project_name))

                bm = BenchmarkRunner(project_info)
                try:
                    bm.run(options.force, options.keep_env, options.unit_tests)
                except Exception as err:
                    logging.error("=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=")
                    logging.error('Benchmarking of %s failed:' % project_name)
                    logging.error(str(traceback.format_exc()))
                    logging.error("=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=")
                finally:
                    # make sure we end up back where we started in case of an error
                    os.chdir(os.path.expanduser(conf["working_dir"]))


if __name__ == '__main__':
    sys.exit(main())
