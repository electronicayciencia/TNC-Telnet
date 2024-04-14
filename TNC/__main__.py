"""
TNC-Telnet: An AX.25 emulator for TCP connections.

EA4BAO  2024/04/09

Commands arrive via named pipe from a virtual machine COM port.

See doc/ directory.

"""

import re
import sys
import argparse
from time import sleep
from tnc import TNC


DEFAULT_CALL = "NOCALL"
DEFAULT_FILE = r'\\.\PIPE\tnc'
DEF_STA_FILE = "stations.txt"
DESCRIPTION = 'An AX.25 emulator for TCP connections'

def parse_args():
    """
    Parse command line arguments
    """
    parser = argparse.ArgumentParser(
        description = DESCRIPTION
    )

    parser.add_argument(
        '--file',
        required = False,
        default  = DEFAULT_FILE,
        help     = 'Device file or named pipe to interact with MS-DOS box (default: %s).' % DEFAULT_FILE
    )

    parser.add_argument(
        '--stations',
        metavar  = "FILE",
        required = False,
        default = DEF_STA_FILE,
        help    = 'JSON file with IP address and TCP port of known stations (default: %s).' % DEF_STA_FILE
    )

    parser.add_argument(
        '--mycall',
        metavar  = "CALLSIGN",
        required = False,
        default = DEFAULT_CALL,
        help    = 'My callsign (default: %s).' % DEFAULT_CALL
    )

    parser.add_argument(
        '--jhost1',
        required = False,
        default  = 0,
        action   = "store_true",
        help     = 'Start TNC in host mode (default is start in terminal mode).'
    )

    parser.add_argument(
        '--ch',
        metavar  = "N",
        required = False,
        default  = 4,
        type     = int,
        help     = 'Number of channels (default is 4).'
    )

    parser.add_argument(
        '-v',
        required = False,
        default  = 0,
        action   = "count",
        help     = 'Display commands and responses. -vv show also TNC polling commands.'
    )

    return parser.parse_args()


def known_stations(file):
    """
    Check stations file.
    Return the number os known stations in the file.
    Format of the file is space separated:
    ssid     ip or host    port
    Lines starting with '#' are comments.
    """

    try:
        f = open(file)
    except Exception as e:
        print("Cannot open stations file: %s" % e)
        return

    n = 0
    for num, line in enumerate(f, 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        try:
            (ssid, host, port) = re.split(r'\s+', line)
            n = n + 1
        except:
            print("Invalid line %d in stations file." % num)

    return n


if __name__ == '__main__':

    args = parse_args()

    print(DESCRIPTION)
    print("Channels available: %d" % args.ch)

    if args.v > 0:
        print("Verbose level: %d" % args.v)


    # Pre-parse stations file
    n = known_stations(args.stations)
    if n:
        print("Known stations: %d" % n)
    else:
        print("No known stations. Edit %s and try again." % args.stations)
        sys.exit()


    # Open named pipe
    try:
        f = open(args.file, 'rb+', buffering=0)
    except Exception as e:
        print("Cannot open I/O file: '%s'" % e)
        sys.exit()

    print("Reading from '%s'..." % args.file)

    # Start the TNC
    t = TNC(
        f,
        stafile  = args.stations,
        verbose  = args.v,
        hostmode = args.jhost1,
        channels = args.ch,
        mycall   = args.mycall.encode("ascii")
    )
    t.start()

    # Main loop
    try:
        while True:
            input("Press Ctrl+C to quit.\n")
    except KeyboardInterrupt:
        pass

    print("Bye! 73")

    sys.exit()
