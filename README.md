# 宿主机状态图

[源码仓库](https://github.com/MoonlyCake/maibot-host-status-plugin) · [发布版本](https://github.com/MoonlyCake/maibot-host-status-plugin/releases)

MaiBot SDK 2.x 插件，通过命令读取当前宿主机资源，并用 Pillow 绘制 PNG 状态图。CPU 采样约 0.8 秒，只在收到命令时工作，不调用模型，没有后台采样任务。

## 命令

发送 `/系统状态`，也支持 `/主机状态`、`/sysinfo`、`/status`。

图中显示 CPU 总占用与各逻辑核心、物理/逻辑核心数、内存已用/总量/可用量、交换空间、磁盘占用与剩余空间、系统架构及运行时间。命令直接返回图片，不再交给 Planner。

## 安装

将仓库放在 MaiBot 的 `plugins/host_status/` 下，目录中应直接包含 `plugin.py` 和 `_manifest.json`，然后重启或重新发现插件。默认启用。宿主可按清单安装依赖；手动安装可在 MaiBot 环境执行 `uv pip install -r plugins/host_status/requirements.txt`。

兼容范围：MaiBot 1.3.12～1.3.99、SDK 2.12.0～2.16.99，Python 3.10+。macOS 自带中文字体；Linux 可安装 Noto CJK 字体（同时装 Bold 字重标题更清晰），Windows 使用微软雅黑。

## 配置

WebUI 的插件配置中可修改字体和磁盘路径，也可编辑插件生成的 `config.toml`：

```toml
[plugin]
enabled = true
config_version = "1.0.0"

[status]
disk_paths = []
font_path = ""
```

`disk_paths` 留空时，macOS 读取 `/System/Volumes/Data`，其他系统读取系统盘。需要查看其他硬盘时填写其挂载路径。APFS 以共享空间的总量减可用量统计占用，包含其他共享卷使用的空间。`font_path` 可指定一个支持中文的字体文件。

指标属于插件进程所在的操作系统。本机原生部署读取本机；容器部署读取容器可见资源。本插件不访问 Docker API，也不读取或修改外部宿主机。

状态图不显示 IP、用户名、完整挂载路径或进程列表；图片在本机生成后发回触发命令的聊天。安装依赖需要访问 Python 包源，采样和绘图无需联网。
