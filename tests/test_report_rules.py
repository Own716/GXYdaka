import os
import unittest
from datetime import datetime
from unittest.mock import patch

from server.report_rules import (
    report_word_count,
    report_generation_range,
    validate_report_content,
    validate_report_settings,
)


class ReportRulesTests(unittest.TestCase):
    @staticmethod
    def _load_task_runner():
        # Import builds an engine object but does not connect to this local dummy.
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "mysql+pymysql://test:test@127.0.0.1/test"},
        ):
            from server import task_runner
        return task_runner

    def test_legacy_defaults_are_one_to_one_thousand(self):
        self.assertEqual(
            validate_report_settings(None), {"minWords": 1, "maxWords": 1000}
        )
        self.assertEqual(validate_report_content("旧行为"), 3)
        self.assertEqual(validate_report_content("x" * 1000), 1000)

    def test_count_is_non_whitespace_unicode_characters(self):
        self.assertEqual(report_word_count("字 A\t\n　🙂"), 3)
        self.assertEqual(report_word_count(" \r\n\t　"), 0)

    def test_configured_range_is_inclusive_and_supports_alias(self):
        settings = {"minWords": 2, "maxWords": 3}
        self.assertEqual(validate_report_content("甲 乙", settings), 2)
        self.assertEqual(
            validate_report_content("甲乙丙", reportSettings=settings), 3
        )
        self.assertEqual(validate_report_settings(settings), settings)
        self.assertEqual(report_generation_range(settings), (2, 3))

    def test_out_of_range_content_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside the allowed range"):
            validate_report_content("甲", {"minWords": 2, "maxWords": 3})
        with self.assertRaisesRegex(ValueError, "outside the allowed range"):
            validate_report_content("甲乙丙丁", {"minWords": 2, "maxWords": 3})

    def test_invalid_ranges_and_content_types_are_rejected(self):
        for settings in (
            {"minWords": -1},
            {"minWords": 0},
            {"maxWords": 0},
            {"maxWords": 10001},
            {"minWords": 4, "maxWords": 3},
            {"minWords": True},
            [],
        ):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                validate_report_settings(settings)
        with self.assertRaises(ValueError):
            report_word_count(None)

    def test_generation_outside_range_never_calls_remote_report_submit(self):
        task_runner = self._load_task_runner()
        from server.util.Config import ConfigManager

        class FakeApi:
            submitted = False

            def get_submitted_reports_info(self, _report_type):
                return {"data": [], "flag": 0}

            def get_job_info(self):
                return {"jobId": "job"}

            def submit_report(self, _report):
                self.submitted = True

        config = ConfigManager(
            config={
                "config": {
                    "reportSettings": {
                        "weekly": {"enabled": True, "minWords": 3, "maxWords": 4}
                    }
                },
                "planInfo": {"planPaper": {"weekPaperNum": 2}},
                "userInfo": {"userId": "u", "orgJson": {"snowFlakeId": "o"}},
            }
        )
        api = FakeApi()
        with (
            patch.object(task_runner, "check_ai_generation_quota"),
            patch.object(task_runner, "generate_article", return_value="短文"),
            patch.object(task_runner, "upload_img") as upload,
        ):
            result = task_runner._submit_report_common(
                api_client=api,
                config=config,
                report_type="week",
                title_func=lambda _count: "周报",
                check_time_func=lambda _time: True,
                get_submitted_func=lambda: api.get_submitted_reports_info("week"),
                paper_num_key="planInfo.planPaper.weekPaperNum",
                image_count_key="config.reportSettings.weekly.imageCount",
                task_name="周报提交",
                form_type=8,
                force_report=True,
            )
        self.assertEqual(result["status"], "fail")
        self.assertFalse(api.submitted)
        upload.assert_not_called()

    def test_monthly_last_and_fixed_31_both_run_at_february_month_end(self):
        task_runner = self._load_task_runner()
        from server.util.Config import ConfigManager

        for submit_day in ("last", 31):
            config = ConfigManager(
                config={
                    "config": {
                        "reportSettings": {
                            "monthly": {"submitTime": submit_day, "submitAt": "12:00"}
                        }
                    }
                }
            )
            with self.subTest(submit_day=submit_day), patch.object(
                task_runner, "_submit_report_common", side_effect=lambda **kw: kw["check_time_func"](datetime(2025, 2, 28, 12, 0))
            ):
                self.assertTrue(task_runner.submit_monthly_report(config, object()))

    def test_nonreplace_clockin_skips_disallowed_schedule_dates(self):
        task_runner = self._load_task_runner()
        from server.util.Config import ConfigManager

        config = ConfigManager(
            config={
                "config": {
                    "clockIn": {
                        "schedule": {"weekdays": []},
                        "location": {"address": "test"},
                    }
                }
            }
        )

        class NoCallApi:
            def __getattr__(self, name):
                raise AssertionError(f"unexpected API call: {name}")

        result = task_runner.perform_clock_in(
            NoCallApi(), config, target_time=datetime(2025, 2, 28, 9, 0)
        )
        self.assertEqual(result["status"], "skip")
        self.assertIn("不符合打卡日期设置", result["message"])


if __name__ == "__main__":
    unittest.main()
