import json
from pathlib import Path

from scripts.build_inspection_standard_corpus import build
from libs.db.seed import STANDARD_KNOWLEDGE_SEED
from libs.inspection_standard_corpus import standard_state


def test_build_keeps_multiple_tables_equations_and_page_sources(tmp_path, monkeypatch):
    file = STANDARD_KNOWLEDGE_SEED['knowledgeFiles'][0]
    sidecars = tmp_path/'sidecars'
    folder = sidecars/file['id']
    folder.mkdir(parents=True)
    content = [
        {'type':'text','text':'1.1 验收正文','page_idx':0,'bbox':[0,0,500,100]},
        {'type':'table','table_body':'<table><tr><th>项目</th><th>值</th></tr><tr><td>A</td><td>10</td></tr></table>','page_idx':0,'bbox':[0,100,500,200]},
        {'type':'table','table_body':'<table><tr><th>项目</th><th>值</th></tr><tr><td>B</td><td>20</td></tr></table>','page_idx':1,'bbox':[0,100,500,200]},
        {'type':'equation','text':'P=2tS/D','text_format':'latex','page_idx':1,'bbox':[0,300,500,400]},
    ]
    (folder/'content_list.json').write_text(json.dumps(content))
    (folder/'full.md').write_text('验收正文')
    output=tmp_path/'corpus.json'
    report=build(sidecars, output)
    assert report['fileCount']==1
    assert report['layoutFallbackCount']==1
    assert report['files'][0]['sourceTables']==report['files'][0]['normalizedTables']==2
    monkeypatch.setenv('AICHECK_INSPECTION_CORPUS',str(output))
    state=standard_state({})
    record=state['standard_knowledge_records'][0]
    assert len(record['tables'])==2
    assert {item['pageNo'] for item in record['tables']}=={1,2}
    assert 'P=2tS/D' in str(record['equations'])
    assert all(source['sourceType']=='new_mineru' for table in record['tables'] for source in table['sources'])
    assert record['ocrQuality']['layoutFallback'] is True
    assert record['sidecarHashes']['content_list.json']
    assert not any(record.get('projectId') for record in state['documents'])


def test_sections_reading_order_empty_and_out_of_range(tmp_path):
    import pytest
    from scripts.build_inspection_standard_corpus import add_section_paths
    from libs.standard_knowledge_canonical import build_standard_knowledge_record
    from libs.inspection_standard_content import select_content
    from libs.inspection_services import InspectionServiceError
    from test_standard_knowledge_canonical import canonical_source_fixture
    state=canonical_source_fixture()
    parsed=state['ocr_parse_results'][0]
    parsed['layoutBlocks']=[
        {'text':'5.3 要求','pageNo':1,'blockType':'text','sourceOrder':0},
        {'text':'a) 第一项','pageNo':1,'blockType':'text','sourceOrder':1},
        {'text':'5.3.1 子条款','pageNo':1,'blockType':'text','sourceOrder':3},
        {'text':'b) 第二项','pageNo':1,'blockType':'text','sourceOrder':4},
        {'text':'5.4 下一节','pageNo':2,'blockType':'text','sourceOrder':5},
    ]
    parsed['tables']=[{'pageNo':1,'sourceOrder':2,'normalizedRows':[{'值':'10'}]}]
    add_section_paths(parsed)
    record=build_standard_knowledge_record(state,state['knowledge_files'][0]['id'],tmp_path,include_supplemental=False)
    record['pageCount']=3
    record['readingOrderBasis']='mineru_content_list_source_order'
    record['ocrQuality']={'layoutFallback':True}
    selected=select_content(record,page_no=None,section='5.3')
    assert [b['text'] for b in selected['blocks']]==['5.3 要求','a) 第一项','5.3.1 子条款','b) 第二项']
    assert len(selected['tables'])==1
    assert selected['locationQuality']['layoutFallback'] is True
    assert select_content(record,page_no=3,section=None)['selection']['reason']=='empty_page'
    assert select_content(record,page_no=None,section='999')['selection']['reason']=='section_not_located'
    with pytest.raises(InspectionServiceError) as exc:
        select_content(record,page_no=9999,section=None)
    assert exc.value.reason=='pageOutOfRange'
