"""Package standalone data services without inspection rules, reports or credentials."""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=('SKILL.md','安装说明.md','scripts/setup_workbuddy.py','references/platform-setup.md','references/matching.md','references/output.md',
       'scripts/data_client.py','scripts/service_transport.py','scripts/mcp_server.py')
def build():
    source=ROOT/'skills/aicheck-data-services';out=ROOT/'output/skills/aicheck-data-services.zip';out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for f in FILES:
            p=source/f
            if p.is_symlink() or not p.is_file():raise ValueError('Missing or unsafe distribution input')
            z.write(p,'aicheck-data-services/'+f)
    meta={'version':'1.1.1','archive':out.name,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),
          'files':{f:hashlib.sha256((source/f).read_bytes()).hexdigest() for f in FILES}}
    out.with_suffix('.manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    print(out)
if __name__=='__main__':build()
