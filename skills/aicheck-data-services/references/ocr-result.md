# OCR 最终结果的解释

`aicheck_ocr_result` 返回服务器保存的最终加工结果，不是供应商原始输出。MinerU 正常完成时使用其正文与坐标；连续排队超时后改由千问识别。两条路径都经过资料类型提取、结构整理和质量判定，具体步骤以 `processing.postProcessing` 为准，不能把一种引擎的印章补识别能力套用到另一种引擎。

## 排队、切换与轮询

- 保留上传成功返回的原 `jobId`，使用 `aicheck_ocr_status` 查询。默认连续 `pending` 60 秒后由服务器自动切换千问；这是可配置阈值，不是整个文档的完成时限。`running/converting` 不属于 pending 排队超时。
- 状态 `provider/model` 是实际执行来源，`requestedProvider` 是初始提供方。千问接管后 `provider=qwen`，最终结果 `processing.provider` 可为 `aliyun_model_studio`，二者表示同一切换路径。
- `fallback.reason=MINERU_PENDING_TIMEOUT` 说明切换原因；旧任务号在 `fallback.providerTaskId`。`localWaitStopped=true` 只表示本系统停止等待，`remoteCancellation=unsupported` 不能解读为 MinerU 官方取消成功。
- 按 `recommendedPollSeconds` 查询；未提供时建议间隔 10 秒。千问状态可显示 `pageProgress.completed/total`。不要因为看到 pending、切换或同一进度而重复上传。
- 宿主一次交互建议最多观察 10 分钟；超出后报告“服务器仍在处理”、保存 jobId 供继续查询，不擅自标记失败或创建新任务。查询暂时失败时最多重试 3 次，仍失败则报告原始错误码和 jobId。后台任务可能仍在执行。
- `status=failed` 时报告诊断，不自动在两个供应商之间循环重提。`status=success` 后读取结果，分别判断执行状态和资料质量。

状态示例：`provider=qwen, model=qwen3.5-ocr, pageProgress={completed:1,total:2}` 应表达为“MinerU 排队超时，已由千问识别，完成 1/2 页”，而不是“MinerU 已完成”。


## 提交与资料类型

资料类型明确时，从 `aicheck_connection.data.ocr.profiles` 选择 `profileId`。例如焊工证为 `welder_certificate_v1`，焊材证明书为 `welding_consumable_certificate_v1`。类型不明确时省略，服务器按正文路由；结果的 `profileId` 是最终类型，`processing.requestedProfileId` / `detectedProfileId` 和 `profileRouteReason` 说明是否发生路由。不能仅凭文件名宣称类型已核实。

## 阅读顺序

1. 确认 `resultAvailable`。任务 `status=success` 只说明处理完成；还需读取 `outcomeStatus`、`quality.status`、`quality.missingFields/missingTables/blockingReasons` 和诊断。`formalEvidenceReady` 是服务质量门槛，不证明证件真实或工程合格。
2. 一起阅读 `fragments`、`fields`、`tables`、`seals`，保留 `sourceEngine`、`extractionMethod`、`sourceCandidateIds`、`pageNo`、`bbox` 等实际来源。字段提取和表格重建可能出错，重要值应对照原页与正文。
3. `pageNo` 为原件物理页。分页过滤页内对象；`documentFields` 保留未绑定页码的字段，`unlocatedContent` 保留无页码的其他对象。二者仅作为文档级信息，不虚构页码或坐标。全文调用中这些对象也出现在原数组里，展示时去重。
4. `quality`、资料类型及 `processing` 均为全文级；当前页没有某字段或章不能直接推断整份原件缺少。分页 `diagnostics` 同时包含当前页和无页码的诊断。
5. `processing.postProcessing` 记录规范化、字段提取、融合及补识别状态。`sealSecondaryRecognition=completed` 表示处理步骤结束，具体章是否读出仍以每枚章的标记为准；`not_run` / `failed` 不能说已完成核验。旧结果 `provenanceAvailable=false` 时明确说明处理记录不可追溯，不补造记录。

## 印章与证件

视觉模型读出的章可能带 `sealName` / `text`，同时仍为 `recognized=false`、`requiresHumanConfirmation=true` 或 `sealEvidenceLevel=model_read_unverified`。应展示“识别候选，待核对”，不得作为已核实单位身份。印章识别成功也不等于官方登记核验、签章真实性或证件有效性。

千问与 MinerU 的原始产物不同。千问归档可包含 `raw_qwen_json`、`normalized_json`、`markdown`；不要要求其返回 MinerU 原始 ZIP，也不要仅因原始格式不同重跑 OCR。不同路径的坐标、印章和表格完整度可能不同，以每项证据和质量标记为准。
