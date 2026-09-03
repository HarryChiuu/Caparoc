# 前端第三方函式庫（本機化）

Web UI 不從 CDN 載入任何資源，全部改放這裡，確保**沒有外部網路的現場環境**也能正常渲染。
（先前從 jsDelivr / unpkg 載入，離線時 Vue 抓不到 → 整頁只剩未編譯的 `{{ }}` 模板，等同不能用。）

| 檔案 | 版本 | 來源 |
| --- | --- | --- |
| `vue.global.prod.js` | 3.5.42 | https://unpkg.com/vue@3.5.42/dist/vue.global.prod.js |
| `chart.umd.min.js` | 4.4.6 | https://cdn.jsdelivr.net/npm/chart.js@4.4.6/dist/chart.umd.min.js |
| `hammer.min.js` | 2.0.7 (npm hammerjs@2.0.8) | https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js |
| `chartjs-plugin-zoom.min.js` | 2.2.0 | https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.2.0/dist/chartjs-plugin-zoom.min.js |

檔案與上游完全一致（未做任何修改），內含的 `sourceMappingURL` 註解指向未隨附的 `.map`，
只有開啟 DevTools 時會出現一則本機 404，不影響功能。

## 更新方式

1. 依上表下載新版覆蓋（請務必指定明確版號，不要用 `vue@3` 這種浮動標籤）。
2. 更新 `web/templates/index.html` 中 `<script>` 的 `?v=` 版號，避免瀏覽器吃到舊快取。
3. 更新本表。
