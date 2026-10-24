/* 图表库：手写 SVG，无第三方依赖，配色与主题变量一致 */

export const C = {
  brand: "#12876F", brand2: "#0E5C4F", soft: "#E7F4F0",
  ink: "#101828", ink2: "#475467", ink3: "#8B94A3",
  line: "#E4E7EC", red: "#D92D20", green: "#039855",
  amber: "#DC6803", blue: "#175CD3", purple: "#6941C6",
};

const nf = (v, d = 0) =>
  (v === null || v === undefined || isNaN(v)) ? "—"
    : Number(v).toLocaleString("zh-CN", { minimumFractionDigits: d, maximumFractionDigits: d });

export function wan(v, d = 0) { return nf(Number(v) / 1e4, d); }
export function yi(v, d = 2) { return nf(Number(v) / 1e8, d); }

export function sparkline(vals, { w = 84, h = 24, color = C.brand } = {}) {
  if (!vals || vals.length < 2) return "";
  const min = Math.min(...vals), max = Math.max(...vals), r = (max - min) || 1;
  const pts = vals.map((v, i) => [i / (vals.length - 1) * w, h - 2 - (v - min) / r * (h - 5)]);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const area = d + ` L ${w} ${h} L 0 ${h} Z`;
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
    <path d="${area}" fill="${color}" opacity=".07"/>
    <path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round"/>
    <circle cx="${pts[pts.length - 1][0].toFixed(1)}" cy="${pts[pts.length - 1][1].toFixed(1)}" r="2" fill="${color}"/>
  </svg>`;
}

/* 收入柱 + 毛利率线，双轴 */
export function trendChart(rows, { w = 780, h = 250, unit = "万元" } = {}) {
  if (!rows.length) return `<div class="blank">暂无数据</div>`;
  const pl = 52, pr = 46, pt = 16, pb = 26;
  const iw = w - pl - pr, ih = h - pt - pb;
  const revs = rows.map(r => Number(r["营业收入合计"] || 0));
  const max = Math.max(...revs) * 1.12 || 1;
  const gms = rows.map(r => Number(r["毛利率%"] || 0));
  const gmin = Math.min(...gms) - 2, gmax = Math.max(...gms) + 2;
  const y = v => pt + ih - v / max * ih;
  const gy = v => pt + ih - (v - gmin) / ((gmax - gmin) || 1) * ih;
  const step = iw / rows.length, bw = Math.max(3, step * 0.55);
  let grid = "", bars = "", line = "", labels = "";
  for (let i = 0; i <= 4; i++) {
    const val = max / 4 * i, yy = y(val);
    grid += `<line class="gridline" x1="${pl}" x2="${w - pr}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}"/>`;
    grid += `<text class="axis-l" x="${pl - 7}" y="${(yy + 3.4).toFixed(1)}" text-anchor="end">${wan(val)}</text>`;
  }
  const pts = [];
  rows.forEach((r, i) => {
    const x = pl + step * i + (step - bw) / 2;
    const val = Number(r["营业收入合计"] || 0);
    const yy = y(val), hh = pt + ih - yy;
    bars += `<rect x="${x.toFixed(1)}" y="${yy.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(hh, 0).toFixed(1)}"
      rx="1.5" fill="${i === rows.length - 1 ? C.brand : "#BFE3D8"}"/>`;
    pts.push([pl + step * i + step / 2, gy(Number(r["毛利率%"] || 0))]);
    if (i % Math.ceil(rows.length / 8) === 0 || i === rows.length - 1) {
      labels += `<text class="axis-l" x="${(pl + step * i + step / 2).toFixed(1)}" y="${h - 8}" text-anchor="middle">${String(r["月份"]).slice(2)}</text>`;
    }
  });
  line = `<polyline points="${pts.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ")}"
    fill="none" stroke="${C.amber}" stroke-width="1.8" stroke-linejoin="round"/>`;
  const label = `<text class="axis-l" x="${pl}" y="10" fill="${C.ink3}">收入（${unit}）左轴 · 毛利率（%）右轴</text>`;
  return `<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:auto" role="img" aria-label="收入与毛利率趋势">
    ${label}${grid}${bars}${line}${labels}</svg>`;
}

/* 瀑布图：items = [{name, value, kind: in|out|subtotal|total}] */
export function waterfall(items, { w = 780, h = 260 } = {}) {
  if (!items.length) return `<div class="blank">暂无数据</div>`;
  const pl = 56, pr = 16, pt = 18, pb = 42;
  const iw = w - pl - pr, ih = h - pt - pb;
  let cum = 0;
  const tops = items.map(it => {
    if (it.kind === "subtotal" || it.kind === "total") { cum = it.value; return { from: 0, to: it.value }; }
    cum += it.value;
    return { from: cum - it.value, to: cum };
  });
  const hi = Math.max(...tops.map(t => Math.max(Math.abs(t.from), Math.abs(t.to)))) * 1.1 || 1;
  const y = v => pt + ih - v / hi * ih;
  const step = iw / items.length, bw = Math.min(74, step * 0.56);
  let out = "";
  items.forEach((it, i) => {
    const t = tops[i];
    const x = pl + step * i + (step - bw) / 2;
    const y1 = y(Math.max(t.from, t.to)), y2 = y(Math.min(t.from, t.to));
    const color = it.kind === "out" ? C.red : it.kind === "total" ? C.brand2
      : it.kind === "subtotal" ? C.brand : "#7CC9B5";
    out += `<rect x="${x.toFixed(1)}" y="${y1.toFixed(1)}" width="${bw.toFixed(1)}"
      height="${Math.max(2, y2 - y1).toFixed(1)}" rx="2" fill="${color}" opacity="${it.kind === "out" ? .85 : 1}"/>`;
    out += `<text x="${(x + bw / 2).toFixed(1)}" y="${(y1 - 6).toFixed(1)}" text-anchor="middle"
      font-size="10.5" fill="${C.ink2}">${wan(it.value)}</text>`;
    out += `<text class="axis-l" x="${(x + bw / 2).toFixed(1)}" y="${h - 24}" text-anchor="middle">${it.name}</text>`;
    if (i < items.length - 1) {
      out += `<line x1="${(x + bw).toFixed(1)}" x2="${(x + step).toFixed(1)}" y1="${y2.toFixed(1)}" y2="${y2.toFixed(1)}"
        stroke="${C.line}" stroke-dasharray="2 2"/>`;
    }
  });
  return `<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:auto" role="img" aria-label="收入到利润的桥">${out}</svg>`;
}

export function donut(items, { size = 176, thick = 26, center = "", centerSub = "合计（万元）" } = {}) {
  const total = items.reduce((s, i) => s + Math.abs(i.value), 0) || 1;
  const r = (size - thick) / 2, cx = size / 2, cy = size / 2;
  const palette = [C.brand, "#4FBFA0", C.blue, C.purple, C.amber, "#98A2B3", "#7CC9B5"];
  let a = -Math.PI / 2, arcs = "";
  items.forEach((it, idx) => {
    const ang = Math.abs(it.value) / total * Math.PI * 2;
    const a2 = a + ang;
    const large = ang > Math.PI ? 1 : 0;
    const x1 = cx + r * Math.cos(a), y1 = cy + r * Math.sin(a);
    const x2 = cx + r * Math.cos(a2), y2 = cy + r * Math.sin(a2);
    arcs += `<path d="M ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}"
      fill="none" stroke="${it.color || palette[idx % palette.length]}" stroke-width="${thick}" stroke-linecap="butt"/>`;
    a = a2;
  });
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img">
    ${arcs}
    <text x="${cx}" y="${cy - 2}" text-anchor="middle" font-size="15" font-weight="600" fill="${C.ink}">${center}</text>
    <text x="${cx}" y="${cy + 15}" text-anchor="middle" font-size="10.5" fill="${C.ink3}">${centerSub}</text>
  </svg>`;
}

export function hbars(items, { max = null, fmt = wan } = {}) {
  const mx = max || Math.max(...items.map(i => Math.abs(i.value))) || 1;
  return items.map(i => `<div class="bar-row">
    <div class="bl" title="${i.name}">${i.name}</div>
    <div class="hbar"><i style="width:${(Math.abs(i.value) / mx * 100).toFixed(1)}%;background:${i.color || C.brand}"></i></div>
    <div class="bv num">${fmt(i.value)}</div>
  </div>`).join("");
}

/* 账龄堆叠条 */
export function agingBar(buckets, { h = 26 } = {}) {
  const total = buckets.reduce((s, b) => s + Number(b.balance || 0), 0) || 1;
  const colors = { "未到期": "#9BD9C7", "0-30 天": "#F5C26B", "31-60 天": "#E9963F", "61-90 天": "#E4663C", "90+ 天": C.red };
  const seg = buckets.map(b => {
    const p = Number(b.balance || 0) / total * 100;
    return p < 0.2 ? "" : `<div title="${b.bucket} ${wan(b.balance)} 万 ${p.toFixed(1)}%"
      style="width:${p}%;background:${colors[b.bucket] || C.ink3};height:${h}px"></div>`;
  }).join("");
  return `<div style="display:flex;border-radius:6px;overflow:hidden;height:${h}px">${seg}</div>`;
}
