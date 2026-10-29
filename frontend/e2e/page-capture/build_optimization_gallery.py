"""Build the reviewed optimization evidence gallery without altering baseline captures."""
from pathlib import Path
import json
import sys
from hashlib import sha256

ROOT = Path(__file__).resolve().parents[3]
DEST = ROOT / 'docs/verification' / (sys.argv[1] if len(sys.argv) > 1 else 'uiux-optimization')
GROUPS = {'admin': '管理', 'knowledge': '知識庫', 'fde': 'FDE', 'workflows': '工作台'}
if DEST.name == 'score-followup':
    GROUPS = {'knowledge': '知識庫', 'fde': 'FDE', 'workflows': '工作台', 'ndt': '檢測資料', 'interaction': '鍵盤與窄版'}
EXPECTED_BUILD = {'uiux-followup': 'dist-uiux-followup-final', 'uiux-visual-refinement': 'dist-uiux-visual-refinement', 'role-content-focus': 'dist-role-content-focus', 'score-followup': 'dist-score-followup'}.get(DEST.name)
EXPECTED_HASH = sha256((ROOT / 'frontend' / EXPECTED_BUILD / 'index.html').read_bytes()).hexdigest() if DEST.name == 'score-followup' else None
records = []
for group, label in GROUPS.items():
    data = json.loads((DEST / group / 'manifest.json').read_text())
    for original in data['captures']:
        row = dict(original)
        row['group'] = group
        row['groupLabel'] = label
        row['build'] = row.get('build') or ('dist-uiux-release' if str(row.get('status', '')).startswith('before') else data.get('build'))
        row['route'] = row['route'].split('#')[-1]
        row['file'] = f"{group}/{Path(row['file']).name}"
        assert row.get('reviewed'), row['file']
        if EXPECTED_BUILD and not str(row.get('status', '')).startswith('before'):
            assert row.get('build') == EXPECTED_BUILD, f"Intermediate build in final gallery: {row['file']}"
            if EXPECTED_HASH:
                assert (row.get('buildIndexSha256') or data.get('buildIndexSha256')) == EXPECTED_HASH, f"Outdated build hash: {row['file']}"
                row['buildIndexSha256'] = EXPECTED_HASH
        path = DEST / row['file']
        assert path.is_file() and path.read_bytes().startswith(b'\xff\xd8\xff'), path
        records.append(row)
if EXPECTED_BUILD:
    records.sort(key=lambda row: (str(row.get('status', '')).startswith('before'), list(GROUPS).index(row['group'])))
expected = {
    'admin': ['overview','projects','org','business-packs','permission','rules','material-review-points','prompt-templates','report-templates','fine-config','integration','skill-requests','audit'],
    'knowledge': ['overview','sources','files','tasks','rules','retrieval','network','reasoning','compare','config'],
    'fde': ['dashboard','projects','ocr-quality','ai-runs','review-runs','feedback','evaluation','business-packs','capability-bundles','releases','security','incidents','costs','acceptance'],
    'workbench': ['generic','inspection','contractor','ndt','owner']
}
routes = [f'/{group}/{page}' for group, pages in expected.items() for page in pages] + ['/fde-feedback-triage','/fde-blind-review']
if DEST.name == 'score-followup':
    routes = ['/knowledge/overview', '/fde-feedback-triage'] + [f'/workbench/{role}' for role in ['inspection', 'contractor', 'ndt', 'owner']]
coverage = []
for route in routes:
    captures = [r for r in records if r['route'].split('?')[0] == route
                and not str(r.get('status', '')).startswith('before')
                and (not EXPECTED_BUILD or r.get('build') == EXPECTED_BUILD)]
    assert captures, f'Missing route {route}'
    coverage.append({'route': route, 'files': [r['file'] for r in captures]})
assert len(coverage) == (6 if DEST.name == 'score-followup' else 44)
manifest = {'environment': 'production build + real API + isolated in-memory demo data', 'routeCount': len(coverage), 'captureCount': len(records), 'coverage': coverage, 'captures': records}
(DEST / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
page = '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>AIcheck 後台優化驗證</title>
<style>*{box-sizing:border-box}body{margin:0;font-family:system-ui,sans-serif;background:#f4f6fa;color:#17243b}header,main{max-width:1500px;margin:auto;padding:26px}h1{font-size:30px;margin:0 0 10px}p{line-height:1.6}a{color:#254faf}nav{display:flex;gap:14px;flex-wrap:wrap}input,select{padding:12px;border:1px solid #b7c4d5;border-radius:6px;font:inherit}input{flex:1;min-width:230px}#grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:20px}.card{background:white;border:1px solid #d5dfeb;border-radius:10px;overflow:hidden}.card img{display:block;width:100%;aspect-ratio:16/9;object-fit:contain;background:#e9eef6}.content{padding:18px}h2{font-size:18px;margin:10px 0}.meta{font-size:13px;color:#526178;overflow-wrap:anywhere}details{margin-top:14px;line-height:1.6}summary{cursor:pointer}li{margin-top:6px}a:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid #3261c8;outline-offset:3px}</style>
<header><h1>AIcheck 後台優化驗證</h1><p>44 / 44 個後台主路由已逐頁檢視，__COUNT__ 張原始截圖。點圖可看原尺寸；本輪以隔離示例資料驗證介面與互動，沒有對正式資料執行寫入。</p><p><a href="README.md">修改與驗證紀錄</a> · <a href="../page-captures/index.html">優化前逐頁圖集</a></p><nav><input id="search" aria-label="搜尋頁面或問題" placeholder="搜尋頁面、路由、觀察"><select id="group" aria-label="選擇後台區域"><option value="all">全部區域</option><option value="admin">管理</option><option value="knowledge">知識庫</option><option value="fde">FDE</option><option value="workflows">工作台</option></select></nav><p id="count" aria-live="polite"></p></header><main id="grid"></main>
<script>const data=__DATA__;const search=document.querySelector('#search'),group=document.querySelector('#group'),grid=document.querySelector('#grid');function el(tag,text,cls){const n=document.createElement(tag);if(text)n.textContent=text;if(cls)n.className=cls;return n;}function render(){const q=search.value.toLowerCase();const rows=data.filter(r=>(group.value==='all'||r.group===group.value)&&JSON.stringify(r).toLowerCase().includes(q));document.querySelector('#count').textContent=rows.length+' 張截圖';grid.replaceChildren();for(const r of rows){const card=el('article',null,'card'),link=el('a');link.href=r.file;link.target='_blank';link.rel='noopener';const img=el('img');img.src=r.file;img.alt=r.title;img.loading='lazy';link.append(img);card.append(link);const box=el('div',null,'content');box.append(el('div',r.groupLabel+(String(r.status||'').startsWith('before')?' · 修前對照':' · 最終版已確認'),'meta'),el('h2',r.title),el('div',r.route,'meta'));if(r.reviewNote)box.append(el('p',r.reviewNote));const d=el('details');d.append(el('summary','驗證範圍與限制'));for(const key of ['issues','limitations']){const items=Array.isArray(r[key])?r[key]:r[key]?[r[key]]:[];if(items.length){const ul=el('ul');items.forEach(t=>ul.append(el('li',t)));d.append(ul);}}if(r.viewport)d.append(el('p',JSON.stringify(r.viewport),'meta'));box.append(d);card.append(box);grid.append(card);}}search.addEventListener('input',render);group.addEventListener('change',render);render();</script></html>'''
payload = json.dumps(records, ensure_ascii=False).replace('<', '\\u003c')
if DEST.name == 'uiux-followup':
    page = page.replace('AIcheck 後台優化驗證', 'AIcheck 後台後續修復驗證')
    page = page.replace('../page-captures/index.html', '../uiux-optimization/index.html')
    page = page.replace('優化前逐頁圖集', '上一輪逐頁圖集')
    page = page.replace('__COUNT__ 張原始截圖。', '__COUNT__ 張原始截圖（含修前對照）。')
if DEST.name == 'uiux-visual-refinement':
    page = page.replace('AIcheck 後台優化驗證', 'AIcheck 狀態、圖標與圖表優化驗證')
    page = page.replace('../page-captures/index.html', '../uiux-followup/index.html')
    page = page.replace('優化前逐頁圖集', '上一輪逐頁圖集')
if DEST.name == 'role-content-focus':
    page = page.replace('AIcheck 後台優化驗證', 'AIcheck 角色內容精簡驗證')
    page = page.replace('../page-captures/index.html', '../uiux-visual-refinement/index.html')
    page = page.replace('優化前逐頁圖集', '上一輪逐頁圖集')
if DEST.name == 'score-followup':
    page = page.replace('AIcheck 後台優化驗證', 'AIcheck 評分後修復驗證')
    page = page.replace('44 / 44 個後台主路由已逐頁檢視', '本輪 6 / 6 個重點頁面已逐頁檢視，另驗證共用工具列、搜尋及上傳抽屜，包含桌面、中窄版及手機尺寸')
    page = page.replace('../page-captures/index.html', '../role-content-focus/index.html')
    page = page.replace('優化前逐頁圖集', '上一輪完整 44 頁圖集')
    page = page.replace('__COUNT__ 張原始截圖。', '__COUNT__ 張原始截圖（含修前對照）。')
    page = page.replace('<option value="admin">管理</option>', '')
    page = page.replace('<option value="workflows">工作台</option>', '<option value="workflows">工作台</option><option value="ndt">檢測資料</option><option value="interaction">鍵盤與窄版</option>')
(DEST / 'index.html').write_text(page.replace('__DATA__', payload).replace('__COUNT__', str(len(records))))
(DEST / 'coverage.md').write_text('# 逐頁覆蓋清單\n\n' + '\n'.join(f"- `{r['route']}`：" + '、'.join(f'[截圖 {i+1}]({path})' for i,path in enumerate(r['files'])) for r in coverage) + '\n')
print(json.dumps({'routes': len(coverage), 'captures': len(records), 'gallery': str(DEST / 'index.html')}, ensure_ascii=False))
