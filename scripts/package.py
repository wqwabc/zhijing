# -*- coding: utf-8 -*-
"""打包与合规审计：生成 sha256 清单、授权覆盖率报告、可提交 zip。

    python package.py
"""
from __future__ import annotations
import hashlib, json, zipfile
from pathlib import Path

from common import ROOT, DATA, TODAY, read_csv

SKIP_DIRS = {".venv-verda", "__pycache__", "dist", ".git"}
SKIP_PREFIX = ("assets/inbox",)
SKIP_SUFFIX = {".zip", ".pyc"}
SKIP_NAMES = {"MANIFEST.json", "sha256sums.txt", "植境Verda-B数据与素材交付说明-v1.0.docx"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    files = [p for p in ROOT.rglob("*")
             if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS)
             and not p.relative_to(ROOT).as_posix().startswith(SKIP_PREFIX)
             and p.suffix.lower() not in SKIP_SUFFIX and p.name not in SKIP_NAMES and not p.name.startswith("~\$")]
    entries = []
    for p in sorted(files):
        rel = p.relative_to(ROOT).as_posix()
        entries.append({"path": rel, "size": p.stat().st_size, "sha256": sha256(p)})

    lic = read_csv("license_table.csv")
    licensed = {r["file_name"] for r in lic}
    asset_files = [e["path"] for e in entries
                   if e["path"].startswith(("assets/cutout/", "assets/cases/"))
                   and not e["path"].endswith("_preview.jpg")]
    missing = [f for f in asset_files if f not in licensed]
    coverage = (len(asset_files) - len(missing)) / len(asset_files) if asset_files else 1.0

    manifest = {
        "package": "植境Verda-B交付包",
        "version": "v1.1",
        "built_at": TODAY,
        "file_count": len(entries),
        "total_bytes": sum(e["size"] for e in entries),
        "license": {"assets": len(asset_files), "rows": len(lic),
                    "missing": missing, "coverage": round(coverage, 3)},
        "files": entries,
    }
    (ROOT / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(ROOT / "sha256sums.txt", "w", encoding="utf-8") as f:
        for e in entries:
            f.write(f'{e["sha256"]}  {e["path"]}\n')

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"植境Verda-B交付包_v1.1_{TODAY}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for e in entries:
            z.write(ROOT / e["path"], e["path"])
    print(f"文件 {len(entries)} 个，{manifest['total_bytes']/1024/1024:.1f}MB")
    print(f"授权覆盖 {coverage:.0%}（{len(asset_files)-len(missing)}/{len(asset_files)}），缺 {len(missing)} 个")
    if missing:
        for m in missing[:10]:
            print("  ! 缺授权行：", m)
    print(f"打包完成：{out}  {out.stat().st_size/1024/1024:.1f}MB")


if __name__ == "__main__":
    main()
