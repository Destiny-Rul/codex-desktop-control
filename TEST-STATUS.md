# Codex Desktop Control 当前测试状态

- 技能版本：`0.3.5`
- Codex Desktop：待针对当前 build 重新认证
- 测试会话：使用当前 profile 已指定的专用测试会话

## 状态

v0.3.5 增加 owner discovery 的 fail-closed 检查、将其纳入协议锁，并为 Codex Desktop v2 start-turn 请求加入离线回归测试。离线兼容检查通过；当前指定测试会话未被任何 Desktop client 持有，`thread-owner-discovery` 返回 `no-client-found`，因此在线认证被安全阻止。打开该专用测试会话后，先运行 online doctor，再执行 `certify`。