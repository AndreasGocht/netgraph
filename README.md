# Netgraph

Netgraph allows you to monitor which applications use how much bandwidth. The Nethogs lib does the essential monitoring while the data is pushed to Influx and can then be visualised with Graphana.

## Install

I am still looking for a good idea for packaging. If you have any ideas, I welcome a PR or an Issue. Therefore, the installation process is still entirely manual.

```
# install nethogs
git clone git@github.com:raboof/nethogs.git
cd nethogs
sudo DEB_PYTHON_INSTALL_LAYOUT=deb_system pip install .

# install netgraph itself
cd ..
git clone git@github.com:AndreasGocht/netgraph.git
cd netgraph
sudo DEB_PYTHON_INSTALL_LAYOUT=deb_system pip install .

# create config directory and copy the config file (you might want to adjust the config file)
sudo mkdir /etc/netgraph/
sudo cp config.sample.ini /etc/netgraph/config.ini

# deploy systemd file (maybe adjust them, depending on where you run your Influx)
sudo cp netgraph.service /etc/systemd/system/netgraph.service
sudo systemctl enable netgraph.service
sudo systemctl start netgraph.service
```

Please adjust `config.ini` and `netgraph.service` according to your needs.

If there are any questions, please open an issue.

## Suggested Influx Querrys for Graphana

The following Influx query assumes that the bucket in which you save the data is called `netgraph`.

Accumulated data send/received/total:
```
from(bucket:"netgraph")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => (r._measurement == "network_data" and (r._field == "sent_bytes_last" or r._field == "recv_bytes_last")))
  |> keep(columns: ["_time","_value", "_field"])
  |> aggregateWindow(every: 1h, fn: sum, createEmpty: true)
  |> group(columns: ["_time","_field"])
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> group(columns: [])
  |> map(fn: (r) => ({r with total_sum: (r.sent_bytes_last + r.recv_bytes_last)}))
```

Packet stats
```
from(bucket:"netgraph")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => (r._measurement == "packet_stats"))
  |> aggregateWindow(every: 1h, fn: sum, createEmpty: true)
```

Received data per process
```
from(bucket:"netgraph")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => (r._measurement == "network_data" and (r._field == "recv_bytes_last")))
  |> keep(columns: ["_time","_value", "name"])
  |> aggregateWindow(every: 1h, fn: sum, createEmpty: true)
```

Send data per process
```
from(bucket:"netgraph")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => (r._measurement == "network_data" and (r._field == "sent_bytes_last")))
  |> keep(columns: ["_time","_value", "name"])
  |> aggregateWindow(every: 1h, fn: sum, createEmpty: true)
```
