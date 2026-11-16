# -*- coding: utf-8 -*-
"""百科回源 + 入库：把 288 条字段记录挂上可回源链接，导出知识库 JSONL 与索引。"""
from __future__ import annotations
import json
from collections import defaultdict

from common import DATA, read_csv, write_csv

taxa = {r["plant_id"]: r for r in read_csv("taxa_verified.csv")}
rows = read_csv("encyclopedia_entries.csv")

filled = 0
for r in rows:
    t = taxa.get(r["plant_id"], {})
    url = (t.get("wikipedia_url") or "").strip()
    if url:
        r["source_url"] = url
        r["source_status"] = "verified"
        r["license"] = "CC BY-SA 4.0"
        filled += 1
    else:
        r["source_status"] = "pending"
write_csv("encyclopedia_entries.csv", rows)
print("回源", filled, "/", len(rows))

# 知识库：按植物聚合，供 C 直接读
kb = defaultdict(lambda: {"plant_id": "", "fields": {}})
for r in rows:
    e = kb[r["plant_id"]]
    e["plant_id"] = r["plant_id"]
    e["name_cn"] = r["name_cn"]
    e["fields"][r["field"]] = {"content": r["content"], "source_url": r["source_url"],
                               "source_status": r["source_status"]}
with open(DATA / "knowledge_base.jsonl", "w", encoding="utf-8") as f:
    for pid in sorted(kb):
        f.write(json.dumps(kb[pid], ensure_ascii=False) + "\n")

index = {
    "schema": "verda.kb/1.0",
    "generated_at": "2026-11-16",
    "plants": len(kb),
    "entries": len(rows),
    "fields": sorted({r["field"] for r in rows}),
    "verified": sum(1 for r in rows if r["source_status"] == "verified"),
    "files": {"jsonl": "data/knowledge_base.jsonl", "source": "data/encyclopedia_entries.csv"},
}
(DATA / "kb_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
print("kb", index["plants"], "plants", index["entries"], "entries", index["verified"], "verified")
