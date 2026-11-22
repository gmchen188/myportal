import { useEffect, useState } from "react"

/**
 * 页面版本检测 —— 发现自己跑的是旧代码时提示刷新。
 *
 * ## 为什么需要
 *
 * SPA 打开之后，**里面跑的是打开那一刻的 bundle**。后端发布了新代码、
 * 前端重新 build 了，已经开着的页面**不会自己换** —— `index.html` 的
 * `no-cache` 只在刷新时才起作用。
 *
 * 实测踩过：修完「新建船队 422」推送上线，用户又报了一次一模一样的 422 ——
 * 因为他那个标签页是**修复之前就开着的**。同一个 bug 修了两次，
 * 用户看到的是两个一模一样的报错，而谁都看不出页面是旧的。
 *
 * ## 怎么判断「过期」
 *
 * 构建时（`vite.config.ts` 的 `versionFile` 插件）写一个 `version.json`
 * （git 短 hash + 构建时间）。页面加载时把自己的版本记在 sessionStorage，
 * 之后每 60 秒拉一次那个文件：
 *
 *   · 拉不到（dev server 没有这个文件 / 离线）→ 静默跳过
 *   · 版本一样 → 什么都不做
 *   · 版本变了 → 顶部挂一条「页面已更新，点击刷新」
 *
 * **sessionStorage 而不是 localStorage** —— 关掉标签页就重置，
 * 下次打开自然是新版本，不该再提示。
 */

const VERSION_KEY = "myportal.version"
const DISMISSED_KEY = "myportal.version-dismissed"
/** 多久查一次 */
const INTERVAL_MS = 60_000

export interface VersionInfo {
    rev: string
    builtAt: string
}

/** 版本文件的地址。用 BASE_URL —— Pages 挂在 /myportal/ 下。 */
export function versionUrl(): string {
    const base = import.meta.env.BASE_URL ?? "/"
    return `${base}version.json`
}

/**
 * 拉一次版本。拉不到就返回 null —— **不抛错**：
 * dev server 没有这个文件、Pages 还没部署、网络断了，都属于正常情况。
 */
export async function fetchVersion(): Promise<VersionInfo | null> {
    try {
        const res = await fetch(versionUrl(), { cache: "no-store" })
        if (!res.ok) return null
        const v = (await res.json()) as VersionInfo
        if (!v || typeof v.builtAt !== "string") return null
        return v
    } catch {
        return null
    }
}

function readStored(key: string): string | null {
    try {
        return sessionStorage.getItem(key)
    } catch {
        return null
    }
}

function writeStored(key: string, value: string) {
    try {
        sessionStorage.setItem(key, value)
    } catch {
        /* 隐私模式下 sessionStorage 可能不可写 —— 不影响主流程 */
    }
}

export interface VersionCheck {
    /** 页面已经过期（有新版本） */
    stale: boolean
    /** 新版本号（服务端最新的） */
    current: VersionInfo | null
    /** **我当前跑的**是哪个版本 —— 永远显示在界面上，让人能自己核对 */
    mine: VersionInfo | null
    /** 关掉提示 */
    dismiss: () => void
    /** 立刻刷新 */
    reload: () => void
}

export function useVersionCheck(): VersionCheck {
    const [stale, setStale] = useState(false)
    const [current, setCurrent] = useState<VersionInfo | null>(null)
    const [mine, setMine] = useState<VersionInfo | null>(null)

    useEffect(() => {
        let alive = true

        const check = async () => {
            const v = await fetchVersion()
            if (!alive || !v) return
            // **我当前是哪个版本** —— 界面要一直显示它，
            // 这样「页面是不是旧的」不用靠猜。
            setMine(v)
            const key = JSON.stringify(v)
            const mine = readStored(VERSION_KEY)
            if (!mine) {
                // 第一次看到 —— 记下这就是「我」这个版本
                writeStored(VERSION_KEY, key)
                return
            }
            if (mine === key) return
            // 变了 —— 但如果用户已经关掉过这个版本的提示，就不再打扰
            if (readStored(DISMISSED_KEY) === key) return
            setCurrent(v)
            setStale(true)
        }

        void check()
        const timer = setInterval(() => void check(), INTERVAL_MS)
        return () => {
            alive = false
            clearInterval(timer)
        }
    }, [])

    return {
        stale,
        current,
        mine,
        dismiss: () => {
            if (current) writeStored(DISMISSED_KEY, JSON.stringify(current))
            setStale(false)
        },
        reload: () => window.location.reload(),
    }
}
