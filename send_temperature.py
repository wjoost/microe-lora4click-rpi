#!/usr/bin/python3
#
# Send SOC temperature using LoRaWAN module
#

import subprocess
import time
from lora4click import MipotGpio, MipotSerial, MipotCmd

from typing import Optional


def get_soc_temperature() -> Optional[float]:
    result = subprocess.run(['/usr/bin/vcgencmd', 'measure_temp'], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    tokens = result.stdout.split('=')
    if tokens[0] != 'temp':
        return None
    num_str = ''
    for c in tokens[1]:
        if c not in '0123456789.':
            break
        num_str += c
    return float(num_str)


def encode_temperature(temperature: float) -> bytes:
    if temperature < 0:
        temperature_scaled = int(temperature * 10 - 0.5)
    else:
        temperature_scaled = int(temperature * 10 + 0.5)
    return b'\x00\x67' + temperature_scaled.to_bytes(2, 'big', signed=True)


def joined() -> bool:
    # Already joined?
    status = cmd.get_activation_status()
    if status == 2:  # Joined
        return True

    if status == 3:  # MAC error
        cmd.reset()

    # Request OTAA join
    if status == 0:  # Not activated
        print('Requesting join')
        result = cmd.join(1)
        if result == 1:
            raise RuntimeError('Join failed because of an invalid parameter')

    # Wait for join indication
    print('Waiting for network join')
    got_join_indication = False
    now = time.clock_gettime(time.CLOCK_MONOTONIC)
    timeout = now + 300
    while not got_join_indication and timeout > now:
        join_indication = cmd.get_parsed_indication(timeout - now)
        if join_indication is not None and join_indication['indication'] == 'join':
            got_join_indication = True
            break
        now = time.clock_gettime(time.CLOCK_MONOTONIC)

    # No join indication?
    if not got_join_indication:
        print('Waiting for join indication timed out')
        return False

    if join_indication['success']:
        print('Join successfull')
    else:
        print('Join failed')

    # Joined=
    return join_indication['success']


def main() -> int:
    global cmd

    # Init LoRa
    gpio = MipotGpio()
    serial = MipotSerial(gpio)
    cmd = MipotCmd(gpio, serial)

    # Set power source info
    cmd.set_battery_level(0)

    # Loop
    interval_seconds = 300
    num_data_send = 0
    while True:
        # Joined to network?
        if joined():
            temperature = get_soc_temperature()
            payload = encode_temperature(temperature)
            result = cmd.tx_msg(payload, 1, False)
            if result != 0:
                print('Sending data failed with error code %s' % (result))
            else:
                num_data_send += 1
                # Wait for tx indication
                got_tx_indication = False
                while not got_tx_indication:
                    tx_indication = cmd.get_parsed_indication(60)
                    if tx_indication is None:
                        raise RuntimeError('Timeout while waiting for TX indication')
                    got_tx_indication = (tx_indication['indication'] == 'tx_msg_uncon')
                data_rate = tx_indication['data_rate']
                print('Sent temperature %f with a data rate of %d' % (temperature, data_rate))
                # Adjust rate we send out the temperature.
                # The airtime per sensor should not exceed 30 seconds per day
                # in the community network. However, the very first packets
                # will always be sent with a low data rate.
                if num_data_send > 4:
                    if data_rate >= 4:
                        new_interval_seconds = 300
                    elif data_rate == 3:
                        new_interval_seconds = 600
                    elif data_rate == 2:
                        new_interval_seconds = 1200
                    elif data_rate == 1:
                        new_interval_seconds = 1800
                    else:
                        new_interval_seconds = 3600
                    if interval_seconds != new_interval_seconds:
                        print('Adjusting interval to %d minutes' % (new_interval_seconds / 60))
                        interval_seconds = new_interval_seconds

        # Wait for any indication until the next value can be send
        now = time.clock_gettime(time.CLOCK_MONOTONIC)
        timeout = now + interval_seconds
        while timeout > now:
            indication = cmd.get_parsed_indication(timeout - now)
            if indication is not None:
                if indication['indication'] == 'rx_msg':
                    if indication['message_type'] == 0:
                        print('Got unconfirmed message from network')
                    elif indication['message_type'] == 1:
                        print('Got confirmed message from network')
                    elif indication['message_type'] == 2:
                        print('Got multicast message from network')
                    elif indication['message_type'] == 3:
                        print('Got proprietary message from network')
                    else:
                        print('Got message type %d from network' % (indication['message_type']))
                    print('  Receive window: %d' % (indication['slot']))
                    print('  Data rate: %d' % (indication['data_rate']))
                    print('  Received signal strength: %d dBm' % (indication['rssi_dbm']))
                    print('  Signal to noise ratio: %d dB' % (indication['snr_db']))
                    if indication['frame_pending']:
                        print('  More data available')
                    else:
                        print('  No more data available')
                    if indication['port'] is not None:
                        print('  Port: %d' % (indication['port']))
                    if indication['data'] is not None and len(indication['data']) > 0:
                        print('  Data:', end='')
                        for b in indication['data']:
                            print(' %02X' % (b), end='')
                        print('')
            now = time.clock_gettime(time.CLOCK_MONOTONIC)

    return 0


if __name__ == "__main__":
    exit(main())
