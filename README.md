# 工作量+1 (WorkloadPlus1)

一个面向团队内部的极简工作填报系统，支持成员快速记录工作、管理员统计分析与结算导出。

## 项目简介

`工作量+1` 适用于学生组织、实验室、社团或小型团队的日常工作记录与汇总场景。

核心目标：

- 让成员以最低成本完成工作填报，完成工作后及时记录，避免集中填写时出现遗忘的问题。
- 让管理员按部门、成员、项目快速查询与汇总
- 支持结算周期申报与 Excel 导出

## 功能描述

### 成员端

- 用户登录与身份识别
- 工作记录填报（支持单条与批量）
- 个人时间线查看与筛选（含活跃热力图）
- 记录项支持相关内容字段（链接/文本）展示
- 申报页面按项目展示未申报记录，支持多选提交

### 管理端

- 部门统计与活动热力图
- 部门管理（成员管理 + 项目可见性）
- 结算周期管理（周期创建、查看、关闭）
- 结算详情中的成员申报查看与项目状态总结
- Excel 导出（个人 / 项目 / 统计）

### 结算与数据

- 申报支持按记录勾选，提交后已选记录自动标记为已申报
- 申报时长以分钟为最小计算单位，避免浮点误差
- `SettlementClaim` 使用分钟整数字段存储：`paid_minutes`、`volunteer_minutes`、`total_minutes`
- 支持旧库平滑迁移与历史小时字段回填

## 配置说明

项目使用 `.env` 读取运行配置（见 `.env.example`）：

- `debug`
- `database_url`
- `secret_key`
- `session_cookie`
- `session_max_age`

## 技术栈

- 后端框架：`FastAPI`
- 数据模型：`SQLModel`
- 模板引擎：`Jinja2`
- 数据库：`SQLite`（默认）
- 前端交互：`HTMX` + 少量原生 JavaScript
- 包管理：`uv`
- 管理命令：`Typer`
- 数据库迁移：`Alembic`

## 项目结构

```text
CommitMyLabor/
├── app/
│   ├── main.py                # FastAPI 应用入口
│   ├── cli.py                 # Typer 管理命令
│   ├── core/                  # 核心配置与数据库
│   │   ├── config.py
│   │   └── database.py
│   ├── models.py              # 数据模型
│   ├── routers/               # 路由层
│   ├── utils/                 # 业务工具（导出/热力图/脚本）
│   ├── templates/             # Jinja2 模板
│   └── static/                # 静态资源
├── alembic/                   # Alembic 迁移目录
├── alembic.ini
├── pyproject.toml
├── .env.example
└── README.md
```

## 环境要求

- Python `>= 3.14`
- 建议使用 `uv` 管理依赖

## 快速开始

1. 安装依赖

  ```shell
  uv sync
  ```

1. 执行数据库迁移

  ```shell
  uv run alembic upgrade head
  ```

1. 启动应用

  ```shell
  uv run uvicorn app.main:app
  ```

启动后访问：`http://127.0.0.1:8000`

## 常用命令

- 初始化数据库

  ```shell
  uv run workload init-db
  ```

- 生成测试数据

  ```shell
  uv run workload seed-data
  ```

- 创建部门

  ```shell
  uv run workload create-dept "新媒体中心"
  ```

- 查看部门列表

  ```shell
  uv run workload list-dept
  ```

- 生成随机 `secret_key`

  ```shell
  uv run workload gen-secret
  ```

## 更新日志

### 0.0.5 - 2026-03-22

- 申报流程重构（按记录勾选）
  - 用户申报页可按项目查看并勾选「未申报工作记录」，默认全选。
  - 支持全局全选/全不选，以及按项目全选/全不选。
  - 仅勾选记录参与本次申报计算，提交后对应记录会标记为 `claimed=true`。
  - 记录不在当前结算周期时间范围内时，前端默认不勾选。

- 申报输入与校验升级（分钟精度）
  - 工资时长改为「小时(整数) + 分钟(整数)」，志愿时长为「小时(整数)」。
  - 前后端统一按分钟整数校验，避免浮点误差。
  - 总时长展示改为「X小时Y分钟」。

- 结算数据模型升级（分钟存储）
  - `SettlementClaim` 新增分钟整数字段：`paid_minutes`、`volunteer_minutes`、`total_minutes`。
  - 保留小时属性兼容层，旧代码可继续通过 `paid_hours` 等属性读取。
  - 启动时自动执行轻量迁移：为旧库补齐分钟字段并从旧小时字段回填。

- 页面显示优化
  - 时间线中记录卡片优化为标题与时长同一行，部门与相关内容同一行，相关内容可识别链接。
  - 部门统计页筛选结果增加「相关内容」展示（移动端卡片与桌面表格均支持）。

- 记录展示优化
  - 填报页侧栏由「今日记录」调整为「最近记录（最近24小时）」。

- 数据库迁移
  - 引入 Alembic，新增迁移脚本：补齐 `work_record.claimed`，并将 `settlement_claim` 升级为分钟整数字段（含旧小时字段回填）。

### 0.0.4 - 2026-03-06

- 全局部门上下文
  - 侧边栏新增部门切换器，切换后全站按当前部门上下文工作。
  - 管理端菜单按当前部门管理员权限动态显示。
  - `/profile` 页面下线并重定向到 `/record`，移除侧边栏个人资料入口。
  - Session 配置支持通过环境变量注入 `session_cookie` 和 `session_max_age`。

- 热力图升级
  - 时间线与管理端统计页热力图改为周日到周六排序。
  - 增加星期与月份标注、格子悬浮提示。
  - 时间线支持点击某天筛选，选中后其他日期变暗但不隐藏。
  - 统一优化热力图容器尺寸，避免出现纵向滚动。

- 部门管理重构
  - 管理端“成员管理”升级为“部门管理”（路由：`/admin/department`）。
  - 支持项目可见性开关，填报页项目下拉仅展示“可见”项目。
  - 成员管理中管理员不能被移除（后端限制 + 前端按钮隐藏）。
  - 新增旧库兼容补丁：启动时自动为 `project` 表补齐 `is_visible` 字段（若缺失）。

- 结算增强
  - 新增结算项目维度信息：项目状态 + 项目总结。
  - 管理员可在结算详情页按项目填写并保存，支持回显与校验。
  - 项目状态选项改为 `StrEnum`。
  - 管理端结算相关接口统一使用 Period 级依赖（按当前部门和周期鉴权）。
  - 用户申报接口迁移到记录路由：`/claim/{period_id}`。
  - 侧边栏“报酬申报”改为前端快捷入口（`/record?quick_claim=1`）。

- 导出增强
  - 导出重构为 3 个工作表：`个人`、`项目`、`统计`。
  - 去除分钟列，统一使用小时列；总时长改为 Excel 公式计算。
  - 支持按成员/项目分块合并单元格，提升可读性。
  - `统计` 表新增项目统计（含状态/总结）与个人统计，左右并列布局。
  - 导出文件名包含秒级时间戳与筛选条件（结算标题或自定义筛选条件）。
  - Excel 文档元数据写入应用名（`creator` / `lastModifiedBy`）。

- 配置与代码收敛
  - 应用结构重构：`config/database` 迁移到 `app/core`，业务工具迁移到 `app/utils`。
  - 全局统一使用 `app.core.settings` 与 `SessionDep`。
  - 新增 CLI 命令：`workload gen-secret`。
  - 移除部门活跃窗口配置（`active_project_window_months`）及相关 CLI 命令。

## 开发说明

- 主应用入口：`app/main.py`
- CLI 入口：`app/cli.py`
- 核心模块：`app/core/`
- 工具模块：`app/utils/`
