"""通过命令采样宿主机资源并绘制状态图，不调用模型。"""

from __future__ import annotations

from typing import Any
import asyncio
import base64

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase

from .metrics import collect_snapshot
from .render import render_status


class PluginSettings(PluginConfigBase):
    enabled: bool = Field(default=True, description="启用宿主机状态命令")
    config_version: str = Field(default="1.0.0", description="配置版本")


class StatusSettings(PluginConfigBase):
    disk_paths: list[str] = Field(
        default_factory=list,
        description="要显示的磁盘路径；留空时 macOS 使用数据卷，其他系统使用系统盘",
    )
    font_path: str = Field(default="", description="中文字体文件；留空自动选择系统字体")


class HostStatusConfig(PluginConfigBase):
    plugin: PluginSettings = Field(default_factory=PluginSettings)
    status: StatusSettings = Field(default_factory=StatusSettings)


def build_status_image(disk_paths: list[str], font_path: str) -> bytes:
    """将采样和绘制一起放在线程中，避免阻塞插件事件循环。"""
    return render_status(collect_snapshot(disk_paths), font_path)


class HostStatusPlugin(MaiBotPlugin):
    config_model = HostStatusConfig

    async def on_load(self) -> None:
        self.ctx.logger.info("宿主机状态插件已加载：/系统状态；按需采样，本机绘图，不调用模型")

    async def on_unload(self) -> None:
        return None

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        del scope, config_data, version

    @Command(
        "host_status",
        description="绘制当前宿主机的 CPU、内存、交换空间和磁盘状态",
        pattern=r"^/(?:系统状态|主机状态|sysinfo|status)\s*$",
    )
    async def host_status(self, stream_id: str, **kwargs: Any) -> tuple[bool, str, bool]:
        del kwargs
        try:
            png = await asyncio.to_thread(
                build_status_image, self.config.status.disk_paths, self.config.status.font_path,
            )
        except OSError as exc:
            self.ctx.logger.exception("无法读取资源或字体，状态图生成失败")
            await self.ctx.send.text(f"状态图生成失败：{exc}", stream_id)
            return False, "状态图生成失败", True

        sent = await self.ctx.send.image(base64.b64encode(png).decode("ascii"), stream_id)
        # 拦截后续普通聊天处理，命令不会再占一次 Planner/Replyer 调用。
        return bool(sent), "已发送宿主机状态图" if sent else "状态图发送失败", True


def create_plugin() -> HostStatusPlugin:
    return HostStatusPlugin()
