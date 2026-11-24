// The adventure map: an original isometric island drawn in SVG for Scrubble.
// Four places sit on rising terraces, joined by stepping stones. What is open, how many stones are lit and
// where Bubbles stands all come from the backend (rewarded washes); nothing here is tappable progress.
import { useId } from "react";
import type { Adventure, Stage } from "../api";
import gunky from "../assets/gunky.png";
import prickle from "../assets/prickle.png";
import bubbles from "../assets/scrubby.png";
import sneezel from "../assets/sneezel.png";
import "./WorldMap.css";

const TW = 34, TH = 17, ZH = 26, OX = 195, OY = 196;
type P3 = readonly [x: number, y: number, z: number];
const pt = ([x, y, z]: P3): [number, number] => [OX + (x - y) * TW / 2, OY + (x + y) * TH / 2 - z * ZH];
const poly = (ps: P3[]) => ps.map((p) => pt(p).map((n) => n.toFixed(1)).join(",")).join(" ");

/** A box on the grid: lit top, a left face and a darker right face. */
function Block({ x, y, w, d, top, base = -0.9, fill, left, right, rim }: {
  x: number; y: number; w: number; d: number; top: number; base?: number; fill: string; left: string; right: string; rim?: string;
}) {
  return (
    <g>
      <polygon points={poly([[x, y + d, top], [x + w, y + d, top], [x + w, y + d, base], [x, y + d, base]])} fill={left} />
      <polygon points={poly([[x + w, y, top], [x + w, y + d, top], [x + w, y + d, base], [x + w, y, base]])} fill={right} />
      <polygon points={poly([[x, y, top], [x + w, y, top], [x + w, y + d, top], [x, y + d, top]])} fill={fill} stroke={rim} strokeWidth={rim ? 1.6 : 0} strokeLinejoin="round" />
    </g>
  );
}

function Tower({ x, y, z, h = 2.2, roof = "#8a5fd6" }: { x: number; y: number; z: number; h?: number; roof?: string }) {
  const [cx, cy] = pt([x + 0.6, y + 0.6, z + h]);
  return (
    <g>
      <Block x={x} y={y} w={1.2} d={1.2} top={z + h} base={z} fill="#cfc4ee" left="#8f82c9" right="#6f62ad" />
      <path d={`M${cx - 26} ${cy + 4}L${cx} ${cy - 44}L${cx + 26} ${cy + 4}Q${cx} ${cy + 18} ${cx - 26} ${cy + 4}z`} fill={roof} />
      <path d={`M${cx - 26} ${cy + 4}L${cx} ${cy - 44}L${cx - 4} ${cy + 13}Q${cx - 16} ${cy + 11} ${cx - 26} ${cy + 4}z`} fill="#fff" opacity="0.18" />
      <rect x={cx - 4} y={cy + 20} width="8" height="13" rx="4" fill="#3a2f78" />
    </g>
  );
}

function Frond({ at, s = 1, hue = "#57c98a", flip = false }: { at: P3; s?: number; hue?: string; flip?: boolean }) {
  const [x, y] = pt(at);
  return (
    <g transform={`translate(${x} ${y}) scale(${flip ? -s : s} ${s})`}>
      <path d="M0 0C-4-18-16-30-30-36-22-20-18-8 0 0z" fill={hue} /><path d="M0 0C2-22 12-38 26-46 22-26 16-10 0 0z" fill={hue} opacity="0.85" />
      <path d="M0 0C-2-16 0-34 6-50 10-32 8-14 0 0z" fill="#9be8a6" />
    </g>
  );
}

function Shroom({ at, cap = "#f58fa0" }: { at: P3; cap?: string }) {
  const [x, y] = pt(at);
  return (
    <g>
      <rect x={x - 3} y={y - 12} width="6" height="13" rx="3" fill="#f3e9d8" />
      <path d={`M${x - 11} ${y - 10}a11 10 0 0 1 22 0z`} fill={cap} /><circle cx={x - 4} cy={y - 15} r="1.8" fill="#fff" opacity="0.8" /><circle cx={x + 4} cy={y - 13} r="1.3" fill="#fff" opacity="0.8" />
    </g>
  );
}

function Critter({ at, art, size, dy = 0 }: { at: P3; art: string; size: number; dy?: number }) {
  const [x, y] = pt(at);
  return (
    <g>
      <ellipse cx={x} cy={y + 2} rx={size * 0.34} ry={size * 0.11} fill="#0b0a2c" opacity="0.35" />
      <image href={art} x={x - size / 2} y={y - size * 0.9 + dy} width={size} height={size} preserveAspectRatio="xMidYMax meet" />
    </g>
  );
}

// where each place's medal stands, and the grid height of its terrace
const SPOTS: Record<Stage["id"], P3> = {
  bubble_bay: [7.6, 8, 0.12], germ_jungle: [2.6, 7, 1.3], soap_canyon: [7.8, 2.6, 2.4], bacteria_castle: [3.3, 3.1, 3.5],
};
const ORDER: Stage["id"][] = ["bubble_bay", "germ_jungle", "soap_canyon", "bacteria_castle"];

function lerp(a: P3, b: P3, t: number): P3 {
  // stones rise in a gentle arc so they read as steps between terraces
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t + Math.sin(t * Math.PI) * 0.25];
}

function Stone({ at, lit }: { at: P3; lit: boolean }) {
  const [x, y] = pt(at);
  return (
    <g className={lit ? "stone lit" : "stone"}>
      <ellipse cx={x} cy={y + 9} rx="9" ry="4.5" fill="#0b0a2c" opacity="0.3" />
      <ellipse cx={x} cy={y + 3.5} rx="9.5" ry="5" className="side" /><ellipse cx={x} cy={y} rx="9.5" ry="5" className="top" />
    </g>
  );
}

function Medal({ at, n, stage, current }: { at: P3; n: number; stage: Stage; current: boolean }) {
  const [x, y] = pt(at);
  return (
    <g className={`medal ${stage.unlocked ? "open" : "shut"} ${current ? "current" : ""}`}>
      {current && <ellipse cx={x} cy={y} rx="30" ry="15" className="halo" />}
      <ellipse cx={x} cy={y + 6} rx="19" ry="9.5" className="side" /><ellipse cx={x} cy={y} rx="19" ry="9.5" className="top" />
      <ellipse cx={x} cy={y - 0.5} rx="13.5" ry="6.4" className="face" />
      {stage.unlocked
        ? <text x={x} y={y + 4.2} textAnchor="middle">{n}</text>
        : <g transform={`translate(${x - 6} ${y - 9})`}><rect x="1" y="6" width="10" height="8" rx="2" className="lock" /><path d="M3.2 6V4.2a2.8 2.8 0 0 1 5.6 0V6" className="shackle" /></g>}
    </g>
  );
}

export function WorldMap({ data }: { data: Adventure }) {
  const id = useId();
  const stage = (k: Stage["id"]) => data.stages.find((s) => s.id === k)!;
  const here = [...data.stages].reverse().find((s) => s.unlocked)?.id ?? "bubble_bay";
  const shut = (k: Stage["id"]) => (stage(k).unlocked ? "" : "asleep");
  const summary = `Adventure map. Open: ${data.stages.filter((s) => s.unlocked).map((s) => s.name).join(", ")}. `
    + (data.next ? `${data.next.name} opens in ${data.next.washes_left} more rewarded ${data.next.washes_left === 1 ? "wash" : "washes"}.` : "Every place is open.");
  return (
    <svg className="worldmap" viewBox="12 0 366 398" role="img" aria-label={summary}>
      <defs>
        <linearGradient id={`${id}w`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#58dcd8" /><stop offset="1" stopColor="#2a9fc4" /></linearGradient>
        <linearGradient id={`${id}g`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#8fe08a" /><stop offset="1" stopColor="#3fae78" /></linearGradient>
        <linearGradient id={`${id}c`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#f0a98c" /><stop offset="1" stopColor="#d07a78" /></linearGradient>
        <linearGradient id={`${id}k`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#a892ea" /><stop offset="1" stopColor="#7460c4" /></linearGradient>
        <linearGradient id={`${id}f`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#c9fbff" /><stop offset="1" stopColor="#58dcd8" /></linearGradient>
        <radialGradient id={`${id}sea`} cx="0.5" cy="0.62" r="0.6"><stop offset="0" stopColor="#3fd0c4" stopOpacity="0.5" /><stop offset="1" stopColor="#3fd0c4" stopOpacity="0" /></radialGradient>
      </defs>
      <rect width="390" height="400" fill={`url(#${id}sea)`} />
      {/* far kelp towers */}
      <g fill="#2f5f9e" opacity="0.55">
        <rect x="20" y="150" width="26" height="170" rx="13" /><rect x="52" y="110" width="34" height="200" rx="17" /><rect x="304" y="120" width="34" height="190" rx="17" /><rect x="344" y="166" width="26" height="150" rx="13" />
      </g>

      {/* ---- Bacteria Castle: the back terrace */}
      <g className={shut("bacteria_castle")}>
        <Block x={0} y={0} w={5} d={5} top={3.4} fill={`url(#${id}k)`} left="#5a49a6" right="#463889" rim="#cbbcff" />
        <Tower x={0.3} y={0.3} z={3.4} h={2.6} />
        <Block x={1.5} y={0.5} w={2.2} d={0.8} top={4.6} base={3.4} fill="#cfc4ee" left="#8f82c9" right="#6f62ad" />
        <Tower x={3.5} y={0.3} z={3.4} h={2} roof="#e06c98" />
        <path d={`M${pt([2.6, 1.3, 3.4])[0] - 9} ${pt([2.6, 1.3, 3.4])[1]}v-16a9 9 0 0 1 18 0v16z`} fill="#33276e" />
        <Critter at={[1.5, 3.4, 3.4]} art={prickle} size={46} />
        <g transform={`translate(${pt([1.5, 3.4, 3.4])[0] - 11} ${pt([1.5, 3.4, 3.4])[1] - 56})`}><path d="M1 8 6 13 11 2l5 11 5-5-2 11H3z" fill="#f6c64f" stroke="#a97212" strokeWidth="1.5" strokeLinejoin="round" /></g>
      </g>

      {/* ---- Soap Canyon: terracotta cliffs with a soapy waterfall */}
      <g className={shut("soap_canyon")}>
        <Block x={5} y={0} w={5} d={5} top={2.3} fill={`url(#${id}c)`} left="#b8626c" right="#964d62" rim="#ffd2bd" />
        <Block x={8.2} y={0.4} w={1.5} d={1.7} top={3.3} base={2.3} fill="#f6bfa2" left="#c7727a" right="#a55a6c" />
        <Block x={6} y={0.5} w={1.4} d={1.1} top={2.9} base={2.3} fill="#ffc8d6" left="#e58aa6" right="#c76f93" rim="#fff" />
        <polygon points={poly([[5.6, 5, 2.3], [7, 5, 2.3], [7, 5, 0], [5.6, 5, 0]])} fill={`url(#${id}f)`} />
        <path d={`M${pt([5.9, 5, 2.1])[0]} ${pt([5.9, 5, 2.1])[1]}v44M${pt([6.5, 5, 2.2])[0]} ${pt([6.5, 5, 2.2])[1]}v50`} stroke="#fff" strokeWidth="2.5" strokeLinecap="round" opacity="0.7" />
        <Critter at={[9, 3.6, 2.3]} art={sneezel} size={42} />
        <circle cx={pt([6.7, 1, 3.6])[0]} cy={pt([6.7, 1, 3.6])[1]} r="6" fill="rgba(255,255,255,0.2)" stroke="#fff" strokeOpacity="0.8" strokeWidth="1.5" />
        <circle cx={pt([7.3, 1.2, 4.2])[0]} cy={pt([7.3, 1.2, 4.2])[1]} r="3.5" fill="rgba(255,255,255,0.2)" stroke="#fff" strokeOpacity="0.8" strokeWidth="1.2" />
      </g>

      {/* ---- Germ Jungle: a grassy shelf */}
      <g className={shut("germ_jungle")}>
        <Block x={0} y={5} w={5} d={5} top={1.2} fill={`url(#${id}g)`} left="#8a5a4e" right="#6e4544" rim="#d6ffc4" />
        <polygon points={poly([[0, 10, 1.2], [5, 10, 1.2], [5, 10, 0.92], [0, 10, 0.92]])} fill="#2f9468" />
        <polygon points={poly([[5, 5, 1.2], [5, 10, 1.2], [5, 10, 0.92], [5, 5, 0.92]])} fill="#237a5c" />
        <Frond at={[0.6, 5.6, 1.2]} s={1.25} /><Frond at={[1.7, 5.3, 1.2]} s={0.9} hue="#3fb596" flip /><Frond at={[0.5, 8.6, 1.2]} s={1} hue="#6fd27c" />
        <Shroom at={[3.9, 5.7, 1.2]} /><Shroom at={[1.2, 9.2, 1.2]} cap="#b08cf2" />
        <Critter at={[4.2, 9.1, 1.2]} art={gunky} size={42} />
      </g>

      {/* ---- Bubble Bay: open water at the front */}
      <g>
        <Block x={5} y={5} w={5} d={5} top={0} fill={`url(#${id}w)`} left="#1f86a8" right="#196d92" rim="#c4fbff" />
        <polygon points={poly([[5, 10, -0.5], [10, 10, -0.5], [10, 10, -0.9], [5, 10, -0.9]])} fill="#d9b98a" /><polygon points={poly([[10, 5, -0.5], [10, 10, -0.5], [10, 10, -0.9], [10, 5, -0.9]])} fill="#b9966e" />
        <polygon points={poly([[5.6, 5, 0], [7, 5, 0], [7.6, 6.2, 0], [5.6, 6.4, 0]])} fill="#eaffff" opacity="0.55" />
        {[[8.8, 6.3], [6.2, 8.9], [9.1, 8.8]].map(([x, y]) => <ellipse key={`${x}${y}`} cx={pt([x, y, 0])[0]} cy={pt([x, y, 0])[1]} rx="11" ry="5.5" fill="#7fe08a" stroke="#2f9468" strokeWidth="1.5" />)}
        <path d={`M${pt([5.4, 7.6, 0])[0]} ${pt([5.4, 7.6, 0])[1]}q10-5 20 0M${pt([8.3, 9.4, 0])[0]} ${pt([8.3, 9.4, 0])[1]}q9-4 18 0`} fill="none" stroke="#eaffff" strokeWidth="2" strokeLinecap="round" opacity="0.7" />
      </g>

      {/* ---- stepping stones and medals */}
      {ORDER.slice(0, -1).map((k, i) => Array.from({ length: data.stones }, (_, s) => (
        <Stone key={`${k}${s}`} at={lerp(SPOTS[k], SPOTS[ORDER[i + 1]], (s + 1) / (data.stones + 1))} lit={s < stage(k).stones_lit} />
      )))}
      {ORDER.map((k, i) => <Medal key={k} at={SPOTS[k]} n={i + 1} stage={stage(k)} current={k === here} />)}
      <Critter at={[SPOTS[here][0] - 0.2, SPOTS[here][1] - 0.9, SPOTS[here][2]]} art={bubbles} size={58} />
    </svg>
  );
}
