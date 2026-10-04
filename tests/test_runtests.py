from contextlib import redirect_stderr, redirect_stdout
import errno
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import call, patch


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

    def test_matching_directories_are_not_executed(self):
        directory = self.tests / "a_directory.py"
        directory.mkdir()
        (directory / "__main__.py").write_text("raise RuntimeError('not a script')\n")
        (self.tests / "b_empty_directory.py").mkdir()
        (self.tests / "c_script.py").write_text("print('ordinary script ran')\n")

        result = self.run_runner(self.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ordinary script ran", result.stdout)
        self.assertIn("1 passed, 0 failed", result.stdout)
        self.assertNotIn("directory.py", result.stdout)

    def test_directory_only_suite_is_empty(self):
        (self.tests / "a_directory.py").mkdir()

        result = self.run_runner(self.root)

        self.assertEqual(result.returncode, 1)
        self.assertIn("No test scripts found", result.stderr)
        self.assertNotIn("Done.", result.stdout)

    def test_symlinks_to_regular_scripts_are_run_but_other_links_are_ignored(self):
        target = self.root / "target.py"
        target.write_text("print('linked script ran')\n")
        directory = self.root / "directory"
        directory.mkdir()
        (directory / "__main__.py").write_text("raise RuntimeError('not a script')\n")
        try:
            (self.tests / "a_script.py").symlink_to(target)
            (self.tests / "b_directory.py").symlink_to(directory, target_is_directory=True)
            (self.tests / "c_missing.py").symlink_to(self.root / "missing.py")
        except (OSError, NotImplementedError) as error:
            self.skipTest("Symlinks are unavailable: %s" % error)

        result = self.run_runner(self.root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("a_script.py ...", result.stdout)
        self.assertIn("linked script ran", result.stdout)
        self.assertIn("1 passed, 0 failed", result.stdout)
        self.assertNotIn("b_directory.py", result.stdout)
        self.assertNotIn("c_missing.py", result.stdout)

    def load_runner(self):
        spec = importlib.util.spec_from_file_location("isolated_runner", self.tests / "runtests.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        return runner

    def test_spawn_errors_are_reported_and_remaining_scripts_run(self):
        names = ["a_spawn_error.py", "b_failure.py", "c_success.py"]
        for name in reversed(names):
            (self.tests / name).write_text("pass\n")
        runner = self.load_runner()
        errors = [
            FileNotFoundError(errno.ENOENT, "synthetic missing interpreter"),
            PermissionError(errno.EACCES, "synthetic executable denial"),
            OSError(errno.EAGAIN, "synthetic spawn resource failure"),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__, errno=error.errno):
                stdout, stderr = io.StringIO(), io.StringIO()
                outcomes = [error, subprocess.CompletedProcess([], 7), subprocess.CompletedProcess([], 0)]
                with patch.object(runner.subprocess, "run", side_effect=outcomes) as run, \
                        redirect_stdout(stdout), redirect_stderr(stderr):
                    result = runner.main()

                self.assertEqual(result, 1)
                self.assertEqual(run.call_args_list, [
                    call([sys.executable, name], cwd=str(self.tests)) for name in names
                ])
                self.assertIn("1 passed, 2 failed", stdout.getvalue())
                self.assertIn("a_spawn_error.py", stderr.getvalue())
                self.assertIn(str(error), stderr.getvalue())

    def test_all_spawn_errors_still_produce_a_summary(self):
        names = ["a_first.py", "b_second.py"]
        for name in names:
            (self.tests / name).write_text("pass\n")
        runner = self.load_runner()
        stdout, stderr = io.StringIO(), io.StringIO()
        error = FileNotFoundError(errno.ENOENT, "synthetic missing interpreter")
        with patch.object(runner.subprocess, "run", side_effect=error) as run, \
                redirect_stdout(stdout), redirect_stderr(stderr):
            result = runner.main()

        self.assertEqual(result, 1)
        self.assertEqual(run.call_count, len(names))
        self.assertIn("0 passed, 2 failed", stdout.getvalue())
        for name in names:
            self.assertIn(name, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
