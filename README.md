# switchbot-flask

A small python application to control a Switchbot throught bluetooth on a Raspberry pi zero.


This application is used to control my heating system. There are commands to manually turn on or off heaters.
There is also a "scheduler" mode. This mode will check 3 parameters to choose to turn on/off heaters:
 - day of the week and time of the day
 - current temperature in my house
 - detection of my phone on my wifi network or bluetooth


## 🚦 Pre-requisite

OpenWonderLabs/python-host:
Read https://github.com/OpenWonderLabs/python-host
```
sudo apt install python3-bluez
git clone https://github.com/OpenWonderLabs/python-host.git
```

## 🏗️ Install
```
pip3 install -r requirements.txt
```

## 🚀 Run
```
python3 switchbot_flask.py
```