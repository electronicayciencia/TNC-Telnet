"""
WA8DED TNC AX.25 to Telnet emulator.

EA4BAO  2024/04/09

Commands arrive via named pipe from a virtual machina COM port.


User mode format:
b'\x11' <- DC1 (prevents XOFF lockup)
b'\x18' <- CAN (clears out the garbage)
b'\x1b' <- ESC (command mode)
b'J'
b'H'
b'O'
b'S'
b'T'
b'1'
b'\r'   <- JHOST1 change to Host mode

Host mode format:
b'\x00' <- channel 00
b'\x01' <- command
b'\x01' <- length - 1
b'G'    <- Get
b'0'    <- Optional parameter (0: data, 1: link status)


See
 - doc/WA8DED_firm21.txt
 - doc/host_mode_guide.txt

"""

import sys
from channel import Channel
from monitor import Monitor


FILE = r'\\.\PIPE\tnc'

# Interface mode
MODE_TERM = 0  # terminal mode
MODE_HOST = 1  # host mode

# Output condition
COND_OK      = 0     # Success, nothing follows      short format (Nothing available)
COND_OKMSG   = 1     # Success, message follows      null-terminated format
COND_ERRMSG  = 2     # Failure, message follows      null-terminated format
COND_LNK     = 3     # Link status                   null-terminated format
COND_MON     = 4     # Monitor header/no info        null-terminated format
COND_MONHDR  = 5     # Monitor header/info           null-terminated format
COND_MONINF  = 6     # Monitor information           byte-count format
COND_CONINFO = 7     # Connected information         byte-count format

MSG_I = 0  # Message is data
MSG_S = 1  # Message is link status


class TNC():


    def __init__(self, file):
        
        self.channels = []
        self.max_connections = 4
        self.mode = MODE_TERM  # always start in terminal mode

        self.f = open(file, 'rb+', buffering=0)
        
        self.terminate = False
        
        self.channels = [None] * (self.max_connections + 1)
        self.init_monitor()
        self.init_channels()
        self.run()


    def init_monitor(self):
        """
        Initializes channel 0: monitor
        """
        self.channels[0] = Monitor()


    def init_channels(self):
        """
        Initializes channels
        """
        for i in range(0, self.max_connections):
            self.channels[i+1] = Channel()
            self.channels[i+1].start()


    ############################################################
    # TERMINAL MODE
    ############################################################
    def term_mode(self):
        """
        Switch from HOST to TERMINAL mode.
        """
        self.mode = MODE_TERM
        print("TNC in TERMINAL mode")


    def term_response(self, msg):
        """
        Send a response in terminal mode
        msg: message or b""
        """
        self.f.write(msg + b"\r\n")


    def term_cmd(self, cmd):
        """
        Execute terminal mode command and write the answer to the stream
        """
        if cmd == b"JHOST1":
            self.host_mode()
            self.host_response(0, COND_OK, b"")

        else:
            msg = b"INVALID COMMAND: %s" % cmd
            print(msg)
            self.term_response(msg)


    def term_read(self):
        """
        Read data or command from f in TERMINAL mode
        Return (i, buffer)
        i = 0 for data, 1 for commands
        """
        # Special characters in terminal mode
        CHR_CAN = b"\x18"  # cancel: clear the queue
        CHR_CR  = b"\x0d"  # cr: input commands
        CHR_ESC = b"\x1b"  # escape: switch from data to command mode

        buffer = b""
        is_command = 0

        while True:
            c = self.f.read(1)

            if c == CHR_CR:
                return (is_command, buffer)

            elif c == CHR_CAN:
                buffer = b""

            elif c == CHR_ESC:
                is_command = 1
                buffer = b""

            else:
                buffer = buffer + c



    ############################################################
    # HOST MODE
    ############################################################
    def host_mode(self):
        """
        Switch from TERMINAL to HOST mode.
        """
        self.mode = MODE_HOST
        print("TNC in HOST mode")


    def host_response(self, ch, cond, msg = b""):
        """
        Send a response in host mode
        cond: output condition
        msg: message or b""
        """
        if cond == COND_OK:
            m = b"%c%c" % (ch, cond)

        elif cond in [COND_ERRMSG, COND_OKMSG]:
            m = b"%c%c%s\0" % (ch, cond, msg)

        elif cond == COND_LNK:
            m = b"%c%c(%d) %s\0" % (ch, cond, ch, msg)

        elif cond == COND_CONINFO:
            m = b"%c%c%c%s" % (ch, cond, len(msg) - 1, msg)

        else:
            print("Host mode response type %d not implemented" % cond)
            return

        print(b"Response: %s" % m)
        
        self.f.write(m)


    def host_cmd(self, ch, cmd):
        """
        Execute host mode command and write the answer to the stream
        """
        c = cmd[0:1]
        args = cmd[1:].strip()
        
        # Check channel number
        if ch > self.max_connections:
            self.host_response(ch, COND_ERRMSG, b"INVALID CHANNEL NUMBER")
            return
        
        # Execute command
        if c == b"G": # G0  polling
            if args == b"0":
                (t, msg) = self.channels[ch].G(0)
            elif args == b"1":
                (t, msg) = self.channels[ch].G(1)
            else:
                (t, msg) = self.channels[ch].G()
            
            if not msg:
                self.host_response(ch, COND_OK)
            else:
                if t == MSG_S:
                    self.host_response(ch, COND_LNK, msg)
                else:
                    self.host_response(ch, COND_CONINFO, msg)
                
                
        elif c == b"C":  # C GP160  CQ callsing
            if args == b"":
                ans = self.channels[ch].C()
                if ans == None:
                    self.host_response(ch, COND_ERRMSG, b"CHANNEL NOT CONNECTED")
                else:
                    self.host_response(ch, COND_OKMSG, ans)
            else:
                self.channels[ch].C(args)    # todo: this may fail if connected
                self.host_response(ch, COND_OK)
        
        elif c == b"I":  # I NOCALL identification
            if args == b"":
                ans = self.channels[ch].I()
                self.host_response(ch, COND_OKMSG, ans)
            else:
                self.channels[ch].I(args)    # todo: this may fail if connected
                self.host_response(ch, COND_OK)
        
        elif c == b"M":  # MIUS Monitor Filter
            if args == b"":
                ans = self.channels[0].M()
                self.host_response(ch, COND_OKMSG, ans)
            else:
                self.channels[0].M(args)
                self.host_response(ch, COND_OK)

        elif c == b"Y":  # Y4 Max connections
            if args == b"":
                ans = self.max_connections
                self.host_response(ch, COND_OKMSG, ans)
            else:
                #self.max_connections = args  # not implemented
                self.host_response(ch, COND_OK)

        elif c == b"L":  # L LinkStatus
            ans = self.channels[ch].L()
            self.host_response(ch, COND_OKMSG, ans)

        elif c == b"D":  # D disconnect
            self.channels[ch].D()
            self.host_response(ch, COND_OK)

        elif c == b"J":  # JHOST0 disable host mode (exit)
            if args == b"HOST0":
                self.host_response(ch, COND_OK)
                self.term_mode()
                self.term_response(b"ok")
                self.terminate = True
            else:
                self.host_response(ch, COND_OK)

        elif c == b"U":  # U0 unattended mode
            self.host_response(ch, COND_OK)

        elif c == b"K":  # K 08.04.124 timestamp
            self.host_response(ch, COND_OK)

        elif c == b"@":  # @V0 Callsign validation disabled
            self.host_response(ch, COND_OK)

        elif c == b"H":  # H0 ??
            self.host_response(ch, COND_OK)

        else:
            print("Unknown command:", c, args)
            self.host_response(ch, COND_ERRMSG, b"INVALID COMMAND: %s" % c )


    def host_data(self, ch, data):
        """
        Transmit data in host mode
        """
        self.channels[ch].tx(data)
        self.host_response(ch, COND_OK)


    def host_read(self):
        """
        Read data or command from f in HOST mode
        Return (c, i, buffer)
        c = channel
        i = 0 for data, 1 for commands
        """
        c = ord(self.f.read(1))  # channel
        i = ord(self.f.read(1))  # infocmd
        l = ord(self.f.read(1))  # len - 1
        
        # Note read on pipes is not blocking
        buffer = b""
        while len(buffer) < l + 1:
            buffer += self.f.read(1)
        
        print(b"Command: %d %d %d '%s'" % (c,i,l,buffer))
        return (c, i, buffer)


    ############################################################
    # Main loop
    ############################################################
    def run(self):
        """
        Main read/execute loop
        """
        while self.terminate == False:
            if self.mode == MODE_TERM:
                (is_command, buffer) = self.term_read()

                if is_command:
                    self.term_cmd(buffer)

            else:
                (ch, is_command, buffer) = self.host_read()

                if is_command:
                    self.host_cmd(ch, buffer)
                else:
                    self.host_data(ch, buffer)


if __name__ == '__main__':
    t = TNC(FILE)
    t.run()

