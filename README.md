# microe-lora4click-rpi

Python sample code for a [Microe LoRa Click](https://www.mikroe.com/lora-rf-click)
board mounted on a Raspberry PI using the [Microe Pi 3 Click shield](https://www.mikroe.com/pi-3-click-shield).

The click board uses an [Mipot 32001353 LoRaWAN 868MHz TRX](https://www.mipot.com/en/rf-wireless-products/lorawan-868mhz-trx-32001353/)
module.

## send_temperature.py
Send the SOC temperature in Cayenne LPP format every five minutes via LoRaWAN.

## configure.py

Configures the device. The application EUI and key has to be specified.

## get_info.py

Displays some informations like the device EUI.

## lora4click.py

Abstracts the communication with the LoRa board.
