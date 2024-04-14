"""
TNC-Telnet: An AX.25 emulator for TCP connections.

EA4BAO  2024/04/09

Commands arrive via named pipe from a virtual machine COM port.

See doc/ directory.

"""

import sys
import argparse
from time import sleep
from tnc import TNC


DEFAULT_CALL = "NOCALL"
DEFAULT_FILE = r'\\.\PIPE\tnc'
DEF_STA_FILE = "./tnc/stations.json"
DESCRIPTION = 'An AX.25 emulator for TCP connections'

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


args = parser.parse_args()

print(DESCRIPTION)
print("Channels available: %d" % args.ch)
if args.v > 0:
    print("Verbose level: %d" % args.v)
print("Reading from '%s'..." % args.file)


f = open(args.file, 'rb+', buffering=0)

t = TNC(
    f,
    stafile  = args.stations,
    verbose  = args.v,
    hostmode = args.jhost1,
    channels = args.ch,
    mycall   = args.mycall.encode("ascii")
)
t.start()

try:
    while True:
        input("Press Ctrl+C to quit.\n")
except KeyboardInterrupt:
    pass

print("Bye! 73")

sys.exit()
