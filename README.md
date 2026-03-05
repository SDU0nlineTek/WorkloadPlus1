# 工作量+1 (WorkloadPlus1)

一个面向团队内部的极简工作填报系统，支持成员快速记录工作、管理员统计分析与结算导出。

## 项目简介

`工作量+1` 适用于学生组织、实验室、社团或小型团队的日常工作记录与汇总场景。

核心目标：

- 让成员以最低成本完成工作填报
- 让管理员按部门、成员、项目快速查询与汇总
- 支持结算周期申报与 Excel 导出

## 主要功能

- 用户登录与身份管理
- 工作记录填报（支持批量提交）
- 个人时间线查看与筛选
- 部门统计与活动热力图
- 成员管理与管理员权限控制
- 结算周期管理与个人申报
- Excel 导出（个人汇总 / 项目汇总）

## 技术栈

- 后端框架：`FastAPI`
- 数据模型：`SQLModel`
- 模板引擎：`Jinja2`
- 数据库：`SQLite`（默认）
- 前端交互：`HTMX` + 少量原生 JavaScript
- 包管理：`uv`
- 管理命令：`Typer`

## 项目结构

```text
CommitMyLabor/
├── app/
│   ├── main.py                # FastAPI 应用入口
│   ├── cli.py                 # Typer 管理命令
│   ├── config.py              # 配置管理
│   ├── database.py            # 数据库连接与会话
│   ├── models/                # 数据模型
│   ├── routers/               # 路由层
│   ├── services/              # 业务服务
│   ├── templates/             # Jinja2 模板
│   └── static/                # 静态资源
├── pyproject.toml
└── README.md
```

## 环境要求

- Python `>= 3.14`
- 建议使用 `uv` 管理依赖

## 快速开始

1. 创建环境

```shell
uv sync
```

2. 启动应用

```shell
uv run uvicorn app.main:app
```

启动后访问：`http://127.0.0.1:8000`

## 常用命令

- 初始化数据库

```power
uv run workload init-db
```

- 生成测试数据

```powershell
uv run workload seed-data
```

- 创建部门

```powershell
uv run workload create-dept "新媒体中心"
```

- 查看部门列表

```powershell
uv run workload list-dept
```

## 开发说明

- 主应用入口：`app/main.py`
- CLI 入口：`app/cli.py`
- 根目录 `main.py` / `cli.py` / `seed_data.py` 为兼容入口，可继续使用。

