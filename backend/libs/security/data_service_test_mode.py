"""Temporary, narrowly scoped anonymous data-service testing switch.

Enable by writing `enabled` to output/data-services-noauth.enabled in the API
working directory. Remove the file to restore authentication without restart.
Anonymous OCR jobs use a shared test identity; existing users' jobs remain private.
"""
from pathlib import Path
import re

ACTOR = 'internal-data-services-test'

def enabled():
    try:
        return Path('output/data-services-noauth.enabled').read_text().strip() == 'enabled'
    except OSError:
        return False

def allows(method, path):
    if not enabled():
        return False
    if path.startswith('/api/'):
        path = path[4:]
    if method == 'GET':
        return path in {'/inspection-services/capabilities', '/inspection-services/standards'} or bool(
            re.fullmatch(r'/inspection-services/standards/[A-Za-z0-9_-]+/canonical', path)
            or re.fullmatch(r'/internal/ocr/mineru/tasks/[A-Za-z0-9_-]+(?:/result)?', path))
    return method == 'POST' and path in {
        '/inspection-services/standard-status', '/inspection-services/certificate-validity',
        '/inspection-services/certificate-registry', '/internal/ocr/mineru/tasks/upload'}
