# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Author: laumy <mingyuan.liu@spacemit.com>

from typing import Dict, List

from .service_descriptor import ServiceDescriptor


class ToolRegistry:
    """
    维护系统中所有对外暴露的工具（ServiceDescriptor）。
    """

    def __init__(self) -> None:
        self._services: Dict[str, ServiceDescriptor] = {}

    def register_service(self, sd: ServiceDescriptor) -> None:
        self._services[sd.full_name] = sd

    def get(self, full_name: str) -> ServiceDescriptor | None:
        return self._services.get(full_name)

    def all_services(self) -> List[ServiceDescriptor]:
        return list(self._services.values())

    def remove_by_device(self, device_id: str) -> None:
        """
        移除指定 device_id 关联的所有工具描述。
        用于设备断线或重连时清理旧的工具映射。
        """
        self._services = {
            name: sd for name, sd in self._services.items() if sd.device_id != device_id
        }


__all__ = ["ToolRegistry"]


