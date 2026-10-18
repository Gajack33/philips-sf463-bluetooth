"""Run the complete offline verification and write a machine-readable proof.

Uses an existing compiler, JDK and GCC (WSL GCC on Windows). Downloads nothing,
opens no device connection, and never exports a complete firmware image or APK.
Each command has its own log; failed/skipped checks never produce passed=true.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sf463_verify_builder", ROOT / "firmware/build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


def verification_inputs():
    paths = {ROOT / "requirements-analysis.txt", ROOT / "app/build.py", ROOT / "app/AndroidManifest.xml"}
    for directory, suffixes in ((ROOT / "firmware", {".c", ".h", ".S", ".ld", ".py"}),
                                (ROOT / "app/src", {".java"}),
                                (ROOT / "app/tests", {".java"}),
                                (ROOT / "app/res", {".xml"})):
        paths.update(path for path in directory.rglob("*") if path.is_file() and path.suffix in suffixes)
    paths.update((ROOT / "reproduction").glob("*.py"))
    return {path.relative_to(ROOT).as_posix(): build.digest(path.read_bytes()) for path in sorted(paths)}


def unittest_result(output, minimum):
    matches = re.findall(r"^(test_\S+) \(([^)]+)\) \.\.\. ok\s*$", output, re.MULTILINE)
    ids = [owner if owner.endswith("." + method) else owner + "." + method for method, owner in matches]
    counts = re.findall(r"^Ran (\d+) tests? in ", output, re.MULTILINE)
    count = int(counts[-1]) if counts else 0
    passed = (count >= minimum and len(ids) == count and len(set(ids)) == count
              and re.search(r"^OK\s*$", output, re.MULTILINE) is not None)
    return passed, count, ids


def to_wsl(path):
    path = PureWindowsPath(str(Path(path).resolve()))
    if not path.drive or not re.fullmatch(r"[A-Za-z]:", path.drive):
        raise ValueError("WSL verification requires an ordinary Windows drive path")
    return "/mnt/" + path.drive[0].lower() + "/" + "/".join(path.parts[1:])


class Verification:
    def __init__(self, output, environment):
        self.output, self.environment = output, environment
        self.stages = []

    def command(self, name, command, *, parser=None):
        command = [str(value) for value in command]
        log = self.output / (name + ".log")
        try:
            result = subprocess.run(command, cwd=ROOT, env=self.environment, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=600)
            text = result.stdout.decode("utf-8", errors="replace")
            code = result.returncode
        except (OSError, subprocess.TimeoutExpired) as error:
            text, code = str(error), -1
        log.write_text(text, encoding="utf-8")
        stage = {"name": name, "command": command, "exit_code": code, "passed": code == 0,
                 "log": log.name, "log_sha256": build.digest(log.read_bytes()), "test_count": 0, "tests": []}
        if parser is not None:
            parsed, count, ids = parser(text)
            stage.update({"passed": stage["passed"] and parsed, "test_count": count, "tests": ids})
        self.stages.append(stage)
        print(f"{'PASS' if stage['passed'] else 'FAIL'} {name}" +
              (f" ({stage['test_count']} tests)" if stage["test_count"] else ""), flush=True)
        if not stage["passed"]:
            print(text[-3000:], file=sys.stderr, flush=True)
        return stage


def host_core_result(text):
    ids = re.findall(r"^(test_\S+) PASS\s*$", text, re.MULTILINE)
    summary = re.findall(r"^(\d+)/(\d+) passed; runtime=(\d+) bytes\s*$", text, re.MULTILINE)
    count, expected, size = map(int, summary[-1]) if summary else (0, 0, 0)
    return count >= 14 and count == expected == len(ids) and 0 < size <= 640, count, ids


def app_result(text):
    ids = re.findall(r"^PASS (test\S+)\s*$", text, re.MULTILINE)
    counts = re.findall(r"^(\d+) host-Java tests passed\s*$", text, re.MULTILINE)
    count = int(counts[-1]) if counts else 0
    privacy = "PASS manifestPrivacy: no application permissions, no window retrieval or window events" in text
    return count >= 22 and count == len(ids) and privacy, count, ids


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", help="Existing Zig or Clang executable")
    parser.add_argument("--java-home", type=Path, help="Optional existing JDK; never installs one")
    parser.add_argument("--out", required=True, type=Path, help="Verification directory outside this repository")
    args = parser.parse_args(argv)
    output = args.out.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("Verification output must be outside the repository")
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    if args.compiler:
        environment["SF463_COMPILER"] = args.compiler
    if args.java_home:
        java_bin = args.java_home.resolve() / "bin"
        if not (java_bin / ("java.exe" if os.name == "nt" else "java")).is_file():
            parser.error("--java-home must identify an existing JDK")
        environment["PATH"] = str(java_bin) + os.pathsep + environment.get("PATH", "")
    runner = Verification(output, environment)
    before = verification_inputs()
    production = build.source_hashes()
    hooks = json.loads((ROOT / "firmware/hooks.json").read_text(encoding="utf-8"))
    hook_sha256 = build.hook_digest(hooks)
    compiler = build.compiler_command(args.compiler or environment.get("SF463_COMPILER"))
    runner.command("compiler", compiler + ["--version"])
    for name, script, minimum in (("baseline-front", "verify_front_hid_candidate.py", 5),
                                  ("baseline-diagnostic", "verify_diagnostic_candidate.py", 6)):
        runner.command(name, [sys.executable, str(ROOT / "reproduction" / script)],
                       parser=lambda text, minimum=minimum: unittest_result(text, minimum))
    runner.command("firmware-tests", [sys.executable, "-m", "unittest", "discover", "-s",
                   "firmware/tests", "-p", "test_*.py", "-v"],
                   parser=lambda text: unittest_result(text, 51))
    # Temporary host executable is created beneath the explicit output scope;
    # only this freshly created child is cleaned up when both processes exit.
    with tempfile.TemporaryDirectory(prefix="host-core-", dir=output) as temporary:
        temporary = Path(temporary).resolve()
        if temporary.parent != output:
            raise ValueError("Unexpected temporary host-build scope")
        executable = temporary / "sf463-core-tests"
        sources = [ROOT / "firmware/core/sf_core.c", ROOT / "firmware/core/test_sf_core.c"]
        flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", "-g", "-fno-omit-frame-pointer",
                 "-fsanitize=address,undefined"]
        if os.name == "nt":
            wsl = shutil.which("wsl.exe") or "wsl.exe"
            compile_command = [wsl, "--exec", "gcc", *flags, *(to_wsl(path) for path in sources), "-o", to_wsl(executable)]
            run_command = [wsl, "--exec", "env", "ASAN_OPTIONS=detect_leaks=1:halt_on_error=1",
                           "UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1", to_wsl(executable)]
        else:
            compile_command = ["gcc", *flags, *sources, "-o", executable]
            run_command = ["env", "ASAN_OPTIONS=detect_leaks=1:halt_on_error=1",
                           "UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1", executable]
        compiled = runner.command("host-core-compile", compile_command)
        if compiled["passed"]:
            runner.command("host-core-tests", run_command, parser=host_core_result)
    runner.command("companion-host", [sys.executable, str(ROOT / "app/build.py"), "--test-only"], parser=app_result)
    variant_images = {}
    for variant in ("diagnostic", "usage"):
        destination = output / variant
        stage = runner.command("build-" + variant, [sys.executable, str(ROOT / "firmware/build.py"),
            "--variant", variant, "--compiler", compiler[0], "--check", "--out", destination])
        if stage["passed"]:
            check = json.loads((destination / "check.json").read_text(encoding="utf-8"))
            if (check.get("hardware_validated") is not False or check["sources"] != production
                    or check["integration_hook_sha256"] != hook_sha256):
                stage["passed"] = False
                stage["error"] = "Build provenance changed or incorrectly claimed hardware validation"
            else:
                variant_images[variant] = check["image_sha256"]
    after = verification_inputs()
    current_hooks = json.loads((ROOT / "firmware/hooks.json").read_text(encoding="utf-8"))
    stable = before == after and build.source_hashes() == production and build.hook_digest(current_hooks) == hook_sha256
    tests = [stage["name"] + ":" + name for stage in runner.stages for name in stage["tests"]]
    passed = stable and len(variant_images) == 2 and all(stage["passed"] for stage in runner.stages)
    report = {"schema": 1, "passed": passed, "scope": "offline-software-only", "hardware_validated": False,
              "flashed": False, "published": False, "inputs_unchanged": stable,
              "test_count": sum(stage["test_count"] for stage in runner.stages), "tests": tests,
              "stages": runner.stages, "sources": production, "verification_inputs": before,
              "integration_hook_sha256": hook_sha256, "variant_images": variant_images,
              "limitations": ["Native ROM/RTOS/BLE/allocator contracts are explicit fixtures.",
                  "Radio, real allocation margins, all hardware keys, long standby and battery current remain unvalidated.",
                  "Unicorn write-hook limitation in factory unaligned memcpy is documented in the adapter suites."]}
    report_file = output / "verification.json"
    report_file.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "test_count": report["test_count"],
                      "variant_images": variant_images, "proof": str(report_file)}), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
