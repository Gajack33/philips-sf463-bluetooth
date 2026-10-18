"""No-Gradle native Android builder; uses only an existing SDK/JDK and Python stdlib.

Run --test-only for pure host-Java checks. Signing identity is private, outside Git.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent


def run(*args, env=None):
    completed = subprocess.run([str(x) for x in args], capture_output=True, env=env)
    output = completed.stdout.decode(errors="replace") + completed.stderr.decode(errors="replace")
    if completed.returncode:
        raise RuntimeError(f"{Path(str(args[0])).name} failed ({completed.returncode}):\n{output}")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-root", type=Path)
    parser.add_argument("--private-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build" / "artifacts")
    parser.add_argument("--test-only", action="store_true")
    args = parser.parse_args()
    java = Path(shutil.which("java") or "java").resolve().parent
    suffix = ".exe" if os.name == "nt" else ""
    javac, runtime = java / ("javac" + suffix), java / ("java" + suffix)
    build = ROOT / "build"
    host = build / "host-tests"
    host.mkdir(parents=True, exist_ok=True)
    core = sorted((ROOT / "src/fr/local/tv/sf463/core").glob("*.java"))
    tests = sorted((ROOT / "tests").rglob("*.java"))
    run(javac, "-encoding", "UTF-8", "--release", "8", "-d", host, *core, *tests)
    test_output = run(runtime, "-ea", "-cp", host, "fr.local.tv.sf463.core.CoreTests")
    print(test_output, end="", flush=True)
    # Privacy checks are assertions against shipped files, not claims about a device run.
    manifest_text = (ROOT / "AndroidManifest.xml").read_text(encoding="utf-8")
    service_text = (ROOT / "res/xml/key_service.xml").read_text(encoding="utf-8")
    assert "<uses-permission" not in manifest_text, "Companion must not request runtime/network/Bluetooth permissions"
    assert 'android:canRetrieveWindowContent="false"' in service_text
    assert 'android:accessibilityEventTypes=' not in service_text  # Default is no subscribed event types.
    print("PASS manifestPrivacy: no application permissions, no window retrieval or window events", flush=True)
    if args.test_only:
        return
    if args.sdk_root is None or args.private_dir is None:
        parser.error("APK build requires --sdk-root and --private-dir (outside the repository)")
    sdk = args.sdk_root.resolve()
    tool_candidates = sorted(sdk.glob("build-tools*/**/aapt2" + suffix))
    android_candidates = sorted(sdk.glob("platforms*/**/android.jar"))
    if not tool_candidates or not android_candidates:
        raise RuntimeError("Expected an existing SDK with aapt2/build-tools and android.jar/platforms")
    tools, android = tool_candidates[-1].parent, android_candidates[-1]
    private = args.private_dir.resolve()
    if private == ROOT or ROOT in private.parents or ROOT.parent in private.parents:
        raise RuntimeError("Signing identity must live outside the Git repository")
    private.mkdir(parents=True, exist_ok=True)
    key = private / "sf463-companion.p12"
    password_file = private / "sf463-companion.password"
    environment = os.environ.copy()
    if key.exists():
        if not password_file.exists():
            raise RuntimeError("Preserve the signing identity; its dedicated password file is missing")
        environment["SF463_BUILD_PASSWORD"] = password_file.read_text(encoding="utf-8").strip()
    else:
        if password_file.exists():
            raise RuntimeError("A dedicated signing password exists without its key; inspect the private directory")
        password = secrets.token_urlsafe(36)
        password_file.write_text(password, encoding="utf-8")
        environment["SF463_BUILD_PASSWORD"] = password
        run(java / ("keytool" + suffix), "-genkeypair", "-keystore", key, "-storetype", "PKCS12",
            "-alias", "sf463-companion", "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
            "-dname", "CN=SF463 local companion", "-storepass:env", "SF463_BUILD_PASSWORD",
            "-keypass:env", "SF463_BUILD_PASSWORD", env=environment)
    classes, dex = build / "classes", build / "dex"
    classes.mkdir(exist_ok=True)
    dex.mkdir(exist_ok=True)
    sources = sorted((ROOT / "src").rglob("*.java"))
    run(javac, "-encoding", "UTF-8", "--release", "8", "-classpath", android, "-d", classes, *sources)
    # Supply every compiled class explicitly; no Gradle download, plugin or production dependency.
    run(runtime, "-cp", tools / "lib/d8.jar", "com.android.tools.r8.D8", "--min-api", "26",
        "--lib", android, "--output", dex, *sorted(classes.rglob("*.class")))
    resources = build / "resources.zip"
    run(tools / ("aapt2" + suffix), "compile", "--dir", ROOT / "res", "-o", resources)
    unsigned, aligned = build / "unsigned.apk", build / "aligned.apk"
    run(tools / ("aapt2" + suffix), "link", "-o", unsigned, "-I", android,
        "--manifest", ROOT / "AndroidManifest.xml", resources)
    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as apk:
        apk.write(dex / "classes.dex", "classes.dex")
    run(tools / ("zipalign" + suffix), "-f", "4", unsigned, aligned)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    signed = output / "SF463-Companion-0.1.0.apk"
    run(runtime, "-jar", tools / "lib/apksigner.jar", "sign", "--ks", key,
        "--ks-key-alias", "sf463-companion", "--ks-pass", "env:SF463_BUILD_PASSWORD",
        "--out", signed, aligned, env=environment)
    run(runtime, "-jar", tools / "lib/apksigner.jar", "verify", "--verbose", signed)
    badging = run(tools / ("aapt2" + suffix), "dump", "badging", signed)
    assert "sdkVersion:'26'" in badging and "targetSdkVersion:'34'" in badging
    assert "uses-permission:" not in badging
    report = {
        "apk": signed.name, "bytes": signed.stat().st_size,
        "sha256": hashlib.sha256(signed.read_bytes()).hexdigest(),
        "minSdk": 26, "targetSdk": 34, "hostTests": test_output.strip().splitlines(),
        "signatureVerified": True, "applicationPermissions": [],
        "deviceInstalled": False, "accessibilityEnabled": False,
        "deviceValidation": "Pending: TV UI, SAF, accessibility key dispatch, application/HDMI launches and reboot",
    }
    (output / "companion-build.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"apk": str(signed), "bytes": report["bytes"], "sha256": report["sha256"], "signatureVerified": True}), flush=True)


if __name__ == "__main__":
    main()
