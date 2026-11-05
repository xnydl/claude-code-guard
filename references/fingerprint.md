# Fingerprint Chromium Guarded

浏览器维护和新装统一使用 **Fingerprint Chromium Guarded**（fingerprint-chromium），不再用 Camoufox 打开网页或接收 CLI 登录。以下依据 2026-11-05 对当前 macOS 启动器的只读核对，是代码/配置基线，不代表本次已做登录、抓包或断网验收。更新 Skill 不部署这些设置，也不更改代理客户端的运行配置。

## 入口、profile 与固定指纹

- 手动入口是 `~/Applications/Fingerprint Chromium Guarded.app`；安装在其他目录时现场核实。不能双击内置 `Chromium.app` 或裸跑 `chrome`/`Chromium`，否则绕过启动器。
- CLI 的 BROWSER 使用 `~/.local/claude-guard/bin/claude-fingerprint-chromium`，通过受限本地 IPC 请求同一应用打开官方登录 URL；已有窗口复用同一受保护实例。
- 当前资料根目录为 `~/Library/Application Support/Fingerprint Chromium Guarded/`：`profile/` 是独立 user-data-dir，`device.json` 保存固定 seed，`launch_fingerprint_chromium.py` 是启动器，`geo_cdp.py` 处理定位覆盖。审计脚本摘要，不读取 Cookie、密码、历史记录、登录 URL 或 seed 值。
- 当前是一份固定 profile，**不是** Camoufox 旧的按节点分目录逻辑。不因代理开关、动态 IP 或更新 Skill 重建 profile/seed，不迁移、合并或删除其他浏览器登录资料。换身份或另建 profile 须另外授权。
- seed 应是稳定的非零 32 位整数；已有文件损坏就拒绝启动，不能静默重建。不同新环境不复制作者 seed。
- 浏览器 profile 单实例锁防止数据库损坏，不应变成 CLI 的全局单例限制；多个 CLI 登录请求可交给同一浏览器实例。不改系统默认浏览器，登录由用户完成。

## 节点与公网 IP 是两种约束

1. 读取 CLI 同一份节点策略。当前旧布局使用 `~/.local/claude-guard/network-policy.json` 的 `selected_node` 与 `clash.dedicated_proxy`；新模板 `expected_node` 属于另一布局，不能混写。
2. 从实际专用入站解析 Selector/链式依赖，最终叶子精确等于指定目标。浏览器全部网页 HTTP(S) 使用独立本地 gate → 专用入站，不能回退普通规则入口、系统 PAC、DIRECT 或其他叶子。
3. 启动前严格验证实际公网 IP/地区，用**同一个 IP**查询 GeoIP。节点名、旗帜、延迟、其他浏览器出口及旧缓存不能替代此证据。
4. 固定节点不等于静态公网 IP。当前浏览器钉住启动时验证的 IPv4；同叶子 IP 改变也关闭受保护实例，重开后按新 IP 查询 GeoIP，保留原 profile/seed。不能照搬 CLI 的同叶子动态 IP 更新行为。
5. 只维护浏览器不改变 CLI Hook、沙箱、分流、节点或系统网络；节点重载/关闭实例须先确认授权及连接影响。

已有部署显式启用固定主备时，保留该能力，但浏览器仍只认可当前生效叶子与启动 IP。CLI 切到备用不等于浏览器已同步迁移；浏览器须阻断后重新验证并重开，不扩成多节点允许列表。

## 版本、语言、时区

- 核对来源、架构、真实二进制版本和 SHA-256，再记录版本。当前 macOS 基线为 148.0.7778.215，不是“最新版”，本次不升级；上游补丁或摘要不可核验时说明来源限制。
- 当前启动参数包含 `--user-data-dir=<专用 profile>`、`--fingerprint=<固定 seed>`、`--fingerprint-platform=macos`、既定 platform-version、`--fingerprint-brand=Chrome`。平台/version 是该 profile 的选择，不是 Windows 或其他机器的默认值。
- 当前台湾配置为 `--timezone=Asia/Taipei`、`--lang=zh-TW`、`--accept-lang=zh-TW,zh`，进程 TZ/locale 对应；不改系统时区，不靠页面加载后 JS 替换 Date。
- 新环境按已验证出口地区及用户选择确定 locale、IANA 时区和平台。检查首页、新标签、新窗口、跨站 iframe 的 Intl、Date offset、语言、UA/UA-CH；参数存在不等于生效。台湾 offset=-480 是正常 UTC+8，不是大陆 IP 泄漏。

## 定位跟随出口，不使用本机 GPS

- 离线 GeoIP 查询同次验证的公网 IP，校验 IP、国家、IANA 时区、有限坐标和库时效。当前台湾策略要求 Asia/Taipei、台湾范围坐标，库超过 45 天拒绝使用。失败不能用本机真实位置、随意固定城市或空结果放行。
- 保留 `--remote-debugging-pipe` 私有管道，不开放 DevTools TCP 监听。启动先停在 `about:blank`，默认拒绝未覆盖的定位请求。
- `Target.setAutoAttach` + `waitForDebuggerOnStart`：对新 page、跨站 iframe、webview 先执行 `Emulation.setGeolocationOverride`，再恢复执行。按既有授权处理受管 context 位置权限后才导航业务页，不新增系统精确位置授权。
- 管道断开、覆盖失败或实际 IP 变化就关闭该实例。不能仅给首页设一次坐标或只注入 navigator.geolocation 就宣称全覆盖。
- **不要误删现有依赖**：当前 `lookup_geoip.py` 仍借用旧 Camoufox Python 环境的离线 GeoIP 数据/读取库，不启动 Camoufox，不使用其 Cookie。这是定位查询依赖而非浏览器入口；此次不卸载。未来完全去除该依赖须另行替换为独立 GeoIP 读取器，验证后再移除。

## DNS、WebRTC、IPv6

目标是限制本地解析/直连旁路，不是让检测页“看不见 DNS”。当前 Chromium 实例配置：

```text
--proxy-server=http://127.0.0.1:<浏览器 gate 端口>
--proxy-bypass-list=<-loopback>
--disable-non-proxied-udp
--force-webrtc-ip-handling-policy=disable_non_proxied_udp
--disable-quic
--dns-prefetch-disable
--host-resolver-rules=MAP * ^NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1
--disable-background-networking
```

- HTTP 代理对目标域名代解析；gate 只向数字 loopback 上游建连接。代理列表不追加 DIRECT，不设置 `--no-proxy-server`。
- 核对所选版本 resolver sentinel；当前是 **`^NOTFOUND`**，不是旧 `~NOTFOUND`。它阻止浏览器本地解析，目标域名仍由代理侧处理。
- 仅在该专用 user-data-dir 的 `Local State` 设置 `dns_over_https.mode="off"`，避免浏览器自带 DoH 绕过既定解析策略。写前解析、保留其他字段，损坏就阻断；不改普通 Chrome 或全局策略。
- 关闭该实例 DoH 不关闭网站 HTTPS/TLS；代理隧道和代理侧 DNS 是否加密需独立核验，不能声称所有 DNS 自动加密。
- WebRTC 设置限制非代理 UDP，不是关闭全部 WebRTC。分别验证 STUN/候选地址、QUIC、IPv4/IPv6 直连拒绝路径；参数不能替代内核出站限制。
- 保留现有活跃网卡 IPv6 关闭、Mihomo ipv6:false 与 TUN 要求，分别核对。更新 Skill 不执行网卡命令或重载代理。
- 远端递归 DNS 的 IP/国家可与代理公网出口不同，不单独构成本地泄漏；检测页空结果可能是测试失败/受阻，也不证明安全。用同轮唯一测试域名、实际路径和必要抓包区分浏览器、节点引导 DNS 与授权国内分流，不记录登录 URL/正文。
- 浏览器局部设置与系统 DNS 是两层。用户明确要求普通 Chrome/CLI 一并使用代理 DNS 时，按 [Clash DNS](dns.md) 单独授权部署；不能因浏览器维护自动改全局解析策略。
- TYPE64（SVCB）、TYPE65（HTTPS）辅助验收见 [保护边界](layers.md)。不为检测页变绿屏蔽全部记录。

## 持续校验与超时

- 本地 relay 对新连接做快速检查；当前约每 2 秒快速、每 30 秒严格复核出口。存在轮询/排队窗口，不称逐包或零窗口防护。
- 检查失败、策略/节点变化或定位控制故障时，关闭 relay 存量连接和该浏览器进程组，不误杀其他浏览器/CLI。
- 探测/重试必须有界。若设置 30 秒预算，应覆盖全部尝试和排队；重试期封闸，只有同叶子、同 IP、定位一致才恢复。明确不安全的节点/地区/配置变化立即阻断。不同后端当前实现不相同，不笼统写成全部已支持 30 秒，也不借此改 CLI Hook 或代理设置。
- 本地 URL 分发就绪等待与上游代理连接超时是不同预算，不拉长前者掩盖后者失败。

## 维护与新装

1. 维护先核对应用、BROWSER、启动器、GeoIP helper、profile/seed 路径和只读摘要，不运行安装器或动现用进程。新装从 [项目仓库](https://github.com/adryfish/fingerprint-chromium) 选择目标 OS/架构版本，按该版本文档审查参数。
2. 获准部署后准备独立 profile/seed、受管启动器、本地 gate、GeoIP、私有 CDP 定位覆盖。仅下载原版浏览器或安装器成功退出不代表保护完成。
3. BROWSER 仅接受 Claude 官方 HTTPS 登录 URL，经私有 IPC 交给同一受保护实例；确认网络检查及打开成功后才返回成功。不把登录 URL 写日志或拼接 shell 执行。
4. `fingerprint-chromium.sh/.ps1` 调用 `ccg_browser.py`。macOS 分发到已部署应用的私有 Unix socket，**不安装或替代完整启动器**。Windows/Linux 尚无等效分发实现，模板明确阻断，须另行适配验收，不退回 Chrome/Edge。
5. `camoufox.sh/.ps1`、`claude-camoufox.sh` 仅保留旧名兼容跳转，目标也是 Chromium；新配置不引用。不因换入口删除旧 profile、重签应用或重置系统权限。

## 检查清单

- [ ] GUI 与 CLI 到同一受保护 Chromium，未裸开内置二进制；缺失/未就绪/URL 拒绝均阻断，无普通浏览器回退。
- [ ] 叶子、专用入站及全部网页路径一致；公网 IP、GeoIP、时区、坐标一致；不把绿延迟当验证。
- [ ] profile/seed 重启保持，未迁移账号资料；浏览器锁不限制多个 CLI。
- [ ] 新窗口/标签/跨站 iframe 在运行前覆盖定位；管道故障、IP/节点变化会阻断，原 profile 不删除。
- [ ] 专用 DoH、resolver 规则、QUIC/WebRTC/IPv6 与本地 DNS 旁路分别验收，未改系统/普通 Chrome DNS。
- [ ] UA/UA-CH、语言、时区与所选版本一致；保留来源和版本限制。
- [ ] 获准后再做错误节点、代理断开、直连、长连接及重启测试；未测项标为未验证，不自动登录真实账号验收。

协议依据：[Chromium 代理/DNS](https://chromium.googlesource.com/chromium/src/+/HEAD/net/docs/proxy.md)、[CDP 自动附加](https://chromedevtools.github.io/devtools-protocol/tot/Target/#method-setAutoAttach)、[CDP 定位覆盖](https://chromedevtools.github.io/devtools-protocol/tot/Emulation/#method-setGeolocationOverride)。以选定版本及现场行为为准。
