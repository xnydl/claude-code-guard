---
name: claude-code-guard
description: >
  配置、维护或排查 Claude Code 本地网络保护：Claude/Anthropic 的 HTTP(S) 走专用入站与固定出口；默认单节点，也可显式配置一个主节点和一个备用节点做 fail-closed 自动故障切换；shell、脚本、远端数据库不拦。核对 wrapper、Clash/Mihomo 专用入站、链式代理、动态住宅 IP、网络 Hook、macOS 沙箱与 Camoufox。也用于明确授权的账号残留扫描或清理。用户提到 claude-code-guard、Claude 防封、远端库被拦截、Seatbelt EPERM、代理断连阻断、节点漂移或主备切换时使用；不能保证不封号、绝对不泄漏或不同账号无法关联。
---

# Claude Code 网络保护 Skill

目标是可核验的路由约束，不是绕过服务条款或承诺账号安全。遵守服务适用地区与使用规则；不把节点名、住宅 IP 或第三方评分当作官方认可。复制步骤见 [README.md](README.md)。

## 流量分流（必须）

只保护 Claude Code / Claude CLI **发往 Claude、Anthropic 站点的 HTTP(S)**：`HTTP_PROXY` → 本地 gate → 专用入站 → 当前生效的 **一个** 最终叶子。默认固定单节点；只有用户明确指定主、备两个具体叶子和 Selector 路由根时，才启用受控主备切换。

**不要拦截** shell、脚本、git、远端数据库客户端。它们通常不用 HTTP 代理，Seatbelt 应放行真实网络，由 Clash 规则模式把国内目标 DIRECT。只拒绝进程改 Mihomo 控制口。

HTTP CONNECT 默认真 Claude 走专用入站。用户**当场授权**的公司/国内域名后缀，才可以送到规则入站；不要复制另一台机器的域名列表，也不要为了数据库去放宽专用入站。改沙箱后必须重启 Claude，旧进程仍是旧规则。

## 先分清维护还是新装

1. **维护已有环境优先**：读 wrapper、Hook、沙箱、启动服务和浏览器入口。不能因为附带安装器就重新安装。
2. 先读 [维护与部署识别](references/maintenance.md)。目标机器可能使用 `~/.claude-guard/` 新布局或 `~/.local/claude-guard/` 旧布局；必须先审计并识别真实运行版本，不能互相覆盖。
3. 用只读审计获取文件存在性、SHA-256 和有限设置：

       python3 "<SKILL>/scripts/ccg_audit.py"

   审计不调用网络、不读 Cookie/聊天/钥匙串、不证明流量安全。要记录浏览器启动器摘要时显式传 --browser-launcher "<已确认的脚本路径>"。
4. 记录变更前摘要和用户已有选择，再做最小修改。仅更新 Skill 时，只改 Skill 源码/使用副本，不改运行中脚本、代理、账号资料或系统设置。
5. 已有明确选择且与配置匹配时直接沿用。新出口未获选择、清理范围不清、需要停用保护或中断会话时才询问。

## 路由与节点规则

- Clash **规则模式**允许国内开发服务 DIRECT、Claude 走独立上游。TUN 开启不等于全部流量走代理；系统代理开关不能证明实际出口。Seatbelt 不拦 shell/脚本/远端库。
- 任一时刻**只能有一个生效的最终出口节点**，按完整叶子名精确匹配。默认配置只保存单个 `expected_node`。主备是显式可选能力：只允许一个 `primary_node` 和一个 `secondary_node`，二者都必须是用户指定的具体、不同、非 DIRECT/REJECT/PASS 叶子，Selector 必须且只能直接包含这两个叶子；失败阈值限制为 2-5，严格探测间隔限制为 5-60 秒。不得扩展成节点白名单、负载均衡、随机选择或候选池轮换。支持单跳与链式代理；“单跳”不是 Clash DIRECT。
- 从实际专用入站的 proxy 解析 Selector 的 now，再核对 dialer-proxy/入口依赖。允许 Selector 作为路由根，但最终出口必须等于当前唯一 `expected_node`。循环、缺失、DIRECT/REJECT/PASS 或无法确定的链路不能当作已验证。
- 🤖 AI服务 可指向台湾 Selector，但不必是 CLI 专用入口的路由根。不能只看 UI，也不能假定旧策略组 claude-guard-exit 存在。
- 固定节点不等于固定公网 IP。同一指定节点的新 TW 动态 IP 可更新 CLI 会话；其他任何叶子均不应放行。未启用主备时，换出口必须由用户明确重新指定并替换旧目标。启用主备时，只能从主切到预先指定的备用，不能临时追加第三节点。节点名、旗帜、显示延迟都不是地区证据。
- 短时重试只能使用当前 `expected_node`，不能回退 DIRECT、系统代理或未指定节点。已有新鲜严格验证时，单次有界的控制口超时、trace 超时或 Anthropic 临时不可达可保留上一条已验证路由并立即复核，连续达阈值才关门；叶子漂移、地区不符、TUN/IPv6 或主备状态不一致仍立即拒绝。主节点连续失败达到阈值后，切换过程必须先置 `switching=true` 并关闭活动隧道，严格验证备用节点的实际路由、地区和 Anthropic 可达性后才能放行。失败必须读回确认回滚；无法确认时保持 `blocked`。默认不自动回切主节点。

分层、重试和验收读 [保护边界](references/layers.md)；浏览器读 [Camoufox](references/fingerprint.md)。

## 本机已确认偏好

以下不是其他客户的新装默认值：

- 保留规则分流、任一时刻唯一生效出口、动态 IP 兼容和会话恢复；本机已按用户指定启用固定主备，不扩展成节点池。
- 本机明确选择默认 --permission-mode bypassPermissions；显式参数优先。它放宽工具权限，不增强网络保护；新装不擅自开启。
- **不要设置 CLAUDE_CODE_DISABLE_MOUSE**。鼠标转义码先排查 TTY/raw mode、退出清理及后台进程读写终端，不用禁用鼠标掩盖问题。
- 用 Claude 进程 BROWSER 指向 claude-camoufox；不改 macOS 全局默认浏览器，不碰普通 Chrome 的任一 profile。
- 不因更新 CLI/Skill 自动清凭证、聊天、Cookie 或重置指纹；读 [清理边界](references/identity-purge.md)。

## 新环境或迁移

先读 [客户端与旧模板](references/clients.md)。探测系统、真实客户端、代理/控制端口和已有部署，不复制作者节点/端口/路径：

    python3 "<SKILL>/scripts/ccg_detect.py" --list

原始探测 JSON 可能含控制器 secret，不能原样发布。新环境默认只让用户确认一个完整叶子名。用户明确要求主备时，再确认一个备用叶子和一个 Selector 路由根；不能从地区或测速结果自动挑节点，也不能把 Selector 成员整体当作白名单。只能检测端口时不能声称已验证最终节点。

附带 `ccg_install.py`、`ccg_guard.py`、`ccg_gate.py` 和 `ccg_failover.py` 是通用模板，**不等同现用本机策略**。默认仍为单节点；同时提供 `--secondary-node` 与 `--ai-group` 才生成主备配置。不要用模板回滚或覆盖已有部署；安装器会拒绝覆盖发现的保护文件/已有 Hook。新环境也先做能力差异审查、适配及隔离测试，再按授权部署。

## 验收与交付

- 语法/单测 → 比较文件 → 只读路由核对 → 无账号的独立拒绝路径测试。
- 用户允许影响连接后才能切节点、关 TUN 或断网测试；不打断正在运行的任务。
- 测试错误节点、错误地区、控制器失联、上游断开、IPv6/DNS、备用 loopback 代理及长连接；启用主备时还要测试切换屏障、备用探测失败、回滚失败、活动隧道关闭和不会自动回切；没测的写“未验证”。
- --fast 不证明地区；Hook 存在不证明每条 HTTP 请求被检查；启动器路径不证明当前进程受沙箱限制。
- 更新 CLI 只更新真实二进制，保留 wrapper/Hook/设置/服务。用前后摘要证明保护文件未改；没有前置摘要就不能宣称“哈希证明未改”。
- 更新 Skill 后运行 scripts/test_skill.py。用户明确要求发布到 GitHub 时才提交并推送该仓库。
