import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import ocr_client as client
from mcp_server import Server

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve();self.allowed=self.base/'allowed';self.allowed.mkdir()
        self.out=self.base/'out';self.out.mkdir()
        self.cfg=patch.object(client,'config',return_value=(self.base,Path(sys.executable),[self.allowed],self.out));self.cfg.start();self.addCleanup(self.cfg.stop)
    def test_escape_and_symlink(self):
        other=self.base/'outside.pdf';other.write_bytes(b'pdf')
        link=self.allowed/'link.pdf';link.symlink_to(other)
        for path in (other,link):
            self.assertEqual(client.invoke('start',{'filePath':str(path)})['error']['code'],'pathNotAllowed')
    def test_arguments(self):
        for name,args in [('result',{'taskId':'../x'}),('result',{'taskId':'a'*32,'pageNo':True}),('start',{'filePath':'x','engine':'unknown'}),('start',{'filePath':'x','extra':1})]:
            self.assertEqual(client.invoke(name,args)['error']['code'],'invalidArguments')
    def test_page_boundary_and_structured_table(self):
        task='a'*32;p=self.out/task;p.mkdir()
        (p/'status.json').write_text('{"status":"completed"}')
        (p/'result.json').write_text(json.dumps({'source':{'totalPages':2},'tables':[{'pageNo':2,'rows':[['1.60','MPa']]}]}))
        self.assertEqual(client.invoke('result',{'taskId':task,'pageNo':3})['error']['code'],'pageOutOfRange')
        self.assertEqual(client.invoke('result',{'taskId':task,'pageNo':2})['data']['page']['tables'][0]['rows'][0][0],'1.60')
    def test_missing_credentials_does_not_submit(self):
        f=self.allowed/'a.pdf';f.write_bytes(b'pdf')
        with patch.object(client,'runtime_info',return_value={'mineruCredentialsConfigured':False}),patch.object(client.subprocess,'Popen') as popen:
            self.assertEqual(client.invoke('start',{'filePath':str(f),'engine':'mineru'})['error']['code'],'notConfigured');popen.assert_not_called()
    def test_stdio(self):
        requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},{'jsonrpc':'2.0','method':'notifications/initialized'},{'jsonrpc':'2.0','id':2,'method':'tools/list'},{'jsonrpc':'2.0','id':3,'method':'resources/read','params':{'uri':'aicheck-ocr://skill'}}]
        p=subprocess.run([sys.executable,str(ROOT/'scripts/mcp_server.py')],input='\n'.join(map(json.dumps,requests))+'\n',capture_output=True,text=True,check=True)
        responses=list(map(json.loads,p.stdout.splitlines()));self.assertEqual(len(responses),3)
        self.assertEqual({t['name'] for t in responses[1]['result']['tools']},{'aicheck_ocr_connection','aicheck_ocr_start','aicheck_ocr_result'})
        self.assertIn('识别与审查',responses[2]['result']['contents'][0]['text'])

if __name__=='__main__':unittest.main()
