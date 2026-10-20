"""Five illustrative scenarios, sharing geometry, camera and presentation time."""
from pathlib import Path
import json, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw
from geometry import WaveModel, WORLDS, ease, SIZE, W, H, BG, BLUE, MUTED, INK
from scipy.spatial import ConvexHull

ROOT=Path(__file__).resolve().parents[3]
import imageio_ffmpeg
DEST=ROOT/'assets/convex-hull'
RSI=dict(name='AI · recursive self-improvement',key='ai-rsi',ai=True,
         autonomous=True,subtitle='AI discovers, fills and improves itself.')
SLOW=dict(name='AI slows human discovery',key='ai-slowdown',ai=True)
SCENARIOS=[WORLDS[0],SLOW,*WORLDS[1:],RSI]
GENERATIONS=120
SCALE_ROUND=40
FPS=30
MOTION=4.
HOLD=.3
INTRO=.12
END=MOTION
# Separate the tiles with paper-coloured gutters. Align the encoded frame to
# 16-pixel blocks so hardware decoding/cropping cannot expose an adjacent tile.
VIDEO_LAYOUT=dict(tileWidth=516,tileHeight=438,stride=560,x=16,y=16,height=480)

def loop_scene_time(display):
    return float(np.clip(display,0,MOTION))

def rsi_schedule():
    # One complete autonomous cycle per event. Every part of the cycle speeds
    # up together; the final completed geometry remains the same as before.
    weights=np.array([(1+.033*n)**-2 for n in range(GENERATIONS)])
    # Finish the last infill exactly at the plotted endpoint. Its subsequent
    # improvement phase lies beyond the excerpt, so there is no terminal plateau.
    total=(MOTION-INTRO)/(1-.22*weights[-1]/weights.sum())
    spans=total*weights/weights.sum()
    events=[];start=INTRO
    for n,span in enumerate(spans):
        events.append(dict(n=n,start=float(start),pop=float(start),
                           fill=float(start+.15*span),learn=float(start+.78*span),
                           end=float(start+span)))
        start+=span
    return events

class ComparisonModel(WaveModel):
    def __init__(self,dim):
        assert dim==2
        super().__init__(dim,round_count=GENERATIONS)
        self.fill_opacity=255;self.patch_radius=1.1;self.patch_alpha=255
        v=self.vertices[SCALE_ROUND]
        self.scale=252/(1.035*np.abs(v).max())
        rng=np.random.default_rng(4829+dim)
        extent=np.abs(v).max()*1.65
        cloud=rng.uniform(-extent,extent,(6400,dim))
        self.cloud=cloud[self.inside(cloud,self.hulls[-1])]
        self.rsi_events=rsi_schedule()
        self.lobes=len(self.peaks)
        # Partition the existing sine/cosine wave, without changing spike
        # amplitudes or the hull reached after all five discoveries.
        distance=np.abs(np.arange(len(self.heights))[:,None]-self.peaks[None,:])
        groups=np.minimum(distance,len(self.heights)-distance).argmin(axis=1)
        self.groups=[self.active[groups[self.active]==i] for i in range(self.lobes)]
        self.partial=[self.initial]
        self.partial_patches=[self.patch_sets[0]]
        self.partial_segments=[[]]
        self.steps=[]
        for n in range(20):
            a,b=self.advances[n]
            old_points={tuple(p) for p in self.patch_sets[n]}
            additions=np.array([p for p in self.patch_sets[n+1] if tuple(p) not in old_points])
            nearest=np.linalg.norm(additions[:,None,:]-b[self.peaks][None,:,:],axis=2).argmin(axis=1)
            pending=np.ones(len(additions),dtype=bool)
            for j,indices in enumerate(self.groups):
                vertices=np.vstack([self.partial[-1],b[indices]])
                hull=ConvexHull(vertices);vertices=vertices[hull.vertices]
                self.partial.append(vertices)
                # Preserve the exact old final islands, revealing the local
                # cluster associated with each lobe as its discovery appears.
                reveal=pending & ((nearest<=j) if j<self.lobes-1 else True) & self.inside(additions,hull)
                points=np.vstack([self.partial_patches[-1],additions[reveal]])
                pending[reveal]=False
                self.partial_patches.append(points)
                segments=list(self.partial_segments[-1])
                if j%2==0:segments.append((a[self.peaks[j]],b[self.peaks[j]]))
                self.partial_segments.append(segments)
                self.steps.append(dict(n=n,indices=indices,peak=self.peaks[j]))
            assert not pending.any()
            assert len(self.partial_patches[-1])==len(self.patch_sets[n+1])
            assert np.isclose(ConvexHull(self.partial[-1]).volume,self.hulls[n+1].volume)
        human=np.linspace(INTRO,3.80,20)
        strong=INTRO+3.68*np.log1p(.035*np.arange(100))/np.log1p(.035*99)
        # Each new discovery takes 65% longer: closure is quick, but the
        # human process that supplies new ideas is progressively weakened.
        slow=INTRO+(human[1]-human[0])*(1.65**np.arange(20)-1)/.65
        slow=slow[slow<3.80]
        self.human_events=[]
        for i,times in enumerate([human,strong,slow]):
            # Continue the strong-feedback cadence beyond the excerpt, rather
            # than adding a long final gap that makes its growth flatten out.
            next_pop=times[-1]+(times[-1]-times[-2]) if i==1 else 3.90
            gaps=np.diff(np.append(times,next_pop))
            self.human_events.append([dict(k=k,pop=float(pop),fill=float(pop+min(.03,.1*gap)),
                                          end=float(pop+min(.09,.8*gap)))
                                      for k,(pop,gap) in enumerate(zip(times,gaps))])
        # End on the last completed infill, as for RSI. Preserve all 100 human
        # discoveries and the final hull while removing the terminal plateau.
        strong_events=self.human_events[1]
        stretch=(MOTION-INTRO)/(strong_events[-1]['end']-INTRO)
        for event in strong_events:
            for phase in ('pop','fill','end'):
                event[phase]=INTRO+(event[phase]-INTRO)*stretch
        strong_events[-1]['end']=MOTION

    def state(self,w,t):
        if t<INTRO:
            return dict(n=-1,human=0,discovered=0,ai=0,completed=0,known_n=0,
                        step=0,frontier=self.initial,patch_points=self.partial_patches[0],patch_segments=[],
                        fill=self.initial,fill_alpha=ease(t/INTRO),pop_age=-1.)
        if w.get('autonomous'):
            event=next((e for e in self.rsi_events if t<e['end']-1e-10),None)
            if event is None:
                return dict(n=GENERATIONS-1,human=0,discovered=1,ai=1,
                            completed=GENERATIONS,known_n=GENERATIONS,fill=self.vertices[GENERATIONS],
                            frontier=self.vertices[GENERATIONS],fill_alpha=1,pop_age=2.)
            n=event['n'];ai=ease((t-event['fill'])/(event['learn']-event['fill']))
            a,b=self.advances[n]
            fill=self.vertices[n] if ai==0 else np.vstack([self.vertices[n],(a+(b-a)*ai)[self.active]])
            return dict(n=n,human=0,discovered=1,ai=ai,completed=n,known_n=n+1,
                        fill=fill,frontier=self.vertices[n+1],fill_alpha=1,pop_age=t-event['pop'])
        events=self.human_events[2 if w['key']=='ai-slowdown' else int(w['key']=='ai-strong-feedback')]
        event=next((e for e in reversed(events) if t>=e['pop']),None)
        assert event is not None
        k=event['k'];step=self.steps[k];n=step['n']
        ai=ease((t-event['fill'])/(event['end']-event['fill']))
        a,b=self.advances[n];indices=step['indices']
        fill=self.partial[k] if ai==0 else np.vstack([self.partial[k],(a+(b-a)*ai)[indices]])
        count=k+1
        return dict(n=n,human=1,discovered=1,ai=ai,completed=(k+int(ai>=1))/self.lobes,
                    known_n=count//self.lobes,step=count,fill=fill,fill_alpha=1,
                    frontier=self.partial[count],patch_points=self.partial_patches[count],
                    patch_segments=self.partial_segments[count],wave_indices=indices,
                    wave_peaks=[step['peak']],pop_age=t-event['pop'])

    def draw_fill(self,im,s,t):
        vertices=s['fill']
        polygon=self.project(vertices[ConvexHull(vertices).vertices],t)
        ImageDraw.Draw(im,'RGBA').polygon(
            [tuple(p) for p in polygon],fill=(*INK,round(255*s['fill_alpha'])))

    def render(self,w,t):
        im=Image.new('RGB',(W,H),BG);d=ImageDraw.Draw(im,'RGBA');s=self.state(w,t)
        if not w['ai']:
            self.outline(d,s['frontier'],t,(*MUTED,100),True)
            self.draw_patches(im,s,t)
        else:
            if t<INTRO:self.draw_patches(im,s,t,1-s['fill_alpha']*.8)
            self.draw_fill(im,s,t)
        d=ImageDraw.Draw(im,'RGBA')
        self.outline(d,self.initial,t,(*MUTED,65),True)
        if s['discovered'] and s['ai']<1 and w['ai']:
            self.outline(d,s['frontier'],t,(*MUTED,140),True)
        self.draw_wave(im,s,t,w)
        return im

    def verify_rsi(self):
        assert np.isclose(self.rsi_events[-1]['learn'],END)
        assert self.rsi_events[-1]['end']>END
        assert np.isclose(self.human_events[1][-1]['end'],END)
        for t in np.linspace(0,END,401):
            a,b=[self.state(w,t) for w in WORLDS[:2]]
            assert np.array_equal(a['frontier'],b['frontier'])
            assert a['step']==b['step']
            assert self.state(RSI,t)['human']==0
        for i,events in enumerate(self.human_events):
            w=[WORLDS[0],WORLDS[2],SLOW][i]
            for e in events:
                assert self.state(w,e['pop']-1e-8)['step']==e['k']
                assert self.state(w,e['pop'])['step']==e['k']+1
                assert self.state(w,e['fill']-1e-8)['ai']==0
        assert max(np.diff([e['pop'] for e in self.human_events[0]]))<.2
        assert [self.state(w,END)['completed'] for w in SCENARIOS[:4]]==[4,1.2,4,20]
        assert np.all(np.diff([e['pop'] for e in self.human_events[2]],n=2)>0)
        assert self.state(SLOW,END)['step']<self.state(WORLDS[0],END)['step']
        assert np.isclose(self.state(RSI,END)['ai'],1)
        corners=np.array([[42,140],[558,140],[558,578],[42,578]])*1.2
        silhouette=ConvexHull(self.project(self.vertices[GENERATIONS],END))
        distances=corners@silhouette.equations[:,:2].T+silhouette.equations[:,2]
        assert np.all(distances.max(axis=1)<-5)
        print('Verified: 20 human discoveries, first at 0.12s, maximum gap 0.194s; matched frontiers, fixed spikes, preserved final geometry, autonomous RSI engulfs canvas.',flush=True)

def render(dim):
    model=ComparisonModel(dim);model.verify_rsi();shape=model.shape
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    layout=VIDEO_LAYOUT
    width=layout['stride']*len(SCENARIOS)
    command=[ffmpeg,'-hide_banner','-loglevel','error','-y','-f','rawvideo',
             '-vcodec','rawvideo','-s',f'{width}x{layout["height"]}','-pix_fmt','rgb24','-r',str(FPS),
             '-i','-','-an','-c:v','libx264','-preset','medium','-crf','19',
             '-pix_fmt','yuv420p','-movflags','+faststart',str(DEST/f'{shape}-loop.mp4')]
    proc=subprocess.Popen(command,stdin=subprocess.PIPE)
    for frame in range(round((MOTION+HOLD)*FPS)):
        if frame>round(MOTION*FPS):
            proc.stdin.write(result.tobytes());continue
        t=loop_scene_time(frame/FPS);result=Image.new('RGB',(width,layout['height']),BG)
        for i,w in enumerate(SCENARIOS):
            crop=model.render(w,t).resize(SIZE,Image.Resampling.LANCZOS).crop((42,140,558,578))
            result.paste(crop,(i*layout['stride']+layout['x'],layout['y']))
            if frame==round(MOTION*FPS):crop.save(DEST/f'{shape}-{i}.webp',quality=92)
        proc.stdin.write(result.tobytes())
        if frame%30==0:print(shape,'frame',frame,flush=True)
    proc.stdin.close();assert proc.wait()==0
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-i',str(DEST/f'{shape}-loop.mp4'),'-f','null','-'],check=True)
    (DEST/'video-layout.json').write_text(json.dumps(layout,separators=(',',':'))+'\n')
    print('Encoded and decoded',shape,round((DEST/f'{shape}-loop.mp4').stat().st_size/1e6,2),'MB; 4 seconds + 0.3-second final hold',flush=True)

if __name__=='__main__':
    DEST.mkdir(parents=True,exist_ok=True)
    render(2)
