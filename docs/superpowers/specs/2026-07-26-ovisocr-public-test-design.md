# OvisOCR2 公开在线测试页设计

## 目标

在 `/home/dev-bjy` 部署 `/Volumes/Volume/project/ocr` 中的真实
OvisOCR2 Q6 模型服务，并在 AIcheck 的 FDE 后台增加在线测试入口。
测试页同时以无需登录的独立地址公开：

`http://39.108.128.107:8081/ocr-test/`

## 约束

- 目标主机为 Linux x86_64，仅有 4 个逻辑 CPU、30 GiB 内存且没有 GPU。
- 使用真实 `OvisOCR2-Q6_K.gguf` 与 `mmproj-F16.gguf`，不使用测试模式。
- 单次只处理一张 JPG、JPEG、PNG 或 WebP 图片。
- 上传上限为 20 MiB，最大安全像素数为 1600 万。
- 推理单并发；排队期间页面应明确展示等待状态。
- llama.cpp 推理端口不得直接暴露到公网。
- 不修改或覆盖工作区中与本功能无关的未提交改动。

## 方案

### 服务架构

在 `/home/dev-bjy/ovisocr` 部署独立 Docker Compose 栈：

- `llama-server`：使用 Linux CPU 版 llama.cpp，加载 Q6 主模型和视觉投影器；
- `ovisocr-web`：运行 Python Web 服务，负责上传校验、图片缩放、调用
  llama.cpp、结果清理和流式响应；
- 两个服务只通过 Docker 私有网络通信；
- Web 服务仅连接至 AIcheck 边缘网关所在网络，不单独发布公网端口；
- Compose 配置健康检查和 `unless-stopped` 自动重启策略。

目标机资源较少，因此 llama.cpp 使用单并发和受控线程数。请求超时设置为
15 分钟，页面持续显示推理状态，避免用户将 CPU 推理误判为卡死。

### HTTP 接口

OCR Web 服务保留健康检查，并提供公开测试接口：

- `GET /healthz`：返回模型、视觉投影器和 llama.cpp 可用状态；
- `POST /api/ocr`：接收单张图片并以 NDJSON 流返回状态和识别结果。

流事件包含：

- `page_start`：图片已通过校验并开始处理；
- `stream`：增量 Markdown；
- `complete`：最终 Markdown、可渲染 Markdown、字符数和耗时；
- `error`：稳定的错误代码与面向用户的中文提示。

服务不记录图片内容或识别正文；运行日志只保留请求时间、耗时、状态和错误摘要。

### 公开页面

AIcheck 前端新增公开路由 `/ocr-test/`。该路由不经过登录和角色校验，页面包含：

- 图片拖放或文件选择；
- 本地图片预览、文件名和大小；
- “开始识别”“重新选择”“复制 Markdown”操作；
- 排队、加载模型、推理中、完成和失败状态；
- 流式 Markdown 原文与渲染结果；
- CPU 推理可能较慢、单图和文件限制说明；
- 手机和桌面端均可使用的响应式布局。

页面通过同源 `/ocr-api/` 调用 OCR 服务，不访问 llama.cpp 端口。

### FDE 入口

FDE 路由目录新增“在线 OCR 测试”入口。入口不复制测试功能，只跳转到公开
`/ocr-test/` 页面，确保公开访问和后台访问使用同一实现。

### 网关

AIcheck 边缘 Nginx 增加两类转发：

- `/ocr-test/` 继续由 AIcheck 前端处理；
- `/ocr-api/` 转发到 `ovisocr-web`，移除前缀后访问内部 API。

网关为上传设置 20 MiB 限制，并将读取超时设置为 15 分钟以支持 CPU 流式推理。
llama.cpp 服务不映射宿主机公网端口。

## 错误处理

- 不支持的格式、空文件、超限文件和损坏图片在推理前拒绝；
- llama.cpp 未就绪时返回明确的“模型服务正在启动”提示；
- 推理超时、连接中断和空输出均转换为稳定错误事件；
- 前端保留当前已收到的增量结果，同时允许重新提交；
- 服务重启后 Compose 自动恢复，健康检查阻止未就绪流量。

## 测试与验收

### 自动化测试

- OCR 项目：配置、上传校验、NDJSON 事件顺序、异常映射和健康检查；
- AIcheck 前端：公开路由、FDE 入口、文件校验和流式事件解析；
- 构建检查：Python 测试与编译、前端类型检查和生产构建。

### 服务器验收

1. `llama-server` 与 `ovisocr-web` 健康；
2. 公网地址无需登录即可打开；
3. 使用真实图片完成一次真实 Q6 推理并返回非空结果；
4. FDE 后台入口可到达同一测试页；
5. llama.cpp 端口不能从公网直接访问；
6. 重启 Compose 后服务自动恢复；
7. AIcheck 原有健康检查和 FDE 页面仍可访问。

## 非目标

- PDF、多图批处理或多模型选择；
- 用户账户、调用额度或结果持久化；
- GPU 推理或自动扩缩容；
- 将该服务接入 AIcheck 正式 OCR 生产流水线。
