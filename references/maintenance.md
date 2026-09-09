# 维护流程与本机基线

## 2026-09-05 核对

依据本机 wrapper、网络门、三个 Hook、Seatbelt、settings 与 Camoufox 启动器文件。是代码/配置基线，不是本次已抓包、断网或登录验收；实时网络状态/版本仍需另查。

| 项目 | 本机位置/配置 |
| --- | --- |
| 保护入口 | ~/.local/claude-guard/bin/claude |
| 原生 CLI | ~/.local/bin/claude，更新它不应替换保护入口 |
| 网络检查 | ~/.claude/hooks/network-killswitch.sh |
| 请求 Hook | ~/.claude/hooks/network-request-hook.sh |
| 工具规则 | ~/.claude/hooks/system-info-guard.sh |
| 网络门 | ~/.local/claude-guard/bin/claude-network-gate.py |
| 沙箱 | ~/.local/claude-guard/claude-network.sb |
| 登录入口 | ~/.local/claude-guard/bin/claude-camoufox |
| 持久化启动器 | /Applications/Camoufox Persistent.app/Contents/Resources/launch_camoufox.py |
| 设置 | ~/.claude/settings.json，其他机器还须查 CLAUDE_CONFIG_DIR |
| 端口 | CLI → gate 7899 → 专用上游 7898；控制口 7900；普通分流入口 7897 |
| listener | claude-guard-upstream，loopback、UDP 关闭，从其 proxy 解析路由 |

这些不是跨机器默认。旧模板 ~/.claude-guard/state.json 不是本机部署权威配置。

### 唯一目标节点（最新 Skill 要求）

    优秀|【3x】中转|台湾hinet动态家宽01

这是本机已有指定，不是其他机器的默认值。精确匹配完整名字；名字中的竖线不是列表分隔符。只接受单个 expected_node，不添加白名单、备用节点或按地区自动挑选。链式入口和 Selector 不算额外出口，但其最终叶子必须等于该目标。用户改选时替换原目标，重新校验并绑定，不能追加节点。

此前核对的运行中 Shell guard 与浏览器仍有历史多节点允许逻辑；本次只收紧 Skill，未修改这些运行文件。不能把旧实现作为新版规则，也不能声称运行环境已经变成单节点。以后若获准部署，应将两端同时收敛为用户指定的唯一节点，并测试其他任何叶子均拒绝。

### 最近变更

- 全局 → 规则模式，保留国内测试开发服务 DIRECT；Claude 专用入口独立绑定。
- 用户最新要求：只指定一个最终节点，不添加白名单或备用出口；保留单跳、链式和 Selector 解析。更换节点须明确替换旧目标并重绑会话。
- 固定公网 IP → CLI 同叶子且 TW 的新 IP 可更新；浏览器还有严格比较差异。
- 短探测 → 多端点、有限缓存/宽限，Hook 35 秒、控制调用约 32 秒；失败阻止 Hook 操作，不是波动自动 kill CLI。
- CLI 升级与保护入口分离；保留用户选定的 bypassPermissions，显式参数覆盖默认值。
- 不设置禁用鼠标环境变量，TTY 清理与网络检测分离。
- 只设置 Claude 的 BROWSER，保留正常 Chrome 用户资料；清账号不再作为维护默认步骤。

## 维护顺序

1. ccg_audit.py 获取前置摘要；只读确认服务、监听端口、shell 解析。磁盘存在不代表运行中。
2. 更新 Skill ≠ 部署；更新 CLI ≠ 重装保护；诊断 ≠ 改全局网络。
3. 备份将改的具体非凭证配置，增量编辑；保留其他 Hook、权限、鼠标偏好、开发例外，禁止旧模板整份覆盖。
4. 语法/离线模拟后再审计比较。重启 gate/CLI/浏览器须按授权说明影响。
5. 只报必要脱敏状态，不显示真实公网 IP、内部服务地址、secret、Cookie 或正文。
6. 分别交付变更、未变更、验证、限制；[保护边界](layers.md) 中的缺口不能写成已实现。

## 源码与使用副本

本次找到源码位于 tanyu-skills/claude-code-guard，Grok 使用独立副本 ~/.grok/skills/claude-code-guard。用户给的 GitHub 地址不等于本地 origin；发布前检查 remote、状态、授权，不能自动提交到其他远端。

只同步本次修改的 Skill 文件，保留副本其他文件，比较摘要。更新 Skill 不重启 Grok/Claude/Clash/浏览器。新任务可读新版；已加载旧 Skill 的任务需重新读取，不保证自动热更新。
