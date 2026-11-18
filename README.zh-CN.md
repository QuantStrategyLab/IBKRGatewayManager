# IBKRGatewayManager

IBKRGatewayManager 负责让 QuantStrategyLab 交易系统所依赖的 Interactive Brokers Gateway VM 持续在线。它管理这台 VM 的部署、远端同步、Docker 发布，以及让 Gateway 保持登录状态的 2FA watcher，省去运维人员手动点击验证弹窗。InteractiveBrokersPlatform 仓库依赖这个 Gateway 保持在线且已认证，但本仓库本身从不决定哪个策略交易、也不会提交订单。

[English README](README.md)

> 投资有风险。本项目不构成投资建议，仅用于学习、研究和工程审阅。

## 这个仓库是什么

IBKRGatewayManager 是 QuantStrategyLab 的IBKR Gateway 运维工具。管理 IBKR Gateway VM 的部署、远端同步、Docker 发布和 2FA watcher。

它支撑系统运行，但不决定哪个策略应该 live。策略资格由策略仓和 snapshot 仓负责；券商执行由平台仓负责。

## 设计边界

- 下游仓库依赖的契约要保持稳定，必要时做版本化。
- 除非有协同迁移计划，否则优先保持向后兼容。
- 密钥和环境专属配置不要写进共享库代码。
- 会影响多个平台或策略包的改动，需要在文档中说明。
- 遇到小型、通用的 Gateway 弹窗时，系统绝不自动点击确认。若 API 不可用，watcher 最多只会做一次不点击弹窗的容器重启；弹窗仍存在则继续失败关闭，交由人工审阅。

## QSL 架构角色

- **层级**：`运行时运维`。
- **职责**：IBKR gateway VM 生命周期与 2FA 运维工具。
- **事实源/归属**：gateway 部署、remote sync、Docker rollout、watcher setup。
- **消费对象**：InteractiveBrokersPlatform 的运维需求。
- **禁止事项**：决定策略 eligibility 或提交交易订单。

## Gateway 目标配置

部署 workflow 必须使用仓库级 Actions variable `IB_GATEWAY_TARGETS_JSON`。它是以非敏感目标标签为 key 的 JSON object（或每项包含 `name` 的 list）。每个目标自行提供 GCP project、Workload Identity provider、service account、VM 位置和部署参数；仓库中没有默认 gateway 或云账号。

目标的 `maintenance_enabled=false` 仅暂停定时重新部署，不会关闭 VM 上已安装的 Gateway 健康与 2FA 定时器。定时 workflow 在所有目标被跳过时仍可能显示成功；该结果不代表 Gateway API、登录或账户身份已验证。需要运行只读诊断并另行核对账户级证据，不能为了获得绿色状态而重新启用定时部署。

```json
{
  "gateway-a": {
    "gcp_project_id": "<gcp-project-id>",
    "gcp_workload_identity_provider": "projects/<number>/locations/global/workloadIdentityPools/<pool>/providers/<provider>",
    "gcp_workload_identity_service_account": "<service-account>@<gcp-project-id>.iam.gserviceaccount.com",
    "gce_user": "<vm-user>",
    "gce_instance_name": "<vm-name>",
    "gce_zone": "<gcp-zone>",
    "deploy_path": "/opt/ibkr-gateway",
    "mode": "paper",
    "container_name": "<container-name>",
    "compose_project_name": "<compose-project>",
    "compose_service_name": "<compose-service>",
    "cloud_run_egress_cidr": "<trusted-egress-cidr>",
    "allow_connections_from_localhost_only": "no",
    "ssh_private_key_secret_name": "<secret-manager-secret-name>"
  }
}
```

使用 Secret Manager secret 的**名称**，不要写入 secret 值。完整部署要求为 SSH 密钥、Gateway 用户名和密码指定目标专属 secret 名称。VNC 是可选的：不设置 `vnc_server_password_secret_name` 即停用 VNC 服务。TOTP 自动填码默认关闭；显式启用时也必须指定目标专属 TOTP secret 名称。关闭时工作流不读取或下发 TOTP 种子。不得提交目标 JSON、凭证、账户标识、地址或私钥。缺少必需目标配置时，会在任何云认证或远端操作前失败关闭。

可选的 `ib_gateway_base_version` 为单个目标指定 Gateway 基础镜像版本；未设置时使用 `10.50.1e`。仅在该目标完成兼容性核对后调整，其他目标不受影响。

完整部署以 `0600` 权限安装 VM 上的运行环境 `.env`。Gateway 使用配置的用户名和密码；显式启用 `ibkr_2fa_autofill` 时，2FA bot 还会读取该目标的 TOTP 种子并填写兼容的验证弹窗，这条路径不使用 VNC。启用平台流量前仍须核实 API 和账户身份。VM 会保存 Gateway 密码；启用自动填码时也会保存 TOTP 种子，应限制该主机及部署身份的访问权限。

迁移 VM 到新项目时，可选的 `gcp_secret_project_id` 可继续从原项目读取 Secret Manager；不填则使用 `gcp_project_id`。部署 service account 须同时有新 VM 和原项目中指定 secret 的权限。新 VM 就绪且旧 Gateway 停止后，才能修改目标配置。

项目名和 VM 名可用于 IAP 运维，平台服务可通过 VPC 内网地址连接 Gateway；Gateway VM 连接 IBKR 公网仍需单独的互联网出口。移除 VM 外部 IP 后须配置 Cloud NAT 等出口，并计算其费用。

手动只读元数据 workflow 可选对比受保护目标的 SSH 公钥与实例/项目 SSH 密钥元数据。仅在同时启用 `match_current_gateway` 和 `inspect_ssh_policy` 时开启 `inspect_ssh_key_binding`，并保持 `inspect_connections` 关闭。该检查仅返回固定的匹配、不匹配或未知状态，不打开 SSH 连接，也不代表 guest 侧 SSH 健康。启用 OS Login 时元数据密钥对比结果为未知；不匹配也不证明 Gateway 不可达。

同时启用 `match_current_gateway` 和 `inspect_connections` 时，同一受限 IAP SSH 检查还会读取容器实际发布的 TCP 映射，并检查宿主机及目标容器命名空间中的映射容器端口、宿主机 API 端口和 5000 端口，避免混淆宿主机端口与容器端口。输出仅包含固定状态，不含地址或进程详情；不发送 API/HTTP 请求，也不修改运行配置。5000 端口有监听不代表存在 Client Portal Gateway 或有效会话，未监听也不排除其他端口或容器。原生 socket 观测不证明认证状态、现金完整性或资金使用权限。原有的双参数辅助函数及其六字段输出仍受支持；扩展响应仅作为完整字段组接受。

元数据 workflow 的 `inspect_readonly_api=true` 模式会在绑定了精确资源摘要的受保护目标上执行一次受限底层 API 握手。它仅允许 API 启动，不同步账户或订单。独立的 `inspect_contract_details` 开关默认关闭，且依赖该模式；当针对已验证的 SOXL Gateway 显式授权时，会在握手后追加一次 SOXL/SMART/USD 合约定义请求。出站 SDK 端口仅允许启动（71）和这一次固定请求（9），禁止提交、撤单及所有其他请求。连接等待和合约定义等待在原有 25 秒原生上限内各设 10 秒限制，不重试、不重连。

原生进程仅输出固定状态、完成/计数结果、身份匹配布尔值和允许的错误码。不完整记录保持未知，被拒绝的请求不视为成功的空响应，本地合约定义响应也不证明 Cloud Run 链路、账户身份、行情权限或交易就绪。所有原始 SDK 输出和回调错误均被捕获；不发生登录、重启、配置修改或依赖变更。

独立的手动 `Read Native Cash From Existing Gateway` workflow 会在该受保护目标上执行一次主动、受限的读取。其预期单一账户来自 `IB_GATEWAY_EXPECTED_ACCOUNT_SELECTOR_JSON`，从现有运行时的私有选择器复制，而非从目标标签推断。请求数据前会先校验现有 VM 地址和原生托管账户。它使用容器内已安装的 `ib_insync==0.9.86`，不安装、不重启、不登录、不部署容器，也不创建云资源。原生出站消息仅限于 API 启动、所选账户更新（含取消订阅）和全客户端未成交订单读取；不允许汇总请求、订单写入或自动绑定。使用随机非零 client ID 以避开 SDK 的零号客户端手动订单绑定路径；冲突时直接失败，不重试。

该 workflow 仅输出固定字段状态/计数及证据摘要。现金数值和所选 API 订单保存在现有容器 `/tmp` 下新建的 `0700` 目录中，写入仅新建、权限为 `0600` 的 `observation.json`。回读会在本地校验这些字节。这属于容器本地证据，而非持久云端报告；容器替换可能导致其丢失。缺失的交割字段、划转义务和持久存储仍属于明确缺口。空的 API 订单结果不证明已覆盖所有账户义务或资金使用权限。

如需检查成功运行已保存的交割相关字段名，请同时提供其 `saved_capture_id` 和 `saved_evidence_sha256`。该模式会在仅返回 tag/币种/计数元数据之前，校验私有文件的权限、精确摘要、账户、捕获标识和完成读取标记；不会构造 SDK 客户端或重连券商。数值行计数仅表示采集器按十进制保留的内容，不确立交割语义，也不允许标签别名。文件缺失或绑定不匹配时直接失败，不回退到新的券商请求。

`SettledCashByDate`、`SettledCashByDate-C` 和 `SettledCashByDate-S` 仅作为受限原始字符串保留在私有观测文件中。时间表不是标量十进制数：诊断不会丢弃其文本，也不会将其别名为 `SettledCash`。公开输出仅展示行数和语法形态，并将所有数字/字母串折叠，使日期和金额保持私有。解析时间表、选择日期/分部以及确定其财务含义需要各自经过验证的来源契约；此诊断不授予任何资金使用权限。

公开采集脚本会经过 gzip/base64 打包后通过 SSH stdin 传输，并在执行前于现有 Linux 宿主机上校验其精确源码摘要。账户绑定信息仍仅通过 stdin 传递，绝不放在命令行参数中。捕获 UUID 会在传输前输出，以便在读取中断后无需再次向券商发起请求即可检查。超时时间不会被延长。

已保存回读还会报告单对语法、数字键形态以及同一捕获中总额、证券与商品分部之间的精确算术关系。零键不假定为当日，日历形态的键也不指定券商时区；与捕获账面现金相等不证明交割语义。多条目、缺失原始文本和重复项均会显式保留；不会选定某一条目作为当前现金，也不会修改生产现金适配器。

同时提供两个已保存绑定参数时，可选的 `retain_saved_on_host` 开关会将校验通过的原始字节复制到现有宿主机用户的私有 `~/.qsl-native-cash-evidence/<capture UUID>/observation.json`。该复制复用现有 SSH/Docker 访问，保留原始 SHA256，创建 `0700`/`0600` 路径并校验字节回读。已存在相同副本时仅执行读取；冲突文件绝不覆盖。Docker 归档仅保留在宿主机内存中，不解压，且只接受单个常规文件；原始字节不经 SSH 回传。在宿主机磁盘保留期间，该副本可跨越容器替换保留，但它不是经过验证的云端报告，也不能防止 VM 或磁盘丢失。该开关默认关闭且依赖已保存文件模式，从不重连券商；若请求的保留失败，任务将失败，同时保留单独的已保存读取结果。不会创建权限、存储服务或 Gateway 部署。

同一 workflow 接受 `runtime_preflight=true`，用于对受保护的匹配宿主机执行仅元数据检查。该模式与已保存捕获和保留参数互斥。它会检查现有 Docker 镜像来源标签、运行中 Gateway 容器内已安装的发行包元数据，以及宿主机可用内存/磁盘；从不拉取或启动镜像、导入券商/策略包、读取容器配置、连接券商，也不修改软件或状态。仅固定状态和资源计数离开 Linux。候选镜像标签不构成来源验证，容器内缺失的包不代表其他环境，且检查结果从不授予运行时或交易就绪状态。

`runtime_image_access=true` 会单独使用 VM 挂载的 service account token 检查固定的原始平台镜像清单。其私有不可变定位符来自 `PILOT_RUNTIME_BASE_IMAGE`，不作为公开 workflow 输入。该检查与其他模式互斥，拒绝重定向和代理，并校验返回字节与准入摘要一致；从不拉取镜像层、启动运行时或修改权限，被拒绝时立即停止操作。

`runtime_identity_diagnostic=true` 仅诊断该 VM 认证阶段。它报告已读取的 VM 元数据中挂载的 service account 数量，并发起一次带有固定 HTTP/传输/响应状态的元数据 token 请求；从不请求镜像仓库、重试请求、修改身份，也不打印 token、账户身份或错误正文。该模式与所有其他模式互斥。

## 仓库结构

- `tests/`：单元测试、契约测试和回归测试。
- `.github/workflows/`：CI、定时任务、发布或部署 workflow。
- `scripts/`：运维脚本和本地辅助工具。

## 快速开始

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

## 延伸文档

- 暂无独立 `docs/` 目录；请先阅读本 README 和 workflow 文件。

## QSL 兼容性

- `qsl.toml` 记录 `tier`、`upgrade_ring` 和 `compat.bundle`，用于兼容性检查。
- 这个 Gateway 运维工具从 `requirements.txt` 安装 Python 依赖。

## 社区和安全

- 贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，确认 PR 范围、本地校验和文档要求。
- 讨论、issue 和 review 请遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
- 涉及密钥、自动化、券商/交易所或云资源的漏洞请按 [SECURITY.md](SECURITY.md) 私密报告；不要为 secret 或实盘风险开公开 issue。

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。AI 助手与维护者遵循 [AGENTS.md](AGENTS.md)。

## 许可证

详见 [LICENSE](LICENSE)。
