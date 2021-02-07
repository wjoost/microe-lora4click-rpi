#!/usr/bin/python3
#
# Get informations from module

from lora4click import MipotGpio, MipotSerial, MipotCmd


def show_hex(msg, data: bytes) -> None:
    print(msg, end='')
    for v in data:
        print(' %02X' % (v), end='')
    print('')

    return


def main() -> int:

    # Init
    gpio = MipotGpio()
    serial = MipotSerial(gpio)
    cmd = MipotCmd(gpio, serial)

    # Get version
    module_version = cmd.get_fw_version()
    print('Module version: %x' % (module_version))

    # Get serial number
    serial_number = cmd.get_serial_no()
    print('Module serial: %d' % (serial_number))

    # Get device EUI
    device_eui = cmd.get_deveui()
    show_hex('Device EUI:', device_eui)

    # Get AppEUI / Join EUI
    join_eui = cmd.eeprom_read(0x08, 8)[::-1]
    show_hex('Join EUI:', join_eui)

    # Get Class
    lora_class = cmd.eeprom_read(0x20, 1)
    if lora_class[0] == 0:
        print('Class: A')
    elif lora_class[0] == 1:
        print('Class C')
    else:
        print('Unknown class: 0x%02X' % (lora_class[0]))

    # ADR active?
    adr = cmd.eeprom_read(0x23, 1)
    if adr[0] == 0:
        print('ADR disabled')
    else:
        print('ADR enabled')

    # Unconfirmed transmit message repeat setting
    tx_repeat = cmd.eeprom_read(0x25, 1)
    print('Unconfirmed message repeat: %d' % (tx_repeat[0]))

    # Public network?
    public_net = cmd.eeprom_read(0x2E, 1)
    if public_net[0] == 0:
        print('Network: private')
    elif public_net[0] == 1:
        print('Network: public')
    else:
        print('Unknown network config: 0x%02X' % (public_net[0]))

    return 0


if __name__ == "__main__":
    exit(main())
