# IBKRGatewayManager


## QSL 架构角色

- **层级**：`运行时运维`。
- **职责**：IBKR gateway VM 生命周期与 2FA 运维工具。
- **事实源/归属**：gateway 部署、remote sync、Docker rollout、watcher setup。
- **消费对象**：InteractiveBrokersPlatform 的运维需求。
- **禁止事项**：决定策略 eligibility 或提交交易订单。

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

## Gateway 目标配置

部署 workflow 必须使用仓库级 Actions variable `IB_GATEWAY_TARGETS_JSON`。它是以非敏感目标标签为 key 的 JSON object（或每项包含 `name` 的 list）。每个目标自行提供 GCP project、Workload Identity provider、service account、VM 位置和部署参数；仓库中没有默认 gateway 或云账号。

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

使用 Secret Manager secret 的**名称**，不要写入 secret 值。完整部署要求为 SSH 密钥和 VNC 密码指定目标专属 secret 名称；自动登录目标另需 Gateway 用户名和密码名称。TOTP 自动填码默认关闭；显式启用时也必须指定目标专属 TOTP secret 名称。关闭时工作流不读取或下发 TOTP 种子。不得提交目标 JSON、凭证、账户标识、地址或私钥。缺少目标配置时，会在任何云认证或远端操作前失败关闭。

完整部署以 `0600` 权限安装 VM 上的运行环境 `.env`。人工认证目标设置 `manual_auth: true`、`ibkr_2fa_autofill: "no"`、`maintenance_enabled: false`。完整部署此时只下发 VNC 凭据并启动容器，保持恢复定时器停用，报告 `GATEWAY_MANUAL_AUTH_REQUIRED=true`；这不代表券商登录或 API 就绪。经临时 IAP/SSH VNC 隧道人工登录后，应先核实 API 和账户身份，再启用平台流量。默认自动登录路径仍会把 Gateway 密码放在 VM 上，不适用于完全人工认证要求。

迁移 VM 到新项目时，可选的 `gcp_secret_project_id` 可继续从原项目读取 Secret Manager；不填则使用 `gcp_project_id`。部署 service account 须同时有新 VM 和原项目中指定 secret 的权限。新 VM 就绪且旧 Gateway 停止后，才能修改目标配置。

项目名和 VM 名可用于 IAP 运维，平台服务可通过 VPC 内网地址连接 Gateway；Gateway VM 连接 IBKR 公网仍需单独的互联网出口。移除 VM 外部 IP 后须配置 Cloud NAT 等出口，并计算其费用。

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

## 社区和安全

- 贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，确认 PR 范围、本地校验和文档要求。
- 讨论、issue 和 review 请遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
- 涉及密钥、自动化、券商/交易所或云资源的漏洞请按 [SECURITY.md](SECURITY.md) 私密报告；不要为 secret 或实盘风险开公开 issue。

## 许可证

详见 [LICENSE](LICENSE)。
