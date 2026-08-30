from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "codex-desktop-control"
MANIFEST = SKILL_ROOT / "PACKAGE-MANIFEST.sha256"
PREFIX = "codex-desktop-control/"
IGNORED_PARTS = {"__pycache__"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
REPARSE_POINT = 0x400


def assert_regular_source(path: Path) -> None:
    info = path.lstat()
    if path.is_symlink() or stat.S_ISLNK(info.st_mode):
        raise RuntimeError(f"symbolic links are forbidden in the release: {path}")
    if getattr(info, "st_file_attributes", 0) & REPARSE_POINT:
        raise RuntimeError(f"Windows reparse points are forbidden in the release: {path}")
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"release source is not a regular file: {path}")


def canonical_bytes(path: Path) -> bytes:
    assert_regular_source(path)
    return path.read_bytes().replace(b"\r\n", b"\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(canonical_bytes(path)).hexdigest()


def package_sources() -> dict[PurePosixPath, Path]:
    files: dict[PurePosixPath, Path] = {PurePosixPath("LICENSE"): REPO_ROOT / "LICENSE"}
    for path in SKILL_ROOT.rglob("*"):
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & REPARSE_POINT:
            raise RuntimeError(f"links and reparse points are forbidden in the release tree: {path}")
        if not path.is_file() or path == MANIFEST:
            continue
        relative = path.relative_to(SKILL_ROOT)
        if IGNORED_PARTS.intersection(relative.parts) or path.suffix in IGNORED_SUFFIXES:
            continue
        published = PurePosixPath(relative.as_posix())
        assert_regular_source(path)
        files[published] = path
    return files


def package_files() -> set[PurePosixPath]:
    return set(package_sources())


def verify() -> dict[str, object]:
    if not MANIFEST.is_file():
        raise RuntimeError(f"missing manifest: {MANIFEST}")

    declared: dict[PurePosixPath, str] = {}
    for number, line in enumerate(MANIFEST.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            expected, published = line.split(None, 1)
        except ValueError as exc:
            raise RuntimeError(f"invalid manifest line {number}") from exc
        if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise RuntimeError(f"invalid SHA-256 on manifest line {number}")
        if not published.startswith(PREFIX):
            raise RuntimeError(f"invalid package prefix on manifest line {number}")
        relative = PurePosixPath(published[len(PREFIX) :])
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise RuntimeError(f"unsafe package path on manifest line {number}")
        if relative in declared:
            raise RuntimeError(f"duplicate package path: {relative}")
        declared[relative] = expected

    sources = package_sources()
    actual = set(sources)
    missing_from_manifest = sorted(str(path) for path in actual - declared.keys())
    missing_from_disk = sorted(str(path) for path in declared.keys() - actual)
    mismatched: list[str] = []
    for relative, expected in declared.items():
        path = sources.get(relative)
        if path is not None and sha256(path) != expected:
            mismatched.append(str(relative))

    report = {
        "ok": not (missing_from_manifest or missing_from_disk or mismatched),
        "declared_files": len(declared),
        "missing_from_manifest": missing_from_manifest,
        "missing_from_disk": missing_from_disk,
        "hash_mismatches": mismatched,
    }
    if not report["ok"]:
        raise RuntimeError(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
