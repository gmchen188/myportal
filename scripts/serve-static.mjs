/**
 * 静态文件服务器 —— 用于把构建产物作为常驻服务跑。
 *
 * 为什么要它（而不是 vite dev server）：
 *
 * · **vite dev 是开发服务器** —— watch 文件、重编译、开 HMR 连接。
 *   做成开机自启服务，机器一开就占 CPU 编译，还会在有人改文件时
 *   半夜重启。对「当服务器用」这个场景是错的。
 * · production build 是**静态产物** —— 直接发文件，零编译，零 watch。
 *
 * 它还做两件生产需要的事：
 *
 * 1. **SPA fallback** —— 未知路径回 index.html（前端路由直接访问
 *    /admin 不会 404）
 * 2. **反向代理 /api 与 /health 到后端** —— 前端与后台同源，
 *    免掉跨域；顺带让「静态站」也能有真正的后台
 *
 * 用法：
 *   node scripts/serve-static.mjs --root <dir> --port <port> [--api <origin>] [--base <path>]
 *
 * 例：
 *   node scripts/serve-static.mjs --root C:/path/web/dist --port 5174 --api http://127.0.0.1:9102
 */
import http, { createServer } from "node:http"
import { createReadStream, existsSync, statSync } from "node:fs"
import { extname, join, normalize, resolve } from "node:path"

function arg(name, fallback = null) {
    const i = process.argv.indexOf(`--${name}`)
    return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback
}

const root = resolve(arg("root", "."))
const port = Number(arg("port", "5174"))
const apiOrigin = arg("api", null)
const base = arg("base", "")

const MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".wasm": "application/wasm",
    ".webp": "image/webp",
}

if (!existsSync(join(root, "index.html"))) {
    console.error(`[serve-static] 根目录没有 index.html: ${root}`)
    process.exit(1)
}

/** 把 /api 与 /health 转发到后端 —— 让静态站与后台同源。 */
function proxy(req, res) {
    const target = new URL(req.url, apiOrigin)
    const headers = { ...req.headers, host: target.host }
    const upstream = http.request(
        target,
        { method: req.method, headers, timeout: 60000 },
        (up) => {
            res.writeHead(up.statusCode || 502, up.headers)
            up.pipe(res)
        },
    )
    upstream.on("error", (err) => {
        // 后端不在 → 明确说「后台不可达」，别回一个含糊的 404
        res.writeHead(502, { "Content-Type": "application/json; charset=utf-8" })
        res.end(
            JSON.stringify({
                detail: {
                    error: "后台不可达",
                    detail: `无法连接后台 ${apiOrigin}：${err.code || err.message}`,
                },
            }),
        )
    })
    req.pipe(upstream)
}

const server = createServer((req, res) => {
    const raw = (req.url || "/").split("?")[0]

    // 后端路径 → 转发
    if (apiOrigin && (raw === "/health" || raw.startsWith("/api/"))) {
        proxy(req, res)
        return
    }

    // 去掉 base 前缀
    let path = raw
    if (base && path.startsWith(base)) path = path.slice(base.length) || "/"

    // 防目录穿越
    const safe = normalize(path).replace(/^(\.\.[/\\])+/, "")
    let file = join(root, safe)
    if (!file.startsWith(root)) file = join(root, "index.html")

    if (existsSync(file) && statSync(file).isFile()) {
        res.writeHead(200, {
            "Content-Type": MIME[extname(file).toLowerCase()] ?? "application/octet-stream",
            "Cache-Control": file.includes("/assets/") ? "public, max-age=31536000, immutable" : "no-cache",
        })
        createReadStream(file).pipe(res)
        return
    }

    // SPA fallback —— 直接访问 /admin、/siem 这类前端路由不该 404
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" })
    createReadStream(join(root, "index.html")).pipe(res)
})

server.listen(port, "127.0.0.1", () => {
    console.log(
        `[serve-static] ${root} → http://127.0.0.1:${port}${base}` +
            (apiOrigin ? `  (代理 /api,/health → ${apiOrigin})` : ""),
    )
})

// 优雅退出 —— nssm stop 时不要留孤儿进程
for (const sig of ["SIGTERM", "SIGINT"]) {
    process.on(sig, () => {
        server.close(() => process.exit(0))
        setTimeout(() => process.exit(0), 3000).unref()
    })
}
