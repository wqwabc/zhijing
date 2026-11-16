# frontend · 照片模式与自选面板（E）

单文件前端，无构建、无依赖、无框架。目标是在 D 的 Flask 就位之前，把「照片模式 + 自选面板」这条链路的交互与几何逻辑先跑通，并与 B 已交付的真实素材/主数据对齐。

## 运行

```bash
# 在仓库根目录（必须用 http，不能用 file:// —— 页面要 fetch data/）
python -m http.server 8123
# 打开
http://127.0.0.1:8123/frontend/index.html
# 演示态（自动铺好地面线并放三株，用于联调与录屏）
http://127.0.0.1:8123/frontend/index.html?demo=1
```

原因：`assets_index.json` 与 `plants_master.csv` 通过 `fetch` 读取，`file://` 协议会被浏览器拦截；页面在 fetch 失败时会退回到 9 条内置记录（只在没起服务时兜底，不要依赖它）。

## 数据来源（全部是仓库里已有的真数据）

| 用途 | 来源 | 字段 |
|---|---|---|
| 素材可用性 / 株高区间 / 主色 / 光照 / 毒性 | `data/assets_index.json` | `has_cutout` `file` `height_range_cm` `dominant_hex` `light_level` `pet_safe` `toxic` `style_tags` |
| 株型 / 冠幅 / 每周工时 / 参考价 | `data/plants_master.csv` | `form` `leaf` `care_min_week` `price_cny` `difficulty` |
| 合成用图 | `assets/cutout/{Pxx}/{Pxx}_front_*.png` | 真实去底 PNG，30 张未到位时按 `has_cutout=false` 灰显 |

两个读数口径：

1. **`has_cutout=false` → 面板灰显「仅参考」，不可点选**（FR-07 素材可用性，避免点了没反应）。
2. **素材代表株高取 `height_range_cm` 的中位数**。这是 `docs/06_数据字典.md` 6.3 节约定的「合成缩放用中位数」；因为素材没有逐张标注真实株高，像素与厘米的换算是近似的，详见 `docs/12_前端与部署.md` 的待确认项。

## 已实现的 FR 对照

| FR | 实现位置 | 说明 |
|---|---|---|
| FR-01 照片校验 | `checkPhoto()` | 本地预校验：长边 / 平均亮度 / 对比度；模糊与地面检测留 `/api/photo/check` |
| FR-02 尺度锚定 | `btnGround` / `btnRef` + `pxPerM()` | 两点画地面线、参照物标定像素每米，3 步内完成，实时 1m 比例尺 |
| FR-04 合成展示 | `plantBox()` / `drawScene()` | 按真实株高缩放、透明边距自动检测后按**视觉底部**贴地、接触阴影；最终合成待 D 的服务端结果替换 |
| FR-05 素材回退 | `placeholderPlant()` | 素材未就绪时画占位，不开天窗 |
| FR-07 自选面板 | 植物面板 + 图层 + 株高滑块 | 搜索、只看有素材、点选加入、拖动吸附地面线、层级置前/置后、6 株上限、仅参考灰显、株高在品种区间内选规格 |
| FR-10 导出 | `btnExport` / `btnExportList` | PNG（长边 ≥1600，右下角「效果示意」）+ 采购清单 .md（株高/冠幅/光照/毒性/工时/价格） |
| AC-10 降级 | `btnFlat` + `?demo=1` | 立面模式，无照片、无后端也能完整演示 |

## 与后端的接线点

所有路径集中在文件顶部 `CONFIG`：

```js
var CONFIG = { dataRoot: '../data/', assetRoot: '../', maxPlants: 6 };
```

支持 `?data=` 与 `?assets=` 覆盖，方便 Flask 把静态资源挂到别的路径。D 的接口就位后，把 `loadData()` 换成 `fetch('/api/plants')`、把 `drawScene()` 里的本地绘制换成 `/api/compose` 返回图即可，交互层不用动。

## 已知限制

- 缩略图直接用了原图 PNG（9 张共约 10MB），首屏会慢；等 B 按 `docs/06` 出 `.thumb.webp`（宽 480）后替换 `assetUrl()` 的缩略图分支即可。
- 合成是浏览器的 `drawImage`，不是服务端渲染：色温匹配、多图层遮挡、P95 <3s 这些指标必须由 D 的服务端合成来达标，这里只保证交互与比例正确。
- 评分区未接，等 C 的 `/api/score`（结构见 `docs/12_前端与部署.md`）。
