from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from build_release import PREFIX, ZIP_TIMESTAMP, build, sha256
from verify_package import REPO_ROOT, assert_regular_source


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first = root / "first.zip"
        second = root / "second.zip"
        build(first)
        build(second)
        assert sha256(first) == sha256(second)

        with zipfile.ZipFile(first) as archive:
            names = archive.namelist()
            assert PREFIX + "LICENSE" in names
            assert PREFIX + "PACKAGE-MANIFEST.sha256" in names
            assert archive.testzip() is None
            assert all(info.date_time == ZIP_TIMESTAMP for info in archive.infolist())
            assert all(info.filename.startswith(PREFIX) for info in archive.infolist())

        try:
            with patch.object(Path, "is_symlink", return_value=True):
                assert_regular_source(REPO_ROOT / "LICENSE")
        except RuntimeError as exc:
            assert "symbolic links are forbidden" in str(exc)
        else:
            raise AssertionError("release verifier accepted a symbolic link")

    print("PASS: release ZIP is deterministic, valid, and includes the manifest and MIT license")


if __name__ == "__main__":
    main()
