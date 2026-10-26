import cv2
import numpy as np
from rezak.plan import Region
from rezak.framing import inner_player,camera_without_chat

def test_webcam_headroom_trim_preserves_bottom_and_manual_regions():
    from rezak.framing import webcam_region
    from rezak.plan import Segment
    s=Segment(start_ms=0,end_ms=1000,region=Region(x=.1,y=.02,w=.2,h=.3),framing_note='Авто: gap-v2')
    r=webcam_region(s)
    assert abs(r.y-(.02+.3*.14))<1e-8
    assert abs(r.y+r.h-(s.region.y+s.region.h))<1e-8
    assert r.x==s.region.x and r.w==s.region.w
    s.framing_note='Ручное кадрирование'
    assert webcam_region(s)==s.region

def test_dense_layout_reserves_only_six_percent_for_text():
    from rezak.framing import split_layout,video_filter
    from rezak.plan import Segment
    assert split_layout(1280)==(576,76,628)
    segment=Segment(start_ms=0,end_ms=1000,framing='split',
        region=Region(x=0.0,y=0.0,w=.2,h=.3),
        secondary_region=Region(x=.3,y=.3,w=.6,h=.5))
    filters=video_filter('[in]','out',segment,720,1280,1920,1080)
    from rezak.framing import continuation_layout
    top,gap,bottom,region=continuation_layout(segment,720,1280,1920,1080)
    assert f'pad=720:{top+gap}' in filters[1]
    assert region.y+region.h==1.0
    assert region.x==segment.secondary_region.x
    assert region.w==segment.secondary_region.w
    assert top+gap+bottom==1280
    assert 'force_original_aspect_ratio=decrease' in filters[2]

def test_inner_player_excludes_controls_ads_and_overlaid_webcam():
    image=np.zeros((450,800,3),dtype=np.uint8)
    cv2.rectangle(image,(150,80),(650,300),(100,150,0),2)
    cv2.rectangle(image,(0,0),(210,130),(130,130,130),-1)
    cv2.rectangle(image,(180,320),(640,350),(20,20,200),-1)
    cv2.rectangle(image,(700,340),(790,400),(20,20,200),-1)
    region=inner_player(image,Region(x=.15,y=.1,w=.75,h=.7))
    assert region is not None
    # The overlaid webcam must not cause the underlying video's left side to go.
    assert region.x*800<=151 and (region.x+region.w)*800>=649
    assert 78<=region.y*450<=81 and 299<=(region.y+region.h)*450<=302
    camera=camera_without_chat(image,Region(x=.04,y=.02,w=.16,h=.32))
    assert (camera.y+camera.h)*450<=131

def test_single_line_does_not_invent_video_bounds():
    image=np.zeros((450,800,3),dtype=np.uint8)
    cv2.line(image,(100,100),(650,100),(100,150,0),2)
    assert inner_player(image,Region(x=0.0,y=0.0,w=1.0,h=1.0)) is None
