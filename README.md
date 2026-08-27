# EN|[中文](README_zh.md)
# Web-scrcpy
allowing you to control your Android device from a web browser. Web server for scrcpy.
New features added in the revision:
1. Add audio support (copied from https://github.com/volneiklehm/web-scrcpy)
2. Add the function of restarting the scrcpy service (for example, due to USB instability leading to disconnection or replacement of the controlled phone)
3. Support opening multiple browsers to browse or control Android phones simultaneously
4. Add login authentication (default username "scrcpy", default password "4qw!u"). Only after passing the authentication can you browse and control the phone.

## Effect Demonstration
![Effect](./animation.gif)

## Installation Guide
1. Install adb, ensure that adb is in the path environment variable, and the Android device is connected and the debugging mode is enabled.
2. Install Python 3.7+ and pip.
3. Install the source code:
   - Clone the project repository: `git clone https://github.com/yuleniwo/web-scrcpy.git`
   - Navigate to the project directory: `cd web-scrcpy`
   - Install the dependencies: `pip3 install -r requirements.txt`
   - Start running: `python3 app.py`
4. Open a browser and visit http://localhost:5000, then you can see the control interface of scrcpy.

## Contributing
1. Fork the repo.
2. Create a new branch: git checkout -b your - branch - name
3. Make changes and submit a Pull Request.

## License
Apache License 2.0.

## Contact
Original author: 1228504957@qq.com\
Modified version: xzm2@qq.com