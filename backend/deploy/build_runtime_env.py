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
    # 对象存储：容器间走服务名，浏览器侧走宿主机映射端口
    "AICHECK_MINIO_ENDPOINT": "minio:9000",
    "AICHECK_MINIO_PUBLIC_ENDPOINT": "127.0.0.1:19000",
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
    "AICHECK_LLM_MODEL_VISION": "deepseek-v4-pro",
}
# 凭证覆盖固定配置：口令、密钥以文件为准
runtime.update({k: v for k, v in secrets.items() if not k.startswith("AICHECK_BOOTSTRAP_PASSWORD_")})

# 模型密钥沿用 DEEPSEEK_API_KEY，不在凭证文件里复制一份。
# 复制一份的代价是轮换时要记得改两处，而漏改的那一处不会报错——只会静默降级。
# 放在 update 之后：这一行的来源就是凭证文件本身，不能反过来被它覆盖成空。
if secrets.get("DEEPSEEK_API_KEY"):
    runtime["AICHECK_LLM_API_KEY"] = secrets["DEEPSEEK_API_KEY"]

TARGET.write_text("".join("%s=%s\n" % (k, v) for k, v in sorted(runtime.items())))
TARGET.chmod(0o600)
print("  runtime env written: %d keys -> %s" % (len(runtime), TARGET))
