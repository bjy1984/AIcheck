from __future__ import annotations

from datetime import date
from typing import Any, Callable
from uuid import uuid4

from libs.raw_vault import (
    RawCapture,
    RawCaptureContext,
    capture_tool_error,
    capture_tool_request,
    capture_tool_result,
)


ToolRunner = Callable[[str, dict[str, Any]], dict[str, Any]]


def compile_node_tool_plan(
    pack: dict[str, Any],
    source_rule_id: str,
    *,
    available_tools: set[str],
    require_published: bool = False,
) -> list[dict[str, Any]]:
    binding_set = pack.get("atomicCheckToolBindingSet") or {}
    lifecycle_status = str(binding_set.get("lifecycleStatus") or "draft").lower()
    pilot_rules = {str(item) for item in binding_set.get("pilotRules") or [] if item}
    if require_published and lifecycle_status != "published" and source_rule_id not in pilot_rules:
        raise ValueError(
            "Formal review requires published atomic check tool bindings or an explicitly enabled "
            f"pilot rule; current status is {lifecycle_status}, sourceRuleId is {source_rule_id}."
        )
    bindings = [
        item
        for item in pack.get("atomicCheckToolBindings") or []
        if isinstance(item, dict) and str(item.get("sourceRuleId")) == source_rule_id
    ]
    plan = []
    for binding in bindings:
        tools = [str(item) for item in binding.get("tools") or []]
        missing = [item for item in tools if item not in available_tools]
        plan.append(
            {
                "atomicCheckId": binding.get("atomicCheckId"),
                "sourceRuleId": source_rule_id,
                "requiredFacts": list(binding.get("requiredFacts") or []),
                "tools": tools,
                "parameters": dict(binding.get("parameters") or {}),
                "outputSchema": binding.get("outputSchema"),
                "implementationStatus": binding.get("implementationStatus"),
                "bindingSetVersion": binding_set.get("version"),
                "bindingSetLifecycleStatus": lifecycle_status,
                "pilotRuleEnabled": source_rule_id in pilot_rules,
                "compilable": not missing,
                "missingTools": missing,
            }
        )
    return plan


def execute_node_tool_plan(
    plan: list[dict[str, Any]],
    *,
    tool_runner: ToolRunner,
    facts: dict[str, Any] | None = None,
    tool_arguments: dict[str, dict[str, Any]] | None = None,
    document_version_ids: list[str] | None = None,
    evidence_facts: list[dict[str, Any]] | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
    raw_capture: RawCapture | None = None,
    raw_context: RawCaptureContext | None = None,
    turn: int | None = None,
) -> dict[str, Any]:
    facts = facts or {}
    tool_arguments = tool_arguments or {}
    document_version_ids = document_version_ids or []
    atomic_results = []
    for item in plan:
        if not item.get("compilable"):
            atomic_results.append(
                {
                    "atomicCheckId": item.get("atomicCheckId"),
                    "result": "evidence_insufficient",
                    "toolResults": [],
                    "warnings": [f"unregistered_tools:{','.join(item.get('missingTools') or [])}"],
                }
            )
            continue
        outputs = []
        for tool_name in item.get("tools") or []:
            arguments = build_tool_arguments(
                tool_name,
                item,
                facts=facts,
                explicit=tool_arguments.get(tool_name) or {},
                document_version_ids=document_version_ids,
                evidence_facts=evidence_facts or [],
                evidence_refs=evidence_refs or [],
            )
            tool_call_id = f"TOOL-{uuid4().hex[:16].upper()}"
            capture_context = (
                RawCaptureContext(**{**raw_context.__dict__, "turn": turn})
                if raw_context is not None and turn is not None
                else raw_context
            )
            if capture_context is not None:
                capture_tool_request(
                    raw_capture,
                    capture_context,
                    tool_name,
                    arguments,
                    provider_tool_call_id=tool_call_id,
                )
            try:
                output = tool_runner(tool_name, arguments)
            except Exception as exc:
                if capture_context is not None:
                    capture_tool_error(
                        raw_capture,
                        capture_context,
                        tool_name,
                        exc,
                        provider_tool_call_id=tool_call_id,
                    )
                raise
            if capture_context is not None:
                capture_tool_result(
                    raw_capture,
                    capture_context,
                    tool_name,
                    output,
                    provider_tool_call_id=tool_call_id,
                )
            outputs.append(output)
        atomic_results.append(
            {
                "atomicCheckId": item.get("atomicCheckId"),
                "result": aggregate_tool_results(outputs),
                "toolResults": outputs,
                "warnings": [],
            }
        )
    return {
        "result": aggregate_atomic_results(atomic_results),
        "atomicResults": atomic_results,
        "summary": summarize(atomic_results),
    }


def build_tool_arguments(
    tool_name: str,
    binding: dict[str, Any],
    *,
    facts: dict[str, Any],
    explicit: dict[str, Any],
    document_version_ids: list[str],
    evidence_facts: list[dict[str, Any]],
    evidence_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    arguments = {**dict(binding.get("parameters") or {}), **explicit}
    if tool_name in {
        "get_document_ocr_result",
        "extract_document_fields",
        "extract_table_records",
        "recognize_signatures_and_seals",
        "locate_evidence_fragment",
        "extract_welder_certificate",
    }:
        arguments.setdefault("documentVersionIds", document_version_ids)
    if tool_name == "validate_evidence_grounding":
        arguments.setdefault("facts", evidence_facts)
        arguments.setdefault("evidenceRefs", evidence_refs)
        return arguments
    if tool_name == "check_document_set_completeness":
        document_set = nested_dict(facts, "designDocumentSet")
        arguments.setdefault("catalogListedDocumentTypes", document_set.get("catalogListedDocumentTypes") or [])
        arguments.setdefault("uploadedDocumentTypes", document_set.get("uploadedDocumentTypes") or [])
        arguments.setdefault("parseableDocumentTypes", document_set.get("parseableDocumentTypes") or [])
    if tool_name == "evaluate_design_document_approval":
        document_container = "calculationDocuments" if str(arguments.get("argumentProfile") or "").startswith("r06_") else "designDocuments"
        arguments.setdefault("documents", nested_dict(facts, document_container).get("documents") or [])
        arguments.setdefault("pipelines", project_pipeline_facts(facts))
    if tool_name == "evaluate_calculation_document_consistency":
        arguments.setdefault("documents", nested_dict(facts, "calculationDocuments").get("documents") or [])
    if tool_name in {"evaluate_design_change_approval", "verify_design_license_seals"}:
        changes = nested_dict(facts, "designChanges") or nested_dict(facts, "designChange")
        arguments.setdefault("hasDesignChanges", changes.get("hasDesignChanges"))
        arguments.setdefault("documents", changes.get("documents") or [])
        if tool_name == "evaluate_design_change_approval":
            arguments.setdefault("pipelines", project_pipeline_facts(facts))
    if tool_name == "evaluate_design_special_requirements":
        special = nested_dict(facts, "designSpecialRequirements")
        fixed_clauses = nested_dict(facts, "fixedClauses")
        arguments.setdefault("requirements", special.get("domains") or {})
        arguments.setdefault(
            "standardRules",
            fixed_clauses.get("designSpecialRequirementRules") or {},
        )
    if tool_name in {"check_license_registry_match", "evaluate_component_manufacturer_scope"}:
        arguments.setdefault("licenseCandidates", list_fact(facts, "manufacturerLicenseCandidates"))
        arguments.setdefault("registryVerifications", list_fact(facts, "manualRegistryVerifications"))
        if tool_name == "evaluate_component_manufacturer_scope":
            arguments.setdefault("componentItems", list_fact(facts, "componentItems"))
    if tool_name in {
        "classify_r13_component_requirements",
        "evaluate_r13_supervision_certificate_completeness",
        "evaluate_r13_type_test_coverage",
    }:
        r13 = nested_dict(facts, "r13")
        arguments.setdefault("designItems", list_value(r13.get("designItems")))
        if tool_name == "evaluate_r13_supervision_certificate_completeness":
            arguments.setdefault("supervisionCertificates", list_value(r13.get("supervisionCertificates")))
        elif tool_name == "evaluate_r13_type_test_coverage":
            arguments.setdefault("typeTestReports", list_value(r13.get("typeTestReports")))
    if tool_name in {
        "classify_r14_component_applicability",
        "evaluate_r14_component_design_match",
        "resolve_r14_required_inspection_items",
        "evaluate_r14_special_report_coverage",
        "evaluate_r14_pressure_compatibility",
    }:
        r14 = nested_dict(facts, "r14")
        arguments.setdefault("designItems", list_value(r14.get("designItems")))
        if tool_name in {"evaluate_r14_component_design_match", "evaluate_r14_pressure_compatibility"}:
            arguments.setdefault("factoryInspectionReports", list_value(r14.get("factoryInspectionReports")))
        if tool_name in {"evaluate_r14_special_report_coverage", "evaluate_r14_pressure_compatibility"}:
            arguments.setdefault("specialInspectionReports", list_value(r14.get("specialInspectionReports")))
        if tool_name == "evaluate_r14_pressure_compatibility":
            arguments.setdefault("pipelineCharacteristics", list_value(r14.get("pipelineCharacteristics")))
    if tool_name in {
        "classify_r15_foreign_manufacturing_applicability",
        "classify_r15_regulatory_requirements",
        "evaluate_r15_manufacturing_license_coverage",
        "evaluate_r15_type_test_coverage",
        "evaluate_r15_manufacturing_inspection_route",
    }:
        r15 = nested_dict(facts, "r15")
        arguments.setdefault("designItems", list_value(r15.get("designItems")))
        if tool_name == "evaluate_r15_manufacturing_license_coverage":
            arguments.setdefault("licenseCandidates", list_value(r15.get("manufacturingLicenseCandidates")))
            arguments.setdefault("registryVerifications", list_value(r15.get("manualRegistryVerifications")))
        elif tool_name == "evaluate_r15_type_test_coverage":
            arguments.setdefault("typeTestReports", list_value(r15.get("typeTestReports")))
        elif tool_name == "evaluate_r15_manufacturing_inspection_route":
            arguments.setdefault("supervisionCertificates", list_value(r15.get("supervisionCertificates")))
            arguments.setdefault("arrivalInspectionRecords", list_value(r15.get("arrivalInspectionRecords")))
            arguments.setdefault(
                "completeMachineInspectionRecords",
                list_value(r15.get("completeMachineInspectionRecords")),
            )
    if tool_name in {
        "resolve_r16_product_standard_profile",
        "evaluate_r16_quality_certificate_batch_coverage",
        "evaluate_r16_quality_certificate_form_and_seals",
        "evaluate_r16_quality_certificate_design_match",
        "evaluate_r16_quality_certificate_content",
        "evaluate_r16_quality_certificate_results",
        "evaluate_r16_batch_traceability",
    }:
        r16 = nested_dict(facts, "r16")
        arguments.setdefault("designItems", list_value(r16.get("designItems")))
        arguments.setdefault("qualityCertificates", list_value(r16.get("qualityCertificates")))
    if tool_name in {
        "evaluate_r17_arrival_acceptance_batch_coverage",
        "evaluate_r17_acceptance_procedure",
        "resolve_r17_sampling_retest_requirement",
        "evaluate_r17_sampling_witness_chain",
        "evaluate_r17_nonconformance_control",
    }:
        r17 = nested_dict(facts, "r17")
        arguments.setdefault("designItems", list_value(r17.get("designItems")))
        arguments.setdefault("acceptanceRecords", list_value(r17.get("acceptanceRecords")))
        arguments.setdefault("witnessRecords", list_value(r17.get("witnessRecords")))
        arguments.setdefault("samplingRetestReports", list_value(r17.get("samplingRetestReports")))
        arguments.setdefault("samplingRules", list_value(r17.get("samplingRules")))
    if tool_name in {
        "classify_r18_material_test_applicability",
        "resolve_r18_material_test_requirement_profile",
        "evaluate_r18_material_retest_report_completeness",
        "evaluate_r18_material_ndt_report_completeness",
        "evaluate_r18_material_report_approval_procedure",
        "evaluate_r18_material_test_results_and_traceability",
    }:
        r18 = nested_dict(facts, "r18")
        arguments.setdefault("designItems", list_value(r18.get("designItems")))
        arguments.setdefault("retestReports", list_value(r18.get("retestReports")))
        arguments.setdefault("materialNdtReports", list_value(r18.get("materialNdtReports")))
    if tool_name in {
        "classify_r20_new_material_applicability",
        "evaluate_r20_new_material_procedure",
    }:
        r20 = nested_dict(facts, "r20")
        arguments.setdefault("designItems", list_value(r20.get("designItems")))
        arguments.setdefault("typeTestReports", list_value(r20.get("typeTestReports")))
        arguments.setdefault("technicalReviewApprovals", list_value(r20.get("technicalReviewApprovals")))
        arguments.setdefault("materialDataDocuments", list_value(r20.get("materialDataDocuments")))
    if tool_name == "evaluate_r21_mark_transfer":
        r21 = nested_dict(facts, "r21")
        arguments.setdefault("markTransferOccurred", r21.get("markTransferOccurred"))
        arguments.setdefault("transferRecords", list_value(r21.get("transferRecords")))
        arguments.setdefault("materialInventory", list_value(r21.get("materialInventory")))
    if tool_name == "evaluate_r22_material_substitution":
        r22 = nested_dict(facts, "r22")
        arguments.setdefault("materialSubstitutionOccurred", r22.get("materialSubstitutionOccurred"))
        arguments.setdefault("substitutionRecords", list_value(r22.get("substitutionRecords")))
        arguments.setdefault("actualMaterialUsage", list_value(r22.get("actualMaterialUsage")))
    if tool_name in {
        "resolve_r23_valve_test_basis",
        "evaluate_r23_valve_sampling",
        "evaluate_r23_valve_test_records",
    }:
        r23 = nested_dict(facts, "r23")
        arguments.setdefault("designStandardRefs", list_value(r23.get("designStandardRefs")))
        arguments.setdefault("contractStandardRefs", list_value(r23.get("contractStandardRefs")))
        arguments.setdefault("designAndContractBasisChecked", r23.get("designAndContractBasisChecked"))
        arguments.setdefault("testLots", list_value(r23.get("testLots")))
        arguments.setdefault("constructionRecords", list_value(r23.get("constructionRecords")))
        arguments.setdefault("testRecords", list_value(r23.get("testRecords")))
        arguments.setdefault(
            "standardRequirementProfiles",
            r23.get("standardRequirementProfiles")
            if isinstance(r23.get("standardRequirementProfiles"), dict)
            else {},
        )
    r24_r34_tool_nodes = {
        "decode_welder_qualification": ("r24",),
        "check_welder_work_coverage": ("r24",),
        "check_wps_pqr_coverage": ("r25",),
        "evaluate_welding_consumable": ("r26",),
        "evaluate_welding_consumable_control": ("r27",),
        "evaluate_pipe_fit_up": ("r28",),
        "evaluate_welding_process": ("r29",),
        "evaluate_weld_appearance": ("r30",),
        "evaluate_weld_repair": ("r31",),
        "resolve_pwht_applicability": ("r32", "r33", "r34"),
        "evaluate_heat_treatment": ("r32", "r34"),
        "evaluate_heat_treatment_instruments": ("r33",),
    }
    if tool_name in r24_r34_tool_nodes:
        for node_key in r24_r34_tool_nodes[tool_name]:
            node_facts = nested_dict(facts, node_key)
            if not node_facts:
                continue
            for key, value in node_facts.items():
                arguments.setdefault(key, value)
            break
    profile = str(arguments.get("argumentProfile") or "")
    if tool_name == "check_all_equal" and profile == "r01_design_org_identity":
        arguments.setdefault(
            "values",
            [
                {"source": "designLicense.holderName", "value": read_fact(facts, "designLicense.holderName")},
                {"source": "designDocument.titleBlockOrganization", "value": read_fact(facts, "designDocument.titleBlockOrganization")},
                {"source": "designDocument.designSealOrganization", "value": read_fact(facts, "designDocument.designSealOrganization")},
            ],
        )
    if tool_name == "check_design_license_scope":
        arguments.setdefault("licenseScopes", list_fact(facts, "designLicense.scopeCodes"))
        grade_path = "designDocument.pipelineGrades" if profile == "r01_design_scope_documents" else "project.pipelineGrades"
        arguments.setdefault("requiredPipelineGrades", list_fact(facts, grade_path))
    if tool_name == "check_installation_license_scope":
        arguments.setdefault("licenseScopes", list_fact(facts, "installationLicense.scopeCodes"))
        arguments.setdefault("requiredPipelineGrades", list_fact(facts, "project.pipelineGrades"))
    if tool_name == "check_date_covers" and profile in {"r01_design_license_period", "r02_installation_license_period"}:
        license_path = "designLicense" if profile.startswith("r01_") else "installationLicense"
        arguments.setdefault("validFrom", read_fact(facts, f"{license_path}.validFrom"))
        arguments.setdefault("validUntil", read_fact(facts, f"{license_path}.validUntil"))
        arguments.setdefault("periodStart", read_fact(facts, "project.constructionStart"))
        period_candidates = [read_fact(facts, "project.plannedConstructionEnd"), read_fact(facts, "project.constructionEnd")]
        if profile == "r01_design_license_period":
            period_candidates.extend(
                [
                    read_fact(facts, "project.actualConstructionEnd"),
                    read_fact(facts, "project.changeClarificationEnd"),
                ]
            )
        arguments.setdefault("periodEnd", latest_date_value(period_candidates))
    if tool_name == "decode_ndt_approval_item_codes":
        agencies = ndt_agency_facts(facts)
        arguments.setdefault(
            "approvalItemCodes",
            list(dict.fromkeys(code for agency in agencies for code in list_value(agency.get("approvalItemCodes")))),
        )
    if tool_name == "evaluate_ndt_agencies":
        arguments.setdefault("agencies", ndt_agency_facts(facts))
    arguments.setdefault("facts", facts)
    if tool_name == "check_required":
        arguments.setdefault("requiredFields", binding.get("requiredFacts") or [])
    return arguments


def nested_dict(value: dict[str, Any], key: str) -> dict[str, Any]:
    nested = value.get(key)
    return nested if isinstance(nested, dict) else {}


def read_fact(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple, set)) else []


def list_fact(value: dict[str, Any], path: str) -> list[Any]:
    return list_value(read_fact(value, path))


def latest_date_value(values: list[Any]) -> Any:
    parsed: list[tuple[date, Any]] = []
    for value in values:
        if not value:
            continue
        try:
            parsed.append((date.fromisoformat(str(value)[:10]), value))
        except ValueError:
            continue
    return max(parsed, key=lambda item: item[0])[1] if parsed else None


def ndt_agency_facts(facts: dict[str, Any]) -> list[dict[str, Any]]:
    container = facts.get("ndtAgencies")
    if isinstance(container, dict):
        agencies = container.get("agencies")
    else:
        agencies = container
    if isinstance(agencies, list):
        return [item for item in agencies if isinstance(item, dict)]
    legacy_license = nested_dict(facts, "ndtLicense")
    legacy_org = nested_dict(facts, "ndtOrganization")
    legacy_plan = nested_dict(facts, "ndtPlan")
    design = nested_dict(facts, "design")
    project = nested_dict(facts, "project")
    if not any((legacy_license, legacy_org, legacy_plan)):
        return []
    return [
        {
            "agencyId": str(legacy_org.get("id") or legacy_license.get("number") or "NDT-AGENCY-1"),
            "licenseOrganizationName": legacy_org.get("name") or legacy_license.get("organizationName"),
            "planOrganizationName": legacy_plan.get("organizationName"),
            "approvalItemCodes": legacy_license.get("approvalItemCodes") or legacy_license.get("methodCodes") or [],
            "requiredMethods": design.get("requiredNdtMethods") or [],
            "validFrom": legacy_license.get("validFrom"),
            "validUntil": legacy_license.get("validUntil"),
            "periodStart": project.get("constructionStart"),
            "plannedPeriodEnd": project.get("plannedConstructionEnd") or project.get("constructionEnd"),
        }
    ]


def project_pipeline_facts(facts: dict[str, Any]) -> list[dict[str, Any]]:
    project = nested_dict(facts, "project")
    pipelines = project.get("pipelines") if isinstance(project.get("pipelines"), list) else []
    if pipelines:
        return [item for item in pipelines if isinstance(item, dict)]
    if not project.get("pipelineGrade"):
        return []
    design_parameters = project.get("designParameters") if isinstance(project.get("designParameters"), dict) else {}
    return [
        {
            "pipelineId": str(project.get("pipelineId") or "PROJECT-PIPELINE"),
            "pipelineGrade": project.get("pipelineGrade"),
            "designPressureMPa": design_parameters.get("designPressureMPa", design_parameters.get("designPressure")),
            "designTemperatureC": design_parameters.get("designTemperatureC", design_parameters.get("designTemperature")),
        }
    ]


def aggregate_tool_results(outputs: list[dict[str, Any]]) -> str:
    """单个原子项内聚合各工具输出。

    优先级（业务口径）：
    1. 证据锚定失效一票否决——grounding 不通过时 passed/failed 均不可靠，降级证据不足；
    2. 已确认的 failed（真实不符合）不被工具执行故障掩盖；
    3. 工具执行故障是系统问题，走独立 execution_error 通道，不伪装成业务结论；
    4. human_review_required 独立保留（证据够但需专业判断 ≠ 证据不足）。
    """
    business_results = [str(item.get("result")) for item in outputs if item.get("result")]
    grounding_failed = any(
        str(item.get("toolName")) == "validate_evidence_grounding"
        and str(item.get("result")) in {"evidence_insufficient", "failed"}
        for item in outputs
    )
    execution_failed = any(item.get("status") in {"rejected", "failed", "error"} for item in outputs)
    if grounding_failed:
        return "evidence_insufficient"
    if "failed" in business_results:
        return "failed"
    if execution_failed:
        return "execution_error"
    if "human_review_required" in business_results:
        return "human_review_required"
    if "evidence_insufficient" in business_results:
        return "evidence_insufficient"
    applicable = [item for item in business_results if item != "not_applicable"]
    if business_results and not applicable:
        return "not_applicable"
    if applicable and all(item == "passed" for item in applicable):
        return "passed"
    return "evidence_insufficient"


def aggregate_atomic_results(items: list[dict[str, Any]]) -> str:
    results = [str(item.get("result")) for item in items]
    if "failed" in results:
        return "failed"
    if "execution_error" in results:
        return "execution_error"
    if "human_review_required" in results:
        return "human_review_required"
    if not results or any(item == "evidence_insufficient" for item in results):
        return "evidence_insufficient"
    applicable = [item for item in results if item != "not_applicable"]
    if not applicable:
        return "not_applicable"
    return "passed" if all(item == "passed" for item in applicable) else "evidence_insufficient"


def summarize(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "atomicCheckCount": len(items),
        "passedCount": sum(1 for item in items if item.get("result") == "passed"),
        "failedCount": sum(1 for item in items if item.get("result") == "failed"),
        "evidenceInsufficientCount": sum(1 for item in items if item.get("result") == "evidence_insufficient"),
        "notApplicableCount": sum(1 for item in items if item.get("result") == "not_applicable"),
        "humanReviewRequiredCount": sum(1 for item in items if item.get("result") == "human_review_required"),
        "executionErrorCount": sum(1 for item in items if item.get("result") == "execution_error"),
    }
