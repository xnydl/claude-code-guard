// Offline fixtures only. Does not load local profiles, accounts or controllers.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, "clash-proxy-dns.js"), "utf8"), context);
const copy = value => JSON.parse(JSON.stringify(value));
const apply = config => copy(context.main(config, "fixture"));
const leaf = "Fixture Taiwan | 01";

function fixture() {
  return {
    mode: "rule", ipv6: false,
    tun: {enable: true, "dns-hijack": ["any:53"], "strict-route": false},
    listeners: [{name: "claude-guard-upstream", type: "mixed", port: 6128,
      listen: "127.0.0.1", udp: false, proxy: leaf}],
    proxies: [{name: leaf, type: "http", server: "192.0.2.10", port: 443,
      "dialer-proxy": "fixture-entry"},
      {name: "fixture-entry", type: "http", server: "192.0.2.11", port: 443}],
    "proxy-groups": [{name: "ordinary", type: "select", proxies: [leaf, "DIRECT"]}],
    rules: ["DOMAIN-SUFFIX,example.test,DIRECT", "MATCH,ordinary"],
    dns: {enable: false, ipv6: true, listen: "127.0.0.1:1053", "use-hosts": true,
      "fake-ip-range": "198.18.0.1/16", "fake-ip-filter": ["*.lan"],
      nameserver: ["114.114.114.114"], "direct-nameserver": ["system"],
      fallback: ["8.8.4.4"], "nameserver-policy": {"geosite:cn": "system"},
      "proxy-server-nameserver-policy": {"+.example.test": "system"}}
  };
}

test("only DNS changes; node, chain, rules, ports and TUN are preserved", () => {
  const before = fixture(), after = apply(copy(before));
  const withoutDns = value => {const result = copy(value); delete result.dns; return result;};
  assert.deepEqual(withoutDns(after), withoutDns(before));
  assert.equal(after.dns.listen, before.dns.listen);
  assert.equal(after.dns["use-hosts"], true);
  assert.deepEqual(after.dns["fake-ip-filter"], before.dns["fake-ip-filter"]);
  assert.equal(after.dns["fake-ip-range"], before.dns["fake-ip-range"]);
});

test("destination and direct-traffic DNS use only proxy-pinned HTTPS", () => {
  const dns = apply(fixture()).dns;
  assert.deepEqual(dns.nameserver, ["https://1.1.1.1/dns-query#" + leaf,
    "https://8.8.8.8/dns-query#" + leaf]);
  assert.deepEqual(dns["direct-nameserver"], dns.nameserver);
  assert.deepEqual(dns.fallback, []);
  assert.deepEqual(dns["nameserver-policy"], {});
  assert.deepEqual(dns["proxy-server-nameserver-policy"], {});
  assert.equal(dns.ipv6, false);
  assert.equal(dns["enhanced-mode"], "fake-ip");
  assert.equal(dns["respect-rules"], true);
});

test("encrypted bootstrap exception is distinct and cannot alias destinations", () => {
  const dns = apply(fixture()).dns;
  const expected = ["https://223.5.5.5/dns-query#DIRECT", "https://1.12.12.12/dns-query#DIRECT"];
  assert.deepEqual(dns["default-nameserver"], expected);
  assert.deepEqual(dns["proxy-server-nameserver"], expected);
  dns.nameserver.push("fixture-change");
  assert.deepEqual(dns["direct-nameserver"], ["https://1.1.1.1/dns-query#" + leaf,
    "https://8.8.8.8/dns-query#" + leaf]);
  assert.deepEqual(dns["proxy-server-nameserver"], expected);
});

test("reapplying the override is idempotent", () => {
  const once = apply(fixture());
  assert.deepEqual(apply(copy(once)), once);
});

test("missing, duplicate, group and builtin bindings fail before mutation", () => {
  const cases = [
    c => {c.listeners = [];},
    c => {c.listeners.push(copy(c.listeners[0]));},
    c => {c.proxies = [];},
    c => {c.proxies.push(copy(c.proxies[0]));},
    c => {c.listeners[0].proxy = "ordinary";},
    ...["DIRECT", "REJECT", "PASS"].map(name => c => {c.listeners[0].proxy = name;})
  ];
  for (const change of cases) {
    const config = fixture(); change(config);
    const before = copy(config);
    assert.throws(() => apply(config), /unique concrete pinned leaf/);
    assert.deepEqual(config, before);
  }
});

test("DNS parameter injection and special proxy types are rejected", () => {
  for (const name of ["bad#DIRECT", "bad&skip-cert-verify=true", "bad\nname", " "]) {
    const config = fixture(); config.listeners[0].proxy = name; config.proxies[0].name = name;
    assert.throws(() => apply(config), /unique concrete pinned leaf/);
  }
  for (const type of ["direct", "reject", "pass", "dns"]) {
    const config = fixture(); config.proxies[0].type = type;
    assert.throws(() => apply(config), /unique concrete pinned leaf/);
  }
});

test("DNS can be added without changing non-DNS fields or blocking record types", () => {
  const config = fixture(); delete config.dns;
  const result = apply(config);
  assert.equal(result.dns.enable, true);
  assert.ok(result.dns.nameserver.every(item => !item.includes("disable-qtype")));
});
