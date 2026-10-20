"""Deterministic 2D hull geometry and ink rendering for the blog figure."""
import numpy as np
from scipy.spatial import ConvexHull
from PIL import Image, ImageDraw
W,H=720,840
SIZE=(600,700)
CENTER=np.array([360.,422.])
BG=(253,252,249)
INK=(48,49,46)
MUTED=(133,134,127)
BLUE=INK
ORANGE=(151,77,53)
N=20
WORLDS=[
 dict(name='Humans only',key='humans-only',ai=False),
 dict(name='Weak AI feedback',key='ai-human-limited',ai=True),
 dict(name='Strong AI feedback',key='ai-strong-feedback',ai=True),
]
def ease(x):
 x=np.clip(x,0,1)
 return float(x*x*(3-2*x))
def cool_colors(points,progress,radius):
 return np.broadcast_to(np.array(INK,dtype=np.uint8),np.asarray(points).shape[:-1]+(3,))
def warm_colors(points,n):
 return np.broadcast_to(np.array(ORANGE,dtype=np.uint8),np.asarray(points).shape[:-1]+(3,))
def color_tuple(rgb):
 return tuple(int(c) for c in rgb)

class WaveModel:

    def __init__(self, dim, round_count=N):
        self.dim = dim
        self.shape = 'circle'
        self.rng = np.random.default_rng(1987 + dim)
        self.amplitude = 0.26
        theta = np.linspace(0, 2 * np.pi, 160, endpoint=False)
        directions = np.column_stack([np.cos(theta), np.sin(theta)])
        raw = 0.72 * np.sin(5 * theta + 0.45) + 0.28 * np.cos(9 * theta - 0.7)
        heights = np.maximum(0, raw) ** 1.55
        peaks = np.where((heights > np.roll(heights, 1)) & (heights > np.roll(heights, -1)) & (heights > 0.08))[0]
        self.seed = 0.65 * directions[::2]
        self.heights = heights / heights.max()
        self.base_directions = directions
        self.peaks = peaks
        self.active = np.where(self.heights > 1e-05)[0]
        self.mesh = None
        self.local = self.rng.normal(0, 0.24, (24, dim))
        self.local = self.local[np.linalg.norm(self.local, axis=1) < 0.52]
        self.initial = np.vstack([self.seed, self.local])
        self.vertices = [self.initial]
        self.hulls = [ConvexHull(self.initial)]
        self.advances = []
        self.anchor_sets = [np.vstack([self.seed[::5], self.local])]
        for n in range(round_count):
            old, h = (self.vertices[-1], self.hulls[-1])
            a = n * 1.731
            R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
            d = directions @ R.T
            denominators = d @ h.equations[:, :dim].T
            radii = np.min(np.where(denominators > 1e-10, -h.equations[:, dim] / np.maximum(denominators, 1e-10), np.inf), axis=1)
            origins = d * radii[:, None]
            targets = origins + d * (self.amplitude * self.heights)[:, None]
            assert self.inside(origins, h).all()
            assert not self.inside(targets[self.active], h, tol=1e-10).any()
            assert np.allclose(np.linalg.norm(targets - origins, axis=1), self.amplitude * self.heights)
            enlarged = np.vstack([old, targets[self.active]])
            newh = ConvexHull(enlarged)
            new = enlarged[newh.vertices]
            nh = ConvexHull(new)
            assert nh.volume > h.volume
            assert self.inside(old, nh).all()
            self.vertices.append(new)
            self.hulls.append(nh)
            self.advances.append((origins, targets))
            self.anchor_sets.append(np.vstack([self.anchor_sets[-1], targets[peaks]]))
        extent = np.abs(self.vertices[-1]).max()
        self.scale = 252 / (1.035 * extent)
        self.patch_sets = []
        clouds = []
        for n, anchors in enumerate(self.anchor_sets):
            start = 0 if n == 0 else len(self.anchor_sets[n - 1])
            for p in anchors[start:]:
                clouds.append(p * 0.985 + self.rng.normal(0, 0.022, (18, dim)))
            points = np.vstack(clouds)
            points = points[self.inside(points, self.hulls[n])]
            self.patch_sets.append(points)
        ext = np.abs(self.vertices[-1]).max()
        cloud = self.rng.uniform(-ext, ext, (2300, dim))
        self.cloud = cloud[self.inside(cloud, self.hulls[-1])]

    def inside(self, p, h, tol=1e-08):
        return np.max(np.asarray(p) @ h.equations[:, :self.dim].T + h.equations[:, self.dim], axis=1) <= tol

    def project(self, p, t):
        p = np.asarray(p)
        return p * np.array([self.scale, -self.scale]) + CENTER

    def outline(self, draw, points, t, color, dashed=False, width=1):
        p = self.project(points, t)
        p = p[ConvexHull(p).vertices]
        for a, b in zip(p, np.roll(p, -1, axis=0)):
            if dashed:
                count = max(1, int(np.linalg.norm(b - a) / 8))
                for j in range(count):
                    draw.line([tuple(a + (b - a) * j / count), tuple(a + (b - a) * min((j + 0.4) / count, 1))], fill=color, width=width)
            else:
                draw.line([tuple(a), tuple(b)], fill=color, width=width)

    def draw_patches(self, im, s, t, opacity=1):
        d = ImageDraw.Draw(im, 'RGBA')
        points = s.get('patch_points', self.patch_sets[s['known_n']])
        radius = np.linalg.norm(s.get('frontier', self.vertices[s['known_n']]), axis=1).max()
        colors = cool_colors(points, s['known_n'] / N, radius)
        dot_radius = getattr(self, 'patch_radius', 1.7)
        dot_alpha = getattr(self, 'patch_alpha', 160)
        for (x, y), col in zip(self.project(points, t), colors):
            d.ellipse((x - dot_radius, y - dot_radius, x + dot_radius, y + dot_radius), fill=(*color_tuple(col), int(dot_alpha * opacity)))
        for i in range(0, len(self.local) - 2, 4):
            a, b = self.local[i:i + 2]
            mid = (a + b) / 2 + 0.08 * np.sin(i + np.arange(self.dim))
            d.line([tuple(p) for p in self.project([a, mid, b], t)], fill=(*BLUE, int(120 * opacity)), width=2)
        if 'patch_segments' in s:
            segments = s['patch_segments']
        else:
            segments = [(a[k], b[k]) for a, b in self.advances[:s['known_n']] for k in self.peaks[::2]]
        for segment in segments:
            d.line([tuple(p) for p in self.project(segment, t)], fill=(*BLUE, int(90 * opacity)), width=1)

    def draw_wave(self, im, s, t, w):
        if s['n'] < 0 or not s.get('discovered', s['human']):
            return
        n = s['n']
        a, b = self.advances[n]
        strength = 1 - 0.72 * s['ai'] if w['ai'] else 1 - 0.45 * min(max(s['pop_age'], 0), 1)
        overlay = Image.new('RGBA', im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        screen = self.project(b, t)
        colors = warm_colors(self.base_directions, n)
        for i, j in zip(range(len(b)), np.roll(np.arange(len(b)), -1)):
            selected = s.get('wave_indices', self.active)
            if max(self.heights[i], self.heights[j]) > 0.01 and (i in selected or j in selected):
                col = color_tuple((colors[i].astype(int) + colors[j]) / 2)
                d.line([tuple(screen[i]), tuple(screen[j])], fill=(*col, int(245 * strength)), width=2)
        for i in s.get('wave_peaks', self.peaks):
            p, q = self.project([a[i], b[i]], t)
            col = color_tuple(colors[i])
            d.line([tuple(p), tuple(q)], fill=(*col, int(165 * strength)), width=1)
            x, y = q
            r = 3.5
            marker = [(x, y - r), (x + r, y + r), (x - r, y + r)] if w.get('autonomous') else [(x, y - r), (x + r, y), (x, y + r), (x - r, y)]
            d.polygon(marker, fill=(*col, int(255 * strength)))
        im.paste(overlay, (0, 0), overlay)
