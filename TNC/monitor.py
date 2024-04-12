"""
TFPCX-Telnet: An AX.25 emulator for TCP connections.

EA4BAO  2024/04/09

Monitor channel
"""

import os
import sys

DEFAULT_CALLSIGN = b"NOCALL"
DEFAULT_FILTER = b"N"

MAX_PKTLEN = 254    # max data frame length
MAX_I_MSGS = 9      # max data frames to store in msgs buffer

MSG_I = 0  # Message is data
MSG_S = 1  # Message is link status

MSG_MON_H  = 4  # Monitor header/no info
MSG_MON_HI = 5  # Monitor header/info
MSG_MON_I  = 6  # Monitor information


class Monitor():

    def __init__(self, verbose = 0):

        self.msgs = []  # link status msgs and data msgs must be in the same buffer
                        # because G command requieres them in chronological order
        self.call    = DEFAULT_CALLSIGN   # callsign
        self.mfilter = DEFAULT_FILTER     # Monitor filter
        self.station = DEFAULT_CALLSIGN   # CQ callsign


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
        Get one of the messages in queue
        Or (None, None)
        TODO: can't select between msg types
        """
        if not self.msgs:
            return (None, None)

        m = self.msgs.pop(0)
        return m


    def C(self, station = b""):
        """
        Set CQ callsign
        station is a byte array.
        """
        if station:
            self.station = station.upper()
        else:
            return self.station


    def L(self):
        """
        Return info to the L command
        b"0 0"
        """
        return b"%d %d" %(
            self._count_msgs(MSG_S),                      # a = Number of link status messages not yet displayed
            self._count_msgs(MSG_I)                       # b = Number of receive frames not yet displayed
        )


    def G(self, t = ""):
        """
        Poll the channel
        Arg is an integger.
        t = 0 : only information
        t = 1 : only link status messages
        t = "": both (in chronological order)
        """
        return self._get_msg(t)


    def I(self, call = ""):
        """
        Change or get the global callsign
        """
        if call:
            self.call = call
        else:
            return self.call


    def M(self, mfilter = ""):
        """
        Change or get the monitor filter
        """
        if mfilter:
            self.mfilter = mfilter
        else:
            return self.mfilter


    def log(self, t, msg, f):
        """
        Add a monitor event
        t: packet type (header, header+info, info)
        msg: message bytes
        f: frame type (ISU)
        """
        self.msgs.append([t, msg])
        #self.msgs.append([MSG_MON_H,  b"fm %s to %s ctl SABM" % (fm, to)])
        #self.msgs.append([MSG_MON_HI, b"fm %s to %s ctl I%02X pid %02X" % (fm, to, 5, 14)])
        #self.msgs.append([MSG_MON_I,  b"Hi\r"])



if __name__ == '__main__':
    m = Monitor()
