# Copy Vive Wireless log files and send statistics to InfluxDB
# Copyright 2020  Simon Arlott
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from tzlocal import get_localzone
import datetime
import pickle
import glob
import os
import re
import shutil
import socket
import sys
import time

hostname = socket.gethostname()
tz = get_localzone()
influxdb = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
influxdb.connect((sys.argv[1], int(sys.argv[2])))

log_filename_pattern = "HtcCU_*_*_*.txt"
re_log_line = re.compile(r"^\[(?P<datetime>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.(?P<millis>\d{3}) \S+ \S+ \S+ \S+\] (?P<message>.+)$")
re_temperature = re.compile(r"^M_Temperature=(?P<m>\d+), R_Temperature=(?P<r>\d+)$")
re_link_condition = re.compile(r".*Link Condition Change : peerSignalQuality = (?P<signal>\d+), performanceQuality = (?P<perf>\d+)$")
re_connection = re.compile(r"Connection Status set to \d+\s*\(CONNECTION_STATUS_(?P<status>.+)\)$")

def copy_logs():
	logs = os.path.join(os.environ["ProgramData"], "VIVE Wireless", "ConnectionUtility", "Log")

	for src_log in sorted(glob.glob(os.path.join(logs, log_filename_pattern))):
		dst_log = os.path.basename(src_log)

		if not os.path.exists(dst_log):
			print(f"Copy {src_log} to {dst_log}")
			shutil.copyfile(src_log, dst_log)
		else:
			src_len = os.stat(src_log).st_size
			dst_len = os.stat(dst_log).st_size

			if src_len > dst_len:
				print(f"Append {src_len - dst_len} from {src_log} to {dst_log}")
				with open(dst_log, "ab") as dst:
					with open(src_log, "rb") as src:
						src.seek(dst_len)
						dst.write(src.read())

def influx_message(series, values, ts):
	return f"{series},host={hostname} {values} {int(ts.timestamp())}{ts.microsecond:06}000\n".encode("utf-8")

def import_logs():
	logs = os.path.join(log_filename_pattern)

	if "last_file" not in state:
		state["last_file"] = datetime.datetime(1, 1, 1, tzinfo=datetime.timezone.utc)
	if "last_line" not in state:
		state["last_line"] = datetime.datetime(1, 1, 1, tzinfo=datetime.timezone.utc)

	for log in sorted(glob.glob(logs)):
		log_dt = tz.localize(datetime.datetime.strptime("_".join(log.split("_")[1:3]), "%Y%m%d_%H%M%S")).astimezone(datetime.timezone.utc)
		if log_dt < state["last_file"]:
			continue

		print(f"Importing {log}")
		with open(log, "rt", encoding="UTF-16LE") as f:
			for line in f:
				line_match = re_log_line.match(line)
				if not line_match:
					continue

				line_dt = tz.localize(datetime.datetime.strptime(line_match["datetime"], "%Y-%m-%d %H:%M:%S").replace(microsecond=int(line_match["millis"]) * 1000)).astimezone(datetime.timezone.utc)
				if line_dt < state["last_line"]:
					continue

				temp_match = re_temperature.match(line_match["message"])
				if temp_match:
					m = int(temp_match["m"])
					r = int(temp_match["r"])
					influxdb.send(influx_message("vive_wireless_temperature", f"m={m}i,r={r}i", line_dt))

				link_match = re_link_condition.match(line_match["message"])
				if link_match:
					signal = int(link_match["signal"])
					if signal == 255:
						signal = -1
					perf = int(link_match["perf"])
					if perf == 255:
						perf = -1
					influxdb.send(influx_message("vive_wireless_signal", f"peerSignalQuality={signal}i,performanceQuality={perf}i", line_dt))

				#conn_match = re_connection.match(line_match["message"])
				#if conn_match:
				#	status = conn_match["status"]
				#	influxdb.send(influx_message("vive_wireless_connection", f"status=\"{status}\"", line_dt))

				time.sleep(0.001)
				state["last_line"] = line_dt

		state["last_file"] = log_dt
		save_state()

def load_state():
	global state

	try:
		with open("state", "rb") as f:
			state = pickle.load(f)
	except FileNotFoundError:
		state = {}

def save_state():
	with open("state", "wb") as f:
		pickle.dump(state, f)

if __name__ == "__main__":
	load_state()
	copy_logs()
	import_logs()
