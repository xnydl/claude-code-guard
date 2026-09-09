---
name: claude-code-guard
description: >
  配置、维护或排查 Claude Code 本地网络保护：核对现有 wrapper、Clash/Mihomo 专用入站、单一固定最终出口节点、链式代理、动态住宅 IP、网络 Hook、macOS 沙箱与 Camoufox 登录浏览器。也用于明确授权的账号残留扫描或清理。用户提到 claude-code-guard、Claude 防封策略、代理断连阻断、节点漂移、网络 Hook 误拦截时使用；不能保证不封号、绝对不泄漏或不同账号无法关联。
---

# Claude Code 网络保护 Skill

目标是可核验的路由约束、故障阻断与本地数据隔离，不是绕过服务条款或承诺账号安全。遵守服务适用地区与使用规则；不把节点名、住宅 IP 或第三方评分当作官方认可。

## 先分清维护还是新装

1. **维护已有环境优先**：读 wrapper、Hook、沙箱、启动服务和浏览器入口。不能因为附带安装器就重新安装。
2. 先读 [维护与本机基线](references/maintenance.md)。现用 ~/.local/claude-guard/ 与旧模板 ~/.claude-guard/ 是两套实现，不能互相覆盖。
3. 用只读审计获取文件存在性、SHA-256 和有限设置：

       python3 "<SKILL>/scripts/ccg_audit.py"

   审计不调用网络、不读 Cookie/聊天/钥匙串、不证明流量安全。要记录浏览器启动器摘要时显式传 --browser-launcher "<已确认的脚本路径>"。
4. 记录变更前摘要和用户已有选择，再做最小修改。仅更新 Skill 时，只改 Skill 源码/使用副本，不改运行中脚本、代理、账号资料或系统设置。
5. 已有明确选择且与配置匹配时直接沿用。新出口未获选择、清理范围不清、需要停用保护或中断会话时才询问。

## 路由与节点规则

- Clash **规则模式**允许国内开发服务 DIRECT、Claude 走独立上游。TUN 开启不等于全部流量走代理；系统代理开关不能证明实际出口。
- **只能指定一个最终出口节点**，按完整叶子名精确匹配。不得添加节点白名单、备用出口或自动轮换；配置仅保存单个 expected_node 字符串，不接受列表或从多个候选中默认选一个。支持单跳与链式代理；“单跳”不是 Clash DIRECT。
- 从实际专用入站的 proxy 解析 Selector 的 now，再核对 dialer-proxy/入口依赖。允许 Selector 作为路由根，但最终出口必须等于唯一指定节点。循环、缺失、DIRECT/REJECT/PASS 或无法确定的链路不能当作已验证。
- 🤖 AI服务 可指向台湾 Selector，但不必是 CLI 专用入口的路由根。不能只看 UI，也不能假定旧策略组 claude-guard-exit 存在。
- 固定节点不等于固定公网 IP。同一指定节点的新 TW 动态 IP 可更新 CLI 会话；其他任何叶子均不应放行。换出口必须由用户明确重新指定，替换旧目标后重新校验/绑定，不能把它追加成备用节点。节点名、旗帜、显示延迟都不是地区证据。
- 短时重试只能使用唯一指定节点，不能回退 DIRECT、系统代理或其他节点；地区明确不符立即拒绝。缓存和轮询有时间窗口，必须说明。

分层、重试和验收读 [保护边界](references/layers.md)；浏览器读 [Camoufox](references/fingerprint.md)。

## 本机已确认偏好

以下不是其他客户的新装默认值：

- 保留规则分流、唯一指定最终出口、动态 IP 兼容和会话恢复。
- 本机明确选择默认 --permission-mode bypassPermissions；显式参数优先。它放宽工具权限，不增强网络保护；新装不擅自开启。
- **不要设置 CLAUDE_CODE_DISABLE_MOUSE**。鼠标转义码先排查 TTY/raw mode、退出清理及后台进程读写终端，不用禁用鼠标掩盖问题。
- 用 Claude 进程 BROWSER 指向 claude-camoufox；不改 macOS 全局默认浏览器，不碰普通 Chrome 的任一 profile。
- 不因更新 CLI/Skill 自动清凭证、聊天、Cookie 或重置指纹；读 [清理边界](references/identity-purge.md)。

## 新环境或迁移

先读 [客户端与旧模板](references/clients.md)。探测系统、真实客户端、代理/控制端口和已有部署，不复制作者节点/端口/路径：

    python3 "<SKILL>/scripts/ccg_detect.py" --list

原始探测 JSON 可能含控制器 secret，不能原样发布。新环境只让用户确认一个完整叶子名，不提供添加白名单或备用节点的选项；Selector 可是路由根但不是最终身份。只能检测端口时不能声称已验证最终节点。

附带 ccg_install.py、ccg_guard.py 等是旧通用模板，**不等同现用本机策略**。不要用其回滚已有部署；安装器会拒绝覆盖发现的保护文件/已有 Hook。新环境也先做能力差异审查、适配及隔离测试，再按授权部署。

## 验收与交付

- 语法/单测 → 比较文件 → 只读路由核对 → 无账号的独立拒绝路径测试。
- 用户允许影响连接后才能切节点、关 TUN 或断网测试；不打断正在运行的任务。
- 测试错误节点、错误地区、控制器失联、上游断开、IPv6/DNS、备用 loopback 代理及长连接；没测的写“未验证”。
- --fast 不证明地区；Hook 存在不证明每条 HTTP 请求被检查；启动器路径不证明当前进程受沙箱限制。
- 更新 CLI 只更新真实二进制，保留 wrapper/Hook/设置/服务。用前后摘要证明保护文件未改；没有前置摘要就不能宣称“哈希证明未改”。
- 更新 Skill 后运行 scripts/test_skill.py 及 Skill Creator 的 quick_validate.py，比较源码与使用副本。未经请求不提交或推送远端。
