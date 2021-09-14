"""Test benchmark functions."""
import unittest

import sys
import shutil
import tempfile

from os import path, chdir, getcwd, remove

benchmark_dir = path.dirname(path.dirname(path.abspath(__file__)))
sys.path.append(benchmark_dir)


class TestCase(unittest.TestCase):
    """ Test benchmark functions. """

    def setUp(self):
        self.startdir = getcwd()
        chdir(benchmark_dir)

    def tearDown(self):
        chdir(self.startdir)

    def test_upload_image(self):
        from benchmark import conf, read_json, upload

        conf.update(read_json("benchmark.cfg"))

        try:
            dest = conf["images"]["upload"]
        except KeyError:
            raise unittest.SkipTest("image destination not specified.")

        filename= "dummy_file"
        open(filename, 'a').close()

        rc, out, err = upload([filename], dest)

        remove(filename)

        self.assertEqual(rc, 0)

    def test_post_results(self):
        from benchmark import conf, read_json, BenchmarkRunner

        conf.update(read_json("benchmark.cfg"))

        project_name = 'CADRE'
        try:
            project_info = read_json("%s.json" % project_name)
            project_info["name"] = project_name
        except:
            raise unittest.SkipTest("Invalid project: %s" % project_name)

        runner = BenchmarkRunner(project_info)
        if runner.slack == None:
            raise unittest.SkipTest("Slack is not configured.")

        runner.post_results("Test post of %s benchmark results, please ignore" % project_name)


if __name__ == '__main__':
    unittest.main()
