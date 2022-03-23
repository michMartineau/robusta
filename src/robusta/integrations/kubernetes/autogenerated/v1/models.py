# This file was autogenerated. Do not edit.

from hikaru.model.rel_1_16.v1 import *
from ...custom_models import RobustaPod,RobustaDeployment,RobustaJob


KIND_TO_MODEL_CLASS = {
    'Pod': RobustaPod,
    'ReplicaSet': ReplicaSet,
    'DaemonSet': DaemonSet,
    'Deployment': RobustaDeployment,
    'StatefulSet': StatefulSet,
    'Service': Service,
    'Event': Event,
    'HorizontalPodAutoscaler': HorizontalPodAutoscaler,
    'Node': Node,
    'ClusterRole': ClusterRole,
    'ClusterRoleBinding': ClusterRoleBinding,
    'Job': RobustaJob,
    'Namespace': Namespace,
    'ServiceAccount': ServiceAccount,
    'PersistentVolume': PersistentVolume
}
