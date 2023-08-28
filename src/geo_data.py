import geoip2.database
import re
import subprocess
import logging

ipv4 = "([\\d.]*):\\d*-([\\d.]*):\\d*"
ipv6 = "([\\da-f:]*):\\d*-([\\da-f:]*):\\d*"
ip_reg = re.compile(f'{ipv4}|{ipv6}')


class GeoData:
    def __init__(self, database_location="./GeoLite2-Country.mmdb", local_ips=None):
        self.reader = geoip2.database.Reader(database_location)
        if local_ips:
            self.local_ips = local_ips
        else:
            self.local_ips = subprocess.check_output(['hostname', '--all-ip-addresses']).decode().split()

    def check_and_translate(self, process_name):
        result = []
        ip_addresses = re.match(ip_reg, process_name)
        if ip_addresses:
            for addr in ip_addresses.groups():
                if addr in self.local_ips:
                    result.append("local")
                elif addr:
                    try:
                        response = self.reader.country(addr)
                        result.append(response.country.name)
                    except geoip2.errors.AddressNotFoundError:
                        result.append("AddressNotFoundError")
                else:
                    result.append("unkonw Error")
                    logging.warn(f"Val in addr \"{addr}\"")
            return f"{result[0]}-{result[1]}"
        else:
            return process_name


if __name__ == "__main__":
    geo_data = GeoData("GeoLite2-Country_20230822/GeoLite2-Country.mmdb", ["144.76.107.201"])
    print(geo_data.check_and_translate("144.76.107.201:22-180.101.88.241:63649"))
