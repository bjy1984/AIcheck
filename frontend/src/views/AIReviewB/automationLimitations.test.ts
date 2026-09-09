import assert from 'node:assert/strict'
import { automationLimitationText } from './automationLimitations'
assert.match(automationLimitationText('procedure_reference_consistency'), /编号和版本/)
assert.match(automationLimitationText('method_specific_technical_requirements'), /专业人员/)
assert.match(automationLimitationText('complete_document_and_application_inventory'), /清单/)
assert.match(automationLimitationText('future_capability'), /人工核对/)
assert.doesNotMatch(automationLimitationText('future_capability'), /补.*文件|不符合|通过/)
