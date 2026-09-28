import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('inspection_report',ROOT/'scripts/report.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


def example():return json.loads((ROOT/'references/report.example.json').read_text())


def positive():
    d=example();c=next(c for c in d['checks'] if c['method']==2)
    c.update(execution='completed',result='passed',basisVerified=True,conditionsMet=True,conditionNote='',evidenceIds=['E1'])
    d['evidence'][0]['locationVerified']=True
    for i in d['issues']:i['checkIds']=[x for x in i['checkIds'] if x!=c['id']]
    return d,c


def test_example_schema_and_methods():
    d=example();assert r.validate(d)==[]
    assert r.catalog()['R04']['methods']==list(range(1,8))
    assert r.catalog()['R16']['methods']==list(range(1,14))
    assert r.catalog()['R24']['methods']==list(range(1,7))
    jsonschema=pytest.importorskip('jsonschema');jsonschema.validate(d,json.loads((ROOT/'references/report.schema.json').read_text()))


def test_material_duplicates_and_placeholder_counts():
    d=example();d['materials'].append({**d['materials'][0],'id':'D2'});assert any('重复文件' in e for e in r.validate(d))
    d=example();d['fileCount']=25;assert any('额外字段' in e for e in r.validate(d))
    d=example();d['materials'][0]['name']='';assert r.validate(d)


def test_omitted_methods_and_unknown_nodes():
    d=example();d['checks'].pop();assert any('未交代方法' in e for e in r.validate(d))
    d=example();d['nodes']=['R99'];assert any('不受支持' in e for e in r.validate(d))


def test_conditional_pass_rejected():
    d,c=positive();assert r.validate(d)==[]
    c['conditionsMet']=False;c['conditionNote']='介质等级不明，仅在Ⅲ级时比例对应'
    assert any('肯定判定' in e for e in r.validate(d))


@pytest.mark.parametrize('period',[
    dict(validFrom=None,validUntil='2028-01-01',eventStart=None,eventEnd=None),
    dict(validFrom='2026-03-02',validUntil='2030-03-02',eventStart='2026-02-13',eventEnd='2026-02-13'),
    dict(validFrom='2028-01-01',validUntil='2026-01-01',eventStart='2026-03-01',eventEnd='2026-03-01')])
def test_date_counterexamples(period):
    d,c=positive();c['kind']='period';c['period']={**period,'evidenceIds':['E1']}
    assert r.validate(d)


def test_complete_period_positive_and_missing_period():
    d,c=positive();c['kind']='period';assert r.validate(d)
    c['period']=dict(validFrom='2024-01-01',validUntil='2028-01-01',eventStart='2026-01-01',eventEnd='2026-02-01',evidenceIds=['E1'])
    assert r.validate(d)==[]


def test_service_failure_and_missing_official_record():
    d,c=positive();c['kind']='official';assert r.validate(d)
    d['services']=[dict(id='S1',tool='certificate_registry',queriedAt='2026-09-25T00:00:00Z',status='failed',summary='503',source='cnse_platform')]
    c['serviceIds']=['S1'];assert r.validate(d)
    d['services'][0]['status']='success';assert r.validate(d)==[]


def test_bad_evidence_and_unread_file():
    d,c=positive();d['evidence'][0]['locationVerified']=False;assert r.validate(d)
    d,c=positive();d['materials'][0]['readStatus']='unread';assert r.validate(d)
    d,c=positive();d['evidence'][0]['page']=3;d['materials'][0]['pages']=2;assert r.validate(d)


def test_corrected_r24_rule_allows_evidence_based_conclusion():
    d,c=positive();c['method']=3
    other=next(x for x in d['checks'] if x is not c and x['method']==3)
    other['method']=2
    assert r.validate(d)==[]


def test_legacy_shared_rule_conflict_cannot_be_passed(tmp_path,monkeypatch):
    import hashlib
    import shutil
    shutil.copytree(ROOT/'references',tmp_path/'references')
    p=tmp_path/'references/business-nodes-v3.md'
    p.write_text(p.read_text().replace('10 表示有背面保护气','因素 10（背面不加保护气）'))
    d=example();d['ruleSha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    c=next(x for x in d['checks'] if x['method']==3)
    c.update(execution='completed',result='passed',basisVerified=True,conditionsMet=True,evidenceIds=['E1'])
    monkeypatch.setattr(r,'ROOT',tmp_path)
    assert any('规则冲突' in e for e in r.validate(d))


def test_offline_outputs_share_ids_counts_and_escape_html(tmp_path):
    d=example();d['project']='<script>alert(1)</script>';d['checks'][0]['actual']='恶意 <img src=x onerror=alert(1)> | [链接](https://example.com)'
    r.render(d,tmp_path);h=(tmp_path/'report.html').read_text();m=(tmp_path/'report.md').read_text()
    assert '<script>alert(1)</script>' not in h and '<img src=x' not in h
    assert '&lt;script&gt;' in h and '&#124;' in m
    assert '1 份唯一资料' in h and '1 份唯一资料' in m
    for c in d['checks']:assert c['id'] in h and c['id'] in m
    assert json.loads((tmp_path/'report.json').read_text())==d
    assert "connect-src 'none'" in h


def test_invalid_report_does_not_create_outputs(tmp_path):
    d,c=positive();c['conditionsMet']=False
    with pytest.raises(ValueError):r.render(d,tmp_path/'invalid')
    assert not (tmp_path/'invalid').exists()


def test_standalone_init_all_nodes_validate_and_render(tmp_path):
    p=tmp_path/'review.json';script=str(ROOT/'scripts/report.py')
    subprocess.run([sys.executable,script,'init',str(p),'--nodes',*r.catalog()],check=True,capture_output=True)
    subprocess.run([sys.executable,script,'render',str(p),'--output',str(tmp_path/'report')],check=True,capture_output=True)
    d=json.loads(p.read_text());assert len(d['checks'])==sum(len(n['methods']) for n in r.catalog().values())
    assert all(c['execution']=='not_run' for c in d['checks'])


def test_r13_license_query_is_not_type_test_verification(tmp_path):
    p=tmp_path/'review.json'
    subprocess.run([sys.executable,str(ROOT/'scripts/report.py'),'init',str(p),'--nodes','R13'],check=True,capture_output=True)
    d=json.loads(p.read_text());c=next(c for c in d['checks'] if c['method']==4)
    c.update(kind='official',execution='completed',result='passed',basisVerified=True,conditionsMet=True,serviceIds=['S1'])
    d['services']=[dict(id='S1',tool='certificate_registry',queriedAt='2026-09-25T00:00:00Z',status='success',summary='仅单位许可证查询成功',source='cnse_platform')]
    assert any('不能替代 R13' in e for e in r.validate(d))
