from starlette.requests import Request
from libs.security.data_service_test_mode import allows, ACTOR
from apps.api.mineru_ocr_routes import mineru_job_access_error, request_actor

def test_switch_scope_and_existing_job_protection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert not allows('GET','/api/inspection-services/capabilities')
    (tmp_path/'output').mkdir(); flag=tmp_path/'output/data-services-noauth.enabled';flag.write_text('enabled')
    assert allows('GET','/api/inspection-services/capabilities')
    assert allows('POST','/api/internal/ocr/mineru/tasks/upload')
    for method,path in [('GET','/api/admin/users'),('GET','/api/projects'),('DELETE','/api/internal/ocr/mineru/tasks/x'),('POST','/api/internal/ocr/mineru/tasks')]:
        assert not allows(method,path)
    req=Request({'type':'http','method':'GET','path':'/api/internal/ocr/mineru/tasks/x/result','headers':[]})
    assert request_actor(req)[0]==ACTOR
    assert mineru_job_access_error(req,{'requestedBy':'system'}) is not None
    assert mineru_job_access_error(req,{'requestedBy':ACTOR}) is None
    assert mineru_job_access_error(req,{'requestedBy':ACTOR,'documentId':'private'}) is not None
    flag.unlink();assert not allows('GET','/api/inspection-services/capabilities')


def test_anonymous_ocr_ignores_stale_token_before_tenant_selection(tmp_path, monkeypatch):
    import asyncio
    from fastapi.responses import JSONResponse
    from apps.api import main

    monkeypatch.chdir(tmp_path)
    (tmp_path / 'output').mkdir()
    (tmp_path / 'output/data-services-noauth.enabled').write_text('enabled')
    request = Request({'type': 'http', 'method': 'GET',
                       'path': '/api/internal/ocr/mineru/tasks/test/result',
                       'headers': [(b'authorization', b'Bearer stale-other-tenant-token')]})

    def unexpected_decode(_):
        raise AssertionError('Anonymous test requests must not decode stale credentials')

    async def capture(request, call_next, *, predecoded_claims, tenant_id):
        assert predecoded_claims is None
        assert tenant_id == main.configured_tenant_id()
        return JSONResponse({'ok': True})

    monkeypatch.setattr(main, 'decode_token', unexpected_decode)
    monkeypatch.setattr(main, 'handle_request', capture)
    response = asyncio.run(main.attach_operation_id(request, None))
    assert response.status_code == 200
