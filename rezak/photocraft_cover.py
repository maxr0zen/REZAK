"""Windows PhotoCraft renderer. No generated faces; all image layers are real frames."""
import itertools
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import cv2
import numpy as np

class PhotoCraft:
    def __init__(self, root):
        executable=os.environ.get('REZAK_PHOTOCRAFT',r'C:\Program Files\ArtCraft\PhotoCraft\photocraft-cli.exe')
        self.p=subprocess.Popen([executable,'mcp','--automation-read-root',str(root),'--automation-write-root',str(root)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.responses=queue.Queue();self.ids=itertools.count(1)
        def read():
            for line in self.p.stdout:self.responses.put(line)
            self.responses.put(None)
        threading.Thread(target=read,daemon=True).start()
        try:
            self.request('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'rezak-covers','version':'1'}})
            self.p.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n');self.p.stdin.flush()
        except Exception:
            self.close();raise

    def request(self,method,params):
        i=next(self.ids)
        self.p.stdin.write(json.dumps({'jsonrpc':'2.0','id':i,'method':method,'params':params})+'\n');self.p.stdin.flush()
        while True:
            try:line=self.responses.get(timeout=90)
            except queue.Empty:raise RuntimeError('PhotoCraft timed out') from None
            if line is None:raise RuntimeError('PhotoCraft exited unexpectedly')
            result=json.loads(line)
            if result.get('id')==i:
                if 'error' in result:raise RuntimeError(str(result['error']))
                return result['result']

    def call(self,tool,**arguments):
        r=self.request('tools/call',{'name':tool,'arguments':arguments})
        if r.get('isError'):raise RuntimeError(str(r.get('content')))
        return r.get('structuredContent') or r.get('content')

    def cmd(self,command,**params):return self.call('command_run',id=command,params=params)

    def close(self):
        if self.p.poll() is None:self.p.terminate()
        try:self.p.wait(timeout=5)
        except subprocess.TimeoutExpired:self.p.kill();self.p.wait()

def inside(t,intervals):return any(a<=t<b for a,b in intervals)

def select_assets(source, job):
    from .framing import detect
    cap=cv2.VideoCapture(str(source))
    detector=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
    eyes=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_eye_tree_eyeglasses.xml')
    portraits=[];scenes=[]
    # Speech about a video can continue after OBS switches to fullscreen webcam.
    # Search preceding context too, but never a cut-out source interval.
    times=sorted({max(0,job['at_ms']+delta*1000) for delta in (-240,-180,-120,-60,-30,-12,-6,-3,0,3,6,12,30)
                  if inside(max(0,job['at_ms']+delta*1000),job['intervals'])})
    try:
        for t in times:
            cap.set(cv2.CAP_PROP_POS_MSEC,t);ok,im=cap.read()
            if not ok:continue
            h,w=im.shape[:2];gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
            faces=detector.detectMultiScale(gray,1.12,5,minSize=(45,45))
            for x,y,fw,fh in faces:
                facegray=gray[y:y+fh,x:x+fw]
                sharp=float(cv2.Laplacian(facegray,cv2.CV_32F).var())
                visible=len(eyes.detectMultiScale(facegray[:int(fh*.7)],1.1,3))
                corner=fw<w*.25 and (x+fw/2<w*.3 or x+fw/2>w*.7) and (y+fh/2<h*.35 or y+fh/2>h*.65)
                if corner and sharp>25:
                    portraits.append((fw*fw*(1+.1*min(visible,2)),t,im,((x+fw/2)/w,(y+fh*.57)/h,fw/w)))
                elif not corner and fw>w*.12 and visible and sharp>10:
                    top=max(0,int(y-fh*.65));bottom=min(h,int(y+fh*1.75))
                    cropw=round((bottom-top)*690/485)
                    left=max(0,min(w-cropw,round(x+fw/2-cropw/2)));right=min(w,left+cropw)
                    # Exclude the streamer overlay from the screen panel.
                    for ox,oy,ow,oh in faces:
                        if ow<w*.25 and ox+ow<w*.3 and oy<bottom and oy+oh>top:
                            left=max(left,int(ox+ow*2))
                    scenes.append((sharp*(1+3*min(visible,2)),t,im[top:bottom,left:right], [left,top,right,bottom]))
            _,content=detect(im)
            if content:
                x,y,cw,ch=round(content.x*w),round(content.y*h),round(content.w*w),round(content.h*h)
                crop=im[y:y+ch,x:x+cw]
                sharp=float(cv2.Laplacian(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),cv2.CV_32F).var())
                if sharp>35:scenes.append((sharp*.5,t,crop,[x,y,x+cw,y+ch]))
    finally:cap.release()
    # A face printed on a banner is not a reliable webcam. Require a stable track
    # across at least three distinct frames; prefer the largest track, not ad sharpness.
    portraits=[p for p in portraits if len({q[1] for q in portraits
        if abs(p[3][0]-q[3][0])<.06 and abs(p[3][1]-q[3][1])<.08})>=3]
    if not portraits or not scenes:
        raise ValueError('Нужен ручной выбор кадров: не найдена чёткая угловая вебка и отдельный экран')
    return max(portraits,key=lambda a:a[0]),max(scenes,key=lambda a:a[0])

def build_cover(root,source,video,brief,job):
    from .covers import place_portrait
    if source.is_symlink() or not source.is_file():raise ValueError('Source missing')
    portrait,screen=select_assets(source,job)
    _,pt,raw,face=portrait;_,st,scene,rect=screen
    model=cv2.dnn.readNetFromONNX(np.fromfile(Path(__file__).with_name('cover_person.onnx'),dtype=np.uint8))
    black=np.zeros((720,1280,3),np.float32);white=np.full_like(black,255)
    if not (place_portrait(black,raw,face,model) and place_portrait(white,raw,face,model)):
        raise ValueError('Portrait mask failed')
    alpha=np.clip(1-(white-black).mean(axis=2)/255,0,1)
    fg=np.dstack([np.clip(black/np.maximum(alpha[:,:,None],.02),0,255),alpha*255]).astype('uint8')
    # Same fixed layout as the approved reference; the caption never resizes the face.
    work=video.parent/(video.stem+'.cover-assets');work.mkdir(exist_ok=True)
    m=PhotoCraft(root)
    def place(name,im):
        p=work/(name+'.png');p.write_bytes(cv2.imencode('.png',im)[1].tobytes())
        m.call('doc_place',path=str(p),fit=False);m.cmd('layer.renameLayer',name=name)
    try:
        m.call('doc_new',name=video.stem,width=1280,height=720)
        yy,xx=np.mgrid[:720,:1280];glow=np.exp(-((xx-740)**2/560**2+(yy-440)**2/370**2))
        bg=np.stack([30+155*glow,8+45*glow,24+130*glow],axis=2).astype('uint8');place('background',bg)
        # Contain preserves full screen content, no distorted faces or arbitrary crop.
        scale=min(690/scene.shape[1],485/scene.shape[0]);sw,sh=round(scene.shape[1]*scale),round(scene.shape[0]*scale)
        card=np.zeros((485,690,3),np.uint8);card[:]=(24,9,30)
        card[(485-sh)//2:(485-sh)//2+sh,(690-sw)//2:(690-sw)//2+sw]=cv2.resize(scene,(sw,sh))
        card=cv2.copyMakeBorder(card,5,5,5,5,cv2.BORDER_CONSTANT,value=(230,210,239))
        panel=np.zeros((720,1280,4),np.uint8);panel[35:530,25:725,:3]=card;panel[35:530,25:725,3]=255
        place('screen',panel);m.cmd('edit.transform',rotate=-3)
        rim=cv2.dilate(fg[:,:,3],cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(9,9)))
        rgba=np.zeros_like(fg);rgba[:,:,:3]=(245,85,228);rgba[:,:,3]=np.maximum(rim,cv2.GaussianBlur(rim,(0,0),15))
        place('portrait-rim',rgba);place('streamer',fg)
        bottom_size=min(110,1100/max(6,len(brief.bottom)))
        for text,y,color in [(brief.top,645-bottom_size*.85-14,'#ffffff'),(brief.bottom,645,'#ffdf00')]:
            size=min(110,1100/max(6,len(text)))
            m.cmd('type.create',text=text.upper(),x=40,y=y,font='Arial',size=size,color=color)
            m.cmd('type.setStyle',font='Arial',fontStyle='Black',weight=900,fauxItalic=True,tracking=-55,horizontalScale=95)
            m.cmd('layer.layerStyle.stroke',size=5,position='outside',color='#190c28',opacity=100)
            m.cmd('layer.layerStyle.dropShadow',color='#10051d',opacity=100,distance=9,angle=90,size=2)
            m.cmd('edit.transform',rotate=-4,reference='center')
        m.call('doc_save',path=str(video.with_suffix('.cover.pcraft')))
        temporary=video.with_suffix('.cover.pending.jpg')
        m.call('doc_export',path=str(temporary),quality=94)
        image=cv2.imdecode(np.fromfile(temporary,dtype=np.uint8),cv2.IMREAD_COLOR)
        if image is None or image.shape[:2]!=(720,1280) or temporary.stat().st_size>2_000_000:
            raise ValueError('Invalid PhotoCraft export')
        (work/'preview-320.jpg').write_bytes(cv2.imencode('.jpg',cv2.resize(image,(320,180)))[1].tobytes())
        temporary.replace(video.with_suffix('.cover.jpg'))
        return {'portrait_ms':pt,'screen_ms':st,'screen_rect':rect,'style':'roman-reference-v2','visual_review':'not_performed'}
    finally:m.close()
