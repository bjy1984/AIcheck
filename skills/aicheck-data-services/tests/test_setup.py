import importlib.util
import json
import os
from pathlib import Path
import pytest

S = Path(__file__).resolve().parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('setup_workbuddy', S/'setup_workbuddy.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_private_configuration_with_spaces_and_unicode(tmp_path):
    root = tmp_path/'工程 资料'; root.mkdir()
    token_file = tmp_path/'private'/'token.txt'
    out = tmp_path/'settings.json'
    m.generate('https://example.com', [root, root], token_file, out, 'test-secret')
    cfg = json.loads(out.read_text())['mcpServers'][m.NAME]
    assert json.loads(cfg['env']['AICHECK_DATA_ALLOWED_ROOTS']) == [str(root)]
    assert 'test-secret' not in out.read_text()
    assert token_file.read_text().strip() == 'test-secret'
    if os.name != 'nt':
        assert token_file.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        m.generate('https://example.com', [root], token_file, out)
    assert token_file.read_text().strip() == 'test-secret'


@pytest.mark.parametrize('url', ['http://example.com','https://user:pass@example.com','https://example.com?token=x','file:///tmp/test'])
def test_invalid_url_no_writes(tmp_path, url):
    with pytest.raises(ValueError):
        m.generate(url,[tmp_path],tmp_path/'token',tmp_path/'config','secret')
    assert list(tmp_path.iterdir()) == []


def test_existing_token_not_overwritten(tmp_path):
    token = tmp_path/'token';token.write_text('original')
    with pytest.raises(FileExistsError):
        m.generate('https://example.com',[tmp_path],token,tmp_path/'config','changed')
    assert token.read_text() == 'original'
    assert not (tmp_path/'config').exists()


def test_live_stdio_check_reports_failure_without_credentials(tmp_path,capsys):
    # Closed loopback port exercises actual subprocess protocol, not a mocked tool call.
    out = tmp_path/'config.json'
    m.generate('http://127.0.0.1:1',[tmp_path],tmp_path/'token',out,'hidden-test-token')
    assert m.check(out) == 1
    text = capsys.readouterr().out
    assert 'networkError' in text
    assert 'hidden-test-token' not in text
