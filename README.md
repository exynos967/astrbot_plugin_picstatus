# PicStatus

以图片形式展示当前设备的运行状态，方便在群聊或私聊中一眼查看 CPU、内存、磁盘、网络等指标。  
本插件基于 AstrBot 的 HTML 文转图（t2i）能力渲染，无需在插件内额外安装浏览器。

## 功能概览

- 显示当前主机关键指标：
  - CPU 使用率 / 物理核心数 / 逻辑线程数 / 主频信息
  - 内存 / 交换分区 使用情况
  - 各挂载盘空间占用 / TOP I/O 情况
  - 网卡上下行速率
  - 访问「百度 / Google」的网络连通性与延迟
  - TOP 进程 CPU / 内存占用
- 头部展示：
  - Bot 头像（自动获取 QQ 头像或默认头像）
  - Bot 名称（支持配置显示文字）
  - AstrBot 运行时长 / 系统运行时长

## 指令说明

- 指令：`运行状态`

具体触发方式取决于你在 AstrBot 中配置的前缀和唤醒词，例如：

- `#运行状态`
- `/运行状态`

当指令被触发时，插件会：

1. 收集当前系统状态（CPU / 内存 / 磁盘 / 网络 / 进程等）。
2. 选择背景图（优先使用消息中携带的图片，其次远程 API / 本地图）。
3. 通过 AstrBot 的 t2i 服务将 HTML 模板渲染为图片。
4. 将图片发送回当前会话。

## 安装与依赖

### 1. 放置插件目录

将本目录 `astrbot_plugin_picstatus/` 放入 AstrBot 的插件目录中，例如：

```text
astrbot_root/
  └─ data/
     └─ plugins/
        └─ astrbot_plugin_picstatus/
            main.py
            collectors.py
            bg_provider.py
            t2i_renderer.py
            templates/
            res/
            ...
```

### 3. AstrBot t2i 服务

本插件依赖 AstrBot Core 提供的 HTML 文转图（t2i）能力：

- 请确保 AstrBot 已正确配置 t2i 服务（远程或本地）。
- 插件内部通过 `self.html_render(...)` 调用 AstrBot 的 t2i 渲染接口。

## 背景图来源逻辑

背景图由 `bg_provider.py` 与指令处理逻辑共同决定，优先级如下：

1. **消息中的图片**
   - 如果触发指令的消息中包含图片（`Image` 消息段），且 `file` 字段为 `http(s)` 链接，插件会尝试下载该图片作为背景。

2. **远程 API（loli）**
   - 环境变量 `PICSTATUS_BG_PROVIDER` 默认为 `"loli"`。
   - 当未使用消息内图片时，会调用 `https://www.loliapi.com/acg/pe/` 获取一张随机背景图。

3. **本地背景**
   - 若设置了环境变量 `PICSTATUS_BG_LOCAL_PATH`，且路径存在，则尝试读取该本地图片作为背景。

4. **内置默认背景**
   - 上述都不可用时，回退到 `res/assets/default_bg.webp` 作为背景。

## 采集内容一览

采集逻辑集中在 `collectors.py`，调用一次 `collect_all()` 会返回一个包含以下键的字典，供模板使用：

- CPU：
  - `cpu_percent`：CPU 总使用率
  - `cpu_count`：物理核心数
  - `cpu_count_logical`：逻辑线程数
  - `cpu_freq`：当前/最大主频（MHz/GHz）
  - `cpu_brand`：CPU 品牌型号
- 内存：
  - `memory_stat`：总量、已用、占比
  - `swap_stat`：交换分区总量、已用、占比
- 磁盘：
  - `disk_usage`：各挂载点已用/总量/占用百分比
  - `disk_io`：按读写总量排序的 TOP 几个磁盘 I/O
- 网络：
  - `network_io`：各网卡的上行/下行速率
  - `network_connection`：访问百度/Google 的 HTTP 状态与延迟
- 进程：
  - `process_status`：按 CPU 使用率排序的 TOP 进程（CPU%、RSS 内存）
- 运行时间与系统信息：
  - `bot_run_time`：AstrBot 运行时长
  - `system_run_time`：系统启动至今的运行时长
  - `time`：当前时间字符串
  - `python_version`：Python 版本
  - `system_name`：系统名称（如 `Linux 6.8.0 (x86_64)`）

这些数据会被注入 Jinja2 模板，生成最终的状态图。

## 注意事项

- **性能与资源**
  - 插件在每次调用时都会采集系统状态并发起 2 个 HTTP 请求（百度/Google），请在网络环境较差的机器上适当调整调用频率。
  - 获取背景图与头像图也会触发网络请求，超时时间默认为 5～10 秒。
- **平台兼容**
  - 头像获取逻辑目前主要针对 QQ（`aiocqhttp`）平台使用 qlogo 接口，其他平台会回退到内置默认头像。
- **安全**
  - 使用消息中的图片作为背景时，会直接请求图片 URL，请确保上游适配器对该字段进行了必要过滤。

## 特别感谢

- [nonebot-plugin-picstatus](https://github.com/lgc-NB2Dev/nonebot-plugin-picstatus)[LgCookie](https://github.com/lgc2333)
