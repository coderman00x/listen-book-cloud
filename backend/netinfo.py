"""网络访问信息（v1.3 增量；v2.0 增加公网模式）：局域网 IP 探测 + 访问信息聚合。

设计约束（红线）：本模块**仅读取网卡地址**，无任何持久化副作用，
不读写用户原始文件，也不写 data/ 内既有业务数据。

IP 探测优先级：
1. LISTENBOOK_LAN_IP 显式指定（多网卡/VPN/容器桥接/NAT 兜底）；
2. socket 技巧：建 UDP socket 连公网地址（不真正发包），取默认路由网卡 IPv4
   ——天然取「走默认路由的那张网卡」的首个非回环 IPv4，通常即手机可达的 LAN IP；
3. 失败回退 127.0.0.1。

v2.0：LISTENBOOK_PUBLIC=1 时走公网分支，**不探测也不返回容器内网 IP**
（容器内网 IP 对手机毫无意义，也不该暴露到公网），改返回 public_url + hint。
"""
from __future__ import annotations

import os
import socket

from .config import ACCESS_TOKEN, LAN_IP, PORT, PUBLIC_MODE, PUBLIC_URL


def get_lan_ip() -> str:
    """返回手机可达的局域网 IPv4（首个非回环地址）。

    仅用标准库，不引入 ifaddr/netifaces 等重依赖。
    """
    if LAN_IP:
        return LAN_IP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 8.8.8.8:80 仅用于触发操作系统选择默认路由网卡，不会真正发包。
        sock.connect(("8.8.8.8", 80))
        ip: str = sock.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        sock.close()
    return ip


def get_network_info() -> dict:
    """聚合网络访问信息，供 ``GET /api/network/info`` 返回。

    - 公网模式（``PUBLIC_MODE``）返回
      ``{mode:"public", public_url, port, access_token_required, hint}``，
      **不含** ``lan_ip`` / ``access_url``，避免把容器内网 IP 暴露给公网前端。
    - 局域网模式保持 v1.3 的全部字段，仅**新增** ``mode:"lan"``，向后兼容旧前端。

    本函数无 request 参数，故 PUBLIC_URL 为空时不做 Host 兜底，只留空并给出 hint，
    由前端用 ``window.location.origin`` 回退。
    """
    if PUBLIC_MODE:
        hint = (
            "公网模式已启用：请用平台提供的 HTTPS 地址在手机打开，生成完请立刻导出 mp3。"
            if PUBLIC_URL
            else (
                "公网模式已启用：未配置 LISTENBOOK_PUBLIC_URL，请在平台环境变量填写公网 "
                "HTTPS 地址（如 https://xxx.onrender.com）；前端将回退到当前页面地址。"
            )
        )
        return {
            "mode": "public",
            "public_url": PUBLIC_URL,
            "port": PORT,
            "access_token_required": bool(ACCESS_TOKEN),
            "hint": hint,
        }

    lan_ip = get_lan_ip()
    port = PORT
    return {
        "mode": "lan",
        "lan_ip": lan_ip,
        "port": port,
        "access_url": f"http://{lan_ip}:{port}",
        "access_token_required": bool(ACCESS_TOKEN),
    }
