# core/filesystems.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class FsSpec:
    id: str
    display: str
    unix_mkfs_cmd: Sequence[str]  # prefix; you append <LABEL> <DEV>
    windows_diskpart_fs: str
    macos_diskutil_fs: str
    cross_platform: bool = True
    notes: str = ""


FS = {
    "exfat": FsSpec(
        id="exfat",
        display="exFAT",
        unix_mkfs_cmd=("mkfs.exfat", "-n"),
        windows_diskpart_fs="exfat",
        macos_diskutil_fs="ExFAT",
        cross_platform=True,
        notes="Best default; supports large files across OSes.",
    ),
    "fat32": FsSpec(
        id="fat32",
        display="FAT32",
        unix_mkfs_cmd=("mkfs.fat", "-F", "32", "-n"),  # dosfstools
        windows_diskpart_fs="fat32",
        macos_diskutil_fs="MS-DOS",
        cross_platform=True,
        notes="Max compatibility but 4GB file limit.",
    ),
    "ntfs": FsSpec(
        id="ntfs",
        display="NTFS",
        unix_mkfs_cmd=("mkfs.ntfs", "-f", "-L"),  # needs ntfs-3g tools
        windows_diskpart_fs="ntfs",
        macos_diskutil_fs="NTFS",
        cross_platform=False,
        notes="Windows-first; macOS write support is not default.",
    ),
    "ext4": FsSpec(
        id="ext4",
        display="ext4",
        unix_mkfs_cmd=("mkfs.ext4", "-L"),
        windows_diskpart_fs="",
        macos_diskutil_fs="",
        cross_platform=False,
        notes="Linux-only.",
    ),
}


def launcher_fs_spec(crypto_params) -> FsSpec:
    fs_id = getattr(crypto_params, "LAUNCHER_FILESYSTEM_ID", "exfat")
    if fs_id not in FS:
        raise RuntimeError(f"Unsupported launcher filesystem id: {fs_id}")
    return FS[fs_id]
