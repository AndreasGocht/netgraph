import geoip2.database
import re
import subprocess
import logging

ipv4 = "([\\d.]*):\\d*-([\\d.]*):\\d*"
ipv6 = "([\\da-f:]*):\\d*-([\\da-f:]*):\\d*"
ip_reg = re.compile(f'{ipv4}|{ipv6}')


class GeoData:
    def __init__(self, database_location="./GeoLite2-Country.mmdb", local_ips=None):        
        if local_ips:
            self.local_ips = local_ips
        else:
            self.local_ips = subprocess.check_output(['hostname', '--all-ip-addresses']).decode().split()
        
        try:
            self.reader = geoip2.database.Reader(database_location)
            self.enable_geodatabase = True
        except FileNotFoundError:
            self.enable_geodatabase = False
            logging.error("Geo Database not found, running without")


    def check_and_translate(self, process_name):
        result = []
        ip_addresses = re.match(ip_reg, process_name)
        if ip_addresses:
            for addr in ip_addresses.groups():
                if addr in self.local_ips:
                    result.append("local")
                elif addr and self.enable_geodatabase:
                    try:
                        response = self.reader.country(addr)
                        result.append(response.country.name)
                    except geoip2.errors.AddressNotFoundError:
                        result.append("AddressNotFoundError")
                elif addr and not self.enable_geodatabase:
                    result = addr
                elif addr is None:
                    pass
                else:
                    result.append("unkonw Error")
                    logging.error(f"Val in addr \"{addr}\", Initial Name \"{process_name}\"")
            return f"{result[0]}-{result[1]}"
        else:
            return process_name


if __name__ == "__main__":
    geo_data = GeoData("../tmp/GeoLite2-Country.mmdb", ["144.76.107.201"])
    print(geo_data.check_and_translate("144.76.107.201:443-91.66.150.251:50016"))
