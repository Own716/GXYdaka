"""Photo API integration tests: in-process ASGI, mocked DB and temporary storage."""
import copy
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('DATABASE_URL', 'mysql+pymysql://test:test@127.0.0.1:1/gxy_isolated_test')

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from server import api, clockin_photos
from server.models import AppUser, User


def picture(color='blue'):
    data = io.BytesIO()
    Image.new('RGB', (48, 32), color).save(data, 'PNG')
    return data.getvalue()


class ClockInPhotoHttpTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = patch.object(clockin_photos, '_ROOT', Path(self.temp.name) / 'photos')
        self.storage.start()
        self.user = User(id=51, tenant_id='tenant-a', phone='mock-only', password='mock-only',
                         enable_clockin=False, clockIn={'imageCount': 0, 'location': {'address': 'untouched'}})
        self.app_user = AppUser(id=101, tenant_id='tenant-a', phone='mock-only', password_hash='mock',
                                enabled=True, bound_user_id=51)
        self.before = copy.deepcopy(self.user.model_dump())
        self.session = Mock()
        self.session.get.side_effect = lambda model, _id: self.app_user if model is AppUser else self.user
        self.app = FastAPI()
        self.app.include_router(api.router, prefix='/api')
        self.app.dependency_overrides[api.get_session] = lambda: self.session
        self.app.dependency_overrides[api.require_users_read] = lambda: {'tenant_id': 'tenant-a', 'sub': 'mock-admin'}
        self.app.dependency_overrides[api.require_users_write] = lambda: {'tenant_id': 'tenant-a', 'sub': 'mock-admin'}
        self.app.dependency_overrides[api.get_user] = lambda: {'tenant_id': 'tenant-a', 'sub': 'app:101'}
        # No lifespan exists on this minimal application: no scheduler/startup/real DB.
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.storage.stop()
        self.temp.cleanup()

    def test_admin_multi_upload_private_preview_delete_and_unchanged_config(self):
        base = '/api/users/51/clock-in/photos'
        response = self.client.post(base, files=[
            ('files', ('morning.png', picture('red'), 'image/png')),
            ('files', ('evening.png', picture('green'), 'image/png')),
        ])
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body['enabled'])
        self.assertEqual(len(body['photos']), 2)
        self.assertEqual(len(self.client.get(base).json()['photos']), 2)
        first = body['photos'][0]
        preview = self.client.get(first['url'])
        self.assertEqual(preview.status_code, 200)
        self.assertIn('no-store', preview.headers['cache-control'])
        self.assertEqual(preview.headers['content-type'], 'image/jpeg')
        with Image.open(io.BytesIO(preview.content)) as image:
            self.assertEqual(image.format, 'JPEG')
        deleted = self.client.delete(first['url'])
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(len(deleted.json()['photos']), 1)
        self.assertEqual(self.client.get(first['url']).status_code, 404)
        self.assertEqual(self.user.model_dump(), self.before)
        self.session.commit.assert_not_called()

    def test_app_and_admin_share_only_the_bound_users_library(self):
        app_base = '/api/app/clock-in/photos'
        response = self.client.post(app_base, files={'files': ('own.png', picture(), 'image/png')})
        self.assertEqual(response.status_code, 200, response.text)
        photo = response.json()['photos'][0]
        self.assertTrue(photo['url'].startswith(app_base + '/'))
        self.assertEqual(self.client.get(photo['url']).status_code, 200)
        self.assertEqual(len(self.client.get('/api/users/51/clock-in/photos').json()['photos']), 1)
        self.assertEqual(self.user.model_dump(), self.before)
        self.app_user.bound_user_id = None
        self.assertEqual(self.client.get(app_base).status_code, 403)

    def test_cross_tenant_reads_uploads_deletes_and_bound_identity_are_rejected(self):
        row = clockin_photos.add_photos('tenant-a', 51, [('own.png', picture())])[0]
        self.user.tenant_id = 'tenant-b'
        base = '/api/users/51/clock-in/photos'
        self.assertEqual(self.client.get(base).status_code, 404)
        self.assertEqual(self.client.get(f"{base}/{row['id']}").status_code, 404)
        self.assertEqual(self.client.delete(f"{base}/{row['id']}").status_code, 404)
        self.assertEqual(self.client.post(base, files={'files': ('blocked.png', picture(), 'image/png')}).status_code, 404)
        self.assertEqual(self.client.get('/api/app/clock-in/photos').status_code, 403)
        self.assertEqual(len(clockin_photos.list_photos('tenant-a', 51)), 1)
        self.assertEqual(clockin_photos.list_photos('tenant-b', 51), [])

    def test_invalid_image_in_batch_has_no_partial_upload_and_limits_are_bounded(self):
        base = '/api/users/51/clock-in/photos'
        response = self.client.post(base, files=[
            ('files', ('valid.png', picture(), 'image/png')),
            ('files', ('invalid.jpg', b'not a photo', 'image/jpeg')),
        ])
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.get(base).json()['photos'], [])
        response = self.client.post(base, files=[('files', (f'{n}.png', picture(), 'image/png')) for n in range(21)])
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.post(base, content=b'x', headers={'content-length': str(33 * 1024 * 1024)}).status_code, 413)
        self.assertEqual(self.client.get(base).json()['photos'], [])

    def test_unauthed_requests_do_not_reach_photo_storage(self):
        self.app.dependency_overrides.pop(api.require_users_read)
        self.app.dependency_overrides.pop(api.require_users_write)
        self.app.dependency_overrides.pop(api.get_user)
        for path in ('/api/users/51/clock-in/photos', '/api/app/clock-in/photos'):
            self.assertIn(self.client.get(path).status_code, (401, 403))
            self.assertIn(self.client.post(path, files={'files': ('private.png', picture(), 'image/png')}).status_code, (401, 403))
        self.assertFalse((Path(self.temp.name) / 'photos').exists())


if __name__ == '__main__':
    unittest.main()
