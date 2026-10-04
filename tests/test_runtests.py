from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.tests = self.root / "tests"
        self.tests.mkdir()
        shutil.copyfile(Path(__file__).with_name("runtests.py"), self.tests / "runtests.py")

    def run_runner(self, cwd):
        return subprocess.run(
            [sys.executable, str(self.tests / "runtests.py")],
            cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True,
        )

    def test_root_invocation_uses_test_directory_and_current_interpreter(self):
        (self.root / "setup.py").write_text("raise RuntimeError('not a test')\n")
        (self.tests / "example.py").write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "assert sys.executable == %r\n"
            "Path('output/result.txt').write_text('passed')\n" % sys.executable
        )

        result = self.run_runner(self.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.tests / "output/result.txt").read_text(), "passed")
        self.assertIn("1 passed, 0 failed", result.stdout)
        self.assertNotIn("setup.py", result.stdout)

    def test_test_directory_invocation_still_works(self):
        (self.tests / "example.py").write_text("print('example ran')\n")

        result = self.run_runner(self.tests)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("example ran", result.stdout)

    def test_failure_is_reported_and_remaining_scripts_run(self):
        (self.tests / "a_failure.py").write_text("raise SystemExit(7)\n")
        (self.tests / "b_success.py").write_text("print('remaining script ran')\n")

        result = self.run_runner(self.root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("remaining script ran", result.stdout)
        self.assertIn("1 passed, 1 failed", result.stdout)

    def test_empty_suite_fails(self):
        result = self.run_runner(self.root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No test scripts found", result.stderr)


if __name__ == "__main__":
    unittest.main()
