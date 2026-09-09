"""Local-only seeded handoff navigation acceptance server; requires backend test dependencies."""
import os
import sys
os.environ.update(AICHECK_ENABLE_DEMO_DATA='true', AICHECK_ENABLE_COMPATIBILITY_MOCKS='true',
    AICHECK_REQUIRE_AUTH='false', AICHECK_SQLITE_DISABLE='true', AICHECK_DATABASE_URL='', DATABASE_URL='',
    AICHECK_WORKSTATIONS_ENABLED='true', AICHECK_REVIEW_PAGE_RANGES_ENABLED='true')
from pathlib import Path
backend_root = Path(__file__).resolve().parents[3] / 'backend'
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / 'tests'))
import pytest
from test_review_evidence_run_integration import setup_function, test_real_route_uses_verified_handoff_and_rejects_changed_verification
patch = pytest.MonkeyPatch()
setup_function()
test_real_route_uses_verified_handoff_and_rejects_changed_verification(patch)
from libs.db.repository import repo
from libs.integrations import task_dispatcher
from libs.review_orchestrator.execution import create_review_run_from_ai_run

def dispatch(project_id, node_id, run_id, **kwargs):
    ai_run = repo.find_one('ai_runs', run_id)
    review = create_review_run_from_ai_run(ai_run, mode='inline')
    return {'mode': 'test', 'taskId': 'MANUAL-UI-' + review['reviewRunId']}
task_dispatcher.dispatch_ai_recheck = dispatch
from copy import deepcopy
from libs.contracts.responses import server_time
review = next(row for row in repo.state['review_runs'] if 'handoffInputsSnapshot' in row)
repo.state.setdefault('review_sessions', []).append({'id': 'HANDOFF-NAV-SESSION', 'tenantId': 'TENANT-DEFAULT',
 'projectId': review['projectId'], 'nodeId': 35, 'createdBy': 'USER-INSPECTION-001', 'status': 'active',
 'activeReviewRunId': review['reviewRunId'], 'createdAt': server_time()})
unknown = deepcopy(review)
unknown.update(id='HANDOFF-NAV-UNKNOWN', reviewRunId='HANDOFF-NAV-UNKNOWN', nodeId=36, inputDocumentVersionIds=['UNREADABLE-LOCAL-FIXTURE'])
repo.state['review_runs'].append(unknown)
os.environ['AICHECK_REQUIRE_AUTH'] = 'true' 
import uvicorn
from apps.api.main import app
uvicorn.run(app, host='127.0.0.1', port=4185)
