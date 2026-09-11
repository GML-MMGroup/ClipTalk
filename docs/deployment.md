# 部署、模型来源与维护

## 服务器访问

本机默认监听 `127.0.0.1:5180`，并发分析为 1，不要求访问令牌。
对外服务需要设置独立的随机访问令牌，并由 HTTPS 反向代理保护访问：

```dotenv
HIGHLIGHT_HOST=0.0.0.0
HIGHLIGHT_PORT=5180
HIGHLIGHT_ALLOW_UNAUTHENTICATED_REMOTE=false
# 填入自己生成的至少 16 字符随机令牌，不要提交到 GitHub。
HIGHLIGHT_ACCESS_TOKEN=
```

以上令牌留空时，对外监听会拒绝启动，这是安全检查，不是安装故障。
普通访问者无需配置服务器环境变量，只需在受保护页面输入部署者提供的令牌。
项目目前仍是单用户应用，令牌不是多租户账户隔离；不要将它当成公共多人素材托管服务。

高级参数见 [environment.example](environment.example)。不要整份复制后原样使用。
通过页面保存的模型密钥位于本机数据目录，不应打包上传。

## 启动方式

- `bash start.sh`：前台统一管理网页和本地 AI 助手，优先使用项目 `.venv`。
- `bash start.sh --check`：只检查，不启动。
- `bash start.sh --external-agent`：网页使用独立部署的助手，不尝试启动助手。
- `bash restart.sh`：原有服务器维护脚本，仅重启网页后端；独立助手保持运行。
- `docker compose up --build -d`：Compose 分别管理网页和助手，默认安装 CPU 版 TalkNet。
- `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d`：GPU 部署；需支持 NVIDIA GPU 的容器运行环境。

不要同时使用前台启动器和 `restart.sh` 管理同一个网页实例。长期部署应选择一个服务管理方式。
独立助手使用 `CLIPTALK_AGENT_SERVICE_URL`；跨容器或跨主机时，双方必须配置相同的独立服务令牌。
本机默认通过数据目录中的 `agent/service-token` 自动共享令牌。
启动器只会复用健康且凭据匹配的本地助手，不会接管或终止其他进程。

## TalkNet 默认安装

`python3 tools/setup.py` 会调用 `tools/install_talknet.py`，不是安装后再让用户手动配路径。
代码固定到 TalkNet-ASD 提交 `6d6821479af485e251c4991487e40573b42181b4`。
隔离依赖位于 `tools/requirements-talknet.txt`，PyTorch 采用项目现有的 2.2.0 CPU/CUDA 12.1 配套版本。
GPU 安装仅在可见驱动满足 CUDA 12.1 的最低要求时自动选择；设备是否实际可用以最终检查为准。

默认布局：

```text
data/models/talknet/
  venv/bin/python
  repository/                 # 保留第三方 LICENSE.md
  pretrain_TalkSet.model
  install.json                # 安装状态和本地权重摘要
```

以下变量默认无需填写；非空时优先使用指定值，不会被自动发现覆盖：
`HIGHLIGHT_TALKNET_PYTHON`、`HIGHLIGHT_TALKNET_REPOSITORY`、`HIGHLIGHT_TALKNET_CHECKPOINT`、`HIGHLIGHT_TALKNET_WORKER`。
`HIGHLIGHT_TALKNET_DEVICE=auto` 会优先使用可用 GPU，否则使用 CPU。
`cuda:N` 按当前进程可见设备编号，兼容 `CUDA_VISIBLE_DEVICES` 的设备映射。
`primary` 使用模型结果作为主要依据；`shadow` 仅用于对比；`off` 明确关闭该能力。

CPU 兼容适配只替换设备选择和权重载入位置，并增加跳过上游演示视频渲染的选项；不改模型结构。
安装验收检查依赖、模型载入及小型前向计算，但不等于任何素材都能准确识别。
不可用时，人物说话检索会在开始检索时显示降级提醒，结果仍需人工核对。

### 模型来源与第三方条件

- [TalkNet-ASD 官方仓库](https://github.com/TaoRuijie/TalkNet-ASD)：代码及第三方组件来源。
- [官方代码许可证](https://github.com/TaoRuijie/TalkNet-ASD/blob/6d6821479af485e251c4991487e40573b42181b4/LICENSE.md)：MIT，安装目录保留版权与许可证。
- [官方 demo](https://github.com/TaoRuijie/TalkNet-ASD/blob/6d6821479af485e251c4991487e40573b42181b4/demoTalkNet.py)：TalkSet 权重下载来源。
- [官方 S3FD 实现](https://github.com/TaoRuijie/TalkNet-ASD/tree/6d6821479af485e251c4991487e40573b42181b4/model/faceDetector/s3fd)：人脸检测权重及相关来源。

安装脚本从原始来源下载权重，不将第三方模型改称为本项目资产。
代码许可证不代表训练数据、人物素材或所有权重都获得无限制使用授权；部署和再分发前应核对对应条件。
源码仓库排除模型权重；默认构建的 Docker 镜像包含模型，公开分发镜像前也需要核对相关条件。
`install.json` 的 SHA-256 记录用于追踪已安装文件，不是上游签名或来源真实性证明。

### 迁移现有手动安装

现有 `.env` 中的绝对路径继续生效。默认安装器发现未由自己管理的 TalkNet 目录时，仅检查，不覆盖。
要迁移到自动安装，先备份并移走原 TalkNet 目录，再清除 `.env` 中不再需要的路径覆盖，重新运行安装命令。
不要在正在进行人物识别时迁移。保留原目录即可在失败时恢复。
显式指定设备不可用、旧代码没有 CPU 适配或权重损坏时，会报错而非假装可用。

## GitHub 发布前检查

保留 README、安装文档和配置示例；不提交 `.env`、`data/`、模型缓存、虚拟环境、任务数据或密钥。
`.gitignore` 不能移除已被 Git 跟踪的秘密；发布前检查暂存内容，误提交的密钥应撤销并更换。

```bash
python3 tools/check_repository.py
python3 tools/setup.py --dry-run
python3 -m pytest -q tests/test_distribution.py tests/test_repository_tools.py tests/test_active_speaker.py tests/test_talknet_worker.py
```

运行中的源码快照可能包含本机 `.env` 和数据目录；可用 `--mode deployment` 做部署检查，不能据此声称源码包没有私有数据。
正式发布前仍应在干净 Linux/WSL2 或 Docker 环境完成真实安装，并各用一段短视频验证 CPU/GPU 人物说话识别。
