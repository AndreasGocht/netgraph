import nethogs
import threading
import signal
import configparser
import argparse
import logging
import geo_data

import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class NetGraphData(metaclass=Singleton):
    def __init__(self, influx_config, devices, geo_database):
        self.influx_url = influx_config["url"]
        self.influx_org = influx_config["org"]
        self.influx_bucket = influx_config["bucket"]
        self.pcap_to_ms = 100
        self.devices = devices
        self.geo = geo_data.GeoData(geo_database)

        token = influx_config["token"]

        self.client = influxdb_client.InfluxDBClient(
            url=self.influx_url,
            token=token,
            org=self.influx_org
        )
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)

        return

    def callback(self, action: int, record: nethogs.NethogsMonitorRecord) -> None:
        name = record.name

        if record.pid == 0:
            name = self.geo.check_and_translate(name)

        try:
            p = influxdb_client.Point("network_data").tag("name", name).field("sent_bytes", record.sent_bytes)
            self.write_api.write(bucket=self.influx_bucket, org=self.influx_org, record=p)

            p = influxdb_client.Point("network_data").tag("name", name).field("recv_bytes", record.recv_bytes)
            self.write_api.write(bucket=self.influx_bucket, org=self.influx_org, record=p)

            p = influxdb_client.Point("network_data").tag("name", name).field("sent_kbs", record.sent_kbs)
            self.write_api.write(bucket=self.influx_bucket, org=self.influx_org, record=p)

            p = influxdb_client.Point("network_data").tag("name", name).field("recv_kbs", record.recv_kbs)
            self.write_api.write(bucket=self.influx_bucket, org=self.influx_org, record=p)

            p = influxdb_client.Point("network_data").tag(
                "name", name).field(
                "sent_bytes_last", record.sent_bytes_last)
            self.write_api.write(bucket=self.influx_bucket, org=self.influx_org, record=p)

            p = influxdb_client.Point("network_data").tag(
                "name", name).field(
                "recv_bytes_last", record.recv_bytes_last)
            self.write_api.write(bucket=self.influx_bucket, org=self.influx_org, record=p)

        except Exception as e:
            logging.exception(e)
            signal.raise_signal(signal.SIGTERM)
        return

    def start(self):
        self.nethogs_th = threading.Thread(
            target=nethogs.nethogsmonitor_loop_devices, args=(
                self.callback, "", self.devices, False, self.pcap_to_ms))
        self.nethogs_th.start()

    def stop(self):
        nethogs.nethogsmonitor_breakloop()
        self.nethogs_th.join()


def main():
    # if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='NetGraph')
    parser.add_argument('-c', '--config')
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read(args.config)

    devices = [item.strip() for item in config["net_graph"]["interfaces"].split(",")]
    geo_database = config["net_graph"].get("geo_database")

    net_graph = NetGraphData(config["influx_db"], devices, geo_database)
    net_graph.start()

    def signal_handler(sig, frame):
        if sig == signal.SIGTERM or sig == signal.SIGINT:
            net_graph.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.sigwait([signal.SIGTERM, signal.SIGINT])
