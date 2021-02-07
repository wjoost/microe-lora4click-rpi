#!/usr/bin/python3
#
# Get informations from module

import argparse
import sys
import time
from lora4click import MipotGpio, MipotSerial, MipotCmd

lora_frequencies = [
    868100000,
    868300000,
    868500000,
    867100000,
    867300000,
    867500000,
    867700000,
    867900000
    ]


def check_hex_string(str, len_wanted):
    if len(str) != len_wanted:
        return False

    for c in str:
        if ((c < '0') or (c > '9')) and ((c < 'a') or (c > 'f')) and ((c < 'A') or (c > 'F')):
            return False

    return True


def show_hex(msg, data: bytes) -> None:
    print(msg, end='')
    for v in data:
        print(' %02X' % (v), end='')
    print('')

    return


def main() -> int:

    # Argument handling
    parser = argparse.ArgumentParser(description='Configure Mipot 32001353 module')
    parser.add_argument('-j', '--joineui', help='Join EUI', required=True)
    parser.add_argument('-k', '--key', help='Application key', required=True)
    args = parser.parse_args()

    if not check_hex_string(args.joineui, 16):
        print('Bad join EUI', file=sys.stderr)
        return 1

    if not check_hex_string(args.key, 32):
        print('Bad application key', file=sys.stderr)
        return 1

    # Init
    gpio = MipotGpio()
    serial = MipotSerial(gpio)
    cmd = MipotCmd(gpio, serial)

    # Reset config
    cmd.factory_reset()

    # Set DataIndicateTimeout to 1ms
    cmd.eeprom_write(0x80, b'\x01')

    # Write application key
    cmd.set_app_key(bytes.fromhex(args.key))

    # Write Join/AppEUI
    cmd.eeprom_write(0x08, bytes.fromhex(args.joineui)[::-1])

    # Main powered
    cmd.set_battery_level(0)

    # Configure channels
    i = 3
    while i < len(lora_frequencies):
        cmd.set_ch_parameters(i, lora_frequencies[i], 0, 5, True)
        i += 1
    cmd.set_ch_parameters(i, 868800000, 7, 7, True)

    # Initiate join
    result = cmd.join(1)
    if result != 0:
        print('Join command failed with code %d' % result, file=sys.stderr)
        return 1
    print('Join in progress')

    # Wait for join indication
    now = time.clock_gettime(time.CLOCK_MONOTONIC)
    timeout = now + 120

    got_join = False
    while not got_join and timeout > now:
        indication = cmd.get_parsed_indication(int(timeout - now))
        if indication is not None and indication['indication'] == 'join':
            got_join = True
            break
        now = time.clock_gettime(time.CLOCK_MONOTONIC)

    if not got_join:
        print('Timeout while waiting for join indication', file=sys.stderr)
        cmd.reset()
        return 1

    if indication['success']:
        print('Join OK')
    else:
        print('Join failed', file=sys.stderr)
        return 1

    # Done
    return 0


if __name__ == "__main__":
    exit(main())
