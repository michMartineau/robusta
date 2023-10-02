from datetime import datetime
from unittest.mock import patch

import pytest

from robusta.core.reporting import Finding
from robusta.core.reporting.blocks import (
    FileBlock,
    LinkProp,
    LinksBlock,
    ScanReportBlock,
)
from robusta.core.reporting.consts import ScanType
from robusta.core.sinks.mail.mail_sink import MailSink
from robusta.core.sinks.mail.mail_sink_params import MailSinkParams, MailSinkConfigWrapper
from robusta.integrations.mail.sender import MailTransformer

# Rename import to avoid re-running tests.test_transformer.TestTransformer here via pytest discovery
from tests.test_transformer import TestTransformer as _TestTransformer


class MockRegistry:
    def get_global_config(self) -> dict:
        return {"account_id": 12345, "cluster_name": "testcluster", "signing_key": "SiGnKeY"}


@pytest.mark.parametrize("finding_resolved", [False, True])
def test_mail_sending(finding_resolved):
    config_wrapper = MailSinkConfigWrapper(
        mail_sink=MailSinkParams(
            name="mail_sink",
            mailto="mailtos://user:password@example.com?from=a@x&to=b@y",
        )
    )
    sink = MailSink(config_wrapper, MockRegistry())

    title = ("[RESOLVED] " if finding_resolved else "") + "title"
    finding = Finding(
        title=title,
        description="Lorem ipsum",
        aggregation_key="1234",
        add_silence_url=True,
    )
    with patch("robusta.integrations.mail.sender.apprise") as mock_apprise:
        sink.write_finding(finding, platform_enabled=True)
    mock_apprise.Apprise.return_value.add.assert_called_once_with("mailtos://user:password@example.com?from=a@x&to=b@y")
    expected_body = (
        """<p>✅ <code>resolved</code> 🟢 <code>info</code> title</p>\n\n<ul>\n  <li><a href="https://platform.robusta.dev/graphs?account=SiGnKeY&clusters=%5B%2212345%22%5D&names=%5B%221234%22%5D">Investigate 🔎</a></li>\n  <li><a href="https://platform.robusta.dev/silences/create?alertname=1234&cluster=12345&account=SiGnKeY&referer=sink">Configure Silences 🔕</a></li></ul>\n<p><b>Source:</b> <code>12345</code></p>\n\n<p>🚨 <b>Alert:</b> Lorem ipsum</p>"""
        if finding_resolved
        else """<p>🔥 <code>firing</code> 🟢 <code>info</code> title</p>\n\n<ul>\n  <li><a href="https://platform.robusta.dev/graphs?account=SiGnKeY&clusters=%5B%2212345%22%5D&names=%5B%221234%22%5D">Investigate 🔎</a></li>\n  <li><a href="https://platform.robusta.dev/silences/create?alertname=1234&cluster=12345&account=SiGnKeY&referer=sink">Configure Silences 🔕</a></li></ul>\n<p><b>Source:</b> <code>12345</code></p>\n\n<p>🚨 <b>Alert:</b> Lorem ipsum</p>"""
    )
    mock_apprise.Apprise.return_value.notify.assert_called_once_with(
        title=title,
        body=expected_body,
        body_format="html",
        notify_type="success" if finding_resolved else "warning",
        attach=mock_apprise.AppriseAttachment.return_value,
    )


# TODO add tests for attachment handling


class TestMailTransformer(_TestTransformer):
    @pytest.fixture()
    def transformer(self, request):
        return MailTransformer()

    @pytest.mark.parametrize(
        "block,expected_result",
        [
            (FileBlock(filename="x.png", contents=b"abcd"), "<p>See attachment x.png</p>"),
            (
                LinksBlock(links=[LinkProp(text="a", url="a.com"), LinkProp(text="b", url="b.org")]),
                """<ul>
  <li><a href="a.com">a</a></li>
  <li><a href="b.org">b</a></li></ul>""",
            ),
        ],
    )
    def test_file_links_scan_report_blocks(self, transformer, block, expected_result):
        with patch("robusta.core.sinks.transformer.logging") as mock_logging:
            assert transformer.block_to_html(block) == expected_result
