# frontend · 照片模式 + 双入口（E）

纯静态前端，无构建、无依赖、无框架。**既能独立演示，也能直接调 D 的 Flask 后端。**

## 运行（两种形态）

```bash
# ① 只跑前端：离线演示模式（植物/案例读 data/ 与 assets/，锚定与合成在前端算）
cd <仓库根目录>
python -m http.server 8123
# 打开 http://127.0.0.1:8123/frontend/index.html

# ② 前端 + 后端（推荐，答辩用这个）
python app.py --port 5055                      # D 的后端
python -m http.server 8123                     # 仓库根目录，前端静态
# 打开 http://127.0.0.1:8123/frontend/index.html?api=http://127.0.0.1:5055
```

`?api=` 是可选的：带上就调真接口（照片校验、锚定校验、合成、七维评分、推荐、改稿全部走服务端）；
不带就退化为本地模式，植物列表、锚定几何、拖拽、导出全部照常可用，只有评分/推荐/改稿提示需要后端。

`?demo=1` 会载入示例房间、自动锚定并放三株植物，用于联调、截图和答辩彩排。

> 为什么必须是 http：`fetch('../data/*.json|csv')` 在 `file://` 下会被浏览器拦截。直接双击 index.html 只能看到空壳。

## 接的是哪些接口（与 `docs/14_接口契约.md` 一致）

| 用途 | 接口 | 前端落点 |
|---|---|---|
| 植物面板（48 种，含 webp 缩略图） | `GET /api/plants` | `loadCatalog()` |
| 照片上传 + 5 项可用性校验 | `POST /api/upload`（multipart `photo`） | `uploadFile()` |
| 尺度锚定校验（px/cm 合理区间、参照线太短/接近水平） | `POST /api/anchor` | `finishAnchor()` |
| 照片合成（等比缩放 + 贴地 + 阴影 + 水印） | `POST /api/compose` | `doCompose()` |
| 七维评分（与推荐同源，保证 AC-11） | `POST /api/score` | `doScore()` |
| 三套方案 | `POST /api/recommend` | `btnRecommend` |
| 一句话改稿 | `POST /api/revise` | `revise()` |

## 交互口径（几处需要留意的决定）

1. **坐标**：一律用**照片像素**坐标与后端对齐（不是屏幕坐标），缩放只影响显示；`px_per_cm` 由前端按「参照物两点距离 ÷ 参照物真实高度」算出，再交后端校验。
2. **拖动是本地即时、合成是服务端异步**：拖动时直接改 DOM 图层位置（不卡）；松手 420ms 后自动请求合成，成功后把服务端成图淡入覆盖，图层自动隐藏。所以「看着像实时合成」，但真正的像素合成在服务端。
3. **落地线只取平均高度**：`/api/compose` 只收一个 `ground_y`，所以落地线若倾斜，按平均高度落；倾斜超过 3° 会在锚定提示里写明。
4. **层级**：`layer` 越小越靠前（0 最前），与 `docs/14` 第 8 节一致；「已放植物」里的 ↑↓ 就是改这个值。
5. **株高**：默认取品种区间中位数，可在区间内改（市售规格），不允许自由缩放 —— 这一条口径需 A 确认（见 `docs/12` 第 3 节）。

## 已知缺口

- **`/api/cases` 还没有**：案例库页目前直接读 `data/cases_manifest.csv` + `assets/cases/*.jpg`（静态态可用），后端出接口后换成 `GET /api/cases` 即可，前端只改 `loadCases()` 一处。
- 缩略图用后端现算的 256px webp（首次请求会落盘缓存到 `.cache/thumbs/`），首次进面板会有几十毫秒延迟。
