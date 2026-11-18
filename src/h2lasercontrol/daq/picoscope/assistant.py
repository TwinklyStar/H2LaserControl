"""ROOT writer and ADC helpers, copied from H2LaserDAQ `src/picoDAQAssistant.py` (F8c: the
ROOT format must not change). Changes: prints -> logging; unused StreamManager and
NumpyRingQueue dropped; flake fixes only."""
import logging
import queue
import re
import threading
from datetime import datetime
from typing import ClassVar

import awkward as ak
import numpy as np
import uproot

_log = logging.getLogger(__name__)

class RootManager:

    _scalar_dtypes: ClassVar[dict] = {
        "int8":  np.int8,
        "int16":  np.int16,
        "int32":  np.int32,
        "float32": np.float32,
        "float64": np.float64,
    }

    def __init__(self, filename, runN, sample_num, add_channels=("A","B","C","D"), chunk_size=1000):
        self._runN = runN
        self._file = uproot.recreate(filename)
        self._filename = filename
        self._chConfig = []
        if (sample_num>0):
            self._branch = {
                "Run": "int32", 
                "WaveN": "int32",
                "Year": "int16", 
                "Month": "int8", 
                "Day": "int8", 
                "Hour": "int8", 
                "Min": "int8", 
                "Sec": "int8",
                "ms": "int16", 
                "nTime": "int32",
                "Time": f"{sample_num} * float32"}
            for ch in add_channels:
                self._branch[f"Ch{ch}"] = f"{sample_num} * float32"
                self._chConfig.append(f"Ch{ch}")

            self._fixed_length = True
        else:
            self._branch = {
                "Run": "int32", 
                "WaveN": "int32",
                "Year": "int16", 
                "Month": "int8", 
                "Day": "int8", 
                "Hour": "int8", 
                "Min": "int8", 
                "Sec": "int8",
                "ms": "int16", 
                "Time": "var * float32"}
            for ch in add_channels:
                self._branch[f"Ch{ch}"] = "var * float32"
                self._chConfig.append(f"Ch{ch}")

            self._fixed_length = False

        self._tree = self._file.mktree("rawWave", self._branch)
        self._chunk_size = max(1, chunk_size)
        self._sample_num = sample_num

        self._wave_n = 0

        self._buffer_n = 3
        if self._fixed_length:
            self._buffers = [{} for i in range(self._buffer_n)]
            for name, typ in self._branch.items():
                match = re.match(r"^.*\* (.*)", typ)    # Any patter starts with '...* ', and capture rest of parts as data type
                for i in range(self._buffer_n):
                    if match:
                        self._buffers[i][name] = np.empty((self._chunk_size, self._sample_num), dtype=match.group(1))
                    else:
                        self._buffers[i][name] = []
        else:
            self._buffers = [{k: [] for k in self._branch} for i in range(self._buffer_n)]  # Buffer
        self._buffer_now = 0
        self._n_buffered = [0 for i in range(self._buffer_n)]

        self.max_queued = 2
        self._stop_queue = object()

    def fill(self, **wave):
        now = datetime.now()
        self._buffers[self._buffer_now]["Year"].append(now.year)
        self._buffers[self._buffer_now]["Month"].append(now.month)
        self._buffers[self._buffer_now]["Day"].append(now.day)
        self._buffers[self._buffer_now]["Hour"].append(now.hour)
        self._buffers[self._buffer_now]["Min"].append(now.minute)
        self._buffers[self._buffer_now]["Sec"].append(now.second)
        self._buffers[self._buffer_now]["ms"].append(now.microsecond // 1000)
        self._buffers[self._buffer_now]["Run"].append(self._runN)
        self._buffers[self._buffer_now]["WaveN"].append(self._wave_n)
        
        required_key = self._chConfig[:]
        required_key.append("Time")
        missing = required_key - wave.keys()
        if missing:
            _log.error("Missing branch %s when filling the tree", missing)
            return

        if self._fixed_length:
            self._buffers[self._buffer_now]["nTime"].append(self._sample_num)
            for k, v in wave.items():
                self._buffers[self._buffer_now][k][self._n_buffered[self._buffer_now], :] = v
        else:
            for k, v in wave.items():
                self._buffers[self._buffer_now][k].append(v)
        self._n_buffered[self._buffer_now] += 1
        if self._n_buffered[self._buffer_now] >= self._chunk_size:
            # print("Batch full")
            buffer_old = self._buffer_now
            self._q.put(buffer_old)
            self._buffer_now = (self._buffer_now + 1) % self._buffer_n

        self._wave_n += 1

    def start_thread(self):
        self._q = queue.Queue(self.max_queued)
        self._thd = threading.Thread(target=self.background_loop, daemon=True)
        self._thd.start()
        _log.debug("ROOT writer thread started: %s", self._filename)
        
    def background_loop(self):
        while True:
            buffer_n = self._q.get()
            if buffer_n is self._stop_queue:
                _log.debug("ROOT writer thread stopped: %s", self._filename)
                break
            # print("Catch buffer ", buffer_n, " from queue")
            self.flush(buffer_n)
            self._q.task_done()

    def flush(self, buffer_n):
        if self._n_buffered[buffer_n] == 0:
            return
        out = {}
        for name, typ in self._branch.items():
            data = self._buffers[buffer_n][name]

            # Variable-length (jagged) branch: "var * <type>"
            if re.match(r"^.*\*", typ):
                if self._fixed_length:
                    out[name] = data[:self._n_buffered[buffer_n]]
                else:
                    out[name] = ak.Array(data)
            else:
                # Scalar branch: cast to the right dtype
                base = typ.strip()
                if base not in self._scalar_dtypes:
                    raise ValueError(f"Unsupported scalar type '{base}' for branch '{name}'")
                out[name] = np.asarray(data, dtype=self._scalar_dtypes[base])

        # print("Conversion takes: ", time.time()-time_start, " secs")
        # Extend once per flush
        self._tree.extend(out)

        # Clear buffers
        if self._fixed_length:
            for name, typ in self._branch.items():
                match = re.match(r"^.*\* (.*)", typ)    # Any patter starts with '...* ', and capture rest of parts as data type
                if match:
                    self._buffers[buffer_n][name] = np.empty((self._chunk_size, self._sample_num), dtype=match.group(1))
                else:
                    self._buffers[buffer_n][name] = []
        else:
            self._buffers[buffer_n] = {k: [] for k in self._branch}
        self._n_buffered[buffer_n] = 0
        # print("Extend takes: ", time.time()-time_start, " secs")

    def close(self):
        self._q.join()                  # Wait for all buffer filled to tree
        self.flush(self._buffer_now)    # Flush remaining data
        self._q.put(self._stop_queue)
        self._file.close()

    def getName(self):
        return self._filename

def fastAdc2mV(bufferADC, range, maxADC, offset=0):
    """ 
        adc2mc(
                c_short_Array           bufferADC
                int                     range
                c_int32                 maxADC
                )
               
        Takes a buffer of raw adc count values and converts it into millivolts
    """

    channelInputRanges = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000]
    vRange = channelInputRanges[range]
    bufferV = bufferADC.astype('int64') * vRange / maxADC.value - offset
    
    return bufferV

def getVoltageRange(range, offset=0):
    channelInputRanges = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000]
    return [-channelInputRanges[range]-offset, channelInputRanges[range]-offset]

def extTrigmV2Adc(voltage_mv):
    return int(voltage_mv / 1000. / 5 * 32767)


