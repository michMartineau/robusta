import logging

from robusta.api import (
    PROMETHEUS_REQUEST_TIMEOUT_SECONDS,
    ExecutionBaseEvent,
    MarkdownBlock,
    PrometheusParams,
    SlackAnnotations,
    TableBlock,
    action,
)
from robusta.integrations.prometheus.utils import get_prometheus_connect


@action
def version_mismatch_enricher(event: ExecutionBaseEvent, params: PrometheusParams):
    """
    Enriches the finding with a prometheus query

    for example prometheus queries see here:
    https://prometheus.io/docs/prometheus/latest/querying/examples/
    """

    try:
        prom = get_prometheus_connect(params)
        list_version_query = 'count by (git_version, cluster, node) (label_replace(kubernetes_build_info{job!~"kube-dns|coredns"}, "git_version", "$1", "git_version", "(v[0-9]*.[0-9]*).*"))'
        prom_params = {"timeout": PROMETHEUS_REQUEST_TIMEOUT_SECONDS}
        prom.check_prometheus_connection(prom_params)
        results = prom.custom_query(query=list_version_query, params=prom_params)
        kubernetes_api_version = max(
            [
                result.get("metric", {}).get("git_version")
                for result in results
                if result.get("metric", {}).get("node") is None
            ]
        )
        nodes_by_version = [
            [result.get("metric", {}).get("node"), result.get("metric", {}).get("git_version")]
            for result in results
            if result.get("metric", {}).get("node") is not None
        ]
        logging.warning(results)
        logging.warning(kubernetes_api_version)
        logging.warning(nodes_by_version)
        # event.add_enrichment(
        #    [PrometheusBlock(data=prometheus_result, query=params.promql_query)],
        # )
        event.add_enrichment(
            [
                MarkdownBlock(f"The kubernetes api server is version {kubernetes_api_version}."),
                TableBlock(
                    nodes_by_version,
                    ["name", "version"],
                    table_name="*Node Versions*",
                ),
                MarkdownBlock(
                    f"To solver this alert, make sure to update all of your nodes to version {kubernetes_api_version}."
                ),
            ],
            annotations={SlackAnnotations.ATTACHMENT: True},
        )
    except Exception:
        logging.error(f"Failed getting query", exc_info=True)
