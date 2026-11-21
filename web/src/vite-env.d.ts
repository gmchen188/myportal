/// <reference types="vite/client" />

interface ImportMetaEnv {
    /** 后台 API 前缀。空 = 同源相对路径（开发走 vite proxy，生产同源部署） */
    readonly VITE_API_BASE?: string
    /** networktopology 画布应用的同源子路径 */
    readonly VITE_NT_BASE?: string
}

interface ImportMeta {
    readonly env: ImportMetaEnv
}
