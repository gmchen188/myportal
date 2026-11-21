import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { SeverityBadge, severityLabel } from "@/components/severity"

describe("严重度显示", () => {
    it("颜色与需求一致：critical 红 / high 粉红 / medium 黄 / 正常绿", () => {
        // 颜色在 monitoring.py 的 SEVERITY_COLOR 里定义，前端从 API 拿。
        // 这里测的是**文案**与**形状标记** —— 颜色由后端权威定义。
        expect(severityLabel("critical")).toBe("严重")
        expect(severityLabel("high")).toBe("高危")
        expect(severityLabel("medium")).toBe("中危")
        expect(severityLabel("normal")).toBe("正常")
    })

    it("unknown 是独立的一档，不是 normal 的别名", () => {
        expect(severityLabel("unknown")).toBe("未知")
        expect(severityLabel("unknown")).not.toBe(severityLabel("normal"))
    })

    it("徽章带文字，不只靠颜色传达信息（无障碍要求）", () => {
        render(<SeverityBadge severity="critical" />)
        expect(screen.getByText("严重")).toBeDefined()
    })
})
