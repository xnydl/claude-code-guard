# Clash 代理 DNS：配置、例外与验收

仅适用于 Clash/Mihomo。此文与 [订阅扩展模板](../scripts/clash-proxy-dns.js) 支持用户**明确选择**的隐私优先 DNS 策略，不自动部署、不更改系统网卡 DNS、代理开关、沙箱或浏览器资料。

## 先区分三层

1. **系统查询被接管**：TUN 把匹配的 DNS 查询交给 Clash；fake-ip 返回虚拟地址。这不证明上游解析已经走代理。
2. **目标域名的上游解析**：`nameserver` / `direct-nameserver` 决定普通域名交给谁；`#<节点名>` 固定的是 DoH 连接的代理路径。网卡填写 `1.1.1.1` 不代表最终解析器就是 Cloudflare。
3. **节点入口引导**：`proxy-server-nameserver` 只解析代理节点入口域名；`default-nameserver` 用于解析 DNS 服务器自身域名。不能把这两项中的国内 DNS 地址单独当作网页/CLI 泄漏证据，也不能让节点入口递归依赖尚未建立的同一代理。

普通 Chrome、受保护 Chromium 和 CLI 的解析方式可能不同。HTTP 代理代解析、浏览器独立 DoH、预解析与插件/子进程都要分别核对。浏览器无结果可能是检测失败/受阻，不证明 CLI 无泄漏；DNS 泄漏通常暴露域名，不等于对话、Cookie 或密钥已泄露。

## 这份可选策略具体做什么

- 保留原网站规则分流、节点/专用 listener、IPv6 关闭及开发服务普通出站；**不把所有 TCP 送进 Claude 专用入口**。
- 复用现有 `claude-guard-upstream` listener 直接指向的唯一具体叶子，不复制作者节点名或端口，不新建候选池。
- `nameserver` 与 `direct-nameserver` 都使用经该叶子的 Cloudflare/Google DoH。即使网站业务流量 DIRECT，它的解析也采用这一路径。
- 清除旧 `nameserver-policy` / `fallback` 等可能选择其他普通域名解析器的条目；节点不可用时解析失败，不添加国内/明文回退。
- 节点入口引导单独使用 AliDNS/DNSPod 的数字 IP HTTPS 端点并显式 DIRECT，保留证书校验；**这是加密但不经节点的例外**，不能宣称所有 DNS 都已走代理。地址只是公开模板选择，不是必须的跨机器默认，部署前确认可达性与用户接受的解析方。
- 保留现有 DNS 监听、hosts、fake-ip 范围/过滤等未指定字段。内网 split-DNS、企业域名、服务发现和特殊 DNS 策略必须先盘点，不能盲目清空；必要时适配明确范围的本地例外并披露，不把内部域名送到公网。

取舍：远程 DNS 可能改变国内 CDN 命中/延迟，指定节点故障也可能让原本直连的网站暂时无法解析；这与“国内 DNS 优先”的策略不同。遇到慢不能偷偷恢复直连回退，应让用户在隐私和可用性之间明确选择。

模板要求 listener **直接指向具体 proxy**。同名/缺失叶子、DIRECT/REJECT/PASS、Selector 或名字包含 DNS 参数分隔符时拒绝生成，避免把不存在的标签误认作接口。已有固定主备或 Selector 路由根时不能直接套用：需将 DNS 与 guard 当前生效角色、切换屏障一并适配并验收，不可暗中改主备或固定到过期主节点。

## 获准部署时的顺序

1. 只读记录当前生效订阅、扩展脚本/覆写优先级、DNS/TUN/网卡、指定 listener/叶子和已有内网 DNS 例外；备份将修改的非凭证文件。不要公开原始订阅、控制器 secret 或内部域名。
2. 选择正确的**订阅扩展脚本**位置，增量合入模板中的 `main` 逻辑，保留已有业务扩展。不要只改会被重新生成的 `clash-verge.yaml`，不要覆盖整个订阅或全局脚本。
3. 普通公网 53 查询需 TUN 接管。按选定 Mihomo 版本核对 UDP 与 TCP，常见配置分别为 `any:53`、`tcp://any:53`；macOS 的 LAN DNS、路由排除及显式 resolver 还需另测。网卡/Mihomo 的 IPv6 状态分别核对；不凭 `dns.ipv6:false` 声称系统 IPv6 已关闭。
4. 运行 `node scripts/test_clash_proxy_dns.js` 与 `python3 scripts/test_skill.py`；对应用生成的候选 YAML 用实际 Mihomo `-t` 校验。Node 测试不证明目标机器已加载该配置，也不证明网络无旁路。
5. 有正在进行的请求时先说明重载影响并取得许可；可以让用户自行完全退出并重开 Clash。重新检查**生效配置**，不是只看扩展文件或旧截图。
6. 保留具体文件备份和恢复方法；若失败，只撤销本次 DNS 扩展并按同样授权重载，不恢复整份旧订阅、不改变节点绑定或凭证。

## 验收应拿到的证据

- TUN/路由真实生效、无第二个活动隧道冲突，活跃物理网卡 IPv6 符合已有要求。
- 分别用 UDP/TCP 对公网 DNS 地址查询无账号测试域名；返回 fake-ip 只证明该查询的接管。
- 强制一次实际普通域名解析，再核对 DoH 到 `1.1.1.1:443` / `8.8.8.8:443` 的连接链包含指定叶子，而非 DIRECT。service socket 示例中的 UID 应取当前用户，不扫描其他用户控制口。

  ```bash
  curl --unix-socket "$CCG_CONTROL_SOCKET" \
    'http://localhost/dns/query?name=example.com&type=A'
  ```

- 普通 Chrome 同页复测，受保护 Chromium 单独测试；再对真实 CLI 代表请求与插件/子进程做同轮唯一域名/时间关联。不得把 Chrome 结果直接复用为 CLI 通过。
- 如需物理接口抓包，仅采集获准测试域名/端口或流量计数，区分目标查询与节点引导，不收集真实登录 URL/对话/凭证。
- TYPE64（SVCB）与 TYPE65（HTTPS）仅辅助观察解析路径/Answer；不因空 Answer 判为安全，不因非空判为泄漏，也不自动屏蔽。
- 代理节点断开、DNS 上游不可达、应用自带 DoH、TUN 关闭和客户端退出等拒绝路径必须在获准后测试；没测就记未验证。检测页地区与节点地区不同本身不构成泄漏，递归解析器可能位于异地。

## 不是全系统断路保护

此扩展约束的是 Clash 管理的普通域名解析。它没有安装 PF/WFP 防火墙、锁住所有程序的直连或处理全部内置 DoH，退出 Clash 后系统可能恢复自身解析。**没有完成系统级出口限制与断网测试，就不能写“全电脑永久不泄漏”**。

若用户要求严格的系统级 fail-closed，另行说明全机断网、内网服务与独立 DoH 的影响，再按授权设计。DNS 修改不能借机把已放开的 shell/数据库重新封进 localhost 沙箱；[沙箱边界](maintenance.md) 与系统级 DNS 防直连不是一回事。

依据：[Mihomo DNS](https://wiki.metacubex.one/en/config/dns/)、[TUN DNS 接管](https://wiki.metacubex.one/en/config/inbound/tun/)、[Clash Verge 扩展顺序](https://www.clashverge.dev/guide/extend.html)。以安装版本和现场证据为准。
