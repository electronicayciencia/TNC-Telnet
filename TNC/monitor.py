"""
TNC-Telnet: An AX.25 emulator for TCP connections.

EA4BAO  2024/04/09

Monitor channel
"""

DEFAULT_CALLSIGN = b"NOCALL"
DEFAULT_FILTER = b"N"

MAX_PKTLEN = 254    # max data frame length
MAX_MSGS = 10       # max number of frames to store in buffer

MSG_I = 0  # Message is data
MSG_S = 1  # Message is link status

MSG_MON_H  = 4  # Monitor header/no info
MSG_MON_HI = 5  # Monitor header/info
MSG_MON_I  = 6  # Monitor information


import os
import sys
import logging

logger = logging.getLogger(__name__)

class Monitor():

    def __init__(self, verbose = 0):

        self.msgs = []  # link status msgs and data msgs must be in the same buffer
                        # because G command requieres them in chronological order
        self.call    = DEFAULT_CALLSIGN   # callsign
        self.mfilter = DEFAULT_FILTER     # Monitor filter
        self.station = DEFAULT_CALLSIGN   # CQ callsign


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


    def D(self):
        """
        Dummy disconnect method.
        """
        pass


    def L(self):
        """
        Return info to the L command
        b"0 0"
        """
        return b"%d %d" %(
            0,                    # a = Number of link status messages not yet displayed
            self._count_msgs()    # b = Number of receive frames not yet displayed
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
            self.mfilter = mfilter.upper()
        else:
            return self.mfilter


    def log(self, ctl, src, dst, seq = None, nxt = None, i = None, c = True):
        """
        Compose an add a monitor event.
        Check if message buffer is full.
        Check the monitor filter.
        ctl: string, kind of frame (SABM, I, RR, UA, DISC or DM)
        src: bytes, source SSID
        dst: bytes, destination SSID
        seq: int, sequence number (0-7) (mandatory for numbered frames)
        nxt: int, next sequence number (mandatory for numbered frames)
        i:   bytes, information (mandatory for I frames)
        c:   bool, It is from a connected channel
        """
        if ctl == "SABM":
            uisc = b"U"
            msg = b"fm %s to %s ctl SABM+" % (src, dst)

        elif ctl == "DISC":
            uisc = b"U"
            msg = b"fm %s to %s ctl DISC+" % (src, dst)

        elif ctl == "UA":
            uisc = b"U"
            msg = b"fm %s to %s ctl UA-" % (src, dst)

        elif ctl == "DM":
            uisc = b"U"
            msg = b"fm %s to %s ctl DM-" % (src, dst)

        elif ctl == "RR":
            uisc = b"S"
            msg = b"fm %s to %s ctl RR%d-" % (src, dst, nxt)

        elif ctl == "I":
            uisc = b"I"
            msg = b"fm %s to %s ctl I%d%d pid F0+" % (src, dst, nxt, seq)

        else:
            logger.warning("Unknown frame type to monitor: %s" % ctl)

        # Monitor filter
        if uisc not in self.mfilter:
            return

        # Discard I frames if buffer is full.
        if uisc in [b"I"] and len(self.msgs) >= MAX_MSGS:
            logger.debug("Discarded monitor frame. Full buffer.")
            return

        # Add messages
        if ctl == "I":
            i = i.replace(b"\r\n", b"\r")
            self.msgs.append([MSG_MON_HI, msg])
            self.msgs.append([MSG_MON_I, i])
        else:
            self.msgs.append([MSG_MON_H, msg])


if __name__ == '__main__':
    m = Monitor()
