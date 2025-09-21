from enreach_tools.infrastructure.external.confluence_client import ConfluenceClientConfig


def test_confluence_config_api_root():
    cfg = ConfluenceClientConfig(base_url="https://example.atlassian.net", email="u", api_token="t")
    assert cfg.api_root() == "https://example.atlassian.net/wiki/rest/api"
