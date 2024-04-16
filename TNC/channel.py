"""
TNC-Telnet: An AX.25 emulator for TCP connections.

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
import re
import socket
import errno
import sys
import threading
import logging
from time import sleep

logger = logging.getLogger(__name__)

class Channel(threading.Thread):

    def __init__(self, ch, monitor, stafile,
                 verbose = 0, mycall = DEFAULT_CALLSIGN):

        global logger  # to change the name once started
        logger = logging.getLogger("channel-%d" % ch)

        threading.Thread.__init__(self, daemon=True)
        self.channel = ch      # my channel id
        self.monitor = monitor # to simulate monitor traffic
        self.stafile = stafile # file with known stations IP
        self.verbose = verbose # log level

        self.status = ST_DISC  # disconnected
        self.buffer_tx = b""   # nothing to send
        self.msgs = []         # link status msgs and data msgs must be in the same buffer
                               # because G command requieres them in chronological order

        self.remote = None    # remote station to connect
        self.me     = mycall     # callsign

        self.seq  = 0          # sequence, for fake monitor
        self.nxt  = 1          # next sequence, for fake monitor


    def run(self):
        """
        Main loop
        """
        logger.debug("Channel %d started" % self.channel)

        # We need a loop due to non-blocking sockets operation
        while True:

            # Disconnected
            if self.status == ST_DISC:

                # Connect if we know the destination
                if self.remote:

                    ipaddr = self._station2ip(self.remote)

                    if not all(ipaddr):
                        self.msgs.append([
                            MSG_S,
                            b"LINK FAILURE with %s: Unknown station" % self.remote
                        ])
                        self.remote = None # force disconnect status

                    else:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.setblocking(False)

                        try:
                            err = s.connect_ex(ipaddr)
                        except socket.gaierror:
                            self.msgs.append([
                                MSG_S,
                                b"LINK FAILURE with %s: Domain resolution failed" % self.remote
                            ])
                            self.remote = None
                            continue

                        errname = errno.errorcode[err]

                        self.monitor.log("SABM", self.me, self.remote)

                        # WSAEWOULDBLOCK = first attempt
                        if errname in ["WSAEWOULDBLOCK", "EINPROGRESS"]:
                            self.status = ST_SETUP
                        else:
                            self.monitor.log("DM", self.remote, self.me)
                            self.msgs.append([
                                MSG_S,
                                b"LINK FAILURE with %s: See terminal output" % self.remote
                            ])
                            logger.error("Socket error '%s' while in status %d." % (errname, self.status))
                            self.remote = None # force disconnect status


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
                        self.monitor.log("UA", self.remote, self.me)
                        self.msgs.append([
                            MSG_S,
                            b"CONNECTED to %s via Telnet" % self.remote
                        ])

                # connection attempt failed
                else:
                    errname = errno.errorcode[err]
                    # connection refused
                    if errname == "WSAECONNREFUSED":
                        self.monitor.log("DM", self.remote, self.me)
                        self.msgs.append([
                            MSG_S,
                            b"BUSY fm %s" % self.remote
                        ])
                    # timeout
                    elif errname == "WSAETIMEDOUT":
                        self.monitor.log("DM", self.me, self.remote)
                        self.msgs.append([
                            MSG_S,
                            b"LINK FAILURE with %s" % self.remote
                        ])
                    # unknown error
                    else:
                        self.monitor.log("DM", self.remote, self.me)
                        self.msgs.append([
                            MSG_S,
                            b"LINK FAILURE with %s" % self.remote
                        ])
                        logger.error("Socket error '%s' while in status %d." % (errname, self.status))

                    self.remote = None # force disconnect status


            # Connected
            elif self.status == ST_CONN:

                # There is data to send
                if len(self.buffer_tx) > 0:
                    self._socket_tx(s)

                # There is space to receive data
                if self._count_msgs(MSG_I) < MAX_I_MSGS:
                    self._socket_rx(s)


            # Disconnect
            if not self.remote:
                self.status = ST_DISC
                try:
                    s.close()
                except:
                    pass

            # loop delay
            sleep(0.01)


    def _socket_rx(self, s):
        """
        Try to receive data in a non-blocking way
        """
        try:
            data = s.recv(MAX_PKTLEN)

            # Socket is closed by the other end
            # no exception but successfully read b""
            if data == b"":
                self.monitor.log("DISC", self.remote, self.me)
                self.monitor.log("UA", self.me, self.remote)
                self.msgs.append([
                    MSG_S,
                    b"DISCONNECTED fm %s" % self.remote
                ])
                self.remote = None # force disconnect status

            else:
                if data:
                    # first packet may be a Telnet negotiation
                    if data.startswith(b"\xff"):
                        self._reply_telnet_negotiation(s, data)
                    else:
                        self.monitor.log(
                           "I", self.remote, self.me,
                           self.seq, self.nxt, data)
                        self.monitor.log("RR", self.me, self.remote, self.seq, self.nxt)
                        self._incr_seq()
                        self.msgs.append([MSG_I, data])

        # no data to read
        except BlockingIOError:
            pass

        # link reset
        except ConnectionResetError:
            self.monitor.log("DM", self.remote, self.me)
            self.msgs.append([
                MSG_S,
                b"LINK RESET fm %s" % self.remote
            ])
            self.remote = None # force disconnect status


    def _socket_tx(self, s):
        """
        Try to send data in a non-blocking way
        """
        try:
            n = s.send(self.buffer_tx[0:MAX_PKTLEN])
            self.monitor.log(
               "I", self.me, self.remote,
               self.seq, self.nxt,
               self.buffer_tx[0:MAX_PKTLEN])
        except ConnectionResetError:
            self.monitor.log("DM", self.remote, self.me)
            self.msgs.append([
                MSG_S,
                b"LINK RESET fm %s" % self.remote
            ])
            self.remote = None # force disconnect status

        if n > 0:
            self.monitor.log("RR", self.remote, self.me, self.seq, self.nxt)
            self._incr_seq()
            self.buffer_tx = self.buffer_tx[n:]


    def _reply_telnet_negotiation(self, sock, options):
        """
        Reply to a telnet negotiation. Won't comply with anything.
        """
        response = options
        response = response.replace(b'\xfc', b'\xfe') # Won't -> don't
        response = response.replace(b'\xfd', b'\xfc') # Do -> won't
        sock.send(response)

        logger.debug("Telnet negotiation: %s -> %s" % (list(options), list(response)))


    def _station2ip(self, station):
        """
        Return ("ip", port) for a known station.
        Return (False, False) if the station's IP data is not known.
        Format of the file is space separated:
        ssid     ip or host    port
        Lines starting with '#' are comments.
        """
        station = station.decode().upper().strip() # station is bytes

        try:
            f = open(self.stafile)
        except Exception as e:
            logger.error("Cannot open stations file: %s" % e)
            return (False, False)

        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            (ssid, host, port, *extra) = re.split(r'\s+', line)

            if all([ssid, host, port]) and ssid.upper() == station:
                logger.info("Station %s address is %s %d" % (station, host, int(port)))
                return (host, int(port))

        return (False, False)


    def _incr_seq(self):
        """
        Increase the fake sequence number
        """
        self.seq = self.nxt
        self.nxt = (self.seq + 1) % 8


    def _count_msgs(self, t = None):
        """
        Return the number of msgs of type t in the msgs buffer
        t = 0 for data, 1 for status, "" for any
        """
        if t == None:
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


    def tx(self, data):
        """
        Append data to TX buffer.
        Data is a string of bytes
        May be thread unsafe.
        """
        ## TODO: the addition of \n is needed only in some systems
        ## RX cluster needs it, F6FBB BBS does not.
        ## This should be an option in the station file.
        ## This could break binary transfers
        if data.endswith(b"\r"):
            data = data + b"\n"
        self.buffer_tx += data


    def C(self, station = None):
        """
        Set remote to connect
        station is a byte array.
        """
        if station:
            self.remote = station.upper()
        else:
            return self.remote


    def D(self):
        """
        Disconnect from a station
        """
        if self.status != ST_DISC:
            self.monitor.log("DISC", self.me, self.remote)
            self.monitor.log("UA", self.remote, self.me)
            self.msgs.append([
                MSG_S,
                b"DISCONNECTED fm %s" % self.remote
            ])
            self.remote = None # force disconnect status


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
            self.me = call
        else:
            return self.me


if __name__ == '__main__':
    c = Channel()
    c.start()
