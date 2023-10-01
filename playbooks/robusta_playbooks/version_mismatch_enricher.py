import logging

from prometrix import PrometheusQueryResult
from robusta.api import PROMETHEUS_REQUEST_TIMEOUT_SECONDS, ExecutionBaseEvent, PrometheusParams, action
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
        query = 'count by (git_version, cluster, node) (label_replace(kubernetes_build_info{job!~"kube-dns|coredns"}, "git_version", "$1", "git_version", "(v[0-9]*.[0-9]*).*"))'
        prom_params = {"timeout": PROMETHEUS_REQUEST_TIMEOUT_SECONDS}
        prom.check_prometheus_connection(prom_params)
        result = prom.custom_query(query=query, params=prom_params)
        logging.warning(result)
        # event.add_enrichment(
        #    [PrometheusBlock(data=prometheus_result, query=params.promql_query)],
        # )
    except Exception:
        logging.error(f"Failed getting query", exc_info=True)
