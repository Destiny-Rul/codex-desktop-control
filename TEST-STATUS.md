# Codex Desktop Control 当前测试状态

- 技能版本：`0.3.6`
- Codex Desktop：`26.825.4187.0`
- 测试会话：`codex://threads/019fe574-d35c-7fc1-a0e5-e737874c9787`

## 状态

v0.3.6 保留 owner discovery 的 fail-closed 检查和 Codex Desktop v2 start-turn 契约，并允许认证标记响应带有首尾空白；非空白额外文本仍会失败。已在当前 build 完成 probe、send/wait/status、临时设置往返与恢复、同 turn steer、精确 interrupt 和最终 probe，research profile 认证通过。