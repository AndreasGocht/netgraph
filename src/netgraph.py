import nethogs
import threading
import signal
import configparser
import argparse
import logging
import datetime
import queue
import time

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


class Influx(threading.Thread):
    def __init__(self, url, org, bucket, token, write_buffer_size = 1) -> None:
        super().__init__()

        self.url = url
        self.org = org
        self.bucket = bucket
        self.write_buffer_size = write_buffer_size

        self.client = influxdb_client.InfluxDBClient(
            url=url,
            token=token,
            org=org
        )

        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.write_buffer = []

        self.queue = queue.Queue()
        self.running = True

    def send_data_point(self, elem):
        self.queue.put(elem)

    def stop(self):
        self.running = False
        self.join()

    def run(self):
        while self.running:
            try:
                if len(self.write_buffer) >= self.write_buffer_size:
                    try:
                        self.write_api.write(bucket=self.bucket, org=self.org, record=self.write_buffer)
                        self.write_buffer = []
                        logging.debug(f"send to Influx")
                    except NewConnectionError as e:
                        logging.error("Can't reach Influx, try again later")
                        time.sleep(1)
                        continue

                try:
                    elem = self.queue.get(timeout=1)
                    logging.debug(f"Got elem")
                except queue.Empty:
                    continue
                self.write_buffer.append(elem)
                logging.debug(f"write buffer len: {len(self.write_buffer)} of {self.write_buffer_size}")

            except Exception as e:
                logging.exception("Some Exception occured, keep running")
                

class NetGraphPcap(regular_timer.RegularTimer, metaclass=Singleton):
    def __init__(self, database: Influx, sample_rate: datetime.timedelta = datetime.timedelta(milliseconds=1000)):
        super().__init__(sample_rate)
        
        logging.info(f"set sample_rate to {sample_rate}")
        
        self.database = database
        self.last_reported = nethogs.nethogs_packet_stats()

    def update(self):
        logging.debug("doing update")

        current_stats = nethogs.nethogs_packet_stats()
        time = datetime.datetime.utcnow()
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
            self.database.send_data_point(p)
        self.last_reported = current_stats
    
    def stop(self):
        self.cancel()
    

class NetGraphData(metaclass=Singleton):
    def __init__(self, database: Influx, devices: list[str], geo_database: geo_data.GeoData, sample_rate: datetime.timedelta = datetime.timedelta(milliseconds=100)):
        self.database = database     

        self.pcap_to_ms = int(sample_rate/datetime.timedelta(milliseconds=1))
        logging.info(f"set pcap_to_ms (sampling rate) to {self.pcap_to_ms} ms")
        self.devices = devices
        self.geo = geo_data.GeoData(geo_database)

    def callback(self, action: int, record: nethogs.NethogsMonitorRecord) -> None:
        time = datetime.datetime.utcnow()
        name = record.name
        logging.debug("received callback")

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

        self.database.send_data_point(p)

    def start(self):
        logging.info(f"Start Nethogs on the following devices: {self.devices}")
        self.nethogs_th = threading.Thread(
            target=nethogs.nethogsmonitor_loop_devices, args=(
                self.callback, "", self.devices, False, self.pcap_to_ms))
        self.nethogs_th.start()

    def stop(self):
        nethogs.nethogsmonitor_breakloop()
        self.nethogs_th.join()


def main():
    import os

    logging.basicConfig(
        level=os.getenv('LOG_LEVEL', 'INFO').upper()
        )
    
    parser = argparse.ArgumentParser(prog='NetGraph')
    parser.add_argument('-c', '--config', required=True)
    args = parser.parse_args()

    config = configparser.ConfigParser()
    ret = config.read(args.config)
    
    if len(ret) == 0:
        raise RuntimeError("Can't find config file")
    else:
        logging.info("loaded config file")

    device_list = config.get("net_graph", "interfaces")
    devices = [item.strip() for item in device_list.split(",")]
    
    geo_database = config.get("net_graph", "geo_database")

    logging.info("setup Influx connection")
    database = Influx(config.get("influx_db", "url"),
                      config.get("influx_db", "org"),
                      config.get("influx_db", "bucket"),
                      config.get("influx_db", "token"), 
                      config.getint("influx_db", "write_buffer_size", fallback = 1)
                      )
    database.start()

    logging.info("Configuring netgraph")
    sample_rate = datetime.timedelta(milliseconds=config.getint("net_graph", "sampling_rate_ms", fallback=100))
    net_graph_data = NetGraphData(database, devices, geo_database, sample_rate)
    net_graph_pcap = NetGraphPcap(database, sample_rate)

    logging.info("Starting netgraph")
    net_graph_data.start()
    net_graph_pcap.start()

    def signal_handler(sig, frame):
        if sig == signal.SIGTERM or sig == signal.SIGINT:
            net_graph_data.stop()
            net_graph_pcap.stop()
            database.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.sigwait([signal.SIGTERM, signal.SIGINT])

if __name__ == '__main__':
    main()
