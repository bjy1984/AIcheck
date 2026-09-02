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
    # 模型链路：DeepSeek 直连，不经 LiteLLM 网关。
    #
    # 网关那条路卡在镜像上——ghcr.io/berriai/litellm 在 daocloud 镜像源不在白名单，
    # 拉不到。而 DeepSeek 是 OpenAI 兼容接口，official_api 这条路直接能打。
    #
    # 模型名必须显式写出来：配置文件里的默认值是 qwen3.7-plus，DeepSeek 不认。
    # 取值以 https://api.deepseek.com/models 实测为准（2026-08-14：
    # deepseek-v4-pro / deepseek-v4-flash 两个）。
    "AICHECK_QWEN_CALL_MODE": "official_api",
    "AICHECK_LLM_API_BASE": "https://api.deepseek.com",
    "AICHECK_LLM_MODEL_REVIEW": "deepseek-v4-pro",
    "AICHECK_LLM_MODEL_DEFAULT": "deepseek-v4-pro",
    "AICHECK_LLM_MODEL_COMPARE_FAST": "deepseek-v4-flash",
    # 一键分析（full-project-analysis）单独走 DashScope 的 qwen3.8-max（与本地一样
    # 直连通义；本地 litellm 映射的是 qwen3.7-plus，2026-09-02 按要求升到 3.8 max）。
    # 地址与密钥在下方 update 之后由视觉那把 DashScope 凭证带入
    # （AICHECK_LLM_PROJECT_REVIEW_API_BASE/_API_KEY），
    # 两个都配齐才生效，否则 qwen_runtime 退回主供应商 DeepSeek——那时这个模型名
    # 会被 DeepSeek 以 HTTP 400 拒绝，run 卡死（2026-08-28 漏配角色时实测过）。
    #
    # 为什么不继续用 deepseek-v4-pro：同一份提示词下它几乎不写 evidenceRefs，
    # 通过的节点直接回空 findings，校验器把整个节点降级成「证据不足」，监检
    # 工作台一条结果都看不到。2026-09-01 PARUN-4B22A0B9B5D34554：24 条 finding
    # 23 条无效；08-28 qwen3.7-plus 那次 66 条里 40 条带原文引用。
    "AICHECK_LLM_MODEL_PROJECT_REVIEW": "qwen3.8-max",
    # 资料分类与其它文本角色共用当前 DeepSeek provider。若遗漏该角色，
    # qwen_runtime.yaml 会回退 qwen3.8-max，而 DeepSeek 会直接返回 HTTP 400。
    "AICHECK_LLM_MODEL_DOCUMENT_CLASSIFIER": "deepseek-v4-pro",
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
runtime.update({k: v for k, v in secrets.items() if not k.startswith("AICHECK_BOOTSTRAP_PASSWORD_")})

# 模型密钥沿用 DEEPSEEK_API_KEY，不在凭证文件里复制一份。
# 复制一份的代价是轮换时要记得改两处，而漏改的那一处不会报错——只会静默降级。
# 放在 update 之后：这一行的来源就是凭证文件本身，不能反过来被它覆盖成空。
if secrets.get("DEEPSEEK_API_KEY"):
    runtime["AICHECK_LLM_API_KEY"] = secrets["DEEPSEEK_API_KEY"]

# embedding 复用视觉那把 DashScope 密钥（同账号同 key）。
# 同样放在 update 之后，且只在真有值时写：写成空串的话 EmbeddingClient
# 仍然 enabled（它只看 base_url），请求会带一个空 Authorization 打过去，
# 报 401 而不是「没配置」——比缺配置更难查。
if secrets.get("AICHECK_LLM_VISION_API_KEY"):
    runtime["AICHECK_EMBEDDING_API_KEY"] = secrets["AICHECK_LLM_VISION_API_KEY"]
    # LLM 备用供应商（DeepSeek 供应商级故障/熔断时降级）也复用这把 DashScope
    # 密钥：模型名走 qwen_runtime.yaml 里 official_api 的通义默认值。
    # 地址与密钥两个都配齐才生效（fallback_provider 的规矩），所以放同一个 if 里。
    runtime["AICHECK_LLM_FALLBACK_API_BASE"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    runtime["AICHECK_LLM_FALLBACK_API_KEY"] = secrets["AICHECK_LLM_VISION_API_KEY"]
    # 一键分析角色直连 DashScope（模型名见上方 AICHECK_LLM_MODEL_PROJECT_REVIEW）。
    # 同一把 key、同一个地址；地址与密钥两个都配齐才生效（role_provider_override 的规矩）。
    runtime["AICHECK_LLM_PROJECT_REVIEW_API_BASE"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    runtime["AICHECK_LLM_PROJECT_REVIEW_API_KEY"] = secrets["AICHECK_LLM_VISION_API_KEY"]

TARGET.write_text("".join("%s=%s\n" % (k, v) for k, v in sorted(runtime.items())))
TARGET.chmod(0o600)
print("  runtime env written: %d keys -> %s" % (len(runtime), TARGET))
