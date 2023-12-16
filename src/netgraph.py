import nethogs
import threading
import signal
import configparser
import argparse
import logging
import dataclasses
import datetime


import geo_data
import regular_timer

import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS
from urllib3.exceptions import NewConnectionError


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


@dataclasses.dataclass
class Influx:
    url: str
    org: str
    bucket: str
    write_api: influxdb_client.WriteApi = None

    def write(self, p: influxdb_client.Point):
        self.write_api.write(bucket=self.bucket, org=self.org, record=p)


class NetGraphPcap(regular_timer.RegularTimer):
    def __init__(self, influx: Influx, dt=datetime.timedelta(milliseconds=1000)):
        super().__init__(dt)
        self.influx = influx
        self.last_reported = nethogs.nethogs_packet_stats()
        self.data_write_buffer = []


    def collect_data(self):
        current_stats = nethogs.nethogs_packet_stats()
        time = datetime.datetime.utcnow()
        data_to_write = []
        for current, last in zip(current_stats, self.last_reported):
            if current.devicename != last.devicename:
                logging.error(f"devices do not match: {current.device_name} != {last.device_name}")
                continue
            p = influxdb_client.Point("packet_stats")
            p.tag("device_name", current.devicename)
            p.field("ps_recv", current.ps_recv - last.ps_recv)
            p.field("ps_drop", current.ps_drop - last.ps_drop)
            p.field("ps_ifdrop", current.ps_ifdrop - last.ps_ifdrop)
            p.time(time)
            data_to_write.append(p)
        self.last_reported = current_stats
        return data_to_write

    def send_data(self):
        while len(self.data_write_buffer) > 0:
            data = self.data_write_buffer.pop()
            try:
                self.influx.write(data)
            except NewConnectionError as e:
                self.data_write_buffer.append(data)
                logging.error("Can't reach Influx, try again later")
                break

    def update(self):
        try:
            data_to_write = self.collect_data()
            self.data_write_buffer.append(data_to_write)
            self.data_to_wirte = []
            self.send_data()
        except Exception as e:
            logging.exception("Some Exception occured")

        


class NetGraphData(regular_timer.RegularTimer, metaclass=Singleton):
    def __init__(self, influx_config, devices, geo_database, dt=datetime.timedelta(milliseconds=1000)):
        super().__init__(dt)        

        self.influx = Influx(influx_config["url"], influx_config["org"], influx_config["bucket"])
        self.pcap_to_ms = 100
        self.devices = devices
        self.geo = geo_data.GeoData(geo_database)
        self.pcap_stats = NetGraphPcap(self.influx)

        token = influx_config["token"]

        self.client = influxdb_client.InfluxDBClient(
            url=self.influx.url,
            token=token,
            org=self.influx.org
        )

        self.influx.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.data_write_buffer = []

        self.lock = threading.RLock()
        self.data_to_wirte = []

    def callback(self, action: int, record: nethogs.NethogsMonitorRecord) -> None:
        time = datetime.datetime.utcnow()
        name = record.name

        if record.pid == 0 and "-" in name:
            name = self.geo.check_and_translate(name)

        p = influxdb_client.Point("network_data")
        p.tag("name", name)
        p.tag("uid", record.uid)
        p.tag("device_name", record.device_name)
        p.field("pid", record.pid)
        p.field("sent_bytes", record.sent_bytes)
        p.field("recv_bytes", record.recv_bytes)
        p.field("sent_kbs", record.sent_kbs)
        p.field("recv_kbs", record.recv_kbs)
        p.field("sent_bytes_last", record.sent_bytes_last)
        p.field("recv_bytes_last", record.recv_bytes_last)
        p.time(time)

        with self.lock:
            self.data_to_wirte.append(p)



    def start(self):
        logging.info(f"Start Nethogs on the following devices: {self.devices}")
        self.nethogs_th = threading.Thread(
            target=nethogs.nethogsmonitor_loop_devices, args=(
                self.callback, "", self.devices, False, self.pcap_to_ms))
        self.nethogs_th.start()
        self.pcap_stats.start()
        super().start()

    def stop(self):
        nethogs.nethogsmonitor_breakloop()
        self.nethogs_th.join()
        self.pcap_stats.cancel()
        self.cancel()

    def send_data(self):
        send_packets = 0
        while len(self.data_write_buffer) > 0:
            data = self.data_write_buffer.pop()
            try:
                self.influx.write(data)
                send_packets += 1
            except NewConnectionError as e:
                self.data_write_buffer.append(data)
                logging.error("Can't reach Influx, try again later")
                break
        logging.debug(f"send {send_packets} data packets")
    
    def update(self):
        try:
            with self.lock:
                self.data_write_buffer.append(self.data_to_wirte)
                self.data_to_wirte = []
            self.send_data()
        except Exception as e:
            logging.exception("Some Exception occured")


def main():
    logging.basicConfig(level=logging.INFO)
    
    parser = argparse.ArgumentParser(prog='NetGraph')
    parser.add_argument('-c', '--config', required=True)
    args = parser.parse_args()

    config = configparser.ConfigParser()
    ret = config.read(args.config)
    
    if len(ret) == 0:
        raise RuntimeError("Can't find config file")
    else:
        logging.info("loaded config file")

    devices = [item.strip() for item in config["net_graph"]["interfaces"].split(",")]
    geo_database = config["net_graph"].get("geo_database")


    logging.info("Configuring netgraph")
    net_graph = NetGraphData(config["influx_db"], devices, geo_database)

    logging.info("Starting netgraph")
    net_graph.start()

    def signal_handler(sig, frame):
        if sig == signal.SIGTERM or sig == signal.SIGINT:
            net_graph.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.sigwait([signal.SIGTERM, signal.SIGINT])


if __name__ == '__main__':
    main()
