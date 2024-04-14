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

MSG_MON_H  = 4  # Monitor header/no info
MSG_MON_HI = 5  # Monitor header/info
MSG_MON_I  = 6  # Monitor information


import os
import re
import socket
import errno
import sys
import threading
import json
from time import sleep


class Channel(threading.Thread):

    def __init__(self, ch, monitor, stafile,
                 verbose = 0, mycall = DEFAULT_CALLSIGN):

        threading.Thread.__init__(self, daemon=True)
        self.channel = ch      # my channel id
        self.monitor = monitor # to simulate monitor traffic
        self.stafile = stafile # file with known stations IP
        self.verbose = verbose # log level

        self.status = ST_DISC  # disconnected
        self.buffer_tx = b""   # nothing to send
        self.msgs = []         # link status msgs and data msgs must be in the same buffer
                               # because G command requieres them in chronological order

        self.station = None    # remote station to connect
        self.call = mycall     # callsign

        self.seq  = 0          # for fake monitor


    def run(self):
        """
        Main loop
        """

        # We need a loop due to non-blocking sockets operation
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

                        self._monitor("MySYN")

                        # WSAEWOULDBLOCK = first attempt
                        if errname in ["WSAEWOULDBLOCK", "EINPROGRESS"]:
                            self.status = ST_SETUP
                        else:
                            self.msgs.append([
                                MSG_S,
                                b"LINK FAILURE with %s: See terminal output" % self.station
                            ])
                            print("Unknown error '%s' while in status %d." % (errname, self.status))
                            self._monitor("ItsRST")
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
                            b"CONNECTED to %s via Internet" % self.station
                        ])
                        self._monitor("ItsSYNACK")

                # connection attempt failed
                else:
                    errname = errno.errorcode[err]
                    # connection refused
                    if errname == "WSAECONNREFUSED":
                        self.msgs.append([
                            MSG_S,
                            b"BUSY fm %s" % self.station
                        ])
                        self._monitor("ItsRST")
                    # timeout
                    elif errname == "WSAETIMEDOUT":
                        self._monitor("MyRST")
                        self.msgs.append([
                            MSG_S,
                            b"LINK FAILURE with %s" % self.station
                        ])
                    # unknown error
                    else:
                        self._monitor("ItsRST")
                        self.msgs.append([
                            MSG_S,
                            b"LINK FAILURE with %s" % self.station
                        ])
                        print("Unknown error '%s' while in status %d." % (errname, self.status))

                    self.station = None # force disconnect status


            # Connected
            elif self.status == ST_CONN:

                # There is data to send
                if len(self.buffer_tx) > 0:
                    try:
                        n = s.send(self.buffer_tx[0:MAX_PKTLEN])
                        self._monitor("MyPSH", self.buffer_tx[0:MAX_PKTLEN])
                    except ConnectionResetError:
                        self.msgs.append([
                            MSG_S,
                            b"LINK RESET fm %s" % self.station
                        ])
                        self._monitor("ItsRST")
                        self.station = None # force disconnect status

                    if n > 0:
                        self.buffer_tx = self.buffer_tx[n:]
                        self._monitor("ItsPSHACK")

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
                            self._monitor("ItsFIN")
                            self._monitor("MyFINACK")
                            self.station = None # force disconnect status

                        else:
                            if data:
                                # first packet nay be a Telnet negotiation
                                if data.startswith(b"\xff"):
                                    self._reply_telnet_negotiation(s, data)
                                else:
                                    self.msgs.append([MSG_I, data])
                                    self._monitor("ItsPSH", data)
                                    self._monitor("MyPSHACK")

                    # no data to read
                    except BlockingIOError:
                        data = b""

                    # link reset
                    except ConnectionResetError:
                        self.msgs.append([
                            MSG_S,
                            b"LINK RESET fm %s" % self.station
                        ])
                        self._monitor("ItsRST")
                        self.station = None # force disconnect status

            # Disconnect
            if not self.station:
                self.status = ST_DISC
                try:
                    s.close()
                except:
                    pass

            # loop delay
            sleep(0.01)


    def _reply_telnet_negotiation(self, sock, options):
        """
        Reply to a telnet negotiation. Won't comply with anything.
        """
        response = options
        response = response.replace(b'\xfc', b'\xfe') # Won't -> don't
        response = response.replace(b'\xfd', b'\xfc') # Do -> won't
        sock.send(response)

        if self.verbose > 0:
            print("Telnet negotiation: %s -> %s" % (list(options), list(response)))


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
            print("Cannot open stations file: %s" % e)
            return (False, False)

        for line in f:
            line = line.strip()
            if line.startswith('#'):
                continue

            (ssid, host, port) = re.split(r'\s+', line)

            if all([ssid, host, port]) and ssid.upper() == station:
                if self.verbose > 0:
                    print("Station %s address is %s %d" % (station, host, int(port)))
                return (host, int(port))

        return (False, False)


    def _monitor(self, t, i = None):
        """
        Simulate monitor events
        """
        me = self.call
        remote = self.station

        # Link setup
        if t == "MySYN":
            mtype = MSG_MON_H
            ftype = "U"
            msg   = b"fm %s to %s ctl SABM+" % (me, remote)

        elif t == "ItsSYNACK":
            mtype = MSG_MON_H
            ftype = "U"
            msg   = b"fm %s to %s ctl UA-" % (remote, me)

        elif t == "MyFIN":
            mtype = MSG_MON_H
            ftype = "U"
            msg   = b"fm %s to %s ctl DISC+" % (me, remote)

        elif t == "ItsFINACK":
            mtype = MSG_MON_H
            ftype = "U"
            msg   = b"fm %s to %s ctl UA-" % (remote, me)

        elif t == "ItsFIN":
            mtype = MSG_MON_H
            ftype = "U"
            msg   = b"fm %s to %s ctl DISC+" % (remote, me)

        elif t == "MyFINACK":
            mtype = MSG_MON_H
            ftype = "U"
            msg   = b"fm %s to %s ctl UA-" % (me, remote)

        elif t == "ItsRST":
            mtype = MSG_MON_H
            ftype = "U"
            msg   = b"fm %s to %s ctl DM-" % (remote, me)

        elif t == "MyRST":
            mtype = MSG_MON_H
            ftype = "U"
            msg   = b"fm %s to %s ctl DM-" % (me, remote)

        elif t == "MyPSH" and i:
            seq = self.seq
            nxt = (seq + 1) % 8
            mtype = MSG_MON_HI
            ftype = "I"
            msg   = b"fm %s to %s ctl I%d%d pid F0+" % (me, remote, nxt, seq)

        elif t == "ItsPSHACK":
            seq = self.seq
            nxt = (seq + 1) % 8
            mtype = MSG_MON_H
            ftype = "S"
            msg   = b"fm %s to %s ctl RR%d-" % (remote, me, nxt)
            self.seq = nxt

        elif t == "ItsPSH" and i:
            seq = self.seq
            nxt = (seq + 1) % 8
            mtype = MSG_MON_HI
            ftype = "I"
            msg   = b"fm %s to %s ctl I%d%d pid F0+" % (remote, me, nxt, seq)

        elif t == "MyPSHACK":
            seq = self.seq
            nxt = (seq + 1) % 8
            mtype = MSG_MON_H
            ftype = "S"
            msg   = b"fm %s to %s ctl RR%d-" % (me, remote, nxt)
            self.seq = nxt

        else:
            print("Warning: unknown monitor event '%s'" % t)
            return

        self.monitor.log(mtype, msg, ftype)

        if i:
            i = i.replace(b"\r\n", b"\r")
            self.monitor.log(MSG_MON_I, i, "I")


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
            self._monitor("MyFIN")
            self._monitor("ItsFINACK")
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
