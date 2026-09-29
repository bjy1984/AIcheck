from types import SimpleNamespace
import json
from starlette.requests import Request
from apps.api import mineru_ocr_routes as m

def req(user):
 r=Request({'type':'http','method':'GET','path':'/','headers':[(b'x-user-id',user.encode()),(b'x-role',b'inspection')]})
 r.state.operation_id='TEST';return r

def test_owned_page_result_and_wrong_user(monkeypatch):
 job={'id':'J','provider':'mineru','requestedBy':'alice','parseResultId':'P','status':'completed'}
 parsed={'id':'P','pages':[{'pageNo':1,'text':'one'},{'pageNo':2,'text':'two'}],'tables':[{'pageNo':2,'text':'table'}]}
 monkeypatch.setattr(m,'load_state',lambda *a:None)
 monkeypatch.setattr(m,'repo',SimpleNamespace(find_one=lambda *a:job,state={'ocr_parse_results':[parsed]}))
 result=m.get_mineru_task_result(req('alice'),'J',2)
 assert result['data']['pages']==[{'pageNo':2,'text':'two'}]
 assert result['data']['resultAvailable']
 denied=m.get_mineru_task_result(req('bob'),'J',2)
 assert json.loads(denied.body)['code']!=0
 assert m.get_mineru_task_result(req('alice'),'J',99).status_code==400
 job['parseResultId']=None
 assert m.get_mineru_task_result(req('alice'),'J')['data']['resultAvailable'] is False
