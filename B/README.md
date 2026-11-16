# 植境 Verda · B 数据与素材交付包 v1.3

这是《植境 Verda 五人分工表 v2.1》里 **B（数据与素材）** 的交付物集合：36 种植物主数据、288 条字段级百科记录、6 风格 × 5 场景的案例配额与元数据表、可追溯的授权表、以及把「采集 → 去底 → 质检 → 索引 → 打包」串起来的脚本链路。

配套说明文档：**植境Verda-B数据与素材交付说明-v1.3.docx**（本包根目录，含逐项对照、数据字典、答辩问答）。

## 现在是什么状态

| 部分 | 状态 |
|---|---|
| 36 种植物主数据（31 字段） | 完成，学名经 iNaturalist 校验 35/36 |
| 288 条百科字段记录 | 完成，来源链接待 W2 回源 |
| 6×5 案例配额（120 张） | 配额完成，图待采 |
| 授权表 / 采集日志 | 结构完成，随采集自动写入 |
| 采集 / 去底 / 质检 / 打包脚本 | 完成，可运行 |
| 去底素材 36 张 | 36/36（23 实拍 + 13 插画回退），全部过 QC |
| 案例 120 张 | 120/120 已入库 |
| 案例 120 张 | 120/120 已入库（6×5 配额） |

素材与案例的「图」没有预置在本包里，原因写在说明文档 1.3 与 11.1：图源需要现场网络与授权核验，把图塞进来反而不可追溯。脚本会在采集时同步写授权行，保证每张图都能回源。

## 快速开始

```bash
# 0) 依赖（Python 3.11）；去底默认 onnxruntime + u2net 模型
python -m pip install -r scripts/requirements.txt
python -m pip install onnxruntime
# 模型（176MB）放到 ~/.u2net/u2net.onnx：
# https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx

# 1) 学名与来源校验（一次性，写 data/taxa_verified.csv）
cd scripts && python verify_taxa.py

# 2) 采集 10 种 P0 素材（iNat 无需 Key；Unsplash/Pexels 需环境变量）
python collect.py inat --plants P01,P02,P03,P04,P05,P16,P17,P23,P24,P35 --limit 1

# 3) 去底 + 1600px + 主色回写（无 rembg 时加 --engine simple）
python cutout.py

# 4) 质检（fail 不入库；--strict 时有 fail 返回码 1）
python qc.py --strict

# 5) 导出给 D 的索引 + 打包（生成 MANIFEST.json / sha256sums.txt / dist/*.zip）
python export_index.py
python package.py
```

环境变量（需要时才设）：

```bash
set UNSPLASH_ACCESS_KEY=xxx
set PEXELS_API_KEY=xxx
set HF_ENDPOINT=https://hf-mirror.com   # rembg 模型下载慢时
```

## 目录

```text
data/        结构化数据（UTF-8-SIG，Excel 可直接打开）
  plants_master.csv        36 种主数据
  encyclopedia_entries.csv 288 条字段级百科
  assets_manifest.csv      素材清单（采集/去底/质检状态）
  cases_quota.csv          30 格案例配额
  cases_manifest.csv       案例元数据（采集后逐行写入）
  license_table.csv        授权表，一行一张
  styles.csv / scenes.csv  风格与场景枚举
  taxa_verified.csv        学名校验结果
  assets_index.json        给 D 的素材可用性清单
assets/      图（inbox 原图 / cutout 成品 / cases 案例）
scripts/     采集、去底、质检、索引、打包
schema/      JSON Schema（plant / asset / case）
docs/        说明文档的 Markdown 源（含 .tpl.md 模板）
logs/        采集日志 jsonl
dist/        打包产物
```

## 数据文件速查

| 文件 | 行数 | 主键 | 谁读 |
|---|---|---|---|
| plants_master.csv | 36 | plant_id | C / D / E |
| encyclopedia_entries.csv | 288 | entry_id | C |
| assets_manifest.csv | 36 | asset_id | D / E |
| cases_manifest.csv | 0 → 120 | case_id | C / E |
| cases_quota.csv | 30 | quota_id | B |
| license_table.csv | 与图同增 | no | 全员 |

## 验收对照

| 分工表要求 | 本包文件 |
|---|---|
| W1 10 种去底素材 | 说明文档 3.4 + `assets_manifest.csv` 的 P0 行 |
| W2 36 种素材 | `assets_manifest.csv` 全部 36 行 + `qc_report.csv` |
| W2 100 张案例 | `cases_quota.csv` + `cases_manifest.csv` |
| 授权表可逐张追溯 | `license_table.csv` + `logs/collect_*.jsonl` |
| 数据字典 | 说明文档第 6 节 + `schema/*.json` |
| 给 D 的接口 | `data/assets_index.json` |

## 许可与引用

素材与案例的许可随图登记在 `license_table.csv`，仅用于课程演示；第三方图片版权归原作者，署名与许可链接见授权表。植物学名与分类信息来自 iNaturalist / Wikipedia，毒性判断参考 ASPCA。
