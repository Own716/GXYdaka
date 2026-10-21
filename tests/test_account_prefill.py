import unittest

from server.account_prefill import build_profile, job_location


class BuildProfileTests(unittest.TestCase):
    def test_reads_platform_fields_and_only_returns_string_allowlist(self):
        result = build_profile(
            {
                "nikeName": "  李同学 ",
                "orgJson": {"orgName": "示例大学", "schoolId": "secret"},
                "token": "do-not-copy",
                "password": "do-not-copy",
                "idCard": "do-not-copy",
            },
            {"planName": "2026 实习计划", "token": "secret"},
            {
                "jobAddress": "岗位地址",
                "practiceCompanyEntity": {
                    "companyName": "示例公司",
                    "address": "企业地址",
                    "companyId": "secret",
                },
                "authorization": "secret",
            },
        )
        self.assertEqual(result, {
            "name": "李同学",
            "schoolName": "示例大学",
            "companyName": "示例公司",
            "companyAddress": "企业地址",
            "jobAddress": "岗位地址",
            "planName": "2026 实习计划",
        })
        self.assertEqual(set(result), {
            "name", "schoolName", "companyName", "companyAddress", "jobAddress", "planName",
        })
        self.assertTrue(all(isinstance(value, str) for value in result.values()))

    def test_supports_name_and_school_fallbacks_without_stringifying_objects(self):
        result = build_profile(
            {"nickName": {"unexpected": "object"}, "name": "备用名", "schoolName": "备用学校"},
            {"planName": {"nested": "must not leak"}},
            {"address": {"private": "object"}, "practiceCompanyEntity": {"companyName": ["not text"]}},
        )
        self.assertEqual(result["name"], "备用名")
        self.assertEqual(result["schoolName"], "备用学校")
        self.assertEqual(result["jobAddress"], "")
        self.assertEqual(result["companyName"], "")
        self.assertEqual(result["planName"], "")
        self.assertNotIn("object", repr(result))

    def test_non_object_inputs_return_empty_string_profile(self):
        self.assertEqual(build_profile(None, [], "not-an-object"), {
            "name": "", "schoolName": "", "companyName": "",
            "companyAddress": "", "jobAddress": "", "planName": "",
        })


class JobLocationTests(unittest.TestCase):
    def test_explicit_nested_location_is_preferred(self):
        result = job_location({
            "workLocation": {"lat": "31.2", "lng": "121.5", "address": "明确上班点"},
            "latitude": 32,
            "longitude": 122,
            "jobAddress": "岗位地址",
        })
        self.assertEqual(result["address"], "明确上班点")
        self.assertEqual(result["latitude"], 31.2)
        self.assertEqual(result["longitude"], 121.5)
        self.assertEqual(result["source"], "实习岗位位置")

    def test_invalid_coordinates_do_not_become_zero_and_address_can_be_shown(self):
        result = job_location({
            "latitude": "not-a-coordinate",
            "longitude": 200,
            "jobAddress": "岗位地址",
            "practiceCompanyEntity": {
                "latitude": 31,
                "longitude": 121,
                "companyAddress": "另一个企业地址",
            },
        })
        self.assertEqual(result["address"], "岗位地址")
        self.assertIsNone(result["latitude"])
        self.assertIsNone(result["longitude"])
        self.assertEqual(result["source"], "实习岗位位置")

    def test_enterprise_location_not_used_for_conflicting_job_address(self):
        result = job_location({
            "jobAddress": "分公司岗位地址",
            "practiceCompanyEntity": {
                "latitude": 31.2,
                "longitude": 121.5,
                "companyAddress": "企业总部地址",
            },
        })
        self.assertEqual(result["address"], "分公司岗位地址")
        self.assertIsNone(result["latitude"])
        self.assertIsNone(result["longitude"])

    def test_enterprise_location_allowed_when_addresses_match_or_job_address_missing(self):
        matching = job_location({
            "jobAddress": "企业地址",
            "practiceCompanyEntity": {
                "latitude": 31.2,
                "longitude": 121.5,
                "address": "企业地址",
            },
        })
        self.assertEqual(matching["source"], "实习企业位置")
        self.assertEqual(matching["latitude"], 31.2)

        missing_job_address = job_location({
            "practiceCompanyEntity": {
                "latitude": 31.2,
                "longitude": 121.5,
                "companyAddress": "企业地址",
            },
        })
        self.assertEqual(missing_job_address["source"], "实习企业位置")
        self.assertEqual(missing_job_address["address"], "企业地址")

    def test_incomplete_nested_location_does_not_hide_real_job_coordinates(self):
        result = job_location({
            "workLocation": {"address": "旧地址候选"},
            "jobAddress": "完整岗位地址", "latitude": 31.2, "longitude": 121.5,
            "province": "上海市", "city": "上海市", "district": "浦东新区",
        })
        self.assertEqual(result["address"], "完整岗位地址")
        self.assertEqual(result["latitude"], 31.2)
        self.assertEqual(result["province"], "上海市")
        self.assertEqual(result["area"], "浦东新区")

    def test_nested_coordinates_use_remote_job_address_and_no_object_regions(self):
        result = job_location({
            "workLocation": {"latitude": 31, "longitude": 121, "province": {"token": "secret"}},
            "jobAddress": "岗位详细地址",
        })
        self.assertEqual(result["address"], "岗位详细地址")
        self.assertEqual(result["province"], "")
        self.assertNotIn("secret", str(result))

    def test_empty_address_without_valid_location_and_non_object(self):
        self.assertIsNone(job_location({
            "jobAddress": "  ",
            "latitude": 95,
            "longitude": 181,
            "practiceCompanyEntity": {},
        }))
        self.assertIsNone(job_location({"latitude": 31, "longitude": 121}))
        self.assertIsNone(job_location(None))
        self.assertIsNone(job_location("not-an-object"))


if __name__ == "__main__":
    unittest.main()
