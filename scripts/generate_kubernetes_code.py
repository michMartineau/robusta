import argparse
import os
import textwrap
from typing import TextIO

KUBERNETES_VERSIONS = ["v1", "v2beta1", "v2beta2"]
KUBERNETES_RESOURCES = [
    "Pod",
    "ReplicaSet",
    "DaemonSet",
    "Deployment",
    "StatefulSet",
    "Service",
    "Event",
    "HorizontalPodAutoscaler",
    "Node",
    "ClusterRole",
    "ClusterRoleBinding",
    "Job",
    "Namespace",
    "ServiceAccount",
    "PersistentVolume",
    "ConfigMap",
]
KUBERNETES_RESOURCES_STR = ",".join(KUBERNETES_RESOURCES)
NON_NAMESPACED_RESOURCES = ["Node", "ClusterRole", "ClusterRoleBinding", "Namespace", "PersistentVolume"]
TRIGGER_TYPES = {
    "create": "K8sOperationType.CREATE",
    "update": "K8sOperationType.UPDATE",
    "delete": "K8sOperationType.DELETE",
    "all_changes": "None",
}

CUSTOM_SUBCLASSES = {
    "Pod": "RobustaPod",
    "Deployment": "RobustaDeployment",
    "Job": "RobustaJob",
}
CUSTOM_SUBCLASSES_NAMES_STR = ",".join(CUSTOM_SUBCLASSES.values())

COMMON_PREFIX = """# This file was autogenerated. Do not edit.\n\n"""


def get_model_class(k8s_resource_name: str) -> str:
    if k8s_resource_name in CUSTOM_SUBCLASSES:
        return CUSTOM_SUBCLASSES[k8s_resource_name]
    return k8s_resource_name


def autogenerate_events(f: TextIO):
    f.write(COMMON_PREFIX)
    f.write(
        textwrap.dedent(
            f"""\
        import logging
        import traceback
        from dataclasses import dataclass
        from abc import abstractmethod
        from hikaru.model import {KUBERNETES_RESOURCES_STR}
        from hikaru.utils import Response
        from pydantic import BaseModel
        from typing import Union, Optional, List
        from ..base_event import K8sBaseChangeEvent
        from ....core.model.events import ExecutionBaseEvent, ExecutionEventBaseParams
        from ..custom_models import {CUSTOM_SUBCLASSES_NAMES_STR}
        """
        )
    )

    all_versioned_resources = set()
    for resource in KUBERNETES_RESOURCES:
        if resource in CUSTOM_SUBCLASSES:
            all_versioned_resources.add(get_model_class(resource))
        else:
            version_resources = [
                f"{version}{resource}" for version in KUBERNETES_VERSIONS
            ]
            all_versioned_resources = all_versioned_resources.union(
                set(version_resources)
            )
    # without this, every time that we re-run the autogeneration, the order changes
    all_versioned_resources = sorted(list(all_versioned_resources))

    all_resources = [get_model_class(resource) for resource in KUBERNETES_RESOURCES]

    for version in sorted(KUBERNETES_VERSIONS):
        for resource in sorted(KUBERNETES_RESOURCES):
            f.write(
                textwrap.dedent(
                    f"""\
                from hikaru.model.rel_1_16.{version} import {resource} as {version}{resource}    
                """
                )
            )

    LOADERS_MAPPING = {}
    for resource in KUBERNETES_RESOURCES:
        LOADERS_MAPPING[resource] = (
            resource not in NON_NAMESPACED_RESOURCES,
            f"{get_model_class(resource)}.readNamespaced{resource}",
        )

    #  build resource loader
    f.write(
        textwrap.dedent(
            f"""\


            LOADERS_MAPPINGS = {'{'}
            """
        )
    )

    for resource in KUBERNETES_RESOURCES:
        f.write(
            f"    '{resource.lower()}': ({resource not in NON_NAMESPACED_RESOURCES}, {get_model_class(resource)}.read{'' if resource in NON_NAMESPACED_RESOURCES else 'Namespaced'}{resource}),\n"
        )

    f.write(f"{'}'}\n\n\n")

    f.write(
        textwrap.dedent(
            f"""\
        class ResourceLoader:
            @staticmethod
            def read_resource(kind: str, name: str, namespace: str = None) -> Response:
                resource_mapper = LOADERS_MAPPINGS[kind.lower()]
                if not resource_mapper:
                    raise Exception("resource loader not found")
                
                if resource_mapper[0]:  # namespaced resource
                    return resource_mapper[1](name=name, namespace=namespace)
                else:
                    return resource_mapper[1](name=name)
        """
        )
    )

    # add the KubernetesResourceEvent
    f.write(
        textwrap.dedent(
            f"""\
            
            
        class ResourceAttributes(ExecutionEventBaseParams):
            kind: str
            name: str
            namespace: Optional[str] = None


        @dataclass
        class KubernetesResourceEvent(ExecutionBaseEvent):
            _obj: Optional[{f"Union[{','.join(all_resources)}]"}] = None

            def __init__(self, obj: {f"Union[{','.join(all_resources)}]"}, named_sinks: List[str]):
                super().__init__(named_sinks=named_sinks)
                self._obj = obj
            
            def get_resource(self) -> Optional[{f"Union[{','.join(all_resources)}]"}]:
                return self._obj

            @staticmethod
            def from_params(params: ResourceAttributes) -> Optional["KubernetesResourceEvent"]:
                try:
                    obj = ResourceLoader.read_resource(
                        kind=params.kind, 
                        name=params.name, 
                        namespace=params.namespace
                    ).obj
                except Exception:
                    logging.error(f"Could not load resource {{params}}", exc_info=True)
                    return None
                return KubernetesResourceEvent(obj=obj, named_sinks=params.named_sinks)


        @dataclass
        class KubernetesAnyChangeEvent(K8sBaseChangeEvent):
            obj: Optional[{f"Union[{','.join(all_versioned_resources)}]"}] = None
            old_obj: Optional[{f"Union[{','.join(all_versioned_resources)}]"}] = None

            def get_resource(self) -> Optional[{f"Union[{','.join(all_versioned_resources)}]"}]:
                return self.obj


        """
        )
    )
    for resource in KUBERNETES_RESOURCES:
        if resource in CUSTOM_SUBCLASSES:
            model_class_str = get_model_class(resource)
        else:
            version_resources = [
                f"{version}{resource}" for version in KUBERNETES_VERSIONS
            ]
            model_class_str = f"Union[{','.join(version_resources)}]"

        namespace_str = "" if resource in NON_NAMESPACED_RESOURCES else "namespace: str"
        f.write(
            textwrap.dedent(
                f"""\
            class {resource}Attributes(ExecutionEventBaseParams):
                name: str
                {namespace_str}


                """
            )
        )

        f.write(
            textwrap.dedent(
                f"""\
            @dataclass
            class {resource}Event(KubernetesResourceEvent):
                def __init__(self, obj: {get_model_class(resource)}, named_sinks: List[str]):
                    super().__init__(obj=obj, named_sinks=named_sinks)
                
                def get_{resource.lower()}(self) -> Optional[{get_model_class(resource)}]:
                    return self._obj

                @staticmethod
                def from_params(params: {resource}Attributes) -> Optional["{resource}Event"]:
                    try:
                        obj = {get_model_class(resource)}.read{"" if resource in NON_NAMESPACED_RESOURCES else "Namespaced"}{resource}(name=params.name{"" if resource in NON_NAMESPACED_RESOURCES else ", namespace=params.namespace"}).obj
                    except Exception:
                        logging.error(f"Could not load {resource} {{params}}", exc_info=True)
                        return None
                    return {resource}Event(obj=obj, named_sinks=params.named_sinks)


            @dataclass
            class {resource}ChangeEvent({resource}Event, KubernetesAnyChangeEvent):
                obj: Optional[{model_class_str}] = None
                old_obj: Optional[{model_class_str}] = None

                def get_{resource.lower()}(self) -> Optional[{model_class_str}]:
                    return self.obj


            """
            )
        )
    mappers = [f"'{r.lower()}': {r}ChangeEvent" for r in KUBERNETES_RESOURCES]
    mappers_str = ",\n    ".join(mappers)
    f.write(f"\nKIND_TO_EVENT_CLASS = {{\n    {mappers_str}\n}}\n")


def autogenerate_models(f: TextIO, version: str):
    f.write(COMMON_PREFIX)
    f.write(
        textwrap.dedent(
            f"""\
        from hikaru.model.rel_1_16.{version} import *
        from ...custom_models import {CUSTOM_SUBCLASSES_NAMES_STR}


        """
        )
    )

    mappers = [f"'{r}': {get_model_class(r)}" for r in KUBERNETES_RESOURCES]
    mappers_str = ",\n    ".join(mappers)
    f.write(f"KIND_TO_MODEL_CLASS = {{\n    {mappers_str}\n}}\n")


def autogenerate_versioned_models(f: TextIO):
    f.write(COMMON_PREFIX)
    for version in sorted(KUBERNETES_VERSIONS):
        f.write(
            textwrap.dedent(
                f"""\
            from .{version}.models import KIND_TO_MODEL_CLASS as {version}
            """
            )
        )

    mappers = sorted([f"'{version}': {version}" for version in KUBERNETES_VERSIONS])
    mappers_str = ",\n    ".join(mappers)

    f.write(f"VERSION_KIND_TO_MODEL_CLASS = {{\n    {mappers_str}\n}}\n")
    f.write(
        textwrap.dedent(
            f"""\


        def get_api_version(apiVersion: str):
            if "/" in apiVersion:
                apiVersion = apiVersion.split("/")[1]
            return VERSION_KIND_TO_MODEL_CLASS.get(apiVersion)
        """
        )
    )


def get_trigger_class_name(trigger_name: str) -> str:
    if trigger_name == "all_changes":
        return "AllChanges"
    return trigger_name.capitalize()


def autogenerate_triggers(f: TextIO):
    f.write(COMMON_PREFIX)
    f.write(
        textwrap.dedent(
            """\
        from typing import Optional, Dict
        from pydantic import BaseModel
        from ..base_triggers import K8sBaseTrigger
        from ....core.model.k8s_operation_type import K8sOperationType
        from .events import *


        """
        )
    )

    triggers = []
    for resource in KUBERNETES_RESOURCES:
        f.write(f"# {resource} Triggers\n")
        for trigger_name, operation_type in sorted(TRIGGER_TYPES.items()):
            f.write(
                textwrap.dedent(
                    f"""\
            class {resource}{get_trigger_class_name(trigger_name)}Trigger(K8sBaseTrigger):

                def __init__(self, name_prefix: str = None, namespace_prefix: str = None, labels_selector: str = None):
                    super().__init__(
                        kind=\"{resource}\", 
                        operation={operation_type}, 
                        name_prefix=name_prefix, 
                        namespace_prefix=namespace_prefix,
                        labels_selector=labels_selector,
                    )

                @staticmethod
                def get_execution_event_type() -> type:
                    return {resource}ChangeEvent


            """
                )
            )
            triggers.append(
                [
                    f"on_{resource.lower()}_{trigger_name}",
                    f"{resource}{get_trigger_class_name(trigger_name)}Trigger",
                ]
            )

    f.write(f"# Kubernetes Any Triggers\n")
    for trigger_name, operation_type in sorted(TRIGGER_TYPES.items()):
        f.write(
            textwrap.dedent(
                f"""\
        class KubernetesAny{get_trigger_class_name(trigger_name)}Trigger(K8sBaseTrigger):

            def __init__(self, name_prefix: str = None, namespace_prefix: str = None, labels_selector: str = None):
                super().__init__(
                    kind=\"Any\", 
                    operation={operation_type}, 
                    name_prefix=name_prefix, 
                    namespace_prefix=namespace_prefix,
                    labels_selector=labels_selector,
                )

            @staticmethod
            def get_execution_event_type() -> type:
                return KubernetesAnyChangeEvent


        """
            )
        )
        triggers.append(
            [
                f"on_kubernetes_any_resource_{trigger_name}",
                f"KubernetesAny{get_trigger_class_name(trigger_name)}Trigger",
            ]
        )

    f.write(
        textwrap.dedent(
            """\
            # K8s Trigger class
            class K8sTriggers(BaseModel):

        """
        )
    )

    for trigger in sorted(triggers):
        f.write(
            textwrap.indent(f"{trigger[0]}: Optional[{trigger[1]}]\n", prefix="    ")
        )


def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    output_dir = os.path.join(
        root_dir, "src/robusta/integrations/kubernetes/autogenerated/"
    )

    parser = argparse.ArgumentParser(
        description="Autogenerate kubernetes models, events, and triggers"
    )
    parser.add_argument(
        "-o", "--output", default=output_dir, type=str, help="output directory"
    )
    args = parser.parse_args()

    # generate versioned events and models
    for version in KUBERNETES_VERSIONS:
        dir_path = os.path.join(args.output, version)
        os.makedirs(dir_path, exist_ok=True)
        with open(os.path.join(dir_path, "models.py"), "w") as f:
            autogenerate_models(f, version)

    # generate all version unions
    with open(os.path.join(args.output, "events.py"), "w") as f:
        autogenerate_events(f)
    with open(os.path.join(args.output, "models.py"), "w") as f:
        autogenerate_versioned_models(f)
    with open(os.path.join(args.output, "triggers.py"), "w") as f:
        autogenerate_triggers(f)


if __name__ == "__main__":
    main()
