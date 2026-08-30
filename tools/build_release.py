from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

from verify_package import MANIFEST, PREFIX, REPO_ROOT, SKILL_ROOT, assert_regular_source, canonical_bytes, package_sources, verify


ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def write_deterministic(archive: zipfile.ZipFile, name: str, source: Path) -> None:
    assert_regular_source(source)
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.flag_bits |= 0x800
    archive.writestr(info, canonical_bytes(source), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def skill_version() -> str:
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*([^\s]+)\s*$", text, re.MULTILINE)
    if not match:
        raise RuntimeError("SKILL.md has no version")
    return match.group(1)


def build(output: Path | None = None) -> dict[str, object]:
    verification = verify()
    version = skill_version()
    output = output or REPO_ROOT / "dist" / f"codex-desktop-control-{version}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)

    sources = package_sources()
    sources[PurePosixPath(MANIFEST.name)] = MANIFEST
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, source in sorted(sources.items()):
            write_deterministic(archive, PREFIX + relative.as_posix(), source)

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        if archive.testzip() is not None:
            raise RuntimeError("release ZIP integrity check failed")
        if len(names) != len(set(names)):
            raise RuntimeError("release ZIP contains duplicate paths")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or not name.startswith(PREFIX):
                raise RuntimeError(f"unsafe release path: {name}")

    digest = sha256(output)
    checksum = output.with_suffix(output.suffix + ".sha256")
    checksum.write_bytes(f"{digest}  {output.name}\n".encode("ascii"))
    return {
        "ok": True,
        "version": version,
        "zip": str(output),
        "sha256": digest,
        "entries": len(sources),
        "manifest": verification,
        "checksum_file": str(checksum),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a verified Codex Desktop Control release ZIP")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))
