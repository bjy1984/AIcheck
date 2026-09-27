"""Build a credential-free OCR Skill + stdio adapter archive."""
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FILES=('SKILL.md','references/platform-setup.md','scripts/ocr_client.py','scripts/mcp_server.py')

def main():
    target=ROOT/'output/skills/aicheck-ocr.zip';target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(ROOT/'skills/aicheck-ocr'/name,'aicheck-ocr/'+name)
    print(target)

if __name__=='__main__':main()
