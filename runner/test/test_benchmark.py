"""Test benchmark functions."""
import unittest

import sys
import shutil
import tempfile

from os import path, chdir, getcwd, remove

sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))


class TestCase(unittest.TestCase):
    """ Test benchmark functions. """

    def setUp(self):
        self.startdir = getcwd()
        chdir('..')

    def tearDown(self):
        chdir(self.startdir)

    def test_upload_image(self):
        from benchmark import main, conf, upload
        main(args=[])

        try:
            dest = conf["images"]["upload"]
        except KeyError:
            raise unittest.SkipTest("image destination not specified.")

        filename= "dummy_file"
        open(filename, 'a').close()

        rc, out, err = upload([filename], dest)

        remove(filename)

        self.assertEqual(rc, 0)


if __name__ == '__main__':
    unittest.main()
