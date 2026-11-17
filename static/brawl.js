/* Heaven Brawl: real-time arcade fighting, carried by shadeDB.
 * Your fighter runs on your own device, so it answers instantly. Your opponent's fighter is
 * drawn from the small updates they publish (see realtime.py), smoothed over the gaps.
 * The attacker's device decides when a punch connects and the defender's device decides what
 * it does to them, so nobody waits on a referee. It is friendly, not tamper-proof. */
(function () {
"use strict";
const W = 800, H = 450, GY = 372, GRAV = 1900, STEP = 1 / 60;
const ROUND_MS = 45000, RO_MS = 3000, CD_MS = 3200, FW = 26, FH = 118;
const CLS = {
  paladin:  { name: "Paladin",  hp: 130, spd: 190, jump: 620, pw: 1.0,  sp: { name: "Shield Bash",  cost: 40, start: 200, act: 160, rec: 320, dmg: 16, reach: 78,  lunge: 230, kb: 260, hs: 340 } },
  seraph:   { name: "Seraph",   hp: 100, spd: 215, jump: 650, pw: 0.95, sp: { name: "Fireball",     cost: 40, start: 220, act: 0,   rec: 300, dmg: 12, proj: 430, kb: 150, hs: 300 } },
  valkyrie: { name: "Valkyrie", hp: 110, spd: 225, jump: 670, pw: 1.05, sp: { name: "Spear Thrust", cost: 40, start: 240, act: 100, rec: 300, dmg: 15, reach: 150, kb: 220, hs: 330 } },
  cherub:   { name: "Cherub",   hp: 95,  spd: 255, jump: 700, pw: 0.9,  sp: { name: "Dash Strike",  cost: 35, start: 100, act: 180, rec: 260, dmg: 11, reach: 62,  lunge: 430, kb: 200, hs: 300 } },
};
const ATK = {
  punch: { start: 70,  act: 90,  rec: 130, dmg: 7,  reach: 62, kb: 120, hs: 230 },
  kick:  { start: 150, act: 110, rec: 220, dmg: 13, reach: 86, kb: 210, hs: 340 },
};
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const sleep = ms => new Promise(r => setTimeout(r, ms));
const median = a => { if (!a.length) return 0; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const pct = (a, p) => { if (!a.length) return 0; const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.round(p * (s.length - 1)))]; };
const r1 = v => Math.round(v * 10) / 10;
let S = null, ctx = null, cssDone = false;

/* ------------------------------------------------------------------ fighters */
class Fighter {
  constructor(slot, cls, x, face) { this.slot = slot; this.cls = cls; this.c = CLS[cls]; this.reset(x, face); }
  reset(x, face) {
    Object.assign(this, { x, y: GY, vx: 0, vy: 0, face, st: "idle", t: 0, hp: this.c.hp, en: 100, hurt: 0, atk: null, ifr: 0, stun: 0, lastBlock: -1e9 });
  }
  setSt(s) { if (this.st !== s) { this.st = s; this.t = 0; } }
  params() { return this.st === "special" ? this.c.sp : ATK[this.st]; }
  active() {  // the attack that is dangerous right now, if any
    if (!this.atk || this.atk.hit || this.st === "hit" || this.st === "ko") return null;
    const P = this.params();
    return P && !P.proj && this.t >= P.start && this.t < P.start + P.act ? P : null;
  }
  step(dt, inp, foeX, canAct, perf) {
    const ms = dt * 1000, ground = this.y >= GY;
    this.t += ms; this.en = Math.min(100, this.en + 14 * dt);
    if (this.ifr > 0) this.ifr -= ms;
    const free = this.st === "idle" || this.st === "walk" || this.st === "block";
    if (free && ground && Math.abs(foeX - this.x) > 4) this.face = foeX > this.x ? 1 : -1;
    if (this.st === "ko") this.vx *= 0.92;
    else if (this.st === "hit") { if (this.t >= this.stun) { this.setSt(ground ? "idle" : "jump"); this.ifr = 140; } else this.vx *= 0.93; }
    else if (this.st === "punch" || this.st === "kick" || this.st === "special") {
      const P = this.params();
      if (P.lunge && this.t >= P.start && this.t < P.start + P.act) this.vx = this.face * P.lunge;
      else this.vx = this.t >= P.start + P.act ? this.vx * 0.8 : 0;
      if (this.t >= P.start + P.act + P.rec) { this.setSt("idle"); this.atk = null; }
    } else if (canAct) this.control(inp, ground, perf);
    else { if (ground) { this.vx = 0; this.setSt("idle"); } inp.q.length = 0; }
    this.vy += GRAV * dt; this.x += this.vx * dt; this.y += this.vy * dt;
    if (this.y >= GY) { this.y = GY; this.vy = 0; if (this.st === "jump") this.setSt("idle"); }
    this.x = clamp(this.x, 30, W - 30);
  }
  control(inp, ground, perf) {
    if (ground && inp.block) { this.setSt("block"); this.vx = 0; this.lastBlock = perf; inp.q.length = 0; return; }
    if (this.st === "block") this.setSt("idle");
    if (ground && inp.q.length) { this.begin(inp.q.shift()); return; }
    const dir = (inp.right ? 1 : 0) - (inp.left ? 1 : 0);
    if (ground) {
      this.vx = dir * this.c.spd;
      if (inp.jump) { this.vy = -this.c.jump; this.setSt("jump"); } else this.setSt(dir ? "walk" : "idle");
    } else inp.q.length = 0;
  }
  begin(a) {
    if (a === "special") { if (this.en < this.c.sp.cost) return; this.en -= this.c.sp.cost; }
    this.setSt(a); this.atk = { hit: false, spawned: false }; this.vx = 0;
  }
  takeHit(h, perf, grace) {
    if (this.st === "ko" || this.ifr > 0) return "none";
    this.hurt++; this.atk = null;
    if ((this.st === "block" || perf - this.lastBlock < grace) && this.y >= GY) {
      this.hp = Math.max(1, this.hp - Math.max(1, Math.round(h.d * 0.2))); this.vx = h.dir * h.kb * 0.35; return "block";
    }
    this.hp = Math.max(0, this.hp - h.d);
    if (this.hp <= 0) { this.setSt("ko"); this.vx = h.dir * h.kb * 1.3; this.vy = -260; return "ko"; }
    this.setSt("hit"); this.stun = h.hs; this.vx = h.dir * h.kb; if (this.y >= GY) this.vy = -140;
    return "hit";
  }
}

class Ghost {  // the opponent as we see them: their updates, smoothed over the gaps
  constructor() { this.buf = []; this.gap = 100; this.raw = null; this.reset(); }
  reset() { this.buf.length = 0; this.raw = null; this.cur = { x: 560, y: GY, face: -1, st: "idle", t: 0, hp: 100, en: 100 }; }
  push(s) {
    const last = this.buf[this.buf.length - 1];
    if (last && s.ts <= last.ts) return;
    if (last) this.gap = this.gap * 0.8 + Math.min(500, s.ts - last.ts) * 0.2;
    this.buf.push(s); if (this.buf.length > 40) this.buf.shift(); this.raw = s;
  }
  update(tNow) {
    const b = this.buf; if (!b.length) return;
    const tr = tNow - clamp(this.gap * 1.6 + 30, 80, 450);
    let i = b.length - 1; while (i > 0 && b[i].ts > tr) i--;
    const a = b[i], n = b[i + 1];
    if (n && tr >= a.ts) {
      const k = clamp((tr - a.ts) / Math.max(1, n.ts - a.ts), 0, 1), late = k > 0.5 ? n : a;
      this.cur = { x: a.x + (n.x - a.x) * k, y: Math.min(GY, a.y + (n.y - a.y) * k), face: a.f, st: late.st, t: late.sf + (tr - late.ts), hp: late.hp, en: late.en };
    } else {
      const dt = clamp((tr - a.ts) / 1000, 0, 0.25);
      this.cur = { x: clamp(a.x + a.vx * dt, 30, W - 30), y: Math.min(GY, a.y + a.vy * dt), face: a.f, st: a.st, t: a.sf + Math.max(0, tr - a.ts), hp: a.hp, en: a.en };
    }
  }
}

const rectHit = (att, P, t) => {
  const x1 = att.x + att.face * 16, x2 = att.x + att.face * (16 + P.reach);
  return Math.max(x1, x2) > t.x - FW && Math.min(x1, x2) < t.x + FW && att.y - 28 > t.y - FH && att.y - 112 < t.y;
};
const projHit = (px, py, t) => px > t.x - FW - 14 && px < t.x + FW + 14 && py > t.y - FH - 8 && py < t.y + 8;

/* ------------------------------------------------------------------ network */
const nowS = () => (S.net ? performance.now() + S.net.off : performance.now());  // the shared (server) clock
async function syncLoop(net, sess) {
  while (S === sess && !net.stop) {
    const t0 = performance.now();
    try {
      const r = await ctx.api("/api/brawl/sync", { key: S.sess.key, token: S.sess.token, gen: S.gen, rec: buildRec() }, 4000);
      if (S !== sess) return;
      net.fails = 0; S.hud.warn = ""; onSync(r, t0, performance.now());
    } catch (e) {
      if (S !== sess) return;
      if (e.status === 404 || e.status === 403 || e.status === 409) { net.stop = true; S.hud.warn = e.message; return; }
      net.fails++; S.hud.warn = "Reconnecting…"; await sleep(Math.min(1500, 120 * net.fails));
    }
    const gap = S.R.phase === "gate" || S.R.phase === "wait" ? 90 : 40;
    await sleep(Math.max(0, gap - (performance.now() - t0)));
  }
}
function buildRec() {
  const o = S.own, R = S.R, now = nowS();
  const rec = { g: S.gen, n: ++S.net.n, ph: R.phase, rd: S.local.ready ? 1 : 0, rtt: Math.round(S.net.rtt),
    s: { x: r1(o.x), y: r1(o.y), vx: Math.round(o.vx), vy: Math.round(o.vy), f: o.face, st: o.st, sf: Math.round(o.t), hp: Math.round(o.hp), en: Math.round(o.en), ts: r1(now) },
    ev: S.evs.filter(e => now - e.at < 3000).slice(-10) };
  if (S.host) { if (R.rc) rec.rc = R.rc; if (R.re) rec.re = R.re; if (R.dn) rec.dn = R.dn; }
  return rec;
}
function onSync(r, t0, t1) {
  const net = S.net, rtt = t1 - t0;
  net.rtts.push(rtt); if (net.rtts.length > 20) net.rtts.shift(); net.rtt = median(net.rtts);
  net.dbs.push(Math.max(r.db.w, r.db.r)); if (net.dbs.length > 20) net.dbs.shift();
  net.offs.push({ rtt, off: r.t - (t0 + t1) / 2 }); if (net.offs.length > 12) net.offs.shift();
  const best = [...net.offs].sort((a, b) => a.rtt - b.rtt).slice(0, 3);  // trust the quickest answers
  net.off = best.reduce((s, x) => s + x.off, 0) / best.length;
  if (S.R.phase === "gate") S.gate.samples.push(rtt);
  if (r.opp && r.opp.g === S.gen && r.opp.n > S.oppN) {
    const doc = r.opp; S.oppN = doc.n;
    S.od = { ph: doc.ph, rd: doc.rd, rtt: doc.rtt, rc: doc.rc, re: doc.re, dn: doc.dn, at: performance.now(), s: doc.s };
    if (doc.s && doc.s.ts >= S.minTs) S.ghost.push(doc.s);
    for (const ev of doc.ev || []) onEvent(ev);
  }
}
function onEvent(ev) {
  if (S.seen.has(ev.i)) return;
  S.seen.add(ev.i);
  if (ev.r !== S.R.n || S.R.phase !== "fight") return;
  if (ev.k === "proj") S.projs.push({ id: ev.id, remote: true, x0: ev.x, y: ev.y, dir: ev.dir, spd: ev.spd, t0: ev.t, dead: false });
  else if (ev.k === "hit") {
    const res = S.own.takeHit({ d: ev.d, dir: ev.dir, kb: ev.kb, hs: ev.hs }, performance.now(), clamp(S.net.rtt / 2 + 60, 80, 220));
    hitFx(S.own, res, true);
    if (ev.p) S.projs.forEach(p => { if (p.remote && p.id === ev.p) p.dead = true; });
  }
}
const pushEv = e => { e.i = ++S.evId; e.r = S.R.n; e.at = r1(nowS()); S.evs.push(e); if (S.evs.length > 16) S.evs.shift(); };

/* ------------------------------------------------------------------ rounds */
const slotPos = (slot) => slot === "p1" ? [240, 1] : [560, -1];
function beginRound(n, at) {
  const R = S.R; R.n = n; R.start_at = at; R.phase = "cd"; R.w = null; S.projs.length = 0; S.sparks.length = 0; S.evs.length = 0;
  let [x, f] = slotPos(S.me); S.own.reset(x, f); S.own.hp = S.own.c.hp;
  if (S.foe) { [x, f] = slotPos(S.os); S.foe.reset(x, f); }
  if (S.ghost) { S.ghost.reset(); S.minTs = nowS() - 150; }
  S.banner = { text: "ROUND " + n, at: performance.now(), ms: 1100 };
  hideGate();
}
function startRound(n, at) { S.R.rc = { n, start_at: at }; beginRound(n, at); }
const foeHp = () => S.cpu ? S.foe.hp : (S.od && S.od.s ? S.od.s.hp : S.own.c.hp);
function hostRounds(now) {
  const R = S.R;
  if (R.phase === "wait" && S.local.ready && S.od && S.od.rd) startRound(1, now + CD_MS);
  else if (R.phase === "fight") {
    const mine = S.own.hp, theirs = foeHp(), timeUp = now >= R.start_at + ROUND_MS;
    if (mine <= 0 || theirs <= 0 || timeUp) {
      const w = mine <= 0 && theirs <= 0 ? "draw" : mine <= 0 ? S.os : theirs <= 0 ? S.me : mine > theirs ? S.me : theirs > mine ? S.os : "draw";
      if (w !== "draw") R.wins[w]++;
      R.phase = "ro"; R.end_at = now; R.w = w; R.re = { n: R.n, w, wins: { ...R.wins }, at: r1(now) };
      S.banner = { text: timeUp && mine > 0 && theirs > 0 ? "TIME" : "K.O.", at: performance.now(), ms: 1600 };
    }
  } else if (R.phase === "ro" && now >= R.end_at + RO_MS) {
    if (R.wins.p1 >= 2 || R.wins.p2 >= 2 || R.n >= 5) {
      const w = R.wins.p1 > R.wins.p2 ? "p1" : R.wins.p2 > R.wins.p1 ? "p2" : "draw";
      R.phase = "over"; R.dn = { w, wins: { ...R.wins } };
      S.banner = { text: w === S.me ? "YOU WIN" : w === "draw" ? "DRAW" : "YOU LOSE", at: performance.now(), ms: 99999 };
      ctx.act("/api/move", { move: { finish: { winner: w, wins: R.wins } } });
    } else startRound(R.n + 1, now + 2600);
  }
}
function guestRounds(now) {
  const o = S.od, R = S.R; if (!o) return;
  if (o.rc && o.rc.n > R.n && R.phase !== "over") beginRound(o.rc.n, o.rc.start_at);
  if (o.re && o.re.n === R.n && R.phase !== "ro" && R.phase !== "over") {
    R.phase = "ro"; R.wins = o.re.wins; R.w = o.re.w; R.end_at = now;
    S.banner = { text: S.own.hp <= 0 || foeHp() <= 0 ? "K.O." : "TIME", at: performance.now(), ms: 1600 };
  }
  if (o.dn && R.phase !== "over") {
    R.phase = "over"; R.wins = o.dn.wins;
    S.banner = { text: o.dn.w === S.me ? "YOU WIN" : o.dn.w === "draw" ? "DRAW" : "YOU LOSE", at: performance.now(), ms: 99999 };
  }
}
function aiStep(perf) {
  const ai = S.ai, f = S.foe, o = S.own; if (perf < ai.next) return;
  ai.next = perf + 110 + Math.random() * 90;
  const inp = ai.inp; inp.left = inp.right = inp.block = inp.jump = false;
  const dx = o.x - f.x, dist = Math.abs(dx), threat = o.st === "punch" || o.st === "kick" || o.st === "special";
  if (threat && dist < 130 && Math.random() < 0.45) inp.block = true;
  else if (f.c.sp.proj && dist > 260 && f.en >= f.c.sp.cost && Math.random() < 0.3) inp.q.push("special");
  else if (dist > 80) { if (dx > 0) inp.right = true; else inp.left = true; }
  else if (Math.random() < 0.6) { const r = Math.random(); inp.q.push(r < 0.5 ? "punch" : r < 0.82 ? "kick" : "special"); }
  else if (Math.random() < 0.3) { if (dx > 0) inp.left = true; else inp.right = true; }
  if (Math.random() < 0.04) inp.jump = true;
  if (inp.q.length > 2) inp.q.shift();
}

/* ------------------------------------------------------------------ combat */
const dmgOf = (att, P) => att.st === "special" ? P.dmg : Math.round(P.dmg * att.c.pw);
function spark(x, y, kind) { S.sparks.push({ x, y, at: performance.now(), kind }); }
function hitFx(f, res, mine) {
  if (res === "none") return;
  spark(f.x, f.y - 80, res);
  ctx.tone(res === "block" ? 180 : res === "ko" ? 110 : 300, res === "ko" ? 0.3 : 0.07, 0, "square", 0.07);
  if (mine) { S.shake = res === "ko" ? 12 : 6; ctx.buzz(res === "ko" ? 140 : 35); if (res === "ko" && !S.cpu) pushEv({ k: "ko" }); }
}
function deliver(att, P, tgt, perf) {
  const h = { d: dmgOf(att, P), dir: att.face, kb: P.kb, hs: P.hs };
  if (S.cpu) { const res = tgt.takeHit(h, perf, 90); hitFx(tgt, res, tgt === S.own); }
  else { pushEv({ k: "hit", ...h }); spark(tgt.x, tgt.y - 80, "hit"); ctx.tone(300, 0.06, 0, "square", 0.06); }
}
function spawnProj(f, now) {
  const sp = f.c.sp;
  if (f.st !== "special" || !sp.proj || !f.atk || f.atk.spawned || f.t < sp.start) return;
  f.atk.spawned = true;
  const p = { id: ++S.projId, owner: f, x0: f.x + f.face * 36, y: f.y - 76, dir: f.face, spd: sp.proj, dmg: sp.dmg, kb: sp.kb, hs: sp.hs, t0: now, dead: false };
  S.projs.push(p);
  if (!S.cpu && f === S.own) pushEv({ k: "proj", id: p.id, x: r1(p.x0), y: r1(p.y), dir: p.dir, spd: p.spd, t: r1(now) });
}
function combat(perf, now) {
  const own = S.own, a = own.active(), tgt = S.cpu ? S.foe : S.ghost.cur;
  if (a && rectHit(own, a, tgt)) { own.atk.hit = true; deliver(own, a, tgt, perf); }
  spawnProj(own, now);
  if (S.cpu) {
    const f = S.foe, fa = f.active();
    if (fa && rectHit(f, fa, own)) { f.atk.hit = true; deliver(f, fa, own, perf); }
    spawnProj(f, now);
  }
}
function projectiles(perf, now) {
  for (const p of S.projs) {
    p.x = p.x0 + p.dir * p.spd * (now - p.t0) / 1000;
    if (p.x < -40 || p.x > W + 40 || now - p.t0 > 2600) p.dead = true;
    if (p.dead || p.remote || S.R.phase !== "fight") continue;  // the owner's device decides what a fireball hits
    const tgt = S.cpu ? (p.owner === S.own ? S.foe : S.own) : S.ghost.cur;
    if (!projHit(p.x, p.y, tgt)) continue;
    p.dead = true;
    if (S.cpu) { const res = tgt.takeHit({ d: p.dmg, dir: p.dir, kb: p.kb, hs: p.hs }, perf, 90); hitFx(tgt, res, tgt === S.own); }
    else { pushEv({ k: "hit", d: p.dmg, dir: p.dir, kb: p.kb, hs: p.hs, p: p.id }); spark(tgt.x, tgt.y - 80, "hit"); }
  }
  S.projs = S.projs.filter(p => !p.dead);
}

/* ------------------------------------------------------------------ the loop */
function tick(dt) {
  const perf = performance.now(), now = nowS(), R = S.R;
  if (R.phase === "cd" && now >= R.start_at) { R.phase = "fight"; S.banner = { text: "FIGHT!", at: perf, ms: 900 }; }
  if (S.cpu) { if (R.phase === "fight") aiStep(perf); hostRounds(now); }
  else { S.ghost.update(now); if (S.host) hostRounds(now); else guestRounds(now); gateTick(); }
  const fight = R.phase === "fight", foe = S.cpu ? S.foe : S.ghost.cur;
  S.own.step(dt, S.inp, foe.x, fight && S.own.st !== "ko", perf);
  if (S.cpu) S.foe.step(dt, S.ai.inp, S.own.x, fight && S.foe.st !== "ko", perf);
  if (fight) combat(perf, now);
  projectiles(perf, now);
  S.sparks = S.sparks.filter(s => perf - s.at < 240);
  S.shake = Math.max(0, S.shake - 40 * dt);
}
function frame(ts) {
  if (!S) return;
  S.raf = requestAnimationFrame(frame);
  S.acc += Math.min(0.1, (ts - S.last) / 1000); S.last = ts;
  while (S.acc >= STEP) { tick(STEP); S.acc -= STEP; }
  draw();
}

/* ------------------------------------------------------------------ drawing */
function seg(g, pts) { g.beginPath(); pts.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1]))); g.stroke(); }
function drawFigure(g, o, slot, cls, perf) {
  const fill = slot === "p1" ? "#fff" : "#000", line = slot === "p1" ? "#000" : "#fff";
  const st = o.st, t = o.t, C = CLS[cls], P = st === "special" ? C.sp : ATK[st];
  const bob = st === "idle" || st === "block" ? Math.sin(perf / 230) * 2 : 0;
  let head = [0, -112 + bob], hip = [0, -54], fh = [24, -86], bh = [8, -82], ff = [16, 0], bf = [-12, 0], lean = 0;
  if (st === "walk") { const p = Math.sin(t / 95) * 18; ff = [p, -Math.max(0, Math.cos(t / 95)) * 8]; bf = [-p, -Math.max(0, -Math.cos(t / 95)) * 8]; }
  else if (st === "jump") { ff = [18, -20]; bf = [-10, -30]; fh = [24, -104]; bh = [6, -100]; }
  else if (st === "punch" || st === "kick" || st === "special") {
    const a = clamp((t - P.start) / Math.max(1, P.act), 0, 1), on = t >= P.start && t < P.start + (P.act || 1) + 40;
    if (st === "punch") { fh = on ? [Math.min(70, P.reach + 6), -88] : [4, -86]; bh = [-2, -80]; }
    else if (st === "kick") { lean = -6; ff = on ? [Math.min(92, P.reach + 6), -58] : [-4, -30]; fh = [10, -92]; bh = [-6, -84]; }
    else { fh = on || t >= P.start ? [44, -86] : [0, -84]; bh = on || t >= P.start ? [36, -80] : [-4, -80]; lean = cls === "cherub" ? 10 : 0; if (cls === "cherub") { ff = [30, 0]; bf = [-22, 0]; } }
    void a;
  } else if (st === "block") { fh = [28, -96]; bh = [26, -64]; }
  else if (st === "hit") { lean = -12; head = [-12, -108]; fh = [-6, -70]; bh = [-14, -62]; }
  const draw = (w, col) => {
    g.lineWidth = w; g.strokeStyle = col; g.lineCap = "round"; g.lineJoin = "round";
    const sh = [lean * 0.4, -92];
    seg(g, [[lean, head[1] + 12], [0, hip[1]]]);
    seg(g, [sh, [(sh[0] + bh[0]) / 2 + 2, (sh[1] + bh[1]) / 2 + 8], bh]);
    seg(g, [sh, [(sh[0] + fh[0]) / 2, (sh[1] + fh[1]) / 2 + 6], fh]);
    seg(g, [hip, [(hip[0] + bf[0]) / 2 + 3, -28], bf]);
    seg(g, [hip, [(hip[0] + ff[0]) / 2 + 3, -28 + (st === "kick" && ff[1] < -40 ? -14 : 0)], ff]);
  };
  g.save(); g.translate(o.x, o.y); g.scale(o.face, 1);
  if (st === "ko") { g.rotate(-1.45); g.translate(0, -8); }
  draw(14, line); draw(8, fill);
  g.fillStyle = fill; g.strokeStyle = line; g.lineWidth = 4; g.beginPath(); g.arc(head[0] + lean, head[1], 13, 0, 7); g.fill(); g.stroke();
  g.lineWidth = 3;  // what sets each fighter apart
  if (cls === "paladin") { g.fillStyle = fill; g.beginPath(); g.rect(bh[0] - 1, bh[1] - 14, 12, 30); g.fill(); g.stroke(); }
  else if (cls === "seraph") { g.beginPath(); g.ellipse(head[0] + lean, head[1] - 22, 14, 5, 0, 0, 7); g.stroke(); }
  else if (cls === "valkyrie") { g.beginPath(); g.moveTo(fh[0] - 30, fh[1] + 6); g.lineTo(fh[0] + 56, fh[1] - 4); g.stroke(); }
  else { g.beginPath(); g.arc(-8, -84, 14, 2.2, 4.4); g.stroke(); }
  if (st === "special" && cls === "paladin" && t >= P.start && t < P.start + P.act) { g.beginPath(); g.arc(46, -70, 30, -1.2, 1.2); g.stroke(); }
  if (st === "special" && cls === "cherub" && t >= P.start && t < P.start + P.act) { g.lineWidth = 2; [-60, -80, -100].forEach(y => seg(g, [[-30, y], [-90, y]])); }
  if (st === "special" && cls === "valkyrie" && t >= P.start && t < P.start + P.act) { g.lineWidth = 4; seg(g, [[40, -84], [P.reach + 24, -84]]); }
  g.restore();
}
function drawBar(g, x, w, frac, ink, line, align) {
  g.strokeStyle = ink; g.lineWidth = 3; g.strokeRect(x, 30, w, 16);
  g.fillStyle = ink; const f = clamp(frac, 0, 1) * (w - 6);
  g.fillRect(align > 0 ? x + 3 : x + w - 3 - f, 33, f, 10);
}
function draw() {
  const d = S.d, g = d.g, perf = performance.now(), now = nowS(), R = S.R;
  if (!S.col || perf - S.col.at > 800) {
    const cs = getComputedStyle(document.documentElement), v = n => cs.getPropertyValue(n).trim();
    S.col = { at: perf, ink: v("--ink") || "#fff", bg: v("--bg") || "#000", line: v("--line") || "#333", muted: v("--muted") || "#888" };
  }
  const { ink, bg, line, muted } = S.col, k = d.cv.width / W;
  g.setTransform(k, 0, 0, k, 0, 0); g.fillStyle = bg; g.fillRect(0, 0, W, H);
  const sh = S.shake > 0 ? [(Math.random() - 0.5) * S.shake, (Math.random() - 0.5) * S.shake] : [0, 0];
  g.save(); g.translate(sh[0], sh[1]);
  g.strokeStyle = line; g.lineWidth = 2;
  for (let i = 0; i < 5; i++) { const x = 80 + i * 160; g.strokeRect(x - 24, 130, 48, GY - 130); g.beginPath(); g.arc(x + 80, 158, 38, Math.PI, 0); g.stroke(); }
  g.fillStyle = ink; g.fillRect(0, GY, W, 4);
  g.strokeStyle = line; for (let x = -20; x < W; x += 44) { g.beginPath(); g.moveTo(x, GY + 8); g.lineTo(x - 26, H); g.stroke(); }
  for (const p of S.projs) { g.fillStyle = "#fff"; g.strokeStyle = "#000"; g.lineWidth = 4; g.beginPath(); g.arc(p.x, p.y, 12, 0, 7); g.fill(); g.stroke(); g.lineWidth = 2; seg(g, [[p.x - p.dir * 12, p.y], [p.x - p.dir * 34, p.y]]); }
  const foe = S.cpu ? S.foe : S.ghost.cur, foeCls = S.cpu ? S.foe.cls : S.foeCls;
  const mine = { x: S.own.x, y: S.own.y, face: S.own.face, st: S.own.st, t: S.own.t };
  const fo = { x: foe.x, y: foe.y, face: foe.face, st: foe.st, t: foe.t };
  drawFigure(g, fo, S.os, foeCls, perf); drawFigure(g, mine, S.me, S.own.cls, perf);
  for (const s of S.sparks) { const a = (perf - s.at) / 240; g.strokeStyle = s.kind === "block" ? muted : ink; g.lineWidth = 4 * (1 - a) + 1; for (let i = 0; i < 8; i++) { const an = i * 0.785, r1_ = 8 + a * 10, r2 = 20 + a * 26; seg(g, [[s.x + Math.cos(an) * r1_, s.y + Math.sin(an) * r1_], [s.x + Math.cos(an) * r2, s.y + Math.sin(an) * r2]]); } }
  g.restore();
  // heads-up display
  const p1 = S.me === "p1" ? S.own : (S.cpu ? S.foe : null), p2 = S.me === "p2" ? S.own : (S.cpu ? S.foe : null);
  const hp1 = p1 ? p1.hp : foe.hp, hp2 = p2 ? p2.hp : foe.hp, c1 = p1 ? p1.c.hp : CLS[S.me === "p1" ? S.own.cls : foeCls].hp, c2 = CLS[S.me === "p2" ? S.own.cls : foeCls].hp;
  drawBar(g, 16, 330, hp1 / c1, ink, line, -1); drawBar(g, W - 346, 330, hp2 / c2, ink, line, 1);
  g.fillStyle = ink; g.font = "600 15px Inter, system-ui, sans-serif"; g.textBaseline = "alphabetic";
  g.textAlign = "left"; g.fillText(S.names.p1 || "P1", 16, 24); g.textAlign = "right"; g.fillText(S.names.p2 || "P2", W - 16, 24);
  const en = (x, v, al) => { g.fillStyle = muted; g.fillRect(x, 52, 120, 5); g.fillStyle = ink; g.fillRect(al > 0 ? x : x + 120 - 120 * v / 100, 52, 120 * v / 100, 5); };
  en(16, (S.me === "p1" ? S.own : S.cpu ? S.foe : { en: foe.en }).en, 1); en(W - 136, (S.me === "p2" ? S.own : S.cpu ? S.foe : { en: foe.en }).en, -1);
  for (let i = 0; i < 2; i++) { g.strokeStyle = ink; g.lineWidth = 2; g.fillStyle = ink; g.beginPath(); g.arc(24 + i * 18, 74, 5, 0, 7); R.wins.p1 > i ? g.fill() : g.stroke(); g.beginPath(); g.arc(W - 24 - i * 18, 74, 5, 0, 7); R.wins.p2 > i ? g.fill() : g.stroke(); }
  g.textAlign = "center"; g.fillStyle = ink; g.font = "700 26px Inter, system-ui, sans-serif";
  const left = R.phase === "fight" ? clamp(Math.ceil((ROUND_MS - (now - R.start_at)) / 1000), 0, 99) : R.phase === "cd" || R.phase === "gate" || R.phase === "wait" ? 45 : 0;
  g.fillText(R.phase === "gate" || R.phase === "wait" ? "" : left, W / 2, 46);
  if (S.net) { g.font = "600 12px Inter, system-ui, sans-serif"; g.fillStyle = muted; g.fillText(S.hud.warn || `${Math.round(S.net.rtt)} ms`, W / 2, 66); }
  // banners
  let text = "", big = true;
  if (S.banner && perf - S.banner.at < S.banner.ms) text = S.banner.text;
  else if (R.phase === "cd") { const s = Math.ceil((R.start_at - now) / 1000); if (s > 0 && s <= 3) text = String(s); }
  else if (R.phase === "wait") { text = "Waiting for " + (S.names[S.os] || "opponent") + "…"; big = false; }
  if (S.od && R.phase === "fight" && perf - S.od.at > 6000) { text = "Opponent connection lost…"; big = false; }
  if (text) {
    g.font = big ? "700 72px 'Bricolage Grotesque', Inter, sans-serif" : "600 24px Inter, system-ui, sans-serif";
    g.lineWidth = 8; g.strokeStyle = bg; g.strokeText(text, W / 2, 230); g.fillStyle = ink; g.fillText(text, W / 2, 230);
  }
}

/* ------------------------------------------------------------------ connection check */
function hideGate() { if (S && S.d) S.d.gate.classList.add("hidden"); }
function showGate(html) { S.d.gate.innerHTML = `<div class="ovcard bw-card">${html}</div>`; S.d.gate.classList.remove("hidden"); }
function gateTick() {
  if (S.R.phase !== "gate" && S.R.phase !== "wait") return;
  const g = S.gate;
  if (S.R.phase === "gate" && !g.shown) {
    if (g.samples.length >= 6) { g.shown = true; g.verdict = verdict(); showVerdict(); }
    else { const n = g.samples.length; if (g.n !== n) { g.n = n; showGate(`<div class="big">📶</div><h3>Checking your connection</h3><p>Real-time fighting needs a steady link. Sending test updates (${n} of 6).</p><button class="btn ghost sm" id="bw-leave">Leave match</button>`); wireGate(); } }
  }
  const el = S.d.gate.querySelector("#bw-opp"); if (el) { const t = oppText(); if (el.textContent !== t) el.textContent = t; }
}
function oppText() {
  const n = S.names[S.os] || "Your opponent", o = S.od;
  if (!o) return n + " is still connecting.";
  const lag = o.rtt ? ` (${o.rtt} ms)` : "";
  return o.rd ? n + " is ready" + lag + "." : n + " is checking their connection" + lag + ".";
}
function verdict() {
  const net = S.net, rtts = S.gate.samples, med = median(rtts), p95 = pct(rtts, 0.95), opp = S.od && S.od.rtt ? S.od.rtt : med;
  const tick = Math.max(45, (med + opp) / 2), delay = Math.round(med / 2 + opp / 2 + tick / 2);
  const db = median(net.dbs), unstable = p95 > 2.5 * med && p95 > 150;
  let level = delay <= 110 ? "smooth" : delay <= 220 ? "some" : "laggy"; if (unstable && level === "smooth") level = "some";
  const points = [`Your round trip is about ${Math.round(med)} ms. Of that, roughly ${Math.round(Math.min(db, med))} ms is the database and ${Math.round(Math.max(0, med - db))} ms is your network and the game server.`];
  if (unstable) points.push(`Your connection is uneven: the slowest updates take ${Math.round(p95)} ms. Expect stutters.`);
  if (S.od && S.od.rtt) points.push(`${S.names[S.os] || "Your opponent"}'s round trip is about ${S.od.rtt} ms, which counts too.`);
  points.push("Arcade fighters like this feel best under about 100 ms.");
  const head = { smooth: "Smooth. About " + delay + " ms between their move and your screen.", some: "Some lag. About " + delay + " ms between their move and your screen.", laggy: "Laggy. About " + delay + " ms between their move and your screen." }[level];
  const extra = { smooth: "", some: "Blocks and counters will feel a little late, but it is playable.", laggy: "It will feel like slow motion, and hits may land after you thought you had dodged." }[level];
  return { level, head, points: extra ? [extra, ...points] : points, delay };
}
function showVerdict() {
  const v = S.gate.verdict;
  showGate(`<h3>Connection check</h3><div class="verdict ${v.level === "smooth" ? "good" : ""}"><h3>${esc(v.head)}</h3><ul>${v.points.map(p => `<li>${esc(p)}</li>`).join("")}</ul></div>
    <p class="note" id="bw-opp"></p>
    <button class="btn" id="bw-go">${v.level === "laggy" ? "Play anyway" : "Play"}</button>
    <button class="btn ghost sm" id="bw-speed">Run the full speed test</button><div id="bw-sp"></div>
    <button class="btn ghost sm" id="bw-leave">${v.level === "laggy" ? "Not now, leave match" : "Leave match"}</button>`);
  wireGate();
}
function wireGate() {
  const q = id => S.d.gate.querySelector(id);
  if (q("#bw-go")) q("#bw-go").onclick = () => {
    S.local.ready = true; S.R.phase = "wait";
    showGate(`<div class="big">⏳</div><h3>You're ready</h3><p id="bw-opp"></p><button class="btn ghost sm" id="bw-leave">Leave match</button>`); wireGate();
  };
  if (q("#bw-leave")) q("#bw-leave").onclick = () => ctx.leave();
  if (q("#bw-speed")) q("#bw-speed").onclick = () => { q("#bw-speed").disabled = true; ctx.speed(q("#bw-sp")).finally(() => { const b = q("#bw-speed"); if (b) b.disabled = false; }); };
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ------------------------------------------------------------------ interface */
const CSS = `
.bw{position:absolute;inset:0;display:flex;flex-direction:column;gap:6px;padding:2px 8px 0;user-select:none;-webkit-user-select:none;touch-action:none}
.bw .hidden{display:none!important}
.bw-msg{margin:auto;color:var(--muted);text-align:center;padding:0 24px}
.bw-pick{overflow:auto;padding:6px 0;touch-action:pan-y}
.bw-play{flex:1;min-height:0;display:flex;flex-direction:column;gap:6px}
.bw-stage{position:relative;flex:none;width:100%;aspect-ratio:16/9;max-height:100%;display:grid;place-items:center}
.bw-cv{display:block;border:1px solid var(--line);border-radius:12px;background:var(--bg)}
.bw-wide{position:absolute;right:8px;bottom:8px;height:30px;padding:0 12px;border:1px solid var(--line);border-radius:99px;background:var(--bg);color:var(--ink);font:600 12px var(--ui)}
.bw-hint{position:absolute;left:8px;bottom:12px;margin:0;font-size:12px;color:var(--muted)}
.bw-tip{flex:1;min-height:0;margin:0;display:grid;place-items:center;padding:0 28px;text-align:center;color:var(--muted);font-size:13px}
.bw.wide .bw-tip{display:none}
.bw-pad{flex:none;min-height:0;display:flex;align-items:flex-end;justify-content:space-between;gap:10px;padding:2px 2px max(12px,env(safe-area-inset-bottom))}
.bw-dpad{flex:1 1 0;max-width:210px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));grid-template-areas:". up ." "lf . rt";gap:8px}
.bw-dpad .up{grid-area:up}.bw-dpad .lf{grid-area:lf}.bw-dpad .rt{grid-area:rt}
.bw-act{flex:1 1 0;max-width:220px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.bw-pad button{min-height:68px;border:2px solid var(--ink);border-radius:20px;background:transparent;color:var(--ink);font:600 14px var(--ui);touch-action:none;-webkit-tap-highlight-color:transparent}
.bw-pad button svg{width:26px;height:26px;fill:none;stroke:currentColor;stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round}
.bw-pad button.on{background:var(--ink);color:var(--on-ink)}
.bw-gate{position:absolute;inset:0;z-index:20;display:grid;place-items:center;padding:12px;background:var(--scrim);overflow:auto}
.bw-card{max-height:100%;overflow:auto;width:min(380px,100%)}
.bw-card .btn{margin-top:10px}.bw-card .verdict{margin-top:10px;text-align:left}
.bw.wide{padding:0}
.bw.wide .bw-play{position:relative;gap:0}
.bw.wide .bw-stage{flex:1;aspect-ratio:auto;min-height:0}
.bw.wide .bw-cv{border-radius:0;border-width:0}
.bw.wide .bw-pad{position:absolute;left:10px;right:10px;bottom:0;flex:none;pointer-events:none;align-items:flex-end;padding-bottom:max(10px,env(safe-area-inset-bottom))}
.bw.wide .bw-pad button{pointer-events:auto;min-height:56px;background:rgba(128,128,128,.25)}
.bw.wide .bw-pad button.on{background:var(--ink)}
.bw.wide .bw-dpad{max-width:200px}.bw.wide .bw-act{max-width:190px}
.bw.wide .bw-wide{top:auto;right:auto;left:50%;bottom:12px;transform:translateX(-50%)}.bw.wide .bw-hint{bottom:auto;top:14px}
`;
const ARROW = { up: "M5 15l7-7 7 7", lf: "M15 5l-7 7 7 7", rt: "M9 5l7 7-7 7" };
const KEYS = { ArrowLeft: "left", a: "left", ArrowRight: "right", d: "right", ArrowUp: "jump", w: "jump", " ": "jump", ArrowDown: "block", s: "block", j: "punch", z: "punch", k: "kick", x: "kick", l: "special", c: "special" };
let keys = null;

function ensureDOM(root) {
  if (root._bw) return root._bw;
  if (!cssDone) { cssDone = true; const s = document.createElement("style"); s.textContent = CSS; document.head.append(s); }
  const arrow = c => `<button data-k="${{ up: "jump", lf: "left", rt: "right" }[c]}" class="${c}" aria-label="${{ up: "Jump", lf: "Left", rt: "Right" }[c]}"><svg viewBox="0 0 24 24"><path d="${ARROW[c]}"/></svg></button>`;
  root.innerHTML = `<div class="bw"><div class="bw-msg hidden"></div><div class="bw-pick hidden"></div>
    <div class="bw-play hidden"><div class="bw-stage"><canvas class="bw-cv"></canvas><button class="bw-wide" type="button">Wide</button><p class="bw-hint hidden">Rotate your phone for the full wide view</p></div>
    <p class="bw-tip">Tip: tap Wide, then turn your phone sideways, for a much bigger arena.</p>
    <div class="bw-pad"><div class="bw-dpad">${arrow("up")}${arrow("lf")}${arrow("rt")}</div>
    <div class="bw-act"><button data-k="punch">Punch</button><button data-k="kick">Kick</button><button data-k="special">Special</button><button data-k="block">Block</button></div></div></div>
    <div class="bw-gate hidden"></div></div>`;
  const q = s => root.querySelector(s);
  const d = { bw: q(".bw"), msg: q(".bw-msg"), pick: q(".bw-pick"), play: q(".bw-play"), stage: q(".bw-stage"), cv: q(".bw-cv"), pad: q(".bw-pad"), gate: q(".bw-gate"), wide: q(".bw-wide"), hint: q(".bw-hint") };
  d.g = d.cv.getContext("2d");
  d.pick.onclick = e => { const b = e.target.closest("[data-pick]"); if (b && !b.disabled) ctx.act("/api/move", { move: { pick: b.dataset.pick } }); };
  d.wide.onclick = () => setWide(!isWide());
  const hold = (e, down) => { const b = e.target.closest && e.target.closest("[data-k]"); if (!b) return; if (down) { e.preventDefault(); try { b.setPointerCapture(e.pointerId); } catch (_) {} } press(b.dataset.k, down); b.classList.toggle("on", down); };
  d.pad.addEventListener("pointerdown", e => hold(e, true));
  for (const t of ["pointerup", "pointercancel", "lostpointercapture"]) d.pad.addEventListener(t, e => hold(e, false));
  d.pad.addEventListener("contextmenu", e => e.preventDefault());
  new ResizeObserver(fit).observe(d.stage); addEventListener("resize", fit);
  root._bw = d;
  return d;
}
function press(k, down) {
  if (!S) return;
  if (k === "punch" || k === "kick" || k === "special") { if (down) { S.inp.q.push(k); if (S.inp.q.length > 2) S.inp.q.shift(); } }
  else S.inp[k] = down;
}
function release() { if (!S) return; Object.assign(S.inp, { left: false, right: false, jump: false, block: false }); S.inp.q.length = 0; S.d.pad.querySelectorAll(".on").forEach(b => b.classList.remove("on")); }
function bindInput() {
  const typing = t => t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
  const key = e => KEYS[e.key.length === 1 ? e.key.toLowerCase() : e.key];
  const mark = (k, on) => { const b = S && S.d.pad.querySelector(`[data-k="${k}"]`); if (b) b.classList.toggle("on", on); };
  keys = {
    kd: e => { const k = key(e); if (!S || !k || typing(e.target)) return; e.preventDefault(); if (e.repeat) return; press(k, true); mark(k, true); },
    ku: e => { const k = key(e); if (!S || !k || typing(e.target)) return; press(k, false); mark(k, false); },
    blur: release,
  };
  addEventListener("keydown", keys.kd); addEventListener("keyup", keys.ku); addEventListener("blur", keys.blur);
  document.addEventListener("visibilitychange", keys.blur);
}
function unbindInput() {
  if (!keys) return;
  removeEventListener("keydown", keys.kd); removeEventListener("keyup", keys.ku); removeEventListener("blur", keys.blur);
  document.removeEventListener("visibilitychange", keys.blur); keys = null;
}
function fit() {
  const d = ctx && ctx.root && ctx.root._bw; if (!d) return;
  const r = d.stage.getBoundingClientRect(); if (r.width < 10 || r.height < 10) return;
  const s = Math.min(r.width / 16, r.height / 9), cw = Math.floor(16 * s), ch = Math.floor(9 * s), dpr = Math.min(2, window.devicePixelRatio || 1);
  d.cv.style.width = cw + "px"; d.cv.style.height = ch + "px";
  const pw = Math.round(cw * dpr); if (d.cv.width !== pw) { d.cv.width = pw; d.cv.height = Math.round(ch * dpr); }
  d.hint.classList.toggle("hidden", !(d.bw.classList.contains("wide") && innerHeight > innerWidth));
}
const isWide = () => !!(ctx && ctx.root._bw && ctx.root._bw.bw.classList.contains("wide"));
function wantWide() { const p = localStorage.getItem("hd-wide"); return p === "1" ? true : p === "0" ? false : (matchMedia("(orientation: landscape)").matches && innerHeight < 620); }
function setWide(on, silent) {
  const d = ctx.root._bw; d.bw.classList.toggle("wide", on); d.wide.textContent = on ? "Compact" : "Wide"; if (ctx.onWide) ctx.onWide(on);
  if (!silent) localStorage.setItem("hd-wide", on ? "1" : "0");
  try { if (on && document.fullscreenElement && screen.orientation && screen.orientation.lock) screen.orientation.lock("landscape").catch(() => {}); else if (!on && screen.orientation && screen.orientation.unlock) screen.orientation.unlock(); } catch (e) {}
  requestAnimationFrame(fit);
}
function show(d, which) { for (const k of ["msg", "pick", "play"]) d[k].classList.toggle("hidden", k !== which); if (which !== "play") d.gate.classList.add("hidden"); }
function renderPick(d, v) {
  show(d, "pick");
  const st = v.state, other = v.names[v.you === "p1" ? "p2" : "p1"] || "your opponent";
  const cards = Object.entries(ctx.meta.classes).map(([k, c]) => `<button class="cls" data-pick="${k}" aria-pressed="${st.my_pick === k}"${st.my_pick ? " disabled" : ""}><span class="fav" data-ico="${k}"></span><b>${esc(c.title)}</b><small>${CLS[k].hp} HP · ${esc(c.special)}</small><small>${esc(c.blurb)}</small></button>`).join("");
  d.pick.innerHTML = `<div class="pick"><h3>Choose your fighter</h3><p class="sub">${st.my_pick ? `Locked in. Waiting for ${esc(other)}…` : "Real-time arcade fighting. Your opponent can't see your pick until you both lock in."}</p><div class="classes">${cards}</div></div>`;
  ctx.icons(d.pick);
}
function startEngine(v, d) {
  const st = v.state, me = v.you, os = me === "p1" ? "p2" : "p1", cpu = !!v.vs_bot, [x, f] = slotPos(me);
  S = {
    d, gen: st.gen, me, os, host: me === "p1", cpu, names: v.names, sess: ctx.sess(), foeCls: st.opp,
    own: new Fighter(me, st.me, x, f), foe: null, ghost: null, od: null, oppN: 0, minTs: 0,
    inp: { left: false, right: false, jump: false, block: false, q: [] },
    R: { phase: cpu ? "cd" : "gate", n: 0, start_at: 0, end_at: 0, wins: { p1: 0, p2: 0 }, w: null, rc: null, re: null, dn: null },
    local: { ready: false }, gate: { samples: [], shown: false, verdict: null, n: -1 }, evs: [], evId: 0, seen: new Set(),
    projs: [], projId: 0, sparks: [], shake: 0, banner: null, last: performance.now(), acc: 0, net: null, raf: 0, hud: {}, ai: null, col: null,
  };
  if (cpu) { const [fx, ff] = slotPos(os); S.foe = new Fighter(os, st.opp, fx, ff); S.ai = { inp: { left: false, right: false, jump: false, block: false, q: [] }, next: 0 }; }
  else { S.ghost = new Ghost(); S.net = { off: 0, offs: [], n: 0, rtt: 0, rtts: [], dbs: [], fails: 0, stop: false }; }
  bindInput(); setWide(wantWide(), true); fit();
  if (cpu) startRound(1, performance.now() + 2400); else syncLoop(S.net, S);
  S.raf = requestAnimationFrame(frame);
}
function stopEngine() {
  if (!S) return;
  cancelAnimationFrame(S.raf); if (S.net) S.net.stop = true; unbindInput(); if (ctx && ctx.onWide) ctx.onWide(false);
  try { if (screen.orientation && screen.orientation.unlock) screen.orientation.unlock(); } catch (e) {}
  if (S.d) S.d.gate.classList.add("hidden");
  S = null;
}
window.Brawl = {
  update(v, c) {
    ctx = c; const d = ensureDOM(c.root), st = v.state;
    if (v.status === "waiting") { stopEngine(); d.msg.textContent = "Waiting for an opponent to join."; show(d, "msg"); return; }
    if (st.phase === "pick") { stopEngine(); renderPick(d, v); return; }
    if (v.status === "done") { stopEngine(); d.msg.textContent = "Match over."; show(d, "msg"); return; }
    show(d, "play");
    if (!S || S.gen !== st.gen || S.d !== d) { stopEngine(); startEngine(v, d); } else S.names = v.names;
  },
  stop: stopEngine,
  toggleWide() { if (ctx && ctx.root._bw) setWide(!isWide()); },
  isWide,
  debug: () => S,
};
})();
