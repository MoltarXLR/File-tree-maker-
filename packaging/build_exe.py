"""Build dist/FolderTemplateMaker.exe with PyInstaller (run this on Windows).

    python packaging/build_exe.py

Needs:  pip install pyinstaller
The build uses the committed assets/icon.ico, so Pillow is not needed.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from foldertemplatemaker import APP_NAME, __version__  # noqa: E402

EXE_NAME = "FolderTemplateMaker"


def version_resource_text(version: str) -> str:
    """The text of a PyInstaller 'version file' - the details shown in the exe's Properties."""
    numbers = (version.split(".") + ["0", "0", "0", "0"])[:4]
    tuple_text = ", ".join(str(int(n)) for n in numbers)
    dotted = ".".join(str(int(n)) for n in numbers)
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({tuple_text}),
    prodvers=({tuple_text}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', ''),
        StringStruct('FileDescription', '{APP_NAME}'),
        StringStruct('FileVersion', '{dotted}'),
        StringStruct('InternalName', '{EXE_NAME}'),
        StringStruct('OriginalFilename', '{EXE_NAME}.exe'),
        StringStruct('ProductName', '{APP_NAME}'),
        StringStruct('ProductVersion', '{dotted}')])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> int:
    try:
        import PyInstaller.__main__ as pyinstaller
    except ImportError:
        print("PyInstaller isn't installed.  Run:  python -m pip install pyinstaller")
        return 1

    build_dir = os.path.join(ROOT, "build")
    os.makedirs(build_dir, exist_ok=True)
    version_file = os.path.join(build_dir, "version_info.txt")
    with open(version_file, "w", encoding="utf-8") as handle:
        handle.write(version_resource_text(__version__))

    arguments = [
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",                      # no black console window
        "--name", EXE_NAME,
        "--icon", os.path.join(ROOT, "assets", "icon.ico"),
        "--version-file", version_file,
        "--paths", ROOT,
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(build_dir, "work"),
        "--specpath", build_dir,
        os.path.join(ROOT, "FolderTemplateMaker.pyw"),
    ]
    pyinstaller.run(arguments)
    exe = os.path.join(ROOT, "dist", EXE_NAME + (".exe" if os.name == "nt" else ""))
    if not os.path.isfile(exe):
        print("The build did not produce", exe)
        return 1
    print("\nBuilt:", exe, "(%.1f MB)" % (os.path.getsize(exe) / 1048576.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
