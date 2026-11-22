import { fileURLToPath, URL } from "node:url"
import { writeFileSync } from "node:fs"
import { execSync } from "node:child_process"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// vitest 的配置类型与 vite 不同 —— 从 vitest/config 导入 defineConfig，
// 才认得 `test` 字段。
import { defineConfig } from "vitest/config"

/**
 * 构建时写一个 `version.json` —— 前端拿它判断**自己是不是旧页面**。
 *
 * ## 为什么需要
 *
 * 踩过的坑：修完「新建船队 422」，用户又报了一次 422 —— 因为他那个页面
 * 是**部署前就打开的**，里面跑的还是旧 bundle。SPA 不会自动换代码，
 * `index.html` 的 `no-cache` 只在**刷新时**才起作用。
 *
 * 于是同一个 bug 修了两次，用户看到的是两个一模一样的报错。
 *
 * 现在前端每 60 秒拉一次这个文件，版本变了就提示刷新 ——
 * **不用再靠用户自己判断该不该 F5**。
 */
function versionFile() {
    return {
        name: "myportal-write-version",
        apply: "build" as const,
        closeBundle() {
            let rev = ""
            try {
                rev = execSync("git rev-parse --short HEAD", { stdio: ["ignore", "pipe", "ignore"] })
                    .toString()
                    .trim()
            } catch {
                // 不是 git 仓库（Pages 的 Actions 里是 checkout 过的，但
                // 本地拷一份产物时可能不是）—— 时间戳也够用。
            }
            const builtAt = new Date().toISOString()
            const outDir = process.env.VITE_OUT_DIR ?? "dist"
            writeFileSync(
                fileURLToPath(new URL(`./${outDir}/version.json`, import.meta.url)),
                JSON.stringify({ rev, builtAt }, null, 2),
                "utf-8",
            )
        },
    }
}

export default defineConfig({
    plugins: [react(), tailwindcss(), versionFile()],
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
        // **超时放宽** —— 好几条测试要渲染整页（资产清单、总览），
        // 那些组件很重（表格 + 导入 + 导出 + CMDB 面板 + 图表）。
        // 默认 5 秒在机器稍忙时就整片变红 —— 那是**测试环境慢**，不是功能坏了。
        //
        // 判据：失败全是 `TestTimeoutError`，且**单独跑同一个文件必过**。
        testTimeout: 20000,
        hookTimeout: 20000,
    },
})
