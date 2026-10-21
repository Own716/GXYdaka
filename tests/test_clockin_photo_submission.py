"""Offline regressions for school-required photos and truthful clock-in results."""
import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('DATABASE_URL', 'mysql+pymysql://test:test@127.0.0.1:1/gxy_isolated_test')

from server import task_runner
from server.coreApi.MainLogicApi import ApiClient
from server.util.Config import ConfigManager

SCHOOL_ERROR = '学校设置必须上传图片'
ATTACHMENT = 'org-3/2026-10-21/report/remote-7_123456.jpg'


def config(enabled=True):
    return ConfigManager(config={
        'tenant_id': 'tenant-a', 'user_id': 51,
        'config': {
            'device': 'test-device',
            'clockIn': {'photoEnabled': enabled, 'imageCount': 0, 'mode': 'none',
                        'location': {'address': 'mock address', 'latitude': '30.1', 'longitude': '120.1'}},
        },
        'planInfo': {'planId': 'test-plan'},
        'userInfo': {'nikeName': 'mock', 'userType': 'student', 'userId': 'remote-7',
                     'roleKey': 'student', 'token': 'mock-token', 'orgJson': {'snowFlakeId': 'org-3'}},
    })


def api_client(cfg, response):
    client = ApiClient.__new__(ApiClient)
    client.config = cfg
    client._post_request = Mock(return_value=response)
    client.get_checkin_records = Mock(return_value=[])
    client.get_upload_token = Mock(return_value='mock-upload-token')
    return client


class ClockInPhotoSubmissionTest(unittest.TestCase):
    def test_uploaded_object_key_reaches_real_submit_payload_unchanged(self):
        for replace in (False, True):
            with self.subTest(replace=replace):
                cfg = config()
                # Even stale location metadata must not erase a newly uploaded photo.
                cfg.config['config']['clockIn']['location']['attachments'] = None
                client = api_client(cfg, {'code': 200, 'msg': 'success'})
                with patch.object(task_runner, 'choose_photo_bytes', return_value=b'normalized-jpeg'), patch.object(task_runner, 'upload_image_bytes', return_value=ATTACHMENT) as upload:
                    result = task_runner.perform_clock_in(client, cfg, replace=replace, target_time=datetime(2026, 10, 21, 8, 0))
                self.assertEqual(result['status'], 'success')
                upload.assert_called_once_with('mock-upload-token', 'org-3', 'remote-7', [b'normalized-jpeg'])
                path, _headers, payload = client._post_request.call_args.args
                self.assertEqual(payload['attachments'], ATTACHMENT)
                self.assertIsInstance(payload['attachments'], str)
                self.assertNotIn(',', payload['attachments'])
                self.assertEqual(path, 'attendence/attendanceReplace/v6/save' if replace else 'attendence/clock/v6/save')

    def test_school_error_never_counts_as_success_even_with_business_code_200(self):
        for code in (200, 500, 6111):
            with self.subTest(code=code):
                cfg = config(False)
                client = api_client(cfg, {'code': code, 'msg': SCHOOL_ERROR})
                with patch.object(task_runner, 'upload_img', return_value=''):
                    result = task_runner.perform_clock_in(client, cfg, target_time=datetime(2026, 10, 21, 8, 0))
                self.assertEqual(result['status'], 'fail')
                self.assertIn(SCHOOL_ERROR, result['message'])
                self.assertIn('开启“随机提交”并保存', result['details']['建议'])

    def test_unknown_success_message_and_non_success_adapter_result_fail_closed(self):
        cfg = config()
        client = api_client(cfg, {'code': 200, 'msg': '学校拒绝了这次提交'})
        with self.assertRaisesRegex(ValueError, '学校拒绝'):
            client.submit_clock_in({'type': 'START', 'attachments': ATTACHMENT})
        for response in (None, {}, {'status': 'fail', 'message': SCHOOL_ERROR}, {'status': 'pending'}):
            with self.subTest(response=response):
                mocked = Mock()
                mocked.get_checkin_records.return_value = []
                mocked.submit_clock_in.return_value = response
                with patch.object(task_runner, 'upload_img', return_value=''):
                    result = task_runner.perform_clock_in(mocked, config(False), target_time=datetime(2026, 10, 21, 8, 0))
                self.assertEqual(result['status'], 'fail')

    def test_preauthorization_retry_cannot_turn_photo_failure_into_success(self):
        mocked = Mock()
        mocked.get_checkin_records.return_value = []
        mocked.submit_clock_in.side_effect = [{'status': 'verification_required'}, {'status': 'fail', 'message': SCHOOL_ERROR}]
        hooks = Mock()
        hooks.claim.return_value = SimpleNamespace(id=7, out_register_no='mock-verified')
        with patch.object(task_runner, 'upload_img', return_value=''):
            result = task_runner.perform_clock_in(mocked, config(False), target_time=datetime(2026, 10, 21, 8, 0), preauthorization_hooks=hooks)
        self.assertEqual(result['status'], 'fail')
        self.assertIn(SCHOOL_ERROR, result['message'])
        self.assertEqual(mocked.submit_clock_in.call_count, 2)

    def test_malformed_or_empty_upload_result_never_submits(self):
        for attachment in ('', ' ', [], {}, 'one.jpg,two.jpg'):
            with self.subTest(attachment=attachment):
                client = Mock()
                client.get_checkin_records.return_value = []
                with patch.object(task_runner, 'choose_photo_bytes', return_value=b'one-jpeg'), patch.object(task_runner, 'upload_image_bytes', return_value=attachment):
                    result = task_runner.perform_clock_in(client, config(), target_time=datetime(2026, 10, 21, 8, 0))
                self.assertEqual(result['status'], 'fail')
                self.assertIn('未提交打卡', result['message'])
                client.submit_clock_in.assert_not_called()


if __name__ == '__main__':
    unittest.main()
