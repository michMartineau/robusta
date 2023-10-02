import logging
import tempfile
from typing import List

import apprise
from apprise import NotifyFormat, NotifyType

from robusta.core.reporting.base import BaseBlock, Emojis, Finding, FindingStatus
from robusta.core.reporting.blocks import (
    FileBlock,
    LinksBlock,
    LinkProp,
    MarkdownBlock,
)
from robusta.core.reporting.consts import EnrichmentAnnotation
from robusta.core.sinks.transformer import Transformer


class MailTransformer(Transformer):
    def __init__(self, *args, **kwargs):
        super(MailTransformer).__init__(*args, **kwargs)
        self.file_blocks = []

    def block_to_html(self, block: BaseBlock) -> str:
        # TODO should we additionally support ScanReportBlock here?
        if isinstance(block, FileBlock):
            self.file_blocks.append(block)
            return f"<p>See attachment {block.filename}</p>"
        if isinstance(block, LinksBlock):
            return (
                "<ul>\n"
                + "\n".join(f'  <li><a href="{link.url}">{link.text}</a></li>' for link in block.links)
                + "</ul>"
            )
        else:
            return super().block_to_html(block)


class MailSender:
    def __init__(self, mailto: str, account_id: str, cluster_name: str, signing_key: str):
        self.mailto = mailto
        self.signing_key = signing_key
        self.account_id = account_id
        self.cluster_name = cluster_name

    def send_finding_via_email(self, finding: Finding, platform_enabled: bool):
        # TODO this method is too big, too complex and awkward for unit tests. Improve this.
        blocks: List[BaseBlock] = []

        if finding.title:
            status: FindingStatus = (
                FindingStatus.RESOLVED if finding.title.startswith("[RESOLVED]") else FindingStatus.FIRING
            )
            blocks.append(self.__create_finding_header(finding, status, platform_enabled))
        else:
            # TODO is this correct? Is it possible for the finding to have no title at all?
            status: FindingStatus = FindingStatus.FIRING

        if platform_enabled:
            blocks.append(self.__create_links(finding))

        blocks.append(MarkdownBlock(text=f"*Source:* `{self.cluster_name}`"))
        if finding.description:
            blocks.append(MarkdownBlock(f"{Emojis.Alert.value} *Alert:* {finding.description}"))

        for enrichment in finding.enrichments:
            blocks.extend(enrichment.blocks)

        transformer = MailTransformer()
        html_body = transformer.to_html(blocks).strip()

        ap_obj = apprise.Apprise()
        attachments = apprise.AppriseAttachment()
        attachment_files = []
        try:
            for file_block in transformer.file_blocks:
                # This is awkward, but it's the standard way to handle
                # attachments in apprise - by providing local filesystem
                # names. TODO: We could work around this limitation using
                # some AttachBase-related hacking (create a subclass that
                # would pretend to be downloading content from the web
                # and just return the in-memory file contents).
                f = tempfile.NamedTemporaryFile()
                attachment_files.append(f)
                f.write(file_block.contents)
                attachments.add(f.name)
            ap_obj.add(self.mailto)
            logging.info(f"MailSender: sending title={finding.title}, body={html_body}")
            ap_obj.notify(
                title=finding.title,
                body=html_body,
                body_format=NotifyFormat.HTML,
                notify_type=NotifyType.SUCCESS if status == FindingStatus.RESOLVED else NotifyType.WARNING,
                attach=attachments,
            )
        finally:
            for f in attachment_files:
                try:
                    f.close()
                except:
                    pass

    def __create_finding_header(self, finding: Finding, status: FindingStatus, platform_enabled: bool) -> MarkdownBlock:
        title = finding.title.removeprefix("[RESOLVED] ")
        sev = finding.severity
        status_str: str = f"{status.to_emoji()} `{status.name.lower()}`" if finding.add_silence_url else ""
        return MarkdownBlock(f"{status_str} {sev.to_emoji()} `{sev.name.lower()}` {title}")

    def __create_links(self, finding: Finding):
        links: List[LinkProp] = []
        links.append(
            LinkProp(
                text="Investigate 🔎",
                url=finding.get_investigate_uri(self.account_id, self.cluster_name),
            )
        )

        if finding.add_silence_url:
            links.append(
                LinkProp(
                    text="Configure Silences 🔕",
                    url=finding.get_prometheus_silence_url(self.account_id, self.cluster_name),
                )
            )

        for video_link in finding.video_links:
            links.append(LinkProp(text=f"{video_link.name} 🎬", url=video_link.url))

        return LinksBlock(links=links)
