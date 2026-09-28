#!/usr/bin/env python3
"""Offline report validator/renderer. Python stdlib only; never calls a service."""
import argparse
import hashlib
import html
import json
import re
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT = {'passed':'符合','failed':'不符合','warning':'预警','insufficient':'证据不足','manual':'需人工核查','not_applicable':'不适用','pending':'未判定'}
EXECUTION = {'not_run':'未执行','completed':'已完成','failed':'执行失败','waiting':'待补充'}
KINDS = {'recognize':'待识别','supply':'待补资料','retry':'查询待重试','basis':'依据待核实','rectify':'待整改'}
PRIORITY = {'high':'优先处理','medium':'后续处理','low':'一般提示'}


def catalog():
    text = (ROOT/'references/business-nodes-v3.md').read_text()
    result = {}
    for match in re.finditer(r'^## (R\d+)｜([^\n]+)\n(.*?)(?=^## R|\Z)', text, re.M | re.S):
        body = match[3].split('**备注', 1)[0]
        result[match[1]] = {'name':match[2], 'methods': sorted(set(map(int,re.findall(r'^(\d+)、',body,re.M))))}
    return result


def shape(value, spec, schema, path='$'):
    """Validate exactly the JSON Schema subset used by the bundled contract."""
    if '$ref' in spec:
        spec = schema['$defs'][spec['$ref'].split('/')[-1]]
    errors = []
    types = {'object':lambda v:isinstance(v,dict),'array':lambda v:isinstance(v,list),
             'string':lambda v:isinstance(v,str),'integer':lambda v:type(v) is int,
             'boolean':lambda v:type(v) is bool,'null':lambda v:v is None}
    allowed = spec.get('type', [])
    if isinstance(allowed,str):allowed=[allowed]
    if allowed and not any(types[t](value) for t in allowed):return [f'{path}: 类型错误']
    if 'const' in spec and value != spec['const']:errors.append(f'{path}: 版本或固定值错误')
    if 'enum' in spec and value not in spec['enum']:errors.append(f'{path}: 未知枚举值')
    if isinstance(value,dict):
        for key in spec.get('required',[]):
            if key not in value:errors.append(f'{path}.{key}: 缺少字段')
        for key,v in value.items():
            if key not in spec.get('properties',{}):errors.append(f'{path}.{key}: 不接受额外字段')
            else:errors.extend(shape(v,spec['properties'][key],schema,f'{path}.{key}'))
    if isinstance(value,list):
        if len(value)<spec.get('minItems',0):errors.append(f'{path}: 条目不足')
        if spec.get('uniqueItems') and len({json.dumps(v,sort_keys=True) for v in value})!=len(value):errors.append(f'{path}: 重复条目')
        for i,v in enumerate(value):errors.extend(shape(v,spec['items'],schema,f'{path}[{i}]'))
    if isinstance(value,str):
        if len(value.strip())<spec.get('minLength',0):errors.append(f'{path}: 不得为空')
        if spec.get('pattern') and not re.fullmatch(spec['pattern'],value):errors.append(f'{path}: 格式错误')
        if spec.get('format')=='date-time':
            try:
                if datetime.fromisoformat(value.replace('Z','+00:00')).tzinfo is None:raise ValueError()
            except ValueError:errors.append(f'{path}: 查询时间须包含日期、时间和时区')
        if spec.get('format')=='date':
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError()
                date.fromisoformat(value)
            except ValueError:errors.append(f'{path}: 日期须为有效 YYYY-MM-DD')
    if type(value) is int and value<spec.get('minimum',value):errors.append(f'{path}: 数值太小')
    return errors


def validate(data):
    schema=json.loads((ROOT/'references/report.schema.json').read_text())
    errors=shape(data,schema,schema)
    if errors:return errors
    rules=catalog()
    digest=hashlib.sha256((ROOT/'references/business-nodes-v3.md').read_bytes()).hexdigest()
    if data['ruleSha256']!=digest:errors.append('规则版本与随包 v3 不一致，须先核对规则差异')
    maps={}
    all_ids={'summary','nodes','actions','materials',*('node-'+n for n in data['nodes'])}
    for key in ('materials','evidence','services','checks','issues'):
        maps[key]={}
        for row in data[key]:
            if row['id'] in all_ids:errors.append(f"{row['id']}: ID 重复（全报告唯一）")
            all_ids.add(row['id']);maps[key][row['id']]=row
    paths=set();hashes=set()
    for row in data['materials']:
        path=str(Path(row['path']))
        if path in paths or (row['sha256'] and row['sha256'] in hashes):errors.append(f"{row['id']}: 重复文件路径或内容，请合并资料引用")
        paths.add(path);hashes.add(row['sha256'])
        if not row['sha256'] and not row['hashReason'].strip():errors.append(f"{row['id']}: 缺少无法取得哈希的原因")
    for row in data['evidence']:
        m=maps['materials'].get(row['materialId'])
        if not m:errors.append(f"{row['id']}: 资料引用不存在")
        elif row['page'] and m['pages'] and row['page']>m['pages']:errors.append(f"{row['id']}: 页码越界")
    for node in data['nodes']:
        if node not in rules:errors.append(f'{node}: 不受支持的节点');continue
        found={c['method'] for c in data['checks'] if c['node']==node}
        missing=set(rules[node]['methods'])-found
        if missing:errors.append(f'{node}: 未交代方法 {sorted(missing)}，须显式记录未执行项')
    for c in data['checks']:
        prefix=c['id']+': '
        if c['node'] not in data['nodes'] or c['method'] not in rules.get(c['node'],{}).get('methods',[]):errors.append(prefix+'节点或方法超出范围')
        for field,target in [('evidenceIds','evidence'),('serviceIds','services')]:
            for key in c[field]:
                if key not in maps[target]:errors.append(prefix+f'引用不存在 {key}')
        if c['node']=='R13' and c['method']==4 and c['result']=='passed' and any(maps['services'].get(key,{}).get('tool')=='certificate_registry' for key in c['serviceIds']):
            errors.append(prefix+'人员/单位许可证查询不能替代 R13 型式试验登记核验')
        conclusive=c['result'] in {'passed','failed','not_applicable'}
        if conclusive:
            if c['execution']!='completed' or not c['basisVerified'] or not c['conditionsMet']:errors.append(prefix+'肯定判定缺少已完成核查、已核实依据或满足的条件')
            if not c['evidenceIds']:errors.append(prefix+'肯定判定缺少证据')
            for key in c['evidenceIds']:
                e=maps['evidence'].get(key,{})
                m=maps['materials'].get(e.get('materialId'),{})
                if not e.get('locationVerified') or m.get('readStatus')=='unread':errors.append(prefix+'证据未可靠定位或资料未读取')
            for key in c['serviceIds']:
                if maps['services'].get(key,{}).get('status')!='success':errors.append(prefix+'依赖的服务尚未成功，不能作肯定判定')
        if not c['conditionsMet'] and not c['conditionNote'].strip():errors.append(prefix+'须说明未满足的判定条件')
        if c['kind']=='period' and 'period' not in c:errors.append(prefix+'日期覆盖核查必须填写 period，缺日期用 null')
        if c['kind']=='official' and c['result']=='passed' and not c['serviceIds']:errors.append(prefix+'官方核验通过须关联成功服务记录')
        period=c.get('period')
        if period:
            for key in period['evidenceIds']:
                if key not in maps['evidence'] or key not in c['evidenceIds']:errors.append(prefix+'日期证据不存在或未关联至本核查')
            vals=[period[k] for k in ('validFrom','validUntil','eventStart','eventEnd')]
            if vals[0] and vals[1] and vals[0]>vals[1]:errors.append(prefix+'证件起止日期倒置')
            if vals[2] and vals[3] and vals[2]>vals[3]:errors.append(prefix+'施工/制造日期倒置')
            if c['result']=='passed' and (not all(vals) or not period['evidenceIds'] or not(vals[0]<=vals[2]<=vals[3]<=vals[1])):errors.append(prefix+'日期区间不完整或不覆盖，不能判通过')
        # Known shared-rule conflict must stay unresolved until the rule source is fixed.
        if c['node']=='R24' and c['method'] in (3,5) and conclusive and '因素 10（背面不加保护气）' in (ROOT/'references/business-nodes-v3.md').read_text():
            errors.append(prefix+'R24 工艺因素共享规则冲突尚未修订；方法3/5不得整体作肯定判定')
    linked=set()
    for issue in data['issues']:
        for key in issue['checkIds']:
            linked.add(key)
            c=maps['checks'].get(key)
            if not c:errors.append(issue['id']+': 核查引用不存在')
            elif c['result'] in {'passed','not_applicable'}:errors.append(issue['id']+': 待处理事项不能关联通过/不适用项')
    for c in data['checks']:
        if c['result'] not in {'passed','not_applicable'} and c['id'] not in linked:errors.append(c['id']+': 未完成或问题项缺少处理事项')
    return errors


def node_rows(data):
    rules=catalog();rows=[]
    for node in data['nodes']:
        checks=[c for c in data['checks'] if c['node']==node]
        total=len(rules[node]['methods'])
        done=sum(all(c['execution']=='completed' for c in checks if c['method']==m) for m in rules[node]['methods'])
        results={c['result'] for c in checks}
        verdict='不符合' if 'failed' in results else ('符合' if 'passed' in results and results<={'passed','not_applicable'} else '不适用' if results=={'not_applicable'} else '待处理／未完成')
        rows.append([node,rules[node]['name'],f'{done}/{total} 方法执行完成',verdict])
    return rows


def sections(data):
    """Shared presentation model: no independently authored summary conclusions."""
    rows=node_rows(data);checks={c['id']:c for c in data['checks']}
    priorities={'high':0,'medium':1,'low':2}
    issues=sorted(data['issues'],key=lambda i:(priorities[i['priority']],i['id']))
    yield 'summary','审查摘要',['项目：'+data['project'],'报告日期：'+data['reportDate'],data['scopeNote'],
        f"本次 {len(data['materials'])} 份唯一资料 · {len(rows)} 个节点 · {len(issues)} 项待处理事项",
        '结构与一致性校验通过；不代表原件真实性、技术判断或工程验收通过。',
        '优先处理：'+'；'.join(i['id']+' '+i['title'] for i in issues[:5])],[],[]
    yield 'nodes','节点总览',[],['节点','名称','执行覆盖','业务结论'],rows
    for node in data['nodes']:
        yield 'node-'+node,node+' '+catalog()[node]['name'],[],[],[]
        for c in sorted((c for c in data['checks'] if c['node']==node),key=lambda c:(c['result']=='passed',c['method'])):
            lines=[f"{c['node']} 方法 {c['method']} · {c['object']}",f"执行：{EXECUTION[c['execution']]} ｜ 结果：{RESULT[c['result']]}",
                   '实际：'+c['actual'],'要求／依据：'+c['requirement'],'条件与限制：'+(c['conditionNote'] or '已按记录核查适用条件'),
                   '证据：'+('、'.join(c['evidenceIds']) or '尚无可定位证据'),'辅助服务：'+('、'.join(c['serviceIds']) or '未依赖服务结果')]
            if c.get('period'):
                period=c['period']
                lines.append('日期比较：证件有效区间 '+(period['validFrom'] or '待核实')+' 至 '+(period['validUntil'] or '待核实')+'；施工／制造区间 '+(period['eventStart'] or '待核实')+' 至 '+(period['eventEnd'] or '待核实'))
            yield c['id'],c['id']+' '+c['title'],lines,[],[]
    yield 'actions','处理清单',[],['编号','类型／优先级','问题','关联核查','下一步','完成条件'],[
        [i['id'],KINDS[i['kind']]+'／'+PRIORITY[i['priority']],i['title'],'、'.join(i['checkIds']),i['action'],i['completion']] for i in issues]
    yield 'materials','资料与哈希附录',['规则 SHA-256：'+data['ruleSha256']],['编号','文件','路径','读取状态','页数','SHA-256／不可获取原因'],[
        [m['id'],m['name'],m['path'],{'read':'已读取','partial':'部分读取','unread':'待识别'}[m['readStatus']],str(m['pages'] or '未知'),m['sha256'] or m['hashReason']] for m in data['materials']]
    for e in data['evidence']:
        yield e['id'],'证据 '+e['id'],['资料：'+e['materialId'],'原件物理页：'+str(e['page'] or '未定位页码'),'定位：'+e['locator'],'摘录：'+e['quote'],'定位状态：'+('已核对' if e['locationVerified'] else '待核对')],[],[]
    for s in data['services']:
        yield s['id'],'服务记录 '+s['id'],[s['tool']+' · '+s['queriedAt'],'执行结果：'+s['status'],'来源：'+s['source'],s['summary']],[],[]


def render(data, output):
    errors=validate(data)
    if errors:raise ValueError('\n'.join(errors))
    parts=list(sections(data));known={p[0] for p in parts};known.update(m['id'] for m in data['materials']);known.update(i['id'] for i in data['issues'])
    def escaped(value,md=False):
        value=html.escape(str(value))
        if md:value=value.replace('|','&#124;').replace('\n','<br>').replace('*','&#42;').replace('`','&#96;').replace('[','&#91;').replace(']','&#93;')
        return value
    def mdlinks(value):
        return re.sub(r'\b[A-Za-z][A-Za-z0-9_-]*\b', lambda m:f'[{m[0]}](#{m[0]})' if m[0] in known else m[0], escaped(value,True))
    def links(value):
        # Only internally generated IDs become links, never document-supplied URLs.
        return re.sub(r'\b[A-Za-z][A-Za-z0-9_-]*\b',lambda m:f'<a href="#{m[0]}">{m[0]}</a>' if m[0] in known else m[0],escaped(value))
    md=['# 监检辅助审查报告',''];body=[]
    check_ids={c['id'] for c in data['checks']}
    group_open=False
    for anchor,title,lines,headers,rows in parts:
        md += [f'<a id="{anchor}"></a>',f'## {escaped(title,True)}','']+[mdlinks(line)+'  ' for line in lines]+['']
        content=''.join('<p>'+links(line)+'</p>' for line in lines)
        if headers:
            md+=['| '+' | '.join(map(lambda x:escaped(x,True),headers))+' |','| '+' | '.join('---' for _ in headers)+' |']
            for row in rows:
                cells=[mdlinks(v) for v in row]
                if anchor in {'materials','actions'}:cells[0]=f'<a id="{row[0]}"></a>'+cells[0]
                md.append('| '+' | '.join(cells)+' |')
            md.append('')
            content+='<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+escaped(h)+'</th>' for h in headers)+'</tr></thead><tbody>'
            for row in rows:
                rid=f' id="{row[0]}"' if anchor in {'materials','actions'} else ''
                content+='<tr'+rid+'>'+''.join('<td>'+links(v)+'</td>' for v in row)+'</tr>'
            content+='</tbody></table></div>'
        if anchor.startswith('node-'):
            if group_open:body.append('</details>')
            body.append(f'<details class="node-group" data-node="{anchor[5:]}" id="{anchor}" open><summary>{escaped(title)}</summary>')
            group_open=True
            continue
        if anchor=='actions' and group_open:
            body.append('</details>');group_open=False
        if anchor in check_ids:
            check=next(c for c in data['checks'] if c['id']==anchor)
            body.append(f'<details class="check" data-node="{check["node"]}" data-result="{check["result"]}" id="{anchor}" open><summary>{escaped(title)} <span class="badge {check["result"]}">{RESULT[check["result"]]}</span></summary>{content}</details>')
        else:body.append(f'<section id="{anchor}"><h2>{escaped(title)}</h2>{content}</section>')
    template=(ROOT/'assets/report.html').read_text()
    document=template.replace('<!--OPTIONS-->',''.join(f'<option value="{n}">{n}</option>' for n in data['nodes'])).replace('<!--BODY-->','\n'.join(body))
    output.mkdir(parents=True,exist_ok=True)
    (output/'report.html').write_text(document)
    (output/'report.md').write_text('\n'.join(md)+'\n')
    (output/'report.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['init','validate','render'])
    parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--nodes',nargs='+',default=['R24'])
    args=parser.parse_args()
    if args.command=='init':
        if args.input.exists():parser.error('不覆盖已有输入文件')
        rules=catalog()
        if any(n not in rules for n in args.nodes):parser.error('未知节点')
        data={'schemaVersion':'inspection-report@1','project':'待填写工程名称','reportDate':date.today().isoformat(),'scopeNote':'待填写本次文件和节点范围',
              'ruleSha256':hashlib.sha256((ROOT/'references/business-nodes-v3.md').read_bytes()).hexdigest(),'nodes':list(dict.fromkeys(args.nodes)),
              'materials':[],'evidence':[],'services':[],'checks':[],'issues':[]}
        for node in data['nodes']:
            ids=[]
            for method in rules[node]['methods']:
                key=f'C-{node}-{method}';ids.append(key)
                data['checks'].append(dict(id=key,node=node,method=method,kind='comparison',object='待确定核查对象',title=f'方法 {method} 尚未执行',execution='not_run',result='pending',actual='未核查',requirement='随包 v3 对应方法，适用依据尚待核实',basisVerified=False,conditionsMet=False,conditionNote='尚未执行，不能形成业务结论',evidenceIds=[],serviceIds=[]))
            data['issues'].append(dict(id='I-'+node,checkIds=ids,priority='high',kind='basis',title=node+' 待开展逐项审查',action='读取本次资料并逐项取证',completion='全部方法均有真实执行记录及问题处理安排'))
        args.input.parent.mkdir(parents=True,exist_ok=True);args.input.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');print('已生成待核查清单，不代表已审查');return
    try:
        data=json.loads(args.input.read_text());errors=validate(data)
        if errors:
            print(json.dumps({'ok':False,'errors':errors},ensure_ascii=False,indent=2));raise SystemExit(1)
        if args.command=='render':
            if not args.output:parser.error('render 需要 --output')
            render(data,args.output)
        print(json.dumps({'ok':True,'scope':'结构和明确的一致性关系；不验证原件或专业结论'},ensure_ascii=False))
    except (OSError,ValueError,KeyError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False));raise SystemExit(1)

if __name__=='__main__':main()
