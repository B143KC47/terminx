"""Build the Windows package and its release records."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from terminx import __version__  # noqa: E402

RUNTIME = (
    "terminx",
    "rich",
    "psutil",
    "PySide6",
    "PySide6-Essentials",
    "PySide6-Addons",
    "shiboken6",
    "tomlkit",
    "markdown-it-py",
    "mdurl",
    "Pygments",
)


def records(bundle, output):
    notices = bundle / "licenses"
    notices.mkdir(exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", notices / "terminx-MIT.txt")
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", notices / "CPython-LICENSE.txt")
    bootloader = metadata.distribution("pyinstaller")
    for entry in bootloader.files or ():
        if entry.name == "COPYING.txt":
            shutil.copy2(
                bootloader.locate_file(entry), notices / "PyInstaller-COPYING.txt"
            )
    for name, url in {
        "LGPL-3.0.txt": "https://raw.githubusercontent.com/qt/qtbase/v6.11.2/LICENSES/LGPL-3.0-only.txt",
        "GPL-3.0.txt": "https://raw.githubusercontent.com/qt/qtbase/v6.11.2/LICENSES/GPL-3.0-only.txt",
        "GPL-2.0.txt": "https://raw.githubusercontent.com/pyside/pyside-setup/v6.11.2/LICENSES/GPL-2.0-only.txt",
        "OpenSSL-LICENSE.txt": "https://raw.githubusercontent.com/openssl/openssl/openssl-3.5.4/LICENSE.txt",
        "libffi-LICENSE.txt": "https://raw.githubusercontent.com/libffi/libffi/v3.4.6/LICENSE",
    }.items():
        with urllib.request.urlopen(url, timeout=60) as response:
            (notices / name).write_bytes(response.read())
    components = []
    for name in RUNTIME:
        dist = metadata.distribution(name)
        components.append(
            {
                "type": "library",
                "name": dist.metadata["Name"],
                "version": dist.version,
                "purl": f"pkg:pypi/{name.lower()}@{dist.version}",
            }
        )
        target = notices / name
        for entry in dist.files or ():
            if any(
                word in entry.name.casefold()
                for word in ("license", "copying", "copyright")
            ):
                source = Path(dist.locate_file(entry))
                if source.is_file():
                    target.mkdir(exist_ok=True)
                    destination = target / (
                        str(entry).replace("/", "_").replace("\\", "_")
                    )
                    shutil.copy2(source, destination)
    components.extend(
        [
            {"type": "library", "name": "Qt", "version": metadata.version("PySide6")},
            {"type": "library", "name": "CPython", "version": sys.version.split()[0]},
            {
                "type": "library",
                "name": "OpenSSL",
                "version": ssl.OPENSSL_VERSION.split()[1],
            },
            {"type": "library", "name": "SQLite", "version": sqlite3.sqlite_version},
            {
                "type": "library",
                "name": "PyInstaller bootloader",
                "version": metadata.version("pyinstaller"),
            },
        ]
    )
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "terminx",
                "version": __version__,
            }
        },
        "components": components,
    }
    (output / f"terminx-{__version__}-sbom.json").write_text(
        json.dumps(sbom, indent=2) + "\n", encoding="utf-8"
    )
    distributions = sorted(
        (dist.metadata["Name"], dist.version) for dist in metadata.distributions()
    )
    manifest = {
        "application": __version__,
        "python": sys.version,
        "platform": sys.platform,
        "packages": dict(distributions),
        "source": source_record(),
    }
    (output / f"terminx-{__version__}-build.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def source_record():
    paths = set()
    for directory in ("terminx", "tests", "scripts", "packaging", "docs", ".github"):
        paths.update(
            path
            for path in (ROOT / directory).rglob("*")
            if path.is_file()
            and path.suffix in {".py", ".spec", ".iss", ".md", ".json", ".yml"}
        )
    paths.update(
        path
        for path in ROOT.iterdir()
        if path.is_file()
        and (
            path.suffix in {".md", ".toml", ".lock", ".in", ".txt"}
            or path.name in {"LICENSE", ".gitignore", ".gitattributes"}
        )
    )
    files = {}
    overall = hashlib.sha256()
    for path in sorted(paths):
        name = path.relative_to(ROOT).as_posix()
        digest = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        files[name] = digest
        overall.update(name.encode() + b"\0" + digest.encode() + b"\n")
    return {
        "sha256": overall.hexdigest(),
        "newline_normalization": "LF",
        "files": files,
    }


def third_party_sources(output, bundle=None):
    version = metadata.version("PySide6")
    qt_version = ".".join(version.split(".")[:2])
    urls = {
        f"pyside-setup-everywhere-src-{version}.tar.xz": f"https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{version}-src/pyside-setup-everywhere-src-{version}.tar.xz",
    }
    for module in ("qtbase", "qtsvg", "qtimageformats"):
        name = f"{module}-everywhere-src-{version}.tar.xz"
        urls[name] = (
            f"https://download.qt.io/official_releases/qt/{qt_version}/{version}/submodules/{name}"
        )
    downloaded = ROOT / "_artifacts" / "sources"
    downloaded.mkdir(parents=True, exist_ok=True)
    receipt = {}
    archive_path = output / f"terminx-{__version__}-third-party-sources.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as archive:
        for name, url in urls.items():
            target = downloaded / name
            if not target.exists():
                partial = target.with_suffix(target.suffix + ".part")
                with (
                    urllib.request.urlopen(url, timeout=120) as response,
                    partial.open("wb") as stream,
                ):
                    shutil.copyfileobj(response, stream)
                partial.replace(target)
            with tarfile.open(target, "r:xz") as sources:
                for member in sources:
                    if (
                        bundle
                        and member.isfile()
                        and member.size < 1_000_000
                        and any(
                            word in Path(member.name).name.casefold()
                            for word in ("license", "copying", "copyright")
                        )
                    ):
                        notices = bundle / "licenses" / "upstream-source"
                        notices.mkdir(exist_ok=True)
                        identifier = hashlib.sha256(
                            (name + member.name).encode()
                        ).hexdigest()[:16]
                        original = sources.extractfile(member)
                        if original:
                            with original:
                                (
                                    notices
                                    / (identifier + "-" + Path(member.name).name)
                                ).write_bytes(original.read())
            with target.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            receipt[name] = {"source": url, "sha256": digest}
            archive.write(target, name)
        archive.writestr("sources.json", json.dumps(receipt, indent=2) + "\n")


def checksum(output):
    assets = sorted(
        path
        for path in output.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    lines = []
    for path in assets:
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        lines.append(f"{digest}  {path.name}")
    (output / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iscc", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "release")
    args = parser.parse_args()
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise SystemExit("Use 64-bit Python on Windows")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SystemExit("Select an empty release output directory")
    # A second Qt installation on PATH can replace Windows ICU dependencies.
    system = Path(os.environ["SystemRoot"])
    build_environment = dict(os.environ)
    build_environment["PATH"] = os.pathsep.join(
        map(
            str,
            [
                Path(sys.executable).parent,
                Path(sys.base_prefix),
                system / "System32",
                system,
            ],
        )
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            str(ROOT / "packaging" / "terminx.spec"),
        ],
        cwd=ROOT,
        check=True,
        env=build_environment,
    )
    bundle = ROOT / "dist" / "terminx"
    for name in ("README.md", "LICENSE", "SECURITY.md", "CHANGELOG.md"):
        shutil.copy2(ROOT / name, bundle / name)
    shutil.copytree(ROOT / "docs", bundle / "docs", dirs_exist_ok=True)
    records(bundle, output)
    third_party_sources(output, bundle)
    portable = output / f"terminx-{__version__}-windows-x64-portable.zip"
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                archive.write(path, Path("terminx") / path.relative_to(bundle))
    subprocess.run(
        [
            str(args.iscc.resolve()),
            f"/DAppVersion={__version__}",
            f"/DBundleDir={bundle}",
            f"/DOutputDir={output}",
            str(ROOT / "packaging" / "terminx.iss"),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(output)], cwd=ROOT, check=True
    )
    checksum(output)
    print(f"Release files: {output}")


if __name__ == "__main__":
    main()
