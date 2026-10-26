"""Per-export titles, source-based trims and recoverable deletion."""
import json
import re
import threading
import uuid
from pathlib import Path
from .plan import EditPlan

class ClipLibrary:
    def __init__(self, data):
        self.data=Path(data).resolve()
        self.exports=self.data/'exports'
        self.trash=self.data/'trash'
        self.lock=threading.RLock()

    def path(self, filename):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+\.mp4',filename):raise FileNotFoundError('Ролик не найден')
        path=self.exports/filename
        if path.is_symlink() or not path.is_file() or path.resolve().parent!=self.exports.resolve():raise FileNotFoundError('Ролик не найден')
        return path

    def metadata(self,path):
        sidecar=path.with_suffix('.edit.json')
        return json.loads(sidecar.read_text(encoding='utf-8')) if sidecar.exists() else {}

    def rename(self,filename,title):
        with self.lock:
            path=self.path(filename)
            metadata={**self.metadata(path),'title':title,'title_origin':'manual'}
            for key in ('title_quote','title_evidence','title_version'):metadata.pop(key,None)
            self.write_metadata(path,metadata)
        return metadata

    def write_metadata(self,path,value):
        target=path.with_suffix('.edit.json')
        if target.is_symlink():raise ValueError('Недопустимый файл метаданных')
        temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(target)

    def supersede_horizontal(self,source_id,filename):
        target=self.path(filename)
        plan=EditPlan.model_validate_json(target.with_suffix('.plan.json').read_text(encoding='utf-8'))
        if plan.source_id!=source_id or plan.profile!='horizontal':raise ValueError('Invalid replacement montage')
        for path in self.exports.glob(source_id+'-*.mp4'):
            if path==target:continue
            old=EditPlan.model_validate_json(path.with_suffix('.plan.json').read_text(encoding='utf-8'))
            if old.profile=='horizontal':self.write_metadata(path,{**self.metadata(path),'superseded_by':target.name})

    def supersede_shorts(self,source_id,filenames):
        if not filenames:return
        target=self.path(filenames[0]);keep=set(filenames)
        for path in self.exports.glob(source_id+'-*.mp4'):
            if path.name in keep:continue
            old=EditPlan.model_validate_json(path.with_suffix('.plan.json').read_text(encoding='utf-8'))
            if old.profile=='vertical':self.write_metadata(path,{**self.metadata(path),'superseded_by':target.name})

    def trimmed_plan(self,filename,start_ms,end_ms):
        path=self.path(filename)
        plan=EditPlan.model_validate_json(path.with_suffix('.plan.json').read_text(encoding='utf-8'))
        total=sum(s.end_ms-s.start_ms for s in plan.segments)
        if start_ms<0 or end_ms>total or end_ms-start_ms<250:raise ValueError('Выберите интервал не короче 0,25 с в пределах ролика')
        segments=[];offset=0
        for segment in plan.segments:
            length=segment.end_ms-segment.start_ms
            left=max(start_ms,offset);right=min(end_ms,offset+length)
            if left<right:segments.append(segment.model_copy(update={'start_ms':segment.start_ms+left-offset,'end_ms':segment.start_ms+right-offset}))
            offset+=length
        result=plan.model_dump();result['segments']=[s.model_dump() for s in segments]
        return EditPlan.model_validate(result)

    @staticmethod
    def identity(path):
        plan=json.loads(path.with_suffix('.plan.json').read_text(encoding='utf-8'))
        return ClipLibrary.plan_identity(plan)

    @staticmethod
    def plan_identity(plan):
        parsed=EditPlan.model_validate(plan)
        return json.dumps([parsed.source_id,parsed.profile,[s.model_dump() for s in parsed.segments]],sort_keys=True)

    def delete(self,filename):
        return self.delete_many([filename])

    def delete_many(self,filenames):
        with self.lock:
            if not filenames or len(filenames)>100:raise ValueError('Выберите от 1 до 100 роликов')
            identities={self.identity(self.path(name)) for name in filenames}
            # The gallery collapses duplicate renders; remove that whole displayed group.
            group=[]
            for path in self.exports.glob('*.mp4'):
                try:
                    if self.identity(path) in identities:group.append(self.path(path.name))
                except (ValueError,KeyError,OSError):continue
            files=[]
            for path in group:
                for item in [path,*[path.with_suffix(ext) for ext in ('.plan.json','.probe.json','.edit.json')]]:
                    if item.exists():
                        if item.is_symlink() or item.resolve().parent!=self.exports.resolve():raise ValueError('Недопустимый путь ролика')
                        files.append(item)
            token=uuid.uuid4().hex;directory=self.trash/token;directory.mkdir(parents=True)
            (directory/'manifest.json').write_text(json.dumps({'files':[p.name for p in files]}),encoding='utf-8')
            moved=[]
            try:
                for item in files:item.replace(directory/item.name);moved.append(item)
            except OSError:
                for item in moved:(directory/item.name).replace(item)
                raise
            return {'token':token,'copies':len(group),'selected':len(set(filenames))}

    def restore(self,token):
        if not re.fullmatch(r'[a-f0-9]{32}',token):raise FileNotFoundError('Запись корзины не найдена')
        with self.lock:
            directory=self.trash/token
            manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
            names=manifest['files']
            if any(Path(name).name!=name or (self.exports/name).exists() for name in names):raise ValueError('Нельзя восстановить: имя файла занято')
            moved=[]
            try:
                for name in names:
                    item=directory/name
                    if item.is_symlink() or item.resolve().parent!=directory.resolve():raise ValueError('Недопустимый путь корзины')
                    item.replace(self.exports/name);moved.append(name)
            except (OSError,ValueError):
                for name in moved:(self.exports/name).replace(directory/name)
                raise
            (directory/'manifest.json').unlink();directory.rmdir()
            return {'ok':True}
