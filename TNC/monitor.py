"""
AX.25 to Telnet emulator.

EA4BAO  2024/04/09

Monitor interface
"""

DEFAULT_CALLSIGN = b"NOCALL"
DEFAULT_FILTER = b"N"

MAX_PKTLEN = 254    # max data frame length
MAX_I_MSGS = 9      # max data frames to store in msgs buffer

MSG_I = 0  # Message is data
MSG_S = 1  # Message is link status

import os
import sys


class Monitor():

    def __init__(self):
        
        self.msgs = []  # link status msgs and data msgs must be in the same buffer
                        # because G command requieres them in chronological order
        self.call    = DEFAULT_CALLSIGN   # callsign
        self.mfilter = DEFAULT_FILTER     # Monitor filter
        self.station = DEFAULT_CALLSIGN   # CQ callsign

#    def add_frame(self, data):
#        """
#        Append data to TX buffer.
#        Data is a string of bytes
#        May be thread unsafe.
#        """
#        self.buffer_tx += data


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
        Or (None, None)
        """
        if not self.msgs:
            return (None, None)
            
        if t == "":
            m = self.msgs.pop(0)
            return m[1]

        else:
            for i in range(0, len(self.msgs)):
                m = self.msgs[i]
                if m[0] == t:
                    self.msgs.pop(i)
                    return m[1]


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




if __name__ == '__main__':
    m = Monitor()
