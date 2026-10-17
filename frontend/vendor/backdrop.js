/*!
 * gradient-backdrops — animated shader backdrops for the web.
 * Zero dependencies. Works as a classic <script> (exposes globalThis.GradientBackdrop)
 * or via `import './backdrop.js'` / the ESM wrapper backdrop.mjs.
 *
 * Techniques: domain-warped simplex fbm (after Inigo Quilez), OKLab palette mixing,
 * SDF shapes, Beer–Lambert pigment absorption. Simplex noise: Ashima Arts / Stefan
 * Gustavson (MIT). Hash: Dave Hoskins "hash without sine" (MIT).
 *
 * Each backdrop draws straight into its own WebGL canvas (the fast path). Past 12 on
 * one page, extras render in one shared hidden context and are copied into a 2D canvas,
 * so large galleries stay under the browser's WebGL context limit.
 */
(function (global) {
  'use strict';

  // ---------------------------------------------------------------------------
  // GLSL prelude shared by every style
  // ---------------------------------------------------------------------------
  const PRELUDE = `
precision highp float;
uniform vec2 u_res;
uniform float u_time;
uniform float u_seed;
uniform float u_count;
uniform vec3 u_rgb[6];
uniform vec3 u_lab[6];
#define PI 3.14159265359
#define TAU 6.28318530718

// 0..1 across the canvas, y up
vec2 fragUV() { return gl_FragCoord.xy / u_res; }
// centred, shorter side spans -0.5..0.5, aspect-correct
vec2 fragP() { return (gl_FragCoord.xy - 0.5 * u_res) / min(u_res.x, u_res.y); }
float aspect() { return u_res.x / u_res.y; }
mat2 rot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }

float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
vec2 hash22(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.xx + p3.yz) * p3.zy);
}

// ---- colour: sRGB <-> linear <-> OKLab ----
vec3 toLinear(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }
vec3 toSRGB(vec3 c) { c = max(c, 0.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }
vec3 labToSRGB(vec3 L) {
  float l_ = L.x + 0.3963377774 * L.y + 0.2158037573 * L.z;
  float m_ = L.x - 0.1055613458 * L.y - 0.0638541728 * L.z;
  float s_ = L.x - 0.0894841775 * L.y - 1.2914855480 * L.z;
  float l = l_ * l_ * l_, m = m_ * m_ * m_, s = s_ * s_ * s_;
  return toSRGB(vec3(
     4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s));
}
vec3 srgbToLab(vec3 c) {
  vec3 l = toLinear(c);
  float L_ = pow(max(0.4122214708 * l.r + 0.5363325363 * l.g + 0.0514459929 * l.b, 0.0), 1.0 / 3.0);
  float M_ = pow(max(0.2119034982 * l.r + 0.6806995451 * l.g + 0.1073969566 * l.b, 0.0), 1.0 / 3.0);
  float S_ = pow(max(0.0883024619 * l.r + 0.2817188376 * l.g + 0.6299787005 * l.b, 0.0), 1.0 / 3.0);
  return vec3(0.2104542553 * L_ + 0.7936177850 * M_ - 0.0040720468 * S_,
              1.9779984951 * L_ - 2.4285922050 * M_ + 0.4505937099 * S_,
              0.0259040371 * L_ + 0.7827717662 * M_ - 0.8086757660 * S_);
}
const vec3 LAB_WHITE = vec3(1.0, 0.0, 0.0);

// ---- palette access (u_count stops, evenly spaced) ----
int lastIndex() { return int(u_count + 0.5) - 1; }
vec3 col(int i) {
  vec3 c = u_rgb[0];
  for (int k = 1; k < 6; k++) { if (float(k) > u_count - 0.5) break; if (k <= i) c = u_rgb[k]; }
  return c;
}
vec3 lab(int i) {
  vec3 c = u_lab[0];
  for (int k = 1; k < 6; k++) { if (float(k) > u_count - 0.5) break; if (k <= i) c = u_lab[k]; }
  return c;
}
// smooth OKLab ramp across the whole palette, t in 0..1
vec3 rampLab(float t) {
  t = clamp(t, 0.0, 1.0) * (u_count - 1.0);
  vec3 c = u_lab[0];
  for (int k = 1; k < 6; k++) {
    if (float(k) > u_count - 0.5) break;
    c = mix(c, u_lab[k], clamp(t - float(k - 1), 0.0, 1.0));
  }
  return c;
}
// ramp across a sub-range of stops, a and b are stop indices
vec3 rampRangeLab(float t, float a, float b) {
  return rampLab(mix(a, b, clamp(t, 0.0, 1.0)) / max(u_count - 1.0, 1.0));
}
vec3 ramp(float t) { return labToSRGB(rampLab(t)); }

// ---- simplex noise 3D (Ashima Arts / Stefan Gustavson, MIT) ----
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
float snoise(vec3 v) {
  const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(
            i.z + vec4(0.0, i1.z, i2.z, 1.0))
          + i.y + vec4(0.0, i1.y, i2.y, 1.0))
          + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0) * 2.0 + 1.0;
  vec4 s1 = floor(b1) * 2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
  m = m * m;
  return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}
// fractal sum, roughly -0.9..0.9
float fbm(vec3 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 4; i++) { v += a * snoise(p); p = p * 2.03 + vec3(17.1, 31.7, 7.3); a *= 0.5; }
  return v;
}
float fbmLo(vec3 p) {
  return 0.66 * snoise(p) + 0.34 * snoise(p * 2.03 + vec3(17.1, 31.7, 7.3));
}

// dither removes 8-bit banding in smooth gradients
vec4 finish(vec3 c) {
  c += (hash12(gl_FragCoord.xy + fract(u_time * 0.37) * 91.0) - 0.5) / 255.0;
  return vec4(clamp(c, 0.0, 1.0), 1.0);
}
vec4 finishLab(vec3 L) { return finish(labToSRGB(L)); }
`;

  // ---------------------------------------------------------------------------
  // Styles. params: name -> [default, min, max, step]  (or { value } for arrays)
  // Each param becomes a float uniform u_<name> (arrays become vec2/vec3 arrays).
  // `order` documents how the palette is read by the style.
  // ---------------------------------------------------------------------------
  const STYLES = {
    flow: {
      label: 'Flow',
      order: 'any order — the warped field sweeps across the ramp. 3–5 colours.',
      quality: 0.5,
      params: { scale: [1, 0.3, 3, 0.05], warp: [1, 0, 2, 0.05], contrast: [1, 0.3, 2, 0.05] },
      frag: `
uniform float u_scale, u_warp, u_contrast;
void main() {
  // three rounds of domain warping on low-octave noise: big, soft, liquid shapes
  vec2 p = fragP() * 0.85 * u_scale + vec2(u_seed * 1.37, u_seed * 0.71);
  float t = u_time * 0.07;
  vec2 q = vec2(fbmLo(vec3(p * 0.8, t)), fbmLo(vec3(p * 0.8 + vec2(5.2, 1.3), t)));
  vec2 r = vec2(fbmLo(vec3(p + 0.9 * u_warp * q + vec2(1.7, 9.2), t * 1.2)),
                fbmLo(vec3(p + 0.9 * u_warp * q + vec2(8.3, 2.8), t * 1.2)));
  float f = fbmLo(vec3(p * 0.9 + 0.9 * u_warp * r, t * 0.8));
  float v = 0.5 + u_contrast * (0.85 * f + 0.35 * r.y);
  vec3 L = rampLab(smoothstep(0.0, 1.0, v));
  L.x += 0.03 * smoothstep(0.2, 0.7, length(q));
  gl_FragColor = finishLab(L);
}`,
    },

    liquid: {
      label: 'Liquid dye',
      order: 'any order, 4-6 colours. A wet dye pool the cursor stirs and clicks ripple.',
      quality: 0.5,
      params: {
        scale: [0.7, 0.3, 3, 0.05],
        flow: [1, 0, 2, 0.05],
        mx: [0.5, 0, 1, 0.001],
        my: [0.5, 0, 1, 0.001],
        energy: [0, 0, 1, 0.001],
        rx: [0.5, 0, 1, 0.001],
        ry: [0.5, 0, 1, 0.001],
        age: [99, 0, 4, 0.01],
      },
      frag: `
uniform float u_scale, u_flow, u_mx, u_my, u_energy, u_rx, u_ry, u_age;
void main() {
  vec2 uv = fragUV();
  float asp = aspect();
  vec2 p = vec2(uv.x * asp, uv.y);

  // Cursor: perpendicular swirl + radial press with a tight hand-falloff
  vec2 mo = p - vec2(u_mx * asp, 1.0 - u_my);
  float md = length(mo) + 1e-3;
  float urg = exp(-md * md * 26.0) * u_energy;

  // Click: an expanding damped ring that folds the surface
  vec2 co = p - vec2(u_rx * asp, 1.0 - u_ry);
  float cd = length(co) + 1e-3;
  float d0 = cd - u_age * 1.05;
  float ring = exp(-d0 * d0 * 9.0) * exp(-u_age * 1.2);
  float wobble = ring * sin(cd * 20.0 - u_age * 10.0);

  vec2 force = (vec2(-mo.y, mo.x) * 0.34 + mo * 0.11) * urg
             + (co / cd) * (ring * 0.12 + wobble * 0.11);

  // Wet dye pool: nested domain-warp with a slow downward pour
  float t = u_time * (0.10 + 0.06 * u_flow) + u_seed * 1.7;
  vec2 q = p * 0.85 * u_scale + vec2(u_seed * 1.37, u_seed * 0.71);
  q.y -= u_time * 0.022 * u_flow;
  vec2 w = vec2(fbmLo(vec3(q, t)), fbmLo(vec3(q + vec2(5.2, 1.3), t * 1.1)));
  vec2 dd = q + force * 1.5 + 0.45 * w;
  vec2 r = vec2(fbmLo(vec3(dd + vec2(1.7, 9.2), t * 1.2)),
                fbmLo(vec3(dd + vec2(8.3, 2.8), t * 1.2)));
  float f = fbmLo(vec3(dd + 1.1 * r, t * 0.9));
  float v = 0.5 + 0.58 * f + 0.17 * (r.x + r.y) * 0.5
          + 0.6 * wobble * 0.10 + 0.5 * urg * 0.06;
  v += 0.016 * sin(p.y * 8.0 + p.x * 5.0 + t * 2.6 + w.y * 4.0);

  vec3 L = rampLab(smoothstep(0.04, 0.96, v));
  L = mix(L, vec3(dot(L, vec3(0.299, 0.587, 0.114))), 0.12);
  L.x += 0.012 * urg + 0.05 * ring;
  gl_FragColor = finishLab(L);
}`,
    },

    mesh: {
      label: 'Mesh',
      order: 'one colour per control point (up to 6). Points are [x, y] in 0..1, y from the top.',
      quality: 0.35,
      params: {
        blend: [2.4, 1, 6, 0.1], drift: [1, 0, 3, 0.05], warp: [1, 0, 3, 0.05],
        points: { value: [[0.15, 0.15], [0.85, 0.8], [0.95, 0.35], [0.05, 0.9], [0.5, 0.5], [0.35, 0.65]] },
      },
      frag: `
uniform vec2 u_points[6];
uniform float u_blend, u_drift, u_warp;
void main() {
  vec2 uv = fragUV();
  float asp = aspect();
  vec2 p = vec2(uv.x * asp, uv.y);
  float t = u_time * 0.05;
  p += 0.08 * u_warp * vec2(snoise(vec3(p * 1.3, t)), snoise(vec3(p * 1.3 + 7.7, t)));
  vec3 acc = vec3(0.0);
  float ws = 0.0;
  for (int i = 0; i < 6; i++) {
    if (float(i) > u_count - 0.5) break;
    float fi = float(i);
    vec2 c = vec2(u_points[i].x, 1.0 - u_points[i].y);
    c += 0.12 * u_drift * vec2(sin(t * 2.3 + fi * 1.9 + u_seed), cos(t * 1.7 + fi * 2.7 + u_seed));
    c.x *= asp;
    float w = 1.0 / (pow(length(p - c), u_blend) + 1e-4);
    acc += u_lab[i] * w;
    ws += w;
  }
  gl_FragColor = finishLab(acc / ws);
}`,
    },

    aurora: {
      label: 'Aurora',
      order: 'brightest highlight first → night background last. 4–5 colours.',
      quality: 0.6,
      params: { scale: [1, 0.3, 3, 0.05], fold: [1, 0, 2.5, 0.05], height: [1, 0.3, 2.5, 0.05], intensity: [1, 0.2, 2, 0.05], stars: [0.6, 0, 1, 0.05] },
      frag: `
uniform float u_scale, u_fold, u_height, u_intensity, u_stars;
float curtain(float x, float y, float k, float t) {
  float y0 = 0.38 + 0.14 * k + 0.10 * u_fold * sin(x * 1.1 + t * 0.7 + k * 2.1)
           + 0.08 * u_fold * snoise(vec3(x * 0.6, k * 5.3, t * 0.25));
  float dy = y - y0;
  float rays = 0.5 + 0.5 * snoise(vec3(x * 11.0 * u_scale + k * 13.0, y * 0.5 - t * 0.15, t * 0.35));
  rays = rays * rays * (0.55 + 0.45 * (0.5 + 0.5 * snoise(vec3(x * 2.2 * u_scale + k * 4.0, k, t * 0.2))));
  float up = exp(-max(dy, 0.0) * (3.2 / u_height));
  float base = smoothstep(-0.05, 0.015, dy);
  float line = exp(-abs(dy) * 28.0);
  return base * up * (0.25 + 1.1 * rays) + 0.6 * line * (0.4 + rays);
}
void main() {
  vec2 uv = fragUV();
  float asp = aspect();
  float x = (uv.x - 0.5) * asp;
  float t = u_time * 0.15 + u_seed;
  float I = curtain(x, uv.y, 0.0, t) + 0.55 * curtain(x + 3.1, uv.y, 1.0, t * 0.9);
  I = clamp(I * 0.75 * u_intensity, 0.0, 1.0);
  int li = lastIndex();
  vec3 bg = mix(lab(li), lab(li - 1), 0.22 * (1.0 - uv.y));
  vec3 L = rampLab(1.0 - I) + (bg - lab(li)) * (1.0 - I);
  vec2 sg = uv * vec2(asp, 1.0) * 90.0;
  vec2 cell = floor(sg);
  float sd = length(fract(sg) - hash22(cell + u_seed));
  float star = step(0.93, hash12(cell + 3.7)) * smoothstep(0.09, 0.0, sd);
  star *= smoothstep(0.35, 0.95, uv.y) * (1.0 - I) * u_stars * (0.6 + 0.4 * sin(u_time * 2.0 + hash12(cell) * TAU));
  L.x += star * 0.6;
  gl_FragColor = finishLab(L);
}`,
    },

    silk: {
      label: 'Silk',
      order: 'darkest → lightest (shadow to sheen). 4–6 colours.',
      quality: 0.6,
      params: { scale: [1, 0.4, 2.5, 0.05], folds: [4, 1, 10, 0.5], warp: [1, 0, 2.5, 0.05], sheen: [1, 0, 2, 0.05], angle: [40, -90, 90, 1] },
      frag: `
uniform float u_scale, u_folds, u_warp, u_sheen, u_angle;
float silkH(vec2 p, float t) {
  float a = radians(u_angle);
  vec2 d = vec2(cos(a), sin(a));
  float along = dot(p, d);
  float across = dot(p, vec2(-d.y, d.x));
  float w = u_warp * (0.9 * snoise(vec3(along * 0.7, across * 0.5, t)) + 0.35 * snoise(vec3(p * 1.6, t * 1.4 + 3.0)));
  float u = (across + 0.22 * w) * u_folds * TAU;
  return sin(u) * (0.75 + 0.25 * snoise(vec3(along * 1.1, 2.0, t)));
}
void main() {
  vec2 p = fragP() / u_scale + u_seed;
  float t = u_time * 0.05;
  float e = 0.003;
  float h = silkH(p, t);
  float hx = silkH(p + vec2(e, 0.0), t);
  float hy = silkH(p + vec2(0.0, e), t);
  float relief = 0.035 * 4.0 / max(u_folds, 1.0);
  vec3 N = normalize(vec3(-(hx - h) / e * relief, -(hy - h) / e * relief, 1.0));
  vec3 Ld = normalize(vec3(-0.45, 0.55, 0.7));
  vec3 H = normalize(Ld + vec3(0.0, 0.0, 1.0));
  float diff = clamp((dot(N, Ld) + 0.35) / 1.35, 0.0, 1.0);
  diff = diff * diff * (3.0 - 2.0 * diff);
  float ao = 0.75 + 0.25 * (0.5 + 0.5 * h);
  float nh = max(dot(N, H), 0.0);
  float spec = (pow(nh, 60.0) + 0.3 * pow(nh, 8.0)) * u_sheen;
  float shade = clamp(0.06 + 0.88 * diff * ao, 0.0, 1.0);
  vec3 L = rampLab(shade * 0.92);
  L = mix(L, mix(lab(lastIndex()), LAB_WHITE, 0.5), clamp(spec, 0.0, 1.0));
  gl_FragColor = finishLab(L);
}`,
    },

    sky: {
      label: 'Sky',
      order: 'cloud white first → deepest sky last. 3–5 colours.',
      quality: 0.5,
      params: { scale: [1, 0.3, 3, 0.05], cover: [0.5, 0, 1, 0.02], wind: [1, 0, 4, 0.1], streak: [1, 0, 3, 0.05] },
      frag: `
uniform float u_scale, u_cover, u_wind, u_streak;
void main() {
  vec2 uv = fragUV();
  vec2 p = fragP();
  float t = u_time;
  vec3 skyL = rampLab(mix(0.3, 1.0, smoothstep(-0.1, 1.0, uv.y + 0.12 * sin(uv.x * 2.0 + 1.0))));
  vec2 q = p * vec2(1.0, 1.0 + 1.5 * u_streak) * 0.8 * u_scale + vec2(t * 0.015 * u_wind + u_seed, 0.0);
  vec2 w = vec2(fbmLo(vec3(q * 0.6, t * 0.02)), fbmLo(vec3(q * 0.6 + 4.3, t * 0.02)));
  float n = 0.5 + 0.5 * (0.75 * fbmLo(vec3(q + 0.9 * w, t * 0.03)) + 0.25 * snoise(vec3(q * 3.5 + w, t * 0.05)));
  float c = smoothstep(0.6 - 0.3 * u_cover, 0.95 - 0.25 * u_cover, n);
  vec3 cloud = mix(lab(1), lab(0), smoothstep(0.1, 0.8, c));
  cloud.x += 0.03;
  gl_FragColor = finishLab(mix(skyL, cloud, c));
}`,
    },

    waves: {
      label: 'Waves',
      order: 'top band → bottom band (each colour is one layer). 3–6 colours.',
      quality: 0.5,
      params: { amplitude: [1, 0, 3, 0.05], frequency: [1, 0.2, 3, 0.05], softness: [1, 0, 3, 0.05] },
      frag: `
uniform float u_amplitude, u_frequency, u_softness;
void main() {
  vec2 uv = fragUV();
  float x = uv.x * aspect();
  float y = 1.0 - uv.y;
  float n = u_count;
  float t = u_time + u_seed;
  vec3 L = lab(0);
  for (int k = 1; k < 6; k++) {
    if (float(k) > n - 0.5) break;
    float fk = float(k);
    float b = fk / n
      + 0.045 * u_amplitude * sin(x * (1.2 + 0.5 * fk) * u_frequency + t * 0.25 * (0.6 + 0.25 * fk) + fk * 1.7)
      + 0.03 * u_amplitude * snoise(vec3(x * 0.7 * u_frequency, fk * 3.1, t * 0.06));
    float s = 0.015 + 0.07 * u_softness;
    L = mix(L, lab(k), smoothstep(b - s, b + s, y));
    L.x += 0.025 * exp(-pow((y - b - s) / (0.02 + s), 2.0));
  }
  gl_FragColor = finishLab(L);
}`,
    },

    mist: {
      label: 'Mist',
      order: 'sky first → nearest, darkest ridge last. 4–6 colours.',
      quality: 0.6,
      params: { layers: [5, 2, 6, 1], haze: [1, 0, 2, 0.05], rough: [1, 0.2, 2.5, 0.05], sun: [1, 0, 1.5, 0.05], drift: [1, 0, 4, 0.1] },
      frag: `
uniform float u_layers, u_haze, u_rough, u_sun, u_drift;
float ridge(float x, float k) {
  float r = 0.0, a = 0.55, f = 1.0;
  for (int i = 0; i < 3; i++) {
    float n = 1.0 - abs(snoise(vec3(x * f, k * 3.7, 0.0)));
    r += a * n * n;
    f *= 2.1; a *= 0.45;
  }
  return r;
}
void main() {
  vec2 uv = fragUV();
  float asp = aspect();
  float x = uv.x * asp;
  vec3 L = mix(lab(0), lab(1), 0.45 * (1.0 - uv.y));
  vec2 sp = vec2(0.66 * asp, 0.76);
  float sd = length(vec2(x, uv.y) - sp);
  L = mix(L, LAB_WHITE, u_sun * (smoothstep(0.072, 0.066, sd) * 0.85 + 0.22 * exp(-sd * 9.0)));
  float N = u_layers;
  float aa = 1.5 / u_res.y;
  for (int i = 0; i < 6; i++) {
    if (float(i) > N - 0.5) break;
    float fi = float(i);
    float d = fi / max(N - 1.0, 1.0);
    float base = mix(0.6, 0.1, d);
    float amp = mix(0.07, 0.17, d) * u_rough;
    float xs = x * mix(1.8, 0.9, d) + u_time * 0.012 * u_drift * (0.3 + d) + fi * 17.3 + u_seed;
    float h = base + amp * (ridge(xs, fi) - 0.35);
    vec3 layer = rampLab(mix(0.25, 1.0, d));
    float depth = h - uv.y;
    vec3 misty = mix(layer, lab(0), clamp(0.6 * u_haze * (1.0 - 0.5 * d) * smoothstep(0.0, 0.2, depth), 0.0, 0.95));
    L = mix(L, misty, smoothstep(h + aa, h - aa, uv.y));
  }
  gl_FragColor = finishLab(L);
}`,
    },

    bars: {
      label: 'Bars',
      order: 'background first, then bar colours top → bottom. 4–6 colours.',
      quality: 1,
      params: { bars: [8, 3, 24, 1], gap: [0, 0, 0.6, 0.02], rise: [1, 0, 1, 0.05], wobble: [1, 0, 3, 0.05] },
      frag: `
uniform float u_bars, u_gap, u_rise, u_wobble;
void main() {
  vec2 uv = fragUV();
  float n = floor(u_bars + 0.5);
  float fx = uv.x * n;
  float i = floor(fx);
  float lx = fract(fx);
  float k = (i + 0.5) / n;
  float top = mix(0.92 - 0.62 * u_rise, 0.92, k);
  top += 0.035 * u_wobble * sin(u_time * 0.7 + i * 1.7 + u_seed) + 0.02 * u_wobble * snoise(vec3(i * 0.9, u_seed, u_time * 0.2));
  float aa = 1.5 / u_res.y;
  float m = smoothstep(top + aa, top - aa, uv.y);
  if (u_gap > 0.001) {
    float aax = 1.5 * n / u_res.x;
    float g = u_gap * 0.5;
    m *= smoothstep(g - aax, g + aax, lx) * smoothstep(1.0 - g + aax, 1.0 - g - aax, lx);
  }
  float lastI = u_count - 1.0;
  vec3 bar = rampRangeLab(1.0 - uv.y, 1.0, lastI);
  bar.x *= mix(0.9, 1.06, smoothstep(0.0, 1.0, lx));
  bar.x += 0.05 * smoothstep(top - 0.06, top, uv.y);
  vec3 bg = mix(lab(0), rampRangeLab(1.0 - top, 1.0, lastI), exp(-max(uv.y - top, 0.0) * 14.0) * 0.18);
  gl_FragColor = finishLab(mix(bg, bar, m));
}`,
    },

    prism: {
      label: 'Prism',
      order: 'background (dark) first → brightest glow last. 4–6 colours.',
      quality: 1,
      params: { bars: [11, 3, 40, 1], angle: [0, -180, 180, 1], softness: [1, 0.2, 2, 0.05], spread: [1, 0.3, 2.5, 0.05], valley: [0, 0, 1, 0.05] },
      frag: `
uniform float u_bars, u_angle, u_softness, u_spread, u_valley;
void main() {
  vec2 q = rot(radians(u_angle)) * (fragUV() - 0.5) + 0.5;
  float n = floor(u_bars + 0.5);
  float i = floor(q.x * n);
  float cx = (i + 0.5) / n;
  float drift = 0.06 * sin(u_time * 0.15 + u_seed);
  float bell = exp(-pow((cx - 0.5 - drift) / (0.24 * u_spread), 2.0));
  float env = mix(bell, 1.0 - 0.75 * bell, u_valley);
  float h = mix(0.22, 0.95, env) + 0.025 * sin(u_time * 0.5 + i * 1.3 + u_seed);
  float v = 1.0 - q.y / h;
  float I = smoothstep(0.0, 0.85 * u_softness, v);
  I = pow(I, 0.9) * mix(0.7, 1.0, env);
  gl_FragColor = finishLab(rampLab(I));
}`,
    },

    rings: {
      label: 'Rings',
      order: 'inner → outer. The outermost colour (mixed with white) lights the ring edges.',
      quality: 1,
      params: { rings: [9, 2, 30, 1], cx: [-0.9, -1.5, 1.5, 0.05], cy: [-0.75, -1.5, 1.5, 0.05], glow: [1, 0, 2, 0.05], depth: [1, 0, 3, 0.05] },
      frag: `
uniform float u_rings, u_cx, u_cy, u_glow, u_depth;
void main() {
  vec2 p = fragP();
  float r = length(p - vec2(u_cx, u_cy));
  float k = u_rings * 0.5;
  float s = r * k - u_time * 0.04;
  float f = fract(s);
  vec3 L = rampLab(clamp(r * 0.45, 0.0, 1.0));
  L.x += (f - 0.5) * 0.07 * u_depth;
  float spx = k / min(u_res.x, u_res.y);
  float rim = (smoothstep(1.0 - 2.5 * spx, 1.0, f) + exp(-(1.0 - f) * 9.0) * 0.25) * u_glow;
  L = mix(L, mix(lab(lastIndex()), LAB_WHITE, 0.55), clamp(rim, 0.0, 1.0) * 0.85);
  gl_FragColor = finishLab(L);
}`,
    },

    glow: {
      label: 'Glow',
      order: 'background first, then body shadow → lit side; last colour is the rim light.',
      quality: 0.75,
      params: { blobs: [3, 1, 3, 1], size: [1, 0.4, 2, 0.05], rim: [1, 0, 2, 0.05], light: [60, -180, 180, 1], crescent: [0, 0, 1, 1], x: [0, -1, 1, 0.01], y: [0, -1, 1, 0.01] },
      frag: `
uniform float u_blobs, u_size, u_rim, u_light, u_crescent, u_x, u_y;
vec3 blobDef(int i) {
  if (i == 0) return vec3(0.32, 0.28, 0.36);
  if (i == 1) return vec3(0.18, -0.42, 0.42);
  return vec3(-0.3, 0.22, 0.12);
}
void main() {
  vec2 p = fragP();
  float asp = aspect();
  float t = u_time * 0.12 + u_seed;
  vec2 ld = vec2(cos(radians(u_light)), sin(radians(u_light)));
  vec3 L = mix(lab(0), lab(1), 0.15 * (1.0 - fragUV().y));
  float aa = 2.0 / min(u_res.x, u_res.y);
  vec3 hi = lab(lastIndex());
  hi.x = min(hi.x + 0.08, 1.0);
  for (int i = 0; i < 3; i++) {
    if (float(i) > u_blobs - 0.5) break;
    float fi = float(i);
    vec3 b = blobDef(i);
    vec2 c = vec2((b.x + u_x) * max(asp, 1.0), (b.y + u_y) * max(1.0 / asp, 1.0));
    c += 0.03 * vec2(sin(t + fi * 2.0), cos(t * 0.8 + fi * 1.3));
    float R = b.z * u_size;
    vec2 dv = p - c;
    float a = atan(dv.y, dv.x);
    float d = length(dv) - R * (1.0 + 0.035 * snoise(vec3(cos(a) * 0.9 + fi * 7.0, sin(a) * 0.9, t)));
    if (u_crescent > 0.5) d = max(d, -(length(p - (c - ld * R * 0.45)) - R * 0.95));
    float facing = dot(normalize(dv), ld);
    float inside = smoothstep(aa, -aa, d);
    vec3 body = rampRangeLab(0.5 + 0.5 * dot(dv, ld) / R, 1.0, u_count - 1.0);
    float lit = smoothstep(-0.2, 0.8, facing);
    float rim = exp(-abs(d) / (0.004 + 0.006 * u_rim)) * lit;
    float inner = exp(d / (0.05 * R + 0.02)) * lit * inside * 0.6;
    float halo = exp(-max(d, 0.0) * 9.0) * lit * 0.25 * (1.0 - inside);
    L = mix(L, body, inside);
    L = mix(L, hi, clamp((rim + inner + halo) * u_rim, 0.0, 1.0));
  }
  gl_FragColor = finishLab(L);
}`,
    },

    stripes: {
      label: 'Stripes',
      order: 'top → bottom; the ramp is stepped into soft bands. 3–6 colours.',
      quality: 0.5,
      params: { bands: [7, 2, 24, 1], softness: [0.6, 0, 1, 0.02], wave: [1, 0, 3, 0.05], angle: [0, -90, 90, 1] },
      frag: `
uniform float u_bands, u_softness, u_wave, u_angle;
void main() {
  vec2 q = rot(radians(u_angle)) * (fragUV() - 0.5) + 0.5;
  float t = u_time + u_seed;
  float y = 1.0 - q.y
    + 0.04 * u_wave * sin(q.x * 5.0 + t * 0.3)
    + 0.03 * u_wave * snoise(vec3(q * 2.0, t * 0.05));
  float qn = clamp(y, 0.0, 1.0) * u_bands;
  float f = fract(qn);
  float w = 0.02 + 0.47 * u_softness;
  float tt = (floor(qn) + smoothstep(0.5 - w, 0.5 + w, f)) / u_bands;
  vec3 L = rampLab(tt);
  L.x += 0.02 * (f - 0.5);
  gl_FragColor = finishLab(L);
}`,
    },

    forms: {
      label: 'Forms',
      order: 'background first, then shape centre → shape edge. 4–6 colours.',
      quality: 0.6,
      params: {
        shape: [0, 0, 5, 1], size: [1, 0.3, 2.5, 0.05], blur: [1, 0, 3, 0.05], halo: [1, 0, 2, 0.05],
        x: [0.5, 0, 1, 0.01], y: [0.5, 0, 1, 0.01], rotate: [0, -180, 180, 1],
      },
      frag: `
uniform float u_shape, u_size, u_blur, u_halo, u_x, u_y, u_rotate;
float sdHeart(vec2 p) {
  p.x = abs(p.x);
  if (p.y + p.x > 1.0) return length(p - vec2(0.25, 0.75)) - 0.35355339;
  vec2 a = p - vec2(0.0, 1.0);
  vec2 b = p - 0.5 * max(p.x + p.y, 0.0);
  return sqrt(min(dot(a, a), dot(b, b))) * sign(p.x - p.y);
}
void main() {
  vec2 p = fragP();
  float asp = aspect();
  float t = u_time * 0.1 + u_seed;
  vec2 c = vec2((u_x - 0.5) * max(asp, 1.0), (0.5 - u_y) * max(1.0 / asp, 1.0));
  vec2 q = rot(radians(u_rotate) + 0.06 * sin(t)) * (p - c) / (u_size * (1.0 + 0.02 * sin(t * 1.7)));
  float r = length(q);
  float a = atan(q.y, q.x);
  int s = int(u_shape + 0.5);
  float d;
  float g;
  if (s == 2) {
    d = sdHeart(q * 1.25 + vec2(0.0, 0.55)) / 1.25;
    // radial fill (the SDF interior has creases that would show through)
    g = clamp(length(q * vec2(1.0, 1.1) - vec2(0.0, 0.04)) / 0.46, 0.0, 1.0);
  } else {
    float R;
    if (s == 0) R = 0.40 * (1.0 + 0.13 * cos(12.0 * a));
    else if (s == 1) R = 0.46 * (0.32 + 0.68 * pow(abs(cos(2.0 * a + 0.35 * sin(2.0 * a))), 0.7));
    else if (s == 3) R = 0.44 * (0.5 + 0.5 * pow(abs(cos(1.5 * a)), 0.5));
    else if (s == 4) R = 0.42 * (1.0 + 0.09 * snoise(vec3(cos(a), sin(a), t * 0.6)));
    else R = 0.42 * (0.62 + 0.38 * pow(0.5 + 0.5 * cos(5.0 * a), 1.5));
    d = r - R;
    g = clamp(r / R, 0.0, 1.0);
  }
  float b = 0.004 + 0.06 * u_blur;
  float m = smoothstep(b, -b, d);
  vec3 L = lab(0);
  L = mix(L, lab(lastIndex() - 1), exp(-max(d, 0.0) * 10.0 / (0.4 + u_halo)) * 0.3 * u_halo);
  L = mix(L, rampRangeLab(g, 1.0, u_count - 1.0), m);
  gl_FragColor = finishLab(L);
}`,
    },

    watercolor: {
      label: 'Watercolour',
      order: 'paper first, then one pigment per remaining colour. 3–6 colours.',
      quality: 0.6,
      params: { scale: [1, 0.4, 2.5, 0.05], wetness: [0.6, 0, 1.5, 0.05], edges: [1, 0, 2, 0.05], granulation: [1, 0, 2, 0.05] },
      frag: `
uniform float u_scale, u_wetness, u_edges, u_granulation;
void main() {
  vec2 p = fragP();
  float t = u_time * 0.025;
  float asp = max(aspect(), 1.0);
  vec2 w = 0.16 * vec2(fbmLo(vec3(p * 1.6, t)), fbmLo(vec3(p * 1.6 + 7.3, t)));
  vec2 wf = 0.012 * vec2(snoise(vec3(p * 7.0, t)), snoise(vec3(p * 7.0 + 3.1, t)));
  float tooth = 0.6 * snoise(vec3(p * 240.0, 1.0)) + 0.4 * snoise(vec3(p * 90.0, 2.0));
  vec3 paper = toLinear(u_rgb[0]);
  vec3 absorb = vec3(0.0);
  float washes = u_count - 1.0;
  for (int i = 1; i < 6; i++) {
    if (float(i) > u_count - 0.5) break;
    float fi = float(i);
    vec2 h = hash22(vec2(fi * 7.13 + u_seed, fi * 3.71));
    // washes laid along a loose diagonal so they overlap at the edges, not on top of each other
    float k = (fi - 0.5) / washes - 0.5;
    vec2 c = vec2(k * asp * 1.1 + (h.x - 0.5) * 0.15, -k * 0.35 + (h.y - 0.5) * 0.45);
    c += 0.03 * vec2(sin(t * 3.0 + fi), cos(t * 2.0 + fi * 1.3));
    float rad = (0.22 + 0.08 * h.y) * u_scale * mix(1.0, 1.6, step(washes, 2.5));
    vec2 q = (rot(h.x * 3.0) * (p + w + wf - c)) / vec2(rad * 1.3, rad);
    float d = length(q);
    float feather = 0.04 + 0.22 * u_wetness;
    float m = 1.0 - smoothstep(1.0 - feather, 1.0 + feather, d);
    float uneven = 0.5 + 0.35 * (0.5 + 0.5 * fbmLo(vec3(p * 2.5 + fi * 5.0, t))) - 0.15 * d;
    float edge = exp(-pow((d - 0.98 + feather * 0.3) / (0.02 + 0.06 * u_wetness), 2.0)) * 0.5 * u_edges;
    float gran = max(0.2, 1.0 + tooth * 0.45 * u_granulation);
    vec3 pigment = -log(clamp(toLinear(u_rgb[i]) / max(paper, vec3(0.01)), 0.02, 1.0));
    absorb += pigment * m * (uneven + edge) * gran * 0.85;
  }
  vec3 c = paper * exp(-absorb);
  c *= 1.0 + tooth * 0.025 * u_granulation;
  gl_FragColor = finish(toSRGB(c));
}`,
    },

    swirl: {
      label: 'Swirl',
      order: 'lightest → darkest across the twist. 3–6 colours.',
      quality: 0.5,
      params: { twist: [1, -3, 3, 0.05], scale: [1, 0.4, 2.5, 0.05], cx: [0.25, -1, 1, 0.05], cy: [-0.05, -1, 1, 0.05] },
      frag: `
uniform float u_twist, u_scale, u_cx, u_cy;
void main() {
  vec2 p = fragP();
  float t = u_time * 0.05 + u_seed;
  vec2 c = vec2(u_cx, u_cy) + 0.05 * vec2(sin(t * 1.3), cos(t));
  vec2 d = (p - c) / u_scale;
  float r = length(d);
  d = rot(u_twist * 4.0 * exp(-r * r * 2.2) + t * 0.6) * d;
  float v = 0.5 + 0.95 * (d.x * 0.85 - d.y * 0.25) + 0.1 * fbmLo(vec3(d * 1.4, t * 0.7));
  gl_FragColor = finishLab(rampLab(clamp(v, 0.0, 1.0)));
}`,
    },
  };

  // ---------------------------------------------------------------------------
  // Presets — colourways modelled on the looks in feralui.dev's gradient gallery
  // ---------------------------------------------------------------------------
  const PRESETS = {
    'fluid':            { style: 'flow', colors: ['#F6F9FF', '#9BE0E8', '#C4B5F7', '#F8B8D9'], params: { scale: 0.9, warp: 1 } },
    'iridescent-cloud': { style: 'flow', colors: ['#EAF4FC', '#1E50A2', '#895B8A', '#F09199'], params: { scale: 0.8, warp: 1.1 } },
    'lagoon':           { style: 'flow', colors: ['#E8FAF7', '#7FD6D3', '#2F7FA8', '#1F3E66'] },
    'solar-flare':      { style: 'flow', colors: ['#FFE9B8', '#F8A65B', '#D9503B', '#6A1F4B'], params: { contrast: 1.15 } },
    'orchid':           { style: 'flow', colors: ['#F5EEFF', '#C9A7F0', '#7B4FC9', '#2A1A5E'], params: { warp: 1.3 } },
    'soft-signal':      { style: 'mesh', colors: ['#EAF4FC', '#B28FCE', '#F4B3C2', '#A0D8EF'], params: { points: [[0.15, 0.15], [0.85, 0.8], [0.95, 0.35], [0.05, 0.9]] } },
    'any-words':        { style: 'mesh', colors: ['#F3F1FB', '#C7B6EC', '#F2B5C8', '#9FD3E6', '#FBE7D9'], params: { points: [[0.2, 0.1], [0.8, 0.25], [0.75, 0.75], [0.15, 0.85], [0.5, 0.5]], blend: 2 } },
    'night-swim':       { style: 'aurora', colors: ['#EDFFEB', '#5FE896', '#2E7A6A', '#132B45'] },
    'violet-veil':      { style: 'aurora', colors: ['#FCEBFF', '#D07BF0', '#5B3A9E', '#120C2E'], params: { fold: 1.4 } },
    'amethyst':         { style: 'silk', colors: ['#2E1152', '#5B2699', '#8A46D6', '#AE78EA', '#CFA9F5', '#EDE0FD'], params: { angle: 34, folds: 3.5 } },
    'pearl-silk':       { style: 'silk', colors: ['#3E5868', '#6F8FA0', '#A9C3CF', '#D6E6EC', '#F4FAFC'], params: { angle: -28, folds: 3, sheen: 1.3 } },
    'blue-sky':         { style: 'sky', colors: ['#E6F2FF', '#B3D9FF', '#80B3FF', '#6699E6'] },
    'start-here':       { style: 'sky', colors: ['#F2F8FF', '#B9D6F7', '#6E9BEB', '#2F62D8'], params: { streak: 2.2, cover: 0.6 } },
    'tidal':            { style: 'waves', colors: ['#FEF4F0', '#FBD9D3', '#EFA6AE', '#A9678F', '#54395F'] },
    'field-notes':      { style: 'mist', colors: ['#F2F7ED', '#DEEBD5', '#B6CFB1', '#88AB8D', '#5C8267', '#375343'] },
    'after-hours':      { style: 'bars', colors: ['#05060F', '#16249E', '#4C5BE0', '#B387E8', '#F86AC8', '#FF4E63'], params: { bars: 8 } },
    'citron':           { style: 'prism', colors: ['#26483D', '#557D57', '#A4B963', '#D6D998', '#F2EDCC'], params: { bars: 11 } },
    'glacier':          { style: 'prism', colors: ['#183F60', '#277EA3', '#65BED0', '#B9E3DF', '#EAF4E6'], params: { bars: 10, angle: -90, valley: 1 } },
    'ambient':          { style: 'rings', colors: ['#04122B', '#0B3B87', '#2170D5', '#4C95EA', '#A9D2FA'] },
    'edge':             { style: 'glow', colors: ['#0E2A27', '#163D37', '#2E7D6B', '#5FD3A0', '#E3F27A'], params: { blobs: 2, light: 120 } },
    'moons':            { style: 'glow', colors: ['#0B1530', '#14204A', '#2D4C9A', '#8FB0EA', '#E7EEFF'], params: { blobs: 1, crescent: 1, size: 1.05, light: 20, x: -0.06, y: -0.3 } },
    'gather':           { style: 'stripes', colors: ['#FEF4F4', '#F4B3C2', '#F09199', '#895B8A'], params: { bands: 8 } },
    'solstice':         { style: 'forms', colors: ['#FBF0DC', '#FFEBB0', '#FFC855', '#F28A30', '#D9503B'], params: { shape: 0, x: 0.63, y: 0.47, size: 1.35, rotate: 8 } },
    'petal':            { style: 'forms', colors: ['#FBEEF1', '#FFD6C2', '#F79C97', '#E1679A', '#7E3D9A'], params: { shape: 1, x: 0.66, y: 0.54, size: 1.45, rotate: -32 } },
    'with-love':        { style: 'forms', colors: ['#FFF6F1', '#FFDBC0', '#FF9E7E', '#EE5A82', '#873DBC'], params: { shape: 2, x: 0.6, y: 0.56, size: 1.35, rotate: -10 } },
    'celtics':          { style: 'forms', colors: ['#F3F8EE', '#C9E4BF', '#7DC277', '#2F8A3E', '#1E5E2E'], params: { shape: 3, x: 0.22, y: 0.32, size: 1.5, blur: 2.2, rotate: 15 } },
    'bloom':            { style: 'forms', colors: ['#420B32', '#FFB08A', '#FF6B6B', '#E0245A', '#7A1240'], params: { shape: 5, x: 0.68, y: 0.55, size: 1.1, rotate: 12, blur: 0.6 } },
    'verdant':          { style: 'swirl', colors: ['#F8F6EC', '#E5E8D2', '#C3D3A8', '#94B37D', '#5F8A5C', '#2F5443'] },
    'paper-garden':     { style: 'watercolor', colors: ['#FBF8F1', '#7FA7D9', '#E39AB0', '#F3C76B', '#7CC2A4'] },
  };

  // CSS-only colourways (no canvas) — see cssBackdrop()
  const CSS_PRESETS = {
    'slow-days':   { kind: 'retro',  colors: ['#FFF1CF', '#F5B1AA', '#F09199', '#B28FCE'], grain: 0.35 },
    'rosa':        { kind: 'ios',    colors: ['#A0D8EF', '#EAF4FC', '#F4B3C2', '#FDEFF2'] },
    'atelier':     { kind: 'linear', colors: ['#ED6D3D', '#FFF1CF'], grain: 0.18 },
    'soft-signal': { kind: 'mesh',   colors: ['#EAF4FC', '#B28FCE', '#F4B3C2', '#A0D8EF'] },
    'halo':        { kind: 'conic',  colors: ['#F6D5F7', '#FBE9D7', '#C6E6F5', '#D9CCF4'] },
  };

  // ---------------------------------------------------------------------------
  // Colour helpers (CPU)
  // ---------------------------------------------------------------------------
  let probeCtx = null;
  function parseColor(input) {
    if (Array.isArray(input)) return input.map((v) => (v > 1 ? v / 255 : v)).slice(0, 3);
    const s = String(input).trim();
    const hex = s.match(/^#([0-9a-f]{3,8})$/i);
    if (hex) {
      let h = hex[1];
      if (h.length <= 4) h = h.split('').map((ch) => ch + ch).join('');
      return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
    }
    // anything else CSS understands (rgb(), hsl(), oklch(), named colours)
    if (!probeCtx) {
      const c = document.createElement('canvas');
      c.width = c.height = 1;
      probeCtx = c.getContext('2d', { willReadFrequently: true });
    }
    probeCtx.clearRect(0, 0, 1, 1);
    probeCtx.fillStyle = '#000';
    probeCtx.fillStyle = s;
    probeCtx.fillRect(0, 0, 1, 1);
    const d = probeCtx.getImageData(0, 0, 1, 1).data;
    return [d[0] / 255, d[1] / 255, d[2] / 255];
  }
  const toLin = (c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  function srgbToOklab([r, g, b]) {
    r = toLin(r); g = toLin(g); b = toLin(b);
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [
      0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
      1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
      0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
    ];
  }

  // ---------------------------------------------------------------------------
  // Grain overlay: 256² tile of triangular-distributed noise, generated once.
  // Encoded as white/black speckles whose *alpha* carries the noise, so it is
  // composited with plain alpha blending. (A grey tile + mix-blend-mode:overlay
  // looks similar but forces the browser to re-blend the whole area every frame
  // over an animating canvas, which costs Safari a lot of frame rate.)
  // ---------------------------------------------------------------------------
  let grainCache = null;
  function grainURL() {
    if (grainCache) return grainCache;
    const N = 256;
    const c = document.createElement('canvas');
    c.width = c.height = N;
    const ctx = c.getContext('2d');
    const img = ctx.createImageData(N, N);
    for (let i = 0; i < img.data.length; i += 4) {
      const d = (Math.random() + Math.random()) / 2 - 0.5;
      const v = d > 0 ? 255 : 0;
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
      // dark specks weighted lower: overlay grain barely darkens light colours
      img.data[i + 3] = Math.round(Math.min(1, Math.abs(d) * (d > 0 ? 1.1 : 0.7)) * 255);
    }
    ctx.putImageData(img, 0, 0);
    grainCache = c.toDataURL('image/png');
    return grainCache;
  }

  // ---------------------------------------------------------------------------
  // CSS-only backdrops (static; also the no-WebGL fallback)
  // returns a value for the `background` shorthand
  // ---------------------------------------------------------------------------
  const MESH_SPOTS = [[15, 12], [85, 16], [24, 88], [84, 84], [50, 50], [60, 30]];
  function cssBackdrop(kind, colors, opts = {}) {
    if (typeof kind === 'string' && CSS_PRESETS[kind] && !colors) {
      ({ kind, colors } = CSS_PRESETS[kind]);
    }
    const cs = colors.map(String);
    const angle = opts.angle ?? 180;
    const stops = (list) => list.map((c, i) => `${c} ${((i / Math.max(list.length - 1, 1)) * 100).toFixed(1)}%`).join(', ');
    switch (kind) {
      case 'linear':
        return `linear-gradient(${angle}deg in oklab, ${stops(cs)})`;
      case 'ios':
        return `radial-gradient(90% 70% at 12% 8%, rgba(255,255,255,0.28), rgba(255,255,255,0) 60%), linear-gradient(${opts.angle ?? 135}deg in oklab, ${stops(cs)})`;
      case 'conic':
        return `conic-gradient(from ${opts.angle ?? 210}deg at 50% 50% in oklab, ${stops([...cs, cs[0]])})`;
      case 'retro': {
        const [base, ...rest] = cs;
        const spots = [[18, 22], [82, 30], [30, 85], [78, 82], [50, 50]];
        return rest.map((c, i) => `radial-gradient(70% 60% at ${spots[i % 5][0]}% ${spots[i % 5][1]}% in oklab, ${c}, transparent 72%)`).join(', ') + `, ${base}`;
      }
      case 'mesh':
      default: {
        const [base, ...rest] = cs;
        const pts = opts.points || MESH_SPOTS;
        const layers = rest.map((c, i) => {
          const [x, y] = pts[i % pts.length];
          const sz = 80 + (i % 3) * 10;
          return `radial-gradient(${sz}% ${sz - 10}% at ${x}% ${y}% in oklab, ${c}, transparent 58%)`;
        });
        return `${layers.join(', ')}, ${base}`;
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Renderers
  //
  // direct (default): each backdrop owns a WebGL context on its visible canvas
  //   and draws straight into it. No copies, which is the fast path everywhere and
  //   the only fast path in Safari.
  // shared (overflow): browsers cap live WebGL contexts (~16 per page), so once
  //   MAX_DIRECT backdrops exist, further ones render in one hidden shared context
  //   and are copied into a 2D canvas. Cheap in Chromium, slower in Safari, so it
  //   is only used for galleries with many simultaneous backdrops.
  // ---------------------------------------------------------------------------
  const MAX_DIRECT = 12;
  let directCount = 0;
  let sharedRenderer = null; // null = not yet created, false = unavailable
  const instances = new Set();

  function getShared() {
    if (sharedRenderer === false) return null;
    if (sharedRenderer && !sharedRenderer.lost) return sharedRenderer;
    try {
      sharedRenderer = new Renderer(null);
    } catch (err) {
      console.warn('[gradient-backdrops] WebGL unavailable, using CSS fallback.', err);
      sharedRenderer = false;
      return null;
    }
    return sharedRenderer;
  }

  class Renderer {
    constructor(target) {
      this.shared = !target;
      const canvas = target || document.createElement('canvas');
      if (this.shared) canvas.width = canvas.height = 256;
      const gl = canvas.getContext('webgl', {
        alpha: false, antialias: false, depth: false, stencil: false,
        premultipliedAlpha: false, preserveDrawingBuffer: this.shared,
      });
      if (!gl) throw new Error('webgl context');
      this.canvas = canvas;
      this.gl = gl;
      this.lost = false;
      this.init();
      canvas.addEventListener('webglcontextlost', (e) => {
        e.preventDefault();
        this.lost = true;
      });
      canvas.addEventListener('webglcontextrestored', () => {
        this.init();
        this.lost = false;
        instances.forEach((i) => (i.dirty = true));
        schedule();
      });
    }

    init() {
      const { gl } = this;
      this.programs = new Map();
      this.buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
      gl.enableVertexAttribArray(0);
      gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    }

    program(name) {
      if (this.programs.has(name)) return this.programs.get(name);
      const { gl } = this;
      const style = STYLES[name];
      let entry = null;
      try {
        const prog = gl.createProgram();
        for (const [type, src] of [
          [gl.VERTEX_SHADER, 'attribute vec2 a_pos;void main(){gl_Position=vec4(a_pos,0.0,1.0);}'],
          [gl.FRAGMENT_SHADER, PRELUDE + style.frag],
        ]) {
          const sh = gl.createShader(type);
          gl.shaderSource(sh, src);
          gl.compileShader(sh);
          if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh));
          gl.attachShader(prog, sh);
          gl.deleteShader(sh);
        }
        gl.bindAttribLocation(prog, 0, 'a_pos');
        gl.linkProgram(prog);
        if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
        entry = { prog, locs: new Map() };
      } catch (err) {
        console.error(`[gradient-backdrops] style "${name}" failed to compile:\n`, err.message || err);
      }
      this.programs.set(name, entry);
      return entry;
    }

    loc(entry, name) {
      if (!entry.locs.has(name)) entry.locs.set(name, this.gl.getUniformLocation(entry.prog, name));
      return entry.locs.get(name);
    }

    // returns false only when the style can't compile
    draw(inst) {
      const { gl, canvas } = this;
      if (this.lost) return true;
      const w = inst.canvas.width, h = inst.canvas.height;
      if (!w || !h) return true;
      if (this.shared && (canvas.width < w || canvas.height < h)) {
        canvas.width = Math.max(canvas.width, Math.ceil(w / 256) * 256);
        canvas.height = Math.max(canvas.height, Math.ceil(h / 256) * 256);
      }
      const entry = this.program(inst.opts.style);
      if (!entry) return false;
      gl.useProgram(entry.prog);
      gl.viewport(0, 0, w, h);
      if (this.shared) {
        gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
        gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
      }
      const L = (n) => this.loc(entry, n);
      gl.uniform2f(L('u_res'), w, h);
      gl.uniform1f(L('u_time'), inst.time);
      gl.uniform1f(L('u_seed'), inst.opts.seed);
      gl.uniform1f(L('u_count'), inst.palette.count);
      gl.uniform3fv(L('u_rgb[0]'), inst.palette.rgb);
      gl.uniform3fv(L('u_lab[0]'), inst.palette.lab);
      for (const [key, val] of Object.entries(inst.params)) {
        if (typeof val === 'number' || typeof val === 'boolean') {
          gl.uniform1f(L('u_' + key), +val);
        } else if (Array.isArray(val) && Array.isArray(val[0])) {
          const dim = val[0].length;
          const flat = new Float32Array(6 * dim);
          val.slice(0, 6).forEach((v, i) => flat.set(v.slice(0, dim), i * dim));
          gl[`uniform${dim}fv`](L(`u_${key}[0]`), flat);
        } else if (Array.isArray(val)) {
          gl[`uniform${val.length}fv`](L('u_' + key), new Float32Array(val));
        }
      }
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      if (this.shared) inst.ctx.drawImage(canvas, 0, canvas.height - h, w, h, 0, 0, w, h);
      return true;
    }

    release() {
      const ext = this.gl.getExtension('WEBGL_lose_context');
      if (ext) ext.loseContext();
    }
  }

  // ---------------------------------------------------------------------------
  // Frame loop: one rAF drives every visible, playing backdrop
  // ---------------------------------------------------------------------------
  let raf = 0;
  let lastNow = 0;
  function tick(now) {
    raf = 0;
    const dt = lastNow ? Math.min((now - lastNow) / 1000, 0.1) : 0;
    lastNow = now;
    let animating = false;
    for (const inst of instances) {
      if (!inst.visible || inst.fallbackApplied) continue;
      if (inst.isPlaying()) {
        inst.time += dt * inst.opts.speed;
        inst.dirty = true;
        animating = true;
      }
      if (inst.dirty) inst._draw();
    }
    if (animating) schedule();
    else lastNow = 0;
  }
  function schedule() {
    if (!raf && typeof requestAnimationFrame !== 'undefined') raf = requestAnimationFrame(tick);
  }

  const reducedMotion = typeof matchMedia !== 'undefined' ? matchMedia('(prefers-reduced-motion: reduce)') : null;
  if (reducedMotion && reducedMotion.addEventListener) {
    reducedMotion.addEventListener('change', () => { instances.forEach((i) => (i.dirty = true)); schedule(); });
  }

  // ---------------------------------------------------------------------------
  // Public: createBackdrop(target, options)
  // ---------------------------------------------------------------------------
  const DEFAULTS = {
    style: 'flow', colors: null, params: {}, speed: 1, grain: 0, seed: 0,
    animate: true, respectReducedMotion: true, quality: null, maxPixels: 2.4e6, time: 0,
    mode: 'auto',
  };

  function resolve(options) {
    const preset = options.preset && PRESETS[options.preset];
    if (options.preset && !preset) console.warn(`[gradient-backdrops] unknown preset "${options.preset}"`);
    const merged = { ...DEFAULTS, ...(preset || {}), ...options };
    merged.params = { ...((preset && preset.params) || {}), ...(options.params || {}) };
    if (!STYLES[merged.style]) {
      console.warn(`[gradient-backdrops] unknown style "${merged.style}", using flow`);
      merged.style = 'flow';
    }
    if (!merged.colors || merged.colors.length < 2) merged.colors = PRESETS.fluid.colors;
    return merged;
  }

  function paramDefaults(styleName) {
    const out = {};
    for (const [k, spec] of Object.entries(STYLES[styleName].params)) out[k] = Array.isArray(spec) ? spec[0] : spec.value;
    return out;
  }

  function createBackdrop(target, options = {}) {
    const el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) throw new Error(`[gradient-backdrops] target not found: ${target}`);

    let canvas;
    let grainEl = null;
    const owned = el.tagName !== 'CANVAS';
    if (owned) {
      canvas = document.createElement('canvas');
      canvas.setAttribute('aria-hidden', 'true');
      canvas.className = 'gb-canvas';
      Object.assign(canvas.style, {
        position: 'absolute', inset: '0', width: '100%', height: '100%',
        display: 'block', pointerEvents: 'none', zIndex: '-1',
      });
      const cs = getComputedStyle(el);
      if (cs.position === 'static') el.style.position = 'relative';
      if (cs.isolation !== 'isolate') el.style.isolation = 'isolate';
      el.prepend(canvas);
      grainEl = document.createElement('div');
      grainEl.className = 'gb-grain';
      grainEl.setAttribute('aria-hidden', 'true');
      Object.assign(grainEl.style, {
        position: 'absolute', inset: '0', pointerEvents: 'none', zIndex: '-1',
        backgroundSize: '256px 256px', opacity: '0',
      });
      canvas.after(grainEl);
    } else {
      canvas = el;
    }

    // Own a WebGL context when the budget allows; otherwise share one and copy.
    const mode = options.mode || DEFAULTS.mode;
    let direct = null;
    if (mode === 'direct' || (mode === 'auto' && directCount < MAX_DIRECT)) {
      try { direct = new Renderer(canvas); directCount++; } catch (err) { direct = null; }
    }

    const inst = {
      el, canvas,
      // shared mode only: transparent until the first frame lands
      ctx: direct ? null : canvas.getContext('2d'),
      renderer: direct,
      opts: null, params: null, palette: null,
      time: 0, visible: true, dirty: true, paused: false, fallbackApplied: false, ready: false,

      get mode() { return this.renderer ? 'direct' : 'shared'; },
      isPlaying() {
        if (!this.opts.animate || this.paused) return false;
        if (this.opts.respectReducedMotion && reducedMotion && reducedMotion.matches) return false;
        return true;
      },
      set(next = {}) {
        const prevStyle = this.opts && this.opts.style;
        const base = this.opts ? { ...this.opts, preset: undefined } : {};
        if (next.preset) {
          this.opts = resolve({ ...next });
        } else {
          this.opts = resolve({ ...base, ...next, params: { ...(base.params || {}), ...(next.params || {}) } });
        }
        if (prevStyle && prevStyle !== this.opts.style && !next.params) this.opts.params = {};
        this.params = { ...paramDefaults(this.opts.style), ...this.opts.params };
        const cols = this.opts.colors.slice(0, 6).map(parseColor);
        const rgb = new Float32Array(18), lab = new Float32Array(18);
        cols.forEach((c, i) => { rgb.set(c, i * 3); lab.set(srgbToOklab(c), i * 3); });
        this.palette = { count: cols.length, rgb, lab };
        if ('time' in next) this.time = next.time;
        if (this.fallbackApplied && prevStyle && prevStyle !== this.opts.style && (this.renderer || getShared())) {
          // switched away from a style that failed to compile: give the shader another go
          this.fallbackApplied = false;
          canvas.style.display = 'block';
          el.style.background = this._prevBackground || '';
        }
        if (grainEl) {
          if (this.opts.grain > 0) grainEl.style.backgroundImage = `url(${grainURL()})`;
          grainEl.style.opacity = String(Math.min(1, this.opts.grain));
        }
        this.resize();
        this.dirty = true;
        schedule();
        return this;
      },
      resize() {
        const rect = (owned ? el : canvas).getBoundingClientRect();
        const dpr = Math.min(global.devicePixelRatio || 1, 2);
        const q = this.opts.quality ?? STYLES[this.opts.style].quality;
        let w = Math.max(1, Math.round(rect.width * dpr * q));
        let h = Math.max(1, Math.round(rect.height * dpr * q));
        const over = Math.sqrt((w * h) / this.opts.maxPixels);
        if (over > 1) { w = Math.round(w / over); h = Math.round(h / over); }
        if (canvas.width !== w || canvas.height !== h) {
          canvas.width = w;
          canvas.height = h;
          // resizing clears a WebGL canvas; repaint now so it never flashes black
          if (this.ready && this.renderer) this._draw();
          this.dirty = true;
          schedule();
        }
      },
      _draw() {
        this.dirty = false;
        const r = this.renderer || getShared();
        if (!r) { this._fallback(); return; }
        if (!r.draw(this)) this._fallback();
      },
      play() { this.paused = false; schedule(); return this; },
      pause() { this.paused = true; return this; },
      toggle() { this.paused = !this.paused; schedule(); return this; },
      render() { this.dirty = true; schedule(); return this; },
      snapshot(type = 'image/png', quality) {
        this._draw();
        return canvas.toDataURL(type, quality);
      },
      _fallback() {
        if (this.fallbackApplied || !owned) return;
        this.fallbackApplied = true;
        this._prevBackground = el.style.background;
        canvas.style.display = 'none';
        el.style.background = cssBackdrop('mesh', this.opts.colors);
      },
      destroy() {
        instances.delete(this);
        ro && ro.disconnect();
        io && io.disconnect();
        if (this.renderer) { this.renderer.release(); this.renderer = null; directCount--; }
        if (owned) { canvas.remove(); grainEl && grainEl.remove(); }
      },
    };

    inst.set(options);
    inst.time = (options.time ?? 0) + 20 + inst.opts.seed * 3.7;

    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => inst.resize()) : null;
    ro && ro.observe(owned ? el : canvas);
    const io = typeof IntersectionObserver !== 'undefined'
      ? new IntersectionObserver((entries) => {
          inst.visible = entries[entries.length - 1].isIntersecting;
          if (inst.visible) { inst.dirty = true; schedule(); }
        }, { rootMargin: '100px' })
      : null;
    io && io.observe(owned ? el : canvas);

    instances.add(inst);
    inst.ready = true;
    inst._draw(); // first frame immediately: no blank/black flash before the first rAF
    schedule();
    return inst;
  }

  // ---------------------------------------------------------------------------
  // Declarative: <div data-backdrop="night-swim" data-grain="0.2"></div>
  // data-backdrop takes a preset name or a style name; data-colors, data-params
  // (JSON), data-speed, data-grain, data-seed, data-quality are optional.
  // ---------------------------------------------------------------------------
  function autoInit(root = document) {
    const out = [];
    root.querySelectorAll('[data-backdrop]').forEach((el) => {
      if (el.__backdrop) return;
      const name = el.dataset.backdrop;
      const o = PRESETS[name] ? { preset: name } : { style: name };
      if (el.dataset.colors) {
        const raw = el.dataset.colors.trim();
        o.colors = raw.startsWith('[') ? JSON.parse(raw) : raw.split(/[\s,]+/).filter(Boolean);
      }
      if (el.dataset.params) o.params = JSON.parse(el.dataset.params);
      for (const k of ['speed', 'grain', 'seed', 'quality']) if (el.dataset[k] != null) o[k] = parseFloat(el.dataset[k]);
      if (el.dataset.animate === 'false') o.animate = false;
      el.__backdrop = createBackdrop(el, o);
      out.push(el.__backdrop);
    });
    return out;
  }

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => autoInit());
    else queueMicrotask(() => autoInit());
  }

  global.GradientBackdrop = {
    createBackdrop, autoInit, cssBackdrop, grainURL, parseColor, srgbToOklab,
    STYLES, PRESETS, CSS_PRESETS, PRELUDE,
  };
})(typeof globalThis !== 'undefined' ? globalThis : window);
