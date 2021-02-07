#!/usr/bin/python3
#
# Sample library for Mipot 32001353 module mounted
# on a Mikroe LoRa 4 Click board. The board itself
# is mounted on a raspberry pi using slot 1 off a
# PI 3 click shield
#

import gpiod
import queue
import serial
import time

from typing import Dict, Union, Optional, Tuple


def show_bytes(msg: str, data: bytes) -> None:
    print(msg, end='')
    for x in data:
        print('%02X ' % (x), end='')
    print()


# Class for handling GPIOs
class MipotGpio():
    # PIN settings
    _pin_configuration: Dict[str, Dict[str, Union[int, str]]] = {
        'reset': {
            'gpio': 5,
            'desc': 'MIPOT 32001353 NRST'
        },
        'data': {
            'gpio': 6,
            'desc': 'MIPOT 32001353 NDATA_INDICATE'
        },
        'wake': {
            'gpio': 8,
            'desc': 'MIPOT 32001353 NWAKE'
        }}
    _pin_configuration_chip = "0"

    def __init__(self) -> None:
        # Open GPIO chip
        self._gpio_chip = gpiod.Chip(self._pin_configuration_chip, gpiod.Chip.OPEN_BY_NUMBER)

        # Get reset GPIO
        self._gpio_reset = self._gpio_chip.get_line(self._pin_configuration['reset']['gpio'])
        self._gpio_reset.request(consumer=self._pin_configuration['reset']['desc'], type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])

        # Get wake GPIO
        self._gpio_wake = self._gpio_chip.get_line(self._pin_configuration['wake']['gpio'])
        self._gpio_wake.request(consumer=self._pin_configuration['wake']['desc'], type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])

        # Get data GPIO. Pull up/down not configurable by now.
        # Later module versions have gpiod.LINE_REQ_FLAG_PULL_UP and gpiod.LINE_REQ_FLAG_PULL_DOWN
        self._gpio_data = self._gpio_chip.get_line(self._pin_configuration['data']['gpio'])
        self._gpio_data.request(consumer=self._pin_configuration['data']['desc'], type=gpiod.LINE_REQ_DIR_IN, flags=gpiod.LINE_REQ_EV_FALLING_EDGE)

        # Reset the module
        self.sleep()
        self.reset()

    # Reset the module
    def reset(self) -> None:

        # Pull reset line down
        self._gpio_reset.set_value(0)

        # The minimal time NRST must be held down is not specified
        time.sleep(0.1)

        # Set reset line up
        self._gpio_reset.set_value(1)

        # Give module a lot of time.
        time.sleep(2)

        # Done
        return

    # Wake up the module
    def wakeup(self) -> None:

        # Pull NWAKE down
        self._gpio_wake.set_value(0)

        # Done
        return

    def sleep(self) -> None:
        # Pull NWAKE up
        self._gpio_wake.set_value(1)

        # Done
        return


# Handle serial communication
class MipotSerial():

    # UART to use
    _uart_device = '/dev/serial0'

    # Valid commands and indications
    _valid_commands = [
            0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36,
            0x40, 0x42, 0x43, 0x44, 0x45, 0x46, 0x4A, 0x4B,
            0x50, 0x51, 0x52, 0x53, 0x54, 0x55, 0x57, 0x58]

    _valid_indications = [
            0x41, 0x47, 0x48, 0x49]

    def __init__(self, gpios: MipotGpio) -> None:

        # Store GPIO object
        self._gpios = gpios

        # Open port
        self._uart = serial.Serial(port=self._uart_device, baudrate=115200, bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, rtscts=False, dsrdtr=False)

    def transmit(self, command: bytes) -> None:
        """ Transmit command to device.

        Args:
        - command (bytes): The command, without the preceding 0xAA and without checksum
        """

        # Sanity checks
        if len(command) < 2:
            raise ValueError('command too short')
        if len(command) != command[1] + 2:
            raise ValueError('command length does not match length byte in command')
        if command[0] not in self._valid_commands:
            raise ValueError('Invalid command')

        # Prepend 0xAA
        to_transmit = b'\xaa' + command

        # Calculate checksum
        checksum = 0
        for value in to_transmit:
            checksum += value

        checksum = ((checksum ^ 0xFF) + 1) & 0xFF

        # Append checksum
        to_transmit += bytes([checksum])

        # Wake module up
        self._gpios.wakeup()

        # Diagram in command reference says we should wait 1ms
        time.sleep(0.001)

        # Write out command
        self._uart.write(to_transmit)

        # Done
        return

    def receive(self, timeout_sec: float, expected_cmd_reply: Optional[int]) -> Tuple[bytes, bool]:
        """ Receives data from device.

        Args:
        - timeout_msec (int): Number of seconds to wait for data. May be fractions of a second but not zero.
        - expected_cmd_reply (int): The expected reply. After sending a command, it should be set to the expected reply. Can be None.

        Returns:
        - Either expected command reply or an indication
        - Boolean, True when an indication is returned

        Raises:
        - TimeoutError
        """

        # Sanity check.
        if timeout_sec <= 0:
            raise ValueError('Timeout cannot be less or equal zero')

        # Calculate timeout
        now = time.clock_gettime(time.CLOCK_MONOTONIC)
        timeout = now + timeout_sec

        # Checksum OK?
        checksum_ok = False
        while not checksum_ok:
            # Get start of a command
            got_command = False
            while not got_command:
                # Wait for sync byte
                now = time.clock_gettime(time.CLOCK_MONOTONIC)
                while timeout > now:
                    self._uart.timeout = timeout - now
                    sync_byte = self._uart.read(size=1)
                    if len(sync_byte) != 1:
                        raise TimeoutError('Waiting for sync byte timed out')
                    if sync_byte[0] == 0xAA:
                        break
                    now = time.clock_gettime(time.CLOCK_MONOTONIC)

                # Get command byte. 0xAA is not a valid command reply or indication.
                # Skip superfluous 0xAA bytes but resync to 0xAA on other
                # unexpected command-reply or indication codes.
                command_byte = bytes([0xAA])
                while command_byte[0] == 0xAA:
                    now = time.clock_gettime(time.CLOCK_MONOTONIC)
                    self._uart.timeout = timeout - now
                    command_byte = self._uart.read(size=1)
                    if len(command_byte) != 1:
                        raise TimeoutError('Waiting for command byte timed out')
                    if expected_cmd_reply is not None:
                        if command_byte[0] == expected_cmd_reply or command_byte[0] in self._valid_indications:
                            got_command = True
                            break
                    elif (command_byte[0] & 0x7F in self._valid_commands and command_byte[0] & 0x80 == 0x80) or command_byte[0] in self._valid_indications:
                        got_command = True
                        break

            # Get length byte
            now = time.clock_gettime(time.CLOCK_MONOTONIC)
            if now >= timeout:
                raise TimeoutError('Waiting for length byte timed out')
            self._uart.timeout = timeout - now
            length_byte = self._uart.read(size=1)
            if len(length_byte) == 0:
                raise TimeoutError('Waiting for length byte timed out')

            # Receive remaining bytes
            now = time.clock_gettime(time.CLOCK_MONOTONIC)
            if now >= timeout:
                raise TimeoutError('Timeout while reading remaining bytes')
            self._uart.timeout = timeout - now
            bytes_to_read = length_byte[0] + 1
            further_bytes = self._uart.read(bytes_to_read)
            if len(further_bytes) != bytes_to_read:
                raise TimeoutError('Timeout while reading remaining bytes')

            # Calculate checksum
            checksum = 0xAA + command_byte[0] + length_byte[0]
            for value in further_bytes:
                checksum += value

            # Checksum OK?
            checksum_ok = ((checksum & 0xFF) == 0)

        # Return result
        result = command_byte + length_byte + further_bytes[0:-1]
        return (result, command_byte[0] in self._valid_indications)


class MipotCmd():

    _tx_power_table = [20, 14, 11, 8, 5, 2]
    _lora_frequencies = [868100000, 868300000, 868500000, 867100000, 867300000, 867500000, 867700000, 867900000]

    def __init__(self, gpio: MipotGpio, serial: MipotSerial) -> None:
        self._gpio = gpio
        self._serial = serial
        self._indication_queue: queue.Queue = queue.Queue(32)

        # Not shure if this is needed. Channel list should be part of the JoinAccept send from network
        self._configure_frequencies()

    def _configure_frequencies(self) -> None:
        """ Enable frequencies in use by TTN """
        i = 3
        while i < len(self._lora_frequencies):
            self.set_ch_parameters(i, self._lora_frequencies[i], 0, 5, True)
            i += 1
        self.set_ch_parameters(i, 868800000, 7, 7, True)

    def _get_reply(self, command: int, expected_len: Optional[int], timeout_seconds: float) -> bytes:
        got_reply = False
        num_retries = 8
        while not got_reply and num_retries > 0:
            num_retries -= 1
            (data, is_indication) = self._serial.receive(timeout_seconds, command | 0x80)
            if is_indication:
                try:
                    self._indication_queue.put(data, block=False)
                except queue.Full:
                    pass
            elif expected_len is None or data[1] == expected_len:
                got_reply = True

        return data

    def get_indication(self, timeout_seconds: Optional[int]) -> Optional[bytes]:
        if self._indication_queue.empty():
            self._gpio.wakeup()
            try:
                (data, is_indication) = self._serial.receive(timeout_seconds, None)
            except TimeoutError:
                return None
            if not is_indication:
                raise RuntimeError('Got unexpected command reply 0x%02X' % (data[0]))
            return data
        else:
            return self._indication_queue.get(block=False)

    @staticmethod
    def parse_join_indication(indication: bytes) -> Dict[str, Union[str, bool]]:
        """ Parse a join indication
         args:
        - indication (bytes): A message confirmed indication

        returns dict with the following keys:
        - indication (str): 'tx_msg_con'
        - success (bool): True on success
        """

        if len(indication) != 3:
            raise ValueError('Wrong length for join indication')
        if indication[0] != 0x41:
            raise ValueError('Not a join indication')
        return {
                'indication': 'join',
                'success': (indication[2] == 0)
                }

    @classmethod
    def parse_tx_msg_confirmed_indication(cls, indication: bytes) -> Dict[str, Union[bool, int]]:
        """ Parse a transmit message confirmed indication

        args:
        - indication (bytes): A message confirmed indication

        returns dict with the following keys:
        - indication (str): 'tx_msg_con'
        - success (bool): True on success
        - data_rate (int): Data rate, 0=SF12/125kHz - 5=SF7/125kHz, 6=SF6/250kHz, 7=FSK/50kHz
        - tx_power_dbm (int): transmit power in dBm
        - acked (bool): True when acknowlege has been received
        - num_retries (int): Number of retries
        """

        if len(indication) != 7:
            raise ValueError('Wrong length for transmit message confirmed indication')
        if indication[0] != 0x47:
            raise ValueError('Not a transmit message confirmed indication')
        if indication[4] > 5:
            raise ValueError('Bad transmit power')

        return {
                'indication': 'tx_msg_con',
                'success': (indication[2] == 0x00),
                'data_rate': indication[3],
                'tx_power_dbm': cls._tx_power_table[indication[4]],
                'ack_received': (indication[5] == 0x01),
                'num_retries': indication[6]
                }

    @classmethod
    def parse_tx_msg_unconfirmed_indication(cls, indication: bytes) -> Dict[str, Union[bool, int]]:
        """ Parse a transmit message unconfirmed indication

        args:
        - indication (bytes): A message confirmed indication

        returns dict with the following keys:
        - indication (str): 'tx_msg_uncon'
        - success (bool): True on success
        - data_rate (int): Data rate, 0=SF12/125kHz - 5=SF7/125kHz, 6=SF7/250kHz, 7=FSK/50kHz
        - tx_power_dbm (int): transmit power in dBm

        """

        if len(indication) != 5:
            raise ValueError('Wrong length for transmit message unconfirmed indication')
        if indication[0] != 0x48:
            raise ValueError('Not a transmit message unconfirmed indication')
        if indication[4] > 5:
            raise ValueError('Bad transmit power')

        return {
                'indication': 'tx_msg_uncon',
                'success': (indication[2] == 0x00),
                'data_rate': indication[3],
                'tx_power_dbm': cls._tx_power_table[indication[4]]
                }

    @classmethod
    def parse_rx_msg_indication(cls, indication: bytes) -> Dict[str, Union[bool, int, Optional[bytes]]]:
        """ Parse a receive message indication

        args:
        - indication (bytes): A message confirmed indication

        returns dict with the following keys:
        - indication (str): 'rx_msg'
        - success (bool): Success if True
        - message_type (int): 0 = unconfirmed, 1 = confirmed, 2 = multicast, 3 = proprietary
        - multicast (bool): True when mulitcast
        - data_rate (int): Receive data rate
        - slot (int): Receive slot, 1 or 2
        - frame_pending (bool): The next downlink frame is pending
        - ack (bool): True when an ack has been received
        - rssi_dbm (int): Received signal strength in dBm
        - snr_db (int): Signal to noise ratio or None for FSK
        - port (int): LoRaWAN frame port or None
        - data (bytes): Data received or None
        """
        if len(indication) < 13:
            raise ValueError('Receive message indication too small')
        if indication[0] != 0x49:
            raise ValueError('Not a receive message indication')

        success = (indication[2] == 0x00)
        msg_type = indication[3]
        multicast = (indication[4] == 0x01)
        data_rate = indication[5]
        rx_slot = indication[6]
        frame_pending = (indication[7] == 0x01)
        ack_received = (indication[8] == 0x01)
        rssi_dbm = int.from_bytes(indication[10:12], 'little', signed=True)
        snr = indication[12]
        if len(indication) > 12:
            port: Optional[int] = indication[12]
        else:
            port = None
        if len(indication) > 13 and indication[9] == 0x01:
            data: Optional[bytes] = indication[13:]
        else:
            data = None

        if msg_type > 3:
            raise ValueError('Illegal message type')
        if data_rate > 7:
            raise ValueError('Illegal data rate')
        if rx_slot > 2:
            raise ValueError('Illegal receive window slot')
        if port is not None and (port < 1 or port > 223):
            raise ValueError('Illegal port')

        return {
                'indication': 'rx_msg',
                'success': success,
                'message_type': msg_type,
                'multicast': multicast,
                'data_rate': data_rate,
                'slot': rx_slot,
                'frame_pending': frame_pending,
                'ack': ack_received,
                'rssi_dbm': rssi_dbm,
                'snr_db': snr,
                'port': port,
                'data': data
                }

    def get_parsed_indication(self, timeout_seconds: Optional[int]) -> Optional[Dict[str, Union[str, int, bool]]]:
        """ Get a indication as dictionary

        args:
        - timeout_seconds (int): Timeout in seconds or None

        Returns:
        - Dict with a parsed indication
        """

        indication = self.get_indication(timeout_seconds)

        if indication is None:
            return None

        if indication[0] == 0x41:
            return self.parse_join_indication(indication)

        if indication[0] == 0x47:
            return self.parse_tx_msg_confirmed_indication(indication)

        if indication[0] == 0x48:
            return self.parse_tx_msg_unconfirmed_indication(indication)

        if indication[0] == 0x49:
            return self.parse_rx_msg_indication(indication)

        raise RuntimeError('Unexpected indication 0x%02X' % (indication[0]))

    def reset(self):
        try:
            self._serial.transmit(b'\x30\x00')
            self._get_reply(0x30, 0, 0.25)
        finally:
            self._gpio.sleep()
            time.sleep(2)

        self._configure_frequencies()

    def factory_reset(self) -> bool:
        try:
            self._serial.transmit(b'\x31\x00')
            response = self._get_reply(0x31, 1, 1)
        finally:
            self._gpio.sleep()

        return response[2] == 0x00

    def eeprom_write(self, start_address: int, data: bytes) -> bool:
        if start_address > 0xFF:
            raise ValueError('Bad start address')
        if len(data) > 0xFE:
            raise ValueError('Data too long')
        if start_address + len(data) > 0xFF:
            raise ValueError('Data too long for start address')

        cmd = b'\x32' + bytes([len(data) + 1, start_address]) + data
        try:
            self._serial.transmit(cmd)
            response = self._get_reply(0x32, 1, 1)
        finally:
            self._gpio.sleep()

        return response[2] == 0x00

    def eeprom_read(self, start_address: int, num_bytes: int) -> Optional[bytes]:
        if start_address > 0xFF:
            raise ValueError('Bad start address')
        if start_address + num_bytes > 0x100:
            raise ValueError('Too many bytes requested')

        cmd = b'\x33\x02' + bytes([start_address, num_bytes])

        try:
            self._serial.transmit(cmd)
            response = self._get_reply(0x33, None, 1)
        finally:
            self._gpio.sleep()

        if response[1] != num_bytes + 1 or response[2] != 0x00:
            return None

        return response[3:]

    def get_fw_version(self) -> int:

        try:
            self._serial.transmit(b'\x34\x00')
            response = self._get_reply(0x34, 4, 0.25)
        finally:
            self._gpio.sleep()

        return int.from_bytes(response[2:6], 'little', signed=False)

    def get_serial_no(self) -> int:
        try:
            self._serial.transmit(b'\x35\x00')
            response = self._get_reply(0x35, 4, 0.25)
        finally:
            self._gpio.sleep()

        return int.from_bytes(response[2:6], 'little', signed=False)

    def get_deveui(self) -> bytes:
        try:
            self._serial.transmit(b'\x36\x00')
            response = self._get_reply(0x36, 8, 0.25)
        finally:
            self._gpio.sleep()

        eui = response[2:10]

        return eui[::-1]

    def join(self, mode: int) -> int:
        """ Join the LoRaWAN network

        args:
        - mode: 0: ABP
                1: OTAA

        Return:
        - int: 0: Success
               1: Invalid parameter
               2: Busy
        """

        if mode < 0 or mode > 1:
            raise ValueError('Bad mode')

        cmd = b'\x40\x01' + bytes([mode])
        try:
            self._serial.transmit(cmd)
            response = self._get_reply(0x40, 1, 0.25)
        finally:
            self._gpio.sleep()

        return response[2]

    def get_activation_status(self) -> int:
        """ Get activation status

        Returns:
        - int: 0: Not activated
               1: Joining
               2: Joined
               3: MAC error
        """

        try:
            self._serial.transmit(b'\x42\x00')
            response = self._get_reply(0x42, 1, 0.25)
        finally:
            self._gpio.sleep()

        return response[2]

    def set_app_key(self, app_key: bytes) -> None:
        """ Write the application key needed for OTAA to eeprom

        Args:
        - app_key (bytes): 16 bytes application key
        """

        if len(app_key) != 16:
            raise ValueError('app key must be exactly 16 bytes long')

        cmd = b'\x43\x10' + app_key[::-1]
        try:
            self._serial.transmit(cmd)
            self._get_reply(0x43, 0, 2)
        finally:
            self._gpio.sleep()

        return

    def set_app_session_key(self, app_session_key: bytes) -> None:
        """ Write the application session key needed for APB to eeprom

        Args:
        - app_session_key (bytes): 16 bytes application session key
        """

        if len(app_session_key) != 16:
            raise ValueError('app session key must be exactly 16 bytes long')

        cmd = b'\x44\x10' + app_session_key[::-1]
        try:
            self._serial.transmit(cmd)
            self._get_reply(0x44, 0, 2)
        finally:
            self._gpio.sleep()

        return

    def set_nwk_session_key(self, network_session_key: bytes) -> None:
        """ Write the network session key needed for APB to eeprom

        args:
        - network_session_key (bytes): 16 bytes network session key
        """

        if len(network_session_key) != 16:
            raise ValueError('network session key must be exactly 16 bytes long')

        cmd = b'\x45\x10' + network_session_key[::1]
        try:
            self._serial.transmit(cmd)
            self._get_reply(0x45, 0, 2)
        finally:
            self._gpio.sleep()

        return

    def tx_msg(self, data: bytes, fport: int, confirmed: bool) -> int:
        """ Transmit a message

        args:
        - data (bytes): data to be transmitted
        - fport (int): LoRaWAN frame port (1-223)
        - confirmed (bool): Request confirmation

        returns:
        - status (int): 0: success
                        1: device busy
                        2: device not activated
                        3: channel blocked by duty cycle
                        4: port number not supported
                        5: length not supported
                        6: end node in silent state
                        7: error
        """

        if fport < 1 or fport > 223:
            raise ValueError('Bad fport')
        if len(data) > 209:
            raise ValueError('data length too big')
        if len(data) == 0:
            raise ValueError('nothing to transmit')

        if confirmed:
            options = 1
        else:
            options = 0

        cmd = b'\x46' + bytes([len(data) + 2, options, fport]) + data
        try:
            self._serial.transmit(cmd)
            response = self._get_reply(0x46, 1, 0.25)
        finally:
            self._gpio.sleep()

        return response[2]

    def get_session_status(self) -> int:
        """ Get session status

        Returns:
        - status (int): 0: Idle
                        1: Busy
                        2: Device not activated
                        3: Delayed (LoRa session paused due to duty-cycle)
        """

        try:
            self._serial.transmit(b'\x4a\x00')
            response = self._get_reply(0x4a, 1, 0.25)
        finally:
            self._gpio.sleep()

        return response[2]

    def set_next_dr(self, data_rate: int) -> bool:
        """ Set the data rate for the next transmission

        args:
        - data_rate (int): 0: SF12
                           1: SF11
                           2: SF10
                           3: SF9
                           4: SF8
                           5: SF7
                           6: SF7 with 250kHz bandwidth
                           7: FSK

        returns:
        - status (int): 0: success
                        x: any other value means error
        """
        if data_rate < 0 or data_rate > 7:
            raise ValueError('Bad data rate')

        cmd = b'\x4b\x01' + bytes([data_rate])
        try:
            self._serial.transmit(cmd)
            response = self._get_reply(0x4b, 1, 0.25)
        finally:
            self._gpio.sleep()

        return (response[2] == 0x00)

    def set_battery_level(self, battery_level: int) -> None:
        """ Set battery level transmitted to network as part of the MAC layer

        args:
        - battery_level: 0: powered by main
                         1-254: battery level, 1 minimum, 254 maximum
                         255: battery level cannot be measured
        """

        if battery_level < 0 or battery_level > 255:
            raise ValueError('Bad battery level')

        cmd = b'\x50\x01' + bytes([battery_level])
        try:
            self._serial.transmit(cmd)
            self._get_reply(0x50, 0, 0.25)
        finally:
            self._gpio.sleep()

        return

    def get_battery_level(self) -> int:
        """ Get the battery level previously set

        returns:
        - battery level (int): 0: powered by main
                               1-254; battery level, 1 minimum, 254 maximum
                               255: battery level cannot be measured
        """

        try:
            self._serial.transmit(b'\x51\x00')
            response = self._get_reply(0x51, 1, 0.25)
        finally:
            self._gpio.sleep()

        return response[2]

    def set_uplink_cnt(self, uplink_counter: int) -> None:
        """ Set LoRaWAN uplink counter

        args:
        - uplink_counter (int): Uplink counter, 32bit unsigned
        """

        if uplink_counter < 0 or uplink_counter > 4294967295:
            raise ValueError('Bad uplink counter')

        cmd = b'\x52\x04' + uplink_counter.to_bytes(4, 'little', signed=False)

        try:
            self._serial.transmit(cmd)
            self._get_reply(0x52, 0, 0.25)
        finally:
            self._gpio.sleep()

        return

    def get_uplink_cnt(self) -> int:
        """ Get uplink counter from RAM

        returns:
        - uplink_counter (int): Uplink counter from RAM
        """
        try:
            self._serial.transmit(b'\x53\x00')
            response = self._get_reply(0x53, 4, 0.25)
        finally:
            self._gpio.sleep()

        return int.from_bytes(response[2:6], 'little', signed=False)

    def set_downlink_cnt(self, downlink_counter: int) -> None:
        """ Set downlink counter in RAM

        args:
        - downlink_counter (int): Value of downlink counter to set
        """

        if downlink_counter < 0 or downlink_counter > 4294967295:
            raise ValueError('Bad downlink counter value')

        cmd = b'\x54\x04' + downlink_counter.to_bytes(4, 'little', signed=False)

        try:
            self._serial.transmit(cmd)
            self._get_reply(0x54, 0, 0.25)
        finally:
            self._gpio.sleep()

        return

    def get_downlink_cnt(self) -> int:
        """ Get downlink counter from RAM

        returns:
        - downlink_counter (int): Downlink counter from RAM
        """

        try:
            self._serial.transmit(b'\x55\x00')
            response = self._get_reply(0x55, 4, 0.25)
        finally:
            self._gpio.sleep()

        return int.from_bytes(response[2:6], 'little', signed=False)

    def set_ch_parameters(self, channel: int, frequency: int, min_data_rate: int, max_data_rate: int, enabled: bool) -> int:
        """ Set channel parameters

        args:
        - channel (int): Channel index, from 3-15
        - frequency (int): Frequency in hertz, from 863.125 MHz to 869.875 MHz
        - min_data_rate (int): Minimum data rate 0-7, 0=SF12/125Khz, 5=SF7/125kHz, 6=SF7/250kHz, 7=FSK/50kHz
        - max_data_rate (int): Maximum data rate
        - enabled (bool): Channel enabled?

        returns:
        - status (int): 0x00: Success
                        0xF1: channel out of range
                        0xF2: data rate out of range
                        0xF3: data rate and frequency out of range
                        0xF4: MAC busy
        """

        if channel < 3 or channel > 15:
            raise ValueError('Bad channel')

        if min_data_rate > max_data_rate:
            raise ValueError('Minimum data rate higher than maximum data rate')

        if min_data_rate < 6:
            bandwidth = 125000
        elif min_data_rate == 6:
            bandwidth = 250000
        elif min_data_rate == 7:
            bandwidth = 50000
        else:
            raise ValueError('Bad minimal data rate')

        if max_data_rate < 0 or max_data_rate > 7:
            raise ValueError('Bad maximal data rate')
        if max_data_rate == 6 and bandwidth < 250000:
            bandwidth = 250000

        if frequency - bandwidth / 2 < 863000000:
            raise ValueError('Frequency too low')
        if frequency + bandwidth / 2 > 869000000:
            raise ValueError('Frequency too high')

        data_rate = min_data_rate | (max_data_rate << 4)

        if enabled:
            enabled_parm = b'\x01'
        else:
            enabled_parm = b'\x00'

        cmd = b'\x57\x07' + bytes([channel]) + frequency.to_bytes(4, 'little', signed=False) + bytes([data_rate]) + enabled_parm

        try:
            self._serial.transmit(cmd)
            response = self._get_reply(0x57, 1, 0.25)
        finally:
            self._gpio.sleep()

        return response[2]

    def get_ch_parameters(self, channel: int) -> Tuple[int, int, int, bool]:
        """ Get channel parameters

        args:
        - channel (int): Channel index, 0-15

        returns:
        - frequency (int): Frequency in hertz
        - min_data_rate (int): Minimal data rate
        - max_data_rate (int): Maximal data rate
        - enabled (bool): Channel enabled
        """

        if channel < 0 or channel > 15:
            raise ValueError('Bad channel')

        cmd = b'\x58\x01' + bytes([channel])

        try:
            self._serial.transmit(cmd)
            response = self._get_reply(0x58, 6, 0.25)
        finally:
            self._gpio.sleep()

        frequency = int.from_bytes(response[2:6], 'little', signed=False)
        min_data_rate = response[6] & 0x0F
        max_data_rate = response[6] >> 4
        enabled = (response[7] == 0x01)

        return (frequency, min_data_rate, max_data_rate, enabled)
