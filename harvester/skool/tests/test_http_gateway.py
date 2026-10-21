"""Tests for HttpGateway and ResponseClassifier."""

import pytest
from skool.http_gateway import (
    ClassifiedResponse,
    HttpGateway,
    ResponseClass,
    ResponseClassifier,
)


def test_classify_200_ok_next_data():
    body = '{"pageProps": {"group": {"name": "test-group"}}}'
    url = "https://www.skool.com/_next/data/build123/test-group/about.json"
    cls, data, err = ResponseClassifier.classify(200, body, {}, url)

    assert cls == ResponseClass.OK
    assert data["pageProps"]["group"]["name"] == "test-group"
    assert err is None


def test_classify_200_auth_expired():
    body = '{"pageProps": {"__N_REDIRECT": "/login?redirect=/skoolers"}}'
    url = "https://www.skool.com/_next/data/build123/skoolers/members.json"
    cls, data, err = ResponseClassifier.classify(200, body, {}, url)

    assert cls == ResponseClass.AUTH_EXPIRED
    assert "login" in err


def test_classify_200_gone_redirect():
    body = '{"pageProps": {"__N_REDIRECT": "/discovery"}}'
    url = "https://www.skool.com/_next/data/build123/deleted-group/about.json"
    cls, data, err = ResponseClassifier.classify(200, body, {}, url)

    assert cls == ResponseClass.GONE
    assert "Redirected" in err


def test_classify_200_gone_not_found_flag():
    body = '{"pageProps": {"notFound": true}}'
    url = "https://www.skool.com/_next/data/build123/nonexistent/about.json"
    cls, data, err = ResponseClassifier.classify(200, body, {}, url)

    assert cls == ResponseClass.GONE


def test_classify_200_waf_soft_html():
    body = "<html><head><title>Verify you are human</title></head><body>WAF challenge</body></html>"
    url = "https://www.skool.com/_next/data/build123/test-group/about.json"
    cls, data, err = ResponseClassifier.classify(200, body, {}, url)

    assert cls == ResponseClass.WAF_SOFT
    assert data is None


def test_classify_200_waf_soft_missing_page_props():
    body = '{"error": "something", "items": []}'
    url = "https://www.skool.com/_next/data/build123/test-group/about.json"
    cls, data, err = ResponseClassifier.classify(200, body, {}, url)

    assert cls == ResponseClass.WAF_SOFT


def test_classify_202_waf_challenge():
    body = "<html><body>AWS WAF challenge placeholder</body></html>"
    url = "https://www.skool.com/_next/data/build123/test-group/about.json"
    cls, data, err = ResponseClassifier.classify(202, body, {}, url)

    assert cls == ResponseClass.WAF_CHALLENGE


def test_classify_202_with_page_props_is_ok():
    body = '{"pageProps": {"valid": true}}'
    url = "https://www.skool.com/_next/data/build123/test-group/about.json"
    cls, data, err = ResponseClassifier.classify(202, body, {}, url)

    assert cls == ResponseClass.OK


def test_classify_403_waf_block():
    cls, data, err = ResponseClassifier.classify(403, "Forbidden", {}, "https://www.skool.com")
    assert cls == ResponseClass.WAF_BLOCK


def test_classify_429_rate_limit():
    cls, data, err = ResponseClassifier.classify(429, "Too Many Requests", {}, "https://www.skool.com")
    assert cls == ResponseClass.RATE_LIMIT


def test_classify_404_not_found():
    cls, data, err = ResponseClassifier.classify(404, "Not Found", {}, "https://www.skool.com")
    assert cls == ResponseClass.NOT_FOUND


def test_classify_500_transient():
    cls, data, err = ResponseClassifier.classify(503, "Service Unavailable", {}, "https://www.skool.com")
    assert cls == ResponseClass.TRANSIENT


def test_classify_exception_transient():
    cls, err = ResponseClassifier.classify_exception(TimeoutError("Connection timed out"), "https://www.skool.com")
    assert cls == ResponseClass.TRANSIENT
    assert "TimeoutError" in err


@pytest.mark.asyncio
async def test_http_gateway_cookie_management():
    gw = HttpGateway(cookies={"auth_token": "init_token"})
    assert gw.get_cookie("auth_token") == "init_token"

    await gw.update_tokens(waf_token="fresh_waf", auth_token="fresh_auth")
    assert gw.get_cookie("aws-waf-token") == "fresh_waf"
    assert gw.get_cookie("auth_token") == "fresh_auth"

    await gw.aclose()
