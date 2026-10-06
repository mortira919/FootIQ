// Roles, scenes and lessons copied from the app (lib/data/models.dart, lib/engine/scenes.dart).
// spots: x 0 left → 1 right, y 0 opponent goal → 1 own goal.
// drawn: the flank code the scene is drawn for (scenes.dart puts "me" there); the other flank plays it mirrored.
const ROLES = [
  { id: "st", codes: ["ST"], title: "Центральный нападающий", short: "Нападающий", spots: [[0.5, 0.13]],
    scene: "Уход от опекуна в момент паса",
    lesson: "Стоя перед защитником, ты в его конусе отбора. Уход в зазор между центральными защитниками в момент паса выводит тебя один на один.",
    skills: "отрыв от опекуна, игра на линии офсайда, стартовый триггер прессинга" },
  { id: "winger", codes: ["LW", "RW"], drawn: "LW", title: "Вингер", short: "Вингер", spots: [[0.14, 0.24], [0.86, 0.24]],
    scene: "Атака спины защитника",
    lesson: "Крайний защитник вышел вперёд и смотрит на мяч, а за его спиной пустой коридор. Рывок в спину, пока ты ещё в линии, выводит тебя один на один.",
    skills: "игра один в один, атака спины защитника, смещения в центр под удар" },
  { id: "ss", codes: ["SS"], title: "Оттянутый нападающий", short: "Ложная 9", spots: [[0.5, 0.25]],
    scene: "Опустись и утащи защитника",
    lesson: "Опорный соперника ушёл в прессинг, за ним дыра. Опускаясь туда, ты получаешь мяч лицом к воротам или тянешь за собой центрального защитника.",
    skills: "опускание в глубину, увод защитников, создание коридоров" },
  { id: "am", codes: ["AM"], title: "Атакующий полузащитник", short: "Атакующий", spots: [[0.5, 0.36]],
    scene: "Найди окно между линиями",
    lesson: "За спиной опорного соперника ты недоступен для паса. Сдвинься в правый полуфланг между линиями: там не достанет ни опорный, ни центральный защитник.",
    skills: "открывание между линиями, сканирование полуфлангов, разрезающий пас" },
  { id: "wm", codes: ["LM", "RM"], drawn: "RM", title: "Крайний полузащитник", short: "Крайний", spots: [[0.12, 0.48], [0.88, 0.48]],
    scene: "Прострел назад или навес",
    lesson: "Защитники и вратарь откатились к воротам, у ближней штанги плотно. Свободна зона у одиннадцатиметровой отметки: прострел назад на набегающего опаснее всего.",
    skills: "кроссы, смещения в центр, помощь защитнику в схемах 4-4-2 и 3-5-2" },
  { id: "cm", codes: ["CM"], title: "Центральный полузащитник", short: "Центральный", spots: [[0.5, 0.5]],
    scene: "Смени направление атаки",
    lesson: "Соперник сместился к мячу и закрыл левый фланг. Перевод на дальний фланг находит вингера один в один и с пространством. Нападающий в офсайде.",
    skills: "игра от штрафной до штрафной, треугольники передач, разворот атаки" },
  { id: "dm", codes: ["DM"], title: "Опорный полузащитник", short: "Опорный", spots: [[0.5, 0.63]],
    scene: "Выйди из тени опеки",
    lesson: "Пока ты за спиной прессингующего, линия «мяч и ты» перекрыта. Шаг в сторону от этой линии открывает передачу вперёд.",
    skills: "контроль зоны 14, перекрытие линий передач корпусом, баланс в переходе" },
  { id: "fb", codes: ["LB", "RB"], drawn: "RB", title: "Крайний защитник", short: "Крайний", spots: [[0.13, 0.7], [0.87, 0.7]],
    scene: "Overlap или underlap: куда открыться",
    lesson: "Защитник закрыл вингеру путь внутрь, значит, свободен внешний коридор. Забегание по бровке растягивает оборону и даёт вингеру пас.",
    skills: "забегания overlap и underlap, закрытие дальней штанги, прессинг на фланге" },
  { id: "cb", codes: ["CB"], title: "Центральный защитник", short: "Центральный", spots: [[0.5, 0.78]],
    scene: "Пас между линиями",
    lesson: "Передача в зазор между полузащитой и обороной соперника ломает сразу две линии прессинга: партнёр получает мяч там, где его никто не держит.",
    skills: "удержание линии офсайда, страховка партнёра, передачи между линиями" },
  { id: "gk", codes: ["GK"], title: "Вратарь", short: "Вратарь", spots: [[0.5, 0.9]],
    scene: "Первый пас под прессингом",
    lesson: "Нападающий бежит дугой и отрезает левого защитника, опорного держат. Свободен правый центральный: отдай ему на ход, чтобы он сразу повёл мяч вперёд.",
    skills: "позиция в створе, чтение навесов, игра на выходах, первый пас при розыгрыше" },
];

// Scene data generated from the app's lib/engine/scenes.dart. Meters: x 0..68 across,
// y 0 = opponent goal .. 105 = own goal. Each piece: [shirt number, keyframes]; me = your index in mates;
// ball = holder index at evenly spaced times. You on the ball at the freeze → the answer is a pass, else a run.
const SCENES = {"gk":{"me":0,"ball":[0],"gold":[[46.0,88.0],[58.0,88.0],[58.0,95.0],[46.0,95.0]],"mates":[[1,[[34.0,102.0],[34.0,101.0]]],[4,[[24.0,94.0],[18.0,96.0]]],[5,[[44.0,94.0],[50.0,96.0]]],[6,[[34.0,84.0],[34.0,87.0]]],[3,[[8.0,80.0],[5.0,82.0]]],[2,[[60.0,80.0],[63.0,82.0]]]],"opps":[[9,[[32.0,84.0],[29.0,92.0],[27.0,97.0]]],[10,[[34.0,78.0],[35.5,83.5]]],[11,[[52.0,80.0],[57.0,86.0]]],[7,[[16.0,80.0],[12.0,86.0]]]],"xt":0.03},"cb":{"me":0,"ball":[0],"gold":[[24.0,41.0],[33.0,41.0],[33.0,48.0],[24.0,48.0]],"mates":[[4,[[22.0,80.0],[24.0,74.0]]],[5,[[44.0,80.0],[46.0,76.0]]],[6,[[33.0,66.0],[35.0,60.5]]],[8,[[34.0,50.0],[28.0,45.0]]],[3,[[8.0,66.0],[6.0,60.0]]],[9,[[36.0,38.0],[36.0,36.0]]],[2,[[62.0,66.0],[62.0,60.0]]]],"opps":[[9,[[36.0,54.0],[33.5,64.0]]],[10,[[48.0,52.0],[47.0,62.0]]],[8,[[22.0,44.0],[20.0,48.0]]],[6,[[36.0,44.0],[36.0,47.0]]],[11,[[10.0,46.0],[9.0,50.0]]],[7,[[56.0,46.0],[57.0,50.0]]],[4,[[28.0,32.0],[28.0,34.0]]],[5,[[42.0,32.0],[41.0,34.0]]]],"xt":0.06},"fb":{"me":0,"ball":[1,1,1],"gold":[[60.0,26.5],[67.0,26.5],[67.0,32.0],[60.0,32.0]],"mates":[[2,[[58.0,60.0],[60.0,48.0],[61.0,41.0]]],[7,[[62.0,46.0],[60.0,39.0],[59.0,35.0]]],[8,[[44.0,52.0],[44.0,46.0],[45.0,44.0]]],[9,[[36.0,30.0],[37.0,27.0],[38.0,26.0]]],[10,[[40.0,40.0],[42.0,36.0],[43.0,34.0]]]],"opps":[[3,[[60.0,24.0],[58.0,27.0],[56.0,29.0]]],[11,[[52.0,44.0],[54.0,40.0],[55.0,39.0]]],[5,[[44.0,24.0],[44.0,25.0]]],[4,[[32.0,24.0],[32.0,24.0]]],[6,[[42.0,38.0],[45.0,37.0]]],[1,[[34.0,3.0]]]],"xt":0.05},"dm":{"me":0,"ball":[1],"gold":[[42.0,60.0],[50.0,60.0],[50.0,67.0],[42.0,67.0]],"mates":[[6,[[33.0,70.0],[34.0,66.0],[35.0,63.0]]],[5,[[44.0,84.0],[43.0,80.0],[42.0,76.0]]],[4,[[22.0,82.0],[24.0,78.0]]],[2,[[62.0,72.0],[63.0,64.0]]],[3,[[6.0,70.0],[5.0,62.0]]],[8,[[26.0,56.0],[24.0,50.0]]],[10,[[44.0,52.0],[46.0,46.0]]]],"opps":[[10,[[38.0,60.0],[38.5,65.0],[39.0,69.0]]],[9,[[30.0,62.0],[28.0,68.0],[27.0,72.0]]],[8,[[24.0,58.0],[26.0,60.0],[28.0,62.0]]],[6,[[40.0,50.0],[42.0,52.0]]],[7,[[56.0,58.0],[58.0,60.0]]]],"xt":0.03},"cm":{"me":0,"ball":[3,0,0],"gold":[[56.0,30.0],[66.0,30.0],[66.0,41.0],[56.0,41.0]],"mates":[[8,[[30.0,58.0],[26.0,54.0],[24.0,50.0]]],[3,[[8.0,60.0],[6.0,52.0],[5.0,46.0]]],[11,[[10.0,36.0],[9.0,32.0],[8.0,30.0]]],[6,[[34.0,66.0],[33.0,62.0],[32.0,60.0]]],[7,[[62.0,44.0],[62.0,40.0],[61.0,36.0]]],[9,[[32.0,28.0],[29.0,26.0],[26.5,24.5]]],[10,[[36.0,38.0],[36.0,36.0],[35.0,35.0]]]],"opps":[[10,[[26.0,40.0],[23.0,42.0],[22.0,44.0]]],[8,[[20.0,40.0],[17.0,42.0],[15.0,43.0]]],[6,[[34.0,44.0],[33.0,42.0],[34.0,39.0]]],[7,[[14.0,50.0],[11.0,49.0],[10.0,47.5]]],[4,[[22.0,26.0],[21.0,27.0],[20.0,27.0]]],[5,[[32.0,25.0],[31.0,26.0],[31.0,26.5]]],[2,[[12.0,28.0],[12.0,27.5]]],[3,[[46.0,30.0],[44.0,30.0],[43.0,30.0]]],[11,[[48.0,44.0],[45.0,47.0],[45.0,48.5]]],[1,[[34.0,3.0]]]],"xt":0.05},"am":{"me":0,"ball":[1],"gold":[[38.0,35.0],[46.0,35.0],[46.0,42.0],[38.0,42.0]],"mates":[[10,[[38.0,34.0],[34.0,38.0],[31.0,40.0]]],[8,[[36.0,66.0],[34.0,62.0],[32.0,58.0]]],[9,[[34.0,31.0],[34.0,29.0]]],[11,[[8.0,34.0],[8.0,30.0]]],[7,[[60.0,34.0],[60.0,30.0]]],[6,[[48.0,62.0],[48.0,60.0]]]],"opps":[[6,[[34.0,50.0],[31.0,47.0]]],[8,[[22.0,46.0],[22.0,47.0]]],[10,[[44.0,46.0],[44.0,47.0]]],[4,[[28.0,28.0],[27.0,33.0]]],[5,[[40.0,28.0],[40.0,28.0]]],[2,[[14.0,30.0],[15.0,30.0]]],[3,[[54.0,30.0],[53.0,30.0]]],[1,[[34.0,3.0]]]],"xt":0.07},"wm":{"me":0,"ball":[0],"gold":[[38.0,15.0],[47.0,15.0],[47.0,23.0],[38.0,23.0]],"mates":[[7,[[62.0,34.0],[61.0,20.0],[60.0,11.0]]],[9,[[40.0,24.0],[38.0,12.0],[37.5,5.0]]],[8,[[44.0,34.0],[43.0,26.0],[42.0,19.0]]],[11,[[16.0,28.0],[21.0,18.0],[25.0,10.5]]],[2,[[62.0,44.0],[62.0,34.0],[62.0,28.0]]],[10,[[34.0,34.0],[32.0,28.0],[30.0,24.0]]]],"opps":[[3,[[56.0,20.0],[57.0,10.0],[58.0,5.0]]],[5,[[38.0,18.0],[40.0,10.0],[40.5,6.5]]],[4,[[30.0,18.0],[30.0,10.0],[30.0,7.0]]],[2,[[18.0,18.0],[20.0,12.0],[21.0,8.0]]],[6,[[40.0,34.0],[38.0,28.0],[36.0,25.0]]],[1,[[34.0,2.0],[35.0,2.0],[35.0,2.5]]]],"xt":0.11},"winger":{"me":0,"ball":[1],"gold":[[10.0,18.0],[18.0,18.0],[18.0,27.0],[10.0,27.0]],"mates":[[11,[[10.0,40.0],[9.0,34.0],[9.0,31.0]]],[8,[[26.0,60.0],[24.0,54.0],[22.0,50.0]]],[9,[[34.0,30.0],[33.0,28.0],[32.0,28.0]]],[3,[[6.0,58.0],[6.0,52.0],[5.0,48.0]]],[10,[[38.0,42.0],[36.0,40.0],[35.0,38.0]]]],"opps":[[2,[[12.0,30.0],[13.0,32.0],[13.5,35.0]]],[5,[[28.0,24.0],[27.0,26.0],[26.0,27.0]]],[4,[[38.0,24.0],[38.0,26.0],[38.0,27.0]]],[3,[[52.0,26.0],[52.0,27.0]]],[7,[[28.0,40.0],[27.0,42.0],[26.0,44.0]]],[6,[[40.0,48.0],[38.0,46.0]]],[1,[[34.0,3.0]]]],"xt":0.09},"st":{"me":0,"ball":[1],"gold":[[24.0,11.0],[32.0,11.0],[32.0,19.0],[24.0,19.0]],"mates":[[9,[[32.0,30.0],[33.0,27.0],[34.0,25.0]]],[10,[[30.0,50.0],[28.0,44.0],[26.0,40.0]]],[11,[[8.0,32.0],[8.0,28.0]]],[7,[[60.0,32.0],[60.0,28.0]]],[8,[[44.0,52.0],[44.0,48.0]]]],"opps":[[5,[[34.0,21.0]]],[4,[[22.0,22.0],[20.0,23.0]]],[2,[[54.0,24.0]]],[3,[[12.0,24.0]]],[6,[[32.0,48.0],[31.0,46.0],[30.0,44.0]]],[8,[[40.0,42.0],[40.0,40.0]]],[1,[[34.0,4.0]]]],"xt":0.08},"ss":{"me":0,"ball":[1],"gold":[[26.0,33.0],[38.0,33.0],[38.0,41.0],[26.0,41.0]],"mates":[[9,[[34.0,30.0],[34.0,28.0],[34.0,26.0]]],[6,[[34.0,72.0],[32.0,66.0],[30.0,62.0]]],[11,[[8.0,30.0],[8.0,28.0]]],[7,[[60.0,30.0],[60.0,28.0]]],[8,[[44.0,58.0],[46.0,52.0],[48.0,48.0]]],[10,[[20.0,56.0],[19.0,50.0],[18.0,46.0]]]],"opps":[[5,[[36.0,22.0],[37.0,22.0]]],[4,[[30.0,22.0],[29.0,23.0]]],[6,[[34.0,46.0],[35.0,52.0],[35.0,55.0]]],[8,[[21.0,43.0]]],[10,[[46.0,44.0]]],[2,[[54.0,24.0]]],[3,[[14.0,24.0]]],[1,[[34.0,4.0]]]],"xt":0.05}};

const NS = "http://www.w3.org/2000/svg";
const pitch = document.querySelector(".pitch");
const scene = document.getElementById("scene");
const board = document.getElementById("board");
const phase = document.getElementById("phase");
const field = (name) => scene.querySelector(`[data-f="${name}"]`);
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const FEET = 2; // ball sits 2 m in front of its holder, as in tactics.dart
const T = { play: 3200, freeze: 4000, solve: 5600, loop: 7400 };
let current = "DM";
let timer;
let frame;
let visible = true;

new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(board);

const el = (tag, attrs, parent = board) => {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  parent.append(e);
  return e;
};
const lerp = (a, b, u) => [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u];
const clamp = (u) => Math.min(1, Math.max(0, u));
const ease = (u) => (u < 0.5 ? 4 * u * u * u : 1 - (-2 * u + 2) ** 3 / 2);
const fade = (ms, from, len) => clamp((ms - from) / len);

// Catmull-Rom through keyframes, same as Piece.at in tactics.dart.
function at(path, t) {
  if (path.length === 1) return path[0];
  const f = clamp(t) * (path.length - 1);
  const i = Math.min(Math.floor(f), path.length - 2);
  const u = f - i, u2 = u * u, u3 = u2 * u;
  const p = (k) => path[Math.min(path.length - 1, Math.max(0, k))];
  const m0 = [(p(i + 1)[0] - p(i - 1)[0]) / 2, (p(i + 1)[1] - p(i - 1)[1]) / 2];
  const m1 = [(p(i + 2)[0] - p(i)[0]) / 2, (p(i + 2)[1] - p(i)[1]) / 2];
  const h = [2 * u3 - 3 * u2 + 1, u3 - 2 * u2 + u, -2 * u3 + 3 * u2, u3 - u2];
  return [0, 1].map((d) => h[0] * p(i)[d] + h[1] * m0[d] + h[2] * p(i + 1)[d] + h[3] * m1[d]);
}

function ballAt(raw, mates, t) {
  const feet = (q) => [q[0], q[1] - FEET];
  const b = raw.ball;
  if (b.length === 1) return feet(at(mates[b[0]].path, t));
  const n = b.length - 1, f = clamp(t) * n, k = Math.min(Math.floor(f), n - 1);
  if (b[k] === b[k + 1]) return feet(at(mates[b[k]].path, t));
  return lerp(feet(at(mates[b[k]].path, k / n)), feet(at(mates[b[k + 1]].path, (k + 1) / n)), f - k);
}

function drawPitch(root = board) {
  for (let y = -42, i = 0; y < 147; y += 10.5, i++) el("rect", { x: -60, y, width: 188, height: 10.5, fill: i % 2 ? "#0c3c29" : "#0a3524" }, root);
  const g = el("g", { fill: "none", stroke: "rgb(240 248 243 / 0.45)", "stroke-width": 0.3 }, root);
  el("rect", { x: 0, y: 0, width: 68, height: 105 }, g);
  el("line", { x1: 0, y1: 52.5, x2: 68, y2: 52.5 }, g);
  el("circle", { cx: 34, cy: 52.5, r: 9.15 }, g);
  for (const [y, dir] of [[0, 1], [105, -1]]) {
    el("rect", { x: 13.84, y: dir > 0 ? y : y - 16.5, width: 40.32, height: 16.5 }, g);
    el("rect", { x: 24.84, y: dir > 0 ? y : y - 5.5, width: 18.32, height: 5.5 }, g);
    el("path", { d: `M26.7 ${y + dir * 16.5}a9.15 9.15 0 0 ${dir > 0 ? 0 : 1} 14.6 0` }, g);
  }
}

function disc(n, fill, ink, mine, root = board) {
  const g = el("g", {}, root);
  el("circle", { r: 2, fill, stroke: mine ? "#fff" : "rgb(0 0 0 / 0.45)", "stroke-width": mine ? 0.4 : 0.2 }, g);
  const t = el("text", { "text-anchor": "middle", "dominant-baseline": "central", "font-size": 1.75, "font-weight": 700, "font-family": "JetBrains Mono, monospace", fill: ink }, g);
  t.textContent = n;
  return g;
}

function play(id, mirrored) {
  cancelAnimationFrame(frame);
  const raw = SCENES[id];
  const fx = (q) => (mirrored ? [68 - q[0], q[1]] : q);
  const mates = raw.mates.map(([n, path]) => ({ n, path: path.map(fx) }));
  const opps = raw.opps.map(([n, path]) => ({ n, path: path.map(fx) }));
  const gold = raw.gold.map(fx);
  const target = [gold.reduce((s, q) => s + q[0], 0) / gold.length, gold.reduce((s, q) => s + q[1], 0) / gold.length];
  const isPass = raw.ball[raw.ball.length - 1] === raw.me;
  const me = mates[raw.me];
  const meFreeze = me.path[me.path.length - 1];
  const passer = mates[raw.ball[raw.ball.length - 1]];
  const ballFreeze = ballAt(raw, mates, 1);

  // Frame the action at 16:9 with a margin.
  const pts = [...mates.flatMap((m) => m.path), ...opps.flatMap((o) => o.path), ...gold];
  const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]);
  let [x0, x1, y0, y1] = [Math.min(...xs) - 6, Math.max(...xs) + 6, Math.min(...ys) - 6, Math.max(...ys) + 6];
  const w = Math.max(x1 - x0, (y1 - y0) * 16 / 9), h = w * 9 / 16;
  board.setAttribute("viewBox", `${(x0 + x1 - w) / 2} ${(y0 + y1 - h) / 2} ${w} ${h}`);

  board.replaceChildren();
  const defs = el("defs", {});
  const marker = el("marker", { id: "head", viewBox: "0 0 10 10", refX: 6, refY: 5, markerWidth: 4, markerHeight: 4, orient: "auto-start-reverse" }, defs);
  el("path", { d: "M0 0L10 5L0 10z", fill: "#ffd60a" }, marker);
  drawPitch();
  const zone = el("polygon", { points: gold.map((q) => q.join(",")).join(" "), fill: "rgb(255 214 10 / 0.2)", stroke: "#ffd60a", "stroke-width": 0.3, "stroke-dasharray": "1 0.6" });
  const from = isPass ? ballFreeze : meFreeze;
  const arrow = el("line", { x1: from[0], y1: from[1], x2: target[0], y2: target[1], stroke: "#ffd60a", "stroke-width": 0.55, "stroke-dasharray": "1.4 0.9", "marker-end": "url(#head)" });
  const ring = el("circle", { r: 2.1, fill: "none", stroke: "#ffd60a", "stroke-width": 0.3 });
  const oppG = opps.map((o) => ({ o, g: disc(o.n, "#e5483d", "#fff") }));
  const mateG = mates.filter((m) => m !== me).map((m) => ({ o: m, g: disc(m.n, "#eef3f0", "#060a08") }));
  const meG = disc(me.n, "#00855c", "#fff", true);
  const star = el("path", { d: "M0-1 .29-.4.95-.31.48.15.59.81 0 .5-.59.81-.48.15-.95-.31-.29-.4Z", fill: "#ffd60a", stroke: "#060a08", "stroke-width": 0.08 });
  const ball = el("circle", { r: 0.85, fill: "#fff", stroke: "#060a08", "stroke-width": 0.2 });
  const put = (g, q, s = 1) => g.setAttribute("transform", `translate(${q[0]} ${q[1]}) scale(${s})`);
  const task = isPass ? "Твоя задача: отдай пас в зону" : "Твоя задача: откройся в зону";

  const render = (ms) => {
    const t = clamp(ms / T.play);
    for (const { o, g } of [...oppG, ...mateG]) put(g, at(o.path, t));
    let mePos = at(me.path, t);
    let ballPos = ballAt(raw, mates, t);
    const solve = ease(fade(ms, T.freeze + 400, 900));
    if (!isPass) {
      mePos = lerp(meFreeze, target, solve);
      if (ms > T.freeze) ballPos = lerp(ballFreeze, [target[0], target[1] - FEET], ease(fade(ms, T.freeze + 900, 700)));
    } else if (ms > T.freeze) {
      ballPos = lerp(ballFreeze, target, solve);
    }
    put(meG, mePos);
    put(star, [mePos[0], mePos[1] - 4.1], 1.9);
    put(ball, ballPos);
    const pulse = fade(ms, T.play, T.freeze - T.play);
    put(ring, mePos, 1 + pulse * 1.6);
    ring.setAttribute("opacity", ms > T.play && ms < T.freeze ? 1 - pulse : 0);
    zone.setAttribute("opacity", fade(ms, T.play, 400));
    arrow.setAttribute("opacity", ms < T.solve ? fade(ms, T.play + 300, 400) : 1 - fade(ms, T.solve + 1200, 400));
    const text = ms < T.play ? "Розыгрыш" : ms < T.solve ? task : "Золото";
    if (phase.textContent !== text) { phase.textContent = text; phase.classList.toggle("gold", text === "Золото"); }
  };

  if (reduce) { render(T.freeze); return; }
  const start = performance.now();
  const tick = (now) => {
    if (visible) render((now - start) % T.loop);
    frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
}

for (const role of ROLES) {
  role.spots.forEach(([x, y], i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "marker";
    b.dataset.code = role.codes[i];
    b.style.left = `${x * 100}%`;
    b.style.top = `${y * 100}%`;
    b.setAttribute("aria-pressed", String(role.codes[i] === current));
    b.setAttribute("aria-label", `${role.title}, ${role.codes[i]}`);
    b.innerHTML = `<span class="disc">${role.codes[i]}</span><span class="name">${role.short}</span>`;
    b.addEventListener("click", () => select(role, role.codes[i]));
    pitch.append(b);
  });
}

function select(role, code) {
  for (const m of pitch.querySelectorAll(".marker")) m.setAttribute("aria-pressed", String(m.dataset.code === code));
  if (code === current) return;
  current = code;
  const side = role.drawn ? (code[0] === "L" ? ", левый фланг" : ", правый фланг") : "";
  clearTimeout(timer);
  scene.classList.add("swapping");
  scene.querySelector(".clip").classList.add("swapping");
  timer = setTimeout(() => {
    field("code").textContent = code;
    field("title").textContent = role.title + side;
    field("scene").textContent = role.scene;
    field("lesson").textContent = role.lesson;
    field("skills").textContent = `Тренирует: ${role.skills}.`;
    play(role.id, Boolean(role.drawn) && code !== role.drawn);
    scene.classList.remove("swapping");
    scene.querySelector(".clip").classList.remove("swapping");
  }, reduce ? 0 : 200);
  if (matchMedia("(max-width: 900px)").matches) scene.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "nearest" });
}

play("dm", false);

// --- Try it: the app's judge, ported 1:1 from lib/engine/tactics.dart (evaluate, explain) ---

const W = 68, L = 105;
const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
const mul = (a, k) => [a[0] * k, a[1] * k];
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const last = (path) => path[path.length - 1];
const CONE = Math.PI / 6; // 60° tackle cone
const REACH = 15, MARK = 2, SHADOW_HALF = 1.5, SHADOW_LEN = 40;

const facing = (from, ball) => { const d = sub(ball, from), n = Math.hypot(...d); return n < 0.01 ? [0, 1] : mul(d, 1 / n); };
const coneRadius = (opp, ball) => Math.min(6, Math.max(3, 3 + 0.1 * dist(opp, ball)));
function inCone(p, opp, ball) {
  const d = sub(p, opp), n = Math.hypot(...d);
  if (n > coneRadius(opp, ball)) return false;
  if (n < 0.01) return true;
  const f = facing(opp, ball);
  return (d[0] * f[0] + d[1] * f[1]) / n >= Math.cos(CONE);
}
function coverShadow(opp, ball) {
  const d = sub(opp, ball), len = Math.hypot(...d);
  if (len < 1) return [];
  const n = mul([-d[1], d[0]], SHADOW_HALF / len), k = (len + SHADOW_LEN) / len;
  const a = add(opp, n), b = sub(opp, n);
  return [a, b, add(ball, mul(sub(b, ball), k)), add(ball, mul(sub(a, ball), k))];
}
function inPolygon(p, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i], b = poly[j];
    if ((a[1] > p[1]) !== (b[1] > p[1]) && p[0] < ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}

function evaluate(sc, t) {
  if (!t) return { reason: "timeout" };
  if (t[0] < 0 || t[0] > W || t[1] < 0 || t[1] > L) return { reason: "out", end: t };
  const ball = sc.ball;
  let r = sc.me;
  if (sc.isPass) {
    const others = sc.mates.map((_, i) => i).filter((i) => i !== sc.passer);
    r = others.reduce((a, b) => (dist(sc.mates[a].at, t) <= dist(sc.mates[b].at, t) ? a : b));
  }
  if (dist(sc.mates[r].at, t) > REACH) return { reason: "noReceiver", end: t };
  if (sc.isOffside(sc.mates[r].at)) return { reason: "offside", end: t, receiver: r };
  const len = dist(t, ball);
  let hit = null; // earliest along the pass wins
  sc.opps.forEach(({ at: o }, i) => {
    let h = inPolygon(t, coverShadow(o, ball)) ? [dist(o, ball), "shadow", o] : null;
    for (let d = 2; d <= len && !h; d += 0.5) {
      const p = add(ball, mul(sub(t, ball), d / len));
      if (inCone(p, o, ball)) h = [d, "cone", p];
    }
    if (!h && dist(o, t) < MARK) h = [len, "marked", o];
    if (h && (!hit || h[0] < hit[0])) hit = [h[0], h[1], i, h[2]];
  });
  if (hit) return { reason: hit[1], end: hit[3], culprit: hit[2], receiver: r };
  return { reason: inPolygon(t, sc.gold) ? "optimal" : "safe", end: t, receiver: r };
}

const OUTCOME = { optimal: "gold", safe: "silver" };
const WORD = { gold: "Золото", silver: "Серебро", error: "Ошибка" };
function explain(sc, v) {
  const run = !sc.isPass;
  const opp = () => `№${sc.opps[v.culprit].n}`;
  return {
    timeout: "Время вышло. В матче на решение ещё меньше секунд.",
    out: "Мяч уходит за пределы поля.",
    noReceiver: run ? "Слишком далеко, не успеешь к передаче." : "Рядом с точкой паса нет партнёра, мяч уходит сопернику.",
    offside: run ? "Ты за линией офсайда в момент паса." : `Партнёр №${v.receiver != null ? sc.mates[v.receiver].n : ""} в офсайде в момент паса.`,
    cone: `Мяч проходит через конус отбора ${v.culprit != null ? opp() : ""}. Перехват.`,
    shadow: run ? `Ты в тени опеки ${v.culprit != null ? opp() : ""}: он закрывает линию паса корпусом.` : `Пас в тень опеки ${v.culprit != null ? opp() : ""}: он закрывает линию корпусом.`,
    marked: run ? `Ты вплотную к ${v.culprit != null ? opp() : ""}, он заберёт мяч.` : `Партнёр под плотной опекой ${v.culprit != null ? opp() : ""}.`,
    safe: "Мяч сохранён, но угрозы воротам нет.",
    optimal: `Лучшее решение: +${sc.xt.toFixed(2)} xT.`,
  }[v.reason];
}

function freezeScene(id) {
  const raw = SCENES[id];
  const withPath = raw.mates.map(([n, path]) => ({ n, path }));
  const mates = raw.mates.map(([n, path]) => ({ n, at: last(path) }));
  const opps = raw.opps.map(([n, path]) => ({ n, at: last(path) }));
  const ys = opps.map((o) => o.at[1]).sort((a, b) => a - b);
  const offside = ys.length < 2 ? 0 : ys[1];
  const ball = ballAt(raw, withPath, 1);
  const passer = raw.ball[raw.ball.length - 1];
  return {
    id, mates, opps, ball, passer, me: raw.me, isPass: passer === raw.me, gold: raw.gold, xt: raw.xt,
    isOffside: (p) => p[1] < L / 2 && p[1] < ball[1] && p[1] < offside,
  };
}

const tb = document.getElementById("try-board");
const tUi = (id) => document.getElementById(`try-${id}`);
const TRY_ORDER = ["cm", "st", "cb", "winger", "dm", "am", "wm", "fb", "ss", "gk"];
let tIdx = 0, tState = "idle", tSc, tDeadline, tTick, tAim, tAimMark, tLayer;

// Frozen frame of a scene, fitted to the svg's own aspect. Returns the layer under the pieces for overlays.
function drawFrozen(svg, sc, pad = 9) {
  const pts = [...sc.mates.map((m) => m.at), ...sc.opps.map((o) => o.at), ...sc.gold];
  const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs) - pad, Math.max(...xs) + pad, Math.min(...ys) - pad, Math.max(...ys) + pad];
  const A = svg.clientWidth / svg.clientHeight || 4 / 3;
  const w = Math.max(x1 - x0, (y1 - y0) * A), h = w / A;
  svg.setAttribute("viewBox", `${(x0 + x1 - w) / 2} ${(y0 + y1 - h) / 2} ${w} ${h}`);
  svg.replaceChildren();
  const defs = el("defs", {}, svg);
  for (const [id, fill] of [["head", "#fff"], ["head-live", "#30d158"]]) {
    const m = el("marker", { id: `${svg.id}-${id}`, viewBox: "0 0 10 10", refX: 6, refY: 5, markerWidth: 4, markerHeight: 4, orient: "auto-start-reverse" }, defs);
    el("path", { d: "M0 0L10 5L0 10z", fill }, m);
  }
  drawPitch(svg);
  const layer = el("g", {}, svg);
  const put = (g, q) => g.setAttribute("transform", `translate(${q[0]} ${q[1]})`);
  sc.opps.forEach((o) => put(disc(o.n, "#e5483d", "#fff", false, svg), o.at));
  sc.mates.forEach((mt, i) => { if (i !== sc.me) put(disc(mt.n, "#eef3f0", "#060a08", false, svg), mt.at); });
  const me = sc.mates[sc.me].at;
  put(disc(sc.mates[sc.me].n, "#00855c", "#fff", true, svg), me);
  el("path", { d: "M0-1 .29-.4.95-.31.48.15.59.81 0 .5-.59.81-.48.15-.95-.31-.29-.4Z", fill: "#ffd60a", stroke: "#060a08", "stroke-width": 0.08, transform: `translate(${me[0]} ${me[1] - 4.1}) scale(1.9)` }, svg);
  el("circle", { cx: sc.ball[0], cy: sc.ball[1], r: 0.85, fill: "#fff", stroke: "#060a08", "stroke-width": 0.2 }, svg);
  return layer;
}

function tLoad(id) {
  cancelAnimationFrame(tTick);
  tSc = freezeScene(id);
  const role = ROLES.find((r) => r.id === id);
  tUi("code").textContent = role.drawn || role.codes[0];
  tUi("role").textContent = role.title;
  tUi("scene").textContent = role.scene;
  tUi("task").textContent = tSc.isPass ? "Мяч у тебя. Нажми, куда отдать пас." : "Мяч у партнёра. Нажми, куда открыться под пас.";
  tLayer = drawFrozen(tb, tSc);
  const me = tSc.mates[tSc.me].at;
  tAim = tSc.isPass ? [...tSc.ball] : [...me];
  tAimMark = el("circle", { r: 1.2, fill: "none", stroke: "#fff", "stroke-width": 0.35, "stroke-dasharray": "0.6 0.4", opacity: 0 }, tb);
  tState = "idle";
  tUi("start").hidden = false;
  tUi("again").hidden = true;
  tUi("bar").style.setProperty("--left", 1);
  tUi("bar").classList.remove("low");
  tResult(null);
}

function tResult(v) {
  const box = tUi("result");
  const o = v ? OUTCOME[v.reason] || "error" : null;
  box.className = `result ${o || ""}`;
  tUi("word").textContent = o ? WORD[o] : "Твой ход";
  tUi("why").textContent = v ? explain(tSc, v) : "Звезда отмечает тебя. Решение сервер оценит одним из трёх вердиктов.";
  for (const li of document.querySelectorAll(".scale li")) li.classList.toggle("on", li.dataset.o === o);
}

function tStart() {
  if (tState !== "idle") return;
  tState = "running";
  tUi("start").hidden = true;
  tb.focus({ preventScroll: true });
  tDeadline = performance.now() + 7000;
  const tick = (now) => {
    const left = Math.max(0, (tDeadline - now) / 7000);
    tUi("bar").style.setProperty("--left", left);
    tUi("bar").classList.toggle("low", left < 0.3);
    if (left === 0) return tFinish(null);
    tTick = requestAnimationFrame(tick);
  };
  tTick = requestAnimationFrame(tick);
}

function tFinish(t) {
  if (tState !== "running") return;
  tState = "done";
  cancelAnimationFrame(tTick);
  tAimMark.setAttribute("opacity", 0);
  const v = evaluate(tSc, t);
  const g = tLayer;
  el("polygon", { points: tSc.gold.map((q) => q.join(",")).join(" "), fill: "rgb(255 214 10 / 0.22)", stroke: "#ffd60a", "stroke-width": 0.3, "stroke-dasharray": "1 0.6" }, g);
  if (v.culprit != null) {
    const o = tSc.opps[v.culprit].at;
    if (v.reason === "shadow") {
      el("polygon", { points: coverShadow(o, tSc.ball).map((q) => q.join(",")).join(" "), fill: "rgb(229 72 61 / 0.22)" }, g);
    } else {
      const f = facing(o, tSc.ball), a = Math.atan2(f[1], f[0]), r = coneRadius(o, tSc.ball);
      const p1 = add(o, [r * Math.cos(a - CONE), r * Math.sin(a - CONE)]), p2 = add(o, [r * Math.cos(a + CONE), r * Math.sin(a + CONE)]);
      el("path", { d: `M${o}L${p1}A${r} ${r} 0 0 1 ${p2}Z`, fill: "rgb(229 72 61 / 0.35)", stroke: "#e5483d", "stroke-width": 0.25 }, g);
    }
    el("circle", { cx: o[0], cy: o[1], r: 2.8, fill: "none", stroke: "#e5483d", "stroke-width": 0.4 }, g);
  }
  if (t) {
    const me = tSc.mates[tSc.me].at;
    if (!tSc.isPass) el("line", { x1: me[0], y1: me[1], x2: t[0], y2: t[1], stroke: "#30d158", "stroke-width": 0.45, "stroke-dasharray": "1.2 0.8", "marker-end": "url(#try-board-head-live)" }, g);
    const end = v.end || t;
    el("line", { x1: tSc.ball[0], y1: tSc.ball[1], x2: end[0], y2: end[1], stroke: "#fff", "stroke-width": 0.4, "marker-end": "url(#try-board-head)" }, g);
    el("path", { d: `M${t[0] - 1} ${t[1] - 1}l2 2m0-2l-2 2`, stroke: "#fff", "stroke-width": 0.4 }, g);
  }
  tResult(v);
  tUi("again").hidden = false;
}

function tPoint(e) {
  const p = tb.createSVGPoint();
  p.x = e.clientX; p.y = e.clientY;
  const q = p.matrixTransform(tb.getScreenCTM().inverse());
  return [q.x, q.y];
}

tb.addEventListener("pointerdown", (e) => { if (tState === "running") tFinish(tPoint(e)); });
tb.addEventListener("keydown", (e) => {
  const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
  if (tState === "idle" && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); return tStart(); }
  if (tState !== "running") return;
  if (step) {
    e.preventDefault();
    tAim = add(tAim, step);
    tAimMark.setAttribute("transform", `translate(${tAim[0]} ${tAim[1]})`);
    tAimMark.setAttribute("opacity", 1);
  } else if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    tFinish(tAim);
  }
});
tUi("start").addEventListener("click", tStart);
tUi("again").addEventListener("click", () => { tLoad(TRY_ORDER[tIdx]); tStart(); });
tUi("next").addEventListener("click", () => { tIdx = (tIdx + 1) % TRY_ORDER.length; tLoad(TRY_ORDER[tIdx]); });
tLoad(TRY_ORDER[0]);

// --- Modes: live previews of each mode's mechanic ---

{
  const svg = document.getElementById("mode-board");
  const sc = freezeScene("am");
  const layer = drawFrozen(svg, sc, 7);
  const gold = sc.gold, me = sc.mates[sc.me].at;
  const target = [gold.reduce((s, q) => s + q[0], 0) / gold.length, gold.reduce((s, q) => s + q[1], 0) / gold.length];
  el("polygon", { points: gold.map((q) => q.join(",")).join(" "), fill: "rgb(255 214 10 / 0.22)", stroke: "#ffd60a", "stroke-width": 0.3, "stroke-dasharray": "1 0.6" }, layer);
  el("line", { x1: me[0], y1: me[1], x2: target[0], y2: target[1], stroke: "#30d158", "stroke-width": 0.5, "stroke-dasharray": "1.2 0.8", "marker-end": "url(#mode-board-head-live)" }, layer);

  const ring = document.querySelector(".countdown");
  const digit = ring.querySelector(".mono");
  const clock = document.getElementById("rush-clock");
  const steps = document.querySelectorAll(".steps i");
  let left = 8, rush = 181; // first tick shows 7 and 3:00
  const tick = () => {
    left = left === 0 ? 7 : left - 1;
    ring.classList.toggle("reset", left === 7);
    ring.style.setProperty("--gone", String(1 - left / 7));
    digit.textContent = left;
    rush = rush === 0 ? 180 : rush - 1;
    clock.textContent = `${Math.floor(rush / 60)}:${String(rush % 60).padStart(2, "0")}`;
    const solved = Math.min(5, Math.floor((180 - rush) / 30) + 1);
    steps.forEach((s, i) => s.classList.toggle("on", i < solved));
  };
  if (reduce) { ring.style.setProperty("--gone", "0.43"); digit.textContent = "4"; clock.textContent = "2:41"; steps.forEach((s, i) => s.classList.toggle("on", i < 2)); }
  else { tick(); setInterval(tick, 1000); }
}
