"""
TNC-Telnet: An AX.25 emulator for TCP connections.

EA4BAO  2024/04/09

Commands arrive via named pipe from a virtual machine COM port.

See doc/ directory.

"""

import re
import sys
import logging
import argparse
from time import sleep
from tnc import TNC

DEFAULT_CALL = "NOCALL"
DEFAULT_FILE = r'\\.\PIPE\tnc'
DEF_STA_FILE = "stations.txt"
NAME = "TNCTelnet"
VERSION = 1.0
DESCRIPTION = 'An AX.25 emulator for TCP connections'

logger = logging.getLogger(NAME)

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
        help     = 'Display commands and responses. Multiple times show more info.'
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
        logger.error("Cannot open stations file: %s" % e)
        return

    n = 0
    for num, line in enumerate(f, 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        try:
            (ssid, host, port, *extra) = re.split(r'\s+', line)
            n = n + 1
        except:
            logger.warning("Invalid line %d in stations file." % num)

    return n


def addLoggingLevel(levelName, levelNum, methodName=None):
    """
    From: https://stackoverflow.com/questions/2183233/how-to-add-a-custom-loglevel-to-pythons-logging-facility/35804945#35804945

    Comprehensively adds a new logging level to the `logging` module and the
    currently configured logging class.

    `levelName` becomes an attribute of the `logging` module with the value
    `levelNum`. `methodName` becomes a convenience method for both `logging`
    itself and the class returned by `logging.getLoggerClass()` (usually just
    `logging.Logger`). If `methodName` is not specified, `levelName.lower()` is
    used.

    To avoid accidental clobberings of existing attributes, this method will
    raise an `AttributeError` if the level name is already an attribute of the
    `logging` module or if the method name is already present

    Example
    -------
    >>> addLoggingLevel('TRACE', logging.DEBUG - 5)
    >>> logging.getLogger(__name__).setLevel("TRACE")
    >>> logging.getLogger(__name__).trace('that worked')
    >>> logging.trace('so did this')
    >>> logging.TRACE
    5

    """
    if not methodName:
        methodName = levelName.lower()

    if hasattr(logging, levelName):
       raise AttributeError('{} already defined in logging module'.format(levelName))
    if hasattr(logging, methodName):
       raise AttributeError('{} already defined in logging module'.format(methodName))
    if hasattr(logging.getLoggerClass(), methodName):
       raise AttributeError('{} already defined in logger class'.format(methodName))

    # This method was inspired by the answers to Stack Overflow post
    # http://stackoverflow.com/q/2183233/2988730, especially
    # http://stackoverflow.com/a/13638084/2988730
    def logForLevel(self, message, *args, **kwargs):
        if self.isEnabledFor(levelNum):
            self._log(levelNum, message, args, **kwargs)
    def logToRoot(message, *args, **kwargs):
        logging.log(levelNum, message, *args, **kwargs)

    logging.addLevelName(levelNum, levelName)
    setattr(logging, levelName, levelNum)
    setattr(logging.getLoggerClass(), methodName, logForLevel)
    setattr(logging, methodName, logToRoot)


def setup_log(verbosity):
    """
    Configure the logging options for the project.
    """

    addLoggingLevel('TRACE', logging.DEBUG - 5)

    loglevel = logging.WARNING if verbosity <= 0 else \
               logging.INFO    if verbosity == 1 else \
               logging.DEBUG   if verbosity == 2 else \
               logging.TRACE   # for repetitive polling commands

    logging.basicConfig(format='%(levelname)s: %(message)s', level=loglevel)


if __name__ == '__main__':
    print(NAME, VERSION)
    args = parse_args()
    setup_log(args.v)

    # Check stations file
    n = known_stations(args.stations)
    if n:
        logger.info("Known stations: %d" % n)
    else:
        logger.critical("No known stations. Edit %s and try again." % args.stations)
        sys.exit()

    # Open named pipe
    try:
        f = open(args.file, 'rb+', buffering=0)
    except Exception as e:
        logger.critical("Cannot open I/O file: '%s'" % e)
        sys.exit()

    logger.info("Reading from '%s'..." % args.file)

    # Start the TNC
    logger.info("Channels available: %d" % args.ch)

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
