# Web-scrcpy
通过web远程控制Android手机\
改版增加功能：
1. 增加音频支持(抄https://github.com/volneiklehm/web-scrcpy)
2. 增加重启scrcpy服务的功能(例如usb不稳定导致断开或者跟换被控手机)
3. 支持打开多个浏览器同时浏览或控制安卓手机
4. 增加登录鉴权(默认用户名"scrcpy"，默认密码"4qw!u")，鉴权通过后方可浏览、控制手机。

## 效果展示
![效果展示](./animation.gif)

## 安装指南
1. 安装adb，确保adb在path环境变量中，并且Android设备已连接并启用调试模式
2. 安装Python 3.7+和pip
3. 安装源码：
   - 克隆项目仓库：`git clone https://github.com/yuleniwo/web-scrcpy.git`
   - 进入项目目录：`cd web-scrcpy`
   - 安装依赖：`pip3 install -r requirements.txt`
   - 启动运行：`python3 app.py`
4. 打开一个浏览器，访问`http://localhost:5000`，即可看到scrcpy的控制界面

## 参与方式
1. Fork 项目.
2. 创建一个新分析: git checkout -b your - branch - name
3. 提交Pull Request.

## 开源协议
Apache License 2.0.

## 联系方式
原作者：1228504957@qq.com\
修改版：xzm2@qq.com