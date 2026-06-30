"""Tiny zero-dependency assertion harness shared by the verify scripts.

No pytest required — each test file builds a Check(), calls .that(...) for each
assertion, and ends with sys.exit(check.report(title)). mass.sh aggregates the
exit codes. Keeps the suite runnable with nothing but the stdlib + requests.
"""
import sys


class Check:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warned = 0
        self._fail_names = []

    def that(self, name, cond):
        """Hard assertion: a False fails the suite."""
        if cond:
            self.passed += 1
            print(f"  PASS  {name}")
        else:
            self.failed += 1
            self._fail_names.append(name)
            print(f"  FAIL  {name}")
        return cond

    def warn(self, name, cond):
        """Soft assertion: a False warns but does NOT fail the suite.

        For conditions that can be legitimately false (market closed, data lag)
        but are worth surfacing.
        """
        if cond:
            self.passed += 1
            print(f"  PASS  {name}")
        else:
            self.warned += 1
            print(f"  WARN  {name}")
        return cond

    def info(self, msg):
        print(f"  ...   {msg}")

    def report(self, title):
        print()
        line = f"{title}: {self.passed} passed"
        if self.warned:
            line += f", {self.warned} warned"
        if self.failed:
            line += f", {self.failed} FAILED -> {self._fail_names}"
        else:
            line += ", 0 failed"
        print(line)
        return 1 if self.failed else 0
