from typing import Literal
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Application(Input):
    client_id:str=Field(min_length=1,max_length=512)
    client_secret:str=Field(default='',max_length=2048)


class Route(Input):
    account_id:str|None=None


class Owner(Input):
    streamer_id:str


class ReviewedRetry(Input):
    confirmed_not_sent:Literal[True]


class Upload(Input):
    filename:str
    account_ids:list[str]=Field(min_length=1,max_length=2)
    title:str=Field(min_length=1,max_length=240)
    description:str=Field(default='',max_length=5000)
    privacy:Literal['private','unlisted','public']|None=None
    made_for_kids:bool|None=None


def router(publishing):
    r=APIRouter(prefix='/api/publishing')
    def run(callback):
        try:return callback()
        except (ValueError,FileNotFoundError) as exc:raise HTTPException(400,str(exc))

    @r.get('')
    def status():return publishing.snapshot()

    @r.get('/applications')
    def config():return publishing.config()

    @r.post('/applications/{platform}')
    def configure(platform:str,value:Application):
        run(lambda:publishing.configure(platform,value.client_id,value.client_secret))
        return {'ok':True}

    @r.post('/oauth/{platform}')
    def begin(platform:str,request:Request,response:Response):
        state,url=run(lambda:publishing.begin_oauth(platform,str(request.base_url)))
        response.set_cookie('rezak_oauth_'+platform,state,max_age=600,httponly=True,samesite='lax',path='/api/publishing/oauth/'+platform)
        return {'url':url}

    @r.get('/oauth/{platform}/callback')
    def callback(platform:str,request:Request,state:str='',code:str='',error:str=''):
        # Uvicorn formats access logs after this response: do not log one-time codes.
        request.scope['query_string']=b''
        if error or not code:raise HTTPException(400,'Подключение отменено или не предоставлен код авторизации')
        try:publishing.finish_oauth(platform,state,request.cookies.get('rezak_oauth_'+platform,''),code)
        except (ValueError,KeyError) as exc:raise HTTPException(400,str(exc))
        except Exception:raise HTTPException(400,'Не удалось завершить OAuth. Проверьте настройки приложения и начните подключение заново')
        response=RedirectResponse('/#twitch',status_code=303)
        response.delete_cookie('rezak_oauth_'+platform,path='/api/publishing/oauth/'+platform)
        return response

    @r.post('/accounts/{key}/disconnect')
    def disconnect(key:str):
        run(lambda:publishing.disconnect(key));return {'ok':True}

    @r.put('/routes/{streamer_id}/{platform}')
    def route(streamer_id:str,platform:str,value:Route):
        run(lambda:publishing.bind(streamer_id,platform,value.account_id));return {'ok':True}

    @r.get('/clips/{filename}/owner')
    def owner(filename:str):return {'streamer_id':run(lambda:publishing.owner(filename))}

    @r.put('/clips/{filename}/owner')
    def assign(filename:str,value:Owner):
        run(lambda:publishing.assign(filename,value.streamer_id));return {'ok':True}

    @r.post('/jobs')
    def enqueue(value:Upload):
        return {'ids':run(lambda:publishing.enqueue(value.filename,value.account_ids,value.title,value.description,value.privacy,value.made_for_kids))}

    @r.post('/jobs/{key}/cancel')
    def cancel(key:str):run(lambda:publishing.cancel(key));return {'ok':True}

    @r.post('/jobs/{key}/retry')
    def retry(key:str):run(lambda:publishing.retry(key));return {'ok':True}

    @r.post('/jobs/{key}/review-retry')
    def reviewed_retry(key:str,value:ReviewedRetry):
        run(lambda:publishing.reviewed_retry(key));return {'ok':True}
    return r
