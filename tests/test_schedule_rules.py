import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from server.schedule_rules import (
    clockin_date_allowed,
    preview_clockin_dates,
    validate_clockin_schedule,
)


class ClockinScheduleRulesTest(unittest.TestCase):
    def test_validation_normalizes_weekdays_and_defaults(self):
        self.assertEqual(
            validate_clockin_schedule({"schedule": {"weekdays": [1, 3, 1]}})["weekdays"],
            (1, 3),
        )
        self.assertEqual(validate_clockin_schedule({})["weekdays"], (1, 2, 3, 4, 5, 6, 7))
        self.assertEqual(validate_clockin_schedule({"customDays": [2]})["weekdays"], (2,))

    def test_invalid_schedule_fields_raise_value_error(self):
        invalid_configs = [
            {"schedule": {"startDate": "2025-02-30"}},
            {"schedule": {"endDate": "2025-01-01", "startDate": "2025-01-02"}},
            {"schedule": {"totalDays": 0}},
            {"schedule": {"totalDays": 3651}},
            {"schedule": {"totalDays": True}},
            {"schedule": {"weekdays": [0]}},
            {"schedule": {"weekdays": ["1"]}},
            {"schedule": {"skipHolidays": "true"}},
            {"schedule": {"startTime": "24:00"}},
            {"schedule": {"endTime": "8:00"}},
        ]
        for config in invalid_configs:
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_clockin_schedule(config)

    def test_empty_date_strings_are_unset(self):
        rules = validate_clockin_schedule({"schedule": {"startDate": "", "endDate": ""}})
        self.assertIsNone(rules["startDate"])
        self.assertIsNone(rules["endDate"])

    def test_date_ranges_are_inclusive_and_total_days_is_calendar_based(self):
        config = {
            "schedule": {
                "startDate": "2025-03-10",
                "endDate": "2025-03-20",
                "totalDays": 3,
                "weekdays": [1, 2, 3, 4, 5, 6, 7],
            }
        }
        self.assertFalse(clockin_date_allowed(config, datetime.date(2025, 3, 9)))
        self.assertTrue(clockin_date_allowed(config, "2025-03-10"))
        self.assertTrue(clockin_date_allowed(config, "2025-03-12"))
        self.assertFalse(clockin_date_allowed(config, "2025-03-13"))
        self.assertFalse(clockin_date_allowed(config, "2025-03-21"))

    def test_weekdays_and_skip_holidays_use_injected_calendar(self):
        weekdays = {"schedule": {"weekdays": [1, 3, 5]}}
        self.assertTrue(clockin_date_allowed(weekdays, "2025-03-10"))
        self.assertFalse(clockin_date_allowed(weekdays, "2025-03-11"))
        skip_holidays = {"schedule": {"skipHolidays": True}}
        called = []

        def calendar(day):
            called.append(day)
            return day.date().isoformat() == "2025-03-10"

        # Saturday makeup work is allowed when the calendar marks it as work.
        self.assertTrue(clockin_date_allowed(skip_holidays, "2025-03-15", holiday_checker=calendar))
        self.assertFalse(clockin_date_allowed(skip_holidays, "2025-03-10", holiday_checker=calendar))
        self.assertEqual([day.date().isoformat() for day in called], ["2025-03-15", "2025-03-10"])

    def test_legacy_holiday_mode_and_explicit_override(self):
        holiday = lambda day: True
        self.assertFalse(clockin_date_allowed({"mode": "holiday"}, "2026-10-01", holiday_checker=holiday))
        self.assertTrue(clockin_date_allowed({"mode": "holiday", "specialClockIn": True}, "2026-10-01", holiday_checker=holiday))
        self.assertTrue(clockin_date_allowed({"mode": "holiday", "schedule": {"skipHolidays": False}}, "2026-10-01", holiday_checker=holiday))

    def test_preview_returns_next_allowed_dates_and_stops_at_end_date(self):
        config = {
            "schedule": {
                "startDate": "2025-03-10",
                "endDate": "2025-03-14",
                "weekdays": [1, 3, 5],
            }
        }
        self.assertEqual(
            preview_clockin_dates(config, from_date="2025-03-09", limit=5),
            ["2025-03-10", "2025-03-12", "2025-03-14"],
        )
        self.assertEqual(preview_clockin_dates(config, from_date="2025-03-15"), [])
        self.assertEqual(preview_clockin_dates(config, from_date="2025-03-10", limit=0), [])

    def test_preview_jumps_to_future_start_and_caps_limit(self):
        config = {"schedule": {"startDate": "2040-01-01", "weekdays": [1, 2, 3, 4, 5, 6, 7]}}
        self.assertEqual(
            preview_clockin_dates(config, from_date="2025-01-01", limit=1),
            ["2040-01-01"],
        )
        self.assertEqual(len(preview_clockin_dates(config, from_date="2040-01-01", limit=31)), 31)
        with self.assertRaises(ValueError):
            preview_clockin_dates(config, from_date="2040-01-01", limit=32)

    def test_preview_stops_after_maximum_scan_range(self):
        config = {"schedule": {"skipHolidays": True, "weekdays": [1, 2, 3, 4, 5, 6, 7]}}
        checked = []
        results = preview_clockin_dates(
            config,
            from_date="2025-01-01",
            limit=1,
            holiday_checker=lambda day: checked.append(day) or True,
        )
        self.assertEqual(results, [])
        self.assertEqual(len(checked), 3660)

    def test_preview_is_side_effect_free(self):
        config = {"schedule": {"weekdays": [1], "startDate": "2025-03-10"}}
        before = {"schedule": dict(config["schedule"])}
        preview_clockin_dates(config, from_date="2025-03-10", limit=2)
        self.assertEqual(config, before)

    def test_empty_clockin_weekdays_do_not_prevent_report_registration(self):
        from server.scheduler import add_user_job

        user = SimpleNamespace(
            id=42,
            enable_clockin=False,
            clockIn={"schedule": {"weekdays": []}},
            reportSettings={"monthly": {"enabled": True, "submitTime": "last"}},
        )
        with patch("server.scheduler.scheduler.add_job") as add_job:
            add_user_job(user)
        self.assertEqual(add_job.call_count, 1)
        trigger = add_job.call_args.args[1]
        from server.scheduler import scheduler
        self.assertEqual(str(trigger.timezone), str(scheduler.timezone))
        day_field = next(field for field in trigger.fields if field.name == "day")
        self.assertEqual(str(day_field.expressions[0]), "last")

    def test_out_of_range_scheduler_run_does_not_disable_clockin(self):
        from sqlmodel import Session, SQLModel, create_engine
        from server.models import User
        from server.scheduler import run_job

        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            user = User(
                phone="13900000001",
                password="encrypted",
                enable_clockin=True,
                clockIn={"schedule": {"startDate": "2020-01-01", "endDate": "2020-01-02"}},
            )
            session.add(user)
            session.commit()
            user_id = user.id

        with (
            patch("server.scheduler.engine", engine),
            patch("server.scheduler.run_task_by_config") as run_task,
        ):
            run_job(user_id, "START")

        run_task.assert_not_called()
        with Session(engine) as session:
            self.assertTrue(session.get(User, user_id).enable_clockin)

    def test_future_start_date_does_not_expire_total_days_early(self):
        from sqlmodel import Session, SQLModel, create_engine
        from server.models import User
        from server.scheduler import run_job

        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        today = datetime.datetime.now().date()
        future = today + datetime.timedelta(days=30)
        with Session(engine) as session:
            user = User(
                phone="13900000002",
                password="encrypted",
                enable_clockin=True,
                clockIn={"schedule": {"startDate": future.isoformat(), "totalDays": 1}},
            )
            session.add(user)
            session.commit()
            user_id = user.id

        with (
            patch("server.scheduler.engine", engine),
            patch("server.scheduler.run_task_by_config") as run_task,
        ):
            run_job(user_id, "START")

        run_task.assert_not_called()
        with Session(engine) as session:
            self.assertTrue(session.get(User, user_id).enable_clockin)

    def test_scheduler_and_preview_share_single_holiday_calendar_check(self):
        from sqlmodel import Session, SQLModel, create_engine
        from server.models import User
        from server.scheduler import run_job

        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            user = User(
                phone="13900000003",
                password="encrypted",
                enable_clockin=True,
                clockIn={"schedule": {"skipHolidays": True}},
            )
            session.add(user)
            session.commit()
            user_id = user.id

        with (
            patch("server.scheduler.engine", engine),
            patch("server.util.HelperFunctions.is_holiday", return_value=True) as calendar,
            patch("server.scheduler.run_task_by_config") as run_task,
        ):
            run_job(user_id, "START")

        run_task.assert_not_called()
        self.assertEqual(calendar.call_count, 1)


if __name__ == "__main__":
    unittest.main()
