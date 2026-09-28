"""Explicit selection metadata for the public review original-content contract."""
from __future__ import annotations
from libs.inspection_services import InspectionServiceError

CONTENT_KEYS = ('sections','clauses','blocks','tables','equations','images','seals')


def select_content(record: dict, *, page_no: int | None, section: str | None) -> dict:
    from apps.api.knowledge_admin_routes import scoped_standard_canonical
    page_count = record.get('pageCount')
    if page_no is not None and (page_no < 1 or (page_count is not None and page_no > page_count)):
        raise InspectionServiceError(f'页码超出范围：请求 {page_no}，总页数 {page_count}。', reason='pageOutOfRange')
    scoped = scoped_standard_canonical(record, include_blocks=True, include_history=False,
                                       section=section, page_no=page_no, content_group=None)
    counts={key:len(scoped.get(key,[])) for key in CONTENT_KEYS}
    found=any(counts.values())
    scoped['selection']={'pageNo':page_no,'section':section,'pageCount':page_count,
        'contentFound':found,'counts':counts,
        'reason':None if found else 'section_not_located' if section else 'empty_page' if page_no else 'empty_document'}
    scoped['readingOrderBasis']=record.get('readingOrderBasis','unavailable')
    scoped['locationQuality']={'bboxAvailable':any(item.get('bbox') for key in CONTENT_KEYS for item in scoped.get(key,[])),
                               'layoutFallback':record.get('ocrQuality',{}).get('layoutFallback',False),
                               'hierarchyBasis':record.get('hierarchyBasis','explicit_fields_only')}
    return scoped
