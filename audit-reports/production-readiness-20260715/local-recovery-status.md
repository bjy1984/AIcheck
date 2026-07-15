# 本机恢复能力状态

生成日期：2026-07-15

- PostgreSQL 已启用 WAL 归档，`archive_mode=on`，归档超时 60 秒。
- pgBackRest 仓库使用 AES-256-CBC 加密，保留 6 个全备和 35 个差异备份。
- 首个全量备份：1.5GB、4519 个文件。
- 隔离恢复演练：RPO 0 秒，RTO 24 秒，10 个非模板数据库清单与源端一致。
- 调度：周日全备、周一至周六差异备份、每月恢复演练、每 6 小时状态验收；使用 `flock` 防止并发。

该能力明确为 `local_only`：仓库与生产数据位于同一主机，不能抵御主机或可用区整体损失，也没有 KMS 支持的异地副本。因此它降低了误删、逻辑损坏和本机回退风险，但不能解除“异地加密副本与时间点恢复”这一正式上线阻塞项。

## TLS 运行维护

- 当前证书使用 Let's Encrypt `shortlived` 配置，需高频续期。
- ACME staging dry-run 已通过 HTTP-01 多视角校验。
- `verify_tls_runtime.sh` 用于校验证书 IP SAN、信任链、剩余有效期和 HTTPS 可用性，并可在 Nginx 配置通过后安全 reload TLS 代理。
