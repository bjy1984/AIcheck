#!/usr/bin/env python3
"""把分散的凭证文件 + 固定运行时配置，拼成 docker --env-file。

不用 shell 的 `. file`：凭证里含 $ ! # 等字符，source 会当成 shell 语法解析
（实际踩过 `W#!+...: command not found`）。docker --env-file 按 KEY=VALUE
原样读取，不做任何展开，是这类值唯一安全的传法。

输出 /home/dev-bjy/aicheck-runtime.env（600）。**输出不进仓库，本脚本进仓库。**

## 为什么现在纳入版本管理

2026-08-14 之前这个脚本只存在于服务器 /home/dev-bjy 下，而 deploy_to_server.sh
每次部署都调它。也就是说：部署行为的一半逻辑没有版本、没有 diff、没法回滚，
改坏了也无从追溯——和 docker-compose.deploy.yml「看起来是权威其实没人校验」
是同一类问题。

它每次**重新生成**目标文件。手工往 aicheck-runtime.env 里追加的行，
下次部署就没了（这条坑真实踩过：模型配置加完，部署一次全丢）。
要加运行时配置，就加在下面的 runtime 字典里；要加凭证，加进 SECRET_FILES。

部署时由 deploy_to_server.sh 从仓库同步到服务器，不再手工维护。
"""
import os
import pathlib

SECRET_FILES = ["/home/dev-bjy/stack-secrets.env", "/home/dev-bjy/aicheck-secrets.env"]
TARGET = pathlib.Path("/home/dev-bjy/aicheck-runtime.env")

# 宿主机是 Python 3.6，不用 3.9+ 的内置泛型标注
secrets = {}
for src in SECRET_FILES:
    path = pathlib.Path(src)
    if not path.exists():
        continue
    for line in path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            secrets[key.strip()] = value.strip()

user = secrets.get("AICHECK_POSTGRES_USER", "aicheck")
password = secrets.get("AICHECK_POSTGRES_PASSWORD", "")
database = secrets.get("AICHECK_POSTGRES_DB", "aicheck")

runtime = {
    "AICHECK_DATABASE_URL": "postgresql://%s:%s@aicheck-postgres:5432/%s" % (user, password, database),
    "AICHECK_TENANT_ID": "TENANT-DEFAULT",
    "AICHECK_TENANT_MODE": "isolated",
    "AICHECK_REDIS_URL": "redis://aicheck-redis:6379/0",
    "AICHECK_REQUIRE_AUTH": "true",
    "AICHECK_ENABLE_DEMO_DATA": "true",
    "AICHECK_BOOTSTRAP_LOCAL_ROLES": "true",
    "AICHECK_STRICT_PRODUCTION": "false",
    "AICHECK_ALLOWED_HOSTS": "*",
    # 对象存储：容器间走服务名；浏览器侧必须走**浏览器能连上的**地址。
    #
    # 这里原来写的是 127.0.0.1:19000——那是服务器自己的回环地址。
    # 预签名 URL 直接发给浏览器，浏览器连的是自己的 127.0.0.1，必然失败。
    # 2026-08-15 实操上传实测：upload-session 建会话 176ms 成功，
    # 随后传字节那步报 `Failed to fetch`，**通过浏览器上传对所有角色 100% 失败**。
    # 库里那批「有记录、无内容哈希」的空壳文件就是这么来的。
    #
    # MinIO 只绑在宿主机 127.0.0.1:19000，对外不通；不新开端口，
    # 改由页面同源的 nginx 按桶前缀 /documents/ 反代过去
    # （见 deploy/nginx-default.conf）。预签名按这个 host 计算，
    # nginx 原样透传 Host，签名才对得上。
    "AICHECK_MINIO_ENDPOINT": "minio:9000",
    "AICHECK_MINIO_PUBLIC_ENDPOINT": os.getenv("AICHECK_PUBLIC_ORIGIN", "39.108.65.148:8081"),
    "AICHECK_MINIO_SECURE": "false",
    # 任务派发走 celery，队列由各 worker 容器消费
    "AICHECK_TASK_DISPATCH": "celery",
    # Office 在线预览：浏览器经本机 nginx 反代 /onlyoffice/ 访问，与页面同源
    "AICHECK_ONLYOFFICE_BASE": "/onlyoffice",
    "AICHECK_REVIEW_ORCHESTRATION": "inline",
    # 模型链路：通义（DashScope 兼容模式）直连，不经 LiteLLM 网关。
    #
    # 网关那条路卡在镜像上——ghcr.io/berriai/litellm 在 daocloud 镜像源不在白名单，
    # 拉不到。official_api 这条路走 OpenAI 兼容协议，直接能打。
    #
    # 2026-09-03 起全部文本角色统一用通义（此前主供应商是 DeepSeek）：
    # - DeepSeek V4 Pro 在审查提示词下几乎不写 evidenceRefs，通过的节点直接回空
    #   findings，校验器整体降级成「证据不足」（PARUN-4B22A0B9B5D34554：24 条 23 条无效）；
    # - 09-03 DeepSeek 欠费 HTTP 402，全部复核失败。
    # 主密钥由下方 update 之后从视觉那把 DashScope 凭证带入（同账号同 key）。
    # 模型名以 DashScope 实际可调为准（09-02/09-03 实测 qwen3.7-plus / qwen3.8-max 均 200）。
    # 工位模式：新建审查运行时冻结文件范围 / 生效规则 / 工位快照（execution.py
    # create_review_run_from_ai_run → initialize_run_workstation）。此前只是开发开关，
    # 生产从没开过，于是 329 次真实运行**没有一次**带 documentScopeSnapshot，
    # 验收 fixture 一份都导不出（2026-09-10 盘点）。开关不给既有运行补快照，只影响新运行；
    # /rerun 走 clone_review_run_for_replay，不经这一步，重跑要走 ai-recheck 的新建路径。
    "AICHECK_WORKSTATIONS_ENABLED": "true",
    # 公示平台（CNSE）：2026-09-12 实测一个 302 走 17 秒，默认 5s 连接超时把查询全打成失败。
    # 连接 20s、读取 60s；验证码图片最大 16MB，读取要留够。
    "AICHECK_CNSE_TIMEOUT_CONNECT": "20",
    "AICHECK_CNSE_TIMEOUT_READ": "60",
    "AICHECK_QWEN_CALL_MODE": "official_api",
    "AICHECK_LLM_API_BASE": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "AICHECK_LLM_MODEL_REVIEW": "qwen3.7-plus",
    # P8 H4：分片信封修复失败后的升级模型（只对"模型没按契约输出"的分片重跑一次）。
    "AICHECK_LLM_MODEL_REVIEW_ESCALATION": "qwen3.8-max",
    # P8 H5：审查提示词模式，checklist=清单填表（灰度用，基准对照后再切）；默认自由模式。
    "AICHECK_REVIEW_PROMPT_MODE": "freeform",
    # P0 2.2：资料类型变更。stage1=加 wps/pqr/工艺卡/平台核验/PMI 并拆节点 25，焊材证明与施焊记录仍是条件必传；
    # stage2=再把节点 26 焊材证明、节点 29/24 施焊记录改必传。翻到 stage1 的前置是 2.4 重键迁移
    # （2026-09-07 已完成）与新类型的审查点（同日补进 config/material_review_points.json）。
    "AICHECK_WELDING_MATERIAL_TYPES_V2": "stage1",
    "AICHECK_LLM_MODEL_DEFAULT": "qwen3.7-plus",
    "AICHECK_LLM_MODEL_COMPARE_FAST": "qwen3.6-flash",
    # 一键分析（full-project-analysis）用 qwen3.8-max（2026-09-02 按要求升到 3.8 max）。
    "AICHECK_LLM_MODEL_PROJECT_REVIEW": "qwen3.8-max",
    # 资料分类：qwen_runtime.yaml 的默认值也是 qwen3.8-max，这里显式写出，
    # 新增 LLM 角色时这份清单必须同步补齐（漏配角色曾让 run 卡死，2026-08-28）。
    "AICHECK_LLM_MODEL_DOCUMENT_CLASSIFIER": "qwen3.8-max",
    # 视觉单独走一家：DeepSeek 的 chat.completions 不接受图片，发 image_url
    # 直接 400（unknown variant `image_url`）。此前这一项也写着 deepseek-v4-pro，
    # 等于声明了一个不存在的能力——印章读字上线第一次实跑就栽在这里。
    # 地址与密钥在凭证文件里（AICHECK_LLM_VISION_API_BASE / _API_KEY），
    # 两个都配齐才生效，只配一半会退回主供应商。
    "AICHECK_LLM_MODEL_VISION": "qwen-vl-max",
    # OCR 分工：正文/表格走 MinerU 云端 API，印章由视觉模型读字。
    #
    # 密钥 AICHECK_MINERU_API_KEY 在凭证文件里，由下面的 update 带进来。
    # 这里只写路由，不写密钥——密钥进仓库这条线不能开。
    #
    # 本地那份 .env 同时带着 AICHECK_OCR_OFFLINE_ONLY / AICHECK_OCR_DISABLE_NETWORK
    # =true，那是给 ocr-service 容器用的；照抄到服务器会把 MinerU 这条云端调用
    # 直接堵死，且不会报错——只会静默退回占位结果。所以这两项一个都不带上来。
    #
    # 印章：ocr-service 容器已经在这台机器上跑起来了（镜像 2.4 GB、模型 360 MB），
    # 本地读字默认开启（AICHECK_ENABLE_LOCAL_SEAL_READING 默认 true），
    # 所以这里不需要显式写开关。0818 实测读字率 81%（59/73 枚）。
    # 分工是否真的生效由 online_probe.py 的 ocr-routing 检查项断言——
    # 这条链路坏掉的方式很安静：印章一直没有文字，不报错也不降级提示，
    # 监检看到的是「这份资料没盖章」，而实际盖了。
    "AICHECK_OCR_DEFAULT_PROVIDER": "mineru",
    "AICHECK_OCR_ALLOW_PLACEHOLDER": "false",
    # 印章读字走本地模型，模型只装在 ocr-service 容器里（2.4 GB 镜像 + 360 MB 模型）。
    # 代码里的默认值是 http://ocr-service:8010，而这台机器上的容器叫
    # aicheck-ocr-service——名字对不上就连不通，而症状只是印章一直没有文字，
    # 不会有任何人来报错。
    "AICHECK_OCR_BASE_URL": "http://aicheck-ocr-service:8010",
    # 向量化走 Qwen 官方 API（DashScope 兼容模式）。
    #
    # 这台机器上没有本地 embedding 服务：compose 里的 embedding-service
    # 从来没在这里起过。而 embed_knowledge 跑在 worker 里——配置缺了它不会
    # 报「没配置」，只会让资料一直停在「待向量化」，进而让施工方**永远报不了审**
    # （报审前置要求 OCR/切片/向量化三段全绿）。0818 实测积压 36 份。
    #
    # SERVED_MODEL_NAME 必须是 API 真认的模型名：请求体里的 model 字段取的是它，
    # 不是 MODEL_ID。两个都写成 text-embedding-v4，少写一个就是 400。
    #
    # 密钥沿用视觉那把 DashScope key（AICHECK_LLM_VISION_API_KEY，见下方 update）：
    # 同一个账号同一把钥匙，复制成两份的代价是轮换时漏改一处，
    # 而漏改的那处不会报错——只会静默停摆。
    "AICHECK_EMBEDDING_PROVIDER": "official_api",
    "AICHECK_EMBEDDING_API_BASE": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "AICHECK_EMBEDDING_MODEL_ID": "text-embedding-v4",
    "AICHECK_EMBEDDING_SERVED_MODEL_NAME": "text-embedding-v4",
    # 断点批大小取满 EMBED_BATCH_SIZE（32）：默认 8 是为「避免长任务阻塞」，
    # 但 cpu.heavy 并发为 1，多条续跑链竞争时每链每轮只前进 8 个分块、
    # 却要等其他所有链各跑一轮——233 分块的文件要 30 轮×链数（2026-08-29 实测
    # 39 条链集体停在 offset=24）。批大小 32 不增加 API 调用次数（一次调用
    # 本就发 32 段），只把断点开销降到 1/4。
    "AICHECK_EMBEDDING_CHECKPOINT_BATCH_SIZE": "32",
}
# 凭证覆盖固定配置：口令、密钥以文件为准
# DEEPSEEK_* 不透传：2026-09-24 起模型全部走通义，运行时里留着 DeepSeek 密钥只会让
# 某条旧路径（litellm server 模式、模型对比 challenger）悄悄又打回去。
runtime.update({
    k: v for k, v in secrets.items()
    if not k.startswith("AICHECK_BOOTSTRAP_PASSWORD_") and not k.startswith("DEEPSEEK_")
})

# 主模型密钥复用视觉那把 DashScope 密钥（同账号同 key）——embedding 也是它。
# 不在凭证文件里复制第二份：轮换时漏改的那份不会报错，只会静默降级。
# 放在 update 之后，且只在真有值时写：写成空串会让就绪检查以为「配了但是空的」。
if secrets.get("AICHECK_LLM_VISION_API_KEY"):
    runtime["AICHECK_LLM_API_KEY"] = secrets["AICHECK_LLM_VISION_API_KEY"]
    runtime["AICHECK_EMBEDDING_API_KEY"] = secrets["AICHECK_LLM_VISION_API_KEY"]

# 百炼 Token Plan（套餐制）。三种密钥/端点完全隔离，混用一律 401：
#   按量计费 sk-…            → dashscope.aliyuncs.com/compatible-mode/v1
#   Token Plan sk-sp-…       → token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
#   Coding Plan sk-sp-…      → coding.dashscope.aliyuncs.com/v1
# 2026-09-10 一把有效的 Token Plan 密钥被误打到按量端点，连错三轮。凭证文件里给了
# AICHECK_TOKEN_PLAN_API_KEY，文本与视觉角色就整体切到 Token Plan：
# - 模型名不动：qwen3.7-plus / qwen3.8-max / qwen3.6-flash 在 Token Plan 实测 200；
# - 视觉改 qwen3.7-plus：Token Plan 没有 qwen-vl-max，而 qwen3.7-plus 实测能读图；
# - embeddings **不切**：Token Plan 没有 text-embedding-v4（404），仍走按量端点，
#   密钥取凭证里的 AICHECK_EMBEDDING_API_KEY，没有就沿用视觉那把（按量 sk-）。
# 放在 update 之后：凭证里旧的 AICHECK_LLM_VISION_API_BASE/_KEY（按量）要被它盖掉。
TOKEN_PLAN_BASE = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
if secrets.get("AICHECK_TOKEN_PLAN_API_KEY"):
    token_plan_key = secrets["AICHECK_TOKEN_PLAN_API_KEY"]
    runtime["AICHECK_LLM_API_BASE"] = TOKEN_PLAN_BASE
    runtime["AICHECK_LLM_API_KEY"] = token_plan_key
    # 视觉不跟着切：按量端点有 qwen-vl-max（专门的视觉模型，印章读字就是为它配的），
    # Token Plan 没有，只能退而用 qwen3.7-plus 读图。凭证文件里地址与密钥**两个都齐**
    # 才认（沿用 vision_override 的老规矩：只配一半会拼出"新地址配旧密钥"）；
    # 缺任一个才整体退回 Token Plan。
    if not (secrets.get("AICHECK_LLM_VISION_API_BASE") and secrets.get("AICHECK_LLM_VISION_API_KEY")):
        runtime["AICHECK_LLM_VISION_API_BASE"] = TOKEN_PLAN_BASE
        runtime["AICHECK_LLM_VISION_API_KEY"] = token_plan_key
        runtime["AICHECK_LLM_MODEL_VISION"] = "qwen3.7-plus"
    # embeddings 只能走按量端点（Token Plan 没有 text-embedding-v4，实测 404）。
    embedding_key = secrets.get("AICHECK_EMBEDDING_API_KEY") or secrets.get("AICHECK_LLM_VISION_API_KEY")
    if embedding_key:
        runtime["AICHECK_EMBEDDING_API_KEY"] = embedding_key

# LLM 备用供应商：通义按量计费（主供应商 Token Plan 限流/故障/熔断时降级）。
# 2026-09-24 起不再用 DeepSeek（用户要求全部走通义）：当天灰度里 Token Plan 按分钟
# 限流 429，一转 DeepSeek 就 402 欠费，一次复核 30 个证据分片落空。按量计费与 Token Plan
# 额度互相独立，限流时正好接得住；模型名与主供应商逐角色相同（三个文本模型在按量端点
# 实测 200）。只有主供应商是 Token Plan、且有按量 sk- 密钥时才配——主供应商本身就是按量
# 时，备胎指回同一个端点毫无意义。凭证里的 DEEPSEEK_API_KEY 不再读取。
PAYG_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
payg_key = next(
    (
        secrets[name]
        for name in ("AICHECK_LLM_VISION_API_KEY", "AICHECK_EMBEDDING_API_KEY")
        if secrets.get(name, "").startswith("sk-") and not secrets[name].startswith("sk-sp-")
    ),
    "",
)
if runtime.get("AICHECK_LLM_API_BASE") == TOKEN_PLAN_BASE and payg_key:
    runtime["AICHECK_LLM_FALLBACK_API_BASE"] = PAYG_BASE
    runtime["AICHECK_LLM_FALLBACK_API_KEY"] = payg_key
    for name, value in list(runtime.items()):
        if name.startswith("AICHECK_LLM_MODEL_") and name != "AICHECK_LLM_MODEL_VISION":
            runtime[name.replace("AICHECK_LLM_MODEL_", "AICHECK_LLM_FALLBACK_MODEL_")] = value

# Jev 插件（外部模型，只给提示与事实核对，不改结论）。凭证里放了 AICHECK_JEV_API_KEY 才开：
# 总开关、出境批准、逐项建议（PRIMARY_DECISION）与事实核对（FACT_CHECK）。真正外发还要
# 项目级开关（管理员「编辑项目」里的 Jev 加强）打开并在运行建立时冻结——没打开的项目一个字都
# 不送。2026-09-25 用户批准：只 GDLNG 与 ECD202 两个测试项目可出境。
# 文档路由、第二意见、声明影子等其他阶段不开：它们不走项目开关。
if secrets.get("AICHECK_JEV_API_KEY"):
    runtime.update({
        "AICHECK_JEV_ENABLED": "true",
        "AICHECK_JEV_DATA_EGRESS_APPROVED": "true",
        "AICHECK_JEV_PRIMARY_DECISION_ENABLED": "true",
        "AICHECK_JEV_FACT_CHECK_ENABLED": "true",
    })
else:
    for name in [key for key in runtime if key.startswith("AICHECK_JEV_")]:
        runtime.pop(name)

TARGET.write_text("".join("%s=%s\n" % (k, v) for k, v in sorted(runtime.items())))
TARGET.chmod(0o600)
print("  runtime env written: %d keys -> %s" % (len(runtime), TARGET))
