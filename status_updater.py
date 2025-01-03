import json
import os.path
import subprocess
from datetime import datetime, timedelta
from typing import List

wg_confs_dir: str = "/etc/wireguard"
ov_confs_dir: str = "/etc/openvpn/server"


def bash_command(command: List[str]) -> str:
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=True)
        return result.stdout.strip()
    except Exception as bash_exception:
        print(f"Warning: {bash_exception}")
        return ""


def remove_openvpn_client_port(ip_and_port) -> str:
    return ip_and_port.split(':')[0]


def convert_openvpn_datetime_to_epoch(datetime_str) -> int:
    input_format = "%Y-%m-%d %H:%M:%S"
    local_datetime = datetime.strptime(datetime_str, input_format)
    gmt7_datetime = local_datetime + timedelta(hours=7)
    return int(gmt7_datetime.timestamp() * 1000)


def update_openvpn_services() -> dict:
    ovpn_services: List[str] = []
    if os.path.isdir(ov_confs_dir):
        ovpn_services = [
            f.replace('.conf', '')
            for f in os.listdir(ov_confs_dir)
            if f.endswith(".conf")
        ]
    ovpn_services = list(filter(
        lambda name: bash_command(["systemctl", "is-active", f"openvpn-server@{name}.service"]) == 'active',
        ovpn_services
    ))
    if not len(ovpn_services):
        print("No active OpenVPN services.")
        return {}
    result = {}
    for service_name in ovpn_services:
        try:
            with open(os.path.join(ov_confs_dir, f"{service_name}.conf"), mode='r') as conf_file:
                conf_lines = conf_file.readlines()
                hostname = [line for line in conf_lines if line.startswith("server ")][0].split(' ')[1]
                port = [line for line in conf_lines if line.startswith("port ")][0].split(' ')[1]
                host_port = f"{hostname}:{port}".strip()
            status_path: str = f"/var/log/openvpn-{service_name}.log"
            if not os.path.isfile(status_path):
                raise Exception(f"Status log for service '{service_name}' does not exists at path: {status_path}")
            with open(status_path, mode='r') as log_file:
                clients = [client.split(',') for client in log_file.readlines() if client.startswith('CLIENT_LIST')]
            clients = {
                remove_openvpn_client_port(client[2]): convert_openvpn_datetime_to_epoch(client[7])
                for client in clients
            }
            result[host_port] = clients
        except Exception as parse_ovpn_service_exc:
            print(f"Warning: {parse_ovpn_service_exc}")
    return result


if __name__ == '__main__':
    try:
        ovpn_result = update_openvpn_services()
    except Exception as exception:
        print(f"Warning: {exception}")
        ovpn_result = {}
    body: dict = {
        "openvpn": {
            key: len(value)
            for key, value in ovpn_result.items()
        },
    }
    print(json.dumps(body, indent=2))
