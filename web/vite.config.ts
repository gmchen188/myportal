import { fileURLToPath, URL } from "node:url"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// vitest 的配置类型与 vite 不同 —— 从 vitest/config 导入 defineConfig，
// 才认得 `test` 字段。
import { defineConfig } from "vitest/config"

export default defineConfig({
    plugins: [react(), tailwindcss()],
    resolve: {
        alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
    server: {
        port: 5173,
        // 开发时前端跑在 5173，后台在 9102 —— 用代理而不是跨域，
        // 这样和生产的同源部署行为一致（cookie、相对路径都不用改）。
        proxy: {
            "/api": {
                target: process.env.MP_API_ORIGIN ?? "http://127.0.0.1:9102",
                changeOrigin: true,
            },
        },
    },
    build: {
        outDir: "dist",
        sourcemap: true,
    },
    test: {
        environment: "jsdom",
        globals: true,
        setupFiles: ["./src/test/setup.ts"],
    },
})
