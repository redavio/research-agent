import pytest

from research_agent.http import FetchError, get


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:8080/", "http://169.254.169.254/latest/", "http://10.0.0.1/", "file:///etc/passwd"])
def test_refuses_private_and_non_web_addresses(url):
    with pytest.raises(FetchError):
        get(url)
