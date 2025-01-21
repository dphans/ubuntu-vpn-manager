import json
import os.path
import subprocess
from datetime import datetime, timedelta
from typing import List, Optional

import requests
from dotenv import load_dotenv

wg_confs_dir: str = "/etc/amnezia/amneziawg"
ov_confs_dir: str = "/etc/openvpn/server"

load_dotenv(dotenv_path='script.env')
data_dir: str = os.path.join(os.path.dirname(__file__), 'data')
result_file_path: str = os.path.join(data_dir, 'status_updater.json')
api_url: str = os.environ.get('API_URL', '')
public_ip: str = os.environ.get('PUBLIC_HOSTNAME', None)


def read_last_results(default: dict) -> dict:
    if os.path.isfile(result_file_path):
        with open(result_file_path, mode='r') as json_file:
            return json.loads(json_file.read())
    return default


def write_results(result: dict):
    if os.path.isfile(result_file_path):
        os.remove(result_file_path)
    with open(result_file_path, mode='w') as file:
        file.write(json.dumps(result))


def check_results_changes(old: dict, new: dict) -> bool:
    old_servers_clients = old.get("ov", {})
    new_servers_clients = new.get("ov", {})
    for server, clients in old_servers_clients.items():
        old_count = len(clients)
        new_count = len(new_servers_clients.get(server, {}))
        if old_count != new_count:
            return True
    old_servers_clients = old.get("wg", {})
    new_servers_clients = new.get("wg", {})
    for server, clients in old_servers_clients.items():
        old_count = len(clients)
        new_count = len(new_servers_clients.get(server, {}))
        if old_count != new_count:
            return True
    return False


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


def update_openvpn_services(public_ip: str) -> dict:
    ovpn_services: List[str] = []
    if os.path.isdir(ov_confs_dir):
        ovpn_services = [
            f.replace('.conf', '')
            for f in os.listdir(ov_confs_dir)
            if f.endswith(".conf") and not f.startswith("client_")
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
                port = [line for line in conf_lines if line.startswith("port ")][0].split(' ')[1]
                host_port = f"{public_ip}:{port}".strip()
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


def parse_wg_handshake_time(handshake_str, now) -> Optional[str]:
    try:
        components = [comp.strip() for comp in handshake_str.replace('ago', '').split(",")]
        days, hours, minutes, seconds = 0, 0, 0, 0
        for component in components:
            if 'day' in component:
                days = int(component.split(' ')[0])
            elif 'hour' in component:
                hours = int(component.split(' ')[0])
            elif 'min' in component:
                minutes = int(component.split(' ')[0])
            elif 'sec' in component:
                seconds = int(component.split(' ')[0])
        delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
        if delta.total_seconds() >= 130:
            return None  # wg handshake every 120 seconds, greater or equal to 130 mean offline.
        target_datetime = now - delta
        target_datetime = target_datetime + timedelta(hours=7)
        return target_datetime.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as parse_handshake_exc:
        print(f"Warning: {parse_handshake_exc}")
        return None


def update_wg_services(public_ip: str) -> dict:
    wg_services: List[str] = []
    if os.path.isdir(wg_confs_dir):
        wg_services = [
            f.replace('.conf', '')
            for f in os.listdir(wg_confs_dir)
            if f.endswith(".conf")
        ]
    wg_services = list(filter(
        lambda name: bash_command(["systemctl", "is-active", f"awg-quick@{name}.service"]) == 'active',
        wg_services
    ))
    if not len(wg_services):
        print("No active Wireguard services.")
        return {}
    result = {}
    now = datetime.now()
    for service_name in wg_services:
        try:
            with open(os.path.join(wg_confs_dir, f"{service_name}.conf"), mode='r') as conf_file:
                conf_lines = conf_file.readlines()
                port = [line for line in conf_lines if line.startswith("ListenPort")][0].split('=')[1].strip()
                host_port = f"{public_ip}:{port}".strip()
            result[host_port] = {}

            wg_show: str = bash_command(["wg", "show", service_name])
            peers = [[l.strip() for l in line.split('\n') if l.strip()] for line in wg_show.split("peer: ")[1:]]
            for peer_infos in peers:
                latest_handshake_lines = [line for line in peer_infos if line.startswith('latest handshake: ')]
                if not len(latest_handshake_lines):
                    continue
                latest_handshake = ''.join(latest_handshake_lines[0].split(':')[1:]).strip()
                handshake_date = parse_wg_handshake_time(latest_handshake, now=now)
                if not handshake_date:
                    continue
                peer_public_key = peer_infos[0]
                result[host_port][peer_public_key] = handshake_date
        except Exception as parse_wg_service_exc:
            print(f"Warning: {parse_wg_service_exc}")
    return result


def get_public_ipv4() -> str:
    if type(public_ip) is str and len(public_ip):
        return public_ip
    return bash_command(['curl', 'ifconfig.me'])


def main(compare_last_results: bool = False):
    if not api_url:
        print("Failed to fetch API_URL, missing .env file?")

    vps_ip = get_public_ipv4()
    if not vps_ip:
        print("Warning: Cannot get public IP")
        return

    try:
        ovpn_result = update_openvpn_services(public_ip=vps_ip)
    except Exception as exception:
        print(f"Warning: {exception}")
        ovpn_result = {}
    try:
        wg_result = update_wg_services(public_ip=vps_ip)
    except Exception as exception:
        print(f"Warning: {exception}")
        wg_result = {}

    if compare_last_results:
        # Collect statuses and save to 'status_updater.json' file
        os.makedirs(data_dir, exist_ok=True)
        last_result: dict = read_last_results(default={"ov": {}, "wg": {}})

        new_result = {"ov": ovpn_result, "wg": wg_result}
        write_results(result=new_result)

        has_changes = check_results_changes(last_result, new_result)
        if not has_changes:
            print("No changes, no need to update API")
            return

    body: dict = {
        "ov": {
            key: len(value)
            for key, value in ovpn_result.items()
        },
        "wg": {
            key: len(value)
            for key, value in wg_result.items()
        },
    }
    response = requests.post(
        url=f"{api_url}/feature-vpn/mobile-app-vpns/status-updater/",
        json=body,
    )
    print(f"Sent to API with response code: {response.status_code}")
    if response.status_code >= 500:
        print(response.content.decode('utf-8'))
        print(json.dumps(body))


if __name__ == '__main__':
    main()
