"""Compile the reviewed CUA captures into an offline gallery and route index."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[3]
DEST = ROOT / "docs/verification/page-captures"
GROUPS = {"admin": "管理", "knowledge": "知識庫", "fde": "FDE", "workflows": "工作台", "auth": "帳號頁"}
records = []
for group, label in GROUPS.items():
    data = json.loads((DEST / group / "manifest.json").read_text())
    captures = data if isinstance(data, list) else data["captures"]
    for row in captures:
        item = dict(row)
        item["group"] = group
        item["groupLabel"] = label
        item["route"] = item["route"].split("#")[-1]
        item["file"] = f"{group}/{Path(item['file']).name}"
        if item.get("supersededBy"):
            item["originalStatus"] = item["status"]
            item["status"] = "superseded"
        item["title"] += f" · {item['section']}" if item.get("section") else ""
        for field in ("issues", "limitations"):
            value = item.get(field, [])
            item[field] = [value] if isinstance(value, str) and value else value or []
        if not isinstance(data, list):
            item.setdefault("viewport", data.get("viewport", data.get("defaultViewport")))
        file = DEST / item["file"]
        assert file.is_file(), file
        assert file.read_bytes().startswith(b"\xff\xd8\xff"), f"Not JPEG: {file}"
        records.append(item)

expected = {
    "admin": ["overview", "projects", "org", "business-packs", "permission", "rules", "material-review-points", "prompt-templates", "report-templates", "fine-config", "integration", "skill-requests", "audit"],
    "knowledge": ["overview", "sources", "files", "tasks", "rules", "retrieval", "network", "reasoning", "compare", "config"],
    "fde": ["dashboard", "projects", "ocr-quality", "ai-runs", "review-runs", "feedback", "evaluation", "business-packs", "capability-bundles", "releases", "security", "incidents", "costs", "acceptance"],
    "workbench": ["generic", "inspection", "contractor", "ndt", "owner"],
}
routes = [f"/{group}/{page}" for group, pages in expected.items() for page in pages]
routes.extend(["/fde-feedback-triage", "/fde-blind-review"])
assert len(routes) == 44
coverage = []
for route in routes:
    options = [r for r in records if r["route"].split("?")[0] == route and r["status"] not in ("before_fix", "superseded")]
    assert options, f"Missing route: {route}"
    main_fde = re.compile(r"fde/\d{2}-(dashboard|projects|ocr-quality|ai-runs|review-runs|feedback|evaluation|business-packs|capability-bundles|releases|security|incidents|costs|acceptance|feedback-triage|blind-review)\.jpg$")
    options.sort(key=lambda r: 0 if "enabled" in r["file"] or main_fde.fullmatch(r["file"]) else 1)
    coverage.append({"route": route, "file": options[0]["file"], "title": options[0]["title"], "status": options[0]["status"]})

(DEST / "manifest.json").write_text(json.dumps({"backendRoutes": 44, "authRoutes": 4, "captureCount": len(records), "coverage": coverage, "captures": records}, ensure_ascii=False, indent=2))
payload = json.dumps(records, ensure_ascii=False).replace("<", "\\u003c")
document = r'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AIcheck 後台逐頁截圖</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f6f8;color:#182335;font:15px/1.65 system-ui,-apple-system,sans-serif}header,main{max-width:1440px;margin:auto;padding:28px}h1{font-size:28px;margin:0 0 8px}p{margin:8px 0;color:#4f5d70}.summary{display:flex;gap:24px;margin:20px 0}.summary b{font-size:28px;color:#142944}.summary span{display:block;font-size:13px}.toolbar{position:sticky;top:0;z-index:2;background:#f5f6f8ee;backdrop-filter:blur(8px);padding:16px 0;display:flex;gap:12px;flex-wrap:wrap}input,select,button{font:inherit;border:1px solid #b9c4d2;border-radius:6px;background:white;padding:9px 12px;color:inherit}input{min-width:280px;flex:1}button{cursor:pointer}a{color:#1755b8}#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:22px}.card{background:white;border:1px solid #d9e0e9;border-radius:8px;overflow:hidden}.card>a{display:block;background:#e9edf2}.card img{display:block;width:100%;aspect-ratio:16/10;object-fit:contain}.body{padding:16px}h2{font-size:17px;line-height:1.45;margin:8px 0}.route{font:12px/1.5 ui-monospace,monospace;overflow-wrap:anywhere;color:#5c6776}.badge{font-size:12px;padding:3px 8px;border-radius:4px;background:#eaf0f8;color:#334a68}.fixed{background:#e4f4e9;color:#226b39}.limited{background:#fff0d9;color:#835415}.before{background:#f5e7e7;color:#903d3d}details{font-size:13px;margin-top:10px;border-top:1px solid #edf0f5;padding-top:8px}summary{cursor:pointer;color:#344e71}ul{padding-left:20px;margin:8px 0}.caption{font-size:13px;color:#66748a}#count{align-self:center;white-space:nowrap;font-size:13px}footer{padding:32px;text-align:center;font-size:13px;color:#607088}@media(max-width:600px){header,main{padding:18px}#grid{grid-template-columns:1fr}input{min-width:180px}.summary{gap:18px}}
</style>
<header><p>AIcheck · 2026-10-28 / 29</p><h1>後台逐頁截圖確認</h1><p>完整介面建置、實際 API、隔離記憶體示例資料。每張原始 JPEG 已由代理逐張目視檢查；點圖可看原始尺寸。</p>
<div class="summary"><div><b>44 / 44</b><span>後台主路由（含 1 個別名）</span></div><div><b>4 / 4</b><span>登入與帳號頁</span></div><div><b>__COUNT__</b><span>截圖，含子頁、詳情與前後證據</span></div></div>
<p><strong>已修復：</strong>登入重置路由造成歸因與盲審 404；修復後重新登入、點實際入口確認，118 個前端測試檔通過。</p>
<p>這次確認的是畫面、可達性、主要操作與空／錯誤狀態。沒有把未配置的 OCR、AI、正式物件儲存或示例缺失原文算作流程通過。各張「觀察與限制」保留未解問題。</p>
<p><a href="README.md">閱讀總報告與 44 頁對照表</a> · <a href="manifest.json">完整紀錄 JSON</a></p></header>
<main><div class="toolbar"><input id="search" aria-label="搜尋頁名、路由或問題" placeholder="搜尋頁名、路由或問題"><select id="group" aria-label="頁面分組"><option value="">全部分組</option><option value="admin">管理</option><option value="knowledge">知識庫</option><option value="fde">FDE</option><option value="workflows">工作台</option><option value="auth">帳號頁</option></select><select id="scope" aria-label="證據狀態"><option value="current">目前畫面</option><option value="all">包含修復／環境調整前</option><option value="prior">只看調整前證據</option></select><span id="count"></span></div><div id="grid"></div></main><footer>桌面尺寸依各圖紀錄；沒有執行業務提交、發布或部署。圖片未經加工。</footer>
<script>
const data=__DATA__;const search=document.querySelector('#search'),group=document.querySelector('#group'),scope=document.querySelector('#scope'),grid=document.querySelector('#grid');
const prior=r=>r.status==='before_fix'||r.status==='superseded';
function badge(r){if(prior(r))return ['調整前證據','before'];if(r.status==='fixed')return ['修復後已重驗','fixed'];if(/limited|partial|blocked|disabled/.test(r.status))return ['含環境／資料限制','limited'];if(/issues|observations|warning/.test(r.status))return ['已檢視・有觀察','limited'];return ['已檢視',''];}
function node(tag,text,cls){const e=document.createElement(tag);if(text)e.textContent=text;if(cls)e.className=cls;return e;}
function render(){const q=search.value.trim().toLowerCase();const rows=data.filter(r=>(!group.value||r.group===group.value)&&(!q||JSON.stringify(r).toLowerCase().includes(q))&&(scope.value==='all'||(scope.value==='prior'?prior(r):!prior(r))));grid.replaceChildren();document.querySelector('#count').textContent=rows.length+' 張';for(const r of rows){const card=node('article',null,'card'),a=node('a');a.href=r.file;a.target='_blank';a.rel='noopener';const img=node('img');img.src=r.file;img.alt=r.title;img.loading='lazy';a.append(img);card.append(a);const body=node('div',null,'body'),[label,cls]=badge(r);body.append(node('span',r.groupLabel+' · '+label,'badge '+cls),node('h2',r.title),node('div',r.route,'route'));const details=node('details'),issues=r.issues||[],limits=r.limitations||[];details.append(node('summary','觀察與限制（'+(issues.length+limits.length)+'）'));for(const [title,items]of[['觀察',issues],['限制',limits]]){if(items.length){details.append(node('strong',title));const ul=node('ul');items.forEach(s=>ul.append(node('li',s)));details.append(ul);}}if(r.viewport)details.append(node('p',JSON.stringify(r.viewport),'caption'));if(r.reviewNote)details.append(node('p',r.reviewNote,'caption'));body.append(details);card.append(body);grid.append(card);}}
[search,group,scope].forEach(e=>e.addEventListener('input',render));render();
</script></html>'''
(DEST / "index.html").write_text(document.replace("__DATA__", payload).replace("__COUNT__", str(len(records))))
table = "\n".join(f"| `{r['route']}` | [{r['title']}]({r['file']}) | 已檢視，詳見分組限制 |" for r in coverage)
report = f'''# 後台逐頁截圖確認

已完成 **44/44 個後台主路由**（43種內容，overview是projects別名），另補4個帳號頁，整理 **{len(records)} 張原始JPEG**，包含子視圖、詳情、對話框和調整前證據。每張已目視；[開啟可搜尋截圖圖庫](index.html)。

使用目前工作區完整production建置＋真實API，後端為隔離記憶體示例資料。管理視窗1470×748/DPR2，知識與FDE通常1280×720，工作台1470×692/DPR2；圖譜另有全屏補圖。沒有宣稱完成手機版、正式資料庫或外部服務的端到端驗收。

## 本輪確認並修復

登入會呼叫resetRouter，常駐FDE獨立路由未列入保留名單，導致「打開反饋歸因隊列／打開獨立盲審」落到404。已保留父子路由，並同時保留加入項目和規範舊連結。實際登入、點入口重驗通過；回歸測試修前117通過/1失敗，修後118通過/0失敗。修復後建置成功。主圖片為修復後；before-404僅作歷史證據。

監檢初次截圖的403與未啟用提示來自截圖環境。核對後啟用工位功能，僅放行會自動初始化的空會話端點（記憶體、不調模型），在4183重新登入重拍；舊圖以superseded標示。其餘業務寫入仍由隔離服務拒絕。

## 已確認但仍待處理的畫面問題

- **資料語意：**FDE示例評估報告沒有caseSummary.cases，畫面補成「樣本0」卻同時顯示通過率100%。已對照seed與模板，不能把未知補零。建設方歸檔摘要與列表的示例資料也有口徑差異。
- **表格可讀性：**通用工作台雙欄表格、管理細項配置與部分FDE表格在目前寬度截斷欄位或需橫向捲動；發布狀態production_approved拆行。
- **定位與導覽：**知識庫共用摘要佔據大部分首屏；管理168筆審查點缺少就地搜尋／篩選，部分使用者清單也不易定位。
- **用詞與資訊：**組織類型、FDE狀態、能力差異鍵名直接呈現內部代碼。通用工作台證據／人工確認主要是數量，逐筆辦理入口不足。
- **圖譜：**預設與全屏仍有密集標籤重疊。
- **待進一步查證：**規範整體治理缺口與部分零切片行的「正常」口徑、報告模板是否需提供派生草稿的完整流程，未僅憑截圖修改。

## 環境與資料限制

部分規範PDF預覽白區、原文NOT_FOUND、OCR parse result未提供，均留有詳情證據；目前不能宣稱原文預覽成功。沒有執行真實AI、OCR、評測、上傳、發布、改密或授權提交。空列表已確認有提示與下一步，但不能代表有資料時完整流程通過。

分組紀錄：[管理](admin/README.md) · [知識庫](knowledge/README.md) · [FDE](fde/README.md) · [工作台](workflows/README.md) · [完整逐圖JSON](manifest.json)。原始圖片未加工，圖庫可以顯示調整前的錯誤證據。

## 44個後台路由對照

| 路由 | 截圖 | 結果 |
| --- | --- | --- |
{table}

## 帳號頁補圖

[登入](auth/login.jpg) · [加入項目](auth/join.jpg) · [首次改密](auth/change-password.jpg) · [授權頁](auth/skill-authorize.jpg)。註冊連結、首次改密旗標與授權payload為明示的隔離示例；沒有提交。
'''
(DEST / "README.md").write_text(report)
print(json.dumps({"backendRoutes":len(coverage),"captures":len(records),"groups":{g:sum(r['group']==g for r in records) for g in GROUPS}}))
