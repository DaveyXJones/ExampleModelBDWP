import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { PART_INFO, EXPLODE, SECTIONS, TIMING, VIEW } from './parts.js';

const MODEL_URL = new URL('./models/bdry_basement.glb', import.meta.url).href;
const DRACO_PATH = 'https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/libs/draco/gltf/';
const UP = new THREE.Vector3(0, 1, 0);

const viewer = document.getElementById('viewer');
const hintEl = document.getElementById('hint');
const chipEl = document.getElementById('section-chip');
const loadingEl = document.getElementById('loading');
const loadingBar = loadingEl.querySelector('.bar span');
const resetBtn = document.getElementById('reset-view');

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let touchMode = !window.matchMedia('(hover: hover) and (pointer: fine)').matches;

// ---------------------------------------------------------------- renderer, scene, camera
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.NeutralToneMapping;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
viewer.prepend(renderer.domElement);

const labelRenderer = new CSS2DRenderer();
labelRenderer.domElement.className = 'label-layer';
renderer.domElement.after(labelRenderer.domElement);

const scene = new THREE.Scene();
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = VIEW.envIntensity;

const sun = new THREE.DirectionalLight(0xffffff, VIEW.sunIntensity);
sun.position.set(6, 14, 9);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -10, right: 10, top: 10, bottom: -10, near: 1, far: 40 });
sun.shadow.bias = -0.0004;
sun.shadow.normalBias = 0.02;
scene.add(sun, sun.target, new THREE.HemisphereLight(0xffffff, 0x8a8f96, VIEW.hemiIntensity));

const ground = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.ShadowMaterial({ opacity: 0.14 }));
ground.rotation.x = -Math.PI / 2;
ground.position.y = -0.455;
ground.receiveShadow = true;
scene.add(ground);

const camera = new THREE.PerspectiveCamera(36, 1, 0.05, 200);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = VIEW.minDistance;
controls.maxDistance = VIEW.maxDistance;
controls.zoomSpeed = VIEW.wheelZoomSpeed;
controls.minPolarAngle = 0.12;
controls.maxPolarAngle = 1.45;
controls.screenSpacePanning = true;
controls.zoomToCursor = true;
const PAN_LIMIT = new THREE.Box3(new THREE.Vector3(-6, -0.9, -5.2), new THREE.Vector3(6, 3, 5.2));
controls.addEventListener('change', () => PAN_LIMIT.clampPoint(controls.target, controls.target));

function homePose() {
  const target = new THREE.Vector3(...VIEW.home.target);
  const dir = new THREE.Vector3(...VIEW.home.position).sub(target);
  const scale = camera.aspect < 1.3 ? Math.min(2.2, 1.3 / camera.aspect) : 1; // back off on tall/narrow screens
  return { pos: target.clone().addScaledVector(dir, scale), target };
}

function resize() {
  const w = viewer.clientWidth, h = viewer.clientHeight;
  renderer.setSize(w, h);
  labelRenderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
resize();
new ResizeObserver(resize).observe(viewer);
{
  const { pos, target } = homePose();
  camera.position.copy(pos);
  controls.target.copy(target);
  controls.update();
}

// ---------------------------------------------------------------- model
const sections = [];
const pickables = [];
let active = null;     // the section that is exploded (or exploding)
let openLabel = null;  // the label whose description is showing

const asArray = (m) => (Array.isArray(m) ? m : [m]);
const clamp01 = (x) => Math.min(1, Math.max(0, x));
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

const draco = new DRACOLoader().setDecoderPath(DRACO_PATH);
new GLTFLoader().setDRACOLoader(draco).load(
  MODEL_URL,
  (gltf) => {
    initModel(gltf.scene);
    loadingEl.classList.add('done');
  },
  (xhr) => {
    if (xhr.total) loadingBar.style.width = `${Math.round((xhr.loaded / xhr.total) * 100)}%`;
  },
  (err) => {
    console.error(err);
    loadingEl.classList.add('error');
    loadingEl.querySelector('p').textContent = 'Sorry, the 3D model could not be loaded.';
  },
);

function initModel(root) {
  scene.add(root);
  const maxAniso = renderer.capabilities.getMaxAnisotropy();
  root.traverse((o) => {
    if (!o.isMesh) return;
    if (/^HIT_/.test(o.name) || /^HIT_/.test(o.parent?.name || '')) {
      o.visible = false;        // invisible hover/tap area: not drawn, but the raycaster still hits it
      pickables.push(o);
      return;
    }
    o.castShadow = o.receiveShadow = true;
    for (const m of asArray(o.material)) {
      for (const key of ['map', 'normalMap']) if (m[key]) m[key].anisotropy = maxAniso;
      if (m.name === 'MAT_Glass') {
        Object.assign(m, { transparent: true, opacity: 0.3, depthWrite: false });
        o.castShadow = false;
      }
      if (m.name === 'MAT_Hole') o.castShadow = false;
    }
    pickables.push(o);
  });
  root.updateMatrixWorld(true);
  ground.position.y = new THREE.Box3().setFromObject(root).min.y - 0.005;
  const secNodes = [];
  root.traverse((o) => o.name.startsWith('SEC_') && secNodes.push(o));
  for (const node of secNodes) sections.push(makeSection(node));
  // sections that sit on a wall turn see-through together with it
  for (const s of sections) if (s.cfg.fadeWith) s.fadeWith = sections.find((o) => o.name === s.cfg.fadeWith);
  // things standing in the way of a section's pieces fade out while it is open (SECTIONS[...].hides);
  // the section waits 'lead' (phase units) for them to go before anything moves
  for (const s of sections) {
    s.hides = (s.cfg.hides || []).map((name) => hideTarget(root, name)).filter(Boolean);
    s.lead = s.hides.length ? TIMING.hideFade / TIMING.duration : 0;
  }
}

const hideTargets = new Map();
function hideTarget(root, name) {
  if (hideTargets.has(name)) return hideTargets.get(name);
  const node = root.getObjectByName(name);
  if (!node) {
    console.warn(`parts.js hides: no object named ${name}`);
    return null;
  }
  const meshes = [];
  node.traverse((m) => m.isMesh && meshes.push(m));
  const mats = [];
  for (const m of meshes) {
    // fading needs materials of its own (sections with 'inward' already gave their pieces copies)
    if (asArray(m.material).some((mm) => mm.userData.baseOpacity === undefined)) {
      m.material = Array.isArray(m.material) ? m.material.map(cloneMat) : cloneMat(m.material);
    }
    mats.push(...asArray(m.material));
  }
  const t = { meshes, mats, h: 0, goal: 0 };
  hideTargets.set(name, t);
  return t;
}

function updateHides() {
  for (const t of hideTargets.values()) t.goal = 0;
  for (const s of sections) {
    if (!s.lead) continue;
    const h = clamp01(s.phase / s.lead);
    for (const t of s.hides) t.goal = Math.max(t.goal, h);
  }
  for (const t of hideTargets.values()) {
    if (t.goal === t.h) continue;
    t.h = t.goal;
    setOpacity(t.mats, 1 - t.h);
    for (const m of t.meshes) {
      m.visible = t.h < 0.999;
      m.userData.hidden = t.h > 0.5;   // once mostly gone, the cursor passes through it
    }
  }
}

function cloneMat(m) {
  const c = m.clone();
  c.userData.baseOpacity = m.opacity;
  c.userData.baseTransparent = m.transparent;
  return c;
}

function ownMaterials(obj) {
  const mats = [];
  obj.traverse((m) => {
    if (!m.isMesh) return;
    m.material = Array.isArray(m.material) ? m.material.map(cloneMat) : cloneMat(m.material);
    mats.push(...asArray(m.material));
  });
  return mats;
}

function setOpacity(mats, a) {
  for (const m of mats) {
    const transparent = m.userData.baseTransparent || a < 0.999;
    if (m.transparent !== transparent) {
      m.transparent = transparent;
      m.needsUpdate = true;
    }
    m.opacity = m.userData.baseOpacity * a;
    m.depthWrite = m.userData.baseTransparent ? false : a > 0.6;
  }
}

function makeSection(node) {
  const cfg = SECTIONS[node.name] || {};
  const s = {
    name: node.name, node, cfg, parts: [], labels: [], meshes: [], shellMats: [],
    phase: 0, target: 0, fade: 1, maxOrder: 0, labelsShown: false,
    inward: cfg.inward && new THREE.Vector3(...cfg.inward),
    along: cfg.along && new THREE.Vector3(...cfg.along),
  };
  for (const child of [...node.children]) {
    const [kind, type] = child.name.split('_');
    child.traverse((m) => {
      if (!m.isMesh) return;
      m.userData.section = s;
      s.meshes.push(m);
    });
    // each wall gets its own material copies so it can turn see-through on its own
    const mats = cfg.inward ? ownMaterials(child) : [];
    if (kind === 'SHELL') {
      s.shellMats.push(...mats);
      if (child.name.startsWith('SHELL_Wall_') && s.inward) {
        const box = new THREE.Box3().setFromObject(child);
        const size = box.getSize(new THREE.Vector3());
        s.facePoint = box.getCenter(new THREE.Vector3()).addScaledVector(s.inward, Math.abs(size.dot(s.inward)) / 2);
      }
    } else if ((kind === 'PART' || kind === 'FILL') && s.inward) {
      const ex = { ...(EXPLODE[type] || {}), ...((cfg.explode || {})[type] || {}) };
      const offset = new THREE.Vector3()
        .addScaledVector(s.inward, ex.in || 0)
        .addScaledVector(UP, ex.up || 0)
        .addScaledVector(s.along, ex.along || 0);
      const part = { node: child, type, base: child.position.clone(), offset, order: ex.order || 0, fade: ex.fade, alpha: 1, mats };
      s.parts.push(part);
      s.maxOrder = Math.max(s.maxOrder, part.order);
      if (kind === 'PART' && PART_INFO[type]) addLabel(s, child, type, ex.label || {});
    }
  }
  s.explodable = s.parts.length > 0;
  return s;
}

function addLabel(s, node, type, opts) {
  const info = PART_INFO[type];
  // an LBL_ empty under the part (placed in Blender) wins; otherwise use the part's bounding box
  const marker = node.children.find((c) => c.name.startsWith('LBL_'));
  let anchor;
  if (marker) {
    anchor = marker.getWorldPosition(new THREE.Vector3());
  } else {
    const box = new THREE.Box3().setFromObject(node);
    const size = box.getSize(new THREE.Vector3());
    anchor = box.getCenter(new THREE.Vector3()).addScaledVector(s.along, (opts.t ?? 0) * Math.abs(size.dot(s.along)));
    anchor.y = box.min.y + (opts.h ?? 0.5) * size.y;
  }

  // The element is zero-size and sits exactly on the anchor: the dot marks the part, and the
  // card is offset by --dy (set by layoutLabels) so cards never overlap, with a leader line back.
  const el = document.createElement('div');
  el.className = 'part-label';
  el.innerHTML =
    '<span class="pl-leader" aria-hidden="true"></span><span class="pl-dot" aria-hidden="true"></span>' +
    '<div class="pl-card"><button type="button" class="pl-head" aria-expanded="false">' +
    '<span class="pl-title"></span></button><div class="pl-body"></div></div>';
  el.querySelector('.pl-title').textContent = info.title;
  el.querySelector('.pl-body').textContent = info.text;
  el.section = s;
  el.querySelector('.pl-head').addEventListener('click', (e) => {
    e.stopPropagation();
    toggleLabel(el);
  });

  const obj = new CSS2DObject(el);
  obj.center.set(0, 0);
  obj.position.copy(node.worldToLocal(anchor));
  node.add(obj);
  s.labels.push(el);
  s.labelItems = s.labelItems || [];
  s.labelItems.push({ el, obj, card: el.querySelector('.pl-card') });
}

// Spread the cards of the open section vertically so none overlap (dots stay on their parts).
const CARD_X = 22, HEAD_H = 26, GAP = 6;
const proj = new THREE.Vector3();
function layoutLabels() {
  if (!active || !active.labelsShown || !active.labelItems) return;
  const w = renderer.domElement.clientWidth, h = renderer.domElement.clientHeight;
  const items = [];
  for (const it of active.labelItems) {
    if (it.el.style.display === 'none') continue;
    it.obj.getWorldPosition(proj).project(camera);
    items.push({ it, x: (proj.x * 0.5 + 0.5) * w, y: (-proj.y * 0.5 + 0.5) * h,
                 cw: it.card.offsetWidth, ch: it.card.offsetHeight });
  }
  items.sort((a, b) => a.y - b.y);
  const placed = [];
  const M = 8; // screen margin
  for (const c of items) {
    // card to the right of its dot; else to the left; else centred under the dot, kept on screen
    let side, left, top;
    if (c.x + CARD_X + c.cw <= w - M) [side, left] = ['r', c.x + CARD_X];
    else if (c.x - CARD_X - c.cw >= M) [side, left] = ['l', c.x - CARD_X - c.cw];
    else [side, left] = ['c', c.x - c.cw / 2];
    left = Math.min(Math.max(M, left), w - M - c.cw);     // the card always stays on screen
    top = side === 'c' ? c.y + 16 : c.y - HEAD_H / 2;
    const right = left + c.cw;
    for (let moved = true; moved;) {
      moved = false;
      for (const p of placed) {
        if (left < p.right + GAP && right > p.left - GAP && top < p.bottom + GAP && top + c.ch > p.top - GAP) {
          top = p.bottom + GAP;
          moved = true;
        }
      }
    }
    placed.push({ left, right, top, bottom: top + c.ch });

    const it = c.it;
    const gx = left - c.x, gy = top - c.y;               // card offset from the dot
    if (it.dx === undefined) [it.dx, it.dy] = [gx, gy];
    it.dx += (gx - it.dx) * 0.3;
    it.dy += (gy - it.dy) * 0.3;
    if (Math.abs(gx - it.dx) < 0.5) it.dx = gx;
    if (Math.abs(gy - it.dy) < 0.5) it.dy = gy;
    // leader line from the dot to the nearest edge of the card
    const ex = side === 'r' ? it.dx : side === 'l' ? it.dx + c.cw : Math.min(Math.max(0, it.dx + 12), it.dx + c.cw - 12);
    const ey = side === 'c' ? it.dy : it.dy + HEAD_H / 2;
    const st = it.el.style;
    st.setProperty('--dx', `${it.dx.toFixed(1)}px`);
    st.setProperty('--dy', `${it.dy.toFixed(1)}px`);
    st.setProperty('--len', `${Math.hypot(ex, ey).toFixed(1)}px`);
    st.setProperty('--ang', `${Math.atan2(ey, ex).toFixed(3)}rad`);
  }
}

function toggleLabel(el) {
  const opening = openLabel !== el;
  closeOpenLabel();
  if (!opening) return;
  el.classList.add('open');
  el.querySelector('.pl-head').setAttribute('aria-expanded', 'true');
  openLabel = el;
}

function closeOpenLabel() {
  if (!openLabel) return;
  openLabel.classList.remove('open');
  openLabel.querySelector('.pl-head').setAttribute('aria-expanded', 'false');
  openLabel = null;
}

// ---------------------------------------------------------------- explode / collapse
function activate(s) {
  cancelLeave();
  if (active === s) return;
  if (active) active.target = 0;
  active = s;
  s.target = 1;
  chipEl.textContent = s.cfg.title || '';
  chipEl.hidden = !s.cfg.title;
}

function deactivate() {
  cancelLeave();
  if (active) active.target = 0;
  active = null;
  chipEl.hidden = true;
}

let leaveTimer = null;
function scheduleLeave() {
  if (active && !leaveTimer) leaveTimer = setTimeout(() => { leaveTimer = null; deactivate(); }, TIMING.leaveDelay);
}
function cancelLeave() {
  clearTimeout(leaveTimer);
  leaveTimer = null;
}

function updateSections(dt) {
  const step = dt / (reduceMotion ? 0.12 : TIMING.duration);
  const sf = TIMING.stagger / TIMING.duration;
  for (const s of sections) {
    if (!s.explodable) continue;
    const lead = s.lead || 0;           // time for its 'hides' to fade out first
    const max = lead + 1 + s.maxOrder * sf;
    const goal = s.target ? max : 0;
    if (s.phase !== goal) {
      s.phase = s.target ? Math.min(goal, s.phase + step) : Math.max(0, s.phase - step * TIMING.collapseSpeed);
      for (const p of s.parts) {
        const k = ease(clamp01(s.phase - lead - p.order * sf));
        p.node.position.copy(p.base).addScaledVector(p.offset, k);
        if (p.fade !== undefined) {
          p.alpha = 1 + (p.fade - 1) * k;
          setOpacity(p.mats, s.fade * p.alpha);
        }
      }
    }
    const show = s.target === 1 && s.phase >= max - 0.15;
    if (show !== s.labelsShown) {
      s.labelsShown = show;
      for (const el of s.labels) el.classList.toggle('show', show);
      if (!show && openLabel && openLabel.section === s) closeOpenLabel();
    }
  }
}

// walls between the camera and the room turn see-through so you can look in
const tmp = new THREE.Vector3();
function updateWallFades(dt) {
  for (const s of sections) {
    const ref = s.fadeWith || s;
    if (!ref.facePoint) continue;
    const outside = tmp.copy(camera.position).sub(ref.facePoint).dot(ref.inward) < 0;
    const goal = outside ? VIEW.fadedWallOpacity : 1;
    if (s.fade === goal) continue;
    s.fade += (goal - s.fade) * Math.min(1, dt * 8);
    if (Math.abs(s.fade - goal) < 0.01) s.fade = goal;
    setOpacity(s.shellMats, s.fade);
    for (const p of s.parts) setOpacity(p.mats, s.fade * p.alpha);
    for (const m of s.meshes) {
      m.userData.faded = s.fade < 0.5;
      m.castShadow = !m.userData.faded && !asArray(m.material).some((mm) => mm.name === 'MAT_Glass' || mm.name === 'MAT_Hole');
    }
  }
}

// ---------------------------------------------------------------- picking
const raycaster = new THREE.Raycaster();
const ndc = new THREE.Vector2();
const box = new THREE.Box3();

function pickSection(clientX, clientY, sticky) {
  const r = renderer.domElement.getBoundingClientRect();
  ndc.set(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(ndc, camera);
  let first = null, firstDist = Infinity;   // first solid thing under the cursor
  for (const hit of raycaster.intersectObjects(pickables, false)) {
    if (hit.object.userData.faded || hit.object.userData.hidden) continue;
    first = hit.object.userData.section || null;
    firstDist = hit.distance;
    break;
  }
  if (first && first === active) return active;
  // Keep the open section while the cursor is within its exploded pieces: over the floor, a gap,
  // or something entirely behind the open section. Anything hit inside its area takes over.
  if (sticky && active) {
    const range = rayBoxRange(raycaster.ray, box.setFromObject(active.node).expandByScalar(0.1));
    if (range && (!first || !first.explodable || firstDist > range[1])) return active;
  }
  return first && first.explodable ? first : null;
}

// distances along the ray where it enters and leaves the box, or null
function rayBoxRange(ray, b) {
  let tmin = 0, tmax = Infinity;
  for (const k of ['x', 'y', 'z']) {
    const o = ray.origin[k], d = ray.direction[k];
    if (Math.abs(d) < 1e-9) {
      if (o < b.min[k] || o > b.max[k]) return null;
      continue;
    }
    let t1 = (b.min[k] - o) / d, t2 = (b.max[k] - o) / d;
    if (t1 > t2) [t1, t2] = [t2, t1];
    tmin = Math.max(tmin, t1);
    tmax = Math.min(tmax, t2);
    if (tmin > tmax) return null;
  }
  return [tmin, tmax];
}

let pointer = null;
let overLabelSection = null;
let pickPending = false;
let dragging = false;

viewer.addEventListener('pointermove', (e) => {
  if (e.pointerType !== 'mouse') return;
  if (touchMode) {
    touchMode = false;
    setHint();
  }
  pointer = { x: e.clientX, y: e.clientY };
  overLabelSection = e.target.closest?.('.part-label')?.section || null;
  pickPending = true;
});
viewer.addEventListener('pointerleave', (e) => {
  if (e.pointerType !== 'mouse') return;
  pointer = null;
  overLabelSection = null;
  scheduleLeave();
});
controls.addEventListener('start', () => {
  dragging = true;
  fly = null;
});
controls.addEventListener('end', () => {
  dragging = false;
  pickPending = true;
});

function hoverPick() {
  if (touchMode || dragging) return;
  const s = overLabelSection || (pointer ? pickSection(pointer.x, pointer.y, true) : null);
  if (s) activate(s);
  else scheduleLeave();
}

// Zooming in heads for the surface under the cursor (or between two fingers): the orbit point is
// moved along the view line to that surface's depth, so each zoom step closes in on it instead of
// stopping short (or flying through it) when the orbit point is somewhere else in the room.
const viewDir = new THREE.Vector3();
function focusDepthAt(clientX, clientY) {
  const r = renderer.domElement.getBoundingClientRect();
  ndc.set(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(ndc, camera);
  const hit = raycaster.intersectObjects(pickables, false).find((h) => h.object.visible && !h.object.userData.faded && !h.object.userData.hidden);
  if (!hit) return;
  camera.getWorldDirection(viewDir);
  const depth = hit.point.clone().sub(camera.position).dot(viewDir);
  if (depth > controls.minDistance * 1.2) controls.target.copy(camera.position).addScaledVector(viewDir, depth);
}
viewer.addEventListener('wheel', (e) => {
  controls.zoomSpeed = VIEW.wheelZoomSpeed;
  if (e.deltaY < 0) focusDepthAt(e.clientX, e.clientY);
}, { capture: true, passive: true });

// touch: tap a section to open it, tap it again or tap outside to close
const touches = new Set();
let tap = null;
let firstTouch = null;
viewer.addEventListener('pointerdown', (e) => {
  if (e.pointerType === 'mouse') {
    tap = { x: e.clientX, y: e.clientY, onLabel: !!e.target.closest('.part-label') };
    return;
  }
  if (!touchMode) {
    touchMode = true;
    setHint();
  }
  touches.add(e.pointerId);
  controls.zoomSpeed = VIEW.touchZoomSpeed;
  if (touches.size === 1) firstTouch = { x: e.clientX, y: e.clientY };
  if (touches.size === 2 && firstTouch) focusDepthAt((firstTouch.x + e.clientX) / 2, (firstTouch.y + e.clientY) / 2);
  tap = touches.size === 1
    ? { x: e.clientX, y: e.clientY, t: performance.now(), onLabel: !!e.target.closest('.part-label, button') }
    : null;
});
function endPointer(e) {
  if (e.pointerType === 'mouse') {
    // a plain click on empty space closes an open description
    if (tap && !tap.onLabel && Math.hypot(e.clientX - tap.x, e.clientY - tap.y) < 5) closeOpenLabel();
    tap = null;
    return;
  }
  touches.delete(e.pointerId);
  const t = tap;
  tap = null;
  if (e.type !== 'pointerup' || !t || t.onLabel) return;
  if (Math.hypot(e.clientX - t.x, e.clientY - t.y) > 10 || performance.now() - t.t > 600) return;
  const s = pickSection(e.clientX, e.clientY, false);
  if (s && s !== active) activate(s);
  else deactivate();
}
viewer.addEventListener('pointerup', endPointer);
viewer.addEventListener('pointercancel', endPointer);

function setHint() {
  hintEl.textContent = touchMode
    ? 'Tap a wall to look inside. Tap a label to learn what each part does.'
    : 'Hover over a wall to look inside. Click a label to learn what each part does.';
}
setHint();

// ---------------------------------------------------------------- reset view
let fly = null;
resetBtn.addEventListener('click', () => {
  const { pos, target } = homePose();
  fly = { t: 0, fromPos: camera.position.clone(), fromTarget: controls.target.clone(), pos, target };
});

// ---------------------------------------------------------------- loop
const clock = new THREE.Clock();
renderer.setAnimationLoop(frame);
function frame() {
  const dt = Math.min(clock.getDelta(), 0.05);
  if (fly) {
    fly.t = Math.min(1, fly.t + dt / 0.9);
    const k = ease(fly.t);
    camera.position.lerpVectors(fly.fromPos, fly.pos, k);
    controls.target.lerpVectors(fly.fromTarget, fly.target, k);
    if (fly.t >= 1) fly = null;
  }
  controls.update();
  // near clipping plane follows the zoom, so close-ups don't get cut off and far views stay crisp
  const near = THREE.MathUtils.clamp(camera.position.distanceTo(controls.target) * 0.02, 0.004, 0.1);
  if (Math.abs(near - camera.near) > camera.near * 0.1) {
    camera.near = near;
    camera.updateProjectionMatrix();
  }
  if (pickPending) {
    pickPending = false;
    hoverPick();
  }
  updateSections(dt);
  updateHides();
  updateWallFades(dt);
  renderer.render(scene, camera);
  labelRenderer.render(scene, camera);
  layoutLabels();
  if (openLabel) openLabel.style.zIndex = '100000'; // keep the open description above other labels
}

// handy for testing from the browser console
window.bdryViewer = { sections, activate, deactivate, camera, controls, scene, pickSection, raycaster, frame };
