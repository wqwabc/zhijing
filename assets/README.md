# assets 目录说明

本目录存放图片，交付时为空是正常的：素材与案例由 `scripts/collect.py` 采集后写入。

```text
assets/
├─ inbox/Pxx/                 原始候选图（不直接上线，保留以便复核与换源）
│  └─ _candidates.jsonl       候选元数据：来源、作者、许可、尺寸、sha1
├─ cutout/Pxx/                去底成品
│  ├─ Pxx_front_源.png        RGBA，长边 ≤1600，命名见说明文档 2.5
│  └─ ..._preview.jpg         棋盘格预览，给人眼检查用
└─ cases/                     案例原图，命名 {style}_{room}_{序号}.jpg
```

规则：

- `cutout/` 里的每张 PNG 必须在 `data/license_table.csv` 有一行授权，缺行会被 `package.py` 报出来；
- `inbox/` 的图不参与合成，只作为换源与追溯依据，可以定期清理；
- 文件名一旦入库不要改，`assets_manifest.csv` 与 `assets_index.json` 都按文件名关联。

采集与去底的完整流程见说明文档第 2 节，质检阈值见第 7 节。
