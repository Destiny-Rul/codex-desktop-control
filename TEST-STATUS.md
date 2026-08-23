# Codex Desktop Control 当前测试状态

- 技能版本：`0.3.4`
- Codex Desktop：`26.814.5517.0`
- 测试会话：`codex://threads/01a017f3-c518-7ae1-a78f-2ff3adb5af17`

## 结果

新版 Desktop 中，`thread-stream-following-changed` 的 `sourceClientId` 仅说明一个客户端正在跟随线程，不能再作为线程 owner。控制器现先通过原生只读 IPC `thread-owner-discovery` 获取 Desktop 返回的 `handledByClientId`，仅在该能力不可用时才回退到经过 250ms 稳定窗口的广播发现。针对 Codex Desktop `26.818.3698.0`，`thread-follower-start-turn` 的协议版本已更新为 `2`，并使用当前 handler 需要的 `turnStart.request` 与 `turnStart.context` 形状；用户状态数据库从显式传入的 Codex user-state directory（`state_5.sqlite`）读取。

此前在旧 Desktop build 的指定测试会话通过完整 `certify`：probe、发送/等待/状态读取、临时设置与恢复、steer、interrupt、最终 probe 均成功。当前 `26.818.3698.0` build 仍须在新的、显式指定的测试会话重新认证；在此之前写入能力保持禁用。