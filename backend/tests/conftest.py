"""pytest 全局夹具。

## 为什么把 bcrypt 的 rounds 调低

bcrypt 默认 12 rounds（约 100ms 一次）。管理后台的测试要登录很多次，
几十次哈希就是**两分多钟** —— CI 会被拖垮。

**只在测试里调低**，生产保持默认 12。变量必须在 bcrypt 服务被 import
之前设好，所以放在 conftest 里（pytest 先加载它）。
"""

import os

# 4 rounds 约 1ms —— 测试够用
os.environ.setdefault("MP_BCRYPT_ROUNDS", "4")
