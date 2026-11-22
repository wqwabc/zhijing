# 植境 Verda

绿植审美搭配 Agent ｜ 数据 · 算法 · 后端 · 前端

拍一张房间照片，系统按真实株高把植物放进画面，给出可解释、可执行的三套方案。
本仓库包含四部分：**数据与素材**（采集、去底、质检、索引、授权）、
**评分与知识库**（七维评分、推荐搜索、一句话改稿、案例检索、风格基线）、
**后端服务**（照片校验、尺度锚定、照片合成、HTTP 接口）与
**前端页面**（照片画布、自选面板、案例库、导出）。

## 目录结构

```text
.
├─ assets/          图片：去底素材、装饰案例、程序化插画
├─ data/            结构化数据：植物主数据、百科、案例清单、授权表、素材索引
├─ docs/            交付说明、算法、接口与验收文档（00–17）
├─ frontend/        前端页面（纯静态，零依赖零构建）
├─ server/          Flask 服务：校验 / 锚定 / 合成 / 接口路由
├─ schema/          JSON Schema：植物 / 素材 / 案例
├─ logs/            采集日志（jsonl，逐条可查）
├─ scripts/         采集 → 授权 → 去底 → 质检 → 索引 → 打包
├─ verda/           评分与知识库代码包
├─ tests/           单元测试（评分 / 推荐 / 改稿 / 检索 / 风格 / 接口 / 合成）
├─ demos/           演示脚本
└─ app.py           后端入口
```

## 快速开始（完整跑起来）

```bash
pip install -r requirements.txt      # Flask + Pillow

# 终端 1：后端
python app.py --port 5055

# 终端 2：仓库根目录起静态服务（前端要 fetch data/，不能用 file:// 直接双击）
python -m http.server 8123
```

打开 **http://127.0.0.1:8123/frontend/index.html?api=http://127.0.0.1:5055**

- 加 `&demo=1` 进入演示态：自动载入示例房间、铺好落地线、放三株植物
- 去掉 `?api=` 则退化为离线演示：植物与案例读本地 `data/`、`assets/`，
  锚定与摆放可用，评分/推荐位置会提示需要后端（断网演示的降级路径）

页面怎么验收、8 分钟演示路径见 `docs/17_验收演示脚本.md`。

## 快速开始（分模块）

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

## 后端（D 交付）

Flask 服务：照片校验、尺度锚定、评分/推荐/改稿接口、照片合成。

```bash
pip install -r requirements.txt

# 开发运行
python app.py                 # http://127.0.0.1:5000
python app.py --mock           # mock 模式：合成返回原图，供前端先行联调

# 单元测试（校验 / 合成 / 接口）
python -m unittest discover -s tests -p test_upload.py
python -m unittest discover -s tests -p test_compose.py
python -m unittest discover -s tests -p test_api.py

# 生产部署（Linux）
gunicorn -w 4 -b 127.0.0.1:8000 app:app
```

接口契约见 `docs/14_接口契约.md`；评分/推荐/改稿返回结构沿用 `verda/` 包原样输出。

## 大模型（看图选株）

接的是 DeepSeek 文本模型：照片只提取主色/亮度/色温等统计特征发给模型，
模型只决定“选哪几株、多高、放哪”，**不生成图片**；选株后仍走 `verda` 确定性评分
和 `assets/cutout` 实拍素材合成。

```bash
# 配置 Key（不配也能跑，自动走规则兜底）
$env:DEEPSEEK_API_KEY="sk-..."
python app.py
```

- 新接口：`POST /api/design`，请求 `photo_id + scene + count + anchor?`
- 无 Key / 超时 / JSON 不合法 → 退回 `verda.recommend`，接口结构不变
- 宠物安全、光照、株高、素材可用都会在本地再校验一遍
- 详细说明见 `docs/18_大模型接入.md`

## 前端（E 交付）

`frontend/` 是纯静态页面，无构建、无框架、无 npm 依赖，四个文件就够：

| 文件 | 内容 |
|---|---|
| `index.html` | 顶栏场景参数 / 舞台 / 评分条 / 三个标签页（AI 推荐 · 自己搭配 · 装饰案例） |
| `app.css` | 样式，与文档视觉基调一致 |
| `app.js` | 交互与接口调用：上传校验、两点锚定、拖动摆放、实时评分、方案套用、改稿、导出 |
| `README.md` | 运行方式、接口对照、交互口径、已知缺口 |

- 坐标统一用**照片像素**（不用屏幕坐标），预览与服务端合成同一套几何
- 拖动结束 420ms 后自动请求 `/api/compose`，服务端成图淡入覆盖；拖动中只动 DOM 图层，不卡
- 植物可左右沿落地线移动、也可上下抬升（显示「离地 X cm」，靠地 8px 自动吸附）；抬升时不改变尺寸
- 七个接口全部接通：`/api/plants`、`/api/upload`、`/api/anchor`、`/api/compose`、`/api/score`、`/api/recommend`、`/api/revise`
- 不带 `?api=` 时自动退化为离线演示模式

已知缺口（详见 `docs/16`）：`GET /api/cases` 未实现，案例页暂读 `data/cases_manifest.csv`；
有植物离地时预览与导出改走前端 canvas（`/api/compose` 的 items 只有 `x`，没有 `y`）。

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
| `docs/14_接口契约.md` | D 的 HTTP 接口契约（字段冻结） |
| `docs/15_前端交付说明.md` | E 的交付说明、接口对照、自检记录 |
| `docs/16_素材与合成质量问题清单.md` | "像贴图"的原因拆解与改法 |
| `docs/17_验收演示脚本.md` | 8 分钟验收/答辩演示路径、AC 自检表 |
| `docs/18_大模型接入.md` | DeepSeek 选株：链路、配置、接口、校验与兜底 |

## 说明

原先的 `B/` 与 `C/` 两个目录已合并到根目录：
`B/assets` → `assets/`，`B/data` → `data/`，`C/verda` → `verda/`，
测试与演示分别在 `tests/`、`demos/`。路径已在代码里同步更新。
前端（E）在 `frontend/`，后端（D）在 `server/` + `app.py`。
