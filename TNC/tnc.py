"""
TFPCX-Telnet: An AX.25 emulator for TCP connections.

EA4BAO  2024/04/09

TNC interface

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
"""

import threading
from time import sleep
from channel import Channel
from monitor import Monitor

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
MSG_MON_H  = 4  # Monitor header/no info
MSG_MON_HI = 5  # Monitor header/info
MSG_MON_I  = 6  # Monitor information

class TNC(threading.Thread):


    def __init__(self, f, stafile, verbose = 0, channels = 4, hostmode = False):
        """
        f: file handler to read/write (rb+)
        stafile: json with known stations IP
        verbose: log level verbosity
        channels: number of channels
        hostmode: start in host mode
        """
        threading.Thread.__init__(self, daemon=True)
        
        self.f = f
        self.verbose = verbose
        self.stafile = stafile
        self.max_connections = channels
        
        self.terminate = False

        if hostmode:
            self.host_mode()
        else:
            self.term_mode()

        self.channels = [None] * (self.max_connections + 1)
        self.init_monitor()
        self.init_channels()


    def init_monitor(self):
        """
        Initializes channel 0: monitor
        """
        self.channels[0] = Monitor(verbose = self.verbose)


    def init_channels(self):
        """
        Initializes channels
        """
        for i in range(0, self.max_connections):
            self.channels[i+1] = Channel(
                ch = i+1,
                monitor = self.channels[0],
                stafile = self.stafile,
                verbose = self.verbose
            )
            self.channels[i+1].start()


    ############################################################
    # TERMINAL MODE
    ############################################################
    def term_mode(self):
        """
        Switch from HOST to TERMINAL mode.
        """
        self.mode = MODE_TERM
        if self.verbose > 0:
            print("TNC in TERMINAL mode")


    def term_response(self, msg):
        """
        Write a response in terminal mode
        msg: message or b""
        """
        if self.verbose:
            print("Terminal resp: %s" % (msg))

        self.f.write(msg + b"\r\n")


    def term_cmd(self, cmd):
        """
        Execute terminal mode command and compose the answer
        """
        if cmd == b"JHOST1":
            self.host_mode()
            # no answer
            #self.term_response(b"OK")
            #self.host_response(0, COND_OK)

        else:
            msg = b"INVALID COMMAND: %s" % cmd
            print(msg)
            self.term_response(msg)


    def term_read(self):
        """
        Read data or command from f in TERMINAL mode
        Return (i, buffer)
        i = 0 for data, 1 for commands
        Echo the characters ir self.echo is enabled
        """
        # Special characters in terminal mode
        CHR_CAN = b"\x18"  # cancel: clear the queue
        CHR_CR  = b"\x0d"  # cr: input commands
        CHR_ESC = b"\x1b"  # escape: switch from data to command mode

        buffer = b""
        is_command = 0

        while True:
            c = self.f.read(1)

            if c == CHR_ESC:
                is_command = 1
                buffer = b""
                
            elif c == CHR_CAN:
                buffer = b""

            elif c == CHR_CR:
                if self.verbose:
                    print("Terminal read: %d %s" % (is_command, buffer))
                return (is_command, buffer)

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
        if self.verbose > 0:
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

        elif cond == COND_MON:
            m = m = b"%c%c%s\0" % (ch, cond, msg)

        elif cond == COND_MONHDR:
            m = m = b"%c%c%s\0" % (ch, cond, msg)

        elif cond == COND_MONINF:
            m = b"%c%c%c%s" % (ch, cond, len(msg) - 1, msg)

        else:
            print("Host mode response type %d not implemented" % cond)
            return

        # Print response only if command level worth it
        if self.verbose >= self.cmdlevel:
            print("Response: %s" % m)

        self.cmdlevel = 0

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
                elif t == MSG_I:
                    self.host_response(ch, COND_CONINFO, msg)
                elif t == MSG_MON_H:
                    self.host_response(ch, COND_MON, msg)
                elif t == MSG_MON_HI:
                    self.host_response(ch, COND_MONHDR, msg)
                elif t == MSG_MON_I:
                    self.host_response(ch, COND_MONINF, msg)
                else:
                    print("Unknown packet type: %d", t)


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
                ans = b"%d" % self.max_connections
                self.host_response(ch, COND_OKMSG, ans)
            else:
                n = int(args)
                if (n <= self.max_connections):
                    self.host_response(ch, COND_OK)
                else:
                    print("Requested %d channels, %d available." % (n, self.max_connections))
                    self.host_response(
                        ch, 
                        COND_ERRMSG, 
                        b"INVALID COMMAND: TNC started with %d channels." % self.max_connections)

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
            else:
                self.host_response(ch, COND_OK)

        elif c == b"U":  # U0 unattended mode
            self.host_response(ch, COND_OK)

        elif c == b"K":  # K 08.04.124 timestamp
            self.host_response(ch, COND_OK)

        elif c == b"Z":  # Z0 disable flow control
            self.host_response(ch, COND_OK)

        elif c == b"@":  # @V0 Callsign validation disabled
            if args.startswith(b"B"):    # @B display free buffers
                self.host_response(ch, COND_OKMSG, b"512")
            else:
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

        # Determine the verbosity level por the command and its response
        if buffer[0:1] in [b"G", b"L", b"@"]:
            self.cmdlevel = 2
        else:
            self.cmdlevel = 1

        if self.verbose >= self.cmdlevel:
            print("Cmd: Ch=%d C/I=%d Len=%d %s" % (c,i,l+1,buffer))
        
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
