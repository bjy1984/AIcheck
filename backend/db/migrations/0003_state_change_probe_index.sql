-- 状态变更探针索引（issue #9）。
--
-- API 进程把全量业务状态驻留在内存，启动时加载一次。进程外的写入——worker 落库、
-- 运维改口令、迁移脚本——它一概看不见，必须重启容器才生效。线上踩过两次：改完
-- 口令登录仍失败，数据写进库了界面还是旧的。
--
-- 修法是让进程能廉价地问「库里有没有比我这份新的东西」。两级探针：
--   一级 max(updated_at)          —— 一个数，没变就什么都不做；
--   二级 按 collection 分组取 max —— 只在一级发现变化时跑，定位改了哪几个集合。
--
-- 不能用 revision 做探针：它是每对象各自计数（实测全表只有 1..4），
-- 不是全局单调序列，比不出「谁更新」。
--
-- 两个索引分别服务两级：一级要 1 行命中，二级要按集合聚合。
-- 36031 行实测：无索引 34ms 全表扫；二级索引后 7.4ms；一级 1 行索引接近 0。

CREATE INDEX IF NOT EXISTS idx_aicheck_state_tenant_updated
    ON public.aicheck_state (tenant_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_aicheck_state_tenant_collection_updated
    ON public.aicheck_state (tenant_id, collection, updated_at DESC);
