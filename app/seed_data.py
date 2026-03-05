"""测试数据生成脚本"""

from datetime import datetime, timedelta
from random import choice, randint

from sqlmodel import Session, func, select

from app.database import create_db_and_tables, engine
from app.models import (
    Department,
    Project,
    SettlementClaim,
    SettlementPeriod,
    User,
    UserDeptLink,
    WorkRecord,
)


def create_test_data():
    """创建测试数据"""
    with Session(engine) as session:
        # 检查是否已有数据
        existing_users = session.exec(select(User)).all()
        if existing_users:
            print("数据库中已有数据，跳过测试数据生成")
            return

        print("开始生成测试数据...")

        # 1. 创建部门
        departments_data = [
            {"name": "新媒体中心", "window_months": 3},
            {"name": "技术部", "window_months": 3},
            {"name": "运营部", "window_months": 2},
        ]

        depts = []
        for data in departments_data:
            dept = Department(
                name=data["name"], active_project_window_months=data["window_months"]
            )
            session.add(dept)
            depts.append(dept)
        session.commit()
        for d in depts:
            session.refresh(d)
        print(f"✓ 创建了 {len(depts)} 个部门")

        # 2. 创建用户
        users_data = [
            {"name": "张三", "sduid": "2021001", "phone": "13800000001"},
            {"name": "李四", "sduid": "2021002", "phone": "13800000002"},
            {"name": "王五", "sduid": "2021003", "phone": "13800000003"},
            {"name": "赵六", "sduid": "2021004", "phone": "13800000004"},
            {"name": "钱七", "sduid": "2021005", "phone": "13800000005"},
            {"name": "孙八", "sduid": "2021006", "phone": "13800000006"},
        ]

        users = []
        for data in users_data:
            user = User(name=data["name"], sduid=data["sduid"], phone=data["phone"])
            session.add(user)
            users.append(user)
        session.commit()
        for u in users:
            session.refresh(u)
        print(f"✓ 创建了 {len(users)} 个用户")

        # 3. 创建用户-部门关联（设置管理员）
        # 张三 - 新媒体中心管理员
        link1 = UserDeptLink(user_id=users[0].id, dept_id=depts[0].id, is_admin=True)
        session.add(link1)

        # 李四 - 新媒体中心成员
        link2 = UserDeptLink(user_id=users[1].id, dept_id=depts[0].id, is_admin=False)
        session.add(link2)

        # 王五 - 技术部管理员
        link3 = UserDeptLink(user_id=users[2].id, dept_id=depts[1].id, is_admin=True)
        session.add(link3)

        # 赵六 - 技术部成员 + 运营部成员
        link4 = UserDeptLink(user_id=users[3].id, dept_id=depts[1].id, is_admin=False)
        link5 = UserDeptLink(user_id=users[3].id, dept_id=depts[2].id, is_admin=False)
        session.add(link4)
        session.add(link5)

        # 钱七 - 运营部管理员
        link6 = UserDeptLink(user_id=users[4].id, dept_id=depts[2].id, is_admin=True)
        session.add(link6)

        # 孙八 - 新媒体中心成员
        link7 = UserDeptLink(user_id=users[5].id, dept_id=depts[0].id, is_admin=False)
        session.add(link7)

        session.commit()
        print("✓ 创建了用户-部门关联")

        # 4. 创建项目
        projects_data = [
            {"name": "公众号推文", "dept_id": depts[0].id},
            {"name": "视频剪辑", "dept_id": depts[0].id},
            {"name": "海报设计", "dept_id": depts[0].id},
            {"name": "网站开发", "dept_id": depts[1].id},
            {"name": "小程序维护", "dept_id": depts[1].id},
            {"name": "活动策划", "dept_id": depts[2].id},
            {"name": "用户调研", "dept_id": depts[2].id},
        ]

        projects = []
        for data in projects_data:
            project = Project(
                dept_id=data["dept_id"],
                name=data["name"],
                last_active_at=datetime.now() - timedelta(days=randint(0, 60)),
            )
            session.add(project)
            projects.append(project)
        session.commit()
        for p in projects:
            session.refresh(p)
        print(f"✓ 创建了 {len(projects)} 个项目")

        # 5. 创建工作记录（最近30天）
        descriptions = [
            "完成了推文排版和发布",
            "剪辑了活动宣传视频",
            "设计了活动海报",
            "修复了网站bug",
            "优化了数据库查询",
            "撰写了活动方案",
            "进行了用户访谈",
            "整理了会议纪要",
            "制作了数据报表",
            "更新了文档资料",
        ]

        records_count = 0
        for _ in range(50):  # 创建50条记录
            user = choice(users)
            # 获取用户的部门
            user_depts = session.exec(
                select(UserDeptLink).where(UserDeptLink.user_id == user.id)
            ).all()
            if not user_depts:
                continue

            user_dept = choice(user_depts)
            dept_projects = [p for p in projects if p.dept_id == user_dept.dept_id]
            if not dept_projects:
                continue

            project = choice(dept_projects)

            # 随机时间（最近30天）
            days_ago = randint(0, 30)
            hours_ago = randint(0, 23)
            created_at = datetime.now() - timedelta(days=days_ago, hours=hours_ago)

            record = WorkRecord(
                user_id=user.id,
                dept_id=user_dept.dept_id,
                project_id=project.id,
                description=choice(descriptions),
                duration_minutes=randint(1, 8) * 30,  # 30分钟到4小时
                related_content=None,
                created_at=created_at,
            )
            session.add(record)
            records_count += 1

        session.commit()
        print(f"✓ 创建了 {records_count} 条工作记录")

        # 6. 创建结算周期
        periods_data = [
            {
                "dept_id": depts[0].id,
                "title": "3月工作量",
                "start": datetime(2024, 3, 1),
                "end": datetime(2024, 3, 31, 23, 59, 59),
                "is_open": False,
            },
            {
                "dept_id": depts[0].id,
                "title": "4月工作量",
                "start": datetime(2024, 4, 1),
                "end": datetime(2024, 4, 30, 23, 59, 59),
                "is_open": True,
            },
            {
                "dept_id": depts[1].id,
                "title": "Q1技术部工作量",
                "start": datetime(2024, 1, 1),
                "end": datetime(2024, 3, 31, 23, 59, 59),
                "is_open": False,
            },
        ]

        periods = []
        for data in periods_data:
            period = SettlementPeriod(
                dept_id=data["dept_id"],
                title=data["title"],
                start_date=data["start"],
                end_date=data["end"],
                is_open=data["is_open"],
            )
            session.add(period)
            periods.append(period)
        session.commit()
        print(f"✓ 创建了 {len(periods)} 个结算周期")

        # 7. 创建一些申报记录
        claims_count = 0
        for period in periods:
            # 获取部门成员
            members = session.exec(
                select(UserDeptLink).where(UserDeptLink.dept_id == period.dept_id)
            ).all()

            for member in members[:3]:  # 每个周期前3个成员申报
                # 计算系统工时
                system_minutes = (
                    session.exec(
                        select(func.sum(WorkRecord.duration_minutes))
                        .where(WorkRecord.user_id == member.user_id)
                        .where(WorkRecord.dept_id == period.dept_id)
                        .where(WorkRecord.created_at >= period.start_date)
                        .where(WorkRecord.created_at <= period.end_date)
                    ).first()
                    or 0
                )

                system_hours = system_minutes / 60

                claim = SettlementClaim(
                    period_id=period.id,
                    user_id=member.user_id,
                    paid_hours=round(system_hours * 0.8, 1),  # 80%作为工资
                    volunteer_hours=round(system_hours * 0.2, 1),  # 20%作为志愿
                    total_hours=round(system_hours, 1),
                )
                session.add(claim)
                claims_count += 1

        session.commit()
        print(f"✓ 创建了 {claims_count} 条申报记录")

        print("\n测试数据生成完成！")
        print("\n管理员账号（可用于快速登录）：")
        print("  - 张三 (13800000001) - 新媒体中心管理员")
        print("  - 王五 (13800000003) - 技术部管理员")
        print("  - 钱七 (13800000005) - 运营部管理员")


def main():
    """脚本入口"""
    # 确保表已创建
    import app.models  # noqa: F401

    create_db_and_tables()

    create_test_data()


if __name__ == "__main__":
    main()
