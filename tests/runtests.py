from pathlib import Path
import subprocess
import sys


def main():
    test_dir = Path(__file__).resolve().parent
    tests = sorted(
        test for test in test_dir.glob("[A-Za-z]*.py")
        if test.name != "runtests.py" and test.is_file()
    )
    if not tests:
        print("No test scripts found.", file=sys.stderr)
        return 1

    (test_dir / "output").mkdir(exist_ok=True)
    failures = []
    for test in tests:
        print("%s ..." % test.name, flush=True)
        try:
            result = subprocess.run([sys.executable, test.name], cwd=str(test_dir))
        except OSError as error:
            print("Failed to run %s: %s" % (test.name, error), file=sys.stderr)
            failures.append(test.name)
            continue
        if result.returncode:
            failures.append(test.name)

    print("Done. %s passed, %s failed." % (len(tests) - len(failures), len(failures)))
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
