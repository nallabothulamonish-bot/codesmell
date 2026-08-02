"""Archive extraction security tests.

Each test names the attack it defends against. If one of these ever fails, the
platform is remotely exploitable -- these are not refactoring-sensitive unit
tests, they are the security boundary.
"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from codesmell.config.settings import IngestionSettings
from codesmell.core.enums import RejectionReason
from codesmell.core.errors import (
    ArchiveTooLargeError,
    CorruptArchiveError,
)
from codesmell.ingestion.archive import SafeZipExtractor
from codesmell.ingestion.sandbox import Workspace


@pytest.fixture
def extractor(
    ingestion_settings: IngestionSettings, workspace: Workspace
) -> SafeZipExtractor:
    return SafeZipExtractor(ingestion_settings, workspace)


def _reasons(report) -> set[RejectionReason]:
    return {r.reason for r in report.rejections}


# --------------------------------------------------------------------- #
# Zip-slip
# --------------------------------------------------------------------- #


def test_rejects_parent_traversal_member(
    extractor, workspace, malicious_zip, regular_mode, tmp_path
):
    """CWE-22: a member named ../../ must never be written."""
    archive = malicious_zip(
        [
            ("../../pwned.txt", "owned", regular_mode),
            ("app/main.py", "x = 1\n", regular_mode),
        ]
    )

    report = extractor.extract(archive, workspace.source_dir)

    assert RejectionReason.PATH_TRAVERSAL in _reasons(report)
    assert report.files_written == 1
    assert not (tmp_path / "pwned.txt").exists()
    assert not (workspace.root.parent / "pwned.txt").exists()


def test_rejects_deeply_nested_traversal(
    extractor, workspace, malicious_zip, regular_mode
):
    """Traversal buried mid-path is still traversal."""
    archive = malicious_zip(
        [("a/b/../../../../etc/passwd", "root:x:0:0", regular_mode)]
    )

    report = extractor.extract(archive, workspace.source_dir)

    assert report.files_written == 0
    assert RejectionReason.PATH_TRAVERSAL in _reasons(report)


def test_rejects_backslash_traversal(
    extractor, workspace, malicious_zip, regular_mode
):
    """Windows-style separators must not slip past a POSIX-only check."""
    archive = malicious_zip([("..\\..\\pwned.txt", "owned", regular_mode)])

    report = extractor.extract(archive, workspace.source_dir)

    assert report.files_written == 0
    assert RejectionReason.PATH_TRAVERSAL in _reasons(report)


def test_rejects_absolute_posix_path(
    extractor, workspace, malicious_zip, regular_mode
):
    archive = malicious_zip([("/etc/cron.d/backdoor", "* * * * *", regular_mode)])

    report = extractor.extract(archive, workspace.source_dir)

    assert report.files_written == 0
    assert RejectionReason.ABSOLUTE_PATH in _reasons(report)
    assert not Path("/etc/cron.d/backdoor").exists()


def test_rejects_windows_drive_path(
    extractor, workspace, malicious_zip, regular_mode
):
    archive = malicious_zip([("C:/Windows/System32/evil.dll", "MZ", regular_mode)])

    report = extractor.extract(archive, workspace.source_dir)

    assert report.files_written == 0
    assert RejectionReason.ABSOLUTE_PATH in _reasons(report)


# --------------------------------------------------------------------- #
# Symlink and special files
# --------------------------------------------------------------------- #


def test_rejects_symlink_member(
    extractor, workspace, malicious_zip, symlink_mode, regular_mode
):
    """A symlink member would let a later write escape the sandbox."""
    archive = malicious_zip(
        [
            ("link.py", "/etc/passwd", symlink_mode),
            ("app/main.py", "x = 1\n", regular_mode),
        ]
    )

    report = extractor.extract(archive, workspace.source_dir)

    assert RejectionReason.SYMLINK in _reasons(report)
    assert not (workspace.source_dir / "link.py").exists()
    assert report.files_written == 1


def test_rejects_special_file_member(extractor, workspace, malicious_zip):
    """FIFOs, devices and sockets have no place in a source archive."""
    fifo_mode = stat.S_IFIFO | 0o644
    archive = malicious_zip([("pipe", "", fifo_mode)])

    report = extractor.extract(archive, workspace.source_dir)

    assert report.files_written == 0
    assert RejectionReason.SPECIAL_FILE in _reasons(report)


# --------------------------------------------------------------------- #
# Zip bombs and resource exhaustion
# --------------------------------------------------------------------- #


def test_rejects_high_compression_ratio_archive(
    extractor, workspace, tmp_path, ingestion_settings
):
    """A classic bomb: highly compressible payload above the ratio ceiling."""
    archive_path = tmp_path / "bomb.zip"
    payload = "A" * (4 * 1024 * 1024)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bomb.txt", payload)

    with pytest.raises(ArchiveTooLargeError) as exc_info:
        extractor.extract(archive_path, workspace.source_dir)

    assert exc_info.value.code == "archive_too_large"


def test_rejects_archive_declaring_excess_uncompressed_size(
    workspace, tmp_path, ingestion_settings
):
    """Total declared expansion above the budget is refused pre-extraction."""
    tight = ingestion_settings.model_copy(
        update={"max_uncompressed_bytes": 1024, "max_member_bytes": 1024}
    )
    extractor = SafeZipExtractor(tight, workspace)

    archive_path = tmp_path / "big.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("a.py", "x" * 4096)

    with pytest.raises(ArchiveTooLargeError):
        extractor.extract(archive_path, workspace.source_dir)


def test_rejects_too_many_members(workspace, tmp_path, ingestion_settings):
    """Member floods exhaust inodes long before they exhaust disk."""
    tight = ingestion_settings.model_copy(update={"max_members": 5})
    extractor = SafeZipExtractor(tight, workspace)

    archive_path = tmp_path / "many.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as archive:
        for index in range(20):
            archive.writestr(f"file_{index}.py", "x = 1\n")

    with pytest.raises(ArchiveTooLargeError) as exc_info:
        extractor.extract(archive_path, workspace.source_dir)

    assert exc_info.value.details["members"] == 20


def test_rejects_oversized_member(workspace, tmp_path, ingestion_settings):
    """One huge file inside an otherwise fine archive is skipped, not fatal."""
    tight = ingestion_settings.model_copy(
        update={"max_member_bytes": 512, "max_compression_ratio": 10_000.0}
    )
    extractor = SafeZipExtractor(tight, workspace)

    archive_path = tmp_path / "mixed.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("small.py", "x = 1\n")
        archive.writestr("huge.py", "y" * 4096)

    report = extractor.extract(archive_path, workspace.source_dir)

    assert report.files_written == 1
    assert RejectionReason.MEMBER_TOO_LARGE in _reasons(report)
    assert (workspace.source_dir / "small.py").exists()
    assert not (workspace.source_dir / "huge.py").exists()


def test_rejects_archive_over_upload_limit(workspace, tmp_path, ingestion_settings):
    tight = ingestion_settings.model_copy(
        update={"max_archive_bytes": 100, "max_uncompressed_bytes": 100}
    )
    extractor = SafeZipExtractor(tight, workspace)

    archive_path = tmp_path / "over.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("a.py", "x" * 4096)

    with pytest.raises(ArchiveTooLargeError):
        extractor.extract(archive_path, workspace.source_dir)


# --------------------------------------------------------------------- #
# Malformed input
# --------------------------------------------------------------------- #


def test_rejects_corrupt_archive(extractor, workspace, tmp_path):
    archive_path = tmp_path / "corrupt.zip"
    archive_path.write_bytes(b"PK\x03\x04 this is not a real zip file at all")

    with pytest.raises(CorruptArchiveError):
        extractor.extract(archive_path, workspace.source_dir)


def test_rejects_empty_archive_file(extractor, workspace, tmp_path):
    archive_path = tmp_path / "empty.zip"
    archive_path.write_bytes(b"")

    with pytest.raises(CorruptArchiveError):
        extractor.extract(archive_path, workspace.source_dir)


def test_rejects_missing_archive(extractor, workspace, tmp_path):
    with pytest.raises(CorruptArchiveError):
        extractor.extract(tmp_path / "nope.zip", workspace.source_dir)


# --------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------- #


def test_extracts_clean_archive_preserving_structure(
    extractor, workspace, make_zip
):
    archive = make_zip(
        {
            "app/__init__.py": "",
            "app/service.py": "class Service:\n    pass\n",
            "app/util/helpers.py": "def helper():\n    return 1\n",
        }
    )

    report = extractor.extract(archive, workspace.source_dir)

    assert report.files_written == 3
    assert report.rejections == ()
    assert (workspace.source_dir / "app" / "service.py").is_file()
    assert (workspace.source_dir / "app" / "util" / "helpers.py").is_file()
    assert (
        workspace.source_dir / "app" / "service.py"
    ).read_text() == "class Service:\n    pass\n"


def test_everything_written_stays_inside_the_workspace(
    extractor, workspace, malicious_zip, regular_mode, symlink_mode
):
    """The invariant that matters: no byte lands outside the sandbox."""
    archive = malicious_zip(
        [
            ("../escape1.py", "x", regular_mode),
            ("/escape2.py", "x", regular_mode),
            ("a/../../escape3.py", "x", regular_mode),
            ("link", "../../../etc/passwd", symlink_mode),
            ("real/module.py", "x = 1\n", regular_mode),
        ]
    )

    extractor.extract(archive, workspace.source_dir)

    written = [p for p in workspace.root.rglob("*") if p.is_file()]
    assert written, "expected the one legitimate member to be extracted"
    for path in written:
        assert path.resolve().is_relative_to(workspace.root.resolve())


def test_supports_only_configured_suffixes(extractor, tmp_path):
    assert extractor.supports(tmp_path / "project.zip")
    assert extractor.supports(tmp_path / "PROJECT.ZIP")
    assert not extractor.supports(tmp_path / "project.tar.gz")
    assert not extractor.supports(tmp_path / "project.rar")


def test_members_without_unix_mode_bits_are_treated_as_regular_files(
    extractor, workspace, malicious_zip
):
    """Regression: Windows-authored archives and zipfile.writestr() record
    permission bits with no file-type bits. Reading a zero file-type field as
    'special file' rejected every member of every ordinary archive."""
    archive = malicious_zip([("app/main.py", "x = 1\n", 0o644)])

    report = extractor.extract(archive, workspace.source_dir)

    assert report.files_written == 1
    assert report.rejections == ()


def test_explicit_non_regular_file_type_is_still_rejected(
    extractor, workspace, malicious_zip
):
    """The permissive-mode fix must not weaken special-file rejection."""
    archive = malicious_zip([("sock", "", stat.S_IFSOCK | 0o644)])

    report = extractor.extract(archive, workspace.source_dir)

    assert report.files_written == 0
    assert RejectionReason.SPECIAL_FILE in _reasons(report)
