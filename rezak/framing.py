"""Conservative CPU face/rectangular-content detection, with editable regions.

Geometric detection is not semantic vision: uncertain layouts retain their frame.
Coordinates are normalized to the original source, never the rendered preview.
"""
import subprocess
from .media import ffmpeg
from .plan import Region
from .events import emit

def frame(source,at_ms):
    import cv2
    import numpy as np
    process=subprocess.run([str(ffmpeg()),'-v','error','-nostdin','-ss',str(at_ms/1000),'-i',str(source),'-frames:v','1','-vf','scale=960:-2','-f','image2pipe','-vcodec','mjpeg','pipe:1'],capture_output=True,timeout=30)
    if process.returncode:raise ValueError('Не удалось получить кадр для монтажа')
    image=cv2.imdecode(np.frombuffer(process.stdout,dtype=np.uint8),cv2.IMREAD_COLOR)
    if image is None:raise ValueError('Пустой кадр для монтажа')
    return image

def detect(image):
    import cv2
    height,width=image.shape[:2];gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    classifier=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
    faces=classifier.detectMultiScale(gray,1.15,6,minSize=(32,32))
    faces=sorted(faces,key=lambda b:int(b[2])*int(b[3]),reverse=True)
    corners=[b for b in faces if b[2]<width*.25 and (b[0]+b[2]/2<width*.3 or b[0]+b[2]/2>width*.7) and (b[1]+b[3]/2<height*.35 or b[1]+b[3]/2>height*.65)]
    if corners:faces=corners
    face=None
    if len(faces):
        x,y,w,h=map(int,faces[0]);left=max(0,x-w*.65);top=max(0,y-h*.6)
        right=min(width,x+w*1.65);bottom=min(height,y+h*2.5)
        face=Region(x=left/width,y=top/height,w=(right-left)/width,h=(bottom-top)/height)
    # Rectangular player borders / embedded videos. Avoid small ads and chat strips.
    edges=cv2.morphologyEx(cv2.Canny(gray,25,80),cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_RECT,(3,3)))
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    regions=[]
    for contour in contours:
        polygon=cv2.approxPolyDP(contour,.02*cv2.arcLength(contour,True),True)
        if not 4<=len(polygon)<=8:continue
        x,y,w,h=cv2.boundingRect(polygon);area=w*h/(width*height)
        if .18<area<.88 and .65<w/h<2.4 and w>width*.30 and h>height*.30:
            if len(faces):
                fx,fy,fw,fh=map(int,faces[0])
                if x<fx+fw/2<x+w and y<fy+fh/2<y+h:continue
            regions.append((area,Region(x=float(x/width),y=float(y/height),w=float(min(w,width-x)/width),h=float(min(h,height-y)/height))))
    content=max(regions,key=lambda item:item[0])[1] if regions else None
    return face,content

def stable(regions):
    if len(regions)<2:return None
    fields=('x','y','w','h')
    if any(max(getattr(r,k) for r in regions)-min(getattr(r,k) for r in regions)>.22 for k in ('x','y')):return None
    x=min(r.x for r in regions);y=min(r.y for r in regions)
    right=max(r.x+r.w for r in regions);bottom=max(r.y+r.h for r in regions)
    return Region(x=x,y=y,w=min(1-x,right-x),h=min(1-y,bottom-y))

def portrait(region,source_ratio):
    """Expand a face region to 9:16 without removing its existing contents."""
    w=region.w;h=region.h;target=9/16
    if w*source_ratio/h>target:h=w*source_ratio/target
    else:w=h*target/source_ratio
    if w>1 or h>1:return region
    return Region(x=max(0.0,min(1-w,region.x+(region.w-w)/2)),y=max(0.0,min(1-h,region.y+(region.h-h)/2)),w=w,h=h)

def inner_player(image,hint):
    """Recover an outlined embedded player, excluding its surrounding controls.

    Require matching horizontal borders and a vertical side ending at both;
    a random coloured line or a large page contour is insufficient evidence.
    """
    import cv2
    import numpy as np
    height,width=image.shape[:2]
    mask=cv2.inRange(cv2.cvtColor(image,cv2.COLOR_BGR2HSV),np.array([35,65,35]),np.array([100,255,230]))
    lines=cv2.HoughLinesP(mask,1,np.pi/180,threshold=60,minLineLength=max(40,int(width*.14)),maxLineGap=18)
    if lines is None:return None
    horizontal=[];vertical=[]
    for line in lines[:,0]:
        x1,y1,x2,y2=map(int,line)
        if abs(y1-y2)<=2 and abs(x2-x1)>=width*.4:
            y=(y1+y2)/2
            if hint.y*height-12<=y<=(hint.y+hint.h)*height+12:horizontal.append((min(x1,x2),max(x1,x2),y))
        elif abs(x1-x2)<=2:vertical.append(((x1+x2)/2,min(y1,y2),max(y1,y2)))
    boxes=[]
    for left1,right1,top in horizontal:
        for left2,right2,bottom in horizontal:
            if not height*.25<bottom-top<height*.7:continue
            # A webcam can obscure one border. Intersecting the visible line
            # lengths silently amputates the left side of the actual video.
            left=min(left1,left2);right=max(right1,right2)
            if right-left<width*.4:continue
            if left<hint.x*width-15 or right>(hint.x+hint.w)*width+15:continue
            if not any(abs(x-right)<8 and abs(y1-top)<10 and abs(y2-bottom)<10 for x,y1,y2 in vertical):continue
            boxes.append((right-left,bottom-top,left,top,right,bottom))
    if not boxes:return None
    # The largest supported video rectangle preserves the scene, not its UI below.
    _,_,left,top,right,bottom=max(boxes,key=lambda b:b[0]*b[1])
    return Region(x=float(left/width),y=float(top/height),w=float((right-left)/width),h=float((bottom-top)/height))

def camera_without_chat(image,region):
    import cv2
    import numpy as np
    height,width=image.shape[:2]
    if region.w>.35 or region.y>.35:return region
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(gray,35,100)
    lines=cv2.HoughLinesP(edges,1,np.pi/180,threshold=60,minLineLength=int(width*.15),maxLineGap=10)
    boundaries=[]
    # The webcam/chat boundary can be broken into short edge fragments. Confirm
    # its first abrupt transition to a mostly dark chat strip across the corner.
    left=0 if region.x<.5 else int(min(region.x,.75)*width)
    right=int(max(region.x+region.w,.25)*width) if region.x<.5 else width
    strip=gray[:,left:right];means=strip.mean(axis=1)
    for y in range(max(4,int((region.y+region.h*.5)*height)),min(height-4,int((region.y+region.h)*height))):
        if means[y-3:y].mean()-means[y:y+3].mean()>20 and (strip[y:y+3]<45).mean()>.6:
            boundaries.append(y);break
    if lines is not None:
        for x1,y1,x2,y2 in lines[:,0]:
            if abs(int(y1)-int(y2))>2:continue
            y=(int(y1)+int(y2))/2
            if min(x1,x2)<=region.x*width and max(x1,x2)>=(region.x+region.w)*width and (region.y+region.h*.5)*height<y<(region.y+region.h)*height:
                boundaries.append(y)
    if not boundaries:return region
    bottom=min(boundaries)-2
    if bottom/height-region.y<.08:return region
    return region.model_copy(update={'h':float(bottom/height-region.y)})

def refine_split(plan,source):
    """Upgrade automatic/cached split plans while respecting manual rectangles."""
    cuts=[]
    for segment in plan.segments:
        if segment.framing!='split' or not segment.framing_note.startswith('Авто') or 'gap-v2' in segment.framing_note:
            cuts.append(segment);continue
        cameras=[];screens=[]
        for fraction in (.15,.5,.85):
            image=frame(source,segment.start_ms+round((segment.end_ms-segment.start_ms)*fraction))
            camera=camera_without_chat(image,segment.region)
            if camera.h<segment.region.h-.005:cameras.append(camera)
            # Previously cached gap-v1 bounds may already exclude the left edge.
            hint=segment.secondary_region
            if 'gap-v1' in segment.framing_note:hint=hint.model_copy(update={'x':0.0,'w':1.0})
            screen=inner_player(image,hint)
            if screen:screens.append(screen)
        screen=stable(screens)
        fallback=Region(x=0.0,y=0.0,w=1.0,h=1.0) if 'gap-v1' in segment.framing_note else segment.secondary_region
        update={'region':stable(cameras) or segment.region,'secondary_region':screen or fallback,'framing_note':'Авто: gap-v2; отдельная полоса субтитров. '+('Полные границы видео подтверждены на нескольких кадрах.' if screen else 'Полная граница плеера не подтверждена; сохранена безопасная область.')}
        if screen:update['secondary_region']=screen
        cuts.append(segment.model_copy(update=update))
    return plan.model_copy(update={'segments':cuts})

def auto_frame(plan,source,focus='speaker'):
    if plan.profile!='vertical':return plan
    cuts=[]
    for segment in plan.segments:
        if segment.framing!='fit':cuts.append(segment);continue
        faces=[];screens=[]
        for fraction in (.15,.5,.85):
            image=frame(source,segment.start_ms+round((segment.end_ms-segment.start_ms)*fraction))
            face,screen=detect(image)
            if face:faces.append(face)
            if screen:screens.append(screen)
        face=stable(faces);screen=stable(screens);update={}
        webcam=face and face.w<.30 and face.h<.65 and (face.x+face.w<.4 or face.x>.6)
        if face and screen and (focus=='reaction' or webcam):update={'framing':'split','region':face,'secondary_region':screen}
        elif face and focus in ('screen','reaction'):update={'framing':'split','region':face,'secondary_region':screen or Region(x=0.0,y=0.0,w=1.0,h=1.0)}
        elif focus=='screen' and screen:update={'framing':'crop','region':screen}
        elif focus=='speaker' and face:update={'framing':'crop','region':portrait(face,image.shape[1]/image.shape[0])}
        if update:
            update['framing_note']='Авто: геометрия лица/видеоплеера проверена на трёх кадрах. Проверьте область в редакторе.'
            emit('render',None,'Определены области: '+update['framing'])
        else:update={'framing_note':'Надёжная область не найдена: сохранён полный кадр. Можно указать область вручную.'}
        cuts.append(segment.model_copy(update=update))
    return plan.model_copy(update={'segments':cuts})

def crop_filter(region,sw,sh):
    # Even source-pixel coordinates for YUV420; never evaluate user expressions.
    x=min(sw-2,int(region.x*sw)//2*2);y=min(sh-2,int(region.y*sh)//2*2)
    w=max(2,min(sw-x,int(region.w*sw)//2*2));h=max(2,min(sh-y,int(region.h*sh)//2*2))
    return f'crop={w}:{h}:{x}:{y}'

def reference_layout(height):
    top=round(height*.35)//2*2;gap=round(height*.0625)//2*2
    return top,gap,height-top-gap


def reference_regions(plan,source,sw,sh):
    """Prefer a consistently detected face inside content; otherwise crop centrally."""
    _,_,bottom=reference_layout(1280);cuts=[]
    for s in plan.segments:
        if s.framing!='split':cuts.append(s);continue
        r=s.secondary_region;anchors=[]
        for fraction in (.2,.5,.8):
            image=frame(source,s.start_ms+round((s.end_ms-s.start_ms)*fraction))
            x,y=int(r.x*sw),int(r.y*sh);rw,rh=int(r.w*sw),int(r.h*sh)
            face,_=detect(image[y:y+rh,x:x+rw])
            if face:anchors.append(face.x+face.w/2)
        anchor=sorted(anchors)[len(anchors)//2] if len(anchors)>=2 and max(anchors)-min(anchors)<.25 else .5
        target_w=r.h*sh*(720/bottom)/sw
        if target_w<r.w:
            left=max(r.x,min(r.x+r.w-target_w,r.x+r.w*anchor-target_w/2))
            r=Region(x=float(left),y=r.y,w=float(target_w),h=r.h)
        cuts.append(s.model_copy(update={'secondary_region':r,'framing_note':('reference-crop-v1; '+s.framing_note)[:500]}))
    return plan.model_copy(update={'segments':cuts})


def video_filter(label,out,segment,width,height,sw,sh,headline_ms=0,reference=False):
    scale=lambda h:f'scale={width}:{h}:force_original_aspect_ratio=decrease,pad={width}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1'
    if segment.framing=='split':
        if reference:
            top,gap,bottom=reference_layout(height)
            fill=lambda h:f'scale={width}:{h}:force_original_aspect_ratio=increase,crop={width}:{h},setsar=1'
            filters=[f'{label}split=2[face{out}][screen{out}]']
            camera=crop_filter(webcam_region(segment),sw,sh)
            filters += [f'[face{out}]{camera},{fill(top)},pad={width}:{top+gap}:0:0[top{out}]']
            return filters+[
                    f'[screen{out}]{crop_filter(segment.secondary_region,sw,sh)},{fill(bottom)}[bottom{out}]',
                    f'[top{out}][bottom{out}]vstack=inputs=2,fps=30[{out}]']
        top,gap,bottom,screen_region=continuation_layout(segment,width,height,sw,sh)
        # Preserve both selected regions in full, even when aspect ratios differ.
        face=f'scale={width}:{top}:force_original_aspect_ratio=decrease,pad={width}:{top+gap}:(ow-iw)/2:({top}-ih),setsar=1'
        camera=webcam_region(segment)
        # A small width crop fills the panel after removing excess headroom.
        ratio=camera.w*sw/(camera.h*sh)/(width/top)
        if camera is not segment.region and 1.0<=ratio<=1.15:
            face=f'scale={width}:{top}:force_original_aspect_ratio=increase,crop={width}:{top},pad={width}:{top+gap}:0:0,setsar=1'
        screen=f'scale={width}:{bottom}:force_original_aspect_ratio=decrease,pad={width}:{bottom}:(ow-iw)/2:0,setsar=1'
        return [f'{label}split=2[face{out}][screen{out}]',f'[face{out}]{crop_filter(camera,sw,sh)},{face}[top{out}]',f'[screen{out}]{crop_filter(screen_region,sw,sh)},{screen}[bottom{out}]',f'[top{out}][bottom{out}]vstack=inputs=2,fps=30[{out}]']
    prefix=crop_filter(segment.region,sw,sh)+',' if segment.framing=='crop' else ''
    return [f'{label}{prefix}{scale(height)},fps=30[{out}]']


def split_layout(height):
    """Raised webcam, narrow caption band, and uncropped screen content."""
    top=round(height*.45)//2*2;gap=round(height*.06)//2*2
    return top,gap,height-top-gap


def webcam_region(segment):
    """Reduce headroom slightly less than the user's marked reference (~19%)."""
    region=segment.region
    if not segment.framing_note.startswith('Авто'):return region
    trim=region.h*.14
    return region.model_copy(update={'y':region.y+trim,'h':region.h-trim})


def continuation_layout(segment,width,height,sw,sh):
    """Continue the screen below the player at the same scale to the source edge."""
    _,gap,_=split_layout(height)
    region=segment.secondary_region
    region=region.model_copy(update={'h':1.0-region.y})
    # Match the exact even crop dimensions used by FFmpeg.
    x=min(sw-2,int(region.x*sw)//2*2);y=min(sh-2,int(region.y*sh)//2*2)
    rw=max(2,min(sw-x,int(region.w*sw)//2*2))
    rh=max(2,min(sh-y,int(region.h*sh)//2*2))
    natural=max(2,round(rh*width/rw/2)*2)
    bottom=min(natural,height-gap-round(height*.2)//2*2)
    return height-gap-bottom,gap,bottom,region
