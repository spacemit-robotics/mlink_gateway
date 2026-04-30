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

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ServiceDescriptor:
    """
    描述一个对外暴露的“工具”或“服务”。
    """

    full_name: str          # 在 MCP 中暴露给 LLM 的名称，例如 "device1.self.audio_speaker.set_volume"
    device_id: str          # 默认使用的设备 ID
    tool_name: str          # 设备侧真实工具名，例如 "self.audio_speaker.set_volume"
    description: str        # 文本描述
    input_schema: Dict[str, Any]  # JSON Schema，用于参数校验和 MCP 描述


__all__ = ["ServiceDescriptor"]


