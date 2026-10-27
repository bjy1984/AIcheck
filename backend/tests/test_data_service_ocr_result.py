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

def test_processed_page_result_keeps_document_fields_and_unverified_seals(monkeypatch):
 job={'id':'J','provider':'mineru','requestedBy':'alice','parseResultId':'P','status':'success'}
 parsed={'id':'P','profileId':'welder_certificate_v1','outcomeStatus':'partial',
         'pages':[{'pageNo':1},{'pageNo':2}],
         'fields':[{'fieldCode':'name','value':'测试人员'}, {'fieldCode':'date','pageNo':2,'value':'2026-10-01'}],
         'seals':[{'pageNo':1,'sealName':'测试单位','recognized':False,'requiresHumanConfirmation':True}],
         'quality':{'status':'needs_human_review','missingFields':['certificate_no']},
         'metadata':{'postProcessing':{'profileExtraction':'applied'},'artifactReferences':{'secret':'internal'},'apiKey':'secret'},
         'diagnostics':[{'code':'seal_vision_reading','level':'info','detail':{'secret':'hidden'}}]}
 monkeypatch.setattr(m,'load_state',lambda *a:None)
 monkeypatch.setattr(m,'repo',SimpleNamespace(find_one=lambda *a:job,state={'ocr_parse_results':[parsed]}))
 data=m.get_mineru_task_result(req('alice'),'J',1)['data']
 assert data['fields']==[] and data['documentFields'][0]['value']=='测试人员'
 assert data['seals'][0]['recognized'] is False and data['seals'][0]['requiresHumanConfirmation']
 assert data['quality']['missingFields']==['certificate_no'] and data['scope']['quality']=='document'
 assert data['profileId']=='welder_certificate_v1' and data['processing']['rawProviderOutput'] is False
 assert data['processing']['provenanceAvailable']
 assert 'secret' not in json.dumps(data)
 assert data['diagnostics']==[{'code':'seal_vision_reading','level':'info'}]
