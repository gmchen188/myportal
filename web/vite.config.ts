import { fileURLToPath, URL } from "node:url"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// vitest 的配置类型与 vite 不同 —— 从 vitest/config 导入 defineConfig，
// 才认得 `test` 字段。
import { defineConfig } from "vitest/config"

export default defineConfig({
    plugins: [react(), tailwindcss()],
    // **base 必须是部署路径**。GitHub Pages 的项目站点挂在 /<仓库名>/ 下
    // （这里是 /myportal/），而 Vite 默认 base="/" —— 构建出的 index.html
    // 会引用 "/assets/xxx.js"，浏览器去域名根找，资源 404，页面全白。
    //
    // 实测踩过：线上 curl 拿 index.html 是 200，看起来没问题，
    // 但浏览器里 /assets/... 全 404，React 根本没挂载。
    //
    // VITE_BASE 由构建环境传入；本地开发留空（"/"）。
    // **base 是构建期内联的 —— 改了必须重新 build。**
    base: process.env.VITE_BASE ?? "/",
    resolve: {
        alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
    server: {
        port: 5173,
        // 开发时前端跑在 5173，后台在 9102 —— 用代理而不是跨域，
        // 这样和生产的同源部署行为一致（cookie、相对路径都不用改）。
        proxy: {
            // /api 与 /health 都要代理 —— /health 是后台的健康检查，
            // 侧栏的 FortiSIEM 指示灯用它。只配 /api 的话 /health 会 404，
            // 指示灯永远显示「未连接」。
            "/api": {
                target: process.env.MP_API_ORIGIN ?? "http://127.0.0.1:9102",
                changeOrigin: true,
            },
            "/health": {
                target: process.env.MP_API_ORIGIN ?? "http://127.0.0.1:9102",
                changeOrigin: true,
            },
        },
    },
    build: {
        // **输出目录可覆盖** —— 本地服务与 Pages 构建不能抢同一个目录。
        //
        // 踩过的坑：verify.sh 用 `VITE_BASE=/myportal/` 构建（Pages 版），
        // 产物写进 web/dist —— 而本地 Windows 服务托管的正是 web/dist。
        // 于是本地服务的 index.html 引用 /myportal/assets/...，
        // 静态服务器把那个路径当 SPA 路由回落到 index.html，
        // **浏览器拿到的是 Content-Type: text/html 的 JS 请求 —— 整页白屏**。
        //
        // curl 看 index.html 是 200、curl 看资源也是 200（回落的内容），
        // 只有真浏览器才暴露「白屏」。
        //
        // 所以：本地服务用 dist（base=/），Pages 构建用 dist-pages
        // （base=/<repo>/），两者互不覆盖。
        outDir: process.env.VITE_OUT_DIR ?? "dist",
        sourcemap: true,
    },
    test: {
        environment: "jsdom",
        globals: true,
        setupFiles: ["./src/test/setup.ts"],
    },
})
