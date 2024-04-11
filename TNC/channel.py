"""
AX.25 to Telnet emulator.

EA4BAO  2024/04/09

Channel interface with TCP sockets.
Asynchronous Telnet channel class working as a daemon Thread.

Usage:
    python -i channel.py
    >>> c.C(b"EA4BAO")
    >>> c.G()
    >>> c.tx(b"...")
"""



DEFAULT_CALLSIGN = b"NOCALL"

DEF_STA_FILE = "./stations.json"

MAX_PKTLEN = 254    # max data frame length
MAX_I_MSGS = 9      # max data frames to store in msgs buffer

# Link state
LNK_ST_DSC     =  0 # Disconnected
LNK_ST_LS      =  1 # Link Setup
LNK_ST_FR      =  2 # Frame Reject
LNK_ST_DR      =  3 # Disconnect Request
LNK_ST_I       =  4 # Information Transfer
LNK_ST_RFS     =  5 # Reject Frame Sent
LNK_ST_WA      =  6 # Waiting Acknowledgement
LNK_ST_DB      =  7 # Device Busy
LNK_ST_RDB     =  8 # Remote Device Busy
LNK_ST_BDB     =  9 # Both Devices Busy
LNK_ST_WA_DB   = 10 # Waiting Acknowledgement and Device Busy
LNK_ST_WA_RDB  = 11 # Waiting Acknowledgement and Remote Busy
LNK_ST_WA_BDB  = 12 # Waiting Acknowledgement and Both Devices Busy
LNK_ST_RFS_DB  = 13 # Reject Frame Sent and Device Busy
LNK_ST_RFS_RDB = 14 # Reject Frame Sent and Remote Busy
LNK_ST_RFS_BDB = 15 # Reject Frame Sent and Both Devices Busy

ST_DISC    = LNK_ST_DSC # disconnected
ST_SETUP   = LNK_ST_LS  # trying to connect
ST_CONN    = LNK_ST_I   # connected
ST_EXIT    = -1         # to finish the loop

MSG_I = 0  # Message is data
MSG_S = 1  # Message is link status

import os
import socket
import errno
import sys
import threading
import json
from time import sleep


class Channel(threading.Thread):

    def __init__(self, stafile = DEF_STA_FILE):
        threading.Thread.__init__(self, daemon=True)
        self.status = ST_DISC  # disconnected
        self.buffer_tx = b""   # nothing to send
        self.msgs = []         # link status msgs and data msgs must be in the same buffer
                               # because G command requieres them in chronological order

        self.station = None    # remote station to connect
        self.call = DEFAULT_CALLSIGN   # callsign

        self.stafile = stafile # file with known stations IP


    def run(self):
        """
        Main loop
        """
        while True:
        
            # Disconnected
            if self.status == ST_DISC:

                # Connect if we know the destination
                if self.station:

                    ipaddr = self._station2ip(self.station)

                    if not all(ipaddr):
                        self.msgs.append([
                            MSG_S,
                            b"LINK FAILURE with %s: Unknown station" % self.station
                        ])
                        self.station = None # force disconnect status

                    else:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.setblocking(False)

                        err = s.connect_ex(ipaddr)
                        errname = errno.errorcode[err]

                        # WSAEWOULDBLOCK = first attempt
                        if errname in ["WSAEWOULDBLOCK", "EINPROGRESS"]:
                            self.status = ST_SETUP
                        else:
                            self.msgs.append([
                                MSG_S,
                                b"LINK FAILURE with %s: See terminal output" % self.station
                            ])

                            print("Unknown error:", errname)
                            self.station = None # force disconnect status


            # Trying to connect
            elif self.status == ST_SETUP:
                err = s.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)

                # err = 0 both when it is still trying to connect
                # and also when it is successfully connected
                if err == 0:
                    err = s.connect_ex(ipaddr)
                    errname = errno.errorcode[err]

                    # trying to connect
                    if errname == "WSAEINVAL":
                        self.status == ST_SETUP

                    elif errname == "WSAEISCONN":
                        self.status = ST_CONN
                        self.msgs.append([
                            MSG_S,
                            b"CONNECTED to %s" % self.station
                        ])

                # connection attempt failed
                else:
                    errname = errno.errorcode[err]
                    if errname == "WSAECONNREFUSED":
                        self.msgs.append([
                            MSG_S,
                            b"BUSY fm %s" % self.station
                        ])

                    else:
                        self.msgs.append([
                            MSG_S,
                            b"LINK FAILURE with %s" % self.station
                        ])
                        print("Unknown error:", errname)

                    self.station = None # force disconnect status


            # Connected
            elif self.status == ST_CONN:

                # There is data to send
                if len(self.buffer_tx) > 0:
                    try:
                        n = s.send(self.buffer_tx[0:MAX_PKTLEN])
                    except ConnectionResetError:
                        self.msgs.append([
                            MSG_S,
                            b"LINK RESET fm %s" % self.station
                        ])
                        self.station = None # force disconnect status

                    if n > 0:
                        self.buffer_tx = self.buffer_tx[n:]

                # There is space to receive data
                if self._count_msgs(MSG_I) < MAX_I_MSGS:
                    try:
                        data = s.recv(MAX_PKTLEN)

                        # Socket is closed by the other end
                        # no exception but successfully read b""
                        if data == b"":
                            self.msgs.append([
                                MSG_S,
                                b"DISCONNECTED fm %s" % self.station
                            ])
                            self.station = None # force disconnect status

                        else:
                            # purge binary data (telnet protocol)
                            data = data.replace(b'\xff\xfc\x01', b'')
                            self.msgs.append([MSG_I, data])

                    # no data to read
                    except BlockingIOError:
                        data = b""

                    # link reset
                    except ConnectionResetError:
                        self.msgs.append([
                            MSG_S,
                            b"LINK RESET fm %s" % self.station
                        ])
                        self.station = None # force disconnect status

            # Disconnect
            if not self.station:
                self.status = ST_DISC
                try:
                    s.close()
                except:
                    pass


            sleep(0.1)


    def _station2ip(self, station):
        """
        Return ("ip", port) for a known station.
        Return (False, False) if the station's IP data is not known.
        """
        station = station.decode().upper() # station is bytes, but json is string
        
        try:
            with open(self.stafile) as f:
                stations = json.load(f)
        
        except Exception as e:
            print("Cannot open stations file:", e)
            stations = {}
        
        if station in stations:
            (host, port) = stations[station].split(":")
            return (host, int(port))
        else:
            return (False, False)


    def tx(self, data):
        """
        Append data to TX buffer.
        Data is a string of bytes
        May be thread unsafe.
        """
        self.buffer_tx += data


    def _count_msgs(self, t = ""):
        """
        Return the number of msgs of type t in the msgs buffer
        t = 0 for data, 1 for status, "" for any
        """
        if t == "":
            return len(self.msgs)
        else:
            return len([m for m in self.msgs if m[0] == t])


    def _get_msg(self, t = ""):
        """
        Get one of the link status messages in queue
        t = 0 for data, 1 for status, "" for any
        Return (type, message)
        Or (None, None)
        """
        if not self.msgs:
            return (None, None)
            
        if t == "":
            m = self.msgs.pop(0)
            return m

        else:
            for i in range(0, len(self.msgs)):
                m = self.msgs[i]
                if m[0] == t:
                    self.msgs.pop(i)
                    return m


    def C(self, station = None):
        """
        Set remote to connect
        station is a byte array.
        """
        if station:
            self.station = station.upper()
        else:
            return self.station


    def D(self):
        """
        Disconnect from a station
        """
        if self.status != ST_DISC:
            self.msgs.append([
                MSG_S,
                b"DISCONNECTED fm %s" % self.station
            ])
            self.station = None # force disconnect status


    def L(self):
        """
        Return info to the L command
        b"0 0 0 0 0 0"
        """
        return b"%d %d %d %d %d %d" %(
            self._count_msgs(MSG_S),                      # a = Number of link status messages not yet displayed
            self._count_msgs(MSG_I),                      # b = Number of receive frames not yet displayed
            int(len(self.buffer_tx) / MAX_PKTLEN + 0.5),  # c = Number of send frames not yet transmitted
            0,                                            # d = Number of transmitted frames not yet acknowledged
            0,                                            # e = Number of tries on current operation
            self.status                                   # f = Link state
        )


    def G(self, t = ""):
        """
        Poll the channel
        t = 0 : only information
        t = 1 : only link status messages
        t = "": any (in chronological order)
        Return (type, message)
        """
        return self._get_msg(t)


    def I(self, call = ""):
        """
        Change or get the channel callsign
        """
        if call:
            self.call = call
        else:
            return self.call


if __name__ == '__main__':
    c = Channel()
    c.start()
