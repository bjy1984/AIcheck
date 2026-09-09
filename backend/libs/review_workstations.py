"""Versioned station ownership and immutable per-node review capabilities."""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from libs.review_document_scope import freeze_document_scope, validate_document_scope
from libs.review_orchestrator.tool_scope import ALWAYS_AVAILABLE_TOOLS

REGISTRY = Path(__file__).resolve().parents[1] / 'config/workstations/registry.json'


class WorkstationConfigurationError(ValueError):
    """A missing or inconsistent station must never become an all-purpose agent."""


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def node_number(value: Any) -> int:
    if isinstance(value, bool) or not str(value).isdigit() or not 1 <= int(value) <= 69:
        raise WorkstationConfigurationError('invalid_workstation_node')
    return int(value)


def load_registry(path: Path = REGISTRY) -> dict[str, Any]:
    asset = json.loads(path.read_text())
    if asset.get('schemaVersion') != 'workstations-v1' or not asset.get('version'):
        raise WorkstationConfigurationError('invalid_workstation_registry_version')
    seen_nodes: set[int] = set()
    seen_stations: set[str] = set()
    for station in asset.get('stations') or []:
        station_id = station.get('id')
        if station_id not in set('ABCDEFGHI') or station_id in seen_stations:
            raise WorkstationConfigurationError('duplicate_or_unknown_workstation')
        seen_stations.add(station_id)
        if not station.get('nodeIds') or not station.get('promptVersion'):
            raise WorkstationConfigurationError('workstation_nodes_or_prompt_version_missing')
        for value in station['nodeIds']:
            number = node_number(value)
            if number in seen_nodes:
                raise WorkstationConfigurationError('duplicate_node_owner')
            seen_nodes.add(number)
        prompt_path = (path.parent / station['promptFile']).resolve()
        if not prompt_path.is_relative_to(path.parent.resolve()):
            raise WorkstationConfigurationError('prompt_path_outside_registry')
        station['systemPrompt'] = prompt_path.read_text()
        if not station['systemPrompt'].strip():
            raise WorkstationConfigurationError('workstation_prompt_empty')
    if seen_nodes != set(range(1, 70)) or seen_stations != set('ABCDEFGHI'):
        raise WorkstationConfigurationError('incomplete_workstation_coverage')
    return asset


def freeze_station(node_id: Any, pack: dict[str, Any], catalog: list[dict[str, Any]],
                   *, registry: dict[str, Any] | None = None) -> dict[str, Any]:
    asset = registry if registry is not None else load_registry()
    number = node_number(node_id)
    if pack.get('id') != asset['businessPackId']:
        raise WorkstationConfigurationError('workstation_business_pack_mismatch')
    station = next((row for row in asset['stations'] if number in row['nodeIds']), None)
    if station is None:
        raise WorkstationConfigurationError('node_owner_missing')
    rule_ids = {row['sourceRuleId'] for row in pack.get('atomicChecks') or [] if row.get('nodeId') == number}
    bindings = [row for row in pack.get('atomicCheckToolBindings') or [] if row.get('sourceRuleId') in rule_ids]
    checks = {row['id'] for row in pack.get('atomicChecks') or [] if row.get('nodeId') == number}
    if not checks or {row['atomicCheckId'] for row in bindings} != checks:
        raise WorkstationConfigurationError('node_bindings_incomplete')
    available = {row['name'] for row in catalog}
    required = {name for row in bindings for name in row.get('tools') or []}
    if not required or required - available:
        raise WorkstationConfigurationError('node_tools_missing')
    snapshot = {
        'schemaVersion': 'workstation-run-v1', 'stationId': station['id'],
        'stationName': station['name'], 'routeVersion': asset['version'],
        'promptVersion': station['promptVersion'], 'systemPrompt': station['systemPrompt'],
        'businessPackId': asset['businessPackId'], 'targetNodeId': number,
        'ownedNodeIds': list(station['nodeIds']), 'ruleIds': sorted(rule_ids),
        'atomicCheckIds': sorted(checks), 'bindingsHash': digest(bindings),
        'allowedTools': sorted(required | (ALWAYS_AVAILABLE_TOOLS & available)),
    }
    snapshot['snapshotHash'] = digest(snapshot)
    return deepcopy(snapshot)


def station_snapshot(review_run: dict[str, Any]) -> dict[str, Any] | None:
    validate_document_scope(review_run)
    snapshot = review_run.get('workstationSnapshot')
    if snapshot is None:
        return None  # Historical runs retain their original execution contract.
    if not isinstance(snapshot, dict) or snapshot.get('schemaVersion') != 'workstation-run-v1':
        raise WorkstationConfigurationError('invalid_workstation_snapshot')
    content = {key: value for key, value in snapshot.items() if key != 'snapshotHash'}
    if digest(content) != snapshot.get('snapshotHash'):
        raise WorkstationConfigurationError('workstation_snapshot_hash_mismatch')
    if node_number(review_run.get('nodeId')) != snapshot['targetNodeId'] or snapshot['targetNodeId'] not in snapshot['ownedNodeIds']:
        raise WorkstationConfigurationError('workstation_target_mismatch')
    if review_run.get('businessPackId') != snapshot['businessPackId']:
        raise WorkstationConfigurationError('workstation_snapshot_pack_mismatch')
    return deepcopy(snapshot)


def scope_catalog(review_run: dict[str, Any], catalog: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    snapshot = station_snapshot(review_run)
    if snapshot is None:
        raise WorkstationConfigurationError('workstation_snapshot_missing')
    names = set(snapshot['allowedTools'])
    if names - {item['name'] for item in catalog}:
        raise WorkstationConfigurationError('frozen_workstation_tools_unavailable')
    return [item for item in catalog if item['name'] in names], {
        'scoped': True, 'reason': 'frozen_workstation_node_capabilities',
        'stationId': snapshot['stationId'], 'snapshotHash': snapshot['snapshotHash'],
        'nodeId': snapshot['targetNodeId'], 'toolCount': len(names),
    }


def tool_allowed(review_run: dict[str, Any], tool_name: str) -> bool:
    snapshot = station_snapshot(review_run)
    return snapshot is None or tool_name in snapshot['allowedTools']


def apply_station_messages(review_run: dict[str, Any], messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace legacy roles; retain node procedure as task data, never a second identity."""
    snapshot = station_snapshot(review_run)
    if snapshot is None:
        return messages
    output = [{'role': 'system', 'content': snapshot['systemPrompt']}]
    for message in messages:
        if message.get('role') == 'system':
            procedure = re.sub(r'^你是.*?Agent[。．]?', '', str(message.get('content') or '')).strip()
            if procedure:
                output.append({'role': 'user', 'content': json.dumps({'targetNodeId': snapshot['targetNodeId'], 'nodeProcedure': procedure}, ensure_ascii=False)})
            continue
        output.append(deepcopy(message))
    return output


def initialize_run_workstation(record, project, published_rule, catalog, hash_payload, *, state=None):
    from libs.business_pack import load_business_pack, matching_rule_for_node
    from libs.review_condition_mapping import initialize_condition_mapping
    from libs.review_handoff_inputs import initialize_handoff_inputs
    from libs.review_rule_snapshot import freeze_effective_rule

    station_pack = deepcopy(project.get("businessPackSnapshot") or load_business_pack(record["businessPackId"]))
    if record.get("atomicCheckToolBindingsSnapshot"):
        station_pack["atomicCheckToolBindings"] = record["atomicCheckToolBindingsSnapshot"]
    effective_rule = published_rule or matching_rule_for_node(station_pack, int(record["nodeId"]))
    record["documentScopeSnapshot"] = freeze_document_scope(record, state)
    record["inputDocumentVersionIds"] = deepcopy(record["documentScopeSnapshot"]["documentVersionIds"])
    if "documentPageRanges" in record["documentScopeSnapshot"]:
        record["inputDocumentPageRanges"] = deepcopy(record["documentScopeSnapshot"]["documentPageRanges"])
    record["effectiveRuleSnapshot"] = freeze_effective_rule(record, effective_rule)
    record["ruleSetVersion"] = effective_rule.get("version") or record["ruleSetVersion"]
    record["workstationSnapshot"] = freeze_station(record["nodeId"], station_pack, catalog)
    record["allowedTools"] = record["workstationSnapshot"]["allowedTools"]
    record["inputHash"] = hash_payload({"legacyInputHash": record["inputHash"], "documents": record["documentScopeSnapshot"]["snapshotHash"], "workstation": record["workstationSnapshot"]["snapshotHash"], "effectiveRule": record["effectiveRuleSnapshot"]["snapshotHash"]})

    initialize_condition_mapping(record, state)
    initialize_handoff_inputs(record, state)

def workstation_argument_scope_error(review_run: dict[str, Any], arguments: dict[str, Any]) -> str | None:
    if station_snapshot(review_run) is None:
        return None
    for key in ("projectId", "nodeId"):
        if key in arguments and str(arguments[key]) != str(review_run.get(key)):
            return "WORKSTATION_ARGUMENT_SCOPE_MISMATCH"
    allowed = {str(value) for value in review_run.get("inputDocumentVersionIds") or []}
    pending = [arguments]
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key == "documentVersionIds":
                    if not isinstance(item, list) or any(not isinstance(ref, str) or ref not in allowed for ref in item):
                        return "WORKSTATION_DOCUMENT_SCOPE_MISMATCH"
                elif key == "documentVersionId":
                    if not isinstance(item, str) or item not in allowed:
                        return "WORKSTATION_DOCUMENT_SCOPE_MISMATCH"
                elif isinstance(item, (list, dict)):
                    pending.append(item)
    return None
