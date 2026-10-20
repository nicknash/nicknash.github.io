"""Measure filled area from the exact geometry used in the animation."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.spatial import ConvexHull
from render import ComparisonModel,SCENARIOS,FPS,MOTION,HOLD,loop_scene_time,INTRO
from geometry import W,H

m=ComparisonModel(2)
island_areas=[]
for n in range(21):
    # Render only the known islands and connections onto black, excluding the
    # frontier outline, grid and transient discovery markers. Count their union.
    mask=Image.new('RGB',(W,H),(0,0,0))
    m.draw_patches(mask,dict(known_n=n//m.lobes,frontier=m.partial[n],
                            patch_points=m.partial_patches[n],patch_segments=m.partial_segments[n]),0)
    area=float((np.asarray(mask).max(axis=2)>0).sum()/m.scale**2)
    island_areas.append(area)
initial=island_areas[0]
series=[[] for _ in SCENARIOS]
rounds=[[] for _ in SCENARIOS]
for frame in range(round(MOTION*FPS)+1):
    t=loop_scene_time(frame/FPS)
    for i,w in enumerate(SCENARIOS):
        state=m.state(w,t)
        if not w['ai']:
            area=island_areas[state['step']]
        elif t<INTRO:
            # The initial closure fades from known islands into the seed hull.
            area=initial+(m.hulls[0].volume-initial)*state['fill_alpha']
        else:
            # This is full geometric area, including growth outside the crop.
            area=float(ConvexHull(state['fill']).volume)
        series[i].append(round(area/initial,6))
        rounds[i].append(int(state['completed']))
for values in series:
    assert np.isclose(values[0],1)
    assert np.min(np.diff(values))>=-1e-5
assert series[2][-1]>6*series[0][-1]
assert all(series[i][-1]<series[i+1][-1] for i in range(len(SCENARIOS)-1))
assert np.isclose(series[-1][-1]*initial,m.hulls[120].volume)
for i in (3,4):
    assert np.all(np.diff(series[i][-15:])>0), f'{SCENARIOS[i]["name"]} must keep growing through the final plotted frame'
assert len(np.unique(series[0]))==21
data=dict(fps=FPS,duration=MOTION,hold=HOLD,yMin=0,yMax=[60,60,60,60,600],scale='linear',
          unit='multiples of initial filled area',names=[w['name'] for w in SCENARIOS],series=series,rounds=rounds,
          measurement='Union of drawn islands and connections without AI; full convex-hull area after AI infill, including beyond the canvas. Initial infill interpolates by its opacity.')
p=Path(__file__).resolve().parents[3]/'assets/convex-hull/filled-area.json'
p.write_text(json.dumps(data,separators=(',',':'))+'\n')
print('Measured final areas relative to initial:',[s[-1] for s in series])
print('Verified common baseline, monotonic area, island-only no-AI measurement and unclipped RSI area.')
