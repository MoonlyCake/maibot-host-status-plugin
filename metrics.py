"""按需采集插件进程所在主机的资源状态；采样应在线程中执行。"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence
import platform
import time

import psutil


@dataclass(frozen=True)
class DiskSnapshot:
    path: str
    total: int
    used: int
    free: int
    percent: float


@dataclass(frozen=True)
class HostSnapshot:
    captured_at: datetime
    system: str
    architecture: str
    cpu_name: str
    cpu_percent: float
    core_percent: tuple[float, ...]
    physical_cores: int
    logical_cores: int
    memory_total: int
    memory_used: int
    memory_available: int
    memory_percent: float
    swap_total: int
    swap_used: int
    swap_percent: float
    uptime_seconds: int
    disks: tuple[DiskSnapshot, ...]


def collect_snapshot(disk_paths: Sequence[str] = ()) -> HostSnapshot:
    """采样 CPU 0.8 秒，其余指标读取同一次状态图需要的数据。"""
    core_percent = tuple(psutil.cpu_percent(interval=0.8, percpu=True))
    logical_cores = len(core_percent)
    physical_cores = psutil.cpu_count(logical=False)
    if physical_cores is None:
        # psutil 在系统未提供物理核心信息时返回 None。
        physical_cores = logical_cores

    memory = psutil.virtual_memory()
    memory_used = memory.total - memory.available
    swap = psutil.swap_memory()
    system = platform.system()
    architecture = platform.machine()

    if disk_paths:
        paths = tuple(disk_paths)
    elif system == "Darwin" and Path("/System/Volumes/Data").exists():
        paths = ("/System/Volumes/Data",)
    else:
        paths = ("/",)

    disks = []
    for path in paths:
        usage = psutil.disk_usage(path)
        # APFS 多卷共享容器空间；总量减可用量包含其他共享卷占用。
        used = usage.total - usage.free
        disks.append(DiskSnapshot(path, usage.total, used, usage.free, used / usage.total * 100))

    return HostSnapshot(
        captured_at=datetime.now().astimezone(),
        system=system,
        architecture=architecture,
        cpu_name=platform.processor() or architecture,
        cpu_percent=sum(core_percent) / logical_cores,
        core_percent=core_percent,
        physical_cores=physical_cores,
        logical_cores=logical_cores,
        memory_total=memory.total,
        memory_used=memory_used,
        memory_available=memory.available,
        memory_percent=memory_used / memory.total * 100,
        swap_total=swap.total,
        swap_used=swap.used,
        swap_percent=swap.percent,
        uptime_seconds=int(time.time() - psutil.boot_time()),
        disks=tuple(disks),
    )
