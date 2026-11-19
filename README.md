# 植境 Verda

绿植审美搭配 Agent 的数据与算法交付仓库。

拍一张房间照片，系统按真实株高把植物放进画面，给出可解释、可执行的三套方案。
本仓库包含两部分：**数据与素材**（采集、去底、质检、索引、授权）与
**评分与知识库**（七维评分、推荐搜索、一句话改稿、案例检索、风格基线）。

## 目录结构

```text
.
├─ assets/          图片：去底素材、装饰案例、程序化插画
├─ data/            结构化数据：植物主数据、百科、案例清单、授权表、素材索引
├─ docs/            交付说明与算法文档（00–13）
├─ schema/          JSON Schema：植物 / 素材 / 案例
├─ logs/            采集日志（jsonl，逐条可查）
├─ scripts/         采集 → 授权 → 去底 → 质检 → 索引 → 打包
├─ verda/           评分与知识库代码包
├─ tests/           单元测试（评分 / 推荐 / 改稿 / 检索 / 风格）
└─ demos/           演示脚本
```

## 快速开始

```bash
# 评分演示（读 data/ 里的真实植物数据）
python demos/demo.py

# 推荐 / 改稿
python demos/demo_recommend.py
python demos/demo_revise.py

# 案例检索与风格基线（需要 torch + torchvision / sklearn）
python demos/demo_cases.py
python demos/demo_style.py

# 单元测试（全量需要 torch + torchvision）
python -m unittest discover -s tests -v

# 没有 torchvision 时，先跑纯标准库的三组
python -m unittest discover -s tests -p "test_scoring.py"
python -m unittest discover -s tests -p "test_recommend.py"
python -m unittest discover -s tests -p "test_revise.py"
```

## 数据（对应原 B 交付包）

- `data/plants_master.csv`：植物主数据，一种一行，31 列
- `data/encyclopedia_entries.csv`：字段级百科，每条带来源链接
- `data/cases_manifest.csv` / `data/license_table.csv`：案例元数据与逐张授权
- `data/assets_index.json`：给合成与前端用的素材可用性清单
- `assets/cutout/`：去底 PNG（RGBA，长边 ≥1200）
- `assets/cases/`：装饰案例原图

采集与质检流程见 `docs/02_采集方案.md`、`docs/07_质检SOP.md`；
数据口径与缺口见 `docs/09_数据附录.md`。

## 算法（对应原 C 交付包）

`verda/` 是一个纯标准库可跑的评价包：

- `scoring.py`：六个审美维度 + 场景适配，OKLCH 色彩、权重归一化
- `recommend.py`：稳妥 / 对比 / 个性三套方案，Jaccard 去重
- `revise.py`：七种一句话改稿，保留率 ≥50%
- `case_index.py`：ResNet50 特征 + 余弦相似度检索（需 torch + torchvision）
- `style_clf.py`：风格分类基线（需 sklearn）

评分与推荐只依赖标准库；图像相关模块是可选依赖，
`verda/__init__.py` 不会强制导入它们。

## 文档索引

| 文档 | 内容 |
|---|---|
| `docs/00_lead.md` | 交付说明总入口 |
| `docs/01_交付概览.md` | 交付物与分工对照 |
| `docs/02_采集方案.md` | 四源、六步链路、命名规则 |
| `docs/03_植物清单.md` | 植物选型与覆盖度 |
| `docs/04_案例库.md` | 案例配额与打标 |
| `docs/05_授权合规.md` | 许可对比与授权表字段 |
| `docs/06_数据字典.md` | 表结构、枚举与接口契约 |
| `docs/07_质检SOP.md` | 9 项自动 + 5 项目检 |
| `docs/08_脚本与运行.md` | 五条命令与兜底 |
| `docs/09_数据附录.md` | 分布、计数口径、缺口 |
| `docs/10_答辩问答.md` | B 的 5 问 5 答 |
| `docs/11_风险与待办.md` | 风险与补救 |
| `docs/12_完成度自检.md` | 交付前的逐项自检 |
| `docs/13_算法与知识库.md` | C 的评分、推荐、检索与基线 |

## 说明

原先的 `B/` 与 `C/` 两个目录已合并到根目录：
`B/assets` → `assets/`，`B/data` → `data/`，`C/verda` → `verda/`，
测试与演示分别在 `tests/`、`demos/`。路径已在代码里同步更新。
