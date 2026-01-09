
import unittest
import sys
import os
import requests

# Add src to path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from unittest.mock import MagicMock, patch
from infrastructure_atlas.interfaces.api.routes.jira import (
    get_remote_links,
    create_confluence_remotelink,
    delete_remote_link,
    ConfluenceRemoteLinkReq
)
from fastapi import HTTPException

class TestJiraRemoteLinks(unittest.TestCase):
    
    @patch("infrastructure_atlas.interfaces.api.routes.jira._jira_session")
    @patch("infrastructure_atlas.interfaces.api.routes.jira.require_jira_enabled")
    def test_get_remote_links_success(self, mock_require, mock_session_factory):
        mock_sess = MagicMock()
        mock_session_factory.return_value = (mock_sess, "https://jira.example.com")
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": 123, "object": {"title": "Test Link"}}]
        mock_sess.get.return_value = mock_response
        
        result = get_remote_links("TEST-123")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 123)
        mock_sess.get.assert_called_with("https://jira.example.com/rest/api/3/issue/TEST-123/remotelink", timeout=30)

    @patch("infrastructure_atlas.interfaces.api.routes.jira._jira_session")
    @patch("infrastructure_atlas.interfaces.api.routes.jira.require_jira_enabled")
    def test_create_confluence_link_success(self, mock_require, mock_session_factory):
        mock_sess = MagicMock()
        mock_session_factory.return_value = (mock_sess, "https://jira.example.com")
        
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": 1001,
            "self": "https://jira/remotelink/1001"
        }
        mock_sess.post.return_value = mock_response
        
        req = ConfluenceRemoteLinkReq(page_id="999", title="My Page")
        result = create_confluence_remotelink("TEST-123", req)
        
        self.assertTrue(result["success"])
        self.assertEqual(result["linkId"], 1001)
        
        # Verify payload
        call_args = mock_sess.post.call_args
        self.assertIn("json", call_args[1])
        payload = call_args[1]["json"]
        self.assertIn("appId=", payload["globalId"])
        self.assertEqual(payload["object"]["title"], "My Page")

    @patch("infrastructure_atlas.interfaces.api.routes.jira._jira_session")
    @patch("infrastructure_atlas.interfaces.api.routes.jira.require_jira_enabled")
    def test_delete_remote_link_success(self, mock_require, mock_session_factory):
        mock_sess = MagicMock()
        mock_session_factory.return_value = (mock_sess, "https://jira.example.com")
        
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_sess.delete.return_value = mock_response
        
        result = delete_remote_link("TEST-123", "1001")
        self.assertTrue(result["success"])
        mock_sess.delete.assert_called_with("https://jira.example.com/rest/api/3/issue/TEST-123/remotelink/1001", timeout=30)

    @patch("infrastructure_atlas.interfaces.api.routes.jira._jira_session")
    @patch("infrastructure_atlas.interfaces.api.routes.jira.require_jira_enabled")
    def test_create_link_duplicate(self, mock_require, mock_session_factory):
         # Simulate 400 Bad Request or similar for duplicate if Jira behaves that way
         mock_sess = MagicMock()
         mock_session_factory.return_value = (mock_sess, "https://jira.example.com")
         
         mock_response = MagicMock()
         mock_response.status_code = 400
         mock_response.text = "Link validation failed"
         mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)
         mock_sess.post.return_value = mock_response
         
         req = ConfluenceRemoteLinkReq(page_id="999")
         
         with self.assertRaises(HTTPException) as cm:
             create_confluence_remotelink("TEST-123", req)
         self.assertEqual(cm.exception.status_code, 400)

if __name__ == '__main__':
    unittest.main()
