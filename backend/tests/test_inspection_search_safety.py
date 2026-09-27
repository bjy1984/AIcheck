import pytest
from libs.inspection_standard_identity import identity_check, matches_requested_identity
from libs.knowledge_retrieval import standard_refs_from_text, strict_lexical_match
from scripts.build_inspection_standard_corpus import add_section_paths


def test_quantities_appendices_and_toc_do_not_pollute_hierarchy():
    texts = ['5.3 试验要求', '1.25 倍设计压力', '1.50 MPa', '后续试验说明',
             '附录 A（规范性附录）', '附录引导文字', 'A.1 适用范围', 'a) 子项',
             '附录 B', 'B.1 方法', '参考文献', '其他文字', '目次', '5.3 试验……12']
    blocks = [dict(text=text, sourceOrder=i, blockType='text') for i, text in enumerate(texts)]
    # Even a bogus OCR heading marker must not convert a pressure into a clause.
    blocks[2]['headingLevel'] = 1
    add_section_paths({'layoutBlocks': blocks})
    assert [b['sectionPath'] for b in blocks] == [
        ['5','5.3'], ['5','5.3'], ['5','5.3'], ['5','5.3'], ['A'], ['A'],
        ['A','A.1'], ['A','A.1'], ['B'], ['B','B.1'], [], [], [], []]
    assert 'clauseNo' not in blocks[1] and 'clauseNo' not in blocks[2]


@pytest.mark.parametrize('query,text,expected', [
    ('工业管道 压力试验', '工业管道应开展压力试验', True),
    ('工业管道 压力试验', '工业管道的制造', False),
    ('zzz不存在的东西qqq', '东西', False),
    ('zzz不存在 标准', '标准要求', False),
    ('无损检测 表', '无损检测方法', True),
    ('标准 表', '标准表格', False),
    ('焊接 材料', '焊接材料', True),
    ('WPS', 'WPS 焊接', True),
    ('WPS', 'NEWPS', False),
])
def test_lexical_requires_meaningful_phrases(query, text, expected):
    assert bool(strict_lexical_match(query, text)) is expected


def fixture_record(code='GB/T 8163', cover='GB/T 8163—2018', edition='2018'):
    return {'identity': {'standardCode': {'value':code, 'sources':[
        {'value':code,'sourceType':'new_mineru','pageNo':1}]}},
        'version':{'edition': {'value':edition}},
        'blocks':[{'text':cover,'pageNo':1}]}


def test_identity_needs_independent_version_and_ignores_citations():
    file = {'fileName':'GBT 8163-2018 输送流体用无缝钢管.pdf'}
    check = identity_check(file, fixture_record())
    assert check['status'] == 'verified'
    assert matches_requested_identity(standard_refs_from_text('GB/T 8163-2018'), check)
    for record in [fixture_record(code='GB 50235-2010'),
                   fixture_record(cover='GB/T 8163-2008'), fixture_record(edition='2008')]:
        check = identity_check(file, record)
        assert check['status'] == 'conflict'
        assert not matches_requested_identity(standard_refs_from_text('GB/T 8163-2018'), check)
    record = fixture_record(cover='代替 GB/T 8163—2008')
    record['blocks'].append({'text':'GB/T 8163—2018','pageNo':10})
    assert identity_check(file, record)['status'] == 'unverified'
    assert identity_check(file, None)['status'] == 'unverified'
    record = fixture_record(code='GB/T 8163-2018', cover='')
    record['identity']['standardCode']['sources'][0]['sourceType'] = 'filename_inference'
    assert identity_check(file, record)['status'] == 'unverified'


def test_filename_replacement_annotation_is_not_file_identity():
    file = {'fileName':'NB_T 47013.8-2012 泄漏检测（已被NB_T 47013.8-2025替代）.pdf'}
    record = fixture_record(code='NB/T 47013.8-2012', cover='NB/T 47013.8-2012', edition='2012')
    check = identity_check(file, record)
    assert check['status'] == 'verified'
    assert matches_requested_identity(standard_refs_from_text('NB/T 47013.8-2012'), check)
    assert not matches_requested_identity(standard_refs_from_text('NB/T 47013.8-2025'), check)


def test_canonical_builder_does_not_reintroduce_rejected_quantity(tmp_path):
    from test_standard_knowledge_canonical import canonical_source_fixture
    from libs.standard_knowledge_canonical import build_standard_knowledge_record
    from libs.inspection_standard_content import select_content
    state = canonical_source_fixture()
    parsed = state['ocr_parse_results'][0]
    parsed['layoutBlocks'] = [dict(text=text, pageNo=1, sourceOrder=i, blockType='text')
        for i, text in enumerate(['5.3 压力要求', '1.25 倍设计压力', '附录 A', 'A.1 附录要求'])]
    add_section_paths(parsed)
    record = build_standard_knowledge_record(state, state['knowledge_files'][0]['id'], tmp_path, include_supplemental=False)
    assert not select_content(record, page_no=None, section='1.25')['selection']['contentFound']
    assert any(b['text']=='1.25 倍设计压力' for b in select_content(record, page_no=None, section='5.3')['blocks'])
    assert select_content(record, page_no=None, section='A.1')['clauses']
