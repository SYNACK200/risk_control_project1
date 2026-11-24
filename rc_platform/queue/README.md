# rc_platform/queue —— 队列与并发（M5）

运行时基础设施，**不是流水线能力**：这里没有 `@capability`、不产出契约，`core` 的注册表
也不需要认识它。它只负责「一张单子进队列后怎么被领走、跑、重试、收尾」。

## 分工

| 文件 | 职责 |
| --- | --- |
| `models.py` | `Job` 数据、状态常量、退避公式、`ProgressEvent` → `stage/progress` |
| `store.py` | `QueueStore` 契约 + `MemoryStore` / `SqlAlchemyStore` 两套实现 |
| `service.py` | 状态机、租约与心跳、重试与死信、名次与统计 |
| `worker.py` | 领取→执行→收尾的固定流程、进程内循环 |

存储层只提供六个原语（加、取、列、原子领取、条件写回、清空），重试与状态机全部在
service —— 两套实现各写一遍必然漂移，`MemoryStore` 是行为基线，同一套测试压两遍。

## 最小用法

```python
from rc_platform.queue import MemoryStore, QueueService, SqlAlchemyStore, run_loop
from rc_platform.core.events import ProgressEvent

service = QueueService(SqlAlchemyStore("mysql+pymysql://user:pwd@host/rc?charset=utf8mb4"))
job = service.enqueue({"biz_no": "B20261109-001"}, priority=5, biz_no="B20261109-001")

def handler(job, emit):
    emit(ProgressEvent(job.id, "parse.layout_v2", 1, 3, "start"))
    ...
    emit(ProgressEvent(job.id, "parse.layout_v2", 3, 3, "ok"))

run_loop(service, "worker-1", handler)          # 常驻；测试里传 idle_limit=2 收尾
```

## 契约要点

- `priority` 数值越大越先被领取；同优先级按 `seq`（存储自增）FIFO。
- `claim` 是原子的：条件 UPDATE + rowcount，谁把 `queued` 改成 `running` 谁赢。
- 退避中的任务 `status` 仍是 `queued`，只是 `next_run_at` 未到点领不走；`position` 里
  它仍占一个名次。
- 写回全部带期望条件（`status`/`attempts`/`worker_id`），冲突时返回 `None` 而不是覆盖：
  这就是「取消能赢过迟到的 complete」的实现方式。
- 进度复用 `core/events.py` 的 `ProgressEvent`；`record_progress` 只写进度不动租约，
  续租由 `heartbeat` 负责，两个动作分开才能各自单独测。

## 已知限制（本版明确不做）

1. `stats()` 走全量扫描：单行任务量（万级以内）够用；量大应把计数与最早入队时间下推成
   SQL 聚合，接口形状不变。
2. `run_loop` 不内置信号处理与优雅停机：常驻进程由调用方管线程；`idle_limit` 是给测试与
   一次性批处理收尾用的。
3. `SqlAlchemyStore` 在进程内加了一把锁：sqlite 内存库所有线程共用一条连接（StaticPool），
   不加锁会撞事务。MySQL 下这把锁是不必要的本地串行，但不影响跨进程正确性
   （跨进程靠条件 UPDATE）。
4. 不存执行产物：`Job.payload` 是输入，产物由业务自己落库（backend/ 的职责）。
5. 没有延迟任务与定时任务：`next_run_at` 目前只由重试退避驱动。

## 自测

```bash
python -m pytest rc_platform/queue -q          # 55 条，两种存储各跑一遍
python -m pytest rc_platform/queue -q -s -k concurrent_demo   # 50 并发演示
```
