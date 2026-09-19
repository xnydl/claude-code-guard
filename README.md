# Claude Code Guard

Claude Code Guard 是一个给 Claude Code / Claude CLI 使用的本地网络保护 Skill：把发往 Claude、Anthropic 的 HTTP(S) 请求送入专用代理入口，并绑定到当前唯一生效的最终出口。默认使用单节点；只有用户明确指定时，才启用一主一备的 fail-closed 自动故障切换。

它解决的是“路由约束与可核验维护”，不是绕过服务条款，也不保证不封号、绝对不泄漏或不同账号无法关联。不要把节点名、住宅 IP、旗帜或第三方评分当成官方认可。

本文是从安装到验收的完整教程。只想把 Skill 装进 Codex、Claude Code 或其他 Agent 时，先看[快速安装](#快速安装)；已经有保护环境时，先看[已有环境维护](#已有环境维护)，不要直接运行旧安装器覆盖现有配置。

## 保护边界

| 流量 | 怎么走 |
| --- | --- |
| Claude Code / CLI → `claude.ai` / `api.anthropic.com` | `HTTP_PROXY` → 本地 gate `:7899` → 专用入站 `:7898` → **当前唯一生效叶子** |
| 用户授权的公司/国内 HTTP 域名 | gate → 规则入站 `:7897` → Clash Rule（通常 DIRECT） |
| shell / 脚本 / MySQL / Redis / MongoDB / git | **真实网络**，由 Clash 规则与系统网络处理 |
| Mihomo / Clash 控制口 | 沙箱拒绝，避免进程自行切换出口 |

默认只指定**一个**完整叶子名。显式启用主备时，也只允许预先指定的一个主节点和一个备用节点；任一时刻仍只有一个最终叶子生效。不做节点白名单、负载均衡、随机选择或多节点轮换。

## 工作原理

```text
Claude Code / Claude CLI
        │ HTTP_PROXY / HTTPS_PROXY
        ▼
本地 network gate（示例 :7899）
        │
        ▼
Clash / Mihomo 专用入口（示例 :7898）
        │ 只解析到当前一个最终叶子
        ▼
用户选定的出口节点
```

shell、脚本、git、MySQL、Redis、MongoDB 等通常不走 HTTP 代理，应该由真实网络和 Clash 规则分流；不要为了“所有流量都受保护”把它们强行送进 Claude 专用入口。macOS 沙箱只拒绝进程修改 Clash/Mihomo 控制口，不能替代 HTTP_PROXY、Clash 规则或 TUN 的路径验证。

## 快速安装

需要 Node.js 22+。在终端执行：

```bash
npx skills add xnydl/claude-code-guard -g -y
```

安装后重新打开 Agent 会话，然后输入：

```text
/claude-code-guard
```

安装 Skill **不会**自动改 Clash、wrapper、沙箱、账号资料或浏览器。Skill 只是让 Agent 获得本项目的维护与诊断说明；网络保护仍需按本教程完成配置并验收。

如果不使用 `npx skills`，也可以把仓库目录链接到对应工具的 skills 目录：

```bash
mkdir -p ~/.claude/skills
ln -s "$PWD/claude-code-guard" ~/.claude/skills/claude-code-guard
```

Grok 使用 `~/.grok/skills/claude-code-guard`；Windows 使用 `%USERPROFILE%\\.claude\\skills\\claude-code-guard` 或 `%USERPROFILE%\\.grok\\skills\\claude-code-guard`。详细说明见 [INSTALL.md](INSTALL.md)。

## 复制到另一台机器

不要复制别人的节点名、端口或公司域名。先打开你自己的梯子。

1. Clash / Mihomo 使用**规则模式**；通常开启 TUN、关闭 IPv6。mixed-port 作为普通规则入口（示例 `:7897`）。
2. 增加一条**专用 mixed 入站**（示例 `:7898`，只听 `127.0.0.1`，UDP 关）。单节点时 `proxy` 填选定叶子；主备时填一个专用 Selector 路由根，由 gate 只在受控切换期间修改它。
3. Claude 的 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 指向 gate（示例 `:7899`）。不要把国内库主机写进 `NO_PROXY` 来“绕过保护”——数据库客户端本来就不走 HTTP 代理。
4. Seatbelt 放行普通出站，**只拒绝** Clash 控制 socket。旧模板若 `deny network-outbound` 只放行 localhost，Go 的 MySQL/Redis/Mongo 会 `EPERM`。改沙箱后**必须重启 Claude**，旧进程还是旧规则。
5. 启动前或发 prompt 时校验：当前叶子等于指定叶子；同叶子的动态 IP 可以更新，换叶子就拦截。失败拦截这一次请求，不要杀进程。
6. 可选：`CCG_RULES_HOST_SUFFIXES=example.com,corp.example`（逗号分隔）。只有 HTTP 代理 CONNECT 会看这份列表，不要把别人的域名抄过来。

探测（不自动改配置）：

```bash
python3 scripts/ccg_detect.py --list
```

已有保护环境先审计，不要重跑安装器覆盖：

```bash
python3 scripts/ccg_audit.py
```

## 新环境的完整配置流程

### 1. 先识别环境

确认操作系统、Claude 命令实际指向、Clash/Mihomo 类型、控制器端口、监听端口和已有 wrapper。探测脚本不自动修改系统：

```bash
python3 scripts/ccg_detect.py --list
```

探测结果可能包含控制器 secret、内部地址或当前节点信息，不要原样贴到公开 issue、聊天或网页。

### 2. 默认单节点，可显式指定固定主备

从你自己的 Clash/Mihomo 配置和运行时状态中选出一个完整叶子名，例如 `TW-Home-01`。默认不把节点列表或“自动选择”当成绑定目标。Selector 可以作为路由根，但最终解析出的叶子必须等于当前唯一目标。

固定的是叶子名称，不等于公网 IP 永久不变；同一叶子的动态 IP 可以更新。换叶子时要明确替换旧目标、重新绑定并重新验收。只有你明确要求“主挂后自动切备用”时，才再指定一个不同的具体备用叶子和一个专用 Selector；不能追加第三个节点。

### 3. 配置分层入口

典型本机端口关系如下，端口只是示例，必须以自己的运行配置为准：

| 入口 | 示例 | 用途 |
| --- | ---: | --- |
| 规则入口 | `7897` | 普通开发流量与用户授权域名 |
| 专用入口 | `7898` | 绑定唯一最终叶子的 Claude 流量 |
| 本地 gate | `7899` | Claude wrapper 的 HTTP(S) 代理 |

专用入口应只监听 loopback、关闭 UDP，并指向你选定的单个叶子。旧配置若使用 `deny network-outbound` 只放行 localhost，会把 MySQL/Redis/Mongo 等直接连接打成 `EPERM`；应改为放行普通出站，仅拒绝 Clash 控制 socket。修改沙箱后必须完全重启 Claude，旧进程仍在使用旧规则。

### 4. 运行安装器前先读差异

仓库里的 `ccg_install.py`、`ccg_guard.py`、`ccg_gate.py`、`ccg_failover.py` 是跨平台通用模板，不等同于某台机器上已经运行的保护部署。新环境可以先让安装器输出建议，但不要把成功退出当成“网络保护已完成”：

```bash
python3 scripts/ccg_install.py --node "你的唯一叶子名" --region TW
```

显式主备需要两个具体叶子和一个**恰好只包含它们**的 Selector：

```bash
python3 scripts/ccg_install.py \
  --node "主节点完整名称" \
  --secondary-node "备用节点完整名称" \
  --ai-group "专用 Selector 名称" \
  --region TW
```

主节点达到连续失败阈值后，gate 先封闸、关闭其管理的活动隧道，再切到预先指定的备用并严格核对实际叶子、地区和 Anthropic 可达性。失败阈值限制为 2-5，严格探测间隔限制为 5-60 秒；备用失效会保持阻断，默认不自动回切。已有新鲜严格验证时，单次有界控制口/trace/Anthropic 临时失败只保留当前路由并立即复核；连续达阈值才关门，而叶子、地区、TUN、IPv6 或主备状态异常仍第一次就关门。

它不会自动合并 Mihomo 配置，也不会自动部署 listener 或服务。已有 `~/.local/claude-guard/`、`~/.claude-guard/`、Hook 或启动器时，先维护现有实现。

### 5. 验证允许与拒绝路径

至少验证这些情形：

1. 当前最终叶子等于唯一指定目标时，Claude 可以发起请求。
2. 切换到错误节点、错误地区或无法解析的链路时，本次请求被阻止。
3. 控制器失联、专用入口断开、IPv6/DNS 配置不完整时，不把旧缓存当成新成功。
4. shell、脚本和远端数据库仍能按预期工作，不因沙箱误拦截而出现 `EPERM`。

`--fast` 只能做快速配置检查，不能证明地区；Hook 存在不能证明每一条 HTTP 请求都被检查；启动器路径也不能证明当前进程确实受沙箱限制。

## 已有环境维护

已有保护环境时，顺序应是：

```bash
# 获取只读前置摘要
python3 scripts/ccg_audit.py

# 离线验证 Skill 文件
python3 scripts/test_skill.py
```

维护时保留现有 wrapper、Hook、权限偏好、开发分流和普通浏览器资料；不要因更新 Skill 或 Claude CLI 自动清 Cookie、聊天、钥匙串、账号或 Camoufox profile。更新 Skill 也不等于部署更新，不需要顺手重启 Clash、Claude 或浏览器。

账号残留扫描或清理必须有明确的应用、账号和 profile 范围授权。先读[清理边界](references/identity-purge.md)，不要把“更新工具”理解成“可以清空登录资料”。

## 常见问题排查

### 远端数据库被拦，本地数据库正常

通常是旧 Seatbelt 只放行 localhost，或把数据库连接错误送进了 Claude 专用 HTTP 入站。确认沙箱已放行普通出站、数据库没有写进 `NO_PROXY` 规避保护逻辑、Clash 规则仍负责国内直连；修改后完全重启 Claude。

### 改了沙箱文件仍然 `EPERM`

正在运行的 Claude 进程不会自动加载新沙箱。关闭旧进程并重新从保护入口启动，再复查实际命令路径与环境变量。

### 节点名正确，但仍无法确认出口

节点名、旗帜和延迟都不是地区证据。通过专用入站解析 Selector 的 `.now`、`dialer-proxy` 依赖和实际连接链，确认最终叶子；控制器不可用或链路不完整时，结论只能是“未验证”。

### 想加备用节点自动切换

可以，但不是默认行为。必须显式指定一个主节点、一个备用节点和一个 Selector 路由根；主备都是具体叶子。该能力不会建立白名单、随机轮换或自动回切。

### 想把所有流量都经过 Claude 专用入口

不要这样做。数据库、git 和开发服务不应被送到境外 Claude 出口；它们应保持真实网络并使用 Clash 规则分流。更严格的全流量 fail-closed 是独立改造，不能仅靠 Prompt Hook 或一个 HTTP 代理变量宣称完成。

## 更新与验收清单

- [ ] Skill 已安装，且新会话能读取 `/claude-code-guard`。
- [ ] 已确认本机真实 wrapper、Hook、沙箱、代理入口和控制器。
- [ ] 任一时刻只有一个完整 `expected_node`；未显式启用主备时没有备用节点或自动轮换。
- [ ] 启用主备时，只有一主一备，Selector 真实叶子、`active_role` 和 `expected_node` 一致，且切换/回滚/备用失效路径已验证。
- [ ] Claude/Anthropic 走 `HTTP_PROXY` → gate → 专用入口。
- [ ] shell、脚本、git、数据库未被错误送进专用入口。
- [ ] 错误节点、错误地区、控制器失联和入口断开会拒绝相应操作。
- [ ] `python3 scripts/test_skill.py` 通过；未测试的网络能力明确标记为未验证。

完整的 Agent 操作边界见 [SKILL.md](SKILL.md)，客户端识别见 [references/clients.md](references/clients.md)，维护顺序见 [references/maintenance.md](references/maintenance.md)，分层与验收限制见 [references/layers.md](references/layers.md)。

---

打个小广

AI 代充：https://ssyai.xytpark.cn/

L 站用户可享社区价，每个品一月一次优惠

需要大量的客户可以开个代理，预充的金额会到你的余额

支持企业对接，对公转账，开票，普票专票都可

也欢迎佬友们吃回扣，合作共赢～（为了不浪费我的富可敌国，我要争取做到每日冒泡 hh

原作者的邀请链接：https://ssyai.xytpark.cn/register?invite=R73D442E6A446
