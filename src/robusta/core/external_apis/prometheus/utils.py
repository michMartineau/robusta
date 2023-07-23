import logging
import os
from enum import Enum
from typing import Dict, List, Optional

import requests
from prometheus_api_client import PrometheusApiClientException, PrometheusConnect
from requests.exceptions import ConnectionError, HTTPError
from requests.sessions import merge_setting

from robusta.core.exceptions import (
    NoPrometheusUrlFound,
    PrometheusFlagsConnectionError,
    PrometheusNotFound,
    VictoriaMetricsNotFound,
)
from robusta.core.external_apis.prometheus.custom_connect import AWSPrometheusConnect
from robusta.utils.common import parse_query_string


class PrometheusApis(Enum):
    QUERY = 0
    QUERY_RANGE = 1
    LABELS = 2
    FLAGS = 3
    VM_FLAGS = 4


class PrometheusConfig:
    url: str
    disable_ssl: bool
    additional_headers: Optional[Dict[str, str]]
    prometheus_auth: Optional[str]
    prometheus_url_query_string: Optional[str]
    additional_labels: Optional[Dict[str, str]]
    supported_apis: List[PrometheusApis] = [
        PrometheusApis.QUERY,
        PrometheusApis.QUERY_RANGE,
        PrometheusApis.LABELS,
        PrometheusApis.FLAGS,
    ]


class AWSPrometheusConfig(PrometheusConfig):
    access_key: str
    secret_access_key: str
    service_name: str = "aps"
    aws_region: str
    supported_apis: List[PrometheusApis] = [
        PrometheusApis.QUERY,
        PrometheusApis.QUERY_RANGE,
        PrometheusApis.LABELS,
    ]


class CoralogixPrometheusConfig(PrometheusConfig):
    supported_apis: List[PrometheusApis] = [
        PrometheusApis.QUERY,
        PrometheusApis.QUERY_RANGE,
        PrometheusApis.LABELS,
    ]


class VictoriaMetricsPrometheusConfig(PrometheusConfig):
    prometheus_token: str
    supported_apis: List[PrometheusApis] = [
        PrometheusApis.QUERY,
        PrometheusApis.QUERY_RANGE,
        PrometheusApis.LABELS,
        PrometheusApis.VM_FLAGS,
    ]


class AzurePrometheusConfig(PrometheusConfig):
    azure_resource: str
    azure_metadata_endpoint: str
    azure_token_endpoint: str
    azure_use_managed_id: Optional[str]
    azure_client_id: Optional[str]
    azure_client_secret: Optional[str]

    def get_client_id(self) -> Optional[str]:
        return self.azure_client_id if self.azure_client_id else os.environ.get("AZURE_CLIENT_ID")

    def get_client_secret(self) -> Optional[str]:
        return self.azure_client_secret if self.azure_client_secret else os.environ.get("AZURE_CLIENT_SECRET")


class PrometheusAuthorization:
    bearer_token: str = ""
    azure_authorization: bool = (
        os.environ.get("AZURE_CLIENT_ID", "") != "" and os.environ.get("AZURE_TENANT_ID", "") != ""
    ) and (os.environ.get("AZURE_CLIENT_SECRET", "") != "" or os.environ.get("AZURE_USE_MANAGED_ID", "") != "")

    @classmethod
    def get_authorization_headers(cls, config: PrometheusConfig) -> Dict:
        if isinstance(config, CoralogixPrometheusConfig):
            return {"token": config.prometheus_token}
        elif config.prometheus_auth:
            return {"Authorization": config.prometheus_auth.get_secret_value()}
        elif cls.azure_authorization:
            return {"Authorization": (f"Bearer {cls.bearer_token}")}
        else:
            return {}

    @classmethod
    def request_new_token(cls, config: PrometheusConfig) -> bool:
        if cls.azure_authorization and isinstance(config, AzurePrometheusConfig):
            try:
                if config.azure_use_managed_id:
                    res = requests.get(
                        url=config.azure_metadata_endpoint,
                        headers={
                            "Metadata": "true",
                        },
                        data={
                            "api-version": "2018-02-01",
                            "client_id": config.get_client_id(),
                            "resource": config.azure_resource,
                        },
                    )
                else:
                    res = requests.post(
                        url=config.azure_token_endpoint,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        data={
                            "grant_type": "client_credentials",
                            "client_id": config.get_client_id(),
                            "client_secret": config.get_client_secret(),
                            "resource": config.azure_resource,
                        },
                    )
            except Exception:
                logging.exception("Unexpected error when trying to generate azure access token.")
                return False

            if not res.ok:
                logging.error(f"Could not generate an azure access token. {res.reason}")
                return False

            cls.bearer_token = res.json().get("access_token")
            logging.info("Generated new azure access token.")
            return True

        return False


def get_prometheus_connect(prom_config: PrometheusConfig) -> "CustomPrometheusConnect":
    headers = PrometheusAuthorization.get_authorization_headers(prom_config)
    if isinstance(prom_config, AWSPrometheusConfig):
        prom = AWSPrometheusConnect(
            access_key=prom_config.access_key,
            secret_key=prom_config.secret_access_key,
            service_name=prom_config.service_name,
            region=prom_config.aws_region,
            url=prom_config.url,
            disable_ssl=prom_config.disable_ssl,
            headers=headers,
        )
    else:
        prom = PrometheusConnect(url=prom_config.url, disable_ssl=prom_config.disable_ssl, headers=headers)

    if prom_config.prometheus_url_query_string:
        query_string_params = parse_query_string(prom_config.prometheus_url_query_string)
        prom._session.params = merge_setting(prom._session.params, query_string_params)
    prom.config = prom_config
    return prom


class CustomPrometheusConnect(PrometheusConnect):
    def __init__(self, config: PrometheusConfig):
        super().__init__(url=config.url, disable_ssl=config.disable_ssl, headers=config.additional_headers)
        self.config = config

    def check_prometheus_connection(self, params: dict = None):
        params = params or {}
        try:
            if isinstance(self, AWSPrometheusConnect):
                # will throw exception if not 200
                return self.custom_query(query="example")
            else:
                response = self._session.get(
                    f"{self.url}/api/v1/query",
                    verify=self.ssl_verification,
                    headers=self.headers,
                    # This query should return empty results, but is correct
                    params={"query": "example", **params},
                    context={},
                )
            if response.status_code == 401:
                if PrometheusAuthorization.request_new_token(prom.config):
                    self.headers = PrometheusAuthorization.get_authorization_headers(prom.config)
                    response = self._session.get(
                        f"{self.url}/api/v1/query",
                        verify=self.ssl_verification,
                        headers=self.headers,
                        params={"query": "example", **params},
                    )

            response.raise_for_status()
        except (ConnectionError, HTTPError, PrometheusApiClientException) as e:
            raise PrometheusNotFound(
                f"Couldn't connect to Prometheus found under {self.url}\nCaused by {e.__class__.__name__}: {e})"
            ) from e

    def __text_config_to_dict(self, text: str) -> Dict:
        conf = {}
        lines = text.strip().split("\n")
        for line in lines:
            key, val = line.strip().split("=")
            conf[key] = val.strip('"')

        return conf

    def get_prometheus_flags(self) -> Optional[Dict]:
        try:
            if PrometheusApis.FLAGS in self.config.supported_apis:
                return self.fetch_prometheus_flags()
            if PrometheusApis.VM_FLAGS in self.config.supported_apis:
                return self.fetch_victoria_metrics_flags()
        except Exception as e:
            service_name = "Prometheus" if PrometheusApis.FLAGS in self.config.supported_apis else "Victoria Metrics"
            raise PrometheusFlagsConnectionError(f"Couldn't connect to the url: {self.url}\n\t\t{service_name}: {e}")

    def fetch_prometheus_flags(self) -> Dict:
        try:
            response = self._session.get(
                f"{self.url}/api/v1/status/flags",
                verify=self.ssl_verification,
                headers=self.headers,
                # This query should return empty results, but is correct
                params={},
            )
            response.raise_for_status()
            return response.json().get("data", {})
        except Exception as e:
            raise PrometheusNotFound(
                f"Couldn't connect to Prometheus found under {self.url}\nCaused by {e.__class__.__name__}: {e})"
            ) from e

    def fetch_victoria_metrics_flags(self) -> Dict:
        try:
            # connecting to VictoriaMetrics
            response = self._session.get(
                f"{self.url}/flags",
                verify=self.ssl_verification,
                headers=self.headers,
                # This query should return empty results, but is correct
                params={},
            )
            response.raise_for_status()

            configuration = self.__text_config_to_dict(response.text)
            return configuration
        except Exception as e:
            raise VictoriaMetricsNotFound(
                f"Couldn't connect to VictoriaMetrics found under {self.url}\nCaused by {e.__class__.__name__}: {e})"
            ) from e
