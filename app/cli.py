"""CLI 管理工具"""

import typer
from rich import print as rprint
from rich.table import Table
from sqlmodel import Session, select

from app.database import create_db_and_tables, engine
from app.models import Department, User, UserDeptLink

app = typer.Typer(help="工作量+1 管理工具")


@app.command()
def init_db():
    """初始化数据库"""
    # 确保模型已加载
    import app.models  # noqa: F401

    create_db_and_tables()
    rprint("[green]数据库初始化成功！[/green]")


@app.command()
def create_dept(name: str):
    """创建部门"""
    with Session(engine) as session:
        # 检查是否已存在
        existing = session.exec(
            select(Department).where(Department.name == name)
        ).first()
        if existing:
            rprint(f"[yellow]部门 '{name}' 已存在[/yellow]")
            return

        dept = Department(name=name)
        session.add(dept)
        session.commit()
        session.refresh(dept)
        rprint(f"[green]部门 '{name}' 创建成功，ID: {dept.id}[/green]")


@app.command()
def list_dept():
    """列出所有部门"""
    with Session(engine) as session:
        depts = session.exec(select(Department)).all()
        if not depts:
            rprint("[yellow]暂无部门[/yellow]")
            return

        table = Table(title="部门列表")
        table.add_column("ID", style="cyan")
        table.add_column("名称", style="green")
        table.add_column("活跃周期(月)", style="yellow")

        for dept in depts:
            table.add_row(
                str(dept.id), dept.name, str(dept.active_project_window_months)
            )

        rprint(table)


@app.command()
def add_admin(sduid: str, dept_name: str):
    """根据学号设置某用户为部门管理员"""
    with Session(engine) as session:
        # 查找用户
        user = session.exec(select(User).where(User.sduid == sduid)).first()
        if not user:
            rprint(f"[red]未找到学号为 '{sduid}' 的用户[/red]")
            return

        # 查找部门
        dept = session.exec(
            select(Department).where(Department.name == dept_name)
        ).first()
        if not dept:
            rprint(f"[red]未找到部门 '{dept_name}'[/red]")
            return

        # 检查关联是否存在
        link = session.exec(
            select(UserDeptLink).where(
                UserDeptLink.user_id == user.id, UserDeptLink.dept_id == dept.id
            )
        ).first()

        if link:
            link.is_admin = True
        else:
            link = UserDeptLink(user_id=user.id, dept_id=dept.id, is_admin=True)
            session.add(link)

        session.commit()
        rprint(
            f"[green]用户 '{user.name}' ({sduid}) 已设为部门 '{dept_name}' 的管理员[/green]"
        )


@app.command()
def list_users():
    """列出所有用户"""
    with Session(engine) as session:
        users = session.exec(select(User)).all()
        if not users:
            rprint("[yellow]暂无用户[/yellow]")
            return

        table = Table(title="用户列表")
        table.add_column("ID", style="cyan")
        table.add_column("姓名", style="green")
        table.add_column("学号", style="yellow")
        table.add_column("手机", style="blue")

        for user in users:
            table.add_row(str(user.id), user.name, user.sduid, user.phone)

        rprint(table)


@app.command()
def set_window(dept_name: str, months: int = 3):
    """设置部门的活跃项目判定周期"""
    with Session(engine) as session:
        dept = session.exec(
            select(Department).where(Department.name == dept_name)
        ).first()
        if not dept:
            rprint(f"[red]未找到部门 '{dept_name}'[/red]")
            return

        dept.active_project_window_months = months
        session.commit()
        rprint(f"[green]部门 '{dept_name}' 活跃周期已设为 {months} 个月[/green]")


@app.command("seed-data")
def seed_data_cmd():
    """生成测试数据"""
    from app.seed_data import main as seed_data_main

    seed_data_main()


if __name__ == "__main__":
    app()
