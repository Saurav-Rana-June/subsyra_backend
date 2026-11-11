import io
import os
import unittest
import uuid
from fastapi.testclient import TestClient

from main import app
from src.audit_logs.models import AuditLogModel
from src.users.models import (
    DeletedUserModel,
    EmailVerificationTokenModel,
    RevokedTokenModel,
    UserModel,
    UserRecoveryCodeModel,
    UserSessionModel,
)
from src.utils.db import LocalSession
from src.utils.totp import generate_current_totp


class TestProfileRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.db = LocalSession()
        suffix = uuid.uuid4().hex[:8]
        cls.primary_email = f"profile_primary_{suffix}@example.com"
        cls.updated_email = f"profile_updated_{suffix}@example.com"
        cls.other_email = f"profile_other_{suffix}@example.com"
        cls.primary_mobile = f"91{suffix[:8]}"
        cls.other_mobile = f"92{suffix[:8]}"
        cls.created_user_ids = []
        cls.uploaded_paths = []

    @classmethod
    def tearDownClass(cls):
        for path in cls.uploaded_paths:
            disk_path = path.lstrip("/")
            if os.path.exists(disk_path):
                try:
                    os.remove(disk_path)
                except OSError:
                    pass

        if cls.created_user_ids:
            cls.db.query(AuditLogModel).filter(AuditLogModel.user_id.in_(cls.created_user_ids)).delete(synchronize_session=False)
            cls.db.query(DeletedUserModel).filter(DeletedUserModel.user_id.in_(cls.created_user_ids)).delete(synchronize_session=False)
            cls.db.query(EmailVerificationTokenModel).filter(EmailVerificationTokenModel.user_id.in_(cls.created_user_ids)).delete(synchronize_session=False)
            cls.db.query(UserRecoveryCodeModel).filter(UserRecoveryCodeModel.user_id.in_(cls.created_user_ids)).delete(synchronize_session=False)
            cls.db.query(UserSessionModel).filter(UserSessionModel.user_id.in_(cls.created_user_ids)).delete(synchronize_session=False)
            cls.db.query(UserModel).filter(UserModel.id.in_(cls.created_user_ids)).delete(synchronize_session=False)
            cls.db.commit()
        cls.db.close()

    def _auth_headers(self, token: str, ua: str = "Chrome/120 Windows NT 10.0") -> dict:
        return {"Authorization": f"Bearer {token}", "User-Agent": ua}

    def test_01_register_and_get_enriched_profile(self):
        res1 = self.client.post(
            "/api/users/register",
            json={
                "full_name": "Saurav Kumar",
                "email_address": self.primary_email,
                "mobile_number": self.primary_mobile,
                "password": "Password@123",
            },
            headers={"User-Agent": "Mozilla/5.0 Chrome/120 Windows NT"},
        )
        self.assertEqual(res1.status_code, 200)
        body1 = res1.json()
        self.assertEqual(body1["status"], 201)
        self.__class__.token1 = body1["data"]["token"]
        self.__class__.primary_id = body1["data"]["user"]["id"]
        self.created_user_ids.append(self.primary_id)

        res2 = self.client.post(
            "/api/users/register",
            json={
                "full_name": "Other User",
                "email_address": self.other_email,
                "mobile_number": self.other_mobile,
                "password": "Password@123",
            },
        )
        body2 = res2.json()
        self.assertEqual(body2["status"], 201)
        self.__class__.other_token = body2["data"]["token"]
        self.__class__.other_id = body2["data"]["user"]["id"]
        self.created_user_ids.append(self.other_id)

        me_res = self.client.get("/api/users/me", headers=self._auth_headers(self.token1))
        me_data = me_res.json()["data"]
        self.assertEqual(me_data["first_name"], "Saurav")
        self.assertEqual(me_data["last_name"], "Kumar")
        self.assertEqual(me_data["country_code"], "+91")
        self.assertTrue(me_data["is_email_verified"])
        self.assertFalse(me_data["two_factor_enabled"])
        self.assertEqual(me_data["preferences"]["language"], "en-US")
        self.assertEqual(me_data["notifications"]["billing_frequency"], "weekly")

    def test_02_update_profile_validation_and_email_verification(self):
        # Reject duplicate email owned by other user
        dup_res = self.client.put(
            "/api/users/me",
            json={"email_address": self.other_email},
            headers=self._auth_headers(self.token1),
        )
        self.assertEqual(dup_res.json()["status"], 400)

        # Partial update including unified preferences/notifications and changed email
        upd_res = self.client.patch(
            "/api/users/me",
            json={
                "first_name": "Saurav",
                "last_name": "Rana",
                "display_name": "Saurav R.",
                "job_title": "Head of Finance",
                "country_code": "+1",
                "email_address": self.updated_email,
                "avatar_tone_index": 2,
                "preferences": {"theme": "dark", "timezone": "EST"},
                "notifications": {"product_updates": True, "billing_frequency": "monthly"},
            },
            headers=self._auth_headers(self.token1),
        )
        upd_body = upd_res.json()
        self.assertEqual(upd_body["status"], 200)
        data = upd_body["data"]
        self.assertEqual(data["full_name"], "Saurav Rana")
        self.assertEqual(data["job_title"], "Head of Finance")
        self.assertEqual(data["country_code"], "+1")
        self.assertEqual(data["avatar_tone_index"], 2)
        self.assertFalse(data["is_email_verified"])
        self.assertEqual(data["preferences"]["theme"], "dark")
        self.assertTrue(data["notifications"]["product_updates"])

        # Resend and confirm email verification
        resend = self.client.post(
            "/api/users/me/email-verification/resend",
            headers=self._auth_headers(self.token1),
        ).json()
        self.assertEqual(resend["status"], 200)
        v_token = resend["data"]["verification_token"]

        confirm = self.client.post(
            "/api/users/me/email-verification/confirm",
            json={"token": v_token},
            headers=self._auth_headers(self.token1),
        ).json()
        self.assertEqual(confirm["status"], 200)
        self.assertTrue(confirm["data"]["is_email_verified"])

    def test_03_avatar_upload_idor_fix_and_delete(self):
        # Reject invalid file MIME
        bad_res = self.client.post(
            "/api/users/me/profile-picture",
            files={"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")},
            headers=self._auth_headers(self.token1),
        ).json()
        self.assertEqual(bad_res["status"], 400)

        # Valid PNG upload
        png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        up_res = self.client.post(
            "/api/users/me/profile-picture",
            files={"file": ("avatar.png", io.BytesIO(png_bytes), "image/png")},
            headers=self._auth_headers(self.token1),
        ).json()
        self.assertEqual(up_res["status"], 200)
        pic_path = up_res["data"]["profile_picture"]
        self.assertIsNotNone(pic_path)
        self.uploaded_paths.append(pic_path)

        # IDOR protection: other user cannot delete primary user's avatar
        idor_res = self.client.delete(
            f"/api/users/profile_picture/{self.primary_id}",
            headers=self._auth_headers(self.other_token),
        ).json()
        self.assertEqual(idor_res["status"], 403)

        # Owner can delete via /me/profile-picture
        del_res = self.client.delete(
            "/api/users/me/profile-picture",
            headers=self._auth_headers(self.token1),
        ).json()
        self.assertEqual(del_res["status"], 200)
        self.assertIsNone(del_res["data"]["profile_picture"])
        self.assertEqual(del_res["data"]["avatar_tone_index"], 0)

    def test_04_preferences_and_notifications_routes(self):
        pref_put = self.client.put(
            "/api/users/me/preferences",
            json={"language": "hi", "date_format": "YYYY-MM-DD", "theme": "light"},
            headers=self._auth_headers(self.token1),
        ).json()
        self.assertEqual(pref_put["status"], 200)
        self.assertEqual(pref_put["data"]["language"], "hi")
        self.assertEqual(pref_put["data"]["date_format"], "YYYY-MM-DD")

        notif_put = self.client.put(
            "/api/users/me/notifications",
            json={"billing_summaries": False, "billing_frequency": "daily"},
            headers=self._auth_headers(self.token1),
        ).json()
        self.assertEqual(notif_put["status"], 200)
        self.assertFalse(notif_put["data"]["billing_summaries"])
        self.assertEqual(notif_put["data"]["billing_frequency"], "daily")

    def test_05_sessions_list_revoke_and_change_password(self):
        # Login from a second device
        login2 = self.client.post(
            "/api/users/login",
            json={"email_address": self.updated_email, "password": "Password@123"},
            headers={"User-Agent": "Subsyra iOS", "x-client-location": "Mumbai, IN"},
        ).json()
        self.assertEqual(login2["status"], 200)
        token2 = login2["data"]["token"]

        # Login from a third device
        login3 = self.client.post(
            "/api/users/login",
            json={"email_address": self.updated_email, "password": "Password@123"},
            headers={"User-Agent": "Firefox Linux"},
        ).json()
        self.assertEqual(login3["status"], 200)
        token3 = login3["data"]["token"]
        session3_id = login3["data"]["session_id"]

        sess_list = self.client.get("/api/users/me/sessions", headers=self._auth_headers(token2)).json()
        self.assertEqual(sess_list["status"], 200)
        self.assertGreaterEqual(sess_list["data"]["total"], 3)

        # Revoke session 3 from session 2
        rev3 = self.client.delete(
            f"/api/users/me/sessions/{session3_id}",
            headers=self._auth_headers(token2),
        ).json()
        self.assertEqual(rev3["status"], 200)

        # Session 3 token is now rejected
        check3 = self.client.get("/api/users/me", headers=self._auth_headers(token3)).json()
        self.assertEqual(check3["status"], 401)

        # Change password from token2 invalidates token1 while keeping token2 active
        pw_res = self.client.post(
            "/api/users/me/change-password",
            json={
                "current_password": "Password@123",
                "new_password": "NewPassword@456",
                "confirm_password": "NewPassword@456",
            },
            headers=self._auth_headers(token2),
        ).json()
        self.assertEqual(pw_res["status"], 200)
        self.__class__.token2 = token2

        old_check = self.client.get("/api/users/me", headers=self._auth_headers(self.token1)).json()
        self.assertEqual(old_check["status"], 401)
        still_ok = self.client.get("/api/users/me", headers=self._auth_headers(token2)).json()
        self.assertEqual(still_ok["status"], 200)

    def test_06_two_factor_recovery_codes_and_login_challenge(self):
        setup = self.client.post("/api/users/me/2fa/setup", headers=self._auth_headers(self.token2)).json()
        self.assertEqual(setup["status"], 200)
        secret = setup["data"]["secret"]

        # Wrong code fails
        bad_en = self.client.post(
            "/api/users/me/2fa/enable",
            json={"code": "000000"},
            headers=self._auth_headers(self.token2),
        ).json()
        self.assertEqual(bad_en["status"], 400)

        # Valid TOTP enables 2FA and returns recovery codes
        valid_code = generate_current_totp(secret)
        en_res = self.client.post(
            "/api/users/me/2fa/enable",
            json={"code": valid_code},
            headers=self._auth_headers(self.token2),
        ).json()
        self.assertEqual(en_res["status"], 200)
        self.assertTrue(en_res["data"]["two_factor_enabled"])
        initial_codes = en_res["data"]["recovery_codes"]
        self.assertEqual(len(initial_codes), 6)

        # Fetch hints
        hints = self.client.get("/api/users/me/2fa/recovery-codes", headers=self._auth_headers(self.token2)).json()
        self.assertEqual(hints["data"]["remaining_codes"], 6)

        # Regenerate invalidates initial codes
        regen = self.client.post(
            "/api/users/me/2fa/recovery-codes/regenerate",
            headers=self._auth_headers(self.token2),
        ).json()
        self.assertEqual(regen["status"], 200)
        new_codes = regen["data"]["recovery_codes"]
        self.assertEqual(len(new_codes), 6)

        # Login requires 2FA challenge
        chal = self.client.post(
            "/api/users/login",
            json={"email_address": self.updated_email, "password": "NewPassword@456"},
        ).json()
        self.assertTrue(chal["data"]["requires_2fa"])
        chal_token = chal["data"]["challenge_token"]

        # One-time recovery code succeeds
        mfa_ok = self.client.post(
            "/api/users/login/2fa",
            json={"challenge_token": chal_token, "code": new_codes[0]},
        ).json()
        self.assertEqual(mfa_ok["status"], 200)
        self.assertIn("token", mfa_ok["data"])

        # Reusing spent recovery code fails
        chal2 = self.client.post(
            "/api/users/login",
            json={"email_address": self.updated_email, "password": "NewPassword@456"},
        ).json()
        mfa_reuse = self.client.post(
            "/api/users/login/2fa",
            json={"challenge_token": chal2["data"]["challenge_token"], "code": new_codes[0]},
        ).json()
        self.assertEqual(mfa_reuse["status"], 400)

        # Disable 2FA
        dis = self.client.post(
            "/api/users/me/2fa/disable",
            json={"password": "NewPassword@456"},
            headers=self._auth_headers(self.token2),
        ).json()
        self.assertEqual(dis["status"], 200)
        self.assertFalse(dis["data"]["two_factor_enabled"])

    def test_07_export_personal_data_and_delete_account(self):
        exp = self.client.get("/api/users/me/export", headers=self._auth_headers(self.token2)).json()
        self.assertEqual(exp["status"], 200)
        self.assertIn("profile", exp["data"])
        self.assertIn("login_history", exp["data"])

        dl = self.client.get("/api/users/me/export?download=true", headers=self._auth_headers(self.token2))
        self.assertEqual(dl.status_code, 200)
        self.assertIn("attachment; filename=", dl.headers.get("content-disposition", ""))

        # Wrong password rejected
        bad_del = self.client.request(
            "DELETE",
            "/api/users/me",
            json={"password": "WrongPassword"},
            headers=self._auth_headers(self.token2),
        ).json()
        self.assertEqual(bad_del["status"], 400)

        # Valid password permanently deactivates account & revokes token
        ok_del = self.client.request(
            "DELETE",
            "/api/users/me",
            json={"password": "NewPassword@456"},
            headers=self._auth_headers(self.token2),
        ).json()
        self.assertEqual(ok_del["status"], 200)

        post_del_me = self.client.get("/api/users/me", headers=self._auth_headers(self.token2)).json()
        self.assertEqual(post_del_me["status"], 401)
        post_del_login = self.client.post(
            "/api/users/login",
            json={"email_address": self.updated_email, "password": "NewPassword@456"},
        ).json()
        self.assertEqual(post_del_login["status"], 400)

