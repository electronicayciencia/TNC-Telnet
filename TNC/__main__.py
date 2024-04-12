"""
TFPCX-Telnet: An AX.25 emulator for TCP connections.

EA4BAO  2024/04/09

Commands arrive via named pipe from a virtual machine COM port.

See doc/ directory.

"""

import sys
import argparse
from time import sleep
from tnc import TNC


DEFAULT_FILE = r'\\.\PIPE\tnc'
DEF_STA_FILE = "./tnc/stations.json"
DESCRIPTION = 'An AX.25 emulator for TCP connections'

parser = argparse.ArgumentParser(
    description = DESCRIPTION
)


parser.add_argument(
    '--file',
    required = False,
    default = DEFAULT_FILE,
    help='Device file or named pipe to interact with MS-DOS box (default: %s).' % DEFAULT_FILE
)

parser.add_argument(
    '--stations',
    metavar = "FILE",
    required = False,
    default = DEF_STA_FILE,
    help='JSON file with IP address and TCP port of known stations (default: %s).' % DEF_STA_FILE
)

parser.add_argument(
    '-v',
    required = False,
    default = 0,
    action="count",
    help='Display commands and responses.'
)


args = parser.parse_args()

print(DESCRIPTION)
print("Reading from '%s'..." % args.file)
if args.v > 0:
    print("Verbose level: %d" % args.v)

t = TNC(
    file = args.file, 
    stafile = args.stations,
    verbose = args.v
)
t.start()

try:
    while True:
        input("Press Ctrl+C to quit.\n")
except KeyboardInterrupt:
    pass

print("Bye! 73")

sys.exit()
