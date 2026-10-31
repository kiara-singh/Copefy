import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

TEST_USER_ID = "11111111-2222-3333-4444-555555555555"
OTHER_USER_ID = "99999999-8888-7777-6666-555555555555"
SESSION_ID = "aaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class TestAuthEndpoints(unittest.TestCase):
    def test_unauthenticated_request_fails(self):
        """Endpoints should reject requests missing the Authorization Bearer header."""
        res_session = client.post("/session", json={})
        self.assertIn(res_session.status_code, (401, 403))

        res_chat = client.post("/chat", json={"session_id": SESSION_ID, "message": "hello"})
        self.assertIn(res_chat.status_code, (401, 403))

        res_journal = client.post("/journal", json={"text": "my journal entry"})
        self.assertIn(res_journal.status_code, (401, 403))

    @patch("main.get_supabase")
    def test_invalid_token_fails(self, mock_get_supabase):
        """Endpoints should reject invalid or expired tokens with 401 Unauthorized."""
        mock_supabase = MagicMock()
        mock_supabase.auth.get_user.side_effect = Exception("Invalid token")
        mock_get_supabase.return_value = mock_supabase

        headers = {"Authorization": "Bearer invalid_token"}
        res = client.post("/session", json={}, headers=headers)
        self.assertEqual(res.status_code, 401)

    @patch("main.get_supabase")
    def test_create_session_authenticated(self, mock_get_supabase):
        """Authenticated user creates session stored under their user_id."""
        mock_supabase = MagicMock()
        mock_user = MagicMock()
        mock_user.id = TEST_USER_ID
        mock_user_res = MagicMock()
        mock_user_res.user = mock_user
        mock_supabase.auth.get_user.return_value = mock_user_res
        mock_get_supabase.return_value = mock_supabase

        headers = {"Authorization": "Bearer valid_token"}
        res = client.post("/session", json={}, headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("session_id", data)

        # Verify database table insert was called with TEST_USER_ID
        mock_supabase.table.assert_called_with("sessions")
        mock_supabase.table("sessions").insert.assert_called_once()
        inserted_data = mock_supabase.table("sessions").insert.call_args[0][0]
        self.assertEqual(inserted_data["user_id"], TEST_USER_ID)

    @patch("main.get_supabase")
    def test_chat_unowned_session_is_not_disclosed(self, mock_get_supabase):
        """An unowned session is reported like a missing chat to prevent enumeration."""
        mock_supabase = MagicMock()
        mock_user = MagicMock()
        mock_user.id = TEST_USER_ID
        mock_user_res = MagicMock()
        mock_user_res.user = mock_user
        mock_supabase.auth.get_user.return_value = mock_user_res

        # Mock session ownership check returning OTHER_USER_ID
        mock_select = MagicMock()
        mock_select.maybe_single.return_value.execute.return_value = MagicMock(
            data={"user_id": OTHER_USER_ID}
        )
        mock_supabase.table("sessions").select.return_value.eq.return_value = mock_select

        mock_get_supabase.return_value = mock_supabase

        headers = {"Authorization": "Bearer valid_token"}
        res = client.post(
            "/chat",
            json={"session_id": SESSION_ID, "message": "hello"},
            headers=headers,
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["detail"], "Chat not found.")

    @patch("main.run_agent")
    @patch("main.get_supabase")
    def test_chat_owned_session_success(self, mock_get_supabase, mock_run_agent):
        """Sending a message to an owned session succeeds and records messages."""
        from agent.types import AgentResult

        mock_run_agent.return_value = AgentResult(
            response="Hello! How can I help you?",
            path="direct_answer",
            router="rule",
            route_reason="conversational",
        )

        mock_supabase = MagicMock()
        mock_user = MagicMock()
        mock_user.id = TEST_USER_ID
        mock_user_res = MagicMock()
        mock_user_res.user = mock_user
        mock_supabase.auth.get_user.return_value = mock_user_res

        # Mock session ownership check returning TEST_USER_ID
        mock_select = MagicMock()
        mock_select.maybe_single.return_value.execute.return_value = MagicMock(
            data={"user_id": TEST_USER_ID}
        )
        mock_supabase.table("sessions").select.return_value.eq.return_value = mock_select

        mock_get_supabase.return_value = mock_supabase

        headers = {"Authorization": "Bearer valid_token"}
        res = client.post(
            "/chat",
            json={"session_id": SESSION_ID, "message": "hello world"},
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("response", res.json())

    @patch("main.get_supabase")
    def test_journal_authenticated_success(self, mock_get_supabase):
        """Submitting a journal entry stores content under the authenticated user's ID."""
        mock_supabase = MagicMock()
        mock_user = MagicMock()
        mock_user.id = TEST_USER_ID
        mock_user_res = MagicMock()
        mock_user_res.user = mock_user
        mock_supabase.auth.get_user.return_value = mock_user_res
        mock_get_supabase.return_value = mock_supabase

        headers = {"Authorization": "Bearer valid_token"}
        res = client.post("/journal", json={"text": "feeling great"}, headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "success")

        mock_supabase.table.assert_called_with("journal_entries")
        inserted_data = mock_supabase.table("journal_entries").insert.call_args[0][0]
        self.assertEqual(inserted_data["user_id"], TEST_USER_ID)
        self.assertEqual(inserted_data["content"], "feeling great")

    def test_unauthenticated_persona_api_fails(self):
        """Persona API endpoints should reject unauthenticated requests."""
        res_get = client.get("/personas")
        self.assertIn(res_get.status_code, (401, 403))

        res_post = client.post(
            "/personas",
            json={
                "name": "Test",
                "role_type": "Mentor",
                "base_personality": "Calm",
                "custom_instructions": "",
            },
        )
        self.assertIn(res_post.status_code, (401, 403))

        res_put = client.put(
            "/personas/some-id",
            json={
                "name": "Test",
                "role_type": "Mentor",
                "base_personality": "Calm",
                "custom_instructions": "",
            },
        )
        self.assertIn(res_put.status_code, (401, 403))

        res_delete = client.delete("/personas/some-id")
        self.assertIn(res_delete.status_code, (401, 403))

    @patch("main.get_supabase")
    def test_create_persona_authenticated(self, mock_get_supabase):
        """Authenticated user creates persona stored under their user_id."""
        mock_supabase = MagicMock()
        mock_user = MagicMock()
        mock_user.id = TEST_USER_ID
        mock_user_res = MagicMock()
        mock_user_res.user = mock_user
        mock_supabase.auth.get_user.return_value = mock_user_res

        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock(
            data=[
                {
                    "id": "persona-123",
                    "user_id": TEST_USER_ID,
                    "name": "Mentor Max",
                    "role_type": "Mentor",
                    "base_personality": "Calm, Reflective",
                    "custom_instructions": "Guide me patiently",
                }
            ]
        )
        mock_supabase.table("ai_personas").insert.return_value = mock_insert
        mock_get_supabase.return_value = mock_supabase

        headers = {"Authorization": "Bearer valid_token"}
        payload = {
            "name": "Mentor Max",
            "role_type": "Mentor",
            "base_personality": "Calm, Reflective",
            "custom_instructions": "Guide me patiently",
        }
        res = client.post("/personas", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["name"], "Mentor Max")

        inserted_data = mock_supabase.table("ai_personas").insert.call_args[0][0]
        self.assertEqual(inserted_data["user_id"], TEST_USER_ID)
        self.assertEqual(inserted_data["name"], "Mentor Max")

    @patch("main.get_supabase")
    def test_update_unowned_persona_forbidden(self, mock_get_supabase):
        """Updating a persona owned by another user returns 403 Forbidden."""
        mock_supabase = MagicMock()
        mock_user = MagicMock()
        mock_user.id = TEST_USER_ID
        mock_user_res = MagicMock()
        mock_user_res.user = mock_user
        mock_supabase.auth.get_user.return_value = mock_user_res

        # Ownership check returns OTHER_USER_ID
        mock_select = MagicMock()
        mock_select.execute.return_value = MagicMock(data=[{"user_id": OTHER_USER_ID}])
        mock_supabase.table("ai_personas").select.return_value.eq.return_value = mock_select
        mock_get_supabase.return_value = mock_supabase

        headers = {"Authorization": "Bearer valid_token"}
        payload = {
            "name": "Hacked Persona",
            "role_type": "Other",
            "base_personality": "Evil",
            "custom_instructions": "",
        }
        res = client.put("/personas/persona-123", json=payload, headers=headers)
        self.assertEqual(res.status_code, 403)

    @patch("main.get_supabase")
    def test_delete_unowned_persona_forbidden(self, mock_get_supabase):
        """Deleting a persona owned by another user returns 403 Forbidden."""
        mock_supabase = MagicMock()
        mock_user = MagicMock()
        mock_user.id = TEST_USER_ID
        mock_user_res = MagicMock()
        mock_user_res.user = mock_user
        mock_supabase.auth.get_user.return_value = mock_user_res

        # Ownership check returns OTHER_USER_ID
        mock_select = MagicMock()
        mock_select.execute.return_value = MagicMock(data=[{"user_id": OTHER_USER_ID}])
        mock_supabase.table("ai_personas").select.return_value.eq.return_value = mock_select
        mock_get_supabase.return_value = mock_supabase

        headers = {"Authorization": "Bearer valid_token"}
        res = client.delete("/personas/persona-123", headers=headers)
        self.assertEqual(res.status_code, 403)

    def test_unauthenticated_medical_docs_fails(self):
        """Medical documents endpoints should reject unauthenticated requests."""
        res_get = client.get("/medical-documents")
        self.assertIn(res_get.status_code, (401, 403))

        res_post = client.post(
            "/medical-documents",
            files={"file": ("doc.pdf", b"%PDF-1.5 test", "application/pdf")},
        )
        self.assertIn(res_post.status_code, (401, 403))

        res_delete = client.delete("/medical-documents/some-id")
        self.assertIn(res_delete.status_code, (401, 403))

    @patch("main.get_supabase")
    def test_upload_non_pdf_fails(self, mock_get_supabase):
        """Uploading a non-PDF file returns 400 Bad Request."""
        mock_supabase = MagicMock()
        mock_user = MagicMock()
        mock_user.id = TEST_USER_ID
        mock_user_res = MagicMock()
        mock_user_res.user = mock_user
        mock_supabase.auth.get_user.return_value = mock_user_res
        mock_get_supabase.return_value = mock_supabase

        headers = {"Authorization": "Bearer valid_token"}
        res = client.post(
            "/medical-documents",
            files={"file": ("notes.txt", b"Hello world", "text/plain")},
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Only PDF documents", res.json()["detail"])

    @patch("main.get_supabase")
    def test_upload_invalid_magic_header_fails(self, mock_get_supabase):
        """Uploading a file named .pdf without valid %PDF- header returns 400 Bad Request."""
        mock_supabase = MagicMock()
        mock_user = MagicMock()
        mock_user.id = TEST_USER_ID
        mock_user_res = MagicMock()
        mock_user_res.user = mock_user
        mock_supabase.auth.get_user.return_value = mock_user_res
        mock_get_supabase.return_value = mock_supabase

        headers = {"Authorization": "Bearer valid_token"}
        res = client.post(
            "/medical-documents",
            files={"file": ("fake.pdf", b"INVALID HEADER", "application/pdf")},
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("valid PDF header", res.json()["detail"])

    @patch("main.get_supabase")
    def test_upload_and_delete_medical_doc_success(self, mock_get_supabase):
        """Authenticated user uploads valid PDF, inserts metadata, and deletes document."""
        mock_supabase = MagicMock()
        mock_user = MagicMock()
        mock_user.id = TEST_USER_ID
        mock_user_res = MagicMock()
        mock_user_res.user = mock_user
        mock_supabase.auth.get_user.return_value = mock_user_res

        # Mock DB insert result
        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock(
            data=[
                {
                    "id": "doc-123",
                    "user_id": TEST_USER_ID,
                    "file_name": "lab_results.pdf",
                    "storage_url": f"{TEST_USER_ID}/lab_results.pdf",
                    "uploaded_at": "2026-08-10T10:00:00Z",
                }
            ]
        )
        mock_supabase.table("medical_documents").insert.return_value = mock_insert

        # Mock ownership select query for delete
        mock_select = MagicMock()
        mock_select.execute.return_value = MagicMock(
            data=[
                {
                    "id": "doc-123",
                    "user_id": TEST_USER_ID,
                    "storage_url": f"{TEST_USER_ID}/lab_results.pdf",
                }
            ]
        )
        mock_supabase.table("medical_documents").select.return_value.eq.return_value = mock_select
        mock_get_supabase.return_value = mock_supabase

        headers = {"Authorization": "Bearer valid_token"}
        valid_pdf_bytes = b"%PDF-1.4 sample content"
        res = client.post(
            "/medical-documents",
            files={"file": ("lab_results.pdf", valid_pdf_bytes, "application/pdf")},
            headers=headers,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["file_name"], "lab_results.pdf")

        # Verify deletion
        res_delete = client.delete("/medical-documents/doc-123", headers=headers)
        self.assertEqual(res_delete.status_code, 200)
        self.assertEqual(res_delete.json()["status"], "success")

    @patch("main.get_supabase")
    def test_delete_unowned_medical_doc_forbidden(self, mock_get_supabase):
        """Deleting a medical document owned by another user returns 403 Forbidden."""
        mock_supabase = MagicMock()
        mock_user = MagicMock()
        mock_user.id = TEST_USER_ID
        mock_user_res = MagicMock()
        mock_user_res.user = mock_user
        mock_supabase.auth.get_user.return_value = mock_user_res

        # Ownership check returns OTHER_USER_ID
        mock_select = MagicMock()
        mock_select.execute.return_value = MagicMock(
            data=[
                {
                    "id": "doc-123",
                    "user_id": OTHER_USER_ID,
                    "storage_url": f"{OTHER_USER_ID}/lab_results.pdf",
                }
            ]
        )
        mock_supabase.table("medical_documents").select.return_value.eq.return_value = mock_select
        mock_get_supabase.return_value = mock_supabase

        headers = {"Authorization": "Bearer valid_token"}
        res = client.delete("/medical-documents/doc-123", headers=headers)
        self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    unittest.main()


