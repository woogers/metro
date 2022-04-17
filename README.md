# metro

Code powering a transit display running on a two LED matrices and a Raspberry Pi.

Need a developer API key for Metro's API ([from here](https://developer.wmata.com/)) to run the code.

## Installation

Used Adafruit's RGB Matrix installer script to get [hzeller's RGB Matrix Library](https://github.com/hzeller/rpi-rgb-led-matrix/) up and running on the Raspberry Pi:

```curl https://raw.githubusercontent.com/adafruit/Raspberry-Pi-Installer-Scripts/master/rgb-matrix.sh >rgb-matrix.sh
sudo bash rgb-matrix.sh
```

## Usage

```python3 metro/driver.py```

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

[GPL v3](https://choosealicense.com/licenses/gpl-3.0/)
