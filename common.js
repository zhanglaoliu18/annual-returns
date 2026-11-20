/* 年度收益站公共工具：三页（index / my-account / girlfriend-settlement）共用。
   改动会同时影响三个页面，谨慎。fmt/signed 等格式化函数因 gf 结算页语义
   不同（¥ 前缀）留在各页面内，不在此定义。 */

const CDN = 'https://cdn.jsdelivr.net/gh/zhanglaoliu18/annual-returns@main/';
const RED = '#DC2626', GREEN = '#16A34A', GRAY = '#9CA3AF';
const up = v => v > 0 ? RED : v < 0 ? GREEN : GRAY;

/* 日期：按 UTC 零点对齐，避免时区差一天；slice 兼容带时间的入参 */
const parseD = s => new Date(String(s).slice(0, 10) + 'T00:00:00Z');
const dayDiff = (a, b) => Math.round((parseD(b) - parseD(a)) / 86400000);
const d2s = d => d.toISOString().slice(0, 10);

/* 数据取数：源站优先（新鲜）、CDN 备用（国内可达）；tries 次 600ms 退避重试；
   失败返回 null 不抛异常。
   opts.cdnFirst: CDN 优先（近不变的文件如 shots.json 走 CDN 更稳）
   window.__noCache（调试开关）: 加时间戳参数并 reload，绕过一切缓存 */
async function fetchJSON(url, tries = 0, opts = {}) {
  const nc = opts.noCache || window.__noCache;
  const sep = url.includes('?') ? '&' : '?';
  const b = nc ? sep + 't=' + Date.now() : '';
  const order = opts.cdnFirst ? [CDN + url + b, url + b] : [url + b, CDN + url + b];
  for (const u of order) {
    try {
      const r = await fetch(u, {cache: nc ? 'reload' : 'no-cache'});
      if (r.ok) return await r.json();
    } catch (e) {}
  }
  if (tries > 0) { await new Promise(res => setTimeout(res, 600)); return fetchJSON(url, tries - 1, opts); }
  return null;
}
