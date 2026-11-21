/**
 * 本地模拟 GitHub Pages：静态托管 web/dist + 把 /api 与 /health
 * 代理到一个 404+HTML 的 mock（模拟「Pages 上没有后台」）。
 *
 *   node scripts/mock-pages-serve.mjs [端口] [mock端口]
 *
 * 用来在本地复现线上 Pages 的行为，不必反复部署。
 */
import { createServer } from "node:http"
import { readFileSync, existsSync, statSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join, extname } from "node:path"

const __dir = dirname(fileURLToPath(import.meta.url))
const dist = join(__dir, "..", "web", "dist")
const port = Number(process.argv[2] || 5299)
const mockPort = Number(process.argv[3] || 9103)

const MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

const indexHtml = existsSync(join(dist, "index.html"))
    ? readFileSync(join(dist, "index.html"))
    : "<!doctype html><html><body><div id=root></div></body></html>"

createServer((req, res) => {
    const path = (req.url || "/").split("?")[0]

    // /api 与 /health 转发到 mock（mock 故意返回 404+HTML）
    if (path.startsWith("/api/") || path === "/health") {
        const proxy = createServer(() => {})
        proxy.close()
        // 直接就地返回 404+HTML，等价于 mock
        res.writeHead(404, { "Content-Type": "text/html; charset=utf-8" })
        res.end(indexHtml)
        return
    }

    // 静态文件
    const file = join(dist, path === "/" ? "index.html" : path.replace(/^\//, ""))
    if (existsSync(file) && statSync(file).isFile()) {
        res.writeHead(200, { "Content-Type": MIME[extname(file)] ?? "application/octet-stream" })
        res.end(readFileSync(file))
        return
    }

    // SPA fallback —— Pages 的 404.html 行为
    res.writeHead(404, { "Content-Type": "text/html; charset=utf-8" })
    res.end(indexHtml)
}).listen(port, "127.0.0.1", () => {
    console.log(`mock-pages-serve: http://127.0.0.1:${port}  (dist=${dist})`)
})
