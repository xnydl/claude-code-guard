// Optional Clash Verge subscription extension. Read references/dns.md first.
// Reuse the EXISTING single-leaf protected listener; do not select a new node.
// No runtime/file/network APIs: this function only transforms the config object.
function main(config, profileName) {
  const listeners = (config.listeners || []).filter(function (item) {
    return item.name === "claude-guard-upstream";
  });
  const leaf = listeners.length === 1 && listeners[0].proxy;
  const nodes = (config.proxies || []).filter(function (item) {
    return item.name === leaf;
  });
  if (typeof leaf !== "string" || !leaf.trim() || /[#&\r\n]/.test(leaf) ||
      /^(DIRECT|REJECT|PASS)$/i.test(leaf) || nodes.length !== 1 ||
      typeof nodes[0].type !== "string" ||
      /^(direct|reject|pass|dns)$/i.test(nodes[0].type)) {
    throw new Error("DNS protection: a unique concrete pinned leaf is required; no direct DNS fallback.");
  }

  // Literal IP endpoints need no separate resolver-hostname lookup. #leaf
  // pins the HTTPS connection even when ordinary traffic rules say DIRECT.
  const remoteDns = [
    "https://1.1.1.1/dns-query#" + leaf,
    "https://8.8.8.8/dns-query#" + leaf
  ];

  // Explicit bootstrap exception: ONLY resolve the proxy server's address
  // before the proxy is established. Do not use this list for destinations.
  // Keep TLS verification on; no system/plaintext :53 fallback.
  const bootstrapDns = [
    "https://223.5.5.5/dns-query#DIRECT",
    "https://1.12.12.12/dns-query#DIRECT"
  ];

  config.dns = Object.assign({}, config.dns || {}, {
    enable: true,
    ipv6: false,
    "enhanced-mode": "fake-ip",
    "respect-rules": true,
    "prefer-h3": false,
    "default-nameserver": bootstrapDns.slice(),
    "proxy-server-nameserver": bootstrapDns.slice(),
    "proxy-server-nameserver-policy": {},
    nameserver: remoteDns.slice(),
    "direct-nameserver": remoteDns.slice(),
    "direct-nameserver-follow-policy": true,
    "nameserver-policy": {},
    fallback: [],
    "fallback-filter": {}
  });
  return config;
}
