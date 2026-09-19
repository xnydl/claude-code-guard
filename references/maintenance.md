# 维护流程与部署识别

先核对目标机器的 wrapper、网络门、Hook、Seatbelt、settings 与 Camoufox 启动器。以下是识别项，不是某台机器已完成抓包、断网或登录验收的证明。

| 项目 | 维护时要确认的内容 |
| --- | --- |
| 保护入口 | `claude` 实际命令或 shell 函数，以及注入的代理变量 |
| 运行目录 | 新布局通常是 `~/.claude-guard/`；旧部署可能是 `~/.local/claude-guard/` |
| 请求 Hook | `~/.claude/hooks/` 中实际挂载的 UserPromptSubmit / PostToolBatch 检查 |
| 网络门 | 运行中的 `ccg_gate.py` 或旧 gate 实现，以及真实监听端口 |
| 沙箱 | 运行中的 `claude-network.sb`；修改后必须重启 Claude |
| 状态 | 新模板使用 `~/.claude-guard/state.json`；不要把磁盘文件存在当成运行中证据 |
| 代理链 | CLI → gate → 专用上游。端口是现场配置，不是跨机器默认 |
| Mihomo listener | loopback、UDP 关闭；单节点指向具体叶子，主备模式指向专用 Selector |

## 单节点与固定主备

- 默认只保存一个 `expected_node`。节点必须是用户明确指定的具体叶子，不能是 DIRECT/REJECT/PASS 或自动组。
- 只有用户明确要求自动兜底时，才启用一个 `primary_node`、一个 `secondary_node` 和一个 Selector `ai_group`。两个节点必须不同，Selector 必须且只能直接包含这两个具体叶子；失败阈值限制为 2-5，严格探测间隔限制为 5-60 秒。
- 任一时刻仍只有一个 `expected_node`。`active_role`、`expected_node` 与 Selector 实际叶子必须一致。
- 主节点连续失败达阈值后才可切换。切换期间先置 `switching=true`、关闭 gate 管理的活动隧道，再切到备用并严格验证真实叶子、地区和 Anthropic 可达性。
- 备用验证失败必须读回验证回滚；无法确认时保持 `blocked`。备用运行中失效只阻断，默认不自动回切，不选第三个节点。

## 瞬时失败与明确不安全证据

- 已有新鲜严格验证时，单次有界控制口超时、trace 超时或 Anthropic 临时不可达可保留当前唯一路由并立即复核；连续达到配置阈值才关门。
- 叶子漂移、地区明确不符、TUN 关闭、IPv6 开启、主备角色/状态不一致不是可容忍的网络抖动，第一次就必须 fail closed。
- 严格探测成功会清零快速与完整探测的连续失败计数。状态字段损坏或监控循环异常必须清除放行位、关闭活动隧道，再从关闭状态重试。

## 维护顺序

1. 运行 `python3 scripts/ccg_audit.py` 获取只读摘要；确认真实命令、服务、监听端口和设置引用。
2. 更新 Skill ≠ 部署；更新 CLI ≠ 重装保护；诊断 ≠ 改全局网络。
3. 备份即将修改的具体非凭证配置，增量编辑；保留其他 Hook、权限、鼠标偏好、开发例外和普通浏览器资料。
4. 语法/单测 → 文件比较 → 只读路由核对 → 无账号拒绝路径测试。重启 gate/CLI/浏览器前说明连接影响。
5. 只报必要的脱敏状态，不显示真实公网 IP、控制器 secret、Cookie、凭证或请求正文。
6. 分别交付变更、未变更、已验证和未验证边界；不能把模板能力写成某台机器已完成部署。

## 源码与使用副本

本仓库是通用 Skill 源码。安装工具可能复制或符号链接到 `~/.agents/skills/`、`~/.claude/skills/`、`~/.codex/skills/` 或 `~/.grok/skills/`。发布前核对真实 Git remote、工作区与已安装副本，不要把某台机器的节点名、端口、私有域名或凭证提交到公开仓库。

更新仓库不会自动重启 Claude、Grok、Clash 或浏览器。已加载旧 Skill 的会话需重新读取，不保证热更新。
